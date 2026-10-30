import type { DongMonthlyAnalysis, RiskStage } from "@/types/domain"

// 고립 위험 분석 결과 예시 (2.1). 강남구 22개 동 × 2025-07 ~ 2025-12 (R6·R7).
// 값은 프로토타입용 가상 값이며, V1 대시보드 그림과 비슷한 모양이 되도록 맞췄다.
// - 12월 전월 대비 행동 이상 지수 변화: V1 '행정동별 전월 대비 행동 지수 변화' 그림의 값
// - 개포1동 행동 이상 지수: V1 인사이트 보고서의 추이(8월 56.1 → 12월 55.6, 전월 대비 +3.4)
// - 단계: 점수 구간(고정 기준)으로 매긴다. 시군구 안 5분위로 매기면 매달 단계별 행정동 수가 같아져
//   '고립 위험도 분포 변화(2.1.3)'가 늘 같은 모양이 되기 때문. 아래 기준은 예시이며 실제 기준은 분석 담당이 정한다.

export const ANALYSIS_MONTHS = ["2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]

/** 행정동 코드 → [12월 배경 취약성 지수, 12월 행동 이상 지수, 12월 전월 대비 행동 이상 변화] */
const GANGNAM_DECEMBER: Record<string, [number, number, number]> = {
  "1168051000": [25.5, 53.2, 1.7], // 신사동
  "1168052100": [26.4, 49.6, -0.2], // 논현1동
  "1168053100": [37.2, 52.8, 0.4], // 논현2동
  "1168054500": [38.6, 54.9, 1.9], // 압구정동
  "1168056500": [30.5, 47.3, -1.2], // 청담동
  "1168058000": [36.4, 51.1, 0.4], // 삼성1동
  "1168059000": [29.9, 48.8, -0.1], // 삼성2동
  "1168060000": [35.9, 46.2, -1.6], // 대치1동
  "1168061000": [31.8, 50.4, 0.5], // 대치2동
  "1168063000": [27.8, 44.6, -4.1], // 대치4동
  "1168064000": [44.8, 52.1, 0.4], // 역삼1동
  "1168065000": [35.3, 47.9, -1.3], // 역삼2동
  "1168065500": [23.6, 60.3, 5.2], // 도곡1동
  "1168065600": [29.7, 58.7, 4.3], // 도곡2동
  "1168066000": [24.51, 55.57, 3.4], // 개포1동
  "1168067000": [0.2, 45.8, -1.3], // 개포2동 (배경 취약성 이상값)
  "1168067500": [33.0, 46.9, -2.1], // 개포3동
  "1168069000": [21.9, 54.1, 2.0], // 개포4동
  "1168072000": [22.8, 47.4, -1.5], // 일원본동
  "1168073000": [20.4, 46.5, -1.6], // 일원1동
  "1168075000": [42.1, 49.2, -0.7], // 수서동
  "1168070000": [18.7, 53.6, 0.9], // 세곡동
}

/** 개포1동 행동 이상 지수 (V1 인사이트 보고서 그래프와 같게) */
const GAEPO1_BEHAVIOR = [55.0, 56.1, 58.9, 54.9, 52.2, 55.57]

/** 같은 값이 나오는 간단한 난수 (예시 데이터를 매번 같게 만들려고 씀) */
function random(seed: number) {
  let value = seed
  return () => {
    value = (value * 1103515245 + 12345) % 2147483648
    return value / 2147483648
  }
}

const round = (value: number, digits = 2) => Math.round(value * 10 ** digits) / 10 ** digits

/** 단계 기준 (예시): 이 점수 이상이면 그 단계. [5단계, 4단계, 3단계, 2단계] 하한 */
export const STAGE_CUTOFFS = {
  background: [40, 35, 30, 22],
  behavior: [59, 55, 52.5, 49],
}

function stageOf(score: number, cutoffs: number[]): RiskStage {
  const index = cutoffs.findIndex((cutoff) => score >= cutoff)
  return (index === -1 ? 1 : 5 - index) as RiskStage
}

function buildGangnam(): DongMonthlyAnalysis[] {
  const dongCodes = Object.keys(GANGNAM_DECEMBER)
  const monthCount = ANALYSIS_MONTHS.length
  // 행정동별 월 값 만들기
  const series = dongCodes.map((dongCode, dongIndex) => {
    const [background12, behavior12, change12] = GANGNAM_DECEMBER[dongCode]
    const next = random(dongIndex * 7919 + 17)
    let behavior: number[]
    if (dongCode === "1168066000") {
      behavior = GAEPO1_BEHAVIOR
    } else {
      behavior = new Array(monthCount)
      behavior[monthCount - 1] = behavior12
      behavior[monthCount - 2] = behavior12 - change12
      for (let month = monthCount - 3; month >= 0; month -= 1) {
        const change = round((next() - 0.5) * 4.8, 1)
        behavior[month] = behavior[month + 1] - change
      }
    }
    const drift = (next() - 0.5) * 3
    const background = ANALYSIS_MONTHS.map((_, month) =>
      Math.max(0, background12 + (drift * (monthCount - 1 - month)) / (monthCount - 1)),
    )
    return { dongCode, behavior: behavior.map((value) => round(value)), background: background.map((value) => round(value)) }
  })

  return ANALYSIS_MONTHS.flatMap((month, monthIndex) =>
    series.map((item) => ({
      dongCode: item.dongCode,
      month,
      backgroundScore: item.background[monthIndex],
      backgroundStage: stageOf(item.background[monthIndex], STAGE_CUTOFFS.background),
      behaviorScore: item.behavior[monthIndex],
      behaviorStage: stageOf(item.behavior[monthIndex], STAGE_CUTOFFS.behavior),
      behaviorChange:
        monthIndex === 0 ? null : round(item.behavior[monthIndex] - item.behavior[monthIndex - 1], 1),
    })),
  )
}

export const seedDongMonthlyAnalyses: DongMonthlyAnalysis[] = buildGangnam()
