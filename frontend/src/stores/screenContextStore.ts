import { useEffect, useId, useSyncExternalStore } from "react"
import type { ScreenContext } from "@/api/agentApi"

// AI 패널 질문에 붙이는 화면 문맥 (ai-agent-panel.md 3-1, API-03 context)
// - 지금 보이는 화면이 useScreenContext로 값을 정하고, 화면을 벗어나면(언마운트·숨김) 지운다.
// - 패널은 입력칸 위에 라벨을 보이고, agentStore는 질문을 보내는 순간의 값을 context로 넣는다.
// - 저장하지 않는다: 메모리에만 두고 sessionStorage·질문 행에 넣지 않는다.

export type ScreenContextValue = {
  /** 값이 있는 필드만 담는다 (null·빈 필드는 BE가 400) */
  context: ScreenContext
  /** 패널에 보이는 함께 가는 값. 예: 역삼1동 · 2025.12 기준 */
  label: string
}

/** 값을 정한 화면별 값. 마지막으로 정한 화면의 값을 쓴다 (보이는 화면은 하나다) */
const sources = new Map<string, ScreenContextValue>()
let current: ScreenContextValue | null = null
const listeners = new Set<() => void>()

function emit() {
  const entries = [...sources.values()]
  current = entries.length === 0 ? null : entries[entries.length - 1]
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export const screenContext = {
  /** 질문을 보내는 순간의 화면 문맥 (없으면 null) */
  get(): ScreenContextValue | null {
    return current
  },
}

/** 패널에서 읽는다 */
export function useScreenContextValue(): ScreenContextValue | null {
  return useSyncExternalStore(subscribe, () => current)
}

/**
 * 화면에서 호출: 이 화면이 보이는 동안 질문에 붙일 문맥을 정한다.
 * context가 null이거나 필드가 하나도 없으면 문맥을 정하지 않는다 (숨겨진 화면도 null을 넘긴다)
 */
export function useScreenContext(context: ScreenContext | null, label: string) {
  const id = useId()
  const dongCode = context?.dongCode
  const month = context?.month
  useEffect(() => {
    const clean: ScreenContext = {
      ...(dongCode ? { dongCode } : {}),
      ...(month ? { month } : {}),
    }
    if (Object.keys(clean).length === 0) return
    sources.set(id, { context: clean, label })
    emit()
    return () => {
      sources.delete(id)
      emit()
    }
  }, [id, dongCode, month, label])
}
