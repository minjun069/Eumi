import { useSyncExternalStore } from "react"

// 알림 메시지(토스트). 화면 아래쪽에 잠깐 떴다가 사라진다.

export type Toast = {
  id: number
  message: string
  tone: "default" | "error"
}

const TOAST_DURATION_MS = 2500

let toasts: Toast[] = []
let sequence = 0
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((listener) => listener())
}

export function showToast(message: string, tone: Toast["tone"] = "default") {
  const id = ++sequence
  toasts = [...toasts, { id, message, tone }]
  emit()
  window.setTimeout(() => {
    toasts = toasts.filter((toast) => toast.id !== id)
    emit()
  }, TOAST_DURATION_MS)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, () => toasts)
}
