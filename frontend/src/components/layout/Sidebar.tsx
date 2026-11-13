import { NavLink, useNavigate } from "react-router"
import { MESSAGES } from "@/api/errors"
import type { MenuProfile } from "@/api/types"
import { PATHS } from "@/routes/paths"
import { logout } from "@/session/sessionActions"
import { leaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"

const MENUS = [
  { label: "고립 위험 탐색", to: PATHS.risk },
  { label: "복지자원 관리", to: PATHS.resources },
  { label: "사례자 관리", to: PATHS.cases },
  { label: "마이페이지", to: PATHS.my },
]

/**
 * 0.1 공통 메뉴바: 소속 기관명·이름·직함, 메뉴 이동(0.1.1), 로그아웃(0.1.2)
 * - riskLink가 있으면(다른 메뉴에 있고 고립 위험 탐색을 본 적이 있으면) '고립 위험 탐색'은 마지막으로 본 화면(조건 · 읍면동)으로 간다.
 *   숨겨 둔 화면이 그대로 보인다 (RiskHost)
 */
export function Sidebar({
  profile,
  riskLink,
}: {
  profile: MenuProfile
  riskLink: { pathname: string; search: string; state: unknown } | null
}) {
  const navigate = useNavigate()
  const locked = profile.mustChangePassword

  const onLogout = async () => {
    // 입력 중인 내용이 있으면 먼저 묻는다 (저장하지 않은 내용 경고)
    if (!(await leaveGuard.confirmLeave())) return
    await logout()
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
            to={
              menu.to === PATHS.risk && riskLink ? { pathname: riskLink.pathname, search: riskLink.search } : menu.to
            }
            state={menu.to === PATHS.risk ? riskLink?.state : undefined}
            className={({ isActive }) => (isActive ? "selected" : undefined)}
            aria-disabled={locked || undefined}
            onClick={(event) => {
              // 임시 비밀번호로 로그인했으면 비밀번호를 바꿀 때까지 메뉴를 막는다 (FR-003)
              if (!locked) return
              event.preventDefault()
              showToast(MESSAGES.passwordChangeRequired, "error")
            }}
          >
            {menu.label}
          </NavLink>
        ))}
      </nav>
      <button type="button" className="logout-button" onClick={onLogout}>
        로그아웃
      </button>
    </aside>
  )
}
