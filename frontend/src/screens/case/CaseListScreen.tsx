import { useEffect, useMemo, useState, type FormEvent } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router"
import { EmptyState } from "@/components/common/EmptyState"
import { FieldError } from "@/components/common/FieldError"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { caseApi, type CaseSearchResponse, type CaseSortKey } from "@/mock/api/caseApi"
import { regionApi } from "@/mock/api/regionApi"
import { PATHS } from "@/routes/paths"
import { CaseTable } from "@/screens/case/CaseTable"
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
import { useSession } from "@/session/sessionStore"
import type { AgeGroup, Gender } from "@/types/domain"
import { AGE_GROUPS } from "@/utils/age"

type RegionOption = { code: string; name: string }

/**
 * 4.1 사례자 목록 조회
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

  const [form, setForm] = useState<CaseListFilters | null>(applied ? pickFilters(applied) : null)
  // 날짜 범위 오류는 '검색'을 누른 뒤에 보여 준다
  const [showRangeErrors, setShowRangeErrors] = useState(false)
  const [nonce, setNonce] = useState(0)
  const [result, setResult] = useState<CaseSearchResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [sidos, setSidos] = useState<RegionOption[]>([])
  const [sigungus, setSigungus] = useState<RegionOption[]>([])
  const [dongs, setDongs] = useState<RegionOption[]>([])

  // 주소가 바뀌면(검색·정렬·페이지·뒤로 가기) 입력칸도 적용된 조건으로 맞춘다
  useEffect(() => {
    if (applied) setForm(pickFilters(applied))
  }, [applied])

  // 적용된 조건으로 목록 조회 (주소가 같아도 '검색'을 누르면 다시 조회)
  useEffect(() => {
    if (!applied) return
    const response = caseApi.searchCases(toSearchRequest(applied))
    if (response.ok) {
      setResult(response.data)
      setLoadError(null)
    } else {
      setLoadError(response.message)
    }
  }, [applied, nonce])

  // 지역 목록: 시도는 한 번, 시군구·행정동은 위 단계를 고를 때마다
  useEffect(() => {
    const response = regionApi.getSidos("4.1.1")
    if (response.ok) {
      setSidos(response.data.map((item) => ({ code: item.sidoCode, name: item.sidoName })))
    }
  }, [])
  const sidoCode = form?.sidoCode ?? null
  const sigunguCode = form?.sigunguCode ?? null
  useEffect(() => {
    if (!sidoCode) {
      setSigungus([])
      return
    }
    const response = regionApi.getSigungus("4.1.1", { sidoCode })
    if (response.ok) {
      setSigungus(response.data.map((item) => ({ code: item.sigunguCode, name: item.sigunguName })))
    }
  }, [sidoCode])
  useEffect(() => {
    if (!sigunguCode) {
      setDongs([])
      return
    }
    const response = regionApi.getDongs("4.1.1", { sigunguCode })
    if (response.ok) {
      setDongs(response.data.map((item) => ({ code: item.dongCode, name: item.dongName })))
    }
  }, [sigunguCode])

  useDevScenario(
    {
      screen: "사례자 목록",
      hint: "채우기 버튼은 입력칸만 바꿉니다. '검색'을 눌러 결과를 확인하세요. 상황 전환에서 박성민(공동 담당), 한도윤(담당 사례자 없음)으로도 바꿔 보세요.",
      actions: [
        {
          label: "고립 위험 탐색에서 옴 (개포1동)",
          run: () => navigate(`${PATHS.cases}?dongCode=1168066000`),
        },
        { label: "지역 '전체'로 검색", run: () => navigate(`${PATHS.cases}?sido=all`) },
        {
          label: "결과 없는 키워드 채우기",
          run: () => setForm((prev) => (prev ? { ...prev, keyword: "없는사례자" } : prev)),
        },
        {
          label: "날짜 범위 오류 채우기",
          run: () =>
            setForm((prev) =>
              prev ? { ...prev, registeredFrom: "2026-10-01", registeredTo: "2026-09-01" } : prev,
            ),
        },
      ],
    },
    [],
  )

  if (!profile || !applied || !form) return null

  const registeredError = rangeError(form.registeredFrom, form.registeredTo)
  const recordedError = rangeError(form.recordedFrom, form.recordedTo)

  // 주소가 바뀌면 주소 변경으로 조회된다. 주소가 그대로면(같은 조건 재검색) 직접 다시 조회한다.
  // 주소 변경과 다시 조회를 함께 하면, 주소 반영이 한 박자 늦어 이전 조건으로 한 번 더 조회된다.
  const go = (query: CaseListQuery) => {
    const to = `${PATHS.cases}${buildSearch(query, profile)}`
    if (to === `${location.pathname}${location.search}`) setNonce((value) => value + 1)
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
              {sidos.map((item) => (
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
              {sigungus.map((item) => (
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
              {dongs.map((item) => (
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

      {loadError ? (
        <EmptyState title="목록을 불러오지 못했습니다." description={loadError} />
      ) : result ? (
        <CaseTable
          result={result}
          sort={applied.sort}
          direction={applied.direction}
          onSort={sortBy}
          onPage={(page) => go({ ...applied, page })}
          onOpen={(caseId) => navigate(PATHS.caseDetail(caseId), { state: { listSearch: location.search } })}
        />
      ) : null}
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
