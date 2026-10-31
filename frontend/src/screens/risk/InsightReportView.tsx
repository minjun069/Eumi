import { Emphasized } from "@/components/common/Emphasized"
import type { InsightReportResponse } from "@/mock/api/analysisApi"
import { splitDirection } from "@/screens/risk/emphasis"
import { shortMonth } from "@/screens/risk/riskQuery"
import { STAGE_COLORS, STAGE_TEXT } from "@/screens/risk/riskStyle"
import type { ReportBlock, ReportChart } from "@/types/domain"

// 2.1.4 인사이트 보고서. 저장된 보고서(질문별 문장·목록·그래프 값)를 받아 화면이 그린다.
// 그래프는 Tableau가 아니라 우리 화면이 그린다 (R2: 보고서를 만들 때 그래프 값까지 저장).

type Report = NonNullable<InsightReportResponse["report"]>
type ChartOf<T extends ReportChart["type"]> = Extract<ReportChart, { type: T }>

const MAIN_COLOR = "#2f6fdc"
const OTHER_COLOR = "#c9c5bb"
const BAND_COLOR = "#ece9e1"
const signed = (value: number, digits = 1) => `${value > 0 ? "+" : ""}${value.toFixed(digits)}`

export function InsightReportView({ report }: { report: Report }) {
  return (
    <article className="insight-report">
      <h3 className="report-headline">
        {splitDirection(report.headline).map((part, index) =>
          part.direction ? (
            <span key={index} className={`is-${part.direction}`}>
              {part.text}
            </span>
          ) : (
            part.text
          ),
        )}
      </h3>
      {report.sections.map((section, index) => (
        <section key={index} className="report-section">
          {section.question && <h4 className="report-question">Q. {section.question}</h4>}
          {section.blocks.map((block, blockIndex) => (
            <ReportBlockView key={blockIndex} block={block} />
          ))}
        </section>
      ))}
      <p className="report-footnote">
        월 데이터를 분석할 때 AI가 만든 보고서입니다 ({report.generatedAt}). 더 궁금한 점은 오른쪽 위 AI 패널에서 물어보세요.
      </p>
    </article>
  )
}

function ReportBlockView({ block }: { block: ReportBlock }) {
  if (block.kind === "paragraph") {
    return (
      <p className="report-paragraph">
        <Emphasized text={block.text} />
      </p>
    )
  }
  if (block.kind === "bullets") {
    return (
      <ul className="report-bullets">
        {block.items.map((item) => (
          <li key={item.label}>
            <strong>{item.label}</strong>: <Emphasized text={item.text} />
          </li>
        ))}
      </ul>
    )
  }
  return (
    <figure className="report-chart">
      <ReportChartView chart={block.chart} />
    </figure>
  )
}

function ReportChartView({ chart }: { chart: ReportChart }) {
  switch (chart.type) {
    case "trend":
      return <TrendChart chart={chart} />
    case "factors":
      return <FactorsChart chart={chart} />
    case "weekday":
      return <WeekdayChart chart={chart} />
    case "compare":
      return <CompareChart chart={chart} />
    case "ratio":
      return <RatioChart chart={chart} />
  }
}

