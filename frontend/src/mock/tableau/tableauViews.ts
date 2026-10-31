import { db } from "@/mock/db"
import { GANGNAM_BOUNDARIES } from "@/mock/tableau/gangnamBoundaries"
import type { RiskIndex, RiskStage } from "@/types/domain"
import { boundsOf, insidePolygon, toLonLat, type Polygon } from "@/utils/geo"

// Tableau Public 화면 흉내 (2.1.2 ~ 2.1.3의 지도·그래프 6개)
// 지도·그래프는 Tableau가 자기 데이터(분석 결과를 게시한 파일)로 그리는 부분이라 우리 서버 API가 아니다.
// 화면은 여기서 예시 그림에 쓸 값을 받아 그리고, Tableau에 넘긴 필터·매개변수는 tableauBridge로 API 기록에 메모한다.
// (화면이 db를 직접 읽지 않는다는 규칙의 예외: 이 폴더는 'Tableau 쪽'을 흉내 낸다)

/** 우리 화면이 패널마다 하나씩 넣는 Tableau 화면 (T2-B): 시군구 화면 ①~⑤, 읍면동 화면 ⑥ */
export const TABLEAU_VIEWS = {
  map: "① 시군구 위험도 지도",
  distribution: "② 고립 위험도 분포 변화",
  background: "③ 행정동별 배경 취약성 분포",
  monthly: "④ 월별 행동 이상 지수 변화",
  dongChange: "⑤ 행정동별 전월 대비 행동 이상 지수 변화",
  grid: "⑥ 읍면동 격자 지도",
} as const

/** 격자 한 칸의 크기 (G2-A: 100m) */
export const GRID_SIZE_METERS = 100

export type GridLevel = "low" | "mid" | "high"

export type GridCell = {
  /** 칸의 남서쪽 모서리 (미터 좌표) */
  x: number
  y: number
  level: GridLevel
}

export type StageCounts = Record<RiskStage, number>

export type MapTile = {
  dongCode: string
  dongName: string
  stage: RiskStage
  score: number
  /** 행정동 경계 (Tableau 공간 파일) */
  polygons: Polygon[]
}

export type BackgroundPoint = {
  dongCode: string
  dongName: string
  score: number
  /** 1분위(상위 20%) ~ 5분위(하위 20%) */
  quintile: 1 | 2 | 3 | 4 | 5
  outlier: boolean
}

const emptyCounts = (): StageCounts => ({ 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 })
const round = (value: number, digits = 1) => Math.round(value * 10 ** digits) / 10 ** digits

function dongsOf(sigunguCode: string) {
  return db.dongs.filter((item) => item.sigunguCode === sigunguCode)
}

function rowsOf(sigunguCode: string, month: string) {
  const dongs = dongsOf(sigunguCode)
  return db.dongMonthlyAnalyses
    .filter((item) => item.month === month && dongs.some((dong) => dong.dongCode === item.dongCode))
    .map((item) => ({ ...item, dongName: dongs.find((dong) => dong.dongCode === item.dongCode)?.dongName ?? "" }))
}

function monthsBetween(sigunguCode: string, from: string, to: string): string[] {
  const dongCodes = new Set(dongsOf(sigunguCode).map((item) => item.dongCode))
  return [...new Set(db.dongMonthlyAnalyses.filter((item) => dongCodes.has(item.dongCode)).map((item) => item.month))]
    .filter((month) => month >= from && month <= to)
    .sort()
}

/** 사분위수 (선형 보간) */
function quantile(sorted: number[], ratio: number): number {
  const position = (sorted.length - 1) * ratio
  const lower = Math.floor(position)
  const upper = Math.ceil(position)
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower)
}

function boundaryOf(dongCode: string): Polygon[] {
  return GANGNAM_BOUNDARIES.find((item) => item.dongCode === dongCode)?.polygons ?? []
}

/** 같은 값이 나오는 0~1 난수 (격자 예시 값용) */
function hash(a: number, b: number, c: number): number {
  const value = Math.sin(a * 12.9898 + b * 78.233 + c * 37.719) * 43758.5453
  return value - Math.floor(value)
}

const gridCache = new Map<string, GridCell[]>()

/**
 * ⑥ 격자 예시 값: 동 경계 안을 100m 칸으로 나눠(칸 가운데가 경계 안인 칸만) 칸마다 행동 이상 3단계를 매긴다.
 * 그 동의 행동 이상 단계가 높을수록 '높음' 칸이 많아지고, 이웃한 칸끼리 비슷한 값이 되게 만든다.
 */
function buildGrid(dongCode: string, month: string, behaviorStage: RiskStage): GridCell[] {
  const key = `${dongCode}|${month}`
  const cached = gridCache.get(key)
  if (cached) return cached
  const polygons = boundaryOf(dongCode)
  const bounds = boundsOf(polygons)
  const seed = Number(dongCode.slice(-5)) / 1000
  const monthPhase = Number(month.slice(5)) * 0.35
  const bias = (behaviorStage - 3) * 0.22
  const cells: GridCell[] = []
  const startX = Math.floor(bounds.minX / GRID_SIZE_METERS) * GRID_SIZE_METERS
  const startY = Math.floor(bounds.minY / GRID_SIZE_METERS) * GRID_SIZE_METERS
  for (let x = startX; x < bounds.maxX; x += GRID_SIZE_METERS) {
    for (let y = startY; y < bounds.maxY; y += GRID_SIZE_METERS) {
      const center = toLonLat([x + GRID_SIZE_METERS / 2, y + GRID_SIZE_METERS / 2])
      if (!polygons.some((polygon) => insidePolygon(center, polygon))) continue
      const wave =
        (Math.sin(x / 260 + seed + monthPhase) + Math.sin(y / 330 + seed * 1.7) + Math.sin((x + y) / 190 + monthPhase)) / 3
      const value = wave + (hash(x, y, seed) - 0.5) * 0.5 + bias
      cells.push({ x, y, level: value > 0.32 ? "high" : value > -0.18 ? "mid" : "low" })
    }
  }
  gridCache.set(key, cells)
  return cells
}

