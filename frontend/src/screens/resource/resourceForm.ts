import type { ResourceDetail, ResourceInput } from "@/mock/api/resourceApi"
import { RESOURCE_TEXT_LIMITS } from "@/mock/api/resourceApi"
import type { DocumentExtract } from "@/mock/seed/documentExtracts"
import type { MenuProfile, ResourceStatus, SupportAgeGroup, SupportGender } from "@/types/domain"
import { isValidDateString, todayString } from "@/utils/datetime"

// 복지자원 등록·수정 화면(3.3.1 등록 양식)의 입력값, 화면에서 하는 입력 확인, 예시 채우기

export type ResourceForm = {
  resourceName: string
  operatingOrgName: string
  target: string
  supportAgeGroups: SupportAgeGroup[]
  supportGender: SupportGender | ""
  sidoCode: string | null
  sigunguCode: string | null
  /** null이면 시군구 전체 */
  dongCode: string | null
  periodStart: string
  periodEnd: string
  /** 숫자 입력칸 (글로 두고 '등록'·'저장' 때 확인) */
  fee: string
  status: ResourceStatus
  managerMemberId: number | null
  capacity: string
  actualParticipants: string
  supportContent: string
  applyMethod: string
}

/** 입력 확인·AI 입력 표시를 하는 항목 (지역·운영 기간은 묶어서) */
export type ResourceFormField =
  | "resourceName"
  | "operatingOrgName"
  | "target"
  | "supportAgeGroups"
  | "supportGender"
  | "region"
  | "period"
  | "fee"
  | "status"
  | "manager"
  | "capacity"
  | "actualParticipants"
  | "supportContent"
  | "applyMethod"

export type ResourceFormErrors = Partial<Record<ResourceFormField, string>>

/** 입력값 이름 → 화면 항목 (직접 고치면 'AI 입력' 표시를 지우는 데 씀) */
export function fieldOf(key: keyof ResourceForm): ResourceFormField {
  if (key === "sidoCode" || key === "sigunguCode" || key === "dongCode") return "region"
  if (key === "periodStart" || key === "periodEnd") return "period"
  if (key === "managerMemberId") return "manager"
  return key
}

const NUMBER_PATTERN = /^\d+$/

function textError(value: string, label: string, limit: number, required: boolean): string | undefined {
  const trimmed = value.trim()
  if (required && !trimmed) return `${label}을 입력하세요.`
  if (trimmed.length > limit) return `${limit}자 이내로 입력하세요. (지금 ${trimmed.length}자)`
  return undefined
}

function countError(value: string, label: string, min: number, required: boolean): string | undefined {
  const trimmed = value.trim()
  if (!trimmed) return required ? `${label}을 입력하세요.` : undefined
  if (!NUMBER_PATTERN.test(trimmed) || Number(trimmed) < min) return `${min} 이상의 숫자로 입력하세요.`
  return undefined
}

/** '등록'·'저장'을 막는 입력 오류 */
export function validateResourceForm(form: ResourceForm): ResourceFormErrors {
  const errors: ResourceFormErrors = {}
  const set = (field: ResourceFormField, message: string | undefined) => {
    if (message) errors[field] = message
  }
  set("resourceName", textError(form.resourceName, "자원명", RESOURCE_TEXT_LIMITS.resourceName, true))
  set("operatingOrgName", textError(form.operatingOrgName, "수행·담당 기관", RESOURCE_TEXT_LIMITS.operatingOrgName, true))
  set("target", textError(form.target, "지원 대상", RESOURCE_TEXT_LIMITS.target, true))
  if (form.supportAgeGroups.length === 0) errors.supportAgeGroups = "지원 연령을 하나 이상 고르세요."
  if (!form.supportGender) errors.supportGender = "지원 성별을 고르세요."
  if (!form.sigunguCode) errors.region = "지역을 시군구까지 선택하세요."
  if (!form.periodStart || !form.periodEnd) errors.period = "운영 기간을 입력하세요."
  else if (!isValidDateString(form.periodStart) || !isValidDateString(form.periodEnd)) errors.period = "올바른 날짜가 아닙니다."
  else if (form.periodStart > form.periodEnd) errors.period = "시작일이 종료일보다 늦습니다."
  if (!form.fee.trim()) errors.fee = "이용자 부담금을 입력하세요. 무료면 0을 입력하세요."
  else set("fee", countError(form.fee, "이용자 부담금", 0, true))
  if (form.managerMemberId === null) errors.manager = "담당자를 고르세요."
  set("capacity", countError(form.capacity, "정원", 1, true))
  set("actualParticipants", countError(form.actualParticipants, "실제 참여자 수", 0, false))
  set("supportContent", textError(form.supportContent, "지원 내용", RESOURCE_TEXT_LIMITS.supportContent, false))
  set("applyMethod", textError(form.applyMethod, "신청 방법", RESOURCE_TEXT_LIMITS.applyMethod, false))
  return errors
}

