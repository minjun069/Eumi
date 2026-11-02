import { api } from "@/api/http"
import type { Schemas, SuccessData } from "@/api/types"

// AI Agent 실행 API (API-03·03-S1·03-S2, SSE_이벤트_계약.md)
// 1) POST /agent/runs 로 실행을 만들고(202) → 2) eventsUrl을 EventSource로 연다 → 3) 끊기면 GET /agent/runs/{runId}로 상태 확인.
// 이벤트 스트림(EventSource)은 공통 응답 모양이 아니라서 api 클라이언트를 쓰지 않는다 (stores/agentStore.ts).

export type AgentScreen = Schemas["AgentScreen"]
export type AgentRunRequest = Schemas["AgentRunRequest"]
export type AgentRunCreated = SuccessData<"AgentRunCreated_Success">
export type AgentRunState = SuccessData<"AgentRunState_Success">
export type AgentBlock = Schemas["SavedAgentBlock"]
export type RecommendationCard = Schemas["SavedRecommendationCard"]
export type ProgressStep = Schemas["SavedProgressStep"]

/** SSE 이벤트의 data (SSE_이벤트_계약.md). id는 run 안에서 1씩 늘어나는 정수 */
export type AgentStreamEvent =
  | { event: "step"; data: ProgressStep }
  | { event: "answer"; data: { blocks: AgentBlock[] } }
  | { event: "done"; data: { conversationId: string; turnId: number } }
  | { event: "failed"; data: { code: string; message: string } }

export const AGENT_STREAM_EVENTS = ["step", "answer", "done", "failed"] as const

export const agentApi = {
  /** API-03 POST /agent/runs — 202. 대화당 실행은 하나(409 RUN_ALREADY_ACTIVE) */
  createRun: (request: AgentRunRequest) => api.post<AgentRunCreated>("/agent/runs", request),

  /** API-03-S2 GET /agent/runs/{runId} — 같은 실행의 상태 (연결이 끊겼을 때 복구용). 실행이 사라졌으면 410 */
  getRun: (runId: string) => api.get<AgentRunState>(`/agent/runs/${encodeURIComponent(runId)}`),
}
