import { seedDongMonthlyAnalyses } from "@/mock/seed/analysis"
import { seedDongs, seedSigungus } from "@/mock/seed/regions"
import type {
  DongInsight,
  DongMonthlyAnalysis,
  InsightReport,
  ReportBlock,
  ReportChart,
  ReportSection,
} from "@/types/domain"

// 읍면동 인사이트·인사이트 보고서 예시 (2.1.3·2.1.4).
// 실제로는 월 데이터를 적재할 때 AI가 행정동·월마다 만들어 DB에 저장한다 (1차는 미리 만든 내용을 DB에 직접 넣음).
// - 개포1동 2025-12: V1 인사이트 보고서 내용 그대로 ('등급'은 '단계'로 바꿈)
// - 그 밖의 행정동·월: 분석 값으로 채운 틀 문장 (예시)
// - 세곡동 2025-12: 아직 만들지 못한 상태 (인사이트·보고서 모두 없음)

const GAEPO1 = "1168066000"
/** 인사이트·보고서가 없는 행정동·월 */
export const MISSING_INSIGHT = { dongCode: "1168070000", month: "2025-12" }

const DAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
const TEMPLATE_FACTORS = [
  "주말·주중 활동 차이",
  "요일별 활동 패턴의 고정성",
  "요일 간 활동 편차",
  "60대 이상 여성 활동",
  "하루 활동 시간",
  "시간대별 활동 패턴",
]
const OTHER_FACTORS = "기타 4개 지표"

const round = (value: number, digits = 2) => Math.round(value * 10 ** digits) / 10 ** digits
const signed = (value: number, digits = 1) => `${value > 0 ? "+" : ""}${value.toFixed(digits)}`
const monthNumber = (month: string) => Number(month.slice(5))
const koreanMonth = (month: string) => `${month.slice(0, 4)}년 ${monthNumber(month)}월`

/** 같은 값이 나오는 간단한 난수 */
function random(seed: number) {
  let value = seed
  return () => {
    value = (value * 1103515245 + 12345) % 2147483648
    return value / 2147483648
  }
}

function quantile(sorted: number[], ratio: number): number {
  const position = (sorted.length - 1) * ratio
  const lower = Math.floor(position)
  const upper = Math.ceil(position)
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower)
}

/** 분석을 마친 다음 달 5일 오전 9시에 만들었다고 가정 */
function generatedAtOf(month: string): string {
  const year = Number(month.slice(0, 4))
  const next = monthNumber(month) === 12 ? `${year + 1}-01` : `${year}-${String(monthNumber(month) + 1).padStart(2, "0")}`
  return `${next}-05 09:00:00`
}

function dongNameOf(dongCode: string) {
  return seedDongs.find((item) => item.dongCode === dongCode)?.dongName ?? ""
}

function sigunguNameOf(dongCode: string) {
  return seedSigungus.find((item) => item.sigunguCode === dongCode.slice(0, 5))?.sigunguName ?? ""
}

/** 같은 시군구·같은 월의 행정동들 (행동 이상 지수 높은 순) */
function peersOf(row: DongMonthlyAnalysis) {
  return seedDongMonthlyAnalyses
    .filter((item) => item.month === row.month && item.dongCode.slice(0, 5) === row.dongCode.slice(0, 5))
    .sort((a, b) => b.behaviorScore - a.behaviorScore)
}

function rankOf(row: DongMonthlyAnalysis) {
  return peersOf(row).findIndex((item) => item.dongCode === row.dongCode) + 1
}

/** 행동 이상 지수 추이: 적재된 첫 월부터 이 달까지 */
function trendChart(row: DongMonthlyAnalysis): ReportChart {
  const rows = seedDongMonthlyAnalyses
    .filter((item) => item.dongCode === row.dongCode && item.month <= row.month)
    .sort((a, b) => a.month.localeCompare(b.month))
  return {
    type: "trend",
    heading: `행동 이상 지수 추이 (${sigunguNameOf(row.dongCode)} ${peersOf(row).length}개 동과 비교)`,
    total: peersOf(row).length,
    points: rows.map((item) => {
      const sorted = peersOf(item)
        .map((peer) => peer.behaviorScore)
        .sort((a, b) => a - b)
      return {
        month: item.month,
        score: item.behaviorScore,
        stage: item.behaviorStage,
        rank: rankOf(item),
        median: round(quantile(sorted, 0.5)),
        q1: round(quantile(sorted, 0.25)),
        q3: round(quantile(sorted, 0.75)),
      }
    }),
  }
}

