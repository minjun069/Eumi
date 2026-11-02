import { useSyncExternalStore } from "react"
import {
  AGENT_STREAM_EVENTS,
  agentApi,
  type AgentBlock,
  type AgentRunState,
  type AgentStreamEvent,
  type ProgressStep,
} from "@/api/agentApi"
import { errorMessage, isApiError } from "@/api/errors"
import { sessionStore } from "@/session/sessionStore"
import type { AgentContext } from "@/stores/agentContextStore"

// AI Agent 패널 상태 (FR-071~076, SSE_이벤트_계약.md)
// - 열림, 대화(질문·답변), 답을 받는 중인지. 로그인해 있는 동안 화면을 옮겨도 유지하고,
//   로그아웃하거나 로그인 사용자가 바뀌면 비운다.
// - 질문: POST /agent/runs(202) → eventsUrl을 EventSource로 열어 step → answer → done(또는 failed)을 받는다.
// - 연결이 끊기면 브라우저가 Last-Event-ID를 붙여 같은 실행에 다시 잇는다. 연결이 닫혀 버리면
//   GET /agent/runs/{runId}로 상태를 확인해 완료·실패를 반영하거나 같은 실행에 새로 연결한다.
//   연결이 닫히지 않은 채 멈춘 경우에 대비해, 30초 동안 이벤트가 없으면 상태를 조회해 완료·실패를 반영한다.
//   이미 받은 이벤트 id는 무시한다. 새 질문(POST)을 자동으로 다시 보내지 않는다.
// - 새 대화의 conversationId는 실행을 만들 때 예약값으로 받고, done을 받은 뒤에만 다음 질문에 쓴다 (FR-076).

/** 서버 실행 제한(120초)보다 조금 길게: 이때까지 done·failed가 없으면 상태를 한 번 확인하고 끝낸다 */
const RUN_TIMEOUT_MS = 150_000
/** 같은 실행에 다시 연결하는 최대 횟수 */
const MAX_RECONNECTS = 5
const RECONNECT_DELAY_MS = 1_000
/** 이벤트가 이만큼 오지 않으면 연결이 멈춘 것인지 상태를 조회해 본다 (서버 heartbeat 15초는 브라우저에 보이지 않음) */
const STALL_MS = 30_000
const STALL_CHECK_INTERVAL_MS = 10_000

export const AGENT_MESSAGES = {
  failed: "답변을 만들지 못했습니다.",
  timeout: "응답 시간이 초과되어 답변을 만들지 못했습니다.",
  lost: "답변 연결이 끊겼습니다. 다시 시도해 주세요.",
  expired: "실행 정보가 만료되었습니다. 다시 시도해 주세요.",
} as const

export type AgentStep = ProgressStep

export type AssistantMessage = {
  id: number
  role: "assistant"
  status: "streaming" | "done" | "failed"
  /** 연결이 끊겨 같은 실행에 다시 잇는 중 */
  reconnecting: boolean
  steps: AgentStep[]
  blocks: AgentBlock[]
  error: string | null
  /** 다시 시도·추천 카드 이동에 쓰는 질문 당시의 값 */
  question: string
  context: AgentContext
}

export type AgentMessage = { id: number; role: "user"; text: string } | AssistantMessage

type AgentState = {
  open: boolean
  /** 다음 질문에 붙일 확정 대화 ID (done을 받은 대화만) */
  conversationId: string | null
  messages: AgentMessage[]
  busy: boolean
  /** 이전 대화를 불러왔을 때 위쪽 안내 */
  loadedFrom: { firstQuestion: string; lastMessageAt: string } | null
}

/** 마이페이지 대화 이력에서 불러오는 저장 대화 (API-37) */
export type LoadedConversation = {
  conversationId: string
  firstQuestion: string
  lastMessageAt: string
  turns: { question: string; blocks: AgentBlock[]; progressSteps: AgentStep[] }[]
}

type ActiveRun = {
  messageId: number
  runId: string
  eventsUrl: string
  source: EventSource | null
  lastEventId: number
  reconnects: number
  timer: number | null
  watchdog: number | null
  lastActivity: number
  checking: boolean
}

const EMPTY: AgentState = { open: false, conversationId: null, messages: [], busy: false, loadedFrom: null }

/** 불러온 이전 대화의 답변: 추천 카드 이동에 쓰는 사례자 정보가 없다 (이름을 저장하지 않으므로) */
const RESTORED_CONTEXT: AgentContext = { screen: { screenType: "other", path: "" }, label: "이전 대화" }

