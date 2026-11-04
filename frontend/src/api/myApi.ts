import { api } from "@/api/http"
import type { Schemas, SuccessData } from "@/api/types"

// 마이페이지 (로그인한 회원 본인 정보만)

export type MyInfo = SuccessData<"myApi_getMyInfo_Success">
export type MyInfoPatch = Schemas["MyInfoPatch"]
export type MyResources = SuccessData<"myApi_getMyResources_Success">
export type PasswordChangeRequest = Schemas["PasswordChangeRequest"]
/** 비밀번호 변경 성공: 최신 로그인 사용자 (임시 비밀번호 제한이 풀린 상태) */
export type PasswordChanged = SuccessData<"myApi_changePassword_Success">

export const myKeys = {
  info: ["my", "info"] as const,
  // 복지자원 쿼리(["resources", …]) 아래에 둬서 자원을 등록·수정·삭제하면 함께 무효화된다
  resources: ["resources", "mine"] as const,
}

export const myApi = {
  /** API-30 GET /members/me */
  getMyInfo: () => api.get<MyInfo>("/members/me"),

  /** API-31 PATCH /members/me — 직함·전화만. 보낸 필드만 바꾸고(생략은 유지) null은 비움. 바뀐 내 정보를 돌려준다 */
  updateMyInfo: (patch: MyInfoPatch) => api.patch<MyInfo>("/members/me", patch),

  /** API-35 GET /members/me/resources — 본인이 담당하는 자원 전체 (페이지 없음, 진행 중 먼저·종료일 순) */
  getMyResources: () => api.get<MyResources>("/members/me/resources"),

  /**
   * API-32 PUT /members/me/password — 성공하면 data.user. 서버는 다른 세션을 모두 끝내고 현재 세션 ID를 바꾼다.
   * 현재 비밀번호 불일치(임시 비밀번호 만료 포함) 400 CURRENT_PASSWORD_MISMATCH, 같은 비밀번호 400 NEW_PASSWORD_EQUALS_CURRENT
   */
  changePassword: (request: PasswordChangeRequest) => api.put<PasswordChanged>("/members/me/password", request),
}
