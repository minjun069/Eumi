import { ApiError, callApi, requireMember, serverNote } from "@/mock/api/core"
import { respond } from "@/mock/agent/agentEngine"
import { maskIdentity } from "@/mock/agent/identityMask"
import { deleteScheduledAtOf, isKept } from "@/mock/agent/retention"
import { db, nextId } from "@/mock/db"
import type { AgentBlock, AgentConversation, Member } from "@/types/domain"
import { nowString, todayString } from "@/utils/datetime"

// 0.2 AI Agent 패널 + 5.3 AI 대화 기록
// - 0.2.2 질문 보내기 (화면 기반 응답). 0.2.3 사례자 맞춤 복지자원 추천도 같은 API로 요청한다 (A4-A)
// - 0.2.4 대화 기록 저장: 답을 끝까지 만들면 질문·답변을 신원 정보를 가려 저장 (M9-A: 진행 단계는 저장하지 않음)
// - 5.3.1 이전 대화 조회: 대화 목록 조회, 대화 내용 조회, 대화 기록 삭제
// 보관 기간: 마지막 대화일부터 3개월 (M10-A). 지난 대화는 서버가 매일 지운다.
// 응답은 스트리밍(SSE)으로 이벤트를 나눠 보낸다 (A2-B, 글자 단위 출력은 하지 않음).
// 이벤트 종류(event): step(단계 진행 중 → 완료) … → answer(답변 블록) → done(대화ID) / 중간에 실패하면 error.
// 연결이 끊기거나 시간 안에 끝(done)이 오지 않으면 화면이 실패로 보고 '다시 시도'를 보여 준다(다시 연결하지 않음).
// 프로토타입은 이벤트 목록을 한 번에 만들어 API 기록에 남기고, 패널이 시간 간격을 두고 차례로 보여 준다.

/** 지금 보는 화면 (A3-A: 화면 종류와 ID·조건만 보낸다. 자료 조회와 신원 정보 빼기는 서버가 한다) */
export type AgentScreen =
  | { screenType: "risk-district"; sigunguCode: string; from: string; to: string; index: "background" | "behavior" }
  | { screenType: "risk-dong"; dongCode: string; month: string }
  | { screenType: "case-detail"; caseId: number }
  | { screenType: "resource-detail"; resourceId: number }
  | { screenType: "other"; path: string }

export type AgentAskRequest = {
  /** 처음 질문이면 null. 서버가 대화ID를 만들어 done 이벤트로 돌려준다 */
  conversationId: string | null
  question: string
  screen: AgentScreen
}

export type { AgentBlock, CheckState, RecommendationCard } from "@/types/domain"

export type AgentEvent =
  | { event: "step"; stepId: string; stepName: string; status: "진행 중" | "완료"; detail: string | null }
  | { event: "answer"; blocks: AgentBlock[] }
  | { event: "done"; conversationId: string }
  | { event: "error"; errorMessage: string }

export const AGENT_FAILED_MESSAGE = "답변을 만들지 못했습니다."
export const CONVERSATION_NOT_FOUND_MESSAGE = "대화를 찾을 수 없습니다."

export type ConversationListItem = {
  conversationId: string
  /** 첫 질문 (제목처럼 보여 줌) */
  firstQuestion: string
  questionCount: number
  lastMessageAt: string
  /** 삭제 예정일 = 마지막 대화일 + 3개월 */
  deleteScheduledAt: string
}

export type ConversationListResponse = {
  totalCount: number
  page: number
  size: number
  totalPages: number
  items: ConversationListItem[]
}

export type ConversationDetail = {
  conversationId: string
  firstQuestion: string
  lastMessageAt: string
  deleteScheduledAt: string
  turns: { question: string; blocks: AgentBlock[]; askedAt: string }[]
}

/** 내 대화 중 보관 기간 안의 것 (없거나 남의 대화·보관 기간이 지난 대화면 null) */
function findMyConversation(member: Member, conversationId: string | null): AgentConversation | null {
  if (!conversationId) return null
  const conversation = db.agentConversations.find(
    (item) => item.conversationId === conversationId && item.memberId === member.memberId,
  )
  return conversation && isKept(conversation, todayString()) ? conversation : null
}

