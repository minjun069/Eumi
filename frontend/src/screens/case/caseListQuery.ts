import type { AgeGroup, CaseSearchQuery, CaseSortKey, Gender, SortDirection } from "@/api/caseApi"
import type { MenuProfile } from "@/api/types"
import { AGE_GROUPS } from "@/utils/age"

// 사례자 목록의 검색 조건 ↔ 화면 주소(?…) 변환.
// 조건·정렬·페이지를 주소에 남겨, 상세에서 뒤로 오거나 새로고침해도 유지한다.
//
// 지역 주소 규칙
// - dongCode=…      행정동 (행정동 코드 앞자리로 시도·시군구를 안다). 고립 위험 탐색에서 올 때도 이 형식
// - sido=all        지역 전체
// - sido=…&sigungu=… 시도(·시군구)
// - 지역 값이 없으면 처음 값: 소속 기관 관할 시군구 (C7-B)

export const CASE_PAGE_SIZE = 10

export type CaseListFilters = {
  sidoCode: string | null
  sigunguCode: string | null
  dongCode: string | null
  ageGroup: AgeGroup | "전체"
  gender: Gender | "전체"
  /** 날짜는 빈 문자열이면 제한 없음 */
  registeredFrom: string
  registeredTo: string
  recordedFrom: string
  recordedTo: string
  keyword: string
}

export type CaseListQuery = CaseListFilters & {
  sort: CaseSortKey
  direction: SortDirection
  page: number
}

/** 처음 정렬: 최초 등록일 최신순 */
export const DEFAULT_SORT: { sort: CaseSortKey; direction: SortDirection } = {
  sort: "firstRegisteredAt",
  direction: "desc",
}

/** 날짜 열은 처음 누르면 최신순, 그 밖의 열은 가나다·작은 값 순 */
export function firstDirectionOf(sort: CaseSortKey): SortDirection {
  return sort === "firstRegisteredAt" || sort === "lastRecordedAt" ? "desc" : "asc"
}

const SORT_KEYS: CaseSortKey[] = ["name", "region", "age", "gender", "firstRegisteredAt", "lastRecordedAt"]
const SIDO_PATTERN = /^\d{2}$/
const SIGUNGU_PATTERN = /^\d{5}$/
const DONG_PATTERN = /^\d{10}$/
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/

export function defaultFilters(profile: MenuProfile): CaseListFilters {
  return {
    sidoCode: profile.jurisdictionSidoCode || null,
    sigunguCode: profile.jurisdictionSigunguCode || null,
    dongCode: null,
    ageGroup: "전체",
    gender: "전체",
    registeredFrom: "",
    registeredTo: "",
    recordedFrom: "",
    recordedTo: "",
    keyword: "",
  }
}

/** 주소 → 적용된 조건. 형식이 맞지 않는 값은 처음 값으로 둔다 */
export function parseQuery(params: URLSearchParams, profile: MenuProfile): CaseListQuery {
  const base = defaultFilters(profile)
  let region: Pick<CaseListFilters, "sidoCode" | "sigunguCode" | "dongCode">
  const dongCode = params.get("dongCode")
  const sido = params.get("sido")
  const sigungu = params.get("sigungu")
  if (dongCode && DONG_PATTERN.test(dongCode)) {
    region = { sidoCode: dongCode.slice(0, 2), sigunguCode: dongCode.slice(0, 5), dongCode }
  } else if (sido === "all") {
    region = { sidoCode: null, sigunguCode: null, dongCode: null }
  } else if (sido && SIDO_PATTERN.test(sido)) {
    const sigunguCode = sigungu && SIGUNGU_PATTERN.test(sigungu) && sigungu.startsWith(sido) ? sigungu : null
    region = { sidoCode: sido, sigunguCode, dongCode: null }
  } else {
    region = { sidoCode: base.sidoCode, sigunguCode: base.sigunguCode, dongCode: null }
  }

  const ageGroup = params.get("ageGroup")
  const gender = params.get("gender")
  const sort = params.get("sort") as CaseSortKey | null
  const direction = params.get("dir")
  const page = Number(params.get("page") ?? "1")
  const date = (key: string) => {
    const value = params.get(key) ?? ""
    return DATE_PATTERN.test(value) ? value : ""
  }

  return {
    ...region,
    ageGroup: AGE_GROUPS.includes(ageGroup as AgeGroup) ? (ageGroup as AgeGroup) : "전체",
    gender: gender === "남" || gender === "여" ? gender : "전체",
    registeredFrom: date("regFrom"),
    registeredTo: date("regTo"),
    recordedFrom: date("recFrom"),
    recordedTo: date("recTo"),
    keyword: params.get("keyword") ?? "",
    sort: sort && SORT_KEYS.includes(sort) ? sort : DEFAULT_SORT.sort,
    direction:
      direction === "asc" || direction === "desc"
        ? direction
        : sort && SORT_KEYS.includes(sort)
          ? firstDirectionOf(sort)
          : DEFAULT_SORT.direction,
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
  }
}

