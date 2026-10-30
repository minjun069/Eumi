import { useEffect, useState, useSyncExternalStore, type DependencyList } from "react"

// 화면별 '예외 상황' 도구.
// 각 화면이 자기 화면에서 재현할 상황(입력값 채우기 등)을 등록하면,
// 개발용 영역의 '예외 상황' 칸에 버튼으로 나타난다. 화면을 떠나면 자동으로 사라진다.
// 화면 위에 창(예: 상담 창)이 떠서 따로 등록하면 창의 도구를 보여 주고, 창을 닫으면 화면의 도구로 돌아간다.

export type DevScenarioAction = {
  label: string
  run: () => void
}

export type DevScenarioInfo = {
  label: string
  value: string
  action?: DevScenarioAction
}

export type DevScenarioGroup = {
  title: string
  actions: DevScenarioAction[]
}

export type DevScenario = {
  /** 어느 화면의 도구인지 (예: "로그인 화면") */
  screen: string
  hint?: string
  actions: DevScenarioAction[]
  /** 제목을 붙여 따로 묶는 버튼 (예: 인증 코드 도구) */
  groups?: DevScenarioGroup[]
  infos?: DevScenarioInfo[]
}

/** 등록한 순서(먼저 그려진 화면이 작은 번호) → 도구. 가장 나중에 등록한 것을 보여 준다 */
const entries = new Map<number, DevScenario>()
let sequence = 0
let current: DevScenario | null = null
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

export function useCurrentDevScenario(): DevScenario | null {
  return useSyncExternalStore(subscribe, () => current)
}

/** 화면 컴포넌트에서 호출: 이 화면이 떠 있는 동안 예외 상황 도구를 보여준다 */
export function useDevScenario(scenario: DevScenario, deps: DependencyList) {
  const [id] = useState(() => ++sequence)
  useEffect(() => {
    entries.set(id, scenario)
    update()
    return () => {
      entries.delete(id)
      update()
    }
    // deps는 호출하는 화면이 정한다 (scenario 객체는 렌더링마다 새로 만들어진다)
  }, deps)
}
