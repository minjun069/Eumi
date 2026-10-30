import { useEffect, useId, useSyncExternalStore } from "react"
import { confirmDialog, type ConfirmOptions } from "@/stores/confirmStore"

// '저장하지 않은 내용' 경고 (명세 추가 항목, 4.2.1·4.2.2)
// - 입력 중인 화면·창이 useLeaveGuard(바뀐 내용이 있는지)를 부르면,
//   화면 이동(메뉴, 목록으로·취소, 브라우저 뒤로 가기)은 LeaveGuardHost가 막고 확인 창을 띄운다.
// - 로그아웃처럼 화면 이동 전에 다른 일을 하는 동작은 leaveGuard.confirmLeave()로 먼저 묻는다.
// - 브라우저 새로고침·탭 닫기에는 경고하지 않는다.

export const LEAVE_CONFIRM: ConfirmOptions = {
  title: "저장하지 않은 내용이 있습니다.",
  message: "나가면 입력한 내용이 사라집니다.",
  confirmLabel: "나가기",
  cancelLabel: "계속 작성",
}

/** 지금 바뀐 내용이 있는 화면·창 */
const dirtySources = new Set<string>()
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 바뀐 내용이 있는 화면·창이 하나라도 있는지 (LeaveGuardHost가 이때만 화면 이동을 막는다) */
export function useHasUnsavedChanges(): boolean {
  return useSyncExternalStore(subscribe, () => dirtySources.size > 0)
}

export const leaveGuard = {
  isDirty(): boolean {
    return dirtySources.size > 0
  },

  /** 경고 없이 떠나도록 모두 해제 (저장한 뒤 이동할 때, '나가기'를 고른 뒤, 개발용 상황 전환) */
  release() {
    dirtySources.clear()
    emit()
  },

  /** 바뀐 내용이 있으면 확인 창을 띄우고, '나가기'를 고르면 true */
  async confirmLeave(): Promise<boolean> {
    if (dirtySources.size === 0) return true
    const ok = await confirmDialog(LEAVE_CONFIRM)
    if (ok) leaveGuard.release()
    return ok
  },
}

/** 입력 화면·창에서 호출: 바뀐 내용이 있는 동안 떠나기 전에 경고한다 */
export function useLeaveGuard(dirty: boolean) {
  const id = useId()
  useEffect(() => {
    if (dirty) dirtySources.add(id)
    else dirtySources.delete(id)
    emit()
    return () => {
      dirtySources.delete(id)
      emit()
    }
  }, [dirty, id])
}
