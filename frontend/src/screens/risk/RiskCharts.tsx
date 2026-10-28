import type { ReactNode } from "react"
import type { BackgroundPoint, StageCounts } from "@/mock/tableau/tableauViews"
import {
  DECREASE_COLOR,
  INCREASE_COLOR,
  QUINTILE_COLORS,
  STAGE_COLORS,
  STAGE_TEXT,
  STAGES,
} from "@/screens/risk/riskStyle"
import { shortMonth } from "@/screens/risk/riskQuery"

// 고립 위험 탐색의 Tableau 화면 5개를 비슷하게 흉내 낸 예시 그림.
// 실제 개발에서는 이 자리에 Tableau Public 화면(<tableau-viz>)이 들어간다.

const signed = (value: number, digits = 1) => `${value > 0 ? "+" : ""}${value.toFixed(digits)}`

/** 우리 화면이 만드는 패널(제목·버튼) + 안쪽 Tableau 영역 */
export function TableauPanel({
  view,
  title,
  actions,
  className,
  children,
}: {
  /** ① ~ ⑥ */
  view: string
  title: string
  actions?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section className={`risk-panel ${className ?? ""}`}>
      <header className="risk-panel-head">
        <h2>{title}</h2>
        {actions}
      </header>
      <div className="tableau-frame">
        <span className="tableau-badge">Tableau {view} 예시 그림</span>
        {children}
      </div>
    </section>
  )
}

/** Tableau 영역 안의 안내 (데이터가 없을 때 등) */
export function TableauMessage({ children }: { children: ReactNode }) {
  return <p className="tableau-message">{children}</p>
}

