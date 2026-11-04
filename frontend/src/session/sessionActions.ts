import { authApi, type LoginUser } from "@/api/authApi"
import { prepareCsrf } from "@/api/csrf"
import { errorMessage, isApiError, MESSAGES } from "@/api/errors"
import { setAuthHandlers } from "@/api/http"
import { sessionStore } from "@/session/sessionStore"
import { showToast } from "@/stores/toastStore"

let restoring: Promise<void> | null = null

/** 앱 시작·새로고침 때 서버 세션으로 로그인 상태를 복원한다 (API-01) */
export function restoreSession(): Promise<void> {
  restoring ??= authApi
    .getMe()
    .then(
      (profile) => sessionStore.signIn(profile),
      (error) => {
        sessionStore.signOut()
        // 401은 로그인하지 않은 정상 상태다. 그 밖의 실패만 알린다
        if (!(isApiError(error) && error.status === 401)) showToast(errorMessage(error), "error")
      },
    )
    .finally(() => {
      restoring = null
    })
  return restoring
}

/** 메뉴 프로필을 다시 받는다 (API-01). 내 정보 수정 뒤 머리글·메뉴의 직함을 서버 값으로 맞춘다 */
export async function refreshProfile(): Promise<void> {
  try {
    sessionStore.updateProfile(await authApi.getMe())
  } catch {
    // 실패하면 다음 새로고침 때 복원된다. 로그인 만료는 다른 요청의 401 처리가 맡는다
  }
}

/** 로그인 성공 (API-08 data.user) → 로그인 상태로 바꾼다 */
export function completeLogin(user: LoginUser) {
  const { memberId, name, orgName, title, jurisdictionSidoCode, jurisdictionSigunguCode, mustChangePassword } = user
  sessionStore.signIn({ memberId, name, orgName, title, jurisdictionSidoCode, jurisdictionSigunguCode, mustChangePassword })
  // 로그인하면 서버가 CSRF 토큰을 새로 정하므로 다시 준비한다
  prepareCsrf(true).catch(() => {})
}

/** 로그아웃 (API-02). 서버 세션이 이미 없어도 화면은 로그아웃 상태로 바꾼다 */
export async function logout(): Promise<void> {
  try {
    await authApi.logout()
  } catch {
    // 이미 만료된 세션 등: 화면 쪽 정리는 계속한다
  }
  sessionStore.signOut()
  // 로그아웃 뒤에는 CSRF 토큰을 다시 준비한다
  prepareCsrf(true).catch(() => {})
}

/** 다른 요청에서 401·비밀번호 변경 필요를 받았을 때의 처리. main.tsx에서 한 번 등록한다 */
export function registerAuthHandlers() {
  setAuthHandlers({
    onUnauthorized: () => {
      if (sessionStore.getState().status !== "authenticated") return
      sessionStore.signOut()
      showToast(MESSAGES.sessionExpired, "error")
    },
    onPasswordChangeRequired: () => {
      sessionStore.requirePasswordChange()
      showToast(MESSAGES.passwordChangeRequired, "error")
    },
  })
}