/** 저장은 되지만 알려 주는 안내 (E7-B, E8-A) */
export function formNotices(form: ResourceForm): { period?: string; actualParticipants?: string } {
  const notices: { period?: string; actualParticipants?: string } = {}
  if (form.status === "진행 중" && isValidDateString(form.periodEnd) && form.periodEnd < todayString()) {
    notices.period = "운영 종료일이 지나 저장하면 '종료'로 표시됩니다."
  }
  const capacity = form.capacity.trim()
  const participants = form.actualParticipants.trim()
  if (NUMBER_PATTERN.test(capacity) && NUMBER_PATTERN.test(participants) && Number(participants) > Number(capacity)) {
    notices.actualParticipants = "정원보다 많습니다. 지금 참여 중인 인원이 맞는지 확인하세요."
  }
  return notices
}

/** 입력 확인을 통과한 값 → API 요청 */
export function toResourceInput(form: ResourceForm): ResourceInput {
  return {
    resourceName: form.resourceName.trim(),
    operatingOrgName: form.operatingOrgName.trim(),
    target: form.target.trim(),
    supportAgeGroups: form.supportAgeGroups,
    supportGender: form.supportGender as SupportGender,
    sigunguCode: form.sigunguCode ?? "",
    dongCode: form.dongCode,
    periodStart: form.periodStart,
    periodEnd: form.periodEnd,
    fee: Number(form.fee.trim()),
    status: form.status,
    managerMemberId: form.managerMemberId ?? 0,
    capacity: Number(form.capacity.trim()),
    actualParticipants: form.actualParticipants.trim() ? Number(form.actualParticipants.trim()) : null,
    supportContent: form.supportContent.trim() || null,
    applyMethod: form.applyMethod.trim() || null,
  }
}

export function formFromDetail(detail: ResourceDetail): ResourceForm {
  return {
    resourceName: detail.resourceName,
    operatingOrgName: detail.operatingOrgName,
    target: detail.target,
    supportAgeGroups: detail.supportAgeGroups,
    supportGender: detail.supportGender,
    sidoCode: detail.sidoCode,
    sigunguCode: detail.sigunguCode,
    dongCode: detail.dongCode,
    periodStart: detail.periodStart,
    periodEnd: detail.periodEnd,
    fee: String(detail.fee),
    // 화면에는 담당자가 고른 상태를 보여 준다 (자동 종료는 안내로)
    status: detail.autoEnded ? "진행 중" : detail.status,
    managerMemberId: detail.manager?.memberId ?? null,
    capacity: String(detail.capacity),
    actualParticipants: detail.actualParticipants === null ? "" : String(detail.actualParticipants),
    supportContent: detail.supportContent ?? "",
    applyMethod: detail.applyMethod ?? "",
  }
}

/** 등록 화면 처음 값: 예시 자원. 담당자는 나, 수행·담당 기관은 내 기관, 지역은 관할 시군구 전체 */
export function exampleResourceForm(profile: MenuProfile): ResourceForm {
  return {
    resourceName: "어르신 걷기 동아리",
    operatingOrgName: profile.orgName,
    target: "걷기 운동이 필요한 지역 어르신",
    supportAgeGroups: ["노년"],
    supportGender: "무관",
    sidoCode: profile.jurisdictionSidoCode || null,
    sigunguCode: profile.jurisdictionSigunguCode || null,
    dongCode: null,
    periodStart: "2026-11-02",
    periodEnd: "2026-12-31",
    fee: "0",
    status: "진행 중",
    managerMemberId: profile.memberId,
    capacity: "20",
    actualParticipants: "",
    supportContent: "주 2회 동네 걷기와 스트레칭",
    applyMethod: "기관 전화 또는 방문 신청",
  }
}