/** ② 고립 위험도 분포 변화: 월별 단계별 행정동 수 (누적 막대) */
export function StageDistributionChart({
  rows,
}: {
  rows: { month: string; counts: StageCounts; total: number }[]
}) {
  return (
    <div className="stage-distribution">
      <div className="stage-rows">
        {rows.map((row) => (
          <div key={row.month} className="stage-row">
            <span className="stage-month">{shortMonth(row.month)}</span>
            <div className="stage-bar">
              {STAGES.filter((stage) => row.counts[stage] > 0).map((stage) => (
                <span
                  key={stage}
                  style={{
                    flexGrow: row.counts[stage],
                    background: STAGE_COLORS[stage],
                    color: STAGE_TEXT[stage],
                  }}
                  title={`${stage}단계 ${row.counts[stage]}개 (${Math.round((row.counts[stage] / row.total) * 100)}%)`}
                >
                  {row.counts[stage]}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="stage-legend">
        {STAGES.map((stage) => (
          <span key={stage}>
            <i style={{ background: STAGE_COLORS[stage] }} />
            {stage}단계
          </span>
        ))}
      </div>
    </div>
  )
}

/** ③ 행정동별 배경 취약성 분포: 점(5분위 색) + 상자(사분위수·중앙값) + 이상값 */
export function BackgroundDistributionChart({
  data,
}: {
  data: {
    points: BackgroundPoint[]
    q1: number
    median: number
    q3: number
    whiskerLow: number
    whiskerHigh: number
  }
}) {
  const width = 430
  const left = 14
  const right = 14
  const axisMax = Math.max(50, Math.ceil(Math.max(...data.points.map((point) => point.score)) / 10) * 10)
  const x = (value: number) => left + (value / axisMax) * (width - left - right)
  const centerY = 46
  const ticks = Array.from({ length: axisMax / 10 + 1 }, (_, index) => index * 10)

  return (
    <div className="background-distribution">
      <svg viewBox={`0 0 ${width} 104`} className="chart-svg" role="img" aria-label="행정동별 배경 취약성 분포">
        <line x1={x(data.whiskerLow)} x2={x(data.q1)} y1={centerY} y2={centerY} stroke="#9aa7bd" />
        <line x1={x(data.q3)} x2={x(data.whiskerHigh)} y1={centerY} y2={centerY} stroke="#9aa7bd" />
        <rect
          x={x(data.q1)}
          y={centerY - 11}
          width={x(data.q3) - x(data.q1)}
          height={22}
          fill="#e3ebf8"
          stroke="#9aa7bd"
        />
        <line x1={x(data.median)} x2={x(data.median)} y1={centerY - 11} y2={centerY + 11} stroke="#324085" strokeWidth={2} />
        {data.points.map((point, index) => (
          <g key={point.dongCode}>
            <circle
              cx={x(point.score)}
              cy={centerY + (index % 2 === 0 ? -3 : 3)}
              r={4.5}
              fill={QUINTILE_COLORS[point.quintile]}
              stroke="#fff"
              strokeWidth={1}
            >
              <title>{`${point.dongName} ${point.score.toFixed(1)} (${point.quintile}분위)`}</title>
            </circle>
            {point.outlier && (
              <text x={x(point.score) + 6} y={centerY + 26} fontSize={10} fill="#4b5563">
                {`${point.dongName} ${point.score.toFixed(1)} · 이상값`}
              </text>
            )}
          </g>
        ))}
        <text x={x(data.q1) - 2} y={centerY + 26} fontSize={10} fill="#6b7686" textAnchor="end">
          Q1 {data.q1}
        </text>
        <text x={x(data.median)} y={centerY - 16} fontSize={10} fill="#324085" textAnchor="middle">
          중앙값 {data.median}
        </text>
        <text x={x(data.q3) + 2} y={centerY + 26} fontSize={10} fill="#6b7686" textAnchor="start">
          Q3 {data.q3}
        </text>
        <line x1={left} x2={width - right} y1={90} y2={90} stroke="#c9d1de" />
        {ticks.map((tick) => (
          <text key={tick} x={x(tick)} y={102} fontSize={10} fill="#8a94a5" textAnchor="middle">
            {tick}
          </text>
        ))}
      </svg>
      <div className="quintile-legend">
        {([1, 2, 3, 4, 5] as const).map((quintile) => (
          <span key={quintile}>
            <i style={{ background: QUINTILE_COLORS[quintile] }} />
            {quintile}분위{quintile === 1 ? " 상위 20%" : quintile === 5 ? " 하위 20%" : ""}
          </span>
        ))}
      </div>
    </div>
  )
}

/** ④ 월별 행동 이상 지수 변화: 전월 대비 변화량 막대 + 꺾은선, 기간의 첫 월은 기준월(0) */
export function MonthlyBehaviorChart({ points }: { points: { month: string; change: number }[] }) {
  const width = 430
  const height = 190
  const top = 26
  const bottom = 30
  const maxAbs = Math.max(0.5, ...points.map((point) => Math.abs(point.change))) * 1.25
  const zero = top + (height - top - bottom) / 2
  const y = (value: number) => zero - (value / maxAbs) * ((height - top - bottom) / 2)
  const step = (width - 40) / points.length
  const cx = (index: number) => 30 + step * index + step / 2
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${cx(index)},${y(point.change)}`).join(" ")

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label="월별 행동 이상 지수 변화">
      <line x1={20} x2={width - 10} y1={zero} y2={zero} stroke="#9aa7bd" />
      {points.map((point, index) => {
        const barTop = Math.min(y(point.change), zero)
        const barHeight = Math.abs(y(point.change) - zero)
        return (
          <g key={point.month}>
            {index > 0 && (
              <rect
                x={cx(index) - 15}
                y={barTop}
                width={30}
                height={Math.max(barHeight, 1)}
                fill={point.change >= 0 ? INCREASE_COLOR : DECREASE_COLOR}
                opacity={0.85}
              />
            )}
            <text
              x={cx(index)}
              y={point.change >= 0 ? y(point.change) - 8 : y(point.change) + 16}
              fontSize={11}
              textAnchor="middle"
              fill="#243247"
            >
              {index === 0 ? "0 (기준월)" : signed(point.change, 2)}
            </text>
            <text x={cx(index)} y={height - 8} fontSize={11} textAnchor="middle" fill="#6b7686">
              {shortMonth(point.month)}
            </text>
          </g>
        )
      })}
      <path d={path} fill="none" stroke="#243247" strokeWidth={1.5} />
      {points.map((point, index) => (
        <circle key={point.month} cx={cx(index)} cy={y(point.change)} r={3.5} fill="#243247" />
      ))}
    </svg>
  )
}

/** ⑤ 행정동별 전월 대비 행동 이상 지수 변화: 증가가 큰 순서의 가로 막대 */
export function DongChangeChart({ items }: { items: { dongCode: string; dongName: string; change: number }[] }) {
  const width = 430
  const rowHeight = 17
  const labelWidth = 62
  const barArea = width - labelWidth - 50
  const maxAbs = Math.max(0.5, ...items.map((item) => Math.abs(item.change)))
  const zeroX = labelWidth + barArea / 2 + 10
  const scale = (barArea / 2 - 10) / maxAbs
  const height = items.length * rowHeight + 6

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label="행정동별 전월 대비 행동 이상 지수 변화">
      <line x1={zeroX} x2={zeroX} y1={0} y2={height} stroke="#c9d1de" />
      {items.map((item, index) => {
        const y = index * rowHeight + 3
        const length = Math.abs(item.change) * scale
        const positive = item.change >= 0
        return (
          <g key={item.dongCode}>
            <text x={0} y={y + 11} fontSize={10.5} fill="#4b5563">
              {item.dongName}
            </text>
            <rect
              x={positive ? zeroX : zeroX - length}
              y={y + 2}
              width={Math.max(length, 1)}
              height={rowHeight - 6}
              fill={positive ? INCREASE_COLOR : DECREASE_COLOR}
            />
            <text
              x={positive ? zeroX + length + 4 : zeroX - length - 4}
              y={y + 11}
              fontSize={10}
              textAnchor={positive ? "start" : "end"}
              fill="#243247"
            >
              {signed(item.change)}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
