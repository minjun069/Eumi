import { isApiError } from "@/api/errors"

// 복지자원 화면의 오류 코드 → 화면 동작·문구 (openapi 2.3.0 API-13~17 x-error-codes).
// 서버 문구는 공통 문구라 화면은 error.code로 문구를 고른다.
// 401·403 PASSWORD_CHANGE_REQUIRED는 공통 처리(sessionActions)가 화면을 옮긴다.

/** 자원을 더 다룰 수 없는 경우: 담당자가 아님(403) / 없거나 삭제됨(404) */
export type ResourceAccessError = "FORBIDDEN" | "NOT_FOUND"

export function resourceAccessErrorOf(error: unknown): ResourceAccessError | null {
  if (!isApiError(error)) return null
  if (error.code === "FORBIDDEN") return "FORBIDDEN"
  if (error.code === "NOT_FOUND") return "NOT_FOUND"
  return null
}

export const RESOURCE_ACCESS_TEXT: Record<ResourceAccessError, { title: string; description: string }> = {
  FORBIDDEN: { title: "수정 권한이 없습니다.", description: "복지자원의 담당자만 수정·삭제할 수 있습니다." },
  NOT_FOUND: { title: "복지자원을 찾을 수 없습니다.", description: "삭제되었거나 주소가 잘못되었습니다." },
}

export const RESOURCE_MESSAGES = {
  validation: "입력값을 확인해 주세요.",
  // 서버는 서비스 검사(지역 존재·시군구와 동 일치·기간·같은 기관 활성 담당자)도 fieldErrors에 칸 이름을 담아 보낸다.
  // 칸 이름 없이 오는 400은 화면이 알 수 없는 형식 오류뿐이다
  validationWithoutField: "입력값을 처리하지 못했습니다. 화면을 새로 고친 뒤 다시 시도해 주세요.",
  managerInactive: "같은 기관의 활성 회원이 아닙니다. 담당자 목록을 새로 불러왔으니 다시 고르세요.",
  deleteForbidden: "담당자만 삭제할 수 있습니다. 최신 정보를 다시 불러왔습니다.",
  listValidation: "검색 조건이 올바르지 않습니다. 조건을 다시 골라 검색해 주세요.",
} as const
