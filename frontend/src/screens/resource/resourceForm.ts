import type { AgeGroup } from "@/api/caseApi"
import {
  RESOURCE_TEXT_LIMITS,
  type ResourceDetail,
  type ResourceInput,
  type ResourceStatus,
  type SupportAgeGroup,
  type SupportGender,
} from "@/api/resourceApi"
import type { MenuProfile } from "@/api/types"
import { isValidDateString, todayString } from "@/utils/datetime"

// 복지자원 등록·수정 화면(3.3.1 등록 양식)의 입력값과 화면에서 하는 입력 확인 (서버도 같은 조건을 다시 검사한다)

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
  /** 담당자가 고른 상태 (manualStatus) */
  status: ResourceStatus
  managerMemberId: number | null
  capacity: string
  actualParticipants: string
  supportContent: string
  applyMethod: string
}

/** 입력 확인을 표시하는 항목 (지역·운영 기간은 묶어서) */
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

/** 서버 fieldErrors의 field → 입력칸 */
export const RESOURCE_FORM_FIELDS: Record<string, ResourceFormField> = {
  resourceName: "resourceName",
  operatingOrgName: "operatingOrgName",
  target: "target",
  supportAgeGroups: "supportAgeGroups",
  supportGender: "supportGender",
  sigunguCode: "region",
  dongCode: "region",
  periodStart: "period",
  periodEnd: "period",
  fee: "fee",
  status: "status",
  managerMemberId: "manager",
  capacity: "capacity",
  actualParticipants: "actualParticipants",
  supportContent: "supportContent",
  applyMethod: "applyMethod",
}

/** 입력값 이름 → 화면 항목 (직접 고치면 그 항목의 서버 오류 표시를 지우는 데 쓴다) */
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

/** 저장은 되지만 알려 주는 안내 */
export function formNotices(form: ResourceForm): { period?: string; actualParticipants?: string } {
  const notices: { period?: string; actualParticipants?: string } = {}
  if (form.status === "진행 중" && isValidDateString(form.periodEnd) && form.periodEnd < todayString()) {
    notices.period = "운영 종료일이 지나 저장하면 '종료'로 표시됩니다."
  }
  const capacity = form.capacity.trim()
  const participants = form.actualParticipants.trim()
  if (NUMBER_PATTERN.test(capacity) && NUMBER_PATTERN.test(participants) && Number(participants) > Number(capacity)) {
    notices.actualParticipants = "정원보다 많습니다. 지금 참여 중인 인원이 맞는지 확인하세요. (저장은 됩니다)"
  }
  return notices
}

/** 입력 확인을 통과한 값 → API 요청. 선택 입력은 비우면 null */
export function toResourceInput(form: ResourceForm): ResourceInput {
  // '무관'은 다른 연령대와 함께 보낼 수 없다 (화면에서도 단독 선택)
  const supportAgeGroups: ResourceInput["supportAgeGroups"] = form.supportAgeGroups.includes("무관")
    ? ["무관"]
    : form.supportAgeGroups.filter((age): age is AgeGroup => age !== "무관")
  return {
    resourceName: form.resourceName.trim(),
    operatingOrgName: form.operatingOrgName.trim(),
    target: form.target.trim(),
    supportAgeGroups,
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
    // 화면에는 담당자가 고른 상태(저장값)를 보여 준다. 종료일이 지나 자동 종료된 것은 안내로
    status: detail.manualStatus,
    managerMemberId: detail.manager.memberId,
    capacity: String(detail.capacity),
    actualParticipants: detail.actualParticipants === null ? "" : String(detail.actualParticipants),
    supportContent: detail.supportContent ?? "",
    applyMethod: detail.applyMethod ?? "",
  }
}

/** 등록 화면 처음 값: 담당자는 나, 수행·담당 기관은 내 기관, 지역은 관할 시군구 전체, 운영 시작일은 오늘 */
export function emptyResourceForm(profile: MenuProfile): ResourceForm {
  return {
    resourceName: "",
    operatingOrgName: profile.orgName,
    target: "",
    supportAgeGroups: [],
    supportGender: "",
    sidoCode: profile.jurisdictionSidoCode || null,
    sigunguCode: profile.jurisdictionSigunguCode || null,
    dongCode: null,
    periodStart: todayString(),
    periodEnd: "",
    fee: "",
    status: "진행 중",
    managerMemberId: profile.memberId,
    capacity: "",
    actualParticipants: "",
    supportContent: "",
    applyMethod: "",
  }
}

export function sameResourceForm(a: ResourceForm, b: ResourceForm): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}
