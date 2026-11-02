import { api } from "@/api/http"
import type { MenuProfile, Schemas, SuccessData } from "@/api/types"

// 로그인 상태 관련 API

export type LoginRequest = Schemas["LoginRequest"]
export type LoginUser = Schemas["LoginUser"]
export type LoginData = SuccessData<"authApi_login_Success">

export const authApi = {
  /** API-08 POST /auth/login — 성공하면 data.user. 실패(401 INVALID_CREDENTIALS)는 로그인 만료가 아니므로 화면이 처리한다 */
  login: (request: LoginRequest) => api.post<LoginData>("/auth/login", request, { skipAuthHandling: true }),

  /** API-01 GET /auth/me — 로그인 상태와 메뉴 프로필 (새로고침 복원) */
  getMe: () => api.get<MenuProfile>("/auth/me", { skipAuthHandling: true }),

  /** API-02 POST /auth/logout — 204 */
  logout: () => api.post<void>("/auth/logout", undefined, { skipAuthHandling: true }),
}