/** 처음 값과 같은 조건은 주소에서 뺀다 */
export function buildSearch(query: CaseListQuery, profile: MenuProfile): string {
  const params = new URLSearchParams()
  const base = defaultFilters(profile)
  if (query.dongCode) {
    params.set("dongCode", query.dongCode)
  } else if (!query.sidoCode) {
    params.set("sido", "all")
  } else if (query.sidoCode !== base.sidoCode || query.sigunguCode !== base.sigunguCode) {
    params.set("sido", query.sidoCode)
    if (query.sigunguCode) params.set("sigungu", query.sigunguCode)
  }
  if (query.ageGroup !== "전체") params.set("ageGroup", query.ageGroup)
  if (query.gender !== "전체") params.set("gender", query.gender)
  if (query.registeredFrom) params.set("regFrom", query.registeredFrom)
  if (query.registeredTo) params.set("regTo", query.registeredTo)
  if (query.recordedFrom) params.set("recFrom", query.recordedFrom)
  if (query.recordedTo) params.set("recTo", query.recordedTo)
  if (query.keyword.trim()) params.set("keyword", query.keyword.trim())
  if (query.sort !== DEFAULT_SORT.sort || query.direction !== DEFAULT_SORT.direction) {
    params.set("sort", query.sort)
    params.set("dir", query.direction)
  }
  if (query.page > 1) params.set("page", String(query.page))
  const search = params.toString()
  return search ? `?${search}` : ""
}

/** 적용된 조건 → API-19 query. 빈 값·'전체'는 보내지 않는다 (서버 기본값과 같음) */
export function toSearchRequest(query: CaseListQuery): CaseSearchQuery {
  return {
    sidoCode: query.sidoCode ?? undefined,
    sigunguCode: query.sigunguCode ?? undefined,
    dongCode: query.dongCode ?? undefined,
    ageGroup: query.ageGroup === "전체" ? undefined : query.ageGroup,
    gender: query.gender === "전체" ? undefined : query.gender,
    registeredFrom: query.registeredFrom || undefined,
    registeredTo: query.registeredTo || undefined,
    recordedFrom: query.recordedFrom || undefined,
    recordedTo: query.recordedTo || undefined,
    keyword: query.keyword.trim() || undefined,
    sort: query.sort,
    direction: query.direction,
    page: query.page,
    size: CASE_PAGE_SIZE,
  }
}

export function pickFilters(query: CaseListQuery): CaseListFilters {
  const { sort: _sort, direction: _direction, page: _page, ...filters } = query
  return filters
}

/** 시작일이 종료일보다 늦으면 오류 문구 */
export function rangeError(from: string, to: string): string | null {
  return from && to && from > to ? "시작일이 종료일보다 늦습니다." : null
}
