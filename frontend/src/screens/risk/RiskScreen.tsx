import "@/styles/risk.css"
import { useQuery } from "@tanstack/react-query"
import { useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router"
import { analysisApi, analysisKeys } from "@/api/analysisApi"
import { errorMessage, isApiError } from "@/api/errors"
import { regionApi, regionKeys } from "@/api/regionApi"
import type { MenuProfile } from "@/api/types"
import { EmptyState } from "@/components/common/EmptyState"
import { FieldError } from "@/components/common/FieldError"
import { RiskDongScreen } from "@/screens/risk/RiskDongScreen"
import { LoadError, Loading, MonthSelect, TableauViewPanel } from "@/screens/risk/RiskPanels"
import {
  compactPeriod,
  effectivePeriod,
  filtersOf,
  formatMonth,
  formatPeriod,
  INDEX_LABELS,
  isLoadedPeriod,
  parseRiskQuery,
  riskUrl,
  type DistrictState,
  type RiskFilters,
  type RiskIndex,
  type RiskQuery,
} from "@/screens/risk/riskQuery"
import { useSession } from "@/session/sessionStore"
import { isPublished, TABLEAU_MAP_VIEWS, TABLEAU_VIEWS, tableauParameters } from "@/tableau/tableauConfig"
import type { Conditions } from "@/tableau/tableauTypes"

/**
 * 2.1 고립 위험 탐색. 주소에 dong이 있으면 읍면동 화면(RiskDongScreen), 없으면 시군구 화면
 * - 조건은 주소에 남긴다 (R5-A, riskQuery.ts). 뒤로 가기·새로고침하면 주소에서 다시 그린다
 * - 시군구 지도에서 읍면동으로 가면 시군구 화면을 지우지 않고 숨겨 둔다. '이전으로'에서 Tableau 4개를 다시 띄우지 않으려고.
 *   숨긴 동안에는 떠날 때의 조건으로 멈춰 두고(읍면동 화면에서 기간을 바꿔도 뒤에서 다시 적용하지 않는다), 돌아오면 그때 맞춘다.
 *   새로고침·주소로 바로 들어온 읍면동 화면에서는 시군구 화면을 미리 띄우지 않는다
 */
export function RiskScreen() {
  const session = useSession()
  const location = useLocation()
  const [params] = useSearchParams()
  const search = params.toString()
  const profile = session.status === "authenticated" ? session.profile : null
  const query = useMemo(() => (profile ? parseRiskQuery(new URLSearchParams(search), profile) : null), [search, profile])
  // 이 화면이 떠 있는 동안 시군구 화면을 띄운 적이 있는지 (새로고침해도 navigation state는 남으므로 따로 기억한다)
  const districtShown = useRef(false)
  useEffect(() => {
    if (query && !query.dongCode) districtShown.current = true
  }, [query])

  if (!profile || !query) return null
  const leftFrom = location.state as DistrictState | null
  const districtQuery: RiskQuery | null = !query.dongCode
    ? query
    : leftFrom?.fromDistrict && districtShown.current
      ? { ...query, from: leftFrom.from, to: leftFrom.to, dongCode: null }
      : null

  // 두 화면의 자리를 고정해 두어야 시군구 화면이 숨겨졌다 돌아와도 다시 만들어지지 않는다
  return (
    <>
      {districtQuery && (
        <div className={query.dongCode ? "risk-kept" : undefined} inert={Boolean(query.dongCode)}>
          <RiskDistrictScreen query={districtQuery} profile={profile} />
        </div>
      )}
      {query.dongCode && (
        <RiskDongScreen key={query.dongCode} query={{ ...query, dongCode: query.dongCode }} profile={profile} />
      )}
    </>
  )
}

/**
 * 시군구 화면 (2.1.1 ~ 2.1.2)
 * - 지역(시도→시군구)·기간(시작 월~종료 월) 입력은 '적용'을 눌러야 반영된다. 월 목록은 API-10
 * - 지도·그래프 5개는 같은 Tableau 워크북의 임베드용 대시보드를 패널마다 하나씩 띄운다. 게시본이 없는 뷰는 '준비 중'
 * - 지표 전환(종합 위험·배경 취약성·행동 이상)은 우리 화면의 버튼으로 ① 지도의 대시보드를 바꾼다
 * - 지도에서 행정동 하나를 고르면 읍면동 화면으로 (주소에 dong)
 */
function RiskDistrictScreen({ query, profile }: { query: RiskQuery; profile: MenuProfile }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState<RiskFilters>(() => filtersOf(query))
  const [errors, setErrors] = useState<{ region?: string; period?: string }>({})
  const [refreshKey, setRefreshKey] = useState(0)
  const [selectionError, setSelectionError] = useState("")

  // 주소가 바뀌면(적용·뒤로 가기) 입력칸도 적용된 조건으로 맞춘다
  useEffect(() => {
    setForm(filtersOf(query))
    setErrors({})
    setSelectionError("")
  }, [query.sigunguCode, query.from, query.to])

  const appliedSido = query.sigunguCode.slice(0, 2)
  const sidos = useQuery({ queryKey: regionKeys.sidos, queryFn: regionApi.getSidos })
  const appliedSigungus = useQuery({
    queryKey: regionKeys.sigungus(appliedSido),
    queryFn: () => regionApi.getSigungus(appliedSido),
  })
  const formSigungus = useQuery({
    queryKey: regionKeys.sigungus(form.sidoCode ?? ""),
    queryFn: () => regionApi.getSigungus(form.sidoCode ?? ""),
    enabled: Boolean(form.sidoCode),
  })
  const months = useQuery({
    queryKey: analysisKeys.months(query.sigunguCode),
    queryFn: () => analysisApi.getLoadedMonths(query.sigunguCode),
  })
  // 입력칸의 시군구가 바뀌면 그 시군구의 월로 기간을 고른다
  const formMonthsQuery = useQuery({
    queryKey: analysisKeys.months(form.sigunguCode ?? ""),
    queryFn: () => analysisApi.getLoadedMonths(form.sigunguCode ?? ""),
    enabled: Boolean(form.sigunguCode),
  })
  const formMonths = formMonthsQuery.data?.months ?? []
  const formPeriod = effectivePeriod(form, formMonths)
  const sigunguName = appliedSigungus.data?.find((item) => item.sigunguCode === query.sigunguCode)?.sigunguName ?? ""

  const go = (next: RiskQuery, options?: { replace?: boolean; state?: DistrictState }) =>
    navigate(riskUrl(next, profile), options)

  const apply = () => {
    if (!form.sigunguCode) {
      setErrors({ region: "시군구를 선택하세요." })
      return
    }
    if (formPeriod && formPeriod.from > formPeriod.to) {
      setErrors({ period: "시작 월이 종료 월보다 늦습니다." })
      return
    }
    if (formPeriod && !isLoadedPeriod(formPeriod, formMonths)) {
      setErrors({ period: "분석 결과가 있는 월을 고르세요." })
      return
    }
    setErrors({})
    // 적재된 전체 기간의 끝과 같은 값은 비워 둔다 (주소에서 빠짐)
    const next: RiskQuery = {
      sigunguCode: form.sigunguCode,
      ...(formPeriod ? compactPeriod(formPeriod, formMonths) : { from: null, to: null }),
      index: query.index,
      dongCode: null,
    }
    const nextUrl = riskUrl(next, profile)
    if (nextUrl === `${location.pathname}${location.search}`) {
      // 같은 조건으로 다시 적용: 월 목록을 다시 받고 Tableau에 넘긴 값을 다시 확인한다
      setRefreshKey((value) => value + 1)
      void months.refetch()
    } else {
      navigate(nextUrl)
    }
  }

  const selectDong = (dongCode: string) => {
    // 행정동 코드 앞 5자리가 시군구 코드다. 다른 시군구의 코드가 오면 게시본의 데이터가 어긋난 것이다
    if (dongCode.slice(0, 5) !== query.sigunguCode) {
      setSelectionError(`게시본에서 받은 행정동 코드 ${dongCode}가 ${sigunguName || "지금 시군구"}에 속하지 않습니다.`)
      return
    }
    setSelectionError("")
    go({ ...query, dongCode }, { state: { fromDistrict: true, from: query.from, to: query.to } })
  }

  const body = () => {
    if (months.isPending) return <Loading />
    if (months.isError) {
      if (isApiError(months.error) && (months.error.code === "NOT_FOUND" || months.error.code === "VALIDATION_ERROR")) {
        return <EmptyState title="선택한 시군구를 찾을 수 없습니다." description="지역을 다시 골라 적용하세요." />
      }
      return <LoadError message={errorMessage(months.error)} onRetry={() => void months.refetch()} />
    }
    const loaded = months.data.months
    const period = effectivePeriod(query, loaded)
    if (!period) {
      return (
        <EmptyState
          title="적재된 분석 데이터가 없습니다."
          description={`${sigunguName || "이 시군구"}의 분석 결과가 아직 적재되지 않았습니다.`}
        />
      )
    }
    if (!isLoadedPeriod(period, loaded)) {
      return (
        <EmptyState title="선택한 기간의 분석 데이터가 없습니다." description="분석 결과가 있는 월로 기간을 다시 골라 적용하세요." />
      )
    }
    // 적재된 결과는 있지만 Tableau 게시본이 그 지역·기간을 담고 있지 않으면 잘못된 조건으로 띄우지 않는다
    if (!isPublished(query.sigunguCode, period)) {
      return (
        <EmptyState
          title="이 지역·기간의 지도와 그래프를 준비 중입니다."
          description="분석 결과는 적재되어 있지만 Tableau 게시본이 아직 이 지역·기간을 담고 있지 않습니다."
        />
      )
    }
    return (
      <RiskDashboard
        query={query}
        sigunguName={sigunguName}
        period={period}
        refreshKey={refreshKey}
        onIndex={(index) => go({ ...query, index }, { replace: true })}
        onSelectDong={selectDong}
      />
    )
  }

  return (
    <section className="screen risk-screen">
      <div className="risk-heading">
        <div>
          <h1 className="page-title">고립 위험 탐색</h1>
          <p className="page-desc">시군구 행정동의 고립 위험을 지도와 그래프로 살펴봅니다.</p>
        </div>
        <div className="risk-filters">
          <div className="risk-filter-group">
            <span className="risk-filter-label">지역</span>
            <div className="risk-filter-controls">
              <select
                className="input select"
                aria-label="시도"
                value={form.sidoCode ?? ""}
                aria-invalid={Boolean(errors.region) && !form.sidoCode}
                onChange={(event) => setForm({ sidoCode: event.target.value || null, sigunguCode: null, from: null, to: null })}
              >
                <option value="">시도 선택</option>
                {(sidos.data ?? []).map((item) => (
                  <option key={item.sidoCode} value={item.sidoCode}>
                    {item.sidoName}
                  </option>
                ))}
              </select>
              <select
                className="input select"
                aria-label="시군구"
                value={form.sigunguCode ?? ""}
                disabled={!form.sidoCode}
                aria-invalid={Boolean(errors.region)}
                onChange={(event) => setForm({ ...form, sigunguCode: event.target.value || null, from: null, to: null })}
              >
                <option value="">시군구 선택</option>
                {(formSigungus.data ?? []).map((item) => (
                  <option key={item.sigunguCode} value={item.sigunguCode}>
                    {item.sigunguName}
                  </option>
                ))}
              </select>
            </div>
            <FieldError message={errors.region ?? (sidos.isError || formSigungus.isError ? "지역 목록을 불러오지 못했습니다." : undefined)} />
          </div>
          <div className="risk-filter-group">
            <span className="risk-filter-label">기간</span>
            <div className="risk-filter-controls">
              {(["from", "to"] as const).map((key) => (
                <MonthSelect
                  key={key}
                  label={key === "from" ? "시작 월" : "종료 월"}
                  value={formPeriod?.[key] ?? ""}
                  months={formMonths}
                  invalid={Boolean(errors.period)}
                  separator={key === "to"}
                  onChange={(value) => setForm({ ...form, [key]: value })}
                />
              ))}
            </div>
            <FieldError message={errors.period} />
          </div>
          <button type="button" className="btn btn-primary risk-apply" onClick={apply}>
            적용
          </button>
        </div>
      </div>

      {selectionError && (
        <p className="tableau-error" role="alert">
          {selectionError}
        </p>
      )}
      {body()}
    </section>
  )
}

/** Tableau 패널 5개 */
function RiskDashboard({
  query,
  sigunguName,
  period,
  refreshKey,
  onIndex,
  onSelectDong,
}: {
  query: RiskQuery
  sigunguName: string
  period: { from: string; to: string }
  refreshKey: number
  onIndex: (index: RiskIndex) => void
  onSelectDong: (dongCode: string) => void
}) {
  // 모든 대시보드가 같은 매개변수를 쓴다 (기준 월 = 종료 월 = p_end). 지역·기간 필터는 없다
  const conditions: Conditions = { filters: {}, parameters: tableauParameters(query.sigunguCode, period) }
  const baseMonth = formatMonth(period.to)
  const periodText = formatPeriod(period)

  return (
    <div className="risk-dashboard">
      <div className="risk-column">
        <TableauViewPanel
          view={TABLEAU_MAP_VIEWS[query.index]}
          title={`${sigunguName} 행정동별 ${INDEX_LABELS[query.index]} · ${baseMonth}`}
          label="행정동별 고립 위험 지도"
          conditions={conditions}
          refreshKey={refreshKey}
          onSelectDong={onSelectDong}
          hint="행정동을 누르면 읍면동 화면으로 이동합니다."
          actions={
            <div className="index-toggle" role="group" aria-label="지표">
              {(Object.keys(INDEX_LABELS) as RiskIndex[]).map((index) => (
                <button
                  key={index}
                  type="button"
                  className={query.index === index ? "is-active" : undefined}
                  aria-pressed={query.index === index}
                  onClick={() => query.index !== index && onIndex(index)}
                >
                  {INDEX_LABELS[index]}
                </button>
              ))}
            </div>
          }
        />
        <TableauViewPanel
          view={TABLEAU_VIEWS.distribution}
          title={`${sigunguName} 월별 종합 위험도 단계 분포 · ${periodText}`}
          label="월별 종합 위험도 단계 분포"
          conditions={conditions}
          refreshKey={refreshKey}
        />
      </div>
      <div className="risk-column">
        <TableauViewPanel
          view={TABLEAU_VIEWS.background}
          title={`${sigunguName} 행정동별 배경 취약성 분포 · ${baseMonth}`}
          label="행정동별 배경 취약성 분포"
          conditions={conditions}
          refreshKey={refreshKey}
        />
        <TableauViewPanel
          view={TABLEAU_VIEWS.monthly}
          title={`${sigunguName} 월별 행동 이상 지수 변화 · ${periodText}`}
          label="월별 행동 이상 지수 변화"
          conditions={conditions}
          refreshKey={refreshKey}
        />
        {/* ⑤의 마크에는 행정동 코드가 없어 눌러도 읍면동 화면으로 가지 않는다 */}
        <TableauViewPanel
          view={TABLEAU_VIEWS.dongChange}
          title={`${sigunguName} 행정동별 전월 대비 행동 이상 지수 변화 · ${baseMonth}`}
          label="행정동별 전월 대비 행동 이상 지수 변화"
          conditions={conditions}
          refreshKey={refreshKey}
        />
      </div>
    </div>
  )
}
