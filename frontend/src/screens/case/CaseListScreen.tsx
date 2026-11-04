import "@/styles/list.css"
import "@/styles/case.css"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { useEffect, useMemo, useState, type FormEvent } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router"
import { caseApi, caseKeys, type AgeGroup, type CaseSortKey, type Gender } from "@/api/caseApi"
import { errorMessage, isApiError } from "@/api/errors"
import { FieldError } from "@/components/common/FieldError"
import { PATHS } from "@/routes/paths"
import { CASE_MESSAGES } from "@/screens/case/caseErrors"
import {
  buildSearch,
  defaultFilters,
  firstDirectionOf,
  parseQuery,
  pickFilters,
  rangeError,
  toSearchRequest,
  type CaseListFilters,
  type CaseListQuery,
} from "@/screens/case/caseListQuery"
import { CaseLoadFailed, CaseLoading } from "@/screens/case/CaseStatusViews"
import { CaseTable } from "@/screens/case/CaseTable"
import { useRegionOptions } from "@/screens/case/RegionSelects"
import { useSession } from "@/session/sessionStore"
import { AGE_GROUPS } from "@/utils/age"

/**
 * 4.1 사례자 목록 조회 (API-19)
 * - 4.1.1 검색 필터(지역·연령대·성별·등록일·기록일)·키워드·정렬 / 4.1.2 본인 담당 사례자 목록 / 4.1.3 등록 이동
 * - 조건은 '검색'을 눌러야 적용(C2-A). 정렬·페이지는 누르는 즉시 적용(C1-A, C3-A)
 * - 조건·정렬·페이지는 주소에 남는다 (src/screens/case/caseListQuery.ts)
 */
export function CaseListScreen() {
  const session = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const search = params.toString()
  const profile = session.status === "authenticated" ? session.profile : null

  const applied = useMemo<CaseListQuery | null>(
    () => (profile ? parseQuery(new URLSearchParams(search), profile) : null),
    [search, profile],
  )
  const request = useMemo(() => (applied ? toSearchRequest(applied) : null), [applied])

  const [form, setForm] = useState<CaseListFilters | null>(applied ? pickFilters(applied) : null)
  // 날짜 범위 오류는 '검색'을 누른 뒤에 보여 준다
  const [showRangeErrors, setShowRangeErrors] = useState(false)

  // 주소가 바뀌면(검색·정렬·페이지·뒤로 가기) 입력칸도 적용된 조건으로 맞춘다
  useEffect(() => {
    if (applied) setForm(pickFilters(applied))
  }, [applied])

  // 정렬·페이지를 바꾸는 동안에는 이전 결과를 흐리게 남겨 둔다
  const list = useQuery({
    queryKey: caseKeys.list(request ?? {}),
    queryFn: () => caseApi.searchCases(request ?? {}),
    enabled: request !== null,
    placeholderData: keepPreviousData,
  })
  const regions = useRegionOptions(form?.sidoCode ?? null, form?.sigunguCode ?? null)

  if (!profile || !applied || !form) return null

  const registeredError = rangeError(form.registeredFrom, form.registeredTo)
  const recordedError = rangeError(form.recordedFrom, form.recordedTo)

  // 주소가 바뀌면 주소 변경으로 조회된다. 주소가 그대로면(같은 조건 재검색) 직접 다시 조회한다
  const go = (query: CaseListQuery) => {
    const to = `${PATHS.cases}${buildSearch(query, profile)}`
    if (to === `${location.pathname}${location.search}`) void list.refetch()
    else navigate(to)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (registeredError || recordedError) {
      setShowRangeErrors(true)
      return
    }
    setShowRangeErrors(false)
    go({ ...form, sort: applied.sort, direction: applied.direction, page: 1 })
  }

  const reset = () => {
    setForm(defaultFilters(profile))
    setShowRangeErrors(false)
  }

  const sortBy = (key: CaseSortKey) => {
    const direction =
      applied.sort === key ? (applied.direction === "asc" ? "desc" : "asc") : firstDirectionOf(key)
    go({ ...applied, sort: key, direction, page: 1 })
  }

  const update = (patch: Partial<CaseListFilters>) => setForm({ ...form, ...patch })

  const results = () => {
    if (list.isPending) return <CaseLoading text="사례자 목록을 불러오는 중입니다." />
    if (list.isError) {
      const invalid = isApiError(list.error) && list.error.code === "VALIDATION_ERROR"
      return (
        <CaseLoadFailed
          title="목록을 불러오지 못했습니다."
          message={invalid ? CASE_MESSAGES.listValidation : errorMessage(list.error)}
          onRetry={() => void list.refetch()}
        />
      )
    }
    return (
      <CaseTable
        result={list.data}
        refreshing={list.isPlaceholderData}
        sort={applied.sort}
        direction={applied.direction}
        onSort={sortBy}
        onPage={(page) => go({ ...applied, page })}
        onOpen={(caseId) => navigate(PATHS.caseDetail(caseId), { state: { listSearch: location.search } })}
      />
    )
  }

  return (
    <section className="screen case-list">
      <div className="page-heading">
        <div>
          <h1 className="page-title">사례자 관리</h1>
          <p className="page-desc">내가 담당하는 사례자를 검색합니다.</p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => navigate(PATHS.caseNew, { state: { listSearch: location.search } })}
        >
          사례자 등록
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
              onChange={(event) =>
                update({ sidoCode: event.target.value || null, sigunguCode: null, dongCode: null })
              }
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
          <span className="search-label">연령대</span>
          <select
            className="input select search-short"
            aria-label="연령대"
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
          <span className="search-label">최초 등록일</span>
          <DateRange
            fromLabel="최초 등록일 시작"
            toLabel="최초 등록일 끝"
            from={form.registeredFrom}
            to={form.registeredTo}
            error={showRangeErrors ? registeredError : null}
            onChange={(registeredFrom, registeredTo) => update({ registeredFrom, registeredTo })}
          />
          <span className="search-label">최근 기록일</span>
          <DateRange
            fromLabel="최근 기록일 시작"
            toLabel="최근 기록일 끝"
            from={form.recordedFrom}
            to={form.recordedTo}
            error={showRangeErrors ? recordedError : null}
            onChange={(recordedFrom, recordedTo) => update({ recordedFrom, recordedTo })}
          />
        </div>

        <div className="search-row">
          <span className="search-label">키워드</span>
          <input
            className="input search-keyword"
            aria-label="키워드"
            placeholder="이름 또는 관리번호"
            value={form.keyword}
            onChange={(event) => update({ keyword: event.target.value })}
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

function DateRange({
  fromLabel,
  toLabel,
  from,
  to,
  error,
  onChange,
}: {
  fromLabel: string
  toLabel: string
  from: string
  to: string
  error: string | null
  onChange: (from: string, to: string) => void
}) {
  return (
    <div className="date-range">
      <div className="date-range-inputs">
        <input
          className="input"
          type="date"
          aria-label={fromLabel}
          value={from}
          aria-invalid={Boolean(error)}
          onChange={(event) => onChange(event.target.value, to)}
        />
        <span aria-hidden="true">~</span>
        <input
          className="input"
          type="date"
          aria-label={toLabel}
          value={to}
          aria-invalid={Boolean(error)}
          onChange={(event) => onChange(from, event.target.value)}
        />
      </div>
      <FieldError message={error} />
    </div>
  )
}
