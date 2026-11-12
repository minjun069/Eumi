import type { InsightReport } from "@/api/analysisApi"
import { isPublished, reportSheet, tableauDetailParameters, tableauParameterInputs } from "@/tableau/tableauConfig"
import { TableauSheetFrame } from "@/tableau/TableauSheetFrame"
import type { TableauParameterInput } from "@/tableau/tableauTypes"
import { formatDateTime } from "@/utils/datetime"

/**
 * 2.1.4 인사이트 보고서 (API-12, openapi 2.6.0 · docs/api/insight-report.md 8 · 9절)
 * - AI는 검토를 통과한 칸만 저장한다. 받은 그래프(찬 칸만 칸 순서대로 0~3개)를 순서대로 그리고, 번호는 화면 순서로 붙인다:
 *   상세 워크북 시트(EmbedDetailV01~V08)와 그 설명
 * - 설명이 없으면(null · 공백) 그 그래프 아래에 '설명 준비 중', 그래프가 0개면 그 자리에 '그래프 준비 중'
 * - 퀵 인사이트(report.quickInsight)는 여기서 보이지 않는다. 왼쪽 아래 퀵 인사이트는 API-11(summary[0])이 기준이다
 * - 그래프는 ⑥ 격자 지도와 같은 매개변수(시군구 · 기간 · 행정동)로 띄우고, 화면에 보일 때 불러온다 (TableauSheetFrame)
 * - 시트는 설계 폭(720, V06은 900)으로 펼쳐 패널 폭에 맞춰 줄이고, 설계 높이만큼만 보인다
 *   (게시본 높이가 700이라 아래가 비어 있다. 11/10 확인)
 * - 그래프 하나를 못 불러오면 그 카드만 '다시 시도'를 보이고 설명은 그대로 둔다. 목록에 없는 시트는 띄우지 않는다
 * - 설명은 일반 글이다 (HTML · 강조 표시 없이 줄바꿈만 살린다)
 */
export function InsightReportView({
  report,
  dongCode,
  sigunguCode,
  period,
}: {
  report: InsightReport
  dongCode: string
  sigunguCode: string
  period: { from: string; to: string }
}) {
  const published = isPublished(sigunguCode, period)
  const parameters = tableauParameterInputs(tableauDetailParameters(dongCode, sigunguCode, period))
  return (
    <article className="insight-report">
      {report.graphs.length === 0 && <p className="risk-empty-text">그래프를 준비 중입니다.</p>}
      {report.graphs.map((graph, index) => (
        <ReportGraph
          key={`${index}-${graph.sheet}`}
          number={index + 1}
          sheet={graph.sheet}
          description={graph.description}
          parameters={parameters}
          published={published}
        />
      ))}
      <p className="report-footnote">
        AI 생성 · {formatDateTime(report.generatedAt)}. 더 궁금한 점은 오른쪽 위 AI 패널에서 물어보세요.
      </p>
    </article>
  )
}

function ReportGraph({
  number,
  sheet,
  description,
  parameters,
  published,
}: {
  number: number
  sheet: string
  description: string | null
  parameters: TableauParameterInput[]
  published: boolean
}) {
  const view = reportSheet(sheet)
  const title = view?.title ?? "그래프"
  const text = description?.trim()
  return (
    <figure className="report-graph">
      <figcaption className="report-subtitle">
        {number}. {title}
      </figcaption>
      {published ? (
        <TableauSheetFrame
          src={view?.src ?? null}
          label={title}
          parameters={parameters}
          openWidth={view?.width}
          initialSize={view ? { width: view.width, height: view.height } : undefined}
          visibleHeight={view?.height}
        />
      ) : (
        <p className="tableau-pending">Tableau 게시본이 아직 이 지역·기간을 담고 있지 않습니다.</p>
      )}
      {text ? (
        <p className="report-graph-description">{text}</p>
      ) : (
        <p className="report-graph-description risk-empty-text">설명을 준비 중입니다.</p>
      )}
    </figure>
  )
}