function weekdayChart(month: string, previous: number[], changes: number[]): ReportChart {
  const prevMonth = monthNumber(month) === 1 ? 12 : monthNumber(month) - 1
  return {
    type: "weekday",
    heading: "요일별 일평균 활동 인구",
    caption: `막대 위 숫자 = ${monthNumber(month)}월 변화율`,
    unit: "명",
    days: DAYS,
    series: [
      { label: `${prevMonth}월`, values: previous },
      { label: `${monthNumber(month)}월`, values: previous.map((value, index) => Math.round(value * (1 + changes[index] / 100))) },
    ],
    changes,
  }
}

const paragraph = (text: string): ReportBlock => ({ kind: "paragraph", text })
const chart = (value: ReportChart): ReportBlock => ({ kind: "chart", chart: value })
const bullets = (items: { label: string; text: string }[]): ReportBlock => ({ kind: "bullets", items })

// ── 개포1동 2025-12 (V1 내용) ──

function gaepo1December(row: DongMonthlyAnalysis): { insight: DongInsight; report: InsightReport } {
  const generatedAt = generatedAtOf(row.month)
  return {
    insight: {
      dongCode: row.dongCode,
      month: row.month,
      summary: [
        "개포1동의 위험은 **주말·저녁**에 조용해진 동네에 **고령층만 남는 생활 리듬**에서 나와요.",
        "12월 **주말 활동이 주중보다 두 배 가까이 더 줄었고** 동네 활동의 **26%가 60대 이상**이니, 60대 이상 어르신부터 먼저 살펴보는 게 효과적이에요.",
      ],
      generatedAt,
    },
    report: {
      dongCode: row.dongCode,
      month: row.month,
      headline: "개포1동의 행동이상 점수가 전월대비 3.4점 상승했어요.",
      sections: [
        { question: null, blocks: [chart(trendChart(row))] },
        {
          question: "주요 원인이 뭔가요?",
          blocks: [
            paragraph("주말 활동량이 줄어들고 요일 간 활동 편차가 확대된 것이 주된 원인이에요."),
            chart({
              type: "factors",
              heading: "전월 대비 점수 변화 요인",
              items: [
                { label: "주말 활동이 주중보다 더 줄어듦", value: 1.63 },
                { label: "요일별 활동 패턴이 평소보다 고정적", value: 0.97 },
                { label: "요일 간 활동 편차 확대", value: 0.47 },
                { label: "60대 이상 여성 활동이 남성보다 더 감소", value: 0.36 },
                { label: "하루 활동이 더 짧아짐", value: 0.18 },
                { label: "시간대별 활동 패턴 변화", value: 0.16 },
                { label: OTHER_FACTORS, value: 0.01 },
              ],
            }),
            paragraph("그 중 주말 활동량이 주중에 비해 눈에 띄게 줄어들면서, 동네의 평소 요일 리듬이 달라졌어요."),
            chart(
              weekdayChart(row.month, [88000, 90000, 89000, 87000, 89000, 62000, 58000], [-6.3, -4.5, -2.8, -4.5, -3.0, -7.5, -6.8]),
            ),
          ],
        },
        {
          question: "왜 이런 변화가 생겼나요?",
          blocks: [
            bullets([
              {
                label: "날씨와 시기",
                text: "12월의 매서운 한파와 연말이라는 특성 탓에, 가족 단위 주민들의 야외 활동이 크게 줄어든 것이 가장 유력한 이유예요.",
              },
              {
                label: "지역 특성",
                text: "개포1동은 외부 인구 유입이 거의 없는 '순수 주거지'라서 거주민의 활동 감소가 지표에 훨씬 더 극단적으로 드러났어요.",
              },
            ]),
            chart({
              type: "compare",
              heading: "주민 대비 활동량 (외부 유입)",
              items: [
                { label: "개포1동", value: 0.12, highlight: true },
                { label: "강남 22개 동 중앙값", value: 0.44, highlight: false },
              ],
            }),
            bullets([
              {
                label: "잠재적 위험",
                text: "동네의 배경적인 지표는 안전해 보이지만, 관내 75세 이상 어르신 10명 중 3명이 혼자 살고 계셔서 특별한 주의가 필요해요.",
              },
            ]),
            chart({ type: "ratio", count: 3, total: 10, caption: "75세 이상 어르신 10명 중 3명이 혼자 살아요" }),
          ],
        },
        {
          question: "앞으로 어떤 조치를 해야 할까요?",
          blocks: [
            bullets([
              {
                label: "정확한 타겟 확인",
                text: "대대적인 조사보다는 취약 가구를 빠르게 확인하는 게 먼저예요! 75세 이상 독거 어르신 중 11월에 돌봄 서비스가 종료된 가구를 한파가 오기 전에 파악해서, 'AI 안부전화'나 '스마트플러그' 관리 대상에 신속히 편입해 주세요.",
              },
              {
                label: "데이터 모니터링",
                text: "1월 데이터에서 주말 활동량이 원래대로 돌아오면 상황을 종결해도 좋아요. 하지만 행동이상 4단계가 계속 유지된다면 해당 지역을 '우선 검토 구역'으로 지정하는 것을 권장해 드려요.",
              },
            ]),
          ],
        },
      ],
      generatedAt,
    },
  }
}

