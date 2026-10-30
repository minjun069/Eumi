import type { SortDirection } from "@/mock/api/caseApi"
import type { ResourceSearchRequest, ResourceSortKey } from "@/mock/api/resourceApi"
import type { AgeGroup, Gender } from "@/types/domain"
import { AGE_GROUPS } from "@/utils/age"

// 복지자원 목록의 검색 조건 ↔ 화면 주소(?…) 변환.
// 조건·정렬·페이지를 주소에 남겨, 상세에서 뒤로 오거나 새로고침해도 유지한다.
//
// 지역 주소 규칙 (처음 값은 지역 전체, 3.1.1)
// - dongCode=…        행정동 (행정동 코드 앞자리로 시도·시군구를 안다). 고립 위험 탐색에서 올 때도 이 형식
// - sido=…&sigungu=…  시도(·시군구)

export const RESOURCE_PAGE_SIZE = 10

export type ResourceListFilters = {
  sidoCode: string | null
  sigunguCode: string | null
  dongCode: string | null
  ageGroup: AgeGroup | "전체"
  gender: Gender | "전체"
  /** 정원 입력칸 (빈 문자열이면 제한 없음) */
  capacityMin: string
  capacityMax: string
  managerName: string
}

export type ResourceListQuery = ResourceListFilters & {
  sort: ResourceSortKey
  direction: SortDirection
  page: number
}

/** 처음 정렬: 운영 마감일이 이른 순 (3.1.2) */
export const DEFAULT_SORT: { sort: ResourceSortKey; direction: SortDirection } = {
  sort: "periodEnd",
  direction: "asc",
}

const SORT_KEYS: ResourceSortKey[] = ["resourceName", "capacity", "periodEnd", "fee"]

/** 필터 처음 값: 모두 전체 (3.1.1) */
export const DEFAULT_FILTERS: ResourceListFilters = {
  sidoCode: null,
  sigunguCode: null,
  dongCode: null,
  ageGroup: "전체",
  gender: "전체",
  capacityMin: "",
  capacityMax: "",
  managerName: "",
}

const NUMBER_PATTERN = /^\d+$/

export function parseQuery(params: URLSearchParams): ResourceListQuery {
  const dongCode = params.get("dongCode")
  const sido = params.get("sido")
  const region = dongCode
    ? { sidoCode: dongCode.slice(0, 2), sigunguCode: dongCode.slice(0, 5), dongCode }
    : { sidoCode: sido, sigunguCode: sido ? params.get("sigungu") : null, dongCode: null }
  const ageGroup = params.get("ageGroup")
  const gender = params.get("gender")
  const capacityMin = params.get("capMin") ?? ""
  const capacityMax = params.get("capMax") ?? ""
  const sort = params.get("sort") as ResourceSortKey | null
  const direction = params.get("dir")
  const page = Number(params.get("page") ?? "1")
  return {
    ...region,
    ageGroup: AGE_GROUPS.includes(ageGroup as AgeGroup) ? (ageGroup as AgeGroup) : "전체",
    gender: gender === "남" || gender === "여" ? gender : "전체",
    capacityMin: NUMBER_PATTERN.test(capacityMin) ? capacityMin : "",
    capacityMax: NUMBER_PATTERN.test(capacityMax) ? capacityMax : "",
    managerName: params.get("manager") ?? "",
    sort: sort && SORT_KEYS.includes(sort) ? sort : DEFAULT_SORT.sort,
    direction: direction === "asc" || direction === "desc" ? direction : "asc",
    page: Number.isInteger(page) && page > 0 ? page : 1,
  }
}

/** 처음 값과 같은 조건은 주소에서 뺀다 */
export function buildSearch(query: ResourceListQuery): string {
  const params = new URLSearchParams()
  if (query.dongCode) {
    params.set("dongCode", query.dongCode)
  } else if (query.sidoCode) {
    params.set("sido", query.sidoCode)
    if (query.sigunguCode) params.set("sigungu", query.sigunguCode)
  }
  if (query.ageGroup !== "전체") params.set("ageGroup", query.ageGroup)
  if (query.gender !== "전체") params.set("gender", query.gender)
  if (query.capacityMin.trim()) params.set("capMin", query.capacityMin.trim())
  if (query.capacityMax.trim()) params.set("capMax", query.capacityMax.trim())
  if (query.managerName.trim()) params.set("manager", query.managerName.trim())
  if (query.sort !== DEFAULT_SORT.sort || query.direction !== DEFAULT_SORT.direction) {
    params.set("sort", query.sort)
    params.set("dir", query.direction)
  }
  if (query.page > 1) params.set("page", String(query.page))
  const search = params.toString()
  return search ? `?${search}` : ""
}

const toNumber = (value: string) => (value.trim() ? Number(value.trim()) : null)

export function toSearchRequest(query: ResourceListQuery): ResourceSearchRequest {
  return {
    sidoCode: query.sidoCode,
    sigunguCode: query.sigunguCode,
    dongCode: query.dongCode,
    ageGroup: query.ageGroup,
    gender: query.gender,
    capacityMin: toNumber(query.capacityMin),
    capacityMax: toNumber(query.capacityMax),
    managerName: query.managerName.trim(),
    sort: query.sort,
    direction: query.direction,
    page: query.page,
    size: RESOURCE_PAGE_SIZE,
  }
}

export function pickFilters(query: ResourceListQuery): ResourceListFilters {
  const { sort: _sort, direction: _direction, page: _page, ...filters } = query
  return filters
}

/** 정원 범위 입력 확인 ('검색'을 누를 때) */
export function capacityError(min: string, max: string): string | null {
  const values = [min.trim(), max.trim()]
  if (values.some((value) => value && !NUMBER_PATTERN.test(value))) return "정원은 0 이상의 숫자로 입력하세요."
  if (values[0] && values[1] && Number(values[0]) > Number(values[1])) return "최소 정원이 최대 정원보다 큽니다."
  return null
}