/** 문서에서 뽑은 항목을 양식에 채운다. 채운 항목과 찾지 못한 필수 항목을 함께 돌려준다 (E2-A, E3-A) */
export function applyExtract(
  form: ResourceForm,
  extracted: DocumentExtract,
  missingFields: string[],
): { form: ResourceForm; filled: ResourceFormField[]; missing: ResourceFormField[] } {
  const filled: ResourceFormField[] = []
  const pick = <T,>(value: T | null, field: ResourceFormField, empty: T): T => {
    if (value === null) return empty
    filled.push(field)
    return value
  }
  const next: ResourceForm = {
    ...form,
    resourceName: pick(extracted.resourceName, "resourceName", ""),
    operatingOrgName: pick(extracted.operatingOrgName, "operatingOrgName", ""),
    target: pick(extracted.target, "target", ""),
    supportAgeGroups: pick(extracted.supportAgeGroups, "supportAgeGroups", []),
    supportGender: pick(extracted.supportGender, "supportGender", ""),
    sidoCode: extracted.sigunguCode ? extracted.sigunguCode.slice(0, 2) : null,
    sigunguCode: extracted.sigunguCode,
    dongCode: extracted.dongCode,
    periodStart: extracted.periodStart ?? "",
    periodEnd: extracted.periodEnd ?? "",
    fee: pick(extracted.fee === null ? null : String(extracted.fee), "fee", ""),
    capacity: pick(extracted.capacity === null ? null : String(extracted.capacity), "capacity", ""),
    supportContent: pick(extracted.supportContent, "supportContent", ""),
    applyMethod: pick(extracted.applyMethod, "applyMethod", ""),
    // 실제 참여자 수는 문서에서 뽑지 않으므로 비운다. 담당자·상태는 그대로
    actualParticipants: "",
  }
  if (extracted.sigunguCode) filled.push("region")
  if (extracted.periodStart && extracted.periodEnd) filled.push("period")
  return { form: next, filled, missing: missingFields as ResourceFormField[] }
}

/** 문서 내용으로 바뀔 입력이 있는지 (있으면 덮어쓰기 전에 확인 창) */
export function hasFillableInput(form: ResourceForm): boolean {
  return Boolean(
    form.resourceName.trim() ||
      form.operatingOrgName.trim() ||
      form.target.trim() ||
      form.supportAgeGroups.length > 0 ||
      form.supportGender ||
      form.sigunguCode ||
      form.periodStart ||
      form.periodEnd ||
      form.fee.trim() ||
      form.capacity.trim() ||
      form.actualParticipants.trim() ||
      form.supportContent.trim() ||
      form.applyMethod.trim(),
  )
}

export function sameResourceForm(a: ResourceForm, b: ResourceForm): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/** 개발용 '예외 상황'의 채우기 버튼 (담당자 고르기 외에는 담당자를 바꾸지 않는다) */
export const RESOURCE_FILLS: { label: string; patch: (form: ResourceForm) => Partial<ResourceForm> }[] = [
  {
    label: "예시: 시군구 전체 자원",
    patch: () => ({
      resourceName: "1인 가구 안부 확인 문자",
      target: "1인 가구 주민",
      supportAgeGroups: ["무관"],
      supportGender: "무관",
      dongCode: null,
      capacity: "500",
      fee: "0",
    }),
  },
  {
    label: "예시: 개포1동 유료 프로그램",
    patch: () => ({
      resourceName: "여성 어르신 공예 모임",
      target: "60세 이상 여성 어르신",
      supportAgeGroups: ["노년"],
      supportGender: "여",
      sidoCode: "11",
      sigunguCode: "11680",
      dongCode: "1168066000",
      fee: "5000",
      capacity: "12",
      actualParticipants: "9",
    }),
  },
  {
    label: "기간이 이미 끝난 자원",
    patch: () => ({ periodStart: "2026-03-02", periodEnd: "2026-09-30", status: "진행 중" }),
  },
  {
    label: "빈칸 채우기",
    patch: () => ({
      resourceName: "",
      operatingOrgName: "",
      target: "",
      supportAgeGroups: [],
      supportGender: "",
      sidoCode: null,
      sigunguCode: null,
      dongCode: null,
      periodStart: "",
      periodEnd: "",
      fee: "",
      capacity: "",
      actualParticipants: "",
    }),
  },
  { label: "기간 오류 (시작 > 종료)", patch: () => ({ periodStart: "2026-12-01", periodEnd: "2026-11-01" }) },
  { label: "정원 0 · 부담금 글자", patch: () => ({ capacity: "0", fee: "무료" }) },
  { label: "참여자 수 > 정원", patch: () => ({ capacity: "10", actualParticipants: "12" }) },
  {
    label: "글자 수 초과 (자원명 51자)",
    patch: () => ({ resourceName: "가".repeat(51) }),
  },
]

/** 개발용 PDF 예시 파일 (프로토타입은 파일 이름으로 결과를 고른다, src/mock/seed/documentExtracts.ts) */
export const DOCUMENT_EXAMPLES: { label: string; name: string; size: number; type: string }[] = [
  { label: "PDF: 모두 찾음", name: "어르신_건강걷기_안내문.pdf", size: 1_240_000, type: "application/pdf" },
  { label: "PDF: 일부만 찾음", name: "진로멘토링_일부_안내.pdf", size: 830_000, type: "application/pdf" },
  { label: "PDF: 읽지 못함", name: "스캔본_읽기불가.pdf", size: 5_400_000, type: "application/pdf" },
  { label: "PDF 아닌 파일 (사진)", name: "프로그램_사진.jpg", size: 2_100_000, type: "image/jpeg" },
  { label: "20MB 넘는 파일", name: "사업계획서_전체.pdf", size: 24_500_000, type: "application/pdf" },
]
