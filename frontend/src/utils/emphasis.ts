// 문장의 **…** 표시를 굵은 글씨 조각으로 나눈다 (AI 답변·인사이트·보고서 공통).
// 허용한 강조 문법만 해석하고 HTML은 해석하지 않는다 (NFR-SEC-05).

export type TextPart = { text: string; strong: boolean }

export function splitEmphasis(text: string): TextPart[] {
  return text
    .split(/\*\*(.+?)\*\*/)
    .map((part, index) => ({ text: part, strong: index % 2 === 1 }))
    .filter((part) => part.text !== "")
}
