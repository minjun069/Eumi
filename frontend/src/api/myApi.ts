import { api } from "@/api/http"
import type { Schemas, SuccessData } from "@/api/types"

// 마이페이지 (로그인한 회원 본인 정보만)

export type MyInfo = SuccessData<"myApi_getMyInfo_Success">
export type MyInfoPatch = Schemas["MyInfoPatch"]
export type MyResources = SuccessData<"myApi_getMyResources_Success">
export type PasswordChangeRequest = Schemas["PasswordChangeRequest"]
/** 비밀번호 변경 성공: 최신 로그인 사용자 (임시 비밀번호 제한이 풀린 상태) */
export type PasswordChanged = SuccessData<"myApi_changePassword_Success">
/** 탈퇴 안내: 넘길 사례자·진행 중 자원, 넘겨받을 수 있는 회원, 처리되는 데이터 수 */
export type WithdrawalInfo = Schemas["WithdrawalInfo"]
export type WithdrawalRequest = Schemas["WithdrawalRequest"]

export const myKeys = {
  info: ["my", "info"] as const,
  // 복지자원 쿼리(["resources", …]) 아래에 둬서 자원을 등록·수정·삭제하면 함께 무효화된다
  resources: ["resources", "mine"] as const,
  withdrawal: ["my", "withdrawal"] as const,
}

export const myApi = {
  /** API-30 GET /members/me */
  getMyInfo: () => api.get<MyInfo>("/members/me"),

  /** API-31 PATCH /members/me — 직함·전화만. 보낸 필드만 바꾸고(생략은 유지) null은 비움. 바뀐 내 정보를 돌려준다 */
  updateMyInfo: (patch: MyInfoPatch) => api.patch<MyInfo>("/members/me", patch),

  /** API-35 GET /members/me/resources — 본인이 담당하는 자원 전체 (페이지 없음, 진행 중 먼저·종료일 순) */
  getMyResources: () => api.get<MyResources>("/members/me/resources"),

  /**
   * API-32 PUT /members/me/password — 성공하면 data.user. 서버는 다른 세션을 모두 끝내고 현재 세션 ID를 바꾸며 CSRF 토큰을 지운다.
   * 현재 비밀번호 불일치(임시 비밀번호 만료 포함) 400 CURRENT_PASSWORD_MISMATCH, 같은 비밀번호 400 NEW_PASSWORD_EQUALS_CURRENT.
   * 세션이 바뀌므로 runExclusive 안에서 부른다 (그동안 다른 요청을 멈춘다)
   */
  changePassword: (request: PasswordChangeRequest) =>
    api.put<PasswordChanged>("/members/me/password", request, { exclusive: true }),

  /** API-33 GET /members/me/withdrawal — 탈퇴 안내 (조회 시점 기준. 제출 때 바뀌어 있으면 API-34가 409) */
  getWithdrawalInfo: () => api.get<WithdrawalInfo>("/members/me/withdrawal"),

  /**
   * API-34 POST /members/me/withdrawal — 204. 인계·대화 삭제·탈퇴·모든 세션 삭제를 한 번에 하고 SESSION 쿠키를 만료시킨다.
   * transfers·resourceTransfers는 현재 넘길 대상과 정확히 같아야 한다 (다르거나 후임이 무효면 409 STATE_CONFLICT).
   * 비밀번호 불일치 400 WITHDRAW_PASSWORD_MISMATCH, 이미 탈퇴함 404. 세션이 없어지므로 runExclusive 안에서 부른다
   */
  withdraw: (request: WithdrawalRequest) =>
    api.post<void>("/members/me/withdrawal", request, { exclusive: true }),
}