export const tableauViews = {
  /** ① 시군구 위험도 지도: 기준 월의 행정동별 단계(경계 포함), 범례의 단계별 행정동 수 */
  map(sigunguCode: string, month: string, index: RiskIndex) {
    const tiles: MapTile[] = rowsOf(sigunguCode, month).map((item) => ({
      dongCode: item.dongCode,
      dongName: item.dongName,
      stage: index === "background" ? item.backgroundStage : item.behaviorStage,
      score: index === "background" ? item.backgroundScore : item.behaviorScore,
      polygons: boundaryOf(item.dongCode),
    }))
    const counts = emptyCounts()
    tiles.forEach((tile) => (counts[tile.stage] += 1))
    return { tiles, counts }
  },

  /** ② 고립 위험도 분포 변화: 기간의 월별 단계별 행정동 수 */
  distribution(sigunguCode: string, from: string, to: string, index: RiskIndex) {
    return monthsBetween(sigunguCode, from, to).map((month) => {
      const counts = emptyCounts()
      const rows = rowsOf(sigunguCode, month)
      rows.forEach((item) => (counts[index === "background" ? item.backgroundStage : item.behaviorStage] += 1))
      return { month, counts, total: rows.length }
    })
  },

  /** ③ 행정동별 배경 취약성 분포: 점(5분위 색), 사분위수·중앙값, 이상값 */
  background(sigunguCode: string, month: string) {
    const rows = rowsOf(sigunguCode, month)
    const sorted = rows.map((item) => item.backgroundScore).sort((a, b) => a - b)
    if (sorted.length === 0) return null
    const q1 = quantile(sorted, 0.25)
    const median = quantile(sorted, 0.5)
    const q3 = quantile(sorted, 0.75)
    const iqr = q3 - q1
    const lowerFence = q1 - 1.5 * iqr
    const upperFence = q3 + 1.5 * iqr
    // 5분위: 높은 값부터 순위를 매겨 상위 20%가 1분위
    const ranked = [...rows].sort((a, b) => b.backgroundScore - a.backgroundScore).map((item) => item.dongCode)
    const points: BackgroundPoint[] = rows.map((item) => ({
      dongCode: item.dongCode,
      dongName: item.dongName,
      score: item.backgroundScore,
      quintile: (Math.floor((ranked.indexOf(item.dongCode) * 5) / rows.length) + 1) as BackgroundPoint["quintile"],
      outlier: item.backgroundScore < lowerFence || item.backgroundScore > upperFence,
    }))
    const inside = sorted.filter((value) => value >= lowerFence && value <= upperFence)
    return {
      points,
      q1: round(q1),
      median: round(median),
      q3: round(q3),
      whiskerLow: inside[0],
      whiskerHigh: inside[inside.length - 1],
    }
  },

  /** ④ 월별 행동 이상 지수 변화: 시군구 지수(행정동 평균)의 전월 대비 변화량, 기간의 첫 월은 기준월(0) */
  monthly(sigunguCode: string, from: string, to: string) {
    const averages = monthsBetween(sigunguCode, from, to).map((month) => {
      const rows = rowsOf(sigunguCode, month)
      return { month, score: rows.reduce((sum, item) => sum + item.behaviorScore, 0) / rows.length }
    })
    return averages.map((item, index) => ({
      month: item.month,
      score: round(item.score, 2),
      change: index === 0 ? 0 : round(item.score - averages[index - 1].score, 2),
    }))
  },

  /** ⑤ 행정동별 전월 대비 행동 이상 지수 변화: 기준 월의 변화량(미리 계산한 값), 증가가 큰 순 */
  dongChange(sigunguCode: string, month: string) {
    const rows = rowsOf(sigunguCode, month)
    if (rows.length === 0 || rows.some((item) => item.behaviorChange === null)) return null
    return rows
      .map((item) => ({ dongCode: item.dongCode, dongName: item.dongName, change: item.behaviorChange ?? 0 }))
      .sort((a, b) => b.change - a.change)
  },

  /** ⑥ 읍면동 격자 지도: 동 경계와 100m 격자별 행동 이상 3단계 (기준 월) */
  grid(dongCode: string, month: string) {
    const row = db.dongMonthlyAnalyses.find((item) => item.dongCode === dongCode && item.month === month)
    const polygons = boundaryOf(dongCode)
    if (!row || polygons.length === 0) return null
    const cells = buildGrid(dongCode, month, row.behaviorStage)
    const counts: Record<GridLevel, number> = { low: 0, mid: 0, high: 0 }
    cells.forEach((cell) => (counts[cell.level] += 1))
    return { polygons, cells, counts }
  },
}
