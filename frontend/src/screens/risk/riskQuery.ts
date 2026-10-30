import type { MenuProfile, RiskIndex } from "@/types/domain"

// 고립 위험 탐색의 조회 조건 ↔ 화면 주소(?…) 변환 (R5-A)
// - sigungu: 시군구 코드 (없으면 소속 기관의 관할 시군구)
// - from, to: 시작 월·종료 월 YYYY-MM (없으면 그 시군구에 적재된 전체 기간)
// - index: behavior면 행동 이상 (없으면 배경 취약성)
// - dong: 지도에서 고른 행정동 (있으면 읍면동 화면)

export type RiskQuery = {
  sigunguCode: string
  from: string | null
  to: string | null
  index: RiskIndex
  dongCode: string | null
}

/** 입력칸 (지역·기간). '적용'을 눌러야 주소에 반영된다 */
export type RiskFilters = {
  sidoCode: string | null
  sigunguCode: string | null
  /** null이면 적재된 첫 월 */
  from: string | null
  /** null이면 적재된 마지막 월 */
  to: string | null
}

export const INDEX_LABELS: Record<RiskIndex, string> = {
  background: "배경 취약성",
  behavior: "행동 이상",
}

const MONTH_PATTERN = /^\d{4}-\d{2}$/

export function parseRiskQuery(params: URLSearchParams, profile: MenuProfile): RiskQuery {
  const from = params.get("from")
  const to = params.get("to")
  return {
    sigunguCode: params.get("sigungu") || profile.jurisdictionSigunguCode,
    from: from && MONTH_PATTERN.test(from) ? from : null,
    to: to && MONTH_PATTERN.test(to) ? to : null,
    index: params.get("index") === "behavior" ? "behavior" : "background",
    dongCode: params.get("dong") || null,
  }
}

/** 처음 값과 같은 항목은 주소에서 뺀다 */
export function buildRiskSearch(query: RiskQuery, profile: MenuProfile): string {
  const params = new URLSearchParams()
  if (query.sigunguCode !== profile.jurisdictionSigunguCode) params.set("sigungu", query.sigunguCode)
  if (query.from) params.set("from", query.from)
  if (query.to) params.set("to", query.to)
  if (query.index !== "background") params.set("index", query.index)
  if (query.dongCode) params.set("dong", query.dongCode)
  const search = params.toString()
  return search ? `?${search}` : ""
}

export function filtersOf(query: RiskQuery): RiskFilters {
  return {
    sidoCode: query.sigunguCode.slice(0, 2),
    sigunguCode: query.sigunguCode,
    from: query.from,
    to: query.to,
  }
}

/** 빈 값(null)이면 적재된 전체 기간의 끝으로 채운 실제 기간. 적재된 월이 없으면 null */
export function effectivePeriod(
  period: { from: string | null; to: string | null },
  months: string[],
): { from: string; to: string } | null {
  if (months.length === 0) return null
  return { from: period.from ?? months[0], to: period.to ?? months[months.length - 1] }
}

/** 적재된 전체 기간의 끝과 같은 값은 비운다 (주소에서 빠짐) */
export function compactPeriod(period: { from: string; to: string }, months: string[]) {
  return {
    from: period.from !== months[0] ? period.from : null,
    to: period.to !== months[months.length - 1] ? period.to : null,
  }
}

/** 2025-07 → 2025.07 */
export function formatMonth(month: string): string {
  return month.replace("-", ".")
}

/** 2025-07 → 7월 */
export function shortMonth(month: string): string {
  return `${Number(month.slice(5))}월`
}
