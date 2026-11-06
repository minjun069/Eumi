import { EmptyState } from "@/components/common/EmptyState"

/** 불러오는 중 */
export function MyLoading({ text = "불러오는 중입니다." }: { text?: string }) {
  return (
    <p className="my-loading" role="status">
      {text}
    </p>
  )
}

/** 불러오지 못함 + 다시 시도 */
export function MyLoadFailed({ title, message, onRetry }: { title: string; message: string; onRetry: () => void }) {
  return (
    <div className="my-load-failed" role="alert">
      <EmptyState title={title} description={message} />
      <button type="button" className="btn btn-outline" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  )
}
