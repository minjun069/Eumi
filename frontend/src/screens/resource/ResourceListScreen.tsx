import "@/styles/list.css"
import "@/styles/resource.css"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { useEffect, useMemo, useState, type FormEvent } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router"
import type { AgeGroup, Gender } from "@/api/caseApi"
import { errorMessage, isApiError } from "@/api/errors"
import { RESOURCE_TEXT_LIMITS, resourceApi, resourceKeys, type ResourceSortKey } from "@/api/resourceApi"
import { FieldError } from "@/components/common/FieldError"
import { PATHS } from "@/routes/paths"
import { useRegionOptions } from "@/screens/case/RegionSelects"
import { RESOURCE_MESSAGES } from "@/screens/resource/resourceErrors"
import {
  buildSearch,
  capacityError,
  DEFAULT_FILTERS,
  parseQuery,
  pickFilters,
  toSearchRequest,
  type ResourceListFilters,
  type ResourceListQuery,
} from "@/screens/resource/resourceListQuery"
import { ResourceLoadFailed, ResourceLoading } from "@/screens/resource/ResourceStatusViews"
import { ResourceTable } from "@/screens/resource/ResourceTable"
import { AGE_GROUPS } from "@/utils/age"

/**
 * 3.1 복지자원 조회 (API-13)
 * - 3.1.1 검색 필터(지역·연령·성별·정원·자원명·담당자 이름), 처음 값은 모두 전체. '검색'을 눌러야 적용, '초기화'는 입력만 되돌림
 * - 3.1.2 모든 기관의 복지자원 목록, 진행 중 먼저 + 열 제목 정렬, 10개씩 페이지. 정렬·페이지는 누르는 즉시 적용
 * - 3.1.3 등록 이동
 * - 조건·정렬·페이지는 주소에 남는다 (src/screens/resource/resourceListQuery.ts)
 */
