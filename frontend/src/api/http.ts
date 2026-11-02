import { ensureCsrfToken, prepareCsrf, CSRF_HEADER } from "@/api/csrf"
import { ApiError, CLIENT_ERROR_CODE, MESSAGES } from "@/api/errors"
import type { FieldError } from "@/api/types"

// 공통 HTTP 클라이언트 (공통 응답 및 세션 규칙 · NFR-INT-01)
// - 같은 출처 /api 아래 상대 경로로 부른다. 로그인은 SESSION 쿠키(HttpOnly)로만 유지하고 토큰을 저장하지 않는다.
// - 성공 { success:true, data, meta } → data만 돌려준다. 204는 본문을 읽지 않는다.
// - 실패는 ApiError로 던진다. 401은 로그인 만료, 403 PASSWORD_CHANGE_REQUIRED는 비밀번호 변경 화면으로 보낸다.
// - /health와 SSE(EventSource)는 공통 응답 모양이 아니라서 이 클라이언트를 쓰지 않는다.

const BASE_PATH = "/api"

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE"

export type QueryValue = string | number | boolean | null | undefined
export type Query = Record<string, QueryValue>

export type RequestOptions = {
  /** 빈 값(null·undefined·빈 문자열)은 주소에 넣지 않는다 */
  query?: Query
  /** JSON으로 보낸다. FormData는 그대로 보낸다(파일 업로드) */
  body?: unknown
  signal?: AbortSignal
  /** 401·403 PASSWORD_CHANGE_REQUIRED를 화면 이동으로 처리하지 않고 호출한 쪽에 맡긴다 (로그인 복원 등) */
  skipAuthHandling?: boolean
}

type AuthHandlers = {
  onUnauthorized?: () => void
  onPasswordChangeRequired?: () => void
}

let authHandlers: AuthHandlers = {}

/** 401·비밀번호 변경 필요를 받았을 때 할 일을 등록한다 (main.tsx에서 한 번) */
export function setAuthHandlers(handlers: AuthHandlers) {
  authHandlers = handlers
}

export async function apiRequest<T>(method: Method, path: string, options: RequestOptions = {}): Promise<T> {
  const unsafe = method !== "GET"
  let response = await send(method, path, options)

  // CSRF 토큰이 바뀌었거나 만료됐으면 다시 받아 한 번만 재시도한다.
  // 서버가 처리하기 전에 거절한 요청이라 다시 보내도 안전하다.
  if (unsafe && response.status === 403) {
    const error = await toApiError(response)
    if (error.code !== "CSRF_INVALID") throw handleAuthError(error, options)
    await prepareCsrf(true)
    response = await send(method, path, options)
  }

  if (!response.ok) throw handleAuthError(await toApiError(response), options)
  return readData<T>(response)
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "body">) => apiRequest<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) => apiRequest<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) => apiRequest<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) => apiRequest<T>("PATCH", path, { ...options, body }),
  delete: <T>(path: string, options?: RequestOptions) => apiRequest<T>("DELETE", path, options),
}

/** 화면 주소의 검색 조건 → API query 문자열. 빈 값은 빼고, 문자열 "null"·"undefined"를 보내지 않는다 */
export function toQueryString(query: Query = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue
    params.append(key, String(value))
  }
  const text = params.toString()
  return text === "" ? "" : `?${text}`
}

async function send(method: Method, path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" }
  let body: BodyInit | undefined

  if (options.body instanceof FormData) {
    body = options.body
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json"
    body = JSON.stringify(options.body)
  }

  if (method !== "GET") headers[CSRF_HEADER] = await ensureCsrfToken()

  try {
    return await fetch(`${BASE_PATH}${path}${toQueryString(options.query)}`, {
      method,
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error
    throw new ApiError({ status: 0, code: CLIENT_ERROR_CODE.network, message: MESSAGES.network })
  }
}

async function readData<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  const body = await readJson(response)
  if (isRecord(body) && body.success === true && "data" in body) return body.data as T
  throw badResponse(response)
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = await readJson(response)
  const requestId = response.headers.get("X-Request-Id")

  if (isRecord(body) && body.success === false && isRecord(body.error) && typeof body.error.code === "string") {
    const meta = isRecord(body.meta) ? body.meta : {}
    return new ApiError({
      status: response.status,
      code: body.error.code,
      message: typeof body.error.message === "string" ? body.error.message : MESSAGES.badResponse,
      fieldErrors: Array.isArray(body.error.fieldErrors) ? (body.error.fieldErrors as FieldError[]) : [],
      requestId: typeof meta.requestId === "string" ? meta.requestId : requestId,
    })
  }

  // 공통 오류 모양이 아닌 응답: Nginx가 직접 돌려준 HTML(413·429·502 등)이나 빈 본문
  if (response.status === 413)
    return new ApiError({ status: 413, code: CLIENT_ERROR_CODE.fileTooLarge, message: MESSAGES.fileTooLarge, requestId })
  if (response.status === 429)
    return new ApiError({ status: 429, code: CLIENT_ERROR_CODE.rateLimited, message: MESSAGES.rateLimited, requestId })
  return badResponse(response)
}

function handleAuthError(error: ApiError, options: RequestOptions): ApiError {
  if (options.skipAuthHandling) return error
  if (error.status === 401) authHandlers.onUnauthorized?.()
  else if (error.status === 403 && error.code === "PASSWORD_CHANGE_REQUIRED") authHandlers.onPasswordChangeRequired?.()
  return error
}

function badResponse(response: Response): ApiError {
  return new ApiError({
    status: response.status,
    code: response.status >= 500 || response.status === 0 ? CLIENT_ERROR_CODE.network : CLIENT_ERROR_CODE.badResponse,
    message: response.status >= 500 ? MESSAGES.network : MESSAGES.badResponse,
    requestId: response.headers.get("X-Request-Id"),
  })
}

async function readJson(response: Response): Promise<unknown> {
  if (!(response.headers.get("Content-Type") ?? "").includes("application/json")) return null
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}
