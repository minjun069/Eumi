import { db } from "@/mock/db"
import { ApiError, callApi, findOrganizationName, requireMember, serverNote } from "@/mock/api/core"
import type { AgeGroup, CaseRecord, Gender, Member } from "@/types/domain"
import { ageGroupOf, ageOn } from "@/utils/age"
import { isValidDateString, todayString } from "@/utils/datetime"

// 4. CASE 사례자 관리 (복지관 내)
// - 4.1.2 사례자 목록 조회
// - 4.2.1 사례자 정보 조회·중복 확인·등록·수정·삭제 (상담 기록 4.2.2는 consultationApi.ts)

export type CaseSortKey =
  | "name"
  | "region"
  | "age"
  | "gender"
  | "firstRegisteredAt"
  | "lastRecordedAt"

export type SortDirection = "asc" | "desc"

export type CaseSearchRequest = {
  /** 지역: 아래 단계를 비우면 위 단계 전체 (모두 비우면 전체 지역) */
  sidoCode: string | null
  sigunguCode: string | null
  dongCode: string | null
  ageGroup: AgeGroup | "전체"
  gender: Gender | "전체"
  /** 최초 등록일 범위 (YYYY-MM-DD, 비우면 제한 없음) */
  registeredFrom: string | null
  registeredTo: string | null
  /** 최근 기록일 범위 (YYYY-MM-DD, 비우면 제한 없음) */
  recordedFrom: string | null
  recordedTo: string | null
  /** 이름 또는 관리번호의 일부 */
  keyword: string
  sort: CaseSortKey
  direction: SortDirection
  /** 1부터 시작 */
  page: number
  size: number
}

export type CaseListItem = {
  caseId: number
  managementNo: string
  name: string
  /** 만 나이 */
  age: number
  ageGroup: AgeGroup
  gender: Gender
  sidoName: string
  sigunguName: string
  dongName: string
  firstRegisteredAt: string
  /** 상담 기록이 없으면 null */
  lastRecordedAt: string | null
}

export type CaseSearchResponse = {
  totalCount: number
  page: number
  size: number
  totalPages: number
  items: CaseListItem[]
}

function regionOf(dongCode: string) {
  const dong = db.dongs.find((item) => item.dongCode === dongCode)
  const sigungu = db.sigungus.find((item) => item.sigunguCode === dong?.sigunguCode)
  const sido = db.sidos.find((item) => item.sidoCode === sigungu?.sidoCode)
  return {
    sidoCode: sido?.sidoCode ?? "",
    sidoName: sido?.sidoName ?? "",
    sigunguCode: sigungu?.sigunguCode ?? "",
    sigunguName: sigungu?.sigunguName ?? "",
    dongCode: dong?.dongCode ?? "",
    dongName: dong?.dongName ?? "",
  }
}

/** 최근 기록일 = 등록된 상담 일자 중 가장 최근 날짜 */
export function lastRecordedAtOf(caseId: number): string | null {
  return db.consultations
    .filter((item) => item.caseId === caseId)
    .reduce<string | null>((latest, item) => (!latest || item.consultedAt > latest ? item.consultedAt : latest), null)
}

function toListItem(record: CaseRecord, today: Date): CaseListItem & { sidoCode: string; sigunguCode: string } {
  const age = ageOn(record.birthDate, today)
  const region = regionOf(record.dongCode)
  return {
    caseId: record.caseId,
    managementNo: record.managementNo,
    name: record.name,
    age,
    ageGroup: ageGroupOf(age),
    gender: record.gender,
    sidoName: region.sidoName,
    sigunguName: region.sigunguName,
    dongName: region.dongName,
    firstRegisteredAt: record.firstRegisteredAt,
    lastRecordedAt: lastRecordedAtOf(record.caseId),
    sidoCode: region.sidoCode,
    sigunguCode: region.sigunguCode,
  }
}

function inRange(value: string | null, from: string | null, to: string | null) {
  if (!from && !to) return true
  if (!value) return false
  if (from && value < from) return false
  if (to && value > to) return false
  return true
}

// ── 4.2.1 사례자 정보 관리 ──────────────────────────────

/** D10-B: 없는 사례자·다른 기관 사례자 */
export const CASE_NOT_FOUND_MESSAGE = "사례자를 찾을 수 없습니다."
/** D10-B: 같은 기관이지만 로그인한 회원이 담당자가 아닌 사례자 */
export const CASE_FORBIDDEN_MESSAGE = "조회 권한이 없습니다."

export type CaseManagerItem = {
  memberId: number
  name: string
  title: string | null
}

