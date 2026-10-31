import { db, nextId } from "@/mock/db"
import { ApiError, callApi, requireMember, serverNote } from "@/mock/api/core"
import { FULL_EXTRACT, PARTIAL_EXTRACT, type DocumentExtract } from "@/mock/seed/documentExtracts"
import type { SortDirection } from "@/mock/api/caseApi"
import type {
  AgeGroup,
  Gender,
  Member,
  ResourceStatus,
  SupportAgeGroup,
  SupportGender,
  WelfareResource,
} from "@/types/domain"
import { AGE_GROUPS } from "@/utils/age"
import { isValidDateString, todayString } from "@/utils/datetime"

// 3. RESOURCE 복지자원 관리
// - 3.1.2 복지자원 목록 조회 (3.1.1 검색 필터 포함)
// - 3.2.1 복지자원 상세 조회, 3.2.2 복지자원 수정·삭제
// - 3.3.1 복지자원 등록, 3.3.2 문서 기반 자동 입력

/** 없는 자원·삭제한 자원 */
export const RESOURCE_NOT_FOUND_MESSAGE = "복지자원을 찾을 수 없습니다."
/** 로그인한 회원이 담당자가 아닌 자원 (담당자가 탈퇴한 자원 포함) */
export const RESOURCE_MANAGER_ONLY_MESSAGE = "담당자만 삭제할 수 있습니다."
export const RESOURCE_EDIT_MANAGER_ONLY_MESSAGE = "담당자만 수정할 수 있습니다."
export const DOCUMENT_UNREADABLE_MESSAGE = "문서에서 내용을 읽지 못했습니다."

/** 글자 수 제한 (E9-A, 명세 없음) */
export const RESOURCE_TEXT_LIMITS = {
  resourceName: 50,
  operatingOrgName: 50,
  target: 100,
  applyMethod: 200,
  supportContent: 1000,
} as const

/** 자동 입력에 올릴 수 있는 파일 크기 (E4-B: 20MB, 명세 없음) */
export const DOCUMENT_MAX_BYTES = 20 * 1024 * 1024

/** 열 제목 정렬 (W6-B, F1-A): 자원명, 정원, 운영 기간(종료일), 이용자 부담금 */
export type ResourceSortKey = "resourceName" | "capacity" | "periodEnd" | "fee"

export type ResourceSearchRequest = {
  /** 지역: 아래 단계를 비우면 위 단계 전체 (모두 비우면 전체 지역) */
  sidoCode: string | null
  sigunguCode: string | null
  dongCode: string | null
  /** 지원 연령에 이 연령대가 있거나 '무관'인 자원 */
  ageGroup: AgeGroup | "전체"
  /** 지원 성별이 같거나 '무관'인 자원 */
  gender: Gender | "전체"
  /** 정원 범위 (비우면 제한 없음, 양 끝 포함) */
  capacityMin: number | null
  capacityMax: number | null
  /** 담당자 이름의 일부 */
  managerName: string
  sort: ResourceSortKey
  direction: SortDirection
  /** 1부터 시작 */
  page: number
  size: number
}

export type ResourceListItem = {
  resourceId: number
  resourceName: string
  operatingOrgName: string
  target: string
  capacity: number
  sigunguName: string
  /** 시군구 전체 자원이면 null */
  dongName: string | null
  periodStart: string
  periodEnd: string
  /** 원 단위 금액 (0이면 무료) */
  fee: number
  status: ResourceStatus
}

export type ResourceSearchResponse = {
  totalCount: number
  page: number
  size: number
  totalPages: number
  items: ResourceListItem[]
}

/** 담당자가 고른 상태 + 운영 종료일이 지났으면 '종료' (3.3.1) */
export function effectiveStatus(resource: WelfareResource, today = todayString()): ResourceStatus {
  return resource.status === "종료" || resource.periodEnd < today ? "종료" : "진행 중"
}

function regionNames(resource: WelfareResource) {
  const sigungu = db.sigungus.find((item) => item.sigunguCode === resource.sigunguCode)
  const dong = resource.dongCode ? db.dongs.find((item) => item.dongCode === resource.dongCode) : null
  return { sidoCode: sigungu?.sidoCode ?? "", sigunguName: sigungu?.sigunguName ?? "", dongName: dong?.dongName ?? null }
}

