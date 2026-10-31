import { useLocation, useNavigate } from "react-router"
import { AgentDevSection } from "@/devtools/AgentDevSection"
import { ApiLogPanel } from "@/devtools/ApiLogPanel"
import { DevScenarioPanel } from "@/devtools/DevScenarioPanel"
import { ScenarioSwitcher } from "@/devtools/ScenarioSwitcher"
import { PATHS } from "@/routes/paths"

/**
 * 1440×1024 화면 바깥 오른쪽의 개발용 영역 (서비스 화면이 아님).
 * 위: 화면 흐름도 버튼, 상황 전환(로그인 사용자), 예외 상황(화면별), AI Agent 도구 / 아래: API 기록
 */
export function DevPanel() {
  const navigate = useNavigate()
  const location = useLocation()
  const onFlow = location.pathname === PATHS.flow

  return (
    <aside className="dev-panel" aria-label="프로토타입 도구">
      <div className="dev-panel-head">
        <strong>프로토타입 도구</strong>
        <span>서비스 화면이 아닌 개발용 영역</span>
      </div>
      <section className="dev-section">
        <button
          type="button"
          className="dev-button dev-button-wide"
          aria-current={onFlow ? "page" : undefined}
          onClick={() => navigate(PATHS.flow)}
        >
          화면 흐름도 보기
        </button>
      </section>
      <ScenarioSwitcher />
      <DevScenarioPanel />
      <AgentDevSection />
      <ApiLogPanel />
    </aside>
  )
}
