import type { InsightReport } from "@/api/analysisApi"
import { isPublished, reportSheet, tableauDetailParameters, tableauParameterInputs } from "@/tableau/tableauConfig"
import { TableauSheetFrame } from "@/tableau/TableauSheetFrame"
import type { TableauParameterInput } from "@/tableau/tableauTypes"
import { formatDateTime } from "@/utils/datetime"

/**
 * 2.1.4 인사이트 보고서 (API-12, openapi 2.4.0 · docs/api/insight-report.md 8 · 9절)
 * - AI가 고른 그래프 3개를 순서대로: 상세 워크북 시트(EmbedDetailV01~V08)와 그 설명
 * - 퀵 인사이트(report.quickInsight)는 여기서 다시 보이지 않는다. 같은 글이 왼쪽 아래 퀵 인사이트(API-11 summary[0])에 나온다
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
  description: string
  parameters: TableauParameterInput[]
  published: boolean
}) {
  const view = reportSheet(sheet)
  const title = view?.title ?? "그래프"
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
      <p className="report-graph-description">{description.trim()}</p>
    </figure>
  )
}
