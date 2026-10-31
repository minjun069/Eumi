import { EmptyState } from "@/components/common/EmptyState"
import { Pagination } from "@/components/common/Pagination"
import { SortButton } from "@/components/common/SortButton"
import type { CaseSearchResponse, CaseSortKey, SortDirection } from "@/mock/api/caseApi"

/**
 * 4.1.2 고립 사례자 목록 (C5-B: 관리번호, 이름, 연령/성별, 지역, 최초 등록일, 최근 기록일)
 * 열 제목을 누르면 정렬(C1-A), 아래 페이지 번호(C3-A), 행을 누르면 상세(4.2)
 */
export function CaseTable({
  result,
  sort,
  direction,
  onSort,
  onPage,
  onOpen,
}: {
  result: CaseSearchResponse
  sort: CaseSortKey
  direction: SortDirection
  onSort: (key: CaseSortKey) => void
  onPage: (page: number) => void
  onOpen: (caseId: number) => void
}) {
  const sortButton = (key: CaseSortKey, label: string) => (
    <SortButton label={label} active={sort === key} direction={direction} onClick={() => onSort(key)} />
  )
  const ariaSort = (key: CaseSortKey) =>
    sort === key ? (direction === "asc" ? "ascending" : "descending") : undefined

  return (
    <div className="case-results">
      <p className="result-count">
        검색 결과 <strong>{result.totalCount}</strong>명
      </p>
      <table className="data-table case-table">
        <thead>
          <tr>
            <th className="col-no">관리번호</th>
            <th aria-sort={ariaSort("name")}>{sortButton("name", "이름")}</th>
            <th aria-sort={ariaSort("age") ?? ariaSort("gender")}>
              <span className="sort-pair">
                {sortButton("age", "연령")}
                <span aria-hidden="true">/</span>
                {sortButton("gender", "성별")}
              </span>
            </th>
            <th aria-sort={ariaSort("region")}>{sortButton("region", "지역")}</th>
            <th aria-sort={ariaSort("firstRegisteredAt")}>
              {sortButton("firstRegisteredAt", "최초 등록일")}
            </th>
            <th aria-sort={ariaSort("lastRecordedAt")}>{sortButton("lastRecordedAt", "최근 기록일")}</th>
          </tr>
        </thead>
        <tbody>
          {result.items.map((item) => (
            <tr
              key={item.caseId}
              tabIndex={0}
              onClick={() => onOpen(item.caseId)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onOpen(item.caseId)
              }}
            >
              <td className="col-no">{item.managementNo}</td>
              <td className="col-name">{item.name}</td>
              <td>
                {item.age}세 / {item.gender}
              </td>
              <td>
                {item.sigunguName} {item.dongName}
              </td>
              <td>{item.firstRegisteredAt}</td>
              <td>{item.lastRecordedAt ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.items.length === 0 && <EmptyState title="조건에 맞는 사례자가 없습니다." />}

      {result.totalCount > 0 && <Pagination page={result.page} totalPages={result.totalPages} onPage={onPage} />}
    </div>
  )
}
