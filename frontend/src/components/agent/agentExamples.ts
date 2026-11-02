import type { AgentScreen } from "@/api/agentApi"

// 화면별 예시 질문 (FR-072, 패널의 질문 버튼)

/** 사례자 상세의 'AI 맞춤 자원 추천' 버튼이 보내는 정해진 질문 (FR-077) */
export const RECOMMEND_QUESTION = "이 사례자에게 맞는 복지자원을 추천해 줘"

export function exampleQuestions(screen: AgentScreen): string[] {
  switch (screen.screenType) {
    case "risk-district":
      return ["고립 위험 현황을 요약해 줘", "행동 이상이 가장 많이 오른 동은 어디야?"]
    case "risk-dong":
      return ["보고서의 주요 원인을 쉽게 설명해 줘", "이 동에서 먼저 살펴볼 대상은 누구야?"]
    case "case-detail":
      return [RECOMMEND_QUESTION]
    case "resource-detail":
      return ["이 자원은 어떤 사람에게 맞아?"]
    case "other":
      return ["이 화면에서 무엇을 할 수 있어?"]
  }
}
