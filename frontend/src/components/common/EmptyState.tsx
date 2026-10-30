/** 목록 결과가 없을 때 표시 */
export function EmptyState({
  title = "조건에 맞는 결과가 없습니다.",
  description,
}: {
  title?: string
  description?: string
}) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {description && <p>{description}</p>}
    </div>
  )
}
