import type { TableauArtifact } from "@/components/agent/artifactData"
import { TableauSheetFrame } from "@/tableau/TableauSheetFrame"

/**
 * AI 패널 완료 행의 Tableau 카드 (docs/api/ai-agent-panel.md artifacts, ai/docs/TABLEAU.md 끝 절)
 * - AI가 준 게시 뷰 주소 · 매개변수 · 필터로 띄운다. 띄우기 · 크기 · 확인 · 다시 시도는 TableauSheetFrame
 * - 출처 링크와 참고 사항(warnings)을 아래에 붙인다
 */
export function TableauArtifactCard({ artifact }: { artifact: TableauArtifact }) {
  const { src, title, source, warnings, parameters, filters } = artifact
  return (
    <figure className="agent-artifact agent-tableau">
      <figcaption className="agent-artifact-title">{title}</figcaption>
      <TableauSheetFrame src={src} label={title} parameters={parameters} filters={filters} />
      {source && (
        <a className="agent-artifact-source" href={source.uri} target="_blank" rel="noopener noreferrer">
          출처: {source.label}
        </a>
      )}
      {warnings.length > 0 && (
        <details className="agent-artifact-notes">
          <summary>참고 사항 {warnings.length}개</summary>
          <ul>
            {warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
    </figure>
  )
}
