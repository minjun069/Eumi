import type { RiskStage } from "@/types/domain"

// 고립 위험 탐색 예시 그림의 색·이름 (Tableau에서 정할 값을 비슷하게 흉내 냄)

export const STAGES: RiskStage[] = [5, 4, 3, 2, 1]

export const STAGE_LABELS: Record<RiskStage, string> = {
  5: "매우 높음",
  4: "높음",
  3: "중간",
  2: "낮음",
  1: "매우 낮음",
}

export const STAGE_COLORS: Record<RiskStage, string> = {
  5: "#c62828",
  4: "#ef5b3e",
  3: "#f7963e",
  2: "#fbd25b",
  1: "#fdecb3",
}

/** 칸 위 글자색 (진한 칸은 흰 글자) */
export const STAGE_TEXT: Record<RiskStage, string> = {
  5: "#ffffff",
  4: "#ffffff",
  3: "#3d2a12",
  2: "#3d3412",
  1: "#4a4220",
}

/** 배경 취약성 5분위 색 (1분위 = 상위 20%) */
export const QUINTILE_COLORS: Record<1 | 2 | 3 | 4 | 5, string> = {
  1: "#1f3a93",
  2: "#2f5fc4",
  3: "#5b86d9",
  4: "#8fb0e8",
  5: "#c3d5f3",
}

export const INCREASE_COLOR = "#e53935"
export const DECREASE_COLOR = "#1e6fd9"

/** ⑥ 격자 행동 이상 3단계 색·이름 */
export const GRID_LEVELS = [
  { level: "low", label: "낮음", color: "#fde68a" },
  { level: "mid", label: "중간", color: "#f9a03f" },
  { level: "high", label: "높음", color: "#ef4444" },
] as const
