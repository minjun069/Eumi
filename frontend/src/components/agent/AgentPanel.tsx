import "@/styles/agent.css"
import { useEffect, useMemo, useRef, useState } from "react"
import type { AgentMessage } from "@/api/agentApi"
import { AgentArtifacts } from "@/components/agent/AgentArtifacts"
import { type AnswerArtifacts, artifactsByAnswer } from "@/components/agent/artifactData"
import { EXAMPLE_QUESTIONS } from "@/components/agent/agentExamples"
import { Emphasized } from "@/components/common/Emphasized"
import { AGENT_MESSAGES, agentStore, isEndRow, useAgentState } from "@/stores/agentStore"
import { useScreenContextValue } from "@/stores/screenContextStore"
import { formatDateTime } from "@/utils/datetime"

/**
 * AI Agent 패널 (FR-071~079): 헤더의 AI 아이콘으로 열고, 본문 오른쪽 위를 덮는다.
 * - 질문 행 → 진행 행(단계 이름, 상세는 펼쳐 보기) → 끝 행(완료 답변 / 실패 + 다시 질문 / 중단)
 * - 실행 중에는 보내기를 막고 중단 버튼을 보인다
 * - 위험 탐색 · 읍면동 화면에서는 질문에 화면 문맥(동 · 기준 월)을 붙이고, 입력칸 바로 위에 함께 가는 값을 보인다 (ai-agent-panel.md 3-1)
 * - 완료 행의 artifacts(Tableau 카드, 정화한 표·SVG)를 답변 아래에 그린다 (AgentArtifacts, 내부_연동_변경_계획.md 2-7)
 */
export function AgentPanel() {
  const { open, messages, running, sending, cancelling, notice, loadedFrom } = useAgentState()
  const screen = useScreenContextValue()
  const busy = running || sending
  const [draft, setDraft] = useState("")
  const scrollRef = useRef<HTMLDivElement>(null)
  const turns = toTurns(messages)
  // 완료 행마다 그릴 산출물. 앞 답변에 이미 나온 그래프·표는 다시 그리지 않는다
  const artifacts = useMemo(
    () => artifactsByAnswer(messages.filter((message) => message.status === "완료")),
    [messages],
  )

  // 마지막 질문이 맨 위에 오도록 스크롤한다 (답이 길어도 첫 줄부터 읽게).
  // 답이 아래에 붙어 높이가 늘 때마다 다시 맞춘다
  useEffect(() => {
    const box = scrollRef.current
    if (!box) return
    // 이전 대화를 막 불러왔으면 맨 위의 안내부터 보여 준다
    if (loadedFrom && !running) {
      box.scrollTo({ top: 0 })
      return
    }
    const question = box.querySelector<HTMLElement>(".agent-question:last-of-type")
    box.scrollTo({ top: question ? question.offsetTop - box.offsetTop - 14 : box.scrollHeight })
  }, [messages, open, loadedFrom, running])

  const send = async (question: string) => {
    if (!question.trim() || busy) return
    // 질문이 저장되지 않았으면(409·통신 오류 등) 입력한 내용을 그대로 둔다
    if (await agentStore.ask(question)) setDraft("")
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
          title="대화는 저장되어 있어 마이페이지 'AI 대화 기록'에서 다시 볼 수 있습니다"
          onClick={() => agentStore.newConversation()}
        >
          새 대화
        </button>
        <button type="button" className="agent-close" aria-label="AI Agent 패널 닫기" onClick={() => agentStore.close()}>
          ×
        </button>
      </header>

      <div className="agent-messages" ref={scrollRef}>
        {loadedFrom && (
          <p className="agent-loaded">
            이전 대화를 불러왔어요 · 마지막 대화 {formatDateTime(loadedFrom.lastMessageAt)}
            <br />
            이어서 질문하면 같은 대화에 저장돼요.
          </p>
        )}
        {turns.length === 0 && (
          <div className="agent-greeting">
            <p>무엇을 도와드릴까요?</p>
            <p className="agent-note">
              개인정보는 되도록 입력하지 마세요. 이메일, 010-0000-0000 형식의 휴대전화 번호, '이름:'·'생년월일:' 뒤에
              적은 값(;이나 줄 바꿈 전까지)만 가려서 저장하고 나머지 내용은 그대로 저장돼요.
              <br />
              대화는 마이페이지 'AI 대화 기록'에서 다시 볼 수 있어요.
            </p>
          </div>
        )}
        {turns.map((turn) => (
          <Turn
            key={turn.question.messageId}
            turn={turn}
            busy={busy}
            artifacts={turn.end ? artifacts.get(turn.end.messageId) : undefined}
          />
        ))}
      </div>

      <footer className="agent-input">
        {notice && (
          <p className="agent-notice" role="status">
            {notice}
          </p>
        )}
        <div className="agent-examples" aria-label="예시 질문">
          {EXAMPLE_QUESTIONS.map((question) => (
            <button key={question} type="button" className="agent-chip" disabled={busy} onClick={() => void send(question)}>
              {question}
            </button>
          ))}
        </div>
        {screen && (
          <p className="agent-context" title="질문과 함께 보내는 화면 정보예요. 질문에 다른 동이나 기간을 적으면 질문을 따라요.">
            {screen.label}
          </p>
        )}
        <div className="agent-compose">
          <textarea
            className="input"
            aria-label="AI에게 질문"
            placeholder={busy ? "답변을 만드는 중이에요…" : "궁금한 점을 입력하세요 (Enter로 보내기, Shift+Enter로 줄 바꿈)"}
            value={draft}
            disabled={busy}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void send(draft)
              }
            }}
          />
          {running ? (
            <button type="button" className="btn btn-outline" disabled={cancelling} onClick={() => void agentStore.cancel()}>
              {cancelling ? "중단하는 중…" : "중단"}
            </button>
          ) : (
            <button type="button" className="btn btn-primary" disabled={sending || !draft.trim()} onClick={() => void send(draft)}>
              보내기
            </button>
          )}
        </div>
      </footer>
    </aside>
  )
}

