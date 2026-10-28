import type { ReactNode } from "react"
import { Navigate, useLocation } from "react-router"
import { PATHS } from "@/routes/paths"
import { useSession } from "@/session/sessionStore"

/**
 * 1.2.1 회원가입·비밀번호 찾기를 제외한 화면은 로그인한 경우에만 볼 수 있다.
 * 로그인하지 않은 상태로 접근하면 로그인 화면으로 보낸다.
 * 임시 비밀번호로 로그인해 '비밀번호 변경 필요'이면 비밀번호 변경 화면(5.1.3)만 보여 준다 (M3-A).
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const session = useSession()
  const location = useLocation()

  // 새로고침 직후 로그인 상태를 복원하는 중에는 아무것도 그리지 않는다
  if (session.status === "restoring") return null

  if (session.status === "anonymous")
    return <Navigate to={PATHS.login} replace />

  if (session.profile.mustChangePassword && location.pathname !== PATHS.myPassword)
    return <Navigate to={PATHS.myPassword} replace />

  return children
}
