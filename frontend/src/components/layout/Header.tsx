import { useSession } from "@/session/sessionStore"
import { agentStore, useAgentState } from "@/stores/agentStore"

/**
 * 상단 헤더: 가운데 로고, 우측 AI Agent 아이콘 (0.2.1 누르면 AI Agent 패널을 열고 닫는다).
 * 임시 비밀번호로 로그인해 비밀번호를 바꿔야 하면 아이콘을 막는다 (M3-A)
 */
export function Header() {
  const { open } = useAgentState()
  const session = useSession()
  const locked = session.status === "authenticated" && session.profile.mustChangePassword
  return (
    <header className="top-header">
      <div className="logo-window" aria-label="이음이">
        <img src="/assets/logo.png" alt="" />
      </div>
      <button
        type="button"
        className={`ai-agent-toggle ${open ? "is-open" : ""}`}
        aria-label={open ? "AI Agent 패널 닫기" : "AI Agent 패널 열기"}
        aria-expanded={open}
        disabled={locked}
        title={locked ? "비밀번호를 변경한 뒤 쓸 수 있습니다" : undefined}
        onClick={() => agentStore.toggle()}
      >
        <img src="/assets/ai-agent.png" alt="" />
      </button>
    </header>
  )
}
