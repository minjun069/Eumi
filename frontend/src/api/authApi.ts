import { api } from "@/api/http"
import type { MenuProfile } from "@/api/types"

// 로그인 상태 관련 API. 로그인(API-08)은 로그인 화면 작업에서 추가한다.

export const authApi = {
  /** API-01 GET /auth/me — 로그인 상태와 메뉴 프로필 (새로고침 복원) */
  getMe: () => api.get<MenuProfile>("/auth/me", { skipAuthHandling: true }),

  /** API-02 POST /auth/logout — 204 */
  logout: () => api.post<void>("/auth/logout", undefined, { skipAuthHandling: true }),
}