/** 질문 하나와 그 질문을 가리키는 AI 행들 */
type AgentTurn = { question: AgentMessage; steps: AgentMessage[]; end: AgentMessage | null }

function toTurns(messages: AgentMessage[]): AgentTurn[] {
  const turns: AgentTurn[] = []
  const byQuestion = new Map<number, AgentTurn>()
  for (const message of messages) {
    if (message.status === "질문") {
      const turn: AgentTurn = { question: message, steps: [], end: null }
      turns.push(turn)
      byQuestion.set(message.messageId, turn)
      continue
    }
    // 질문 행을 받지 못한 AI 행은 붙일 곳이 없어 건너뛴다
    const turn = message.questionId === null ? undefined : byQuestion.get(message.questionId)
    if (!turn) continue
    if (isEndRow(message)) turn.end = message
    else turn.steps.push(message)
  }
  return turns
}

function Turn({ turn, busy, artifacts }: { turn: AgentTurn; busy: boolean; artifacts: AnswerArtifacts | undefined }) {
  const { question, steps, end } = turn
  const status = end === null ? "running" : end.status === "완료" ? "done" : end.status === "실패" ? "failed" : "cancelled"
  return (
    <>
      <p className="agent-question">{question.content}</p>
      <div className={`agent-answer is-${status}`}>
        {end === null ? (
          <StepList steps={steps} end={end} />
        ) : (
          steps.length > 0 && (
            <details className="agent-steps-done">
              <summary>진행한 단계 {steps.length}개</summary>
              <StepList steps={steps} end={end} />
            </details>
          )
        )}
        {end === null && <p className="agent-working">답변을 만드는 중…</p>}
        {end?.status === "완료" && (
          <>
            <p className="agent-text">
              <Emphasized text={end.content ?? ""} />
            </p>
            {/* 진행 행의 artifacts는 그리지 않는다 (같은 그래프가 겹친다) */}
            <AgentArtifacts answer={artifacts} />
          </>
        )}
        {end?.status === "실패" && (
          <div className="agent-failed">
            <p>{AGENT_MESSAGES.failed}</p>
            <button
              type="button"
              className="btn btn-outline btn-small"
              disabled={busy}
              onClick={() => agentStore.retry(question.messageId)}
            >
              다시 질문
            </button>
          </div>
        )}
        {end?.status === "취소" && <p className="agent-cancelled">{AGENT_MESSAGES.cancelled}</p>}
      </div>
    </>
  )
}

/** 진행 행: 단계 하나 = 행 하나. 다음 단계나 끝 행이 들어오면 앞 단계가 끝난 것이다 */
function StepList({ steps, end }: { steps: AgentMessage[]; end: AgentMessage | null }) {
  return (
    <ol className="agent-steps">
      {steps.map((step, index) => {
        const last = index === steps.length - 1
        const state = !last || end?.status === "완료" ? "done" : end === null ? "running" : "stopped"
        return (
          <li key={step.messageId} className={`is-${state}`}>
            <i aria-hidden="true">{state === "done" ? "✓" : state === "running" ? "…" : "–"}</i>
            {step.details ? (
              <details className="agent-step-details">
                <summary>{step.content}</summary>
                <p>{step.details}</p>
              </details>
            ) : (
              <span>{step.content}</span>
            )}
          </li>
        )
      })}
    </ol>
  )
}
