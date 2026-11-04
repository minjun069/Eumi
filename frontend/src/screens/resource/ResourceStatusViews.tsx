import { EmptyState } from "@/components/common/EmptyState"
import { RESOURCE_ACCESS_TEXT, type ResourceAccessError } from "@/screens/resource/resourceErrors"

/** 불러오는 중 */
export function ResourceLoading({ text = "불러오는 중입니다." }: { text?: string }) {
  return (
    <p className="resource-loading" role="status">
      {text}
    </p>
  )
}

/** 불러오지 못함 + 다시 시도 */
export function ResourceLoadFailed({
  title,
  message,
  onRetry,
}: {
  title: string
  message: string
  onRetry: () => void
}) {
  return (
    <div className="resource-not-found" role="alert">
      <EmptyState title={title} description={message} />
      <button type="button" className="btn btn-outline" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  )
}

/** 담당자 아님(403) / 찾을 수 없음(404) 안내 */
export function ResourceAccessErrorView({
  error,
  backLabel,
  onBack,
}: {
  error: ResourceAccessError
  backLabel: string
  onBack: () => void
}) {
  const text = RESOURCE_ACCESS_TEXT[error]
  return (
    <div className="resource-not-found">
      <EmptyState title={text.title} description={text.description} />
      <button type="button" className="btn btn-outline" onClick={onBack}>
        {backLabel}
      </button>
    </div>
  )
}
