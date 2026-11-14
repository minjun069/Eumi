import type { ReactNode } from "react"
import { EmptyState } from "@/components/common/EmptyState"
import { formatMonth } from "@/screens/risk/riskQuery"
import type { TableauView } from "@/tableau/tableauConfig"
import type { ChartState, Conditions } from "@/tableau/tableauTypes"
import { TableauWorksheet } from "@/tableau/TableauWorksheet"

// 고립 위험 탐색 화면들이 함께 쓰는 패널

/**
 * 우리 화면의 패널(제목·버튼) + 안쪽 Tableau 대시보드.
 * 게시본(tableauConfig)이 없는 뷰는 다른 뷰를 대신 넣지 않고 '준비 중'을 보인다
 * - 대시보드는 Tableau에서 만든 그대로 띄운다. crop이 있으면 그 부분만 보인다 (⑥: 위 선택 칸만 잘라 낸다)
 * - Tableau 도구 모음은 모든 패널에서 숨긴다 (틀 높이 = 대시보드 높이). 출처는 번호 없이 작은 'Tableau Public' 표시로 남긴다
 */
export function TableauViewPanel({
  view,
  title,
  label,
  conditions,
  actions,
  hint,
  refreshKey,
  onSelectDong,
  onParameterValue,
  onStateChange,
}: {
  view: TableauView
  title: string
  /** 화면 읽기 프로그램용 그래프 이름 */
  label: string
  conditions: Conditions
  actions?: ReactNode
  hint?: string
  refreshKey: number
  onSelectDong?: (dongCode: string) => void
  /** Tableau 매개변수 값 (TableauWorksheet onParameterValue) */
  onParameterValue?: (name: string, value: string) => void
  /** 불러오기 · 적용 상태 (TableauWorksheet onStateChange) */
  onStateChange?: (state: ChartState) => void
}) {
  const { dashboard, worksheet, width, height, crop, hoverHeight } = view
  return (
    <section className="risk-panel is-tableau">
      <header className="risk-panel-head">
        <h2>{title}</h2>
        {actions}
      </header>
      <div className="tableau-frame">
        {dashboard && worksheet ? (
          <>
            <span className="tableau-badge">Tableau Public</span>
            <TableauWorksheet
              dashboard={dashboard}
              worksheet={worksheet}
              label={label}
              width={width}
              height={height}
              filters={conditions.filters}
              parameters={conditions.parameters}
              toolbar="hidden"
              crop={crop}
              hoverHeight={hoverHeight}
              refreshKey={refreshKey}
              onSelectDong={onSelectDong}
              onParameterValue={onParameterValue}
              onStateChange={onStateChange}
            />
            {hint && <p className="tableau-hint">{hint}</p>}
          </>
        ) : (
          <p className="tableau-pending" style={{ minHeight: Math.min(height, 200) }}>
            이 그래프의 Tableau 게시본을 준비 중입니다.
          </p>
        )}
      </div>
    </section>
  )
}

/**
 * 적재된 월(API-10)이 404·400일 때의 제목. 없는 시군구일 수도, 분석 API를 아직 쓸 수 없는 것일 수도 있어
 * 어느 쪽이어도 틀리지 않게 쓴다
 */
export const MONTHS_UNAVAILABLE = "이 지역의 분석 결과를 불러올 수 없습니다."

/** 불러오지 못했을 때: 안내와 다시 시도 */
export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="risk-load-error" role="alert">
      <EmptyState title={message} />
      <button type="button" className="btn btn-outline" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  )
}

/** 불러오는 중 */
export function Loading({ text = "분석 결과를 불러오는 중입니다." }: { text?: string }) {
  return (
    <p className="risk-empty-text" role="status">
      {text}
    </p>
  )
}

/** 월 선택칸. 적재된 월만 고를 수 있다 */
export function MonthSelect({
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
        disabled={months.length === 0}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
      >
        {months.length === 0 && <option value="">-</option>}
        {/* 주소를 직접 고쳐 적재되지 않은 월이 들어온 경우에도 지금 값을 보인다 */}
        {value && !months.includes(value) && <option value={value}>{formatMonth(value)} (없는 월)</option>}
        {months.map((month) => (
          <option key={month} value={month}>
            {formatMonth(month)}
          </option>
        ))}
      </select>
    </>
  )
}
