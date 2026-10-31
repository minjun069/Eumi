import { addLogNote } from "@/devtools/apiLogStore"

// 우리 화면 → Tableau Public 화면으로 넘기는 값과 Tableau에서 받는 이벤트를 API 기록에 메모로 남긴다.
// 실제 개발에서는 Embedding API v3로 넘긴다:
// - 필터: viz.workbook.activeSheet.applyFilterAsync(필드, 값) / 처음 띄울 때 <viz-filter>
// - 매개변수: viz.workbook.changeParameterValueAsync(이름, 값) / 처음 띄울 때 <viz-parameter>
// - 행정동 선택: markselectionchanged 이벤트 (Tableau Public에서 되는지 개발 전에 확인 필요)

export function noteTableau(title: string, lines: string[]) {
  addLogNote([`Tableau ${title}`, ...lines.map((line) => `- ${line}`)].join("\n"))
}