let state: AgentState = EMPTY
let sequence = 0
let active: ActiveRun | null = null
/** reset 뒤에 늦게 도착한 응답을 버리기 위한 세대 번호 */
let generation = 0
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

function updateAssistant(id: number, patch: (message: AssistantMessage) => Partial<AssistantMessage>) {
  setState({
    messages: state.messages.map((message) =>
      message.id === id && message.role === "assistant" ? { ...message, ...patch(message) } : message,
    ),
  })
}

function upsertStep(steps: AgentStep[], step: AgentStep): AgentStep[] {
  return steps.some((item) => item.stepId === step.stepId)
    ? steps.map((item) => (item.stepId === step.stepId ? step : item))
    : [...steps, step]
}

/** 실행을 끝낸다: 연결·타이머 정리 */
function stop(run: ActiveRun) {
  run.source?.close()
  run.source = null
  if (run.timer !== null) window.clearTimeout(run.timer)
  if (run.watchdog !== null) window.clearInterval(run.watchdog)
  run.timer = null
  run.watchdog = null
  if (active === run) active = null
}

function complete(run: ActiveRun, conversationId: string) {
  stop(run)
  updateAssistant(run.messageId, () => ({ status: "done", reconnecting: false }))
  setState({ busy: false, conversationId })
}

function fail(run: ActiveRun | null, messageId: number, error: string) {
  if (run) stop(run)
  updateAssistant(messageId, () => ({ status: "failed", reconnecting: false, error }))
  setState({ busy: false })
}

function apply(run: ActiveRun, event: AgentStreamEvent) {
  switch (event.event) {
    case "step":
      updateAssistant(run.messageId, (message) => ({ steps: upsertStep(message.steps, event.data) }))
      return
    case "answer":
      updateAssistant(run.messageId, () => ({ blocks: event.data.blocks ?? [] }))
      return
    case "done":
      complete(run, event.data.conversationId)
      return
    case "failed":
      fail(run, run.messageId, event.data.message || AGENT_MESSAGES.failed)
      return
  }
}

/** 상태 조회 결과(API-03-S2)를 반영한다. 끝났으면 true */
function applyState(run: ActiveRun, result: AgentRunState): boolean {
  updateAssistant(run.messageId, () => ({ steps: result.progressSteps, blocks: result.blocks }))
  if (result.status === "completed") {
    complete(run, result.conversationId)
    return true
  }
  if (result.status === "failed") {
    fail(run, run.messageId, result.errorMessage || AGENT_MESSAGES.failed)
    return true
  }
  return false
}

function connect(run: ActiveRun) {
  if (active !== run) return
  const source = new EventSource(run.eventsUrl)
  run.source = source

  for (const name of AGENT_STREAM_EVENTS) {
    source.addEventListener(name, (event: MessageEvent<string>) => {
      if (active !== run) return
      run.lastActivity = Date.now()
      // 이미 받은 이벤트는 무시한다 (다시 연결했을 때 서버가 처음부터 보내도 안전)
      const id = Number(event.lastEventId)
      if (Number.isFinite(id) && id > 0) {
        if (id <= run.lastEventId) return
        run.lastEventId = id
      }
      let data: unknown
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      apply(run, { event: name, data } as AgentStreamEvent)
    })
  }

  source.onopen = () => {
    if (active !== run) return
    run.lastActivity = Date.now()
    updateAssistant(run.messageId, () => ({ reconnecting: false }))
  }

  source.onerror = () => {
    if (active !== run) return
    run.reconnects += 1
    updateAssistant(run.messageId, () => ({ reconnecting: true }))
    // 연결이 닫혔거나(서버가 401·410 등으로 거절) 너무 여러 번 끊기면 상태를 직접 확인한다.
    // 그 밖에는 브라우저가 Last-Event-ID를 붙여 같은 실행에 다시 연결한다.
    if (source.readyState === EventSource.CLOSED || run.reconnects > MAX_RECONNECTS) void recover(run)
  }
}

async function recover(run: ActiveRun) {
  run.source?.close()
  run.source = null
  const messageId = run.messageId
  try {
    const result = await agentApi.getRun(run.runId)
    if (active !== run) return
    if (applyState(run, result)) return
    if (run.reconnects > MAX_RECONNECTS) {
      fail(run, messageId, AGENT_MESSAGES.lost)
      return
    }
    // 아직 실행 중: 같은 실행에 새로 연결한다
    window.setTimeout(() => connect(run), RECONNECT_DELAY_MS)
  } catch (error) {
    if (active !== run) return
    // 401이면 공통 처리(로그인 화면으로)가 대화를 비운다
    fail(run, messageId, isApiError(error) && error.status === 410 ? AGENT_MESSAGES.expired : errorMessage(error))
  }
}

