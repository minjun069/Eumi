/** 목록 표의 열 제목 정렬 버튼 (누르면 정렬, 다시 누르면 방향 바꿈) */
export function SortButton({
  label,
  active,
  direction,
  onClick,
}: {
  label: string
  active: boolean
  direction: "asc" | "desc"
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={`sort-button ${active ? "is-active" : ""}`}
      aria-label={`${label} 정렬${active ? (direction === "asc" ? " (오름차순)" : " (내림차순)") : ""}`}
      onClick={onClick}
    >
      {label}
      <span className="sort-icon" aria-hidden="true">
        {active ? (direction === "asc" ? "▲" : "▼") : "↕"}
      </span>
    </button>
  )
}
