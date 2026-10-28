import type { ApiLogEntry } from "@/devtools/apiLogStore"
import { labelOf } from "@/mock/fieldLabels"

// API 기록을 사람이 읽는 텍스트로 바꾼다. 화면 표시와 '전체 복사'가 같은 형식을 쓴다.
// 객체의 항목 이름은 "한글(영문)"으로 표시한다.

export function formatValue(value: unknown, indent = 0): string {
  const pad = "  ".repeat(indent)
  if (value === undefined) return "undefined"
  if (value === null) return "null"
  if (typeof value === "string") return JSON.stringify(value)
  if (typeof value === "number" || typeof value === "boolean")
    return String(value)
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]  // 0건"
    const items = value
      .map((item) => `${pad}  ${formatValue(item, indent + 1)}`)
      .join(",\n")
    return `[  // ${value.length}건\n${items}\n${pad}]`
  }
  if (typeof value === "object") {
    const fields = Object.entries(value as Record<string, unknown>)
    if (fields.length === 0) return "{}"
    const lines = fields
      .map(
        ([key, item]) =>
          `${pad}  ${labelOf(key)}: ${formatValue(item, indent + 1)}`,
      )
      .join(",\n")
    return `{\n${lines}\n${pad}}`
  }
  return String(value)
}

export function formatRequest(request: unknown): string {
  if (
    request &&
    typeof request === "object" &&
    Object.keys(request).length === 0
  ) {
    return "(보내는 값 없음)"
  }
  return formatValue(request)
}

export function formatResponse(response: unknown): string {
  if (response === undefined) return "(받는 값 없음)"
  return formatValue(response)
}

export function formatEntry(entry: ApiLogEntry): string {
  if (entry.kind === "note") return `[${entry.time}] ※ ${entry.message}`
  const head = `[${entry.time}] ${entry.featureId} ${entry.featureName} — ${
    entry.ok ? "성공" : "실패"
  } (화면: ${entry.screen})`
  const request = `요청:\n${formatRequest(entry.request)}`
  const result = entry.ok
    ? `응답:\n${formatResponse(entry.response)}`
    : `실패 사유: ${entry.errorMessage ?? ""}`
  const notes = entry.serverNotes?.length
    ? `서버 처리:\n${entry.serverNotes.map((note) => `- ${note}`).join("\n")}`
    : null
  return [head, request, result, notes].filter(Boolean).join("\n")
}

/** '전체 복사'용. 읽기 쉽도록 오래된 기록부터 순서대로 이어 붙인다 */
export function formatAll(entries: ApiLogEntry[]): string {
  return entries.map(formatEntry).join("\n\n")
}
