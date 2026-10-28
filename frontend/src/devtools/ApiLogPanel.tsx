import { useState } from "react"
import {
  clearApiLog,
  useApiLog,
  type ApiLogEntry,
} from "@/devtools/apiLogStore"
import { copyText } from "@/devtools/copyText"
import { formatAll, formatRequest, formatResponse } from "@/devtools/formatLog"

/** 응답이 이 줄 수보다 길면 처음에는 접어 둔다 */
const LONG_RESPONSE_LINES = 14

/** API 기록 (개발용). 최신 기록이 맨 위에 오고, 패널 안에서 위아래로 스크롤한다 */
export function ApiLogPanel() {
  const entries = useApiLog()
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
    "idle",
  )
  const apiCount = entries.filter((entry) => entry.kind === "api").length
  const newestFirst = [...entries].reverse()

  const copyAll = async () => {
    const copied = await copyText(formatAll(entries))
    setCopyState(copied ? "copied" : "failed")
    window.setTimeout(() => setCopyState("idle"), 1500)
  }

  return (
    <section className="dev-section dev-log">
      <div className="dev-log-head">
        <h2 className="dev-title">
          API 기록 <span className="dev-count">{apiCount}건</span>
        </h2>
        <div className="dev-log-actions">
          <button
            type="button"
            className="dev-button"
            onClick={copyAll}
            disabled={entries.length === 0}
          >
            {copyState === "copied"
              ? "복사함"
              : copyState === "failed"
                ? "복사 실패"
                : "전체 복사"}
          </button>
          <button
            type="button"
            className="dev-button"
            onClick={clearApiLog}
            disabled={entries.length === 0}
          >
            지우기
          </button>
        </div>
      </div>
      <div className="dev-log-list">
        {newestFirst.length === 0 ? (
          <p className="dev-empty">
            화면에서 동작하면 여기에 기능 ID, 요청, 응답이 쌓입니다.
          </p>
        ) : (
          newestFirst.map((entry) => <LogEntry key={entry.id} entry={entry} />)
        )}
      </div>
    </section>
  )
}

function LogEntry({ entry }: { entry: ApiLogEntry }) {
  if (entry.kind === "note") {
    return (
      <div className="log-note">
        <time>{entry.time}</time> ※ {entry.message}
      </div>
    )
  }

  const responseText = entry.ok ? formatResponse(entry.response) : ""
  const isLong = responseText.split("\n").length > LONG_RESPONSE_LINES

  return (
    <article className={`log-entry ${entry.ok ? "is-ok" : "is-fail"}`}>
      <header className="log-entry-head">
        <span className="log-feature-id">{entry.featureId}</span>
        <strong>{entry.featureName}</strong>
        <span className="log-badge">{entry.ok ? "성공" : "실패"}</span>
      </header>
      <div className="log-meta">
        <time>{entry.time}</time>
        <span>화면 {entry.screen}</span>
      </div>
      <div className="log-block">
        <span className="log-label">요청</span>
        <pre>{formatRequest(entry.request)}</pre>
      </div>
      {entry.ok ? (
        <details className="log-block" open={!isLong}>
          <summary className="log-label">
            응답{isLong ? " (눌러서 펼치기)" : ""}
          </summary>
          <pre>{responseText}</pre>
        </details>
      ) : (
        <div className="log-block">
          <span className="log-label">실패 사유</span>
          <p className="log-fail-reason">{entry.errorMessage}</p>
        </div>
      )}
      {entry.serverNotes && entry.serverNotes.length > 0 && (
        <div className="log-block">
          <span className="log-label">서버 처리 (응답에는 드러나지 않음)</span>
          <ul className="log-server-notes">
            {entry.serverNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
    </article>
  )
}
