import { useSyncExternalStore } from "react"
import { agentApi, type AgentMessage, type ConversationDetail } from "@/api/agentApi"
import { errorMessage, isApiError } from "@/api/errors"
import { sessionStore } from "@/session/sessionStore"

// AI 에이전트 패널 상태 (FR-071~076, docs/api/ai-agent-panel.md)
// - 대화 ID와 받은 행(messageId로 중복 없이, 오름차순)을 둔다. 실행 중 = 마지막 질문 행에 끝 행(완료·실패·취소)이 없음.
// - 질문: POST /agent/questions(202) → 질문 행을 바로 붙이고 after=questionId부터 1초마다 조회 → 끝 행을 받으면 멈춘다.
// - 조회가 실패해도 다음 조회가 마지막 id부터 이어 받는다 (재연결 처리 없음). 401은 공통 처리(로그아웃 → 대화 비움).
// - 새로고침: 대화 ID만 sessionStorage에 두고(토큰·회원 ID가 아님) 로그인 복원 뒤 after=0으로 다시 그린다.
//   로그아웃·사용자 전환 때 지운다.
// - 패널을 열 때마다 한 번 조회해, 복원에 실패했거나 멈춘 조회를 이어 받는다.

/** 실행 중 조회 간격 (ai-agent-panel.md 1장) */
const POLL_INTERVAL_MS = 1_000
// TODO(시간 값 미정, BE 설정 eumi.ai.*): FE는 따로 제한 시간을 두지 않는다.
//   끝나지 않는 실행은 BE가 '질문 시각 + AI 실행 제한 + 여유 시간' 뒤에 실패 행을 써서 끝낸다.

const STORAGE_KEY = "eumi.agent.conversationId"

export const AGENT_MESSAGES = {
  failed: "답변을 만들지 못했어요",
  cancelled: "중단했어요",
  runActive: "이전 질문의 답변이 끝난 뒤 질문할 수 있어요",
  notFound: "이전 대화를 찾을 수 없어 새 대화로 시작해요",
} as const

type AgentState = {
  open: boolean
  /** 이어서 질문할 대화 ID (첫 질문 전에는 null) */
  conversationId: string | null
  /** 받은 행, messageId 오름차순 */
  messages: AgentMessage[]
  /** 마지막 질문에 끝 행이 아직 없음: 보내기를 막고 중단 버튼을 보인다 */
  running: boolean
  /** 질문을 보내고 202를 기다리는 중 */
  sending: boolean
  /** 중단을 요청하고 끝 행을 기다리는 중 */
  cancelling: boolean
  /** 입력칸 위 안내 (409·404·질문 실패) */
  notice: string | null
  /** 마이페이지에서 이전 대화를 불러왔을 때 위쪽 안내 */
  loadedFrom: { firstQuestion: string; lastMessageAt: string } | null
}

const EMPTY: AgentState = {
  open: false,
  conversationId: null,
  messages: [],
  running: false,
  sending: false,
  cancelling: false,
  notice: null,
  loadedFrom: null,
}

let state: AgentState = EMPTY
let timer: number | null = null
/** 조회 요청이 나가 있는 중 (겹쳐 보내지 않음) */
let polling = false
/** 400·403으로 조회를 멈춤 (403 PASSWORD_CHANGE_REQUIRED 알림이 1초마다 뜨지 않게). 패널을 다시 열면 이어 간다 */
let paused = false
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

/** 끝 행: 질문마다 하나뿐이다 */
export function isEndRow(message: AgentMessage): boolean {
  return message.status === "완료" || message.status === "실패" || message.status === "취소"
}

/** 마지막 질문 행에 끝 행이 없으면 실행 중 */
function isRunning(messages: AgentMessage[]): boolean {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const question = messages[index]
    if (question.status !== "질문") continue
    return !messages.some((message) => message.questionId === question.messageId && isEndRow(message))
  }
  return false
}

function lastMessageId(): number {
  return state.messages.length === 0 ? 0 : state.messages[state.messages.length - 1].messageId
}

