import { useId, useLayoutEffect, useRef } from "react"
import { type AnswerArtifacts, type HtmlArtifact, sanitizeArtifactHtml } from "@/components/agent/artifactData"
import { TableauArtifactCard } from "@/tableau/TableauArtifactCard"

/** 완료 행의 표 · 그래프 (artifactsByAnswer로 고른 것). 그릴 것도 생략한 것도 없으면 아무것도 그리지 않는다 */
export function AgentArtifacts({ answer }: { answer: AnswerArtifacts | undefined }) {
  if (!answer || (answer.artifacts.length === 0 && answer.repeated === 0)) return null
  return (
    <div className="agent-artifacts">
      {answer.artifacts.map((artifact) =>
        artifact.kind === "tableau" ? (
          <TableauArtifactCard key={artifact.key} artifact={artifact} />
        ) : (
          <HtmlArtifactView key={artifact.key} artifact={artifact} />
        ),
      )}
      {answer.repeated > 0 && (
        <p className="agent-artifacts-repeated">앞 답변과 같은 그래프·표 {answer.repeated}개는 다시 그리지 않았어요.</p>
      )}
    </div>
  )
}

/** 정화한 HTML(표 · SVG)을 글자로 되돌리지 않고 조각 그대로 넣는다 */
function HtmlArtifactView({ artifact }: { artifact: HtmlArtifact }) {
  const boxRef = useRef<HTMLDivElement>(null)
  const idPrefix = `artifact-${useId().replace(/[^A-Za-z0-9]/g, "")}-`
  useLayoutEffect(() => {
    boxRef.current?.replaceChildren(sanitizeArtifactHtml(artifact.content, idPrefix))
  }, [artifact.content, idPrefix])
  return <div ref={boxRef} className={`agent-artifact agent-artifact-html is-${artifact.type}`} />
}