function Legend({ items }: { items: { label: string; color: string; kind?: "line" | "dash" | "box" }[] }) {
  return (
    <div className="report-legend">
      {items.map((item) => (
        <span key={item.label}>
          <i className={`legend-${item.kind ?? "box"}`} style={{ background: item.kind === "dash" ? undefined : item.color, borderColor: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  )
}

/** 행동 이상 지수 추이: 이 동의 점수(선), 시군구 중앙값(점선), 가운데 50% 범위(띠), 월별 단계 */
function TrendChart({ chart }: { chart: ChartOf<"trend"> }) {
  const width = 500
  const height = 210
  const left = 34
  const right = 20
  const top = 26
  const plotBottom = 160
  const values = chart.points.flatMap((point) => [point.score, point.q1, point.q3])
  const low = Math.floor(Math.min(...values) - 1)
  const high = Math.ceil(Math.max(...values) + 2)
  const step = high - low > 12 ? 4 : 2
  const ticks = Array.from({ length: Math.floor((high - low) / step) + 1 }, (_, index) => low + index * step)
  const slot = (width - left - right) / chart.points.length
  const x = (index: number) => left + slot * index + slot / 2
  const y = (value: number) => top + ((high - value) / (high - low)) * (plotBottom - top)
  // 중앙값 선·범위 띠는 달마다 이어 그린다 (한 달뿐이면 그 달 양옆으로 짧게)
  const spans =
    chart.points.length === 1
      ? [
          { at: x(0) - slot / 4, point: chart.points[0] },
          { at: x(0) + slot / 4, point: chart.points[0] },
        ]
      : chart.points.map((point, index) => ({ at: x(index), point }))
  const line = (pick: (point: ChartOf<"trend">["points"][number]) => number) =>
    spans.map((item, index) => `${index === 0 ? "M" : "L"}${item.at.toFixed(1)},${y(pick(item.point)).toFixed(1)}`).join("")
  const band = [
    ...spans.map((item) => `${item.at.toFixed(1)},${y(item.point.q3).toFixed(1)}`),
    ...[...spans].reverse().map((item) => `${item.at.toFixed(1)},${y(item.point.q1).toFixed(1)}`),
  ].join(" ")
  const scores = chart.points.map((point) => point.score)
  const annotated = new Set([scores.indexOf(Math.max(...scores)), scores.indexOf(Math.min(...scores)), chart.points.length - 1])

  return (
    <>
      <div className="report-chart-head">
        <strong>{chart.heading}</strong>
        <Legend
          items={[
            { label: "이 동", color: MAIN_COLOR, kind: "line" },
            { label: "중앙값", color: "#8a94a5", kind: "dash" },
            { label: "가운데 50% 범위", color: BAND_COLOR },
          ]}
        />
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label={chart.heading}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} stroke="#eef1f5" />
            <text x={left - 6} y={y(tick) + 3.5} fontSize={10} textAnchor="end" fill="#8a94a5">
              {tick}
            </text>
          </g>
        ))}
        <polygon points={band} fill={BAND_COLOR} />
        <path d={line((point) => point.median)} fill="none" stroke="#8a94a5" strokeWidth={1.2} strokeDasharray="4 3" />
        {chart.points.length > 1 && <path d={line((point) => point.score)} fill="none" stroke={MAIN_COLOR} strokeWidth={2} />}
        {chart.points.map((point, index) => (
          <g key={point.month}>
            <circle cx={x(index)} cy={y(point.score)} r={4.5} fill={MAIN_COLOR} stroke="#fff" strokeWidth={2}>
              <title>{`${shortMonth(point.month)} ${point.score}점 · ${point.stage}단계 · ${chart.total}개 동 중 ${point.rank}위 · 중앙값 ${point.median}`}</title>
            </circle>
            <text x={x(index)} y={y(point.score) - 9} fontSize={10.5} textAnchor="middle" fill="#243247">
              {point.score.toFixed(1)}
            </text>
            {annotated.has(index) && (
              <text x={x(index)} y={y(point.score) + 17} fontSize={10} textAnchor="middle" fill={MAIN_COLOR}>
                {point.rank}위
              </text>
            )}
            <text x={x(index)} y={plotBottom + 16} fontSize={10.5} textAnchor="middle" fill="#6b7686">
              {shortMonth(point.month)}
            </text>
            <rect x={x(index) - 19} y={plotBottom + 26} width={38} height={18} rx={4} fill={STAGE_COLORS[point.stage]} />
            <text x={x(index)} y={plotBottom + 39} fontSize={10.5} textAnchor="middle" fill={STAGE_TEXT[point.stage]}>
              {point.stage}단계
            </text>
          </g>
        ))}
      </svg>
      <figcaption className="report-caption">파란 글씨 = {chart.total}개 동 중 순위 (가장 높은 달·낮은 달·이번 달)</figcaption>
    </>
  )
}

/** 전월 대비 점수 변화 요인: 올린 요인은 파랑, 내린 요인은 회색 가로 막대 */
function FactorsChart({ chart }: { chart: ChartOf<"factors"> }) {
  const width = 500
  const labelWidth = 200
  const rowHeight = 22
  const values = chart.items.map((item) => item.value)
  const max = Math.max(0, ...values)
  const min = Math.min(0, ...values)
  // 막대 끝 숫자 자리(오른쪽, 내린 요인이 있으면 왼쪽도)를 빼고 나눈다
  const textRoom = 45
  const leftRoom = min < 0 ? textRoom : 0
  const scale = (width - labelWidth - textRoom - leftRoom) / (max - min || 1)
  const zero = labelWidth + leftRoom - min * scale
  const height = chart.items.length * rowHeight + 4

  return (
    <>
      <div className="report-chart-head">
        <strong>{chart.heading}</strong>
        <Legend
          items={[
            { label: "점수를 올린 요인", color: MAIN_COLOR },
            { label: "점수를 내린 요인", color: OTHER_COLOR },
          ]}
        />
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label={chart.heading}>
        <line x1={zero} x2={zero} y1={0} y2={height} stroke="#c9d1de" />
        {chart.items.map((item, index) => {
          const y = index * rowHeight + 4
          const length = Math.max(Math.abs(item.value) * scale, 1)
          const positive = item.value >= 0
          return (
            <g key={item.label}>
              <text x={0} y={y + 12} fontSize={11} fill="#374151">
                {item.label}
              </text>
              <rect
                x={positive ? zero : zero - length}
                y={y + 3}
                width={length}
                height={rowHeight - 9}
                rx={3}
                fill={positive ? MAIN_COLOR : OTHER_COLOR}
              >
                <title>{`${item.label} ${signed(item.value, 2)}`}</title>
              </rect>
              <text
                x={positive ? zero + length + 4 : zero - length - 4}
                y={y + 12}
                fontSize={10.5}
                textAnchor={positive ? "start" : "end"}
                fill="#243247"
              >
                {signed(item.value, 2)}
              </text>
            </g>
          )
        })}
      </svg>
    </>
  )
}

/** 만 단위 (2.5만) */
function inTenThousands(value: number) {
  const amount = value / 10000
  return `${Number.isInteger(amount) ? amount : amount.toFixed(1)}만`
}

/** 요일별 일평균 활동 인구: 전월(회색)·이번 달(파랑) 막대와 변화율 */
function WeekdayChart({ chart }: { chart: ChartOf<"weekday"> }) {
  const width = 500
  const height = 200
  const left = 40
  const top = 22
  const bottom = 172
  const max = Math.max(...chart.series.flatMap((item) => item.values))
  const axisMax = Math.ceil(max / 25000) * 25000
  const ticks = Array.from({ length: axisMax / 25000 + 1 }, (_, index) => index * 25000)
  const slot = (width - left - 10) / chart.days.length
  const y = (value: number) => bottom - (value / axisMax) * (bottom - top)
  const barWidth = 15
  const colors = [OTHER_COLOR, MAIN_COLOR]

  return (
    <>
      <div className="report-chart-head">
        <strong>{chart.heading}</strong>
        <Legend items={chart.series.map((item, index) => ({ label: item.label, color: colors[index] }))} />
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label={chart.heading}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={left} x2={width - 10} y1={y(tick)} y2={y(tick)} stroke="#eef1f5" />
            <text x={left - 6} y={y(tick) + 3.5} fontSize={10} textAnchor="end" fill="#8a94a5">
              {tick === 0 ? "0" : inTenThousands(tick)}
            </text>
          </g>
        ))}
        {chart.days.map((day, dayIndex) => {
          const center = left + slot * dayIndex + slot / 2
          const tallest = Math.max(...chart.series.map((item) => item.values[dayIndex]))
          return (
            <g key={day}>
              {chart.series.map((item, seriesIndex) => {
                const value = item.values[dayIndex]
                return (
                  <rect
                    key={item.label}
                    x={center - barWidth - 1 + seriesIndex * (barWidth + 2)}
                    y={y(value)}
                    width={barWidth}
                    height={bottom - y(value)}
                    rx={3}
                    fill={colors[seriesIndex]}
                  >
                    <title>{`${day} ${item.label} ${value.toLocaleString()}${chart.unit}`}</title>
                  </rect>
                )
              })}
              <text x={center} y={y(tallest) - 6} fontSize={10.5} textAnchor="middle" fill="#243247">
                {signed(chart.changes[dayIndex])}%
              </text>
              <text x={center} y={bottom + 16} fontSize={10.5} textAnchor="middle" fill="#6b7686">
                {day}
              </text>
            </g>
          )
        })}
      </svg>
      <figcaption className="report-caption">{chart.caption}</figcaption>
    </>
  )
}

