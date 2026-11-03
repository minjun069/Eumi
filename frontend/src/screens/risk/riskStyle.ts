// 위험 단계 표시 (읍면동 요약 배지, 보고서 추이 그래프의 월별 단계).
// TODO(분석 담당): 단계 1~5의 의미·이름은 아직 확정되지 않았다 (프로토타입_기능_상세_계약.md 대시보드 절).
// 지금은 프로토타입의 이름·색을 표시용으로만 쓰고, 점수로 단계를 다시 매기지 않는다 (서버가 준 stage 그대로)

const STAGE_LABELS: Record<number, string> = {
  5: "매우 높음",
  4: "높음",
  3: "중간",
  2: "낮음",
  1: "매우 낮음",
}

const STAGE_COLORS: Record<number, string> = {
  5: "#c62828",
  4: "#ef5b3e",
  3: "#f7963e",
  2: "#fbd25b",
  1: "#fdecb3",
}

/** 칸 위 글자색 (진한 칸은 흰 글자) */
const STAGE_TEXT: Record<number, string> = {
  5: "#ffffff",
  4: "#ffffff",
  3: "#3d2a12",
  2: "#3d3412",
  1: "#4a4220",
}

/** 1~5 밖의 값이 오면 이름 없이 회색으로 보인다 */
export function stageStyle(stage: number): { label: string | null; background: string; color: string } {
  return {
    label: STAGE_LABELS[stage] ?? null,
    background: STAGE_COLORS[stage] ?? "#e5e7eb",
    color: STAGE_TEXT[stage] ?? "#374151",
  }
}
