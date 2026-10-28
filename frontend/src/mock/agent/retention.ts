import type { AgentConversation } from "@/types/domain"
import { addMonths, daysBetween, todayString } from "@/utils/datetime"

// AI 대화 기록 보관 기간 (0.2.4): 마지막 대화일부터 3개월 (M10-A).
// 삭제 예정일이 되면 서버의 매일 지우는 작업이 대화와 질문·답변을 지운다.

export const CONVERSATION_KEEP_MONTHS = 3

/** 삭제 예정일 = 마지막 대화일 + 3개월 */
export function deleteScheduledAtOf(conversation: AgentConversation): string {
  return addMonths(conversation.lastMessageAt, CONVERSATION_KEEP_MONTHS)
}

/** 삭제 예정일까지 남은 날 수 (0 이하면 이미 지울 대화) */
export function daysUntilDelete(deleteScheduledAt: string, today = todayString()): number {
  return daysBetween(today, deleteScheduledAt)
}

/** 아직 보관 기간 안인지 */
export function isKept(conversation: AgentConversation, today = todayString()): boolean {
  return deleteScheduledAtOf(conversation) > today
}
