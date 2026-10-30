import { useSyncExternalStore } from "react"
import type { MenuProfile } from "@/types/domain"

// 로그인 상태 저장소.
// - 로그인 정보(토큰 역할)를 브라우저 탭의 sessionStorage에 저장한다: 회원ID + 비밀번호 변경 필요 여부.
//   → 새로고침해도 로그인은 유지되고, 탭(또는 브라우저)을 닫으면 로그아웃된다.
// - 데이터(메모리 DB)는 새로고침하면 처음 상태로 돌아가므로, 새로고침 후에는
//   저장된 회원ID로 메뉴바 사용자 정보(0.1.1)를 다시 조회해 로그인 상태를 복원한다.
// - API 흉내 함수는 getMemberId()·getMustChangePassword()를 "로그인 토큰에 담긴 값"처럼 사용한다.

export type SessionState =
  | {
      status: "anonymous"
    }
  | {
      status: "restoring"
      memberId: number
    }
  | {
      status: "authenticated"
      memberId: number
      profile: MenuProfile
    }

const STORAGE_KEY = "ieumi-v2.session.memberId"

type StoredToken = { memberId: number; mustChangePassword: boolean }

function readStoredToken(): StoredToken | null {
  try {
    const value = sessionStorage.getItem(STORAGE_KEY)
    if (!value) return null
    // 11단계까지는 회원ID 숫자만 저장했다
    if (/^\d+$/.test(value)) return { memberId: Number(value), mustChangePassword: false }
    const parsed = JSON.parse(value) as Partial<StoredToken>
    return typeof parsed.memberId === "number"
      ? { memberId: parsed.memberId, mustChangePassword: parsed.mustChangePassword === true }
      : null
  } catch {
    return null
  }
}

function writeStoredToken(token: StoredToken | null) {
  try {
    if (token === null) sessionStorage.removeItem(STORAGE_KEY)
    else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(token))
  } catch {
    // 저장소를 쓸 수 없는 환경에서는 새로고침 시 로그아웃된다
  }
}

let token = readStoredToken()
let state: SessionState =
  token === null
    ? { status: "anonymous" }
    : { status: "restoring", memberId: token.memberId }

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
    return state.status === "anonymous" ? null : state.memberId
  },

  /** 로그인 정보에 담긴 '비밀번호 변경 필요' (임시 비밀번호로 로그인, M3-A) */
  getMustChangePassword(): boolean {
    return state.status !== "anonymous" && token?.mustChangePassword === true
  },

  /** 로그인 성공 또는 상황 전환으로 로그인 사용자를 정한다 */
  signIn(profile: MenuProfile) {
    token = { memberId: profile.memberId, mustChangePassword: profile.mustChangePassword }
    writeStoredToken(token)
    setState({ status: "authenticated", memberId: profile.memberId, profile })
  },

  /** 새로고침 후 메뉴바 사용자 정보를 다시 받아 복원을 마친다 */
  completeRestore(profile: MenuProfile) {
    setState({ status: "authenticated", memberId: profile.memberId, profile })
  },

  /** 메뉴바 정보가 바뀌었을 때(예: 직함 수정, 비밀번호 변경) 다시 반영한다 */
  updateProfile(profile: MenuProfile) {
    if (state.status !== "authenticated") return
    token = { memberId: profile.memberId, mustChangePassword: profile.mustChangePassword }
    writeStoredToken(token)
    setState({ ...state, profile })
  },

  signOut() {
    token = null
    writeStoredToken(null)
    setState({ status: "anonymous" })
  },
}

export function useSession(): SessionState {
  return useSyncExternalStore(subscribe, sessionStore.getState)
}
