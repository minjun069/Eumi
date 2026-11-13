import { useQuery } from "@tanstack/react-query"
import { useEffect, useState, type ReactNode } from "react"
import { type Location, useNavigate } from "react-router"
import { analysisApi, analysisKeys, type DongInsight, type InsightReportData } from "@/api/analysisApi"
import { errorMessage, isApiError } from "@/api/errors"
import type { MenuProfile } from "@/api/types"
import { EmptyState } from "@/components/common/EmptyState"
import { FieldError } from "@/components/common/FieldError"
import { PATHS } from "@/routes/paths"
import { InsightReportView } from "@/screens/risk/InsightReportView"
import { LoadError, Loading, MONTHS_UNAVAILABLE, MonthSelect, TableauViewPanel } from "@/screens/risk/RiskPanels"
import {
  compactPeriod,
  DONG_PATTERN,
  effectivePeriod,
  formatMonth,
  isLoadedPeriod,
  riskUrl,
  type DistrictState,
  type RiskQuery,
} from "@/screens/risk/riskQuery"
import { stageStyle } from "@/screens/risk/riskStyle"
import { useScreenContext } from "@/stores/screenContextStore"
import {
  gridSelectionCount,
  isPublished,
  TABLEAU_GRID_SELECTION_PARAMETER,
  TABLEAU_VIEWS,
  tableauDetailParameters,
  tableauGridCrop,
} from "@/tableau/tableauConfig"
import { formatDateTime } from "@/utils/datetime"

const NOT_FOUND_DONG = {
  title: "행정동을 찾을 수 없습니다.",
  description: "'이전으로'를 눌러 시군구 지도에서 행정동을 다시 고르세요.",
}

/** 결과가 없다는 뜻의 오류 (없는 행정동·그 달 결과 없음) */
const isNotFound = (error: unknown) =>
  isApiError(error) && (error.code === "NOT_FOUND" || error.code === "VALIDATION_ERROR")

/**
 * 2.1 고립 위험 탐색 — 읍면동 화면 (?dong=)
 * - 기간 필터만 있다 (지역은 시군구 화면에서). 격자 지도·인사이트·보고서는 기간의 마지막 월(기준 월) 기준
 * - 위험도 배지는 행동 이상 단계 (배경 취약성 단계는 함께 표시). 종합 위험(riskGrade)은 그리지 않는다
 * - ⑥ 격자 지도는 Tableau, 요약·인사이트(API-11)와 보고서(API-12)는 우리 서버 API
 * - 결과 없음(404)과 인사이트·보고서 준비 중(null)을 나눠 보인다
 * - 다른 읍면동은 '이전으로'로 시군구 지도로 돌아가 고른다
 * - 숨겨 둘 수 있다 (RiskScreen): 숨긴 동안(active=false) AI 화면 문맥을 붙이지 않는다.
 *   preload(시연 동)면 보이기 전에 보고서 그래프까지 모두 띄워 둔다
 */
