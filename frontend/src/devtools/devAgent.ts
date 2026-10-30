import { addLogNote } from "@/devtools/apiLogStore"
import { isKept } from "@/mock/agent/retention"
import { db, nextId } from "@/mock/db"
import { sessionStore } from "@/session/sessionStore"
import { todayString } from "@/utils/datetime"

// 개발용: AI Agent 패널의 '예외 상황' 재현.
// - 다음 질문 한 번만 AI 서버가 실패하거나(error) 시간 안에 답하지 않게(timeout) 만든다 (mock/agent/agentEngine이 읽음)
// - 상담 내용에 이름이 들어간 상담을 넣어, AI에 넘길 때 이름을 가리는지 확인한다
// - AI 대화 기록(5.3.1): 다른 곳(다른 탭·기기)에서 대화를 지운 상황, 보관 기간이 지난 대화 수

export type AgentFault = "error" | "timeout"

let nextFault: AgentFault | null = null

export const devAgent = {
  setNextFault(fault: AgentFault) {
    nextFault = fault
    addLogNote(fault === "error" ? "다음 AI 질문은 중간에 실패하도록 바꿈" : "다음 AI 질문은 시간 안에 답하지 않도록 바꿈")
  },

  /** AI 서버 흉내가 한 번 읽고 지운다 */
  takeFault(): AgentFault | null {
    const fault = nextFault
    nextFault = null
    return fault
  },

  /** 이 사례자에게 이름이 적힌 상담 기록을 하나 더한다 (오늘 날짜) */
  addNamedConsultation(caseId: number) {
    const record = db.cases.find((item) => item.caseId === caseId)
    const memberId = sessionStore.getMemberId()
    if (!record || memberId === null) return
    db.consultations.push({
      consultationId: nextId(db.consultations, (item) => item.consultationId),
      caseId,
      consultedAt: todayString(),
      purpose: "가족 상담",
      category: "기타",
      categoryEtc: "가족 통화",
      content: `딸 박미정 씨와 통화함. ${record.name} 님이 요즘 끼니를 자주 거르고 외출을 거의 하지 않는다고 함.`,
      recorderMemberId: memberId,
    })
    addLogNote(`사례자 '${record.name}'에 이름이 적힌 상담 기록(오늘)을 더함. 새로고침하면 사라짐`)
  },

  /** 다른 탭·기기에서 이 대화를 지운 것처럼 데이터만 지운다 */
  deleteConversationElsewhere(conversationId: string) {
    const conversation = db.agentConversations.find((item) => item.conversationId === conversationId)
    if (!conversation) return
    db.agentTurns = db.agentTurns.filter((item) => item.conversationId !== conversationId)
    db.agentConversations = db.agentConversations.filter((item) => item.conversationId !== conversationId)
    addLogNote(`다른 곳에서 대화 '${conversation.firstQuestion}'(${conversationId})를 지움 (데이터만 바뀜)`)
  },

  /** 지금 로그인한 회원의 대화 중 보관 기간이 지난 것 (목록에서 빠짐) */
  expiredConversationCount(): number {
    const memberId = sessionStore.getMemberId()
    const today = todayString()
    return db.agentConversations.filter((item) => item.memberId === memberId && !isKept(item, today)).length
  },
}
