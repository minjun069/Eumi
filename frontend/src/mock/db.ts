import { seedDongs, seedSidos, seedSigungus } from "@/mock/seed/regions"
import { seedOrganizations } from "@/mock/seed/organizations"
import { seedMembers } from "@/mock/seed/members"
import { seedDongMonthlyAnalyses } from "@/mock/seed/analysis"
import { seedDongInsights, seedInsightReports } from "@/mock/seed/insights"
import { seedResources } from "@/mock/seed/resources"
import {
  seedCaseManagers,
  seedCaseNumberSequences,
  seedCases,
  seedConsultations,
} from "@/mock/seed/cases"
import { seedAgentConversations, seedAgentTurns } from "@/mock/seed/conversations"
import type { EmailVerification, VerificationToken } from "@/types/domain"

// 메모리 DB. 모듈이 처음 실행될 때 예시 데이터를 복사해 만든다.
// 화면 이동 중에는 유지되고, 새로고침(F5)하면 모듈이 다시 실행되어 처음 상태로 돌아간다.
// 화면 코드는 db를 직접 읽거나 바꾸지 않고 src/mock/api의 함수를 통해서만 다룬다.
// (예외: src/devtools의 개발용 도구는 db를 직접 읽거나 바꾼다)

export const db = {
  sidos: structuredClone(seedSidos),
  sigungus: structuredClone(seedSigungus),
  dongs: structuredClone(seedDongs),
  organizations: structuredClone(seedOrganizations),
  members: structuredClone(seedMembers),
  /** 복지자원 (모든 기관이 함께 조회, 삭제는 soft delete) */
  resources: structuredClone(seedResources),
  /** 사례자, 사례자 담당자(여러 명), 상담 기록 */
  cases: structuredClone(seedCases),
  caseManagers: structuredClone(seedCaseManagers),
  consultations: structuredClone(seedConsultations),
  /** 관리번호 일련번호 (기관·연도별 마지막 번호, 삭제해도 줄이지 않음) */
  caseNumberSequences: structuredClone(seedCaseNumberSequences),
  /** 고립 위험 분석 결과 (행정동·월별, 강남구 2025-07 ~ 2025-12) */
  dongMonthlyAnalyses: structuredClone(seedDongMonthlyAnalyses),
  /** 읍면동 인사이트·인사이트 보고서 (행정동·월별, AI가 만들어 저장한 내용) */
  dongInsights: structuredClone(seedDongInsights),
  insightReports: structuredClone(seedInsightReports),
  /** AI Agent 대화 기록 (0.2.4): 대화와 질문·답변 (신원 정보를 가린 값, 마지막 대화일부터 3개월 보관) */
  agentConversations: structuredClone(seedAgentConversations),
  agentTurns: structuredClone(seedAgentTurns),
  /** 회원가입 이메일 인증 (처음에는 비어 있음) */
  emailVerifications: [] as EmailVerification[],
  verificationTokens: [] as VerificationToken[],
}

/** 목록에서 다음 숫자 ID를 만든다 */
export function nextId<T>(list: T[], pick: (item: T) => number): number {
  return list.reduce((max, item) => Math.max(max, pick(item)), 0) + 1
}