export function RiskDongScreen({
  query,
  profile,
  location,
  active,
  preload,
}: {
  query: RiskQuery & { dongCode: string }
  profile: MenuProfile
  /** 지금 주소 ('이전으로' · '적용'에서 쓴다. 숨긴 화면은 누를 수 없다) */
  location: Location
  active: boolean
  preload: boolean
}) {
  const navigate = useNavigate()
  const validDong = DONG_PATTERN.test(query.dongCode)
  // 행정동 코드 앞 5자리가 시군구 코드다
  const sigunguCode = validDong ? query.dongCode.slice(0, 5) : query.sigunguCode
  const [form, setForm] = useState<{ from: string | null; to: string | null }>({ from: query.from, to: query.to })
  const [error, setError] = useState<string>()
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    setForm({ from: query.from, to: query.to })
    setError(undefined)
  }, [query.from, query.to])

  const months = useQuery({
    queryKey: analysisKeys.months(sigunguCode),
    queryFn: () => analysisApi.getLoadedMonths(sigunguCode),
    enabled: validDong,
  })
  // 코드 형식이 틀리면 캐시에 그 시군구의 월이 있어도 쓰지 않는다 (인사이트·보고서를 부르지 않게)
  const loaded = validDong ? (months.data?.months ?? []) : []
  const period = effectivePeriod(query, loaded)
  const baseMonth = period && isLoadedPeriod(period, loaded) ? period.to : null
  const insight = useQuery({
    queryKey: analysisKeys.insight(query.dongCode, baseMonth ?? ""),
    queryFn: () => analysisApi.getDongInsight(query.dongCode, baseMonth ?? ""),
    enabled: baseMonth !== null,
  })
  const report = useQuery({
    queryKey: analysisKeys.report(query.dongCode, baseMonth ?? ""),
    queryFn: () => analysisApi.getInsightReport(query.dongCode, baseMonth ?? ""),
    enabled: baseMonth !== null,
  })
  // AI 패널 질문에 붙이는 화면 문맥: 이 동 · 기준 월 (ai-agent-panel.md 3-1). 숨겨져 있거나 기준 월이 없거나 코드 형식이 틀리면 붙이지 않는다
  const dongName = insight.data?.dongName
  const contextMonth = active && validDong ? baseMonth : null
  useScreenContext(
    contextMonth ? { dongCode: query.dongCode, month: contextMonth } : null,
    contextMonth ? `${dongName ? `${dongName} · ` : ""}${formatMonth(contextMonth)} 기준` : "",
  )

  const onBack = () => {
    // 시군구 지도에서 바로 왔고 기간을 바꾸지 않았으면 뒤로 가기, 아니면(메뉴로 돌아옴 · 기간 바꿈) 지금 기간으로 시군구 화면.
    // 숨겨 둔 시군구 화면이 같은 조건이면 다시 띄우지 않고 그대로 보인다
    const state = location.state as DistrictState | null
    if (state?.fromDistrict && !state.viaMenu && state.from === query.from && state.to === query.to) navigate(-1)
    else navigate(riskUrl({ ...query, sigunguCode, dongCode: null }, profile), { replace: true })
  }

  const formPeriod = effectivePeriod(form, loaded)
  const apply = () => {
    if (!formPeriod) return
    if (formPeriod.from > formPeriod.to) {
      setError("시작 월이 종료 월보다 늦습니다.")
      return
    }
    if (!isLoadedPeriod(formPeriod, loaded)) {
      setError("분석 결과가 있는 월을 고르세요.")
      return
    }
    setError(undefined)
    const nextUrl = riskUrl({ ...query, ...compactPeriod(formPeriod, loaded) }, profile)
    if (nextUrl === `${location.pathname}${location.search}`) {
      setRefreshKey((value) => value + 1)
      void insight.refetch()
      void report.refetch()
    } else {
      navigate(nextUrl, { replace: true, state: location.state })
    }
  }

  const body = (): ReactNode => {
    if (!validDong) return <EmptyState {...NOT_FOUND_DONG} />
    if (months.isPending) return <Loading />
    if (months.isError) {
      if (isNotFound(months.error)) {
        return (
          <EmptyState
            title={MONTHS_UNAVAILABLE}
            description="'이전으로'를 눌러 시군구 화면에서 다시 확인하거나 잠시 후 다시 시도해 주세요."
          />
        )
      }
      return <LoadError message={errorMessage(months.error)} onRetry={() => void months.refetch()} />
    }
    if (loaded.length === 0) return <EmptyState title="적재된 분석 데이터가 없습니다." />
    if (!baseMonth) {
      return (
        <EmptyState title="선택한 기간의 분석 데이터가 없습니다." description="분석 결과가 있는 월로 기간을 다시 골라 적용하세요." />
      )
    }
    if (insight.isPending) return <Loading />
    if (insight.isError) {
      if (isNotFound(insight.error)) {
        return (
          <EmptyState
            title="이 달의 분석 결과가 없습니다."
            description={`${formatMonth(baseMonth)}에는 이 행정동의 분석 결과가 없습니다. 기간을 바꾸거나 '이전으로'를 눌러 다른 행정동을 고르세요.`}
          />
        )
      }
      return <LoadError message={errorMessage(insight.error)} onRetry={() => void insight.refetch()} />
    }
    return (
      <DongBody
        dong={insight.data}
        baseMonth={baseMonth}
        period={period ?? { from: baseMonth, to: baseMonth }}
        report={report}
        refreshKey={refreshKey}
        preload={preload}
      />
    )
  }

  const dong = insight.data
  return (
    <section className="screen risk-screen risk-dong">
      <div className="risk-heading">
        <div>
          <button type="button" className="back-link" onClick={onBack}>
            &lt; 이전으로
          </button>
          <h1 className="page-title">
            {dong ? `${dong.sigunguName} ${dong.dongName}의 고립 위험 분석` : "읍면동 고립 위험 분석"}
          </h1>
        </div>
        {loaded.length > 0 && (
          <div className="risk-filters">
            <div className="risk-filter-group">
              <span className="risk-filter-label">기간</span>
              <div className="risk-filter-controls">
                {(["from", "to"] as const).map((key) => (
                  <MonthSelect
                    key={key}
                    label={key === "from" ? "시작 월" : "종료 월"}
                    value={formPeriod?.[key] ?? ""}
                    months={loaded}
                    invalid={Boolean(error)}
                    separator={key === "to"}
                    onChange={(value) => setForm({ ...form, [key]: value })}
                  />
                ))}
              </div>
              <FieldError message={error} />
            </div>
            <button type="button" className="btn btn-primary risk-apply" onClick={apply}>
              적용
            </button>
          </div>
        )}
      </div>
      {body()}
    </section>
  )
}

