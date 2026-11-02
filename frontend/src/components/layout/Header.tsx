/**
 * 상단 헤더: 가운데 로고, 우측 AI Agent 아이콘.
 * AI Agent 패널(0.2.1)은 AI 패널 작업에서 연결한다. 그 전까지 아이콘은 눌리지 않는다.
 */
export function Header() {
  return (
    <header className="top-header">
      <div className="logo-window" aria-label="이음이">
        <img src="/assets/logo.png" alt="" />
      </div>
      <button
        type="button"
        className="ai-agent-toggle"
        aria-label="AI Agent 패널 (준비 중)"
        title="AI Agent 패널은 준비 중입니다"
        disabled
      >
        <img src="/assets/ai-agent.png" alt="" />
      </button>
    </header>
  )
}
