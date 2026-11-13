import { useRef, useState } from "react"
import type { InsightReport } from "@/api/analysisApi"
import { ReportGraphDialog } from "@/screens/risk/ReportGraphDialog"
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
 * - 그래프는 ⑥ 격자 지도와 같은 매개변수(시군구 · 기간 · 행정동)로 띄우고, 화면에 보일 때 불러온다 (TableauSheetFrame).
 *   eager(숨겨 둔 시연 동 화면)면 보이기 전에 모두 불러온다
 * - 시트는 게시본 데스크톱 배치의 고정 크기(그래프마다 다름: 720 · 900 폭, 420~700 높이) 그대로 전체를 띄우고,
 *   패널이 더 좁으면 패널 폭에 맞춰 줄인다. 틀 높이는 그래프마다 그 크기를 따른다. 도구 모음만 가린다
 * - 그래프마다 '크게 보기': 같은 시트를 설계 크기(1배)로 창에 띄우고 설명을 함께 보인다 (ReportGraphDialog)
 * - 그래프 하나를 못 불러오면 그 카드만 '다시 시도'를 보이고 설명은 그대로 둔다. 목록에 없는 시트는 띄우지 않는다
 * - 설명은 일반 글이다 (HTML · 강조 표시 없이 줄바꿈만 살린다)
 */
export function InsightReportView({
  report,
  dongCode,
  sigunguCode,
  period,
  eager = false,
}: {
  report: InsightReport
  dongCode: string
  sigunguCode: string
  period: { from: string; to: string }
  /** 보이기 전에 그래프를 모두 불러온다 */
  eager?: boolean
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
          eager={eager}
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
  eager,
}: {
  number: number
  sheet: string
  description: string | null
  parameters: TableauParameterInput[]
  published: boolean
  eager: boolean
}) {
  const view = reportSheet(sheet)
  const title = view?.title ?? "그래프"
  const text = description?.trim()
  const canZoom = published && view !== null
  const [zoomed, setZoomed] = useState(false)
  const zoomButtonRef = useRef<HTMLButtonElement>(null)
  const closeZoom = () => {
    setZoomed(false)
    zoomButtonRef.current?.focus()
  }
  return (
    <figure className={canZoom ? "report-graph has-zoom" : "report-graph"}>
      <figcaption className="report-subtitle">
        {number}. {title}
      </figcaption>
      {canZoom && (
        <button
          ref={zoomButtonRef}
          type="button"
          className="report-zoom-button"
          aria-haspopup="dialog"
          aria-label={`${number}. ${title} 크게 보기`}
          onClick={() => setZoomed(true)}
        >
          크게 보기
        </button>
      )}
      {zoomed && view && (
        <ReportGraphDialog
          title={`${number}. ${title}`}
          src={view.src}
          width={view.width}
          height={view.height}
          parameters={parameters}
          description={text}
          onClose={closeZoom}
        />
      )}
      {published ? (
        <TableauSheetFrame
          src={view?.src ?? null}
          label={title}
          parameters={parameters}
          openWidth={view?.width}
          initialSize={view ? { width: view.width, height: view.height } : undefined}
          hideToolbar
          desktopLayout
          eager={eager}
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