/** 이벤트가 한동안 없으면 상태를 조회한다: 이미 끝났으면 반영하고, 아직 실행 중이면 계속 기다린다 */
async function checkStalled(run: ActiveRun) {
  if (active !== run || run.checking || Date.now() - run.lastActivity < STALL_MS) return
  run.checking = true
  try {
    const result = await agentApi.getRun(run.runId)
    if (active === run && !applyState(run, result)) run.lastActivity = Date.now()
  } catch (error) {
    if (active === run && isApiError(error) && error.status === 410) fail(run, run.messageId, AGENT_MESSAGES.expired)
  } finally {
    run.checking = false
  }
}

async function timeout(run: ActiveRun) {
  if (active !== run) return
  run.source?.close()
  run.source = null
  try {
    const result = await agentApi.getRun(run.runId)
    if (active !== run || applyState(run, result)) return
  } catch {
    // 아래에서 시간 초과로 끝낸다
  }
  if (active === run) fail(run, run.messageId, AGENT_MESSAGES.timeout)
}

async function run(question: string, context: AgentContext) {
  const messageId = ++sequence
  const runGeneration = generation
  setState({
    busy: true,
    messages: [
      ...state.messages,
      { id: messageId, role: "assistant", status: "streaming", reconnecting: false, steps: [], blocks: [], error: null, question, context },
    ],
  })

  try {
    const created = await agentApi.createRun({ conversationId: state.conversationId, question, screen: context.screen })
    if (runGeneration !== generation) return
    const next: ActiveRun = {
      messageId,
      runId: created.runId,
      eventsUrl: created.eventsUrl,
      source: null,
      lastEventId: 0,
      reconnects: 0,
      timer: null,
      watchdog: null,
      lastActivity: Date.now(),
      checking: false,
    }
    active = next
    next.timer = window.setTimeout(() => void timeout(next), RUN_TIMEOUT_MS)
    next.watchdog = window.setInterval(() => void checkStalled(next), STALL_CHECK_INTERVAL_MS)
    connect(next)
  } catch (error) {
    if (runGeneration !== generation) return
    fail(null, messageId, errorMessage(error))
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

  /** 질문 보내기. 답을 받는 중이면 무시한다 (입력·예시 질문도 막혀 있음, FR-073) */
  ask(question: string, context: AgentContext) {
    const text = question.trim()
    if (!text || state.busy) return
    setState({ messages: [...state.messages, { id: ++sequence, role: "user", text }] })
    void run(text, context)
  },

  /** 실패한 답변을 같은 질문·화면으로 다시 받는다 (사용자가 누를 때만 새 실행을 만든다) */
  retry(messageId: number) {
    const failed = state.messages.find((message) => message.id === messageId)
    if (!failed || failed.role !== "assistant" || failed.status !== "failed" || state.busy) return
    setState({ messages: state.messages.filter((message) => message.id !== messageId) })
    void run(failed.question, failed.context)
  },

  /** '새 대화': 지금 대화를 비운다 (완료된 대화는 이미 저장되어 있음). 답을 받는 중이면 무시 */
  newConversation() {
    if (state.busy) return
    setState({ conversationId: null, messages: [], loadedFrom: null })
  },

  /** 마이페이지에서 고른 이전 대화를 패널에 불러와 연다 (FR-069). 답을 받는 중이면 false */
  loadConversation(conversation: LoadedConversation): boolean {
    if (state.busy) return false
    const messages: AgentMessage[] = conversation.turns.flatMap((turn): AgentMessage[] => [
      { id: ++sequence, role: "user", text: turn.question },
      {
        id: ++sequence,
        role: "assistant",
        status: "done",
        reconnecting: false,
        steps: turn.progressSteps,
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

  /** 대화 기록을 지웠을 때: 패널에 열려 있던 대화면 비운다 (FR-070) */
  forget(conversationId: string) {
    if (state.conversationId !== conversationId) return
    agentStore.reset({ keepOpen: true })
  },

  /** 대화를 비운다. 받는 중인 실행의 연결도 닫는다 (서버 실행 취소는 하지 않음) */
  reset({ keepOpen = false }: { keepOpen?: boolean } = {}) {
    generation += 1
    if (active) stop(active)
    state = { ...EMPTY, open: keepOpen && state.open }
    listeners.forEach((listener) => listener())
  },
}

// 로그아웃하거나 로그인 사용자가 바뀌면 대화를 비우고 패널을 닫는다 (FR-071)
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
