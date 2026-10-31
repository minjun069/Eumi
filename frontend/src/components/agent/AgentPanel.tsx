import { useEffect, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router"
import { fallbackAgentContext } from "@/components/agent/agentFallback"
import { Emphasized } from "@/components/common/Emphasized"
import { exampleQuestions } from "@/mock/agent/agentExamples"
import type { AgentBlock, RecommendationCard } from "@/mock/api/agentApi"
import { PATHS } from "@/routes/paths"
import { useCurrentAgentContext, type AgentContext } from "@/stores/agentContextStore"
import { agentStore, useAgentState, type AgentMessage, type AgentStep } from "@/stores/agentStore"

/**
 * 0.2 AI Agent 패널 (11단계): 헤더의 AI 아이콘으로 열고, 본문 오른쪽 위를 덮는다 (A1-A).
 * - 지금 보는 화면을 참고해 답한다 (0.2.2). 단계가 하나씩 나타나고(A2-B), 답이 오면 접힌다
 * - 사례자 상세의 'AI 맞춤 자원 추천'은 정해진 질문으로 같은 API를 부른다 (A4-A), 추천 카드(A5-A)
 */
export function AgentPanel() {
  const { open, messages, busy, loadedFrom } = useAgentState()
  const location = useLocation()
  const registered = useCurrentAgentContext()
  const context = registered ?? fallbackAgentContext(location.pathname)
  const [draft, setDraft] = useState("")
  const scrollRef = useRef<HTMLDivElement>(null)

  // 마지막 질문이 맨 위에 오도록 스크롤한다 (답이 길어도 첫 줄·첫 카드부터 읽게).
  // 답이 아래에 붙어 높이가 늘 때마다 다시 맞춘다
  useEffect(() => {
    const box = scrollRef.current
    if (!box) return
    // 이전 대화를 막 불러왔으면(마지막 답이 불러온 답) 맨 위의 안내부터 보여 준다
    const last = messages[messages.length - 1]
    if (loadedFrom && last?.role === "assistant" && last.status === "done" && last.steps.length === 0) {
      box.scrollTo({ top: 0 })
      return
    }
    const question = box.querySelector<HTMLElement>(".agent-question:last-of-type")
    box.scrollTo({ top: question ? question.offsetTop - box.offsetTop - 14 : box.scrollHeight })
  }, [messages, open, loadedFrom])

  const send = (question: string) => {
    if (!question.trim() || busy) return
    agentStore.ask(question, context)
    setDraft("")
  }

  return (
    <aside className={`agent-panel ${open ? "is-open" : ""}`} aria-label="AI Agent 패널" aria-hidden={!open} inert={!open}>
      <header className="agent-head">
        <img src="/assets/ai-agent.png" alt="" />
        <strong>AI 업무 파트너 이랑이</strong>
        <button
          type="button"
          className="btn btn-outline btn-small agent-new"
          disabled={busy || messages.length === 0}
          title="지금 대화는 저장되어 있어 마이페이지 'AI 대화 기록'에서 다시 볼 수 있습니다"
          onClick={() => agentStore.newConversation()}
        >
          새 대화
        </button>
        <button type="button" className="agent-close" aria-label="AI Agent 패널 닫기" onClick={() => agentStore.close()}>
          ×
        </button>
      </header>
      <p className="agent-context">
        <span>지금 보는 화면</span> {context.label}
      </p>

      <div className="agent-messages" ref={scrollRef}>
        {loadedFrom && (
          <p className="agent-loaded">
            이전 대화를 불러왔어요 · 마지막 대화 {loadedFrom.lastMessageAt.slice(0, 16)}
            <br />
            이어서 질문하면 같은 대화에 저장돼요.
          </p>
        )}
        {messages.length === 0 && (
          <div className="agent-greeting">
            <p>무엇을 도와드릴까요? 지금 보는 화면의 내용을 참고해 답해요.</p>
            <p className="agent-note">
              사례자 정보는 이름·관리번호·생년월일을 빼고 AI에 전달해요. 대화는 이름을 가려 저장하고, 마이페이지 'AI 대화
              기록'에서 다시 볼 수 있어요.
            </p>
          </div>
        )}
        {messages.map((message) =>
          message.role === "user" ? (
            <p key={message.id} className="agent-question">
              {message.text}
            </p>
          ) : (
            <AssistantMessage key={message.id} message={message} />
          ),
        )}
      </div>

      <footer className="agent-input">
        <div className="agent-examples" aria-label="예시 질문">
          {exampleQuestions(context.screen).map((question) => (
            <button key={question} type="button" className="agent-chip" disabled={busy} onClick={() => send(question)}>
              {question}
            </button>
          ))}
        </div>
        <div className="agent-compose">
          <textarea
            className="input"
            aria-label="AI에게 질문"
            placeholder={busy ? "답변을 만드는 중이에요…" : "궁금한 점을 입력하세요 (Enter로 보내기)"}
            value={draft}
            disabled={busy}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                send(draft)
              }
            }}
          />
          <button type="button" className="btn btn-primary" disabled={busy || !draft.trim()} onClick={() => send(draft)}>
            보내기
          </button>
        </div>
      </footer>
    </aside>
  )
}

