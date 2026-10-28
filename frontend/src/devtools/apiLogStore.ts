import { useSyncExternalStore } from "react"

// API 기록 저장소. API 흉내 함수(callApi)가 호출될 때마다 한 건씩 쌓인다.
// 새로고침하면 데이터와 함께 비워진다.

export type ApiCallLog = {
  kind: "api"
  id: number
  time: string
  /** 호출 시점의 화면 주소 */
  screen: string
  featureId: string
  featureName: string
  request: unknown
  ok: boolean
  response?: unknown
  errorMessage?: string
  /** 응답에는 드러나지 않는 서버 안의 처리 (예: "가입된 계정이 없어 메일을 보내지 않음") */
  serverNotes?: string[]
}

export type ApiNoteLog = {
  kind: "note"
  id: number
  time: string
  message: string
}

export type ApiLogEntry = ApiCallLog | ApiNoteLog

type NewApiLog = Omit<ApiCallLog, "id" | "time" | "screen" | "kind">

let entries: ApiLogEntry[] = []
let sequence = 0
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((listener) => listener())
}

/** 17:07:40 형식 */
function now(): string {
  const date = new Date()
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((value) => String(value).padStart(2, "0"))
    .join(":")
}

export function addApiLog(entry: NewApiLog) {
  entries = [
    ...entries,
    {
      kind: "api",
      id: ++sequence,
      time: now(),
      screen: window.location.pathname,
      ...entry,
    },
  ]
  emit()
}

/** 상황 전환처럼 API 호출은 아니지만 흐름을 이해하는 데 필요한 표시 */
export function addLogNote(message: string) {
  entries = [...entries, { kind: "note", id: ++sequence, time: now(), message }]
  emit()
}

export function clearApiLog() {
  entries = []
  emit()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 쌓인 순서(오래된 것 → 최신) 그대로 돌려준다 */
export function useApiLog(): ApiLogEntry[] {
  return useSyncExternalStore(subscribe, () => entries)
}