function DongBody({
  dong,
  baseMonth,
  period,
  report,
  refreshKey,
  preload,
}: {
  dong: DongInsight
  baseMonth: string
  period: { from: string; to: string }
  report: { isPending: boolean; isError: boolean; error: unknown; data?: InsightReportData; refetch: () => unknown }
  refreshKey: number
  /** 보고서 그래프를 보이기 전에 모두 띄운다 */
  preload: boolean
}) {
  const navigate = useNavigate()
  const stage = stageStyle(dong.behavior.stage)
  const month = formatMonth(baseMonth)
  const published = isPublished(dong.sigunguCode, period)
  // ⑥ 비교표에 보일 줄 수: Tableau 안에서 고른 격자 수 (없으면 선택 카드 제목 줄까지만 보인다, tableauGridCrop)
  const [selectedGrids, setSelectedGrids] = useState(0)
  const onGridParameter = (name: string, value: string) => {
    if (name === TABLEAU_GRID_SELECTION_PARAMETER) setSelectedGrids(gridSelectionCount(value))
  }

  return (
    <div className="risk-dong-body">
      <div className="risk-dong-left">
        <div className="dong-summary">
          <span className="dong-summary-label">고립 위험</span>
          <span className="stage-badge" style={{ background: stage.background, color: stage.color }}>
            {dong.behavior.stage}단계{stage.label ? ` ${stage.label}` : ""}
          </span>
          <span className="dong-summary-note">행동 이상 기준 · {month}</span>
          <div className="dong-summary-chips">
            <span className="index-chip">
              배경 취약성 <b>{dong.background.stage}단계</b> ({dong.background.score.toFixed(2)}점)
            </span>
            <span className="index-chip">
              행동 이상 <b>{dong.behavior.stage}단계</b> ({dong.behavior.score.toFixed(2)}점)
            </span>
          </div>
        </div>

        {published ? (
          // 행정동·기준 월은 위쪽 필터 값을 매개변수로 처음부터 넘기고 FirstInteractive 뒤에 다시 읽어 확인한다 (TableauWorksheet).
          // 대시보드에서 위 선택 칸만 잘라 내고 지도 · 범례 · 격자 선택 카드 · 비교표를 보인다.
          // 처음에는 선택 카드 제목 줄까지만 보이고, 격자를 고르면 평균 두 칸과 비교표가 고른 만큼 늘어난다 (해제하면 다시 줄어든다)
          <TableauViewPanel
            view={{ ...TABLEAU_VIEWS.grid, crop: tableauGridCrop(selectedGrids) }}
            title={`${dong.dongName} 격자별 행동 이상 위험도 · ${month}`}
            label="격자별 행동 이상 위험도"
            conditions={{ filters: {}, parameters: tableauDetailParameters(dong.dongCode, dong.sigunguCode, period) }}
            refreshKey={refreshKey}
            onParameterValue={onGridParameter}
          />
        ) : (
          <section className="risk-panel">
            <header className="risk-panel-head">
              <h2>{`${dong.dongName} 격자별 행동 이상 위험도 · ${month}`}</h2>
            </header>
            <p className="tableau-pending">Tableau 게시본이 아직 이 지역·기간을 담고 있지 않습니다.</p>
          </section>
        )}

        <section className="risk-panel quick-insight">
          <header className="risk-panel-head">
            <h2>
              <span className="sparkle" aria-hidden="true">
                ✦
              </span>{" "}
              퀵 인사이트
            </h2>
          </header>
          {/* 2.4.0: summary는 퀵 인사이트 한 개를 담은 배열이다. 일반 글로 줄바꿈을 살려 보인다 (insight-report.md 8절) */}
          {dong.insight && dong.insight.summary[0]?.trim() ? (
            <>
              <p className="quick-insight-text">{dong.insight.summary[0].trim()}</p>
              <p className="quick-insight-meta">AI 생성 · {formatDateTime(dong.insight.generatedAt)}</p>
            </>
          ) : (
            <p className="risk-empty-text">이 달의 인사이트를 준비 중입니다.</p>
          )}
          <p className="quick-links-title">분석 결과를 활용해볼까요?</p>
          <div className="quick-links">
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => navigate(`${PATHS.resources}?dongCode=${dong.dongCode}`)}
            >
              복지자원 찾기 →
            </button>
            <button type="button" className="btn btn-outline" onClick={() => navigate(`${PATHS.cases}?dongCode=${dong.dongCode}`)}>
              사례자 탐색 →
            </button>
          </div>
        </section>
      </div>

      <aside className="risk-panel risk-report-panel" aria-label="인사이트 보고서">
        <header className="risk-panel-head">
          <h2>
            <span className="sparkle" aria-hidden="true">
              ✦
            </span>{" "}
            인사이트 보고서 · {month}
          </h2>
        </header>
        {report.isPending ? (
          <Loading text="보고서를 불러오는 중입니다." />
        ) : report.isError ? (
          isNotFound(report.error) ? (
            <p className="risk-empty-text">이 달의 분석 결과가 없어 보고서가 없습니다.</p>
          ) : (
            <LoadError message={errorMessage(report.error)} onRetry={() => void report.refetch()} />
          )
        ) : report.data?.report ? (
          <InsightReportView
            report={report.data.report}
            dongCode={dong.dongCode}
            sigunguCode={dong.sigunguCode}
            period={period}
            eager={preload}
          />
        ) : (
          <p className="risk-empty-text">이 달의 인사이트 보고서를 준비 중입니다.</p>
        )}
      </aside>
    </div>
  )
}