export type CaseDetail = {
  caseId: number
  managementNo: string
  name: string
  birthDate: string
  /** 만 나이 */
  age: number
  ageGroup: AgeGroup
  gender: Gender
  sidoCode: string
  sidoName: string
  sigunguCode: string
  sigunguName: string
  dongCode: string
  dongName: string
  firstRegisteredAt: string
  /** 상담 기록이 없으면 null */
  lastRecordedAt: string | null
  managers: CaseManagerItem[]
}

/** 사례자 등록·수정 요청 공통 */
export type CaseInput = {
  name: string
  birthDate: string
  gender: Gender
  /** 지역 (행정동까지 필수) */
  dongCode: string
  firstRegisteredAt: string
  /** 담당자 (같은 기관 회원, 한 명 이상) */
  managerMemberIds: number[]
}

export type CaseDuplicateItem = {
  caseId: number
  managementNo: string
  name: string
}

/**
 * 로그인한 회원이 이 사례자를 볼 수 있는지 확인한다 (4.2 모든 API 공통).
 * 없거나 다른 기관 사례자 → 찾을 수 없음, 같은 기관이지만 담당자가 아님 → 권한 없음
 */
export function requireCaseAccess(member: Member, caseId: number): CaseRecord {
  const record = db.cases.find((item) => item.caseId === caseId)
  if (!record || record.orgId !== member.orgId) {
    if (record) serverNote("다른 기관의 사례자라 없는 사례자와 같은 실패로 응답함")
    throw new ApiError(CASE_NOT_FOUND_MESSAGE)
  }
  const isManager = db.caseManagers.some(
    (item) => item.caseId === caseId && item.memberId === member.memberId,
  )
  if (!isManager) {
    serverNote(`로그인한 회원(${member.name})이 이 사례자의 담당자가 아님`)
    throw new ApiError(CASE_FORBIDDEN_MESSAGE)
  }
  return record
}

function managersOf(caseId: number): CaseManagerItem[] {
  return db.caseManagers
    .filter((item) => item.caseId === caseId)
    .map((item) => db.members.find((member) => member.memberId === item.memberId))
    .filter((member): member is Member => Boolean(member))
    .map(({ memberId, name, title }) => ({ memberId, name, title }))
}

function toDetail(record: CaseRecord): CaseDetail {
  const age = ageOn(record.birthDate, new Date())
  const region = regionOf(record.dongCode)
  return {
    caseId: record.caseId,
    managementNo: record.managementNo,
    name: record.name,
    birthDate: record.birthDate,
    age,
    ageGroup: ageGroupOf(age),
    gender: record.gender,
    ...region,
    firstRegisteredAt: record.firstRegisteredAt,
    lastRecordedAt: lastRecordedAtOf(record.caseId),
    managers: managersOf(record.caseId),
  }
}

/** 서버에서도 하는 입력 확인 (화면에서 먼저 확인하므로 보통은 여기까지 오지 않는다) */
function validateCaseInput(member: Member, input: CaseInput): CaseInput {
  const name = input.name.trim()
  if (!name) throw new ApiError("이름을 입력하세요.")
  for (const [label, value] of [
    ["생년월일", input.birthDate],
    ["최초 등록일", input.firstRegisteredAt],
  ] as const) {
    if (!isValidDateString(value)) throw new ApiError(`${label}이 올바른 날짜가 아닙니다.`)
    if (value > todayString()) throw new ApiError(`${label}은 오늘 이후 날짜로 정할 수 없습니다.`)
  }
  if (input.gender !== "남" && input.gender !== "여") throw new ApiError("성별을 선택하세요.")
  if (!db.dongs.some((item) => item.dongCode === input.dongCode)) {
    throw new ApiError("지역을 읍면동까지 선택하세요.")
  }
  const managerMemberIds = [...new Set(input.managerMemberIds)]
  if (managerMemberIds.length === 0) throw new ApiError("담당자를 한 명 이상 지정하세요.")
  const invalid = managerMemberIds.filter(
    (memberId) =>
      !db.members.some(
        (item) => item.memberId === memberId && item.orgId === member.orgId && item.withdrawnAt === null,
      ),
  )
  if (invalid.length > 0) throw new ApiError("담당자는 같은 기관의 회원 중에서만 지정할 수 있습니다.")
  return { ...input, name, managerMemberIds }
}

/** 새 사례자ID (삭제한 사례자의 ID는 다시 쓰지 않는다) */
let lastCaseId = db.cases.reduce((max, item) => Math.max(max, item.caseId), 0)

/** 관리번호 부여 (D9-A): 최초 등록일의 연도로, 기관·연도별 다음 번호 */
function issueManagementNo(orgId: number, firstRegisteredAt: string): string {
  const year = firstRegisteredAt.slice(0, 4)
  let sequence = db.caseNumberSequences.find((item) => item.orgId === orgId && item.year === year)
  if (!sequence) {
    sequence = { orgId, year, lastNo: 0 }
    db.caseNumberSequences.push(sequence)
  }
  sequence.lastNo += 1
  return `${year}-${String(sequence.lastNo).padStart(4, "0")}`
}

