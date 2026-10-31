import { useEffect, useRef } from "react"
import { useBlocker, type BlockerFunction } from "react-router"
import { confirmDialog } from "@/stores/confirmStore"
import { LEAVE_CONFIRM, leaveGuard, useHasUnsavedChanges } from "@/stores/leaveGuardStore"

const shouldBlock: BlockerFunction = ({ currentLocation, nextLocation }) =>
  leaveGuard.isDirty() &&
  (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search)

/**
 * 바뀐 내용이 있는 화면에서 다른 화면으로 이동하려 하면 막고 확인 창을 띄운다.
 * 메뉴·버튼 이동과 브라우저 뒤로 가기에 모두 적용된다 (앱에 하나만 둔다).
 * 막을 내용이 있을 때만 화면 이동 감시(useBlocker)를 켠다.
 */
export function LeaveGuardHost() {
  const hasUnsavedChanges = useHasUnsavedChanges()
  return hasUnsavedChanges ? <NavigationBlocker /> : null
}

function NavigationBlocker() {
  const blocker = useBlocker(shouldBlock)
  const blockerRef = useRef(blocker)
  blockerRef.current = blocker

  useEffect(() => {
    if (blocker.state !== "blocked") return
    confirmDialog(LEAVE_CONFIRM).then((ok) => {
      const current = blockerRef.current
      if (current.state !== "blocked") return
      if (ok) {
        leaveGuard.release()
        current.proceed()
      } else {
        current.reset()
      }
    })
  }, [blocker.state])

  return null
}
