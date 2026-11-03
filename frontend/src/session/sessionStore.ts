import { useSyncExternalStore } from "react"
import { queryClient } from "@/api/queryClient"
import type { MenuProfile } from "@/api/types"

// 로그인 상태 저장소.
// - 로그인 근거는 서버 세션(SESSION 쿠키, HttpOnly)뿐이다. 브라우저에 회원 ID·토큰을 저장하지 않는다.
// - 앱을 열거나 새로고침하면 "restoring"에서 시작해 GET /api/auth/me로 복원한다 (sessionActions.restoreSession).
// - 여기 회원 ID는 화면 표시·캐시 구분용이다. 서버 권한 판단에 쓰지 않는다.

export type SessionState =
  | { status: "restoring" }
  | { status: "anonymous" }
  | { status: "authenticated"; memberId: number; profile: MenuProfile }

let state: SessionState = { status: "restoring" }
const listeners = new Set<() => void>()

function setState(next: SessionState) {
  state = next
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export const sessionStore = {
  getState: () => state,

  /** 로그인 상태가 바뀔 때 알림 받기 (화면 밖 저장소용, 예: AI 대화 비우기) */
  subscribe,

  getMemberId(): number | null {
    return state.status === "authenticated" ? state.memberId : null
  },

  /** 로그인 성공 또는 새로고침 복원으로 로그인 사용자를 정한다 */
  signIn(profile: MenuProfile) {
    // 다른 회원으로 바뀌면 이전 회원의 화면 데이터를 남기지 않는다
    if (state.status === "authenticated" && state.memberId !== profile.memberId) queryClient.clear()
    setState({ status: "authenticated", memberId: profile.memberId, profile })
  },

  /** 메뉴바 정보가 바뀌었을 때(직함 수정, 비밀번호 변경) 다시 반영한다 */
  updateProfile(profile: MenuProfile) {
    if (state.status !== "authenticated") return
    setState({ ...state, profile })
  },

  /** 서버가 403 PASSWORD_CHANGE_REQUIRED를 보냈을 때: 비밀번호 변경 화면만 쓰게 한다 */
  requirePasswordChange() {
    if (state.status !== "authenticated" || state.profile.mustChangePassword) return
    setState({ ...state, profile: { ...state.profile, mustChangePassword: true } })
  },

  /** 로그아웃·로그인 만료: 개인 데이터 캐시를 모두 비운다 */
  signOut() {
    queryClient.clear()
    setState({ status: "anonymous" })
  },
}

export function useSession(): SessionState {
  return useSyncExternalStore(subscribe, sessionStore.getState)
}
