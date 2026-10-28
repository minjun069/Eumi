import { useEffect, useState, useSyncExternalStore, type DependencyList } from "react"
import type { AgentScreen } from "@/mock/api/agentApi"

// AI Agent 패널이 참고할 '지금 보는 화면'.
// 화면이 useAgentContext로 등록하면 패널 위쪽에 표시하고, 질문할 때 screen 값으로 보낸다 (A3-A: 종류와 ID·조건만).
// label·caseName은 우리 화면에만 쓰고 서버로 보내지 않는다.

export type AgentContext = {
  screen: AgentScreen
  /** 패널 위쪽 표시 (예: "사례자 상세 · 관리번호 2025-0005") */
  label: string
  /** 사례자 상세: 추천 자원 상세의 안내 문구용 (A6-A, 서버로 보내지 않음) */
  caseRef?: { caseId: number; caseName: string }
}

const entries = new Map<number, AgentContext>()
let sequence = 0
let current: AgentContext | null = null
const listeners = new Set<() => void>()

function update() {
  const latest = Math.max(0, ...entries.keys())
  current = entries.get(latest) ?? null
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useCurrentAgentContext(): AgentContext | null {
  return useSyncExternalStore(subscribe, () => current)
}

/** 화면 컴포넌트에서 호출: 이 화면이 떠 있는 동안 AI Agent가 참고할 화면 정보 (null이면 등록하지 않음) */
export function useAgentContext(context: AgentContext | null, deps: DependencyList) {
  const [id] = useState(() => ++sequence)
  useEffect(() => {
    if (!context) {
      entries.delete(id)
      update()
      return
    }
    entries.set(id, context)
    update()
    return () => {
      entries.delete(id)
      update()
    }
  }, deps)
}