function AssistantMessage({ message }: { message: Extract<AgentMessage, { role: "assistant" }> }) {
  return (
    <div className={`agent-answer is-${message.status}`}>
      {message.status === "streaming" ? (
        <StepList steps={message.steps} />
      ) : (
        message.steps.length > 0 && (
          <details className="agent-steps-done">
            <summary>진행한 단계 {message.steps.filter((step) => step.status === "완료").length}개</summary>
            <StepList steps={message.steps} />
          </details>
        )
      )}
      {message.status === "streaming" && message.blocks.length === 0 && <p className="agent-working">답변을 만드는 중…</p>}
      {message.blocks.map((block, index) => (
        <AnswerBlock key={index} block={block} context={message.context} />
      ))}
      {message.status === "failed" && (
        <div className="agent-failed">
          <p>{message.error}</p>
          <button type="button" className="btn btn-outline btn-small" onClick={() => agentStore.retry(message.id)}>
            다시 시도
          </button>
        </div>
      )}
    </div>
  )
}

function StepList({ steps }: { steps: AgentStep[] }) {
  return (
    <ol className="agent-steps">
      {steps.map((step) => (
        <li key={step.stepId} className={step.status === "완료" ? "is-done" : "is-running"}>
          <i aria-hidden="true">{step.status === "완료" ? "✓" : "…"}</i>
          <span>
            {step.stepName}
            {step.status === "완료" && step.detail && <em> — {step.detail}</em>}
          </span>
        </li>
      ))}
    </ol>
  )
}

function AnswerBlock({ block, context }: { block: AgentBlock; context: AgentContext }) {
  if (block.kind === "text") {
    return (
      <p className="agent-text">
        <Emphasized text={block.text} />
      </p>
    )
  }
  if (block.kind === "list") {
    return (
      <ul className="agent-list">
        {block.items.map((item) => (
          <li key={item}>
            <Emphasized text={item} />
          </li>
        ))}
      </ul>
    )
  }
  return (
    <div className="rec-cards">
      {block.cards.map((card) => (
        <ResourceCard key={card.resourceId} card={card} context={context} />
      ))}
    </div>
  )
}

const CHECK_ICONS = { met: "✓", unmet: "!", unknown: "?" } as const

function ResourceCard({ card, context }: { card: RecommendationCard; context: AgentContext }) {
  const navigate = useNavigate()
  return (
    <article className="rec-card" aria-label={`${card.rank}순위 ${card.resourceName}`}>
      <header className="rec-head">
        <span className="rec-rank">{card.rank}순위</span>
        <strong>{card.resourceName}</strong>
      </header>
      <p className="rec-meta">
        {card.operatingOrgName} ·{" "}
        <span className={`status-badge ${card.status === "종료" ? "is-ended" : "is-active"}`}>{card.status}</span>
      </p>
      <div className="rec-tags">
        {card.tags.map((tag) => (
          <span key={tag}>{tag}</span>
        ))}
      </div>
      <h4>추천 이유</h4>
      <p>{card.reason}</p>
      <h4>조건 확인</h4>
      <ul className="rec-checks">
        {card.checks.map((check) => (
          <li key={check.label} className={`is-${check.state}`}>
            <i aria-hidden="true">{CHECK_ICONS[check.state]}</i>
            {check.label} — {check.note}
          </li>
        ))}
      </ul>
      <h4>이용 전 확인</h4>
      <ul className="rec-before">
        {card.beforeUse.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <h4>근거</h4>
      <p className="rec-evidence">{card.evidence}</p>
      <button
        type="button"
        className="btn btn-primary btn-small"
        onClick={() =>
          navigate(PATHS.resourceDetail(card.resourceId), {
            state: context.caseRef ? { recommendedFor: context.caseRef } : undefined,
          })
        }
      >
        자원 상세 보기
      </button>
    </article>
  )
}
