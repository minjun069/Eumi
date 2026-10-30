import { NavLink, useNavigate } from "react-router"
import { authApi } from "@/mock/api/authApi"
import { PASSWORD_CHANGE_REQUIRED_MESSAGE } from "@/mock/api/core"
import { PATHS } from "@/routes/paths"
import { sessionStore } from "@/session/sessionStore"
import { leaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"
import type { MenuProfile } from "@/types/domain"

const MENUS = [
  { label: "고립 위험 탐색", to: PATHS.risk },
  { label: "복지자원 관리", to: PATHS.resources },
  { label: "사례자 관리", to: PATHS.cases },
  { label: "마이페이지", to: PATHS.my },
]

/** 0.1 공통 메뉴바: 소속 기관명·이름·직함, 메뉴 이동(0.1.1), 로그아웃(0.1.2) */
export function Sidebar({ profile }: { profile: MenuProfile }) {
  const navigate = useNavigate()
  const locked = profile.mustChangePassword

  const logout = async () => {
    // 입력 중인 내용이 있으면 먼저 묻는다 (저장하지 않은 내용 경고)
    if (!(await leaveGuard.confirmLeave())) return
    authApi.logout()
    sessionStore.signOut()
    navigate(PATHS.login, { replace: true })
  }

  return (
    <aside className="left-sidebar">
      <div className="organization">
        <strong>{profile.orgName}</strong>
        <span>{[profile.name, profile.title].filter(Boolean).join(" ")}</span>
      </div>
      <nav className={`side-menu ${locked ? "is-locked" : ""}`} aria-label="주 메뉴">
        {MENUS.map((menu) => (
          <NavLink
            key={menu.to}
            to={menu.to}
            className={({ isActive }) => (isActive ? "selected" : undefined)}
            aria-disabled={locked || undefined}
            onClick={(event) => {
              // 임시 비밀번호로 로그인했으면 비밀번호를 바꿀 때까지 메뉴를 막는다 (M3-A)
              if (!locked) return
              event.preventDefault()
              showToast(PASSWORD_CHANGE_REQUIRED_MESSAGE, "error")
            }}
          >
            {menu.label}
          </NavLink>
        ))}
      </nav>
      <button type="button" className="logout-button" onClick={logout}>
        로그아웃
      </button>
    </aside>
  )
}
