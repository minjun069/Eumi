import { api } from "@/api/http"
import type { SuccessData } from "@/api/types"

// 고립 위험 탐색의 서버 API. 지도·그래프는 Tableau가 그리고, 여기서는 적재된 월·읍면동 요약·보고서만 받는다

export type LoadedMonths = SuccessData<"analysisApi_getLoadedMonths_Success">
export type DongInsight = SuccessData<"analysisApi_getDongInsight_Success">
export type InsightReportData = SuccessData<"analysisApi_getInsightReport_Success">
export type InsightReport = NonNullable<InsightReportData["report"]>

export const analysisKeys = {
  months: (sigunguCode: string) => ["analysis", "months", sigunguCode] as const,
  insight: (dongCode: string, month: string) => ["analysis", "insight", dongCode, month] as const,
  report: (dongCode: string, month: string) => ["analysis", "report", dongCode, month] as const,
}

const dongPath = (dongCode: string) => `/analysis/dongs/${encodeURIComponent(dongCode)}`

export const analysisApi = {
  /** API-10 GET /analysis/sigungus/{sigunguCode}/months — 오래된 월부터. 적재된 결과가 없으면 months=[] */
  getLoadedMonths: (sigunguCode: string) =>
    api.get<LoadedMonths>(`/analysis/sigungus/${encodeURIComponent(sigunguCode)}/months`),

  /** API-11 GET /analysis/dongs/{dongCode}/insight — 결과 없음은 404, 인사이트를 아직 만들지 않았으면 insight=null */
  getDongInsight: (dongCode: string, month: string) =>
    api.get<DongInsight>(`${dongPath(dongCode)}/insight`, { query: { month } }),

  /** API-12 GET /analysis/dongs/{dongCode}/report — 결과 없음은 404, 보고서를 아직 만들지 않았으면 report=null */
  getInsightReport: (dongCode: string, month: string) =>
    api.get<InsightReportData>(`${dongPath(dongCode)}/report`, { query: { month } }),
}
