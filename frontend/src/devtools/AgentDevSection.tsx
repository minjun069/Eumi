import { useNavigate } from "react-router"
import { devAgent } from "@/devtools/devAgent"
import { devCases } from "@/devtools/devCases"
import { PATHS } from "@/routes/paths"
import { useSession } from "@/session/sessionStore"
import { useCurrentAgentContext } from "@/stores/agentContextStore"
import { agentStore } from "@/stores/agentStore"

/** 개발용 영역의 'AI Agent' 도구: 응답 실패·시간 초과, 추천 상황별 사례자 바로 열기, 이름이 적힌 상담 넣기 */
export function AgentDevSection() {
  const session = useSession()
  const navigate = useNavigate()
  const context = useCurrentAgentContext()
  if (session.status !== "authenticated") return null

  const openCase = (name: string) => {
    const caseId = devCases.findCaseId(name)
    if (caseId) navigate(PATHS.caseDetail(caseId))
  }
  const caseId = context?.screen.screenType === "case-detail" ? context.screen.caseId : null

  return (
    <section className="dev-section">
      <h2 className="dev-title">
        AI Agent <span className="dev-count">0.2 패널</span>
      </h2>
      <div className="dev-scenario-actions">
        <button type="button" className="dev-button" onClick={() => agentStore.open()}>
          패널 열기
        </button>
        <button type="button" className="dev-button" onClick={() => devAgent.setNextFault("error")}>
          다음 응답 중간에 실패
        </button>
        <button type="button" className="dev-button" onClick={() => devAgent.setNextFault("timeout")}>
          다음 응답 시간 초과
        </button>
        <button
          type="button"
          className="dev-button"
          disabled={caseId === null}
          title={caseId === null ? "사례자 상세에서 쓸 수 있습니다" : undefined}
          onClick={() => caseId !== null && devAgent.addNamedConsultation(caseId)}
        >
          이름이 적힌 상담 넣기
        </button>
      </div>
      <div className="dev-group">
        <span className="dev-group-title">추천 상황별 사례자 열기</span>
        <div className="dev-scenario-actions">
          <button type="button" className="dev-button" onClick={() => openCase("이영자")}>
            여러 개 추천 (이영자)
          </button>
          <button type="button" className="dev-button" onClick={() => openCase("김이음")}>
            종료 자원까지 넓힘 (김이음)
          </button>
          <button type="button" className="dev-button" onClick={() => openCase("최민준")}>
            추천 결과 없음 (최민준)
          </button>
          <button type="button" className="dev-button" onClick={() => openCase("차유진")}>
            상담 기록 없음 (차유진)
          </button>
        </div>
      </div>
    </section>
  )
}
