import type { ResourceListItem, ResourceSearchQuery, ResourceSortKey } from "@/api/resourceApi"
import { EmptyState } from "@/components/common/EmptyState"
import { Pagination } from "@/components/common/Pagination"
import { SortButton } from "@/components/common/SortButton"
import { formatFee, formatPeriod, formatRegion } from "@/screens/resource/resourceFormat"

type SortDirection = NonNullable<ResourceSearchQuery["direction"]>

/**
 * 3.1.2 복지자원 목록: 자원명, 수행·담당 기관, 지원 대상, 정원, 지역, 운영 기간, 이용자 부담금, 상태
 * 진행 중 자원이 먼저 오고(서버), 자원명·정원·운영 기간·이용자 부담금 열 제목으로 정렬. 행을 누르면 상세(3.2)
 * 5.2.1 담당 복지자원 목록도 같은 표를 쓴다 (정렬 버튼·페이지 없음 → sorting·onPage를 넘기지 않음)
 */
export function ResourceTable({
  result,
  refreshing = false,
  sorting,
  onPage,
  onOpen,
  countLabel = "검색 결과",
  emptyTitle = "조건에 맞는 복지자원이 없습니다.",
}: {
  result: { totalCount: number; items: ResourceListItem[]; page?: number; totalPages?: number }
  /** 새 조건으로 다시 받는 중 (이전 결과를 흐리게 보여 준다) */
  refreshing?: boolean
  sorting?: { sort: ResourceSortKey; direction: SortDirection; onSort: (key: ResourceSortKey) => void }
  onPage?: (page: number) => void
  onOpen: (resourceId: number) => void
  countLabel?: string
  emptyTitle?: string
}) {
  const header = (key: ResourceSortKey, label: string) =>
    sorting ? (
      <th aria-sort={sorting.sort === key ? (sorting.direction === "asc" ? "ascending" : "descending") : undefined}>
        <SortButton
          label={label}
          active={sorting.sort === key}
          direction={sorting.direction}
          onClick={() => sorting.onSort(key)}
        />
      </th>
    ) : (
      <th>{label}</th>
    )

  return (
    <div className={`resource-results${refreshing ? " is-refreshing" : ""}`} aria-busy={refreshing}>
      <p className="result-count">
        {countLabel} <strong>{result.totalCount}</strong>개
      </p>
      <table className="data-table resource-table">
        <thead>
          <tr>
            {header("resourceName", "자원명")}
            <th>수행·담당 기관</th>
            <th>지원 대상</th>
            {header("capacity", "정원")}
            <th>지역</th>
            {header("periodEnd", "운영 기간")}
            {header("fee", "이용자 부담금")}
            <th>상태</th>
          </tr>
        </thead>
        <tbody>
          {result.items.map((item) => {
            const region = formatRegion(item.sigunguName, item.dongName)
            return (
              <tr
                key={item.resourceId}
                className={item.status === "종료" ? "is-ended" : undefined}
                tabIndex={0}
                onClick={() => onOpen(item.resourceId)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") onOpen(item.resourceId)
                }}
              >
                <td className="col-name" title={item.resourceName}>
                  {item.resourceName}
                </td>
                <td title={item.operatingOrgName}>{item.operatingOrgName}</td>
                <td title={item.target}>{item.target}</td>
                <td className="col-number">{item.capacity}명</td>
                <td title={region}>{region}</td>
                <td className="col-period">{formatPeriod(item.periodStart, item.periodEnd)}</td>
                <td className="col-number">{formatFee(item.fee)}</td>
                <td>
                  <span className={`status-badge ${item.status === "종료" ? "is-ended" : "is-active"}`}>
                    {item.status}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {result.items.length === 0 && <EmptyState title={emptyTitle} />}

      {/* 결과가 없으면 totalPages=0이라 페이지 번호를 그리지 않는다 */}
      {onPage && result.page !== undefined && result.totalPages !== undefined && result.totalPages > 0 && (
        <Pagination page={result.page} totalPages={result.totalPages} onPage={onPage} />
      )}
    </div>
  )
}
