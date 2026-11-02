import type { FieldError } from "@/api/types"

// API 호출 실패는 모두 ApiError로 던진다 (오류를 정상 결과로 돌려주지 않는다).
// - 서버가 보낸 공통 오류 { success:false, error:{ code, message, fieldErrors } }는 그 값을 그대로 쓴다.
// - 응답이 없거나(통신 오류) 공통 오류 모양이 아니면(프록시 HTML, 빈 본문) 아래 클라이언트 코드로 바꾼다.

export const CLIENT_ERROR_CODE = {
  network: "NETWORK_ERROR",
  badResponse: "BAD_RESPONSE",
  rateLimited: "RATE_LIMITED",
  fileTooLarge: "FILE_TOO_LARGE",
} as const

export const MESSAGES = {
  network: "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  badResponse: "서버 응답을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  rateLimited: "요청이 많습니다. 잠시 후 다시 시도해 주세요.",
  fileTooLarge: "파일이 너무 큽니다.",
  sessionExpired: "로그인이 필요합니다. 다시 로그인해 주세요.",
  passwordChangeRequired: "비밀번호를 변경한 뒤 이용할 수 있습니다.",
} as const

export class ApiError extends Error {
  /** HTTP 상태 코드. 응답을 받지 못했으면 0 */
  readonly status: number
  /** 서버 업무 오류 코드 (예: UNAUTHENTICATED) 또는 CLIENT_ERROR_CODE */
  readonly code: string
  readonly fieldErrors: FieldError[]
  /** 서버가 붙인 요청 추적 ID (X-Request-Id). 문의할 때 함께 전달한다 */
  readonly requestId: string | null

  constructor(params: {
    status: number
    code: string
    message: string
    fieldErrors?: FieldError[]
    requestId?: string | null
  }) {
    super(params.message)
    this.name = "ApiError"
    this.status = params.status
    this.code = params.code
    this.fieldErrors = params.fieldErrors ?? []
    this.requestId = params.requestId ?? null
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

/** 화면에 보여 줄 오류 문구 */
export function errorMessage(error: unknown): string {
  return isApiError(error) ? error.message : MESSAGES.badResponse
}

/** 필드별 오류를 { 필드: 사유 } 로 바꾼다 (폼 입력칸 아래 표시용) */
export function fieldErrorMap(error: unknown): Record<string, string> {
  if (!isApiError(error)) return {}
  return Object.fromEntries(error.fieldErrors.map((item) => [item.field, item.reason]))
}
