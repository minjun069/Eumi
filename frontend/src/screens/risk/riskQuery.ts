import type { MenuProfile } from "@/api/types"
import { PATHS } from "@/routes/paths"

// 고립 위험 탐색의 조회 조건 ↔ 화면 주소(?…) 변환 (R5-A)
// - sigungu: 시군구 코드 (없으면 소속 기관의 관할 시군구)
// - from, to: 시작 월·종료 월 YYYY-MM (없으면 그 시군구에 적재된 전체 기간)
// - index: background면 배경 취약성, behavior면 행동 이상 (없으면 종합 위험 = 처음 보이는 지도)
// - dong: 지도에서 고른 행정동 10자리 (있으면 읍면동 화면)

/** ① 지도의 지표. 지표마다 Tableau 지도 대시보드가 따로 있다 (tableauConfig.TABLEAU_MAP_VIEWS) */
export type RiskIndex = "risk" | "background" | "behavior"

export type RiskQuery = {
  sigunguCode: string
  from: string | null
  to: string | null
  index: RiskIndex
  dongCode: string | null
}

/** 시군구 지도에서 읍면동으로 갈 때 남기는 값 (navigation state): 돌아갈 때 기간이 그대로면 뒤로 가기 */
export type DistrictState = { fromDistrict: true; from: string | null; to: string | null }

/** 입력칸 (지역·기간). '적용'을 눌러야 주소에 반영된다 */
export type RiskFilters = {
  sidoCode: string | null
  sigunguCode: string | null
  /** null이면 적재된 첫 월 */
  from: string | null
  /** null이면 적재된 마지막 월 */
  to: string | null
}

/** 버튼 순서대로. 종합 위험(risk_grade)은 배경 취약성·행동 이상 단계와 다른 개념이라 따로 이름 붙인다 (상세 계약 대시보드 절) */
export const INDEX_LABELS: Record<RiskIndex, string> = {
  risk: "종합 위험",
  background: "배경 취약성",
  behavior: "행동 이상",
}

const INDEXES = Object.keys(INDEX_LABELS) as RiskIndex[]

/** 처음 들어오거나 지표를 고르지 않았을 때의 지도. 배경 취약성·행동 이상은 사용자가 버튼으로 고른다 (11/5 결정) */
const DEFAULT_INDEX: RiskIndex = "risk"

const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/
const SIGUNGU_PATTERN = /^\d{5}$/
/** 행정동 코드 10자리 (통계청 adm_cd8과 섞지 않는다) */
export const DONG_PATTERN = /^\d{10}$/

export function parseRiskQuery(params: URLSearchParams, profile: MenuProfile): RiskQuery {
  const sigungu = params.get("sigungu")
  const from = params.get("from")
  const to = params.get("to")
  const index = INDEXES.find((item) => item === params.get("index"))
  return {
    sigunguCode: sigungu && SIGUNGU_PATTERN.test(sigungu) ? sigungu : profile.jurisdictionSigunguCode,
    from: from && MONTH_PATTERN.test(from) ? from : null,
    to: to && MONTH_PATTERN.test(to) ? to : null,
    index: index ?? DEFAULT_INDEX,
    dongCode: params.get("dong") || null,
  }
}

/** 처음 값과 같은 항목은 주소에서 뺀다 */
export function buildRiskSearch(query: RiskQuery, profile: MenuProfile): string {
  const params = new URLSearchParams()
  if (query.sigunguCode !== profile.jurisdictionSigunguCode) params.set("sigungu", query.sigunguCode)
  if (query.from) params.set("from", query.from)
  if (query.to) params.set("to", query.to)
  if (query.index !== DEFAULT_INDEX) params.set("index", query.index)
  if (query.dongCode) params.set("dong", query.dongCode)
  const search = params.toString()
  return search ? `?${search}` : ""
}

/** 조건을 담은 고립 위험 탐색 주소 */
export function riskUrl(query: RiskQuery, profile: MenuProfile): string {
  return `${PATHS.risk}${buildRiskSearch(query, profile)}`
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

/** 두 달이 모두 적재된 월이고 시작 월이 종료 월보다 늦지 않은지 (주소를 직접 고친 경우 등) */
export function isLoadedPeriod(period: { from: string; to: string }, months: string[]): boolean {
  return months.includes(period.from) && months.includes(period.to) && period.from <= period.to
}

/** 2026-08 → 2026.08 */
export function formatMonth(month: string): string {
  return month.replace("-", ".")
}

/** 기간 표시: 한 달이면 그 달만 */
export function formatPeriod(period: { from: string; to: string }): string {
  return period.from === period.to ? formatMonth(period.from) : `${formatMonth(period.from)} ~ ${formatMonth(period.to)}`
}
