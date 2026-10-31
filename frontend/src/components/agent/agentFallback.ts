import type { AgentContext } from "@/stores/agentContextStore"

// 화면이 따로 등록하지 않았을 때 AI Agent 패널이 쓰는 '지금 보는 화면' (주소로 정함)

const LABELS: { pattern: RegExp; label: string }[] = [
  { pattern: /^\/risk/, label: "고립 위험 탐색" },
  { pattern: /^\/resources\/new$/, label: "복지자원 등록" },
  { pattern: /^\/resources\/[^/]+\/edit$/, label: "복지자원 수정" },
  { pattern: /^\/resources\/[^/]+$/, label: "복지자원 상세" },
  { pattern: /^\/resources$/, label: "복지자원 조회" },
  { pattern: /^\/cases\/new$/, label: "사례자 등록" },
  { pattern: /^\/cases\/[^/]+\/edit$/, label: "사례자 수정" },
  { pattern: /^\/cases\/[^/]+$/, label: "사례자 상세" },
  { pattern: /^\/cases$/, label: "사례자 목록" },
  { pattern: /^\/my/, label: "마이페이지" },
]

export function fallbackAgentContext(pathname: string): AgentContext {
  return {
    screen: { screenType: "other", path: pathname },
    label: LABELS.find((item) => item.pattern.test(pathname))?.label ?? "이음이",
  }
}