// ── 그 밖의 행정동·월 (틀 문장) ──

function templateInsight(row: DongMonthlyAnalysis): DongInsight {
  const name = dongNameOf(row.dongCode)
  const total = peersOf(row).length
  const change = row.behaviorChange
  const summary = [
    `${name}의 행동 이상 지수는 **${row.behaviorScore.toFixed(1)}점(${row.behaviorStage}단계)**으로 ${sigunguNameOf(row.dongCode)} ${total}개 동 중 ${rankOf(row)}위예요.`,
    change === null
      ? `${koreanMonth(row.month)}이 첫 적재 월이라 전월과 비교한 변화는 다음 달부터 볼 수 있어요.`
      : change >= 1
        ? `전월보다 **${change.toFixed(1)}점 올라** 점수를 올린 요인을 먼저 살펴보는 게 좋아요.`
        : change <= -1
          ? `전월보다 ${Math.abs(change).toFixed(1)}점 내려 안정되는 흐름이에요.`
          : `전월과 비슷한 수준(${signed(change)}점)이에요.`,
    row.backgroundStage >= 4
      ? `배경 취약성도 **${row.backgroundStage}단계**로 높아 고령·1인 가구 등 취약 가구를 함께 살펴보세요.`
      : `배경 취약성은 ${row.backgroundStage}단계(${row.backgroundScore.toFixed(1)}점)예요.`,
  ]
  return { dongCode: row.dongCode, month: row.month, summary, generatedAt: generatedAtOf(row.month) }
}

/**
 * 전월 대비 변화량을 요인 7개로 나눈다 (합계 = 변화량).
 * 몇 개는 반대 방향(점수를 내린/올린 요인)으로 두고, '기타'는 변화량의 1% 정도.
 */
function templateFactors(change: number, next: () => number) {
  const amount = Math.abs(change)
  const direction = change >= 0 ? 1 : -1
  const picks = TEMPLATE_FACTORS.map((label, index) => ({
    label,
    weight: 0.2 + next() * 0.8,
    opposite: index >= 2 && next() < 0.3,
  }))
  if (amount < 0.5 && !picks.some((item) => item.opposite)) picks[picks.length - 1].opposite = true
  const positives = picks.filter((item) => !item.opposite)
  const negatives = picks.filter((item) => item.opposite)
  const weightOf = (list: typeof picks) => list.reduce((sum, item) => sum + item.weight, 0)
  const offset = negatives.length > 0 ? Math.max(amount * 0.25, 0.3) : 0
  const main = amount * 0.99 + offset
  const items = picks.map((item) => ({
    label: item.label,
    value: round(
      direction *
        (item.opposite ? -(item.weight / weightOf(negatives)) * offset : (item.weight / weightOf(positives)) * main),
    ),
  }))
  const rest = round(change - items.reduce((sum, item) => sum + item.value, 0))
  // 변화 방향으로 영향이 큰 순서 (반대 방향 요인은 아래쪽)
  items.sort((a, b) => direction * (b.value - a.value))
  return [...items, { label: OTHER_FACTORS, value: rest }]
}

