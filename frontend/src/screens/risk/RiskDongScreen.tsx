import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { Emphasized } from "@/components/common/Emphasized"
import { EmptyState } from "@/components/common/EmptyState"
import { FieldError } from "@/components/common/FieldError"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { analysisApi, type DongInsightResponse, type InsightReportResponse } from "@/mock/api/analysisApi"
import { noteTableau } from "@/mock/tableau/tableauBridge"
import { TABLEAU_VIEWS, tableauViews } from "@/mock/tableau/tableauViews"
import { PATHS } from "@/routes/paths"
import { InsightReportView } from "@/screens/risk/InsightReportView"
import { TableauMessage, TableauPanel } from "@/screens/risk/RiskCharts"
import { DongGridMap } from "@/screens/risk/RiskMaps"
import { effectivePeriod, formatMonth, type RiskQuery } from "@/screens/risk/riskQuery"
import { STAGE_COLORS, STAGE_LABELS, STAGE_TEXT } from "@/screens/risk/riskStyle"
import { useAgentContext } from "@/stores/agentContextStore"
import type { RiskStage } from "@/types/domain"

type Loaded =
  | { ok: true; dong: DongInsightResponse; report: InsightReportResponse["report"]; reportError: string | null }
  | { ok: false; message: string }

/**
 * 2.1 고립 위험 탐색 — 읍면동 화면 (5단계)
 * - 기간 필터만 있다 (지역은 시군구 화면에서). 격자 지도·인사이트·보고서는 기간의 마지막 월(기준 월) 기준
 * - 위험도는 격자 지도와 같이 행동 이상 기준 (배경 취약성 단계는 함께 표시)
 * - ⑥ 격자 지도는 Tableau, 인사이트(2.1.3)·보고서(2.1.4)는 우리 서버 API
 * - 다른 읍면동은 '이전으로'로 시군구 지도로 돌아가 고른다
 */
