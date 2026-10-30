import { useSyncExternalStore } from "react"

// 확인 창 (삭제·탈퇴처럼 되돌리기 어려운 동작 전에 띄운다).
// const ok = await confirmDialog({ title: "삭제할까요?", tone: "danger" })

export type ConfirmOptions = {
  title: string
  message?: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: "default" | "danger"
}

type ConfirmRequest = ConfirmOptions & { resolve: (confirmed: boolean) => void }

let current: ConfirmRequest | null = null
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((listener) => listener())
}

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  // 이미 떠 있는 창이 있으면 취소로 닫고 새 창을 띄운다
  current?.resolve(false)
  return new Promise((resolve) => {
    current = { ...options, resolve }
    emit()
  })
}

export function settleConfirm(confirmed: boolean) {
  current?.resolve(confirmed)
  current = null
  emit()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useConfirmRequest(): ConfirmOptions | null {
  return useSyncExternalStore(subscribe, () => current)
}