export function ResourceListScreen() {
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const search = params.toString()

  const applied = useMemo<ResourceListQuery>(() => parseQuery(new URLSearchParams(search)), [search])
  const request = useMemo(() => toSearchRequest(applied), [applied])

  const [form, setForm] = useState<ResourceListFilters>(pickFilters(applied))
  // 정원 범위 오류는 '검색'을 누른 뒤에 보여 준다
  const [showCapacityError, setShowCapacityError] = useState(false)

  // 주소가 바뀌면(검색·정렬·페이지·뒤로 가기) 입력칸도 적용된 조건으로 맞춘다
  useEffect(() => {
    setForm(pickFilters(applied))
    setShowCapacityError(false)
  }, [applied])

  // 정렬·페이지를 바꾸는 동안에는 이전 결과를 흐리게 남겨 둔다
  const list = useQuery({
    queryKey: resourceKeys.list(request),
    queryFn: () => resourceApi.searchResources(request),
    placeholderData: keepPreviousData,
  })
  const regions = useRegionOptions(form.sidoCode, form.sigunguCode)

  const rangeError = capacityError(form.capacityMin, form.capacityMax)

  // 주소가 바뀌면 주소 변경으로 조회된다. 주소가 그대로면(같은 조건 재검색) 직접 다시 조회한다
  const go = (query: ResourceListQuery) => {
    const to = `${PATHS.resources}${buildSearch(query)}`
    if (to === `${location.pathname}${location.search}`) void list.refetch()
    else navigate(to)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (rangeError) {
      setShowCapacityError(true)
      return
    }
    setShowCapacityError(false)
    go({ ...form, sort: applied.sort, direction: applied.direction, page: 1 })
  }

  const reset = () => {
    setForm(DEFAULT_FILTERS)
    setShowCapacityError(false)
  }

  const sortBy = (key: ResourceSortKey) => {
    const direction = applied.sort === key ? (applied.direction === "asc" ? "desc" : "asc") : "asc"
    go({ ...applied, sort: key, direction, page: 1 })
  }

  const update = (patch: Partial<ResourceListFilters>) => setForm({ ...form, ...patch })

  const results = () => {
    if (list.isPending) return <ResourceLoading text="복지자원 목록을 불러오는 중입니다." />
    if (list.isError) {
      const invalid = isApiError(list.error) && list.error.code === "VALIDATION_ERROR"
      return (
        <ResourceLoadFailed
          title="목록을 불러오지 못했습니다."
          message={invalid ? RESOURCE_MESSAGES.listValidation : errorMessage(list.error)}
          onRetry={() => void list.refetch()}
        />
      )
    }
    return (
      <ResourceTable
        result={list.data}
        refreshing={list.isPlaceholderData}
        sorting={{ sort: applied.sort, direction: applied.direction, onSort: sortBy }}
        onPage={(page) => go({ ...applied, page })}
        onOpen={(resourceId) => navigate(PATHS.resourceDetail(resourceId), { state: { listSearch: location.search } })}
      />
    )
  }

  return (
    <section className="screen resource-list">
      <div className="page-heading">
        <div>
          <h1 className="page-title">복지자원 조회</h1>
          <p className="page-desc">지역 복지자원을 검색합니다. 다른 기관의 자원도 함께 보입니다.</p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => navigate(PATHS.resourceNew, { state: { listSearch: location.search } })}
        >
          복지자원 등록
        </button>
      </div>

      <form className="search-panel" onSubmit={submit} noValidate>
        <div className="search-row">
          <span className="search-label">지역</span>
          <div className="search-controls">
            <select
              className="input select"
              aria-label="시도"
              value={form.sidoCode ?? ""}
              onChange={(event) => update({ sidoCode: event.target.value || null, sigunguCode: null, dongCode: null })}
            >
              <option value="">시도 전체</option>
              {regions.sidos.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}
                </option>
              ))}
            </select>
            <select
              className="input select"
              aria-label="시군구"
              value={form.sigunguCode ?? ""}
              disabled={!form.sidoCode}
              onChange={(event) => update({ sigunguCode: event.target.value || null, dongCode: null })}
            >
              <option value="">시군구 전체</option>
              {regions.sigungus.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}
                </option>
              ))}
            </select>
            <select
              className="input select"
              aria-label="읍면동"
              value={form.dongCode ?? ""}
              disabled={!form.sigunguCode}
              onChange={(event) => update({ dongCode: event.target.value || null })}
            >
              <option value="">읍면동 전체</option>
              {regions.dongs.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
          <span className="search-label">연령</span>
          <select
            className="input select search-short"
            aria-label="연령"
            value={form.ageGroup}
            onChange={(event) => update({ ageGroup: event.target.value as AgeGroup | "전체" })}
          >
            <option value="전체">전체</option>
            {AGE_GROUPS.map((group) => (
              <option key={group} value={group}>
                {group}
              </option>
            ))}
          </select>
          <span className="search-label">성별</span>
          <select
            className="input select search-short"
            aria-label="성별"
            value={form.gender}
            onChange={(event) => update({ gender: event.target.value as Gender | "전체" })}
          >
            <option value="전체">전체</option>
            <option value="남">남</option>
            <option value="여">여</option>
          </select>
        </div>
        {regions.error && <FieldError message={regions.error} />}

        <div className="search-row">
          <span className="search-label">정원</span>
          <div className="capacity-range">
            <div className="capacity-inputs">
              <input
                className="input"
                inputMode="numeric"
                aria-label="최소 정원"
                placeholder="최소"
                value={form.capacityMin}
                aria-invalid={showCapacityError && Boolean(rangeError)}
                onChange={(event) => update({ capacityMin: event.target.value })}
              />
              <span aria-hidden="true">~</span>
              <input
                className="input"
                inputMode="numeric"
                aria-label="최대 정원"
                placeholder="최대"
                value={form.capacityMax}
                aria-invalid={showCapacityError && Boolean(rangeError)}
                onChange={(event) => update({ capacityMax: event.target.value })}
              />
              <span className="capacity-unit">명</span>
            </div>
            <FieldError message={showCapacityError ? rangeError : null} />
          </div>
          <span className="search-label">담당자</span>
          <input
            className="input search-manager"
            aria-label="담당자 이름"
            placeholder="담당자 이름"
            value={form.managerName}
            onChange={(event) => update({ managerName: event.target.value })}
          />
        </div>

        <div className="search-row">
          <span className="search-label">자원명</span>
          <input
            className="input search-keyword"
            aria-label="자원명"
            placeholder="자원명 일부"
            maxLength={RESOURCE_TEXT_LIMITS.resourceName}
            value={form.resourceName}
            onChange={(event) => update({ resourceName: event.target.value })}
          />
          <div className="search-actions">
            <button type="button" className="btn btn-outline" onClick={reset}>
              초기화
            </button>
            <button type="submit" className="btn btn-primary">
              검색
            </button>
          </div>
        </div>
      </form>

      {results()}
    </section>
  )
}