/** 신원 정보를 가릴 이름: 같은 기관 사례자 이름 */
function identityNames(member: Member): string[] {
  return db.cases.filter((item) => item.orgId === member.orgId).map((item) => item.name)
}

function maskBlocks(blocks: AgentBlock[], names: string[]): { blocks: AgentBlock[]; count: number } {
  let count = 0
  // 답변 문장에는 '○○ 님' 규칙을 쓰지 않는다 (AI가 쓴 문장을 잘못 가리지 않도록 이름 목록만)
  const mask = (text: string) => {
    const result = maskIdentity(text, names, { pattern: false })
    count += result.count
    return result.text
  }
  const masked = blocks.map((block): AgentBlock => {
    if (block.kind === "text") return { ...block, text: mask(block.text) }
    if (block.kind === "list") return { ...block, items: block.items.map(mask) }
    return {
      ...block,
      cards: block.cards.map((card) => ({
        ...card,
        reason: mask(card.reason),
        evidence: mask(card.evidence),
        checks: card.checks.map((check) => ({ ...check, label: mask(check.label), note: mask(check.note) })),
        beforeUse: card.beforeUse.map(mask),
      })),
    }
  })
  return { blocks: masked, count }
}

export const agentApi = {
  /**
   * 0.2.2 질문 보내기 (화면 기반 응답). 응답은 이벤트 스트림.
   * 서버가 화면 정보로 자료를 조회하고(사례자는 신원 정보를 빼고) AI Agent에 넘긴다.
   * 답을 끝까지 만들면 질문·답변을 대화 기록에 저장한다 (0.2.4).
   */
  ask(request: AgentAskRequest) {
    return callApi(
      { featureId: "0.2.2", featureName: "AI 질문 보내기" },
      request,
      (input): { events: AgentEvent[] } => {
        const member = requireMember()
        const names = identityNames(member)
        const existing = findMyConversation(member, input.conversationId)
        if (input.conversationId && !existing) {
          serverNote(`대화ID(${input.conversationId})가 없거나 보관 기간이 지나 새 대화로 처리함`)
        }

        // 질문에 적은 이름·관리번호도 AI에 넘기기 전에 가린다
        const maskedQuestion = maskIdentity(input.question.trim(), names)
        if (maskedQuestion.count > 0) {
          serverNote(`질문에 적힌 신원 정보 ${maskedQuestion.count}곳을 가려서 AI에 넘김: "${maskedQuestion.text}"`)
        }
        if (existing) {
          const previous = db.agentTurns.filter((item) => item.conversationId === existing.conversationId).length
          serverNote(`저장된 이전 질문·답변 ${previous}개를 함께 AI에 넘김 (대화 이어 가기)`)
        }

        serverNote("응답은 스트리밍(SSE)으로 단계 → 답변 → 끝 순서의 이벤트를 나눠 보냄")
        const events = respond(member, { ...input, question: maskedQuestion.text })
        const last = events[events.length - 1]
        const answer = events.find((item) => item.event === "answer")
        const completed = last?.event !== "error" && answer !== undefined
        // 실패·시간 초과 재현에서는 끝(done) 이벤트를 붙이지 않는다. 실패한 답은 저장하지 않는다
        if (!completed || answer?.event !== "answer") {
          serverNote(existing ? "답을 끝내지 못해 대화 기록에 저장하지 않음" : "답을 끝내지 못해 새 대화ID를 만들지 않음")
          return { events }
        }

        const now = nowString()
        let conversation = existing
        if (!conversation) {
          const number = db.agentConversations.reduce((max, item) => Math.max(max, Number(item.conversationId.replace("conv-", "")) || 0), 0) + 1
          conversation = {
            conversationId: `conv-${number}`,
            memberId: member.memberId,
            firstQuestion: maskedQuestion.text,
            createdAt: now,
            lastMessageAt: now,
          }
          db.agentConversations.push(conversation)
          serverNote(`첫 답을 끝낸 뒤 새 대화ID(${conversation.conversationId})를 만들어 끝(done) 이벤트로 돌려줌. 첫 질문을 대화 제목으로 저장`)
        }
        const maskedAnswer = maskBlocks(answer.blocks, names)
        db.agentTurns.push({
          turnId: nextId(db.agentTurns, (item) => item.turnId),
          conversationId: conversation.conversationId,
          question: maskedQuestion.text,
          blocks: maskedAnswer.blocks,
          askedAt: now,
        })
        conversation.lastMessageAt = now
        serverNote(
          `질문·답변을 대화 기록에 저장함 (0.2.4): 신원 정보를 가린 값, 진행 단계는 저장하지 않음${maskedAnswer.count > 0 ? `, 답변의 이름 ${maskedAnswer.count}곳 가림` : ""}. 삭제 예정일은 ${deleteScheduledAtOf(conversation)} (마지막 대화일부터 3개월)`,
        )
        events.push({ event: "done", conversationId: conversation.conversationId })
        return { events }
      },
    )
  },

  /** 5.3.1 대화 목록 조회: 내 대화, 마지막 대화가 최근인 순, 첫 질문을 제목으로 */
  listConversations(request: { page: number; size: number }) {
    return callApi(
      { featureId: "5.3.1", featureName: "대화 목록 조회" },
      request,
      (input): ConversationListResponse => {
        const member = requireMember()
        const today = todayString()
        const mine = db.agentConversations.filter((item) => item.memberId === member.memberId)
        const kept = mine.filter((item) => isKept(item, today))
        serverNote("내 대화만, 마지막 대화 시각이 최근인 순")
        if (kept.length < mine.length) {
          serverNote(
            `보관 기간(마지막 대화일부터 3개월)이 지난 대화 ${mine.length - kept.length}개는 빼고 돌려줌 — 실제로는 매일 지우는 작업이 삭제 예정일에 지움`,
          )
        }
        kept.sort((a, b) => b.lastMessageAt.localeCompare(a.lastMessageAt))
        const size = Math.max(1, input.size)
        const totalCount = kept.length
        const totalPages = Math.max(1, Math.ceil(totalCount / size))
        const page = Math.min(Math.max(1, input.page), totalPages)
        const items = kept.slice((page - 1) * size, page * size).map((item) => ({
          conversationId: item.conversationId,
          firstQuestion: item.firstQuestion,
          questionCount: db.agentTurns.filter((turn) => turn.conversationId === item.conversationId).length,
          lastMessageAt: item.lastMessageAt,
          deleteScheduledAt: deleteScheduledAtOf(item),
        }))
        return { totalCount, page, size, totalPages, items }
      },
    )
  },

  /** 5.3.1 대화 내용 조회: 고른 대화의 질문·답변 (패널에서 이어서 대화) */
  getConversation(request: { conversationId: string }) {
    return callApi(
      { featureId: "5.3.1", featureName: "대화 내용 조회" },
      request,
      ({ conversationId }): ConversationDetail => {
        const member = requireMember()
        const conversation = findMyConversation(member, conversationId)
        if (!conversation) throw new ApiError(CONVERSATION_NOT_FOUND_MESSAGE)
        serverNote("저장된 질문·답변을 시간 순으로 돌려줌 (진행 단계는 저장하지 않아 없음)")
        return {
          conversationId: conversation.conversationId,
          firstQuestion: conversation.firstQuestion,
          lastMessageAt: conversation.lastMessageAt,
          deleteScheduledAt: deleteScheduledAtOf(conversation),
          turns: db.agentTurns
            .filter((item) => item.conversationId === conversation.conversationId)
            .sort((a, b) => a.askedAt.localeCompare(b.askedAt) || a.turnId - b.turnId)
            .map(({ question, blocks, askedAt }) => ({ question, blocks, askedAt })),
        }
      },
    )
  },

  /** 5.3.1 대화 기록 삭제 (확인 창 뒤) */
  deleteConversation(request: { conversationId: string }) {
    return callApi(
      { featureId: "5.3.1", featureName: "대화 기록 삭제" },
      request,
      ({ conversationId }) => {
        const member = requireMember()
        const conversation = findMyConversation(member, conversationId)
        if (!conversation) throw new ApiError(CONVERSATION_NOT_FOUND_MESSAGE)
        const turns = db.agentTurns.filter((item) => item.conversationId === conversationId).length
        db.agentTurns = db.agentTurns.filter((item) => item.conversationId !== conversationId)
        db.agentConversations = db.agentConversations.filter((item) => item.conversationId !== conversationId)
        serverNote(`대화와 질문·답변 ${turns}개를 지움 (되돌릴 수 없음)`)
        return undefined
      },
    )
  },
}
