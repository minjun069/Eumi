/** 페이지 번호를 한 번에 몇 개까지 보여 줄지 */
const PAGE_WINDOW = 5

/** 목록 아래 페이지 번호 (사례자 목록·복지자원 목록 공통) */
export function Pagination({
  page,
  totalPages,
  onPage,
}: {
  page: number
  totalPages: number
  onPage: (page: number) => void
}) {
  const start = Math.max(1, Math.min(page - Math.floor(PAGE_WINDOW / 2), totalPages - PAGE_WINDOW + 1))
  const pages = Array.from({ length: Math.min(PAGE_WINDOW, totalPages) }, (_, index) => start + index)

  return (
    <nav className="pagination" aria-label="페이지">
      <button type="button" aria-label="이전 페이지" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ‹
      </button>
      {pages.map((item) => (
        <button
          key={item}
          type="button"
          className={item === page ? "is-current" : undefined}
          aria-current={item === page ? "page" : undefined}
          onClick={() => onPage(item)}
        >
          {item}
        </button>
      ))}
      <button type="button" aria-label="다음 페이지" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
        ›
      </button>
    </nav>
  )
}
