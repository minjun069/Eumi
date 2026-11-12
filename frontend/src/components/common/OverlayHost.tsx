import { useEffect } from "react"
import { settleConfirm, useConfirmRequest } from "@/stores/confirmStore"
import { useToasts } from "@/stores/toastStore"

/** 서비스 화면(.app-frame) 안에 확인 창과 알림 메시지를 띄운다 (개발용 영역은 가리지 않음) */
export function OverlayHost() {
  return (
    <>
      <ConfirmHost />
      <ToastStack />
    </>
  )
}

function ConfirmHost() {
  const request = useConfirmRequest()

  useEffect(() => {
    if (!request) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") settleConfirm(false)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [request])

  if (!request) return null

  return (
    <div className="dialog-backdrop" onClick={() => settleConfirm(false)}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-title">{request.title}</h2>
        {request.message && <p>{request.message}</p>}
        <div className="dialog-actions">
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => settleConfirm(false)}
          >
            {request.cancelLabel ?? "취소"}
          </button>
          <button
            type="button"
            className={`btn ${
              request.tone === "danger" ? "btn-danger" : "btn-primary"
            }`}
            onClick={() => settleConfirm(true)}
            autoFocus
          >
            {request.confirmLabel ?? "확인"}
          </button>
        </div>
      </div>
    </div>
  )
}

function ToastStack() {
  const toasts = useToasts()
  if (toasts.length === 0) return null

  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast ${toast.tone === "error" ? "toast-error" : ""}`}
        >
          {toast.message}
        </div>
      ))}
    </div>
  )
}
