import { Outlet, useLocation } from "react-router"
import { AgentPanel } from "@/components/agent/AgentPanel"
import { Header } from "@/components/layout/Header"
import { Sidebar } from "@/components/layout/Sidebar"
import { PATHS } from "@/routes/paths"
import { RiskHost, riskMenuLink, useKeptRiskLocation } from "@/screens/risk/RiskHost"
import { useSession } from "@/session/sessionStore"

/**
 * 로그인 후 화면의 공통 틀: 헤더 + 좌측 메뉴바 + 본문 + AI Agent 패널(본문 오른쪽 위를 덮음)
 * - 고립 위험 탐색은 본문 맨 앞의 RiskHost가 그린다. 다른 메뉴로 가면 숨겨 두고, 메뉴의 '고립 위험 탐색'은 마지막으로 본 화면으로 돌아간다
 */
export function AppLayout() {
  const session = useSession()
  const location = useLocation()
  const riskLocation = useKeptRiskLocation(location, session.status === "authenticated" ? session.memberId : null)
  if (session.status !== "authenticated") return null
  const onRisk = location.pathname === PATHS.risk

  return (
    <>
      <Header />
      <Sidebar profile={session.profile} riskLink={onRisk || !riskLocation ? null : riskMenuLink(riskLocation)} />
      {/* 로그인 사용자가 바뀌면 본문을 다시 그려 화면 데이터를 새로 조회하게 한다 */}
      <main className="workspace" key={session.memberId}>
        {riskLocation && <RiskHost location={riskLocation} active={onRisk} />}
        <Outlet />
      </main>
      <AgentPanel />
    </>
  )
}