function templateReport(row: DongMonthlyAnalysis, seed: number): InsightReport {
  const name = dongNameOf(row.dongCode)
  const change = row.behaviorChange
  const next = random(seed)
  const headline =
    change === null
      ? `${name}의 ${koreanMonth(row.month)} 행동이상 점수는 ${row.behaviorScore.toFixed(1)}점이에요.`
      : Math.abs(change) < 0.5
        ? `${name}의 행동이상 점수가 전월과 비슷했어요.`
        : `${name}의 행동이상 점수가 전월대비 ${Math.abs(change).toFixed(1)}점 ${change > 0 ? "상승" : "하락"}했어요.`

  const sections: ReportSection[] = [{ question: null, blocks: [chart(trendChart(row))] }]

  if (change !== null) {
    const factors = templateFactors(change, next)
    const top = factors[0]
    const base = 50000 + Math.round(next() * 60) * 1000
    const previous = DAYS.map((_, index) => Math.round((base * (index >= 5 ? 0.68 : 1) * (0.97 + next() * 0.06)) / 100) * 100)
    const changes = DAYS.map((_, index) => round(-change * 1.1 * (index >= 5 ? 1.6 : 1) + (next() - 0.5) * 2, 1))
    const weekdayAverage = round(changes.slice(0, 5).reduce((sum, value) => sum + value, 0) / 5, 1)
    const weekendAverage = round((changes[5] + changes[6]) / 2, 1)
    sections.push({
      question: "주요 원인이 뭔가요?",
      blocks: [
        paragraph(
          Math.abs(change) < 0.5
            ? "여러 요인이 서로 상쇄되어 점수 변화가 작았어요."
            : `점수를 가장 많이 ${change > 0 ? "올린" : "내린"} 요인은 '${top.label}'(${signed(top.value, 2)})이에요.`,
        ),
        chart({ type: "factors", heading: "전월 대비 점수 변화 요인", items: factors }),
        paragraph(`요일별로 보면 주중은 평균 ${signed(weekdayAverage)}%, 주말은 평균 ${signed(weekendAverage)}% 달라졌어요.`),
        chart(weekdayChart(row.month, previous, changes)),
      ],
    })
  }

  sections.push({
    question: "앞으로 어떤 조치를 해야 할까요?",
    blocks: [
      bullets(
        row.behaviorStage >= 4
          ? [
              {
                label: "우선 확인",
                text: `행동 이상 ${row.behaviorStage}단계인 만큼, 75세 이상 독거 어르신 등 관리 중인 가구의 안부를 먼저 확인해 주세요.`,
              },
              {
                label: "데이터 모니터링",
                text: `다음 달에도 ${row.behaviorStage}단계 이상이 이어지면 '우선 검토 구역'으로 지정하는 것을 권장해요.`,
              },
            ]
          : row.behaviorStage === 3
            ? [{ label: "데이터 모니터링", text: "중간 단계예요. 다음 달 점수가 더 오르는지 지켜봐 주세요." }]
            : [{ label: "현재 상태 유지", text: "위험이 낮은 편이에요. 지금의 돌봄 서비스를 그대로 이어가면 돼요." }],
      ),
    ],
  })

  return { dongCode: row.dongCode, month: row.month, headline, sections, generatedAt: generatedAtOf(row.month) }
}

function build() {
  const insights: DongInsight[] = []
  const reports: InsightReport[] = []
  seedDongMonthlyAnalyses.forEach((row, index) => {
    if (row.dongCode === MISSING_INSIGHT.dongCode && row.month === MISSING_INSIGHT.month) return
    if (row.dongCode === GAEPO1 && row.month === "2025-12") {
      const { insight, report } = gaepo1December(row)
      insights.push(insight)
      reports.push(report)
      return
    }
    insights.push(templateInsight(row))
    reports.push(templateReport(row, index * 4099 + 11))
  })
  return { insights, reports }
}

const built = build()

export const seedDongInsights: DongInsight[] = built.insights
export const seedInsightReports: InsightReport[] = built.reports