export function RiskDongScreen({
  query,
  months,
  nonce,
  onBack,
  onApply,
}: {
  query: RiskQuery & { dongCode: string }
  months: string[]
  nonce: number
  onBack: () => void
  onApply: (period: { from: string; to: string }) => void
}) {
  const navigate = useNavigate()
  const period = effectivePeriod(query, months)
  const baseMonth = period?.to ?? null
  const [form, setForm] = useState<{ from: string | null; to: string | null }>({ from: query.from, to: query.to })
  const [error, setError] = useState<string>()
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    setForm({ from: query.from, to: query.to })
    setError(undefined)
  }, [query.from, query.to])

  // 화면에 들어올 때·'적용'할 때 인사이트·보고서를 불러오고 ⑥에 필터·매개변수를 넘긴다
  const shown = useRef(false)
  useEffect(() => {
    if (!baseMonth) return
    const insight = analysisApi.getDongInsight({ dongCode: query.dongCode, month: baseMonth })
    if (!insight.ok) {
      setLoaded({ ok: false, message: insight.message })
      return
    }
    noteTableau(shown.current ? `${TABLEAU_VIEWS.grid}에 필터·매개변수 다시 전달 ('적용')` : `${TABLEAU_VIEWS.grid}를 띄우며 넘긴 필터·매개변수`, [
      `${TABLEAU_VIEWS.grid}: 행정동=${query.dongCode}(${insight.data.dongName}), 기준 월=${baseMonth}`,
    ])
    shown.current = true
    const report = analysisApi.getInsightReport({ dongCode: query.dongCode, month: baseMonth })
    setLoaded({
      ok: true,
      dong: insight.data,
      report: report.ok ? report.data.report : null,
      reportError: report.ok ? null : report.message,
    })
  }, [query.dongCode, period?.from, baseMonth, nonce])

  useDevScenario(
    {
      screen: "고립 위험 탐색 (읍면동)",
      hint: "기간의 마지막 월(기준 월)로 격자 지도·인사이트·보고서를 다시 불러옵니다. 채우기 버튼은 입력칸만 바꿉니다. 세곡동은 2025.12 인사이트·보고서가 아직 없는 경우입니다.",
      actions: [
        { label: "세곡동 열기 (인사이트 없음)", run: () => navigate(`${PATHS.risk}?dong=1168070000`) },
        { label: "없는 행정동 열기", run: () => navigate(`${PATHS.risk}?dong=1168099999`) },
        { label: "첫 적재 월만 (2025-07)", run: () => setForm({ from: "2025-07", to: "2025-07" }) },
        { label: "기간 오류 (2025-12 ~ 2025-07)", run: () => setForm({ from: "2025-12", to: "2025-07" }) },
        { label: "사례자 탐색으로 이동", run: () => navigate(`${PATHS.cases}?dongCode=${query.dongCode}`) },
        { label: "복지자원 찾기로 이동", run: () => navigate(`${PATHS.resources}?dongCode=${query.dongCode}`) },
      ],
    },
    [query.dongCode],
  )

  // AI Agent가 참고할 화면: 행정동·기준 월 (0.2.2)
  const loadedDong = loaded?.ok ? loaded.dong : null
  useAgentContext(
    loadedDong && baseMonth
      ? {
          screen: { screenType: "risk-dong", dongCode: query.dongCode, month: baseMonth },
          label: `고립 위험 탐색 · ${loadedDong.sigunguName} ${loadedDong.dongName} (${formatMonth(baseMonth)})`,
        }
      : null,
    [loadedDong, baseMonth],
  )

  const backButton = (
    <button type="button" className="back-link" onClick={onBack}>
      &lt; 이전으로
    </button>
  )

  if (months.length === 0 || !period || !baseMonth) {
    return (
      <section className="screen risk-screen">
        {backButton}
        <EmptyState title="적재된 분석 데이터가 없습니다." />
      </section>
    )
  }
  if (loaded && !loaded.ok) {
    return (
      <section className="screen risk-screen">
        {backButton}
        <EmptyState title={loaded.message} description="'이전으로'를 눌러 시군구 지도에서 행정동을 다시 고르세요." />
      </section>
    )
  }
  if (!loaded) return null

  const { dong, report } = loaded
  const formPeriod = effectivePeriod(form, months)
  const apply = () => {
    if (!formPeriod) return
    if (formPeriod.from > formPeriod.to) {
      setError("시작 월이 종료 월보다 늦습니다.")
      return
    }
    setError(undefined)
    onApply(formPeriod)
  }
  const grid = tableauViews.grid(query.dongCode, baseMonth)

  return (
    <section className="screen risk-screen risk-dong">
      <div className="risk-heading">
        <div>
          {backButton}
          <h1 className="page-title">
            {dong.sigunguName} {dong.dongName}의 고립 위험 분석
          </h1>
        </div>
        <div className="risk-filters">
          <div className="risk-filter-group">
            <span className="risk-filter-label">기간</span>
            <div className="risk-filter-controls">
              {(["from", "to"] as const).map((key) => (
                <MonthSelect
                  key={key}
                  label={key === "from" ? "시작 월" : "종료 월"}
                  value={formPeriod?.[key] ?? ""}
                  months={months}
                  invalid={Boolean(error)}
                  onChange={(value) => setForm({ ...form, [key]: value })}
                  separator={key === "to"}
                />
              ))}
            </div>
            <FieldError message={error} />
          </div>
          <button type="button" className="btn btn-primary risk-apply" onClick={apply}>
            적용
          </button>
        </div>
      </div>

      <div className="risk-dong-body">
        <div className="risk-dong-left">
          <div className="dong-summary">
            <span className="dong-summary-label">고립 위험</span>
            <StageBadge stage={dong.behavior.stage} />
            <span className="dong-summary-note">행동 이상 기준 · {formatMonth(baseMonth)}</span>
            <div className="dong-summary-chips">
              <span className="index-chip">
                배경 취약성 <b>{dong.background.stage}단계</b> ({dong.background.score.toFixed(2)}점)
              </span>
              <span className="index-chip">
                행동 이상 <b>{dong.behavior.stage}단계</b> ({dong.behavior.score.toFixed(2)}점)
              </span>
            </div>
          </div>

          <TableauPanel view="⑥" title={`${dong.dongName} 격자별 행동 이상 위험도 · ${formatMonth(baseMonth)}`}>
            {grid ? (
              <DongGridMap polygons={grid.polygons} cells={grid.cells} counts={grid.counts} />
            ) : (
              <TableauMessage>표시할 격자 데이터가 없습니다.</TableauMessage>
            )}
          </TableauPanel>

          <section className="risk-panel quick-insight">
            <header className="risk-panel-head">
              <h2>
                <span className="sparkle" aria-hidden="true">
                  ✦
                </span>{" "}
                퀵 인사이트
              </h2>
            </header>
            {dong.insight ? (
              <>
                <ul className="quick-insight-list">
                  {dong.insight.summary.map((sentence) => (
                    <li key={sentence}>
                      <Emphasized text={sentence} />
                    </li>
                  ))}
                </ul>
                <p className="quick-insight-meta">AI 생성 · {dong.insight.generatedAt}</p>
              </>
            ) : (
              <p className="risk-empty-text">이 달의 인사이트가 아직 없습니다.</p>
            )}
            <p className="quick-links-title">분석 결과를 활용해볼까요?</p>
            <div className="quick-links">
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => navigate(`${PATHS.resources}?dongCode=${query.dongCode}`)}
              >
                복지자원 찾기 →
              </button>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => navigate(`${PATHS.cases}?dongCode=${query.dongCode}`)}
              >
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
              인사이트 보고서 · {formatMonth(baseMonth)}
            </h2>
          </header>
          {report ? (
            <InsightReportView report={report} />
          ) : (
            <p className="risk-empty-text">{loaded.reportError ?? "이 달의 인사이트 보고서가 아직 없습니다."}</p>
          )}
        </aside>
      </div>
    </section>
  )
}

function StageBadge({ stage }: { stage: RiskStage }) {
  return (
    <span className="stage-badge" style={{ background: STAGE_COLORS[stage], color: STAGE_TEXT[stage] }}>
      {stage}단계 {STAGE_LABELS[stage]}
    </span>
  )
}

function MonthSelect({
  label,
  value,
  months,
  invalid,
  separator,
  onChange,
}: {
  label: string
  value: string
  months: string[]
  invalid: boolean
  separator: boolean
  onChange: (value: string) => void
}) {
  return (
    <>
      {separator && <span aria-hidden="true">~</span>}
      <select
        className="input select risk-month"
        aria-label={label}
        value={value}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
      >
        {months.map((month) => (
          <option key={month} value={month}>
            {formatMonth(month)}
          </option>
        ))}
      </select>
    </>
  )
}
