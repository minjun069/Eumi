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

const conversationPath = (conversationId: string) => `/agent/conversations/${encodeURIComponent(conversationId)}`

export const agentApi = {
  /** API-03 POST /agent/questions — 202. 끝 행 없는 질문이 있으면 409 RUN_ALREADY_ACTIVE, 남의·만료 대화 404 */
  ask: (request: AgentQuestionRequest) => api.post<AgentQuestionCreated>("/agent/questions", request),

  /** API-03-S1 GET /agent/conversations/{id}/messages — after보다 큰 행을 오름차순으로. 처음부터는 after=0 */
  getMessages: (conversationId: string, after: number) =>
    api.get<AgentMessageList>(`${conversationPath(conversationId)}/messages`, { query: { after } }),

  /** API-03-S2 POST /agent/conversations/{id}/cancel — 204, 이미 끝났어도 204. 취소 행은 조회로 받는다 */
  cancel: (conversationId: string) => api.post<void>(`${conversationPath(conversationId)}/cancel`),
}
