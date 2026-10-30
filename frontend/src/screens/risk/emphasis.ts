// 인사이트·보고서 문장의 **…** 표시를 굵은 글씨 조각으로 나눈다

export type TextPart = { text: string; strong: boolean }

export function splitEmphasis(text: string): TextPart[] {
  return text
    .split(/\*\*(.+?)\*\*/)
    .map((part, index) => ({ text: part, strong: index % 2 === 1 }))
    .filter((part) => part.text !== "")
}

/** 제목 문장에서 '상승'·'하락'을 색으로 강조하려고 나눈다 */
export function splitDirection(text: string): { text: string; direction: "up" | "down" | null }[] {
  return text
    .split(/(상승|하락)/)
    .filter((part) => part !== "")
    .map((part) => ({ text: part, direction: part === "상승" ? "up" : part === "하락" ? "down" : null }))
}
