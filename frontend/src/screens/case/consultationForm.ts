import type { ConsultationCategory, ConsultationDetail, ConsultationInput } from "@/api/caseApi"
import { CATEGORY_ETC_MAX, CONTENT_MAX, PURPOSE_MAX } from "@/utils/consultation"
import { isValidDateString, todayString } from "@/utils/datetime"

// 상담 창(4.2.2)의 입력값과 화면에서 하는 입력 확인 (서버도 같은 조건을 다시 검사한다)

export type ConsultationForm = {
  consultedAt: string
  category: ConsultationCategory
  /** 분류가 '기타'일 때만 쓴다 */
  categoryEtc: string
  purpose: string
  content: string
}

export type ConsultationFormErrors = Partial<Record<keyof ConsultationForm, string>>

/** 서버 fieldErrors의 field → 입력칸 */
export const CONSULTATION_FORM_FIELDS: Record<string, keyof ConsultationForm> = {
  consultedAt: "consultedAt",
  category: "category",
  categoryEtc: "categoryEtc",
  purpose: "purpose",
  content: "content",
}

/** 상담 등록 창의 처음 값: 상담 일자는 오늘 */
export function emptyConsultationForm(): ConsultationForm {
  return { consultedAt: todayString(), category: "정기상담", categoryEtc: "", purpose: "", content: "" }
}

export function formFromConsultation(detail: ConsultationDetail): ConsultationForm {
  return {
    consultedAt: detail.consultedAt,
    category: detail.category,
    categoryEtc: detail.categoryEtc ?? "",
    purpose: detail.purpose,
    content: detail.content,
  }
}

export function validateConsultationForm(form: ConsultationForm): ConsultationFormErrors {
  const errors: ConsultationFormErrors = {}
  if (!form.consultedAt) errors.consultedAt = "상담 일자를 입력하세요."
  else if (!isValidDateString(form.consultedAt)) errors.consultedAt = "올바른 날짜가 아닙니다."
  else if (form.consultedAt > todayString()) errors.consultedAt = "오늘 이후 날짜는 입력할 수 없습니다."
  if (form.category === "기타") {
    const etc = form.categoryEtc.trim()
    if (!etc) errors.categoryEtc = "'기타' 분류의 내용을 입력하세요."
    else if (etc.length > CATEGORY_ETC_MAX) errors.categoryEtc = `${CATEGORY_ETC_MAX}자 이내로 입력하세요.`
  }
  const purpose = form.purpose.trim()
  if (!purpose) errors.purpose = "상담 목적을 입력하세요."
  else if (purpose.length > PURPOSE_MAX) errors.purpose = `${PURPOSE_MAX}자 이내로 입력하세요.`
  const content = form.content.trim()
  if (!content) errors.content = "상담 내용을 입력하세요."
  else if (content.length > CONTENT_MAX) errors.content = `${CONTENT_MAX.toLocaleString()}자 이내로 입력하세요.`
  return errors
}

/** 입력 확인을 통과한 값 → API 요청. '기타'가 아니면 categoryEtc는 null */
export function toConsultationInput(form: ConsultationForm): ConsultationInput {
  const base = { consultedAt: form.consultedAt, purpose: form.purpose.trim(), content: form.content.trim() }
  return form.category === "기타"
    ? { ...base, category: "기타", categoryEtc: form.categoryEtc.trim() }
    : { ...base, category: form.category, categoryEtc: null }
}

export function sameConsultationForm(a: ConsultationForm, b: ConsultationForm): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}
