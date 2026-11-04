import { isApiError } from "@/api/errors"

// 사례자 화면의 오류 코드 → 화면 동작·문구 (openapi 2.3.0 API-19~29 x-error-codes).
// 서버 문구는 공통 문구라("요청을 처리하지 못했습니다.") 화면은 error.code로 문구를 고른다.
// 401·403 PASSWORD_CHANGE_REQUIRED는 공통 처리(sessionActions)가 화면을 옮긴다.

/** 사례자를 더 볼 수 없는 경우: 같은 기관 미담당(403) / 다른 기관·없음(404) */
export type CaseAccessError = "FORBIDDEN" | "NOT_FOUND"

export function caseAccessErrorOf(error: unknown): CaseAccessError | null {
  if (!isApiError(error)) return null
  if (error.code === "FORBIDDEN") return "FORBIDDEN"
  if (error.code === "NOT_FOUND") return "NOT_FOUND"
  return null
}

export const CASE_ACCESS_TEXT: Record<CaseAccessError, { title: string; description: string }> = {
  FORBIDDEN: { title: "조회 권한이 없습니다.", description: "담당자로 지정된 사례자만 볼 수 있습니다." },
  NOT_FOUND: { title: "사례자를 찾을 수 없습니다.", description: "삭제되었거나 주소가 잘못되었습니다." },
}

export const CASE_MESSAGES = {
  managementNumberExhausted:
    "최초 등록일 연도의 관리번호(9999번까지)를 모두 사용해 더 등록할 수 없습니다. 관리자에게 문의해 주세요.",
  // API-23 409 STATE_CONFLICT: 조건은 11/9 동시성 작업에서 정한다. 지금은 안내 후 상세를 다시 불러오는 공통 처리만 한다
  stateConflict: "다른 곳에서 바뀌었어요. 최신 내용을 다시 불러왔으니 확인한 뒤 다시 저장해 주세요.",
  validation: "입력값을 확인해 주세요.",
  // 서비스가 검사하는 조건(같은 기관 활성 담당자·행정동·한국 날짜 기준 미래 날짜)은 fieldErrors 없이 400으로 온다
  validationWithoutField:
    "입력값을 확인해 주세요. 담당자 목록을 새로 불러왔으니 퇴사·기관 이동한 담당자가 없는지도 확인해 주세요.",
  consultationNotFound: "상담 기록을 찾을 수 없습니다. 상담 목록을 새로 불러왔습니다.",
  listValidation: "검색 조건이 올바르지 않습니다. 조건을 다시 골라 검색해 주세요.",
} as const

/** 서버 fieldErrors의 field → 화면 입력칸. managerMemberIds[0]처럼 붙은 번호는 뗀다 */
export function fieldErrorsOf<Field extends string>(
  error: unknown,
  fields: Record<string, Field>,
): Partial<Record<Field, string>> {
  if (!isApiError(error)) return {}
  const result: Partial<Record<Field, string>> = {}
  for (const item of error.fieldErrors) {
    const field = fields[item.field.replace(/\[\d+\]$/, "")]
    if (field && !result[field]) result[field] = item.reason
  }
  return result
}
