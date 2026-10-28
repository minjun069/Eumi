import type { ConsultationDetail, ConsultationInput } from "@/mock/api/consultationApi"
import type { ConsultationCategory } from "@/types/domain"
import { CATEGORY_ETC_MAX } from "@/utils/consultation"
import { isValidDateString, todayString } from "@/utils/datetime"

// 상담 창(4.2.2)의 입력값과 화면에서 하는 입력 확인

export type ConsultationForm = {
  consultedAt: string
  category: ConsultationCategory
  /** 분류가 '기타'일 때만 쓴다 */
  categoryEtc: string
  purpose: string
  content: string
}

export type ConsultationFormErrors = Partial<Record<keyof ConsultationForm, string>>

/** 상담 등록 창을 열 때 미리 채우는 예시 */
export function exampleConsultationForm(): ConsultationForm {
  return {
    consultedAt: todayString(),
    category: "정기상담",
    categoryEtc: "",
    purpose: "안부 전화",
    content: "전화로 안부를 확인함. 최근 끼니를 거르지 않고 있다고 함. 다음 주에 방문하기로 함.",
  }
}

/** 개발용 '예외 상황'의 채우기 버튼 */
export const CONSULTATION_FILLS: { label: string; patch: () => Partial<ConsultationForm> }[] = [
  { label: "상담 예시 채우기", patch: () => exampleConsultationForm() },
  { label: "'기타' 분류 채우기 (가정 방문)", patch: () => ({ category: "기타", categoryEtc: "가정 방문" }) },
  {
    label: "'기타' 21자 채우기",
    patch: () => ({ category: "기타", categoryEtc: "가".repeat(CATEGORY_ETC_MAX + 1) }),
  },
  {
    label: "빈칸 채우기",
    patch: () => ({ consultedAt: "", category: "기타", categoryEtc: "", purpose: "", content: "" }),
  },
  { label: "미래 날짜 채우기", patch: () => ({ consultedAt: "2030-01-01" }) },
]

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
  if (!form.purpose.trim()) errors.purpose = "상담 목적을 입력하세요."
  if (!form.content.trim()) errors.content = "상담 내용을 입력하세요."
  return errors
}

export function toConsultationInput(form: ConsultationForm): ConsultationInput {
  return {
    consultedAt: form.consultedAt,
    purpose: form.purpose.trim(),
    category: form.category,
    categoryEtc: form.category === "기타" ? form.categoryEtc.trim() : null,
    content: form.content.trim(),
  }
}

export function sameConsultationForm(a: ConsultationForm, b: ConsultationForm): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}
