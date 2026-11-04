import { EmptyState } from "@/components/common/EmptyState"
import { CASE_ACCESS_TEXT, type CaseAccessError } from "@/screens/case/caseErrors"

/** 불러오는 중 */
export function CaseLoading({ text = "불러오는 중입니다." }: { text?: string }) {
  return (
    <p className="case-loading" role="status">
      {text}
    </p>
  )
}

/** 불러오지 못함 + 다시 시도 */
export function CaseLoadFailed({ title, message, onRetry }: { title: string; message: string; onRetry: () => void }) {
  return (
    <div className="case-access-error" role="alert">
      <EmptyState title={title} description={message} />
      <button type="button" className="btn btn-outline" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  )
}

/** 권한 없음(403) / 찾을 수 없음(404) 안내 (D10-B) */
export function CaseAccessErrorView({
  error,
  forbiddenDescription,
  onBack,
}: {
  error: CaseAccessError
  forbiddenDescription?: string
  onBack: () => void
}) {
  const text = CASE_ACCESS_TEXT[error]
  return (
    <div className="case-access-error">
      <EmptyState
        title={text.title}
        description={error === "FORBIDDEN" && forbiddenDescription ? forbiddenDescription : text.description}
      />
      <button type="button" className="btn btn-outline" onClick={onBack}>
        목록으로
      </button>
    </div>
  )
}
