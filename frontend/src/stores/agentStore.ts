import { useSyncExternalStore } from "react"
import { agentApi, type AgentBlock, type AgentEvent } from "@/mock/api/agentApi"
import { sessionStore } from "@/session/sessionStore"
import type { AgentContext } from "@/stores/agentContextStore"

// AI Agent 패널의 상태 (0.2.1): 열림, 대화(질문·답변), 답을 받는 중인지.
// 로그인해 있는 동안 화면을 옮겨도 유지하고, 로그아웃하거나 로그인 사용자가 바뀌면 비운다.
// 질문·답변은 서버가 대화 기록으로 저장한다 (0.2.4). 마이페이지 'AI 대화 기록'(5.3.1)에서 고르면
// 그 대화를 불러와 이어서 대화하고(M11-A), '새 대화'로 비울 수 있다.
//
// 응답 이벤트는 실제로는 서버가 나눠 보낸다(SSE). 프로토타입은 받은 이벤트 목록을 시간 간격을 두고 차례로 반영한다.

/** 이벤트 사이 간격 (프로토타입에서 단계가 하나씩 나타나 보이게) */
export const AGENT_EVENT_INTERVAL_MS = 450
/** 끝(done) 이벤트를 기다리는 시간. 실제 서비스는 60초 정도, 프로토타입은 짧게 */
export const AGENT_TIMEOUT_MS = 3000
export const AGENT_TIMEOUT_MESSAGE = "응답 시간이 초과되어 답변을 만들지 못했습니다."

export type AgentStep = { stepId: string; stepName: string; status: "진행 중" | "완료"; detail: string | null }

export type AgentMessage =
  | { id: number; role: "user"; text: string }
  | {
      id: number
      role: "assistant"
      status: "streaming" | "done" | "failed"
      steps: AgentStep[]
      blocks: AgentBlock[]
      error: string | null
      /** 다시 시도·추천 카드 이동에 쓰는 질문 당시의 값 */
      question: string
      context: AgentContext
    }

type AgentState = {
  open: boolean
  conversationId: string | null
  messages: AgentMessage[]
  busy: boolean
  /** 이전 대화를 불러왔을 때 위쪽 안내 (예: 마지막 대화 시각) */
  loadedFrom: { firstQuestion: string; lastMessageAt: string } | null
}

const EMPTY: AgentState = { open: false, conversationId: null, messages: [], busy: false, loadedFrom: null }

/** 불러온 이전 대화의 답변: 추천 카드 이동에 쓰는 사례자 정보가 없다 (이름을 저장하지 않으므로) */
const RESTORED_CONTEXT: AgentContext = { screen: { screenType: "other", path: "" }, label: "이전 대화" }

export type LoadedConversation = {
  conversationId: string
  firstQuestion: string
  lastMessageAt: string
  turns: { question: string; blocks: AgentBlock[] }[]
}

let state: AgentState = EMPTY
let sequence = 0
let timers: number[] = []
let ownerMemberId: number | null = sessionStore.getMemberId()
const listeners = new Set<() => void>()