/** 목록 한 줄 (3.1.2 복지자원 목록, 5.2.1 담당 복지자원 목록 공통) */
export function toResourceListItem(resource: WelfareResource, today = todayString()): ResourceListItem {
  const region = regionNames(resource)
  return {
    resourceId: resource.resourceId,
    resourceName: resource.resourceName,
    operatingOrgName: resource.operatingOrgName,
    target: resource.target,
    capacity: resource.capacity,
    sigunguName: region.sigunguName,
    dongName: region.dongName,
    periodStart: resource.periodStart,
    periodEnd: resource.periodEnd,
    fee: resource.fee,
    status: effectiveStatus(resource, today),
  }
}

/** 지역 조건 (W2-B): 행정동을 고르면 그 행정동 자원 + 같은 시군구 전체 자원 */
function matchesRegion(resource: WelfareResource, sidoCode: string, input: ResourceSearchRequest): boolean {
  if (input.dongCode) {
    return (
      resource.dongCode === input.dongCode ||
      (resource.dongCode === null && resource.sigunguCode === input.dongCode.slice(0, 5))
    )
  }
  if (input.sigunguCode) return resource.sigunguCode === input.sigunguCode
  if (input.sidoCode) return sidoCode === input.sidoCode
  return true
}

function validateRange(min: number | null, max: number | null) {
  for (const value of [min, max]) {
    if (value !== null && (!Number.isInteger(value) || value < 0)) throw new ApiError("정원은 0 이상의 숫자로 입력하세요.")
  }
  if (min !== null && max !== null && min > max) throw new ApiError("최소 정원이 최대 정원보다 큽니다.")
}

export type ResourceManager = {
  memberId: number
  name: string
  title: string | null
  orgName: string
}

export type ResourceDetail = {
  resourceId: number
  resourceName: string
  operatingOrgName: string
  target: string
  supportAgeGroups: SupportAgeGroup[]
  supportGender: SupportGender
  sidoCode: string
  sidoName: string
  sigunguCode: string
  sigunguName: string
  /** 시군구 전체 자원이면 null */
  dongCode: string | null
  dongName: string | null
  periodStart: string
  periodEnd: string
  /** 원 단위 금액 (0이면 무료) */
  fee: number
  status: ResourceStatus
  /** 운영 종료일이 지나 자동으로 '종료'가 됐는지 (담당자가 고른 상태는 진행 중) */
  autoEnded: boolean
  capacity: number
  actualParticipants: number | null
  supportContent: string | null
  applyMethod: string | null
  /** 담당자. 탈퇴했으면 null ('퇴사자'로 표시) */
  manager: ResourceManager | null
  /** 로그인한 회원이 수정·삭제할 수 있는지 (V5-A: 담당자 본인만) */
  editable: boolean
}

/** 삭제하지 않은 자원 (없거나 삭제했으면 찾을 수 없음) */
function findLiveResource(resourceId: number): WelfareResource {
  const resource = db.resources.find((item) => item.resourceId === resourceId)
  if (!resource || resource.deletedAt !== null) {
    if (resource) serverNote(`삭제한 자원(삭제일 ${resource.deletedAt})이라 없는 자원과 같은 실패로 응답함`)
    throw new ApiError(RESOURCE_NOT_FOUND_MESSAGE)
  }
  return resource
}

/** 담당자 (탈퇴했으면 null) */
function activeManagerOf(resource: WelfareResource): Member | null {
  const manager = db.members.find((item) => item.memberId === resource.managerMemberId)
  return manager && manager.withdrawnAt === null ? manager : null
}

/** 로그인한 회원이 수정·삭제할 수 있는지: 담당자 본인이고, 담당자가 탈퇴하지 않음 (3.2.2, 5.1.4) */
function canEdit(member: Member, resource: WelfareResource): boolean {
  return activeManagerOf(resource)?.memberId === member.memberId
}

/** 3.3.1 등록·3.2.2 수정 요청 (등록 양식의 항목) */
export type ResourceInput = {
  resourceName: string
  operatingOrgName: string
  target: string
  supportAgeGroups: SupportAgeGroup[]
  supportGender: SupportGender
  /** 지역: 시군구(필수) + 행정동(null이면 시군구 전체) */
  sigunguCode: string
  dongCode: string | null
  periodStart: string
  periodEnd: string
  /** 원 단위, 0이면 무료 */
  fee: number
  status: ResourceStatus
  /** 같은 기관 회원 한 명 */
  managerMemberId: number
  capacity: number
  actualParticipants: number | null
  supportContent: string | null
  applyMethod: string | null
}