/** 받은 행을 messageId 기준으로 합친다 (같은 id면 서버 값으로 바꾼다) */
function merge(rows: AgentMessage[]) {
  if (rows.length === 0) return
  const byId = new Map(state.messages.map((message) => [message.messageId, message]))
  for (const row of rows) byId.set(row.messageId, row)
  const messages = [...byId.values()].sort((a, b) => a.messageId - b.messageId)
  const running = isRunning(messages)
  setState({ messages, running, cancelling: running && state.cancelling })
}

function storeConversationId(conversationId: string | null) {
  try {
    if (conversationId) sessionStorage.setItem(STORAGE_KEY, conversationId)
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // 저장소를 못 쓰면 새로고침 때 대화를 다시 그리지 못할 뿐이다
  }
}

function storedConversationId(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function schedulePoll(delay = POLL_INTERVAL_MS) {
  if (timer !== null || polling || paused) return
  timer = window.setTimeout(() => {
    timer = null
    void poll()
  }, delay)
}

/** after=마지막 id로 한 번 조회해 붙이고, 아직 실행 중이면 1초 뒤 다시 조회한다 */
async function poll() {
  const conversationId = state.conversationId
  if (!conversationId || polling) return
  const pollGeneration = generation
  polling = true
  try {
    const { messages } = await agentApi.getMessages(conversationId, lastMessageId())
    if (pollGeneration !== generation) return
    merge(messages)
  } catch (error) {
    if (pollGeneration !== generation) return
    if (isApiError(error) && error.status === 404) {
      restart()
      return
    }
    // 401은 공통 처리가 로그아웃시키며 대화를 비운다. 400·403은 매초 되풀이하지 않고 멈춘다.
    // 그 밖(통신 오류·5xx·429)은 다음 조회가 마지막 id부터 이어 받는다
    if (isApiError(error) && (error.status === 400 || error.status === 403)) paused = true
  } finally {
    if (pollGeneration === generation) polling = false
  }
  if (pollGeneration === generation && state.running) schedulePoll()
}

/** 대화가 없어졌을 때(404): 새 대화로 초기화하고 알린다 */
function restart() {
  storeConversationId(null)
  agentStore.reset({ keepOpen: true })
  setState({ notice: AGENT_MESSAGES.notFound })
}

async function send(question: string): Promise<boolean> {
  const sendGeneration = generation
  setState({ sending: true, notice: null })
  try {
    const created = await agentApi.ask({ conversationId: state.conversationId, question })
    if (sendGeneration !== generation) return false
    storeConversationId(created.conversationId)
    setState({ conversationId: created.conversationId, sending: false, loadedFrom: null })
    // 질문 행은 다시 받지 않으므로(after=questionId) 입력한 문장으로 바로 붙인다.
    // 새로고침하면(after=0) 서버가 저장한 문장으로 보인다 (이메일·휴대전화·이름/생년월일 필드만 가린 결과)
    merge([
      {
        messageId: created.questionId,
        questionId: null,
        role: "Member",
        status: "질문",
        content: question,
        details: null,
        artifacts: null,
        createdAt: new Date().toISOString(),
      },
    ])
    paused = false
    schedulePoll()
    return true
  } catch (error) {
    if (sendGeneration !== generation) return false
    setState({ sending: false })
    if (isApiError(error) && error.status === 404) {
      restart()
      return false
    }
    if (isApiError(error) && error.code === "RUN_ALREADY_ACTIVE") {
      // 다른 탭 등에서 보낸 질문이 아직 실행 중: 마지막 id부터 조회하면 그 질문과 답이 붙는다
      setState({ notice: AGENT_MESSAGES.runActive })
      paused = false
      void poll()
      return false
    }
    setState({ notice: errorMessage(error) })
    return false
  }
}

export const agentStore = {
  open() {
    setState({ open: true })
    if (state.conversationId) {
      paused = false
      void poll()
    }
  },
  close() {
    setState({ open: false })
  },
  toggle() {
    if (state.open) agentStore.close()
    else agentStore.open()
  },

  /** 질문 보내기. 실행 중·보내는 중이면 무시한다 (입력·예시 질문도 막혀 있음, FR-073). 질문이 저장되면(202) true */
  ask(question: string): Promise<boolean> {
    const text = question.trim()
    if (!text || state.running || state.sending) return Promise.resolve(false)
    return send(text)
  },

  /** 실패한 질문을 같은 대화에 새 질문으로 다시 보낸다 (사용자가 누를 때만) */
  retry(questionMessageId: number) {
    const question = state.messages.find((message) => message.messageId === questionMessageId && message.status === "질문")
    if (question?.content) void agentStore.ask(question.content)
  },

  /** 중단: 취소 행은 조회로 받는다. 취소와 완료가 겹치면 먼저 저장된 끝 행만 남는다 */
  async cancel() {
    const conversationId = state.conversationId
    if (!conversationId || !state.running || state.cancelling) return
    const cancelGeneration = generation
    setState({ cancelling: true, notice: null })
    try {
      await agentApi.cancel(conversationId)
      if (cancelGeneration !== generation) return
      paused = false
      schedulePoll(0)
    } catch (error) {
      if (cancelGeneration !== generation) return
      if (isApiError(error) && error.status === 404) {
        restart()
        return
      }
      setState({ cancelling: false, notice: errorMessage(error) })
    }
  },

  /** '새 대화': 지금 대화를 비운다 (대화는 이미 서버에 저장되어 있음). 실행 중이면 무시 */
  newConversation() {
    if (state.running || state.sending) return
    storeConversationId(null)
    agentStore.reset({ keepOpen: true })
  },

  /** 마이페이지에서 고른 이전 대화(API-37)를 패널에 불러와 연다 (FR-069). 실행 중이면 false */
  loadConversation(conversation: ConversationDetail): boolean {
    if (state.running || state.sending) return false
    agentStore.reset()
    storeConversationId(conversation.conversationId)
    setState({
      open: true,
      conversationId: conversation.conversationId,
      loadedFrom: { firstQuestion: conversation.firstQuestion, lastMessageAt: conversation.lastMessageAt },
    })
    merge(conversation.messages)
    if (state.running) schedulePoll()
    return true
  },

  /** 대화 기록을 지웠을 때: 패널에 열려 있던 대화면 비운다 (FR-070) */
  forget(conversationId: string) {
    if (state.conversationId !== conversationId) return
    storeConversationId(null)
    agentStore.reset({ keepOpen: true })
  },

  /** 대화를 비우고 조회를 멈춘다 (서버 실행 취소는 하지 않음). 저장한 대화 ID는 부른 쪽이 정리한다 */
  reset({ keepOpen = false }: { keepOpen?: boolean } = {}) {
    generation += 1
    if (timer !== null) window.clearTimeout(timer)
    timer = null
    polling = false
    paused = false
    state = { ...EMPTY, open: keepOpen && state.open }
    listeners.forEach((listener) => listener())
  },
}

// 로그아웃하거나 로그인 사용자가 바뀌면 대화를 비우고 저장한 대화 ID도 지운다 (FR-071).
// 로그인하지 않은 상태에서 회원이 정해질 때(새로고침 뒤 복원)만 저장한 대화를 after=0으로 다시 그린다
sessionStore.subscribe(() => {
  if (sessionStore.getState().status === "anonymous") storeConversationId(null)
  const memberId = sessionStore.getMemberId()
  if (memberId === ownerMemberId) return
  const switched = ownerMemberId !== null
  ownerMemberId = memberId
  agentStore.reset()
  if (memberId === null) return
  if (switched) {
    storeConversationId(null)
    return
  }
  const conversationId = storedConversationId()
  if (!conversationId) return
  setState({ conversationId })
  void poll()
})

export function useAgentState(): AgentState {
  return useSyncExternalStore(subscribe, () => state)
}
