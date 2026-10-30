import { db } from "@/mock/db"
import { ApiError, callApi, serverNote } from "@/mock/api/core"
import type { DongMonthlyAnalysis, InsightReport, RiskStage } from "@/types/domain"

// 2. ANALYSIS 고립 위험 탐색 (2.1)
// 지도·그래프는 Tableau가 그리므로 우리 서버 API가 아니다 (src/mock/tableau).
// 여기에는 화면이 직접 부르는 API만 둔다.

export const DONG_NOT_FOUND_MESSAGE = "행정동을 찾을 수 없습니다."
export const NO_ANALYSIS_MESSAGE = "분석 결과가 없는 월입니다."

export type DongInsightResponse = {
  dongCode: string
  dongName: string
  sigunguCode: string
  sigunguName: string
  month: string
  background: { score: number; stage: RiskStage }
  behavior: { score: number; stage: RiskStage }
  /** 아직 만들지 못했으면 null */
  insight: { summary: string[]; generatedAt: string } | null
}

export type InsightReportResponse = {
  /** 아직 만들지 못했으면 null */
  report: Omit<InsightReport, "dongCode" | "month"> | null
}

/** 읍면동 화면 API 공통: 행정동·월 확인 후 그 달 분석 결과 */
function findAnalysis(dongCode: string, month: string): DongMonthlyAnalysis {
  if (!db.dongs.some((item) => item.dongCode === dongCode)) throw new ApiError(DONG_NOT_FOUND_MESSAGE)
  const analysis = db.dongMonthlyAnalyses.find((item) => item.dongCode === dongCode && item.month === month)
  if (!analysis) throw new ApiError(NO_ANALYSIS_MESSAGE)
  return analysis
}

export const analysisApi = {
  /**
   * 2.1.1 적재된 월 목록 조회: 기간 필터의 선택지와 처음 값(적재된 전체 기간).
   * 시군구마다 적재된 기간이 다를 수 있어 시군구 코드를 받는다. 데이터가 없으면 빈 목록.
   */
  getLoadedMonths(request: { sigunguCode: string }) {
    return callApi(
      { featureId: "2.1.1", featureName: "적재된 월 목록 조회" },
      request,
      ({ sigunguCode }): { months: string[] } => {
        if (!db.sigungus.some((item) => item.sigunguCode === sigunguCode)) {
          throw new ApiError("시군구를 찾을 수 없습니다.")
        }
        const dongCodes = new Set(
          db.dongs.filter((item) => item.sigunguCode === sigunguCode).map((item) => item.dongCode),
        )
        const months = [
          ...new Set(db.dongMonthlyAnalyses.filter((item) => dongCodes.has(item.dongCode)).map((item) => item.month)),
        ].sort()
        serverNote(
          months.length > 0
            ? "이 시군구에 분석 결과가 적재된 월만 오래된 순으로 돌려줌"
            : "이 시군구에는 적재된 분석 결과가 없어 빈 목록을 돌려줌",
        )
        return { months }
      },
    )
  },
  /**
   * 2.1.3 읍면동 인사이트 조회: 읍면동 화면 왼쪽의 위험도 요약(배경 취약성·행동 이상 점수와 단계)과 인사이트.
   * 인사이트는 월 데이터를 적재할 때 AI가 만들어 저장한 내용 (기준 월 = 선택한 기간의 마지막 월).
   */
  getDongInsight(request: { dongCode: string; month: string }) {
    return callApi(
      { featureId: "2.1.3", featureName: "읍면동 인사이트 조회" },
      request,
      ({ dongCode, month }): DongInsightResponse => {
        const analysis = findAnalysis(dongCode, month)
        const dong = db.dongs.find((item) => item.dongCode === dongCode)!
        const sigungu = db.sigungus.find((item) => item.sigunguCode === dong.sigunguCode)
        const insight = db.dongInsights.find((item) => item.dongCode === dongCode && item.month === month)
        serverNote("행정동·기준 월의 분석 결과(점수·단계)와 저장해 둔 인사이트를 함께 돌려줌")
        if (!insight) serverNote("이 달의 인사이트가 아직 만들어지지 않아 인사이트는 null")
        return {
          dongCode,
          dongName: dong.dongName,
          sigunguCode: dong.sigunguCode,
          sigunguName: sigungu?.sigunguName ?? "",
          month,
          background: { score: analysis.backgroundScore, stage: analysis.backgroundStage },
          behavior: { score: analysis.behaviorScore, stage: analysis.behaviorStage },
          insight: insight ? { summary: insight.summary, generatedAt: insight.generatedAt } : null,
        }
      },
    )
  },

  /**
   * 2.1.4 인사이트 보고서 조회: 읍면동 화면 오른쪽 보고서. 질문별로 문장·목록·그래프 블록이 들어 있고,
   * 그래프는 화면이 그린다 (보고서를 만들 때 그래프 값까지 함께 저장).
   */
  getInsightReport(request: { dongCode: string; month: string }) {
    return callApi(
      { featureId: "2.1.4", featureName: "인사이트 보고서 조회" },
      request,
      ({ dongCode, month }): InsightReportResponse => {
        findAnalysis(dongCode, month)
        const report = db.insightReports.find((item) => item.dongCode === dongCode && item.month === month)
        if (!report) {
          serverNote("이 달의 인사이트 보고서가 아직 만들어지지 않아 null")
          return { report: null }
        }
        serverNote("저장해 둔 보고서(그래프 값 포함)를 그대로 돌려줌")
        return {
          report: { headline: report.headline, sections: report.sections, generatedAt: report.generatedAt },
        }
      },
    )
  },
}