/** 문서에서 찾지 못하면 알려 주는 필수 항목 (지역·운영 기간은 묶어서) */
const REQUIRED_EXTRACT_FIELDS = [
  "resourceName",
  "operatingOrgName",
  "target",
  "supportAgeGroups",
  "supportGender",
  "region",
  "period",
  "fee",
  "capacity",
] as const

const isCount = (value: number, min: number) => Number.isInteger(value) && value >= min

/** 서버에서도 하는 입력 확인 (화면에서 먼저 확인하므로 보통은 여기까지 오지 않는다) */
function validateResourceInput(orgId: number, input: ResourceInput): ResourceInput {
  // 항목 이름이 모두 받침으로 끝나 '을'·'은'을 붙인다
  const text = (value: string, label: string, limit: number) => {
    const trimmed = value.trim()
    if (!trimmed) throw new ApiError(`${label}을 입력하세요.`)
    if (trimmed.length > limit) throw new ApiError(`${label}은 ${limit}자 이내로 입력하세요.`)
    return trimmed
  }
  const optionalText = (value: string | null, label: string, limit: number) => {
    const trimmed = value?.trim() ?? ""
    if (trimmed.length > limit) throw new ApiError(`${label}은 ${limit}자 이내로 입력하세요.`)
    return trimmed || null
  }
  const resourceName = text(input.resourceName, "자원명", RESOURCE_TEXT_LIMITS.resourceName)
  const operatingOrgName = text(input.operatingOrgName, "수행·담당 기관", RESOURCE_TEXT_LIMITS.operatingOrgName)
  const target = text(input.target, "지원 대상", RESOURCE_TEXT_LIMITS.target)
  const ages = [...new Set(input.supportAgeGroups)]
  const anyAge = ages.includes("무관")
  if (ages.length === 0 || (anyAge && ages.length > 1) || ages.some((age) => age !== "무관" && !AGE_GROUPS.includes(age))) {
    throw new ApiError("지원 연령은 연령대를 하나 이상 고르거나 '무관'만 고르세요.")
  }
  if (!["남", "여", "무관"].includes(input.supportGender)) throw new ApiError("지원 성별을 고르세요.")
  if (!db.sigungus.some((item) => item.sigunguCode === input.sigunguCode)) throw new ApiError("지역을 시군구까지 선택하세요.")
  if (input.dongCode !== null && !db.dongs.some((item) => item.dongCode === input.dongCode && item.sigunguCode === input.sigunguCode)) {
    throw new ApiError("읍면동이 선택한 시군구에 없습니다.")
  }
  if (!isValidDateString(input.periodStart) || !isValidDateString(input.periodEnd)) throw new ApiError("운영 기간이 올바른 날짜가 아닙니다.")
  if (input.periodStart > input.periodEnd) throw new ApiError("운영 시작일이 종료일보다 늦습니다.")
  if (!isCount(input.fee, 0)) throw new ApiError("이용자 부담금은 0 이상의 숫자로 입력하세요.")
  if (input.status !== "진행 중" && input.status !== "종료") throw new ApiError("상태를 고르세요.")
  if (!isCount(input.capacity, 1)) throw new ApiError("정원은 1 이상의 숫자로 입력하세요.")
  if (input.actualParticipants !== null && !isCount(input.actualParticipants, 0)) {
    throw new ApiError("실제 참여자 수는 0 이상의 숫자로 입력하세요.")
  }
  const manager = db.members.find((item) => item.memberId === input.managerMemberId)
  if (!manager || manager.orgId !== orgId || manager.withdrawnAt !== null) {
    throw new ApiError("담당자는 같은 기관의 회원 중에서만 지정할 수 있습니다.")
  }
  return {
    ...input,
    resourceName,
    operatingOrgName,
    target,
    supportAgeGroups: anyAge ? ["무관"] : AGE_GROUPS.filter((age) => ages.includes(age)),
    supportContent: optionalText(input.supportContent, "지원 내용", RESOURCE_TEXT_LIMITS.supportContent),
    applyMethod: optionalText(input.applyMethod, "신청 방법", RESOURCE_TEXT_LIMITS.applyMethod),
  }
}