function setState(next: Partial<AgentState>) {
  state = { ...state, ...next }
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function clearTimers() {
  timers.forEach((timer) => window.clearTimeout(timer))
  timers = []
}

function updateAssistant(id: number, patch: (message: Extract<AgentMessage, { role: "assistant" }>) => Partial<Extract<AgentMessage, { role: "assistant" }>>) {
  setState({
    messages: state.messages.map((message) =>
      message.id === id && message.role === "assistant" ? { ...message, ...patch(message) } : message,
    ),
  })
}

function fail(id: number, error: string) {
  clearTimers()
  updateAssistant(id, () => ({ status: "failed", error }))
  setState({ busy: false })
}

/** 받은 이벤트 하나를 답변 말풍선에 반영 */
function apply(id: number, event: AgentEvent) {
  switch (event.event) {
    case "step":
      updateAssistant(id, (message) => {
        const exists = message.steps.some((step) => step.stepId === event.stepId)
        const step: AgentStep = { stepId: event.stepId, stepName: event.stepName, status: event.status, detail: event.detail }
        return {
          steps: exists ? message.steps.map((item) => (item.stepId === event.stepId ? step : item)) : [...message.steps, step],
        }
      })
      return
    case "answer":
      updateAssistant(id, () => ({ blocks: event.blocks }))
      return
    case "done":
      clearTimers()
      updateAssistant(id, () => ({ status: "done" }))
      setState({ busy: false, conversationId: event.conversationId })
      return
    case "error":
      fail(id, event.errorMessage)
      return
  }
}

function run(question: string, context: AgentContext) {
  const assistantId = ++sequence
  setState({
    busy: true,
    messages: [
      ...state.messages,
      { id: assistantId, role: "assistant", status: "streaming", steps: [], blocks: [], error: null, question, context },
    ],
  })
  const result = agentApi.ask({ conversationId: state.conversationId, question, screen: context.screen })
  if (!result.ok) {
    fail(assistantId, result.message)
    return
  }
  const events = result.data.events
  events.forEach((event, index) => {
    timers.push(window.setTimeout(() => apply(assistantId, event), (index + 1) * AGENT_EVENT_INTERVAL_MS))
  })
  // 끝(done)이나 오류가 오지 않으면 시간 초과로 본다 (다시 연결하지 않고 '다시 시도')
  const ended = events.some((event) => event.event === "done" || event.event === "error")
  if (!ended) {
    timers.push(
      window.setTimeout(() => fail(assistantId, AGENT_TIMEOUT_MESSAGE), events.length * AGENT_EVENT_INTERVAL_MS + AGENT_TIMEOUT_MS),
    )
  }
}

export const agentStore = {
  open() {
    setState({ open: true })
  },
  close() {
    setState({ open: false })
  },
  toggle() {
    setState({ open: !state.open })
  },

  /** 질문 보내기. 답을 받는 중이면 무시한다 (입력도 막혀 있음) */
  ask(question: string, context: AgentContext) {
    const text = question.trim()
    if (!text || state.busy) return
    setState({ messages: [...state.messages, { id: ++sequence, role: "user", text }] })
    run(text, context)
  },

  /** 실패한 답변을 같은 질문·화면으로 다시 받는다 */
  retry(messageId: number) {
    const failed = state.messages.find((message) => message.id === messageId)
    if (!failed || failed.role !== "assistant" || state.busy) return
    setState({ messages: state.messages.filter((message) => message.id !== messageId) })
    run(failed.question, failed.context)
  },

  /** '새 대화': 지금 대화를 비운다 (이미 저장되어 있어 묻지 않음). 답을 받는 중이면 무시 */
  newConversation() {
    if (state.busy) return
    clearTimers()
    setState({ conversationId: null, messages: [], loadedFrom: null })
  },

  /** 마이페이지에서 고른 이전 대화를 패널에 불러와 연다 (M11-A). 답을 받는 중이면 false */
  loadConversation(conversation: LoadedConversation): boolean {
    if (state.busy) return false
    clearTimers()
    const messages: AgentMessage[] = conversation.turns.flatMap((turn): AgentMessage[] => [
      { id: ++sequence, role: "user", text: turn.question },
      {
        id: ++sequence,
        role: "assistant",
        status: "done",
        steps: [],
        blocks: turn.blocks,
        error: null,
        question: turn.question,
        context: RESTORED_CONTEXT,
      },
    ])
    setState({
      open: true,
      conversationId: conversation.conversationId,
      messages,
      loadedFrom: { firstQuestion: conversation.firstQuestion, lastMessageAt: conversation.lastMessageAt },
    })
    return true
  },

  /** 대화 기록을 지웠을 때: 패널에 열려 있던 대화면 비운다 */
  forget(conversationId: string) {
    if (state.conversationId !== conversationId) return
    clearTimers()
    setState({ conversationId: null, messages: [], busy: false, loadedFrom: null })
  },

  /** 대화를 비우고 패널을 닫는다 (로그아웃·로그인 사용자 바뀜) */
  reset() {
    clearTimers()
    state = EMPTY
    listeners.forEach((listener) => listener())
  },
}

// 로그아웃하거나 로그인 사용자가 바뀌면 대화를 비운다
sessionStore.subscribe(() => {
  const memberId = sessionStore.getMemberId()
  if (memberId !== ownerMemberId) {
    ownerMemberId = memberId
    agentStore.reset()
  }
})

export function useAgentState(): AgentState {
  return useSyncExternalStore(subscribe, () => state)
}
