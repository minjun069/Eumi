import type { ConsultationCategory } from "@/api/caseApi"

// 상담 분류와 입력 길이 (API-27·28 ConsultationInput)

export const CONSULTATION_CATEGORIES: ConsultationCategory[] = [
  "초기상담",
  "중기상담",
  "종료상담",
  "정기상담",
  "긴급상담",
  "기타",
]

/** '기타' 분류에 직접 입력하는 내용의 최대 글자 수 */
export const CATEGORY_ETC_MAX = 20
/** 상담 목적 최대 글자 수 */
export const PURPOSE_MAX = 200
/** 상담 내용 최대 글자 수 */
export const CONTENT_MAX = 20_000

/** 목록·상담 창에 보이는 분류. '기타'는 "기타(가정 방문)"처럼 입력한 내용을 함께 표시 */
export function formatCategory(category: ConsultationCategory, categoryEtc: string | null): string {
  return category === "기타" && categoryEtc ? `기타(${categoryEtc})` : category
}