/** 등록·수정 공통 서버 메모: 담당자를 다른 사람으로 정했는지, 종료일이 지났는지, 정원 초과 */
function noteManagerAndStatus(member: Member, value: ResourceInput) {
  if (value.managerMemberId !== member.memberId) {
    const manager = db.members.find((item) => item.memberId === value.managerMemberId)
    serverNote(`담당자를 ${manager?.name}(으)로 지정함. 이제 저장한 회원(${member.name})은 수정·삭제할 수 없음`)
  }
  if (value.status === "진행 중" && value.periodEnd < todayString()) {
    serverNote("운영 종료일이 지나 저장한 상태는 '진행 중'이지만 조회할 때 '종료'로 돌려줌")
  }
  if (value.actualParticipants !== null && value.actualParticipants > value.capacity) {
    serverNote("실제 참여자 수가 정원보다 많지만 저장함 (E7-B: 지금 참여 중인 인원, 정원 초과 가능)")
  }
}

export const resourceApi = {
  /**
   * 3.1.2 복지자원 목록 조회 (3.1.1 검색 필터 포함).
   * 모든 기관의 자원을 돌려준다 (W1-A). 진행 중 자원을 먼저, 그 안에서 고른 정렬 순서.
   */
  searchResources(request: ResourceSearchRequest) {
    return callApi(
      { featureId: "3.1.2", featureName: "복지자원 목록 조회" },
      request,
      (input): ResourceSearchResponse => {
        requireMember()
        validateRange(input.capacityMin, input.capacityMax)
        const today = todayString()
        const managerName = input.managerName.trim()

        serverNote("삭제한 자원(soft delete)은 빼고, 모든 기관의 자원에서 찾음")
        if (input.dongCode) serverNote("행정동 자원과 같은 시군구의 '시군구 전체' 자원을 함께 찾음")
        if (input.ageGroup !== "전체") serverNote(`지원 연령에 '${input.ageGroup}'이 있거나 '무관'인 자원을 함께 찾음`)
        if (input.gender !== "전체") serverNote(`지원 성별이 '${input.gender}' 또는 '무관'인 자원을 찾음`)
        if (managerName) {
          serverNote(`담당자 이름에 '${managerName}' 글자가 들어간 자원 (탈퇴한 담당자는 '퇴사자'로 표시하므로 이름으로 찾지 않음)`)
        }

        const rows = db.resources
          .filter((resource) => resource.deletedAt === null)
          .map((resource) => ({ resource, region: regionNames(resource), status: effectiveStatus(resource, today) }))
          .filter(({ resource, region }) => {
            if (!matchesRegion(resource, region.sidoCode, input)) return false
            if (
              input.ageGroup !== "전체" &&
              !resource.supportAgeGroups.includes(input.ageGroup) &&
              !resource.supportAgeGroups.includes("무관")
            ) {
              return false
            }
            if (input.gender !== "전체" && resource.supportGender !== input.gender && resource.supportGender !== "무관") {
              return false
            }
            if (input.capacityMin !== null && resource.capacity < input.capacityMin) return false
            if (input.capacityMax !== null && resource.capacity > input.capacityMax) return false
            if (managerName) {
              const manager = db.members.find((item) => item.memberId === resource.managerMemberId)
              if (!manager || manager.withdrawnAt !== null || !manager.name.includes(managerName)) return false
            }
            return true
          })

        const autoEnded = rows.filter(({ resource, status }) => status === "종료" && resource.status !== "종료").length
        if (autoEnded > 0) serverNote(`운영 종료일이 오늘(${today})보다 앞인 ${autoEnded}개는 상태를 '종료'로 돌려줌`)

        const sign = input.direction === "asc" ? 1 : -1
        const compare = (a: WelfareResource, b: WelfareResource): number => {
          switch (input.sort) {
            case "resourceName":
              return a.resourceName.localeCompare(b.resourceName, "ko")
            case "capacity":
              return a.capacity - b.capacity
            case "periodEnd":
              return a.periodEnd.localeCompare(b.periodEnd)
            case "fee":
              return a.fee - b.fee
          }
        }
        rows.sort(
          (a, b) =>
            // 진행 중 자원을 항상 먼저 (W6-B)
            Number(a.status === "종료") - Number(b.status === "종료") ||
            compare(a.resource, b.resource) * sign ||
            a.resource.periodEnd.localeCompare(b.resource.periodEnd) ||
            a.resource.resourceId - b.resource.resourceId,
        )
        serverNote(
          `진행 중 자원을 먼저, 그 안에서 ${{ resourceName: "자원명", capacity: "정원", periodEnd: "운영 종료일", fee: "이용자 부담금" }[input.sort]} ${input.direction === "asc" ? "오름차순" : "내림차순"}`,
        )

        const size = Math.max(1, input.size)
        const totalCount = rows.length
        const totalPages = Math.max(1, Math.ceil(totalCount / size))
        const page = Math.min(Math.max(1, input.page), totalPages)
        const items = rows.slice((page - 1) * size, page * size).map(({ resource }) => toResourceListItem(resource, today))
        return { totalCount, page, size, totalPages, items }
      },
    )
  },
  /**
   * 3.2.1 복지자원 상세 조회. 모든 기관 회원이 볼 수 있다 (W1-A).
   * 수정·삭제 가능 여부는 서버가 정해 함께 돌려준다 (V5-A).
   */
  getResource(request: { resourceId: number }) {
    return callApi(
      { featureId: "3.2.1", featureName: "복지자원 상세 조회" },
      request,
      ({ resourceId }): ResourceDetail => {
        const member = requireMember()
        const resource = findLiveResource(resourceId)
        const sigungu = db.sigungus.find((item) => item.sigunguCode === resource.sigunguCode)
        const sido = db.sidos.find((item) => item.sidoCode === sigungu?.sidoCode)
        const dong = resource.dongCode ? db.dongs.find((item) => item.dongCode === resource.dongCode) : null
        const manager = activeManagerOf(resource)
        const status = effectiveStatus(resource)
        const autoEnded = status === "종료" && resource.status !== "종료"
        const editable = canEdit(member, resource)

        if (!manager) serverNote("담당자가 탈퇴해 담당자를 null('퇴사자')로 돌려주고, 아무도 수정·삭제할 수 없음 (5.1.4)")
        else if (editable) serverNote(`로그인한 회원(${member.name})이 담당자라 수정·삭제 가능`)
        else serverNote(`로그인한 회원(${member.name})이 담당자(${manager.name})가 아니라 수정·삭제 불가`)
        if (autoEnded) serverNote(`운영 종료일(${resource.periodEnd})이 지나 상태를 '종료'로 돌려줌`)

        return {
          resourceId: resource.resourceId,
          resourceName: resource.resourceName,
          operatingOrgName: resource.operatingOrgName,
          target: resource.target,
          supportAgeGroups: resource.supportAgeGroups,
          supportGender: resource.supportGender,
          sidoCode: sido?.sidoCode ?? "",
          sidoName: sido?.sidoName ?? "",
          sigunguCode: resource.sigunguCode,
          sigunguName: sigungu?.sigunguName ?? "",
          dongCode: resource.dongCode,
          dongName: dong?.dongName ?? null,
          periodStart: resource.periodStart,
          periodEnd: resource.periodEnd,
          fee: resource.fee,
          status,
          autoEnded,
          capacity: resource.capacity,
          actualParticipants: resource.actualParticipants,
          supportContent: resource.supportContent,
          applyMethod: resource.applyMethod,
          manager: manager
            ? {
                memberId: manager.memberId,
                name: manager.name,
                title: manager.title,
                orgName: db.organizations.find((item) => item.orgId === manager.orgId)?.orgName ?? "",
              }
            : null,
          editable,
        }
      },
    )
  },

  /** 3.2.2 복지자원 삭제: 담당자만. soft delete로 목록·상세·추천에서 뺀다 */
  deleteResource(request: { resourceId: number }) {
    return callApi({ featureId: "3.2.2", featureName: "복지자원 삭제" }, request, ({ resourceId }) => {
      const member = requireMember()
      const resource = findLiveResource(resourceId)
      if (!canEdit(member, resource)) {
        const manager = activeManagerOf(resource)
        serverNote(
          manager
            ? `로그인한 회원(${member.name})이 이 자원의 담당자(${manager.name})가 아님`
            : "담당자가 탈퇴한 자원이라 아무도 삭제할 수 없음 (5.1.4)",
        )
        throw new ApiError(RESOURCE_MANAGER_ONLY_MESSAGE)
      }
      resource.deletedAt = todayString()
      serverNote(`삭제일(deletedAt)을 ${resource.deletedAt}로 기록함 (soft delete, 데이터는 남김)`)
      serverNote("삭제한 자원은 목록·상세 조회·AI 추천에서 뺌")
    })
  },
  /** 3.3.1 복지자원 등록: 등록한 회원의 기관을 등록 기관으로, 지정한 담당자(같은 기관 회원)로 저장 */
  createResource(request: ResourceInput) {
    return callApi(
      { featureId: "3.3.1", featureName: "복지자원 등록" },
      request,
      (input): { resourceId: number } => {
        const member = requireMember()
        const value = validateResourceInput(member.orgId, input)
        const resourceId = nextId(db.resources, (item) => item.resourceId)
        db.resources.push({
          ...value,
          resourceId,
          orgId: member.orgId,
          createdAt: todayString(),
          deletedAt: null,
        })
        const orgName = db.organizations.find((item) => item.orgId === member.orgId)?.orgName ?? ""
        serverNote(`등록한 회원의 기관(${orgName})을 등록 기관으로 저장함`)
        noteManagerAndStatus(member, value)
        return { resourceId }
      },
    )
  },

  /** 3.2.2 복지자원 수정: 담당자만. 등록 양식과 같은 항목을 모두 보낸다 */
  updateResource(request: { resourceId: number } & ResourceInput) {
    return callApi({ featureId: "3.2.2", featureName: "복지자원 수정" }, request, ({ resourceId, ...input }) => {
      const member = requireMember()
      const resource = findLiveResource(resourceId)
      if (!canEdit(member, resource)) {
        const manager = activeManagerOf(resource)
        serverNote(
          manager
            ? `로그인한 회원(${member.name})이 이 자원의 담당자(${manager.name})가 아님`
            : "담당자가 탈퇴한 자원이라 아무도 수정할 수 없음 (5.1.4)",
        )
        throw new ApiError(RESOURCE_EDIT_MANAGER_ONLY_MESSAGE)
      }
      const value = validateResourceInput(resource.orgId, input)
      Object.assign(resource, value)
      serverNote("등록 기관·등록일은 바꾸지 않음")
      noteManagerAndStatus(member, value)
    })
  },

  /**
   * 3.3.2 문서 기반 자동 입력: PDF를 받아 AI가 등록 양식 항목을 뽑아 돌려준다.
   * 실제로는 파일을 올린다(프로토타입 기록에는 파일 이름·크기만 남김). 원문은 저장하지 않는다.
   */
  extractFromDocument(request: { fileName: string; fileSize: number }) {
    return callApi(
      { featureId: "3.3.2", featureName: "문서 기반 자동 입력" },
      request,
      ({ fileName, fileSize }): { extracted: DocumentExtract; missingFields: string[] } => {
        requireMember()
        if (!fileName.toLowerCase().endsWith(".pdf")) throw new ApiError("PDF 파일만 올릴 수 있습니다.")
        if (fileSize > DOCUMENT_MAX_BYTES) throw new ApiError("20MB 이하 파일만 올릴 수 있습니다.")
        serverNote("업로드한 원문은 내용을 추출한 뒤 바로 삭제하고 저장하지 않음 (3.3.2)")
        if (fileName.includes("읽기불가")) {
          serverNote("글자를 읽을 수 없는 문서(스캔 이미지 등)라 항목을 뽑지 못함")
          throw new ApiError(DOCUMENT_UNREADABLE_MESSAGE)
        }
        const extracted = fileName.includes("일부") ? PARTIAL_EXTRACT : FULL_EXTRACT
        serverNote("AI가 문서에서 등록 양식 항목을 뽑아냄. 지역 이름은 시군구·행정동 코드로 바꿔 돌려줌")
        serverNote("담당자·상태·실제 참여자 수는 문서에서 뽑지 않음")
        const missingFields = REQUIRED_EXTRACT_FIELDS.filter((key) =>
          key === "region" ? extracted.sigunguCode === null : key === "period"
            ? extracted.periodStart === null || extracted.periodEnd === null
            : extracted[key] === null,
        )
        if (missingFields.length > 0) serverNote(`찾지 못한 필수 항목 ${missingFields.length}개는 null로 돌려줌`)
        return { extracted, missingFields }
      },
    )
  },
}
