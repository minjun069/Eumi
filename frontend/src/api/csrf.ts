import { ApiError, CLIENT_ERROR_CODE, MESSAGES } from "@/api/errors"

// CSRF 토큰 (공통 응답 및 세션 규칙 · NFR-SEC-02)
// - GET /api/auth/csrf (204)가 XSRF-TOKEN 쿠키(Path=/, HttpOnly 아님)를 발급한다.
// - 상태를 바꾸는 요청(POST·PUT·PATCH·DELETE)마다 쿠키 원문을 X-XSRF-TOKEN 헤더에 담는다.
//   로그인·회원가입 같은 비로그인 요청도 같다.
// - 로그인·로그아웃·비밀번호 변경 뒤에는 prepareCsrf(true)로 다시 준비한다.

const CSRF_COOKIE = "XSRF-TOKEN"
export const CSRF_HEADER = "X-XSRF-TOKEN"

export function readCsrfToken(): string | null {
  const prefix = `${CSRF_COOKIE}=`
  const entry = document.cookie.split("; ").find((item) => item.startsWith(prefix))
  if (!entry) return null
  const value = decodeURIComponent(entry.slice(prefix.length))
  return value === "" ? null : value
}

let pending: Promise<void> | null = null

/** 토큰 쿠키를 준비한다. force가 아니면 쿠키가 이미 있을 때 요청하지 않는다 */
export function prepareCsrf(force = false): Promise<void> {
  if (!force && readCsrfToken()) return Promise.resolve()
  pending ??= fetch("/api/auth/csrf", { credentials: "same-origin", cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw csrfUnavailable(response.status)
    }, () => {
      throw csrfUnavailable(0)
    })
    .finally(() => {
      pending = null
    })
  return pending
}

/** 상태 변경 요청 직전에 부른다: 쿠키가 없으면 먼저 준비한다 */
export async function ensureCsrfToken(): Promise<string> {
  await prepareCsrf()
  const token = readCsrfToken()
  if (!token) throw csrfUnavailable(0)
  return token
}

function csrfUnavailable(status: number) {
  return new ApiError({ status, code: CLIENT_ERROR_CODE.network, message: MESSAGES.network })
}