export const caseApi = {
  /**
   * 4.1.2 사례자 목록 조회 (4.1.1 검색 필터·키워드·정렬 포함)
   * 로그인한 회원이 담당자로 지정된 사례자만 돌려준다.
   */
  searchCases(request: CaseSearchRequest) {
    return callApi(
      { featureId: "4.1.2", featureName: "사례자 목록 조회" },
      request,
      (input): CaseSearchResponse => {
        const member = requireMember()
        const myCaseIds = new Set(
          db.caseManagers.filter((item) => item.memberId === member.memberId).map((item) => item.caseId),
        )
        serverNote(`로그인한 회원(${member.name})이 담당자로 지정된 사례자만 조회함`)

        const today = new Date()
        const keyword = input.keyword.trim()
        const filtered = db.cases
          .filter((record) => record.orgId === member.orgId && myCaseIds.has(record.caseId))
          .map((record) => ({ record, item: toListItem(record, today) }))
          .filter(({ record, item }) => {
            if (input.dongCode && record.dongCode !== input.dongCode) return false
            if (!input.dongCode && input.sigunguCode && item.sigunguCode !== input.sigunguCode) return false
            if (!input.dongCode && !input.sigunguCode && input.sidoCode && item.sidoCode !== input.sidoCode) {
              return false
            }
            if (input.ageGroup !== "전체" && item.ageGroup !== input.ageGroup) return false
            if (input.gender !== "전체" && item.gender !== input.gender) return false
            if (!inRange(item.firstRegisteredAt, input.registeredFrom, input.registeredTo)) return false
            if (!inRange(item.lastRecordedAt, input.recordedFrom, input.recordedTo)) return false
            if (keyword && !item.name.includes(keyword) && !item.managementNo.includes(keyword)) return false
            return true
          })
          .map(({ item }) => item)

        const sign = input.direction === "asc" ? 1 : -1
        const compare = (a: CaseListItem, b: CaseListItem): number => {
          switch (input.sort) {
            case "name":
              return a.name.localeCompare(b.name, "ko")
            case "region":
              return `${a.sigunguName} ${a.dongName}`.localeCompare(`${b.sigunguName} ${b.dongName}`, "ko")
            case "age":
              return a.age - b.age
            case "gender":
              return a.gender.localeCompare(b.gender, "ko")
            case "firstRegisteredAt":
              return a.firstRegisteredAt.localeCompare(b.firstRegisteredAt)
            case "lastRecordedAt":
              return (a.lastRecordedAt ?? "").localeCompare(b.lastRecordedAt ?? "")
          }
        }
        filtered.sort((a, b) => {
          // 최근 기록일이 없는 사례자는 정렬 방향과 관계없이 맨 뒤
          if (input.sort === "lastRecordedAt" && (!a.lastRecordedAt || !b.lastRecordedAt)) {
            if (!a.lastRecordedAt && !b.lastRecordedAt) return 0
            return a.lastRecordedAt ? -1 : 1
          }
          return compare(a, b) * sign || b.managementNo.localeCompare(a.managementNo)
        })

        const size = Math.max(1, input.size)
        const totalCount = filtered.length
        const totalPages = Math.max(1, Math.ceil(totalCount / size))
        const page = Math.min(Math.max(1, input.page), totalPages)
        const items = filtered
          .slice((page - 1) * size, page * size)
          // 응답에는 화면에 필요한 값만 담는다 (정렬·검색에만 쓴 코드는 뺀다)
          .map(({ sidoCode: _sido, sigunguCode: _sigungu, ...item }) => item as CaseListItem)
        return { totalCount, page, size, totalPages, items }
      },
    )
  },

  /** 4.2.1 사례자 정보 조회: 담당자로 지정된 사례자만 */
  getCase(request: { caseId: number }) {
    return callApi({ featureId: "4.2.1", featureName: "사례자 정보 조회" }, request, ({ caseId }): CaseDetail => {
      const member = requireMember()
      return toDetail(requireCaseAccess(member, caseId))
    })
  },

  /**
   * 4.2.1 사례자 중복 확인 (명세 추가 항목): 이름·생년월일이 같은 사례자.
   * 로그인한 회원이 담당하는 사례자 안에서만 찾는다. 수정할 때는 자기 자신을 뺀다(excludeCaseId).
   */
  checkDuplicate(request: { name: string; birthDate: string; excludeCaseId: number | null }) {
    return callApi(
      { featureId: "4.2.1", featureName: "사례자 중복 확인" },
      request,
      ({ name, birthDate, excludeCaseId }): { duplicates: CaseDuplicateItem[] } => {
        const member = requireMember()
        serverNote(`로그인한 회원(${member.name})이 담당하는 사례자 중에서만 확인함`)
        const myCaseIds = new Set(
          db.caseManagers.filter((item) => item.memberId === member.memberId).map((item) => item.caseId),
        )
        const duplicates = db.cases
          .filter(
            (record) =>
              record.orgId === member.orgId &&
              myCaseIds.has(record.caseId) &&
              record.caseId !== excludeCaseId &&
              record.name === name.trim() &&
              record.birthDate === birthDate,
          )
          .map(({ caseId, managementNo, name: caseName }) => ({ caseId, managementNo, name: caseName }))
        return { duplicates }
      },
    )
  },

  /** 4.2.1 사례자 정보 등록: 등록한 회원을 담당자로 지정하고 관리번호를 자동으로 부여 */
  createCase(request: CaseInput) {
    return callApi(
      { featureId: "4.2.1", featureName: "사례자 정보 등록" },
      request,
      (input): { caseId: number; managementNo: string } => {
        const member = requireMember()
        const valid = validateCaseInput(member, input)
        if (!valid.managerMemberIds.includes(member.memberId)) {
          valid.managerMemberIds.unshift(member.memberId)
          serverNote("요청한 담당자에 등록한 회원이 없어 함께 지정함")
        }
        serverNote(`등록한 회원(${member.name})을 담당자로 지정함`)
        const managementNo = issueManagementNo(member.orgId, valid.firstRegisteredAt)
        serverNote(
          `관리번호 ${managementNo} 부여 (${findOrganizationName(member.orgId)}의 ${valid.firstRegisteredAt.slice(0, 4)}년 다음 번호)`,
        )
        lastCaseId += 1
        const caseId = lastCaseId
        db.cases.push({
          caseId,
          orgId: member.orgId,
          managementNo,
          name: valid.name,
          birthDate: valid.birthDate,
          gender: valid.gender,
          dongCode: valid.dongCode,
          firstRegisteredAt: valid.firstRegisteredAt,
        })
        db.caseManagers.push(...valid.managerMemberIds.map((memberId) => ({ caseId, memberId })))
        return { caseId, managementNo }
      },
    )
  },

  /** 4.2.1 사례자 정보 수정: 담당자만. 관리번호는 바꾸지 않는다(D9-A). 본인도 담당자에서 뺄 수 있다(D6-B) */
  updateCase(request: CaseInput & { caseId: number }) {
    return callApi({ featureId: "4.2.1", featureName: "사례자 정보 수정" }, request, (input) => {
      const member = requireMember()
      const record = requireCaseAccess(member, input.caseId)
      const valid = validateCaseInput(member, input)
      if (valid.firstRegisteredAt.slice(0, 4) !== record.firstRegisteredAt.slice(0, 4)) {
        serverNote(`최초 등록일의 연도가 바뀌었지만 관리번호(${record.managementNo})는 바꾸지 않음`)
      }
      record.name = valid.name
      record.birthDate = valid.birthDate
      record.gender = valid.gender
      record.dongCode = valid.dongCode
      record.firstRegisteredAt = valid.firstRegisteredAt
      db.caseManagers = [
        ...db.caseManagers.filter((item) => item.caseId !== record.caseId),
        ...valid.managerMemberIds.map((memberId) => ({ caseId: record.caseId, memberId })),
      ]
      serverNote("담당자 지정을 요청한 목록으로 바꿈")
      if (!valid.managerMemberIds.includes(member.memberId)) {
        serverNote(`로그인한 회원(${member.name})이 담당자에서 빠져, 이후 이 사례자를 조회할 수 없음`)
      }
    })
  },

  /** 4.2.1 사례자 정보 삭제: 담당자만. 상담 기록·담당자 지정도 함께 바로 삭제 (복구 불가) */
  deleteCase(request: { caseId: number }) {
    return callApi({ featureId: "4.2.1", featureName: "사례자 정보 삭제" }, request, ({ caseId }) => {
      const member = requireMember()
      requireCaseAccess(member, caseId)
      const consultationCount = db.consultations.filter((item) => item.caseId === caseId).length
      const managerCount = db.caseManagers.filter((item) => item.caseId === caseId).length
      db.consultations = db.consultations.filter((item) => item.caseId !== caseId)
      db.caseManagers = db.caseManagers.filter((item) => item.caseId !== caseId)
      db.cases = db.cases.filter((item) => item.caseId !== caseId)
      serverNote(`상담 기록 ${consultationCount}건과 담당자 지정 ${managerCount}건을 함께 삭제함 (복구 불가)`)
      serverNote("삭제한 사례자의 관리번호는 다시 쓰지 않음")
    })
  },
}
