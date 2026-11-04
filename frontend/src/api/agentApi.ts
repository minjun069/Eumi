import { api } from "@/api/http"
import type { Schemas, SuccessData } from "@/api/types"

// AI 에이전트 패널 API (API-03·03-S1·03-S2, docs/api/ai-agent-panel.md)
// 질문을 보내면(202) 1초마다 마지막으로 받은 행 이후를 조회해 붙이고, 끝 행(완료·실패·취소)을 받으면 멈춘다 (stores/agentStore.ts).

export type AgentQuestionRequest = Schemas["AgentQuestionRequest"]
export type AgentQuestionCreated = SuccessData<"AgentQuestionCreated_Success">
export type AgentMessageList = SuccessData<"AgentMessages_Success">
/** ai_message 한 행 (질문·진행·완료·실패·취소) */
export type AgentMessage = Schemas["AgentMessage"]
/** 마이페이지에서 고른 대화 전체 (API-37) */
export type ConversationDetail = SuccessData<"agentApi_getConversation_Success">
/** 마이페이지 AI 대화 기록 목록 (API-36) */
export type ConversationPage = SuccessData<"agentApi_listConversations_Success">
export type ConversationListItem = Schemas["ConversationListItem"]

export const conversationKeys = {
  all: ["conversations"] as const,
  list: (page: number) => ["conversations", "list", page] as const,
}

const conversationPath = (conversationId: string) => `/agent/conversations/${encodeURIComponent(conversationId)}`
const savedConversationPath = (conversationId: string) =>
  `/members/me/conversations/${encodeURIComponent(conversationId)}`

export const agentApi = {
  /** API-03 POST /agent/questions — 202. 끝 행 없는 질문이 있으면 409 RUN_ALREADY_ACTIVE, 남의·만료 대화 404 */
  ask: (request: AgentQuestionRequest) => api.post<AgentQuestionCreated>("/agent/questions", request),

  /** API-03-S1 GET /agent/conversations/{id}/messages — after보다 큰 행을 오름차순으로. 처음부터는 after=0 */
  getMessages: (conversationId: string, after: number) =>
    api.get<AgentMessageList>(`${conversationPath(conversationId)}/messages`, { query: { after } }),

  /** API-03-S2 POST /agent/conversations/{id}/cancel — 204, 이미 끝났어도 204. 취소 행은 조회로 받는다 */
  cancel: (conversationId: string) => api.post<void>(`${conversationPath(conversationId)}/cancel`),

  /** API-36 GET /members/me/conversations — 보관 중인 본인 대화, 실행 종료 일시 최신순 */
  listConversations: (page: number, size: number) =>
    api.get<ConversationPage>("/members/me/conversations", { query: { page, size } }),

  /** API-37 GET /members/me/conversations/{id} — 대화 전체 행 (messages는 API-03-S1과 같은 형식). 남의·만료 대화 404 */
  getConversation: (conversationId: string) => api.get<ConversationDetail>(savedConversationPath(conversationId)),

  /** API-38 DELETE /members/me/conversations/{id} — 204. 실행 중이면 서버가 먼저 취소를 요청한다 */
  deleteConversation: (conversationId: string) => api.delete<void>(savedConversationPath(conversationId)),
}