/** 이 동과 비교 대상의 가로 막대 */
function CompareChart({ chart }: { chart: ChartOf<"compare"> }) {
  const max = Math.max(...chart.items.map((item) => item.value))
  return (
    <>
      <Legend items={chart.items.map((item) => ({ label: item.label, color: item.highlight ? MAIN_COLOR : OTHER_COLOR }))} />
      <p className="compare-heading">{chart.heading}</p>
      <div className="compare-bars">
        {chart.items.map((item) => (
          <div key={item.label} className="compare-row" title={`${item.label} ${item.value}`}>
            <span
              className="compare-bar"
              style={{ width: `${(item.value / max) * 78}%`, background: item.highlight ? MAIN_COLOR : OTHER_COLOR }}
            />
            <em>{item.value}</em>
          </div>
        ))}
      </div>
    </>
  )
}

/** 사람 그림 비율 (10명 중 3명) */
function RatioChart({ chart }: { chart: ChartOf<"ratio"> }) {
  return (
    <div className="ratio-chart" role="img" aria-label={chart.caption}>
      <div className="ratio-people">
        {Array.from({ length: chart.total }, (_, index) => (
          <svg key={index} viewBox="0 0 24 34" width={22} height={31} aria-hidden="true">
            <circle cx={12} cy={7} r={6} fill={index < chart.count ? MAIN_COLOR : OTHER_COLOR} />
            <path d="M2 33 V22 a10 9 0 0 1 20 0 V33 Z" fill={index < chart.count ? MAIN_COLOR : OTHER_COLOR} />
          </svg>
        ))}
      </div>
      <strong>{chart.caption}</strong>
    </div>
  )
}
