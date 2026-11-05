// Tableau Public 게시본 설정. 화면 자리마다 임베드용 대시보드가 있다.
// - 메인 화면 ①②③⑤: 메인 워크북(eumi_tableau_main_dashboard_v_master)
// - 읍면동 상세 ⑥: 상세 워크북(eumi_tableau_main_dashboard_v2_0_6_connection_map_fixed, 11/5 이지석 게시)
// 지도·그래프는 서비스 API가 아니라 Tableau Embedding API v3로 띄우고, 자리마다 그 대시보드를 하나씩 띄운다.
// 게시본이 없는 자리는 '준비 중'으로 두고 다른 뷰를 대신 넣지 않는다.
// 기준 문서: fe-ref의 대시보드_구현_확정안.md(11/3 개정), tableau_views.json 3.0.0. 11/5 결정으로 메인 화면은 ①②③⑤만 띄운다.

import type { RiskIndex } from "@/screens/risk/riskQuery"

export const TABLEAU_MODULE_URL = "https://public.tableau.com/javascripts/api/tableau.embedding.3.latest.min.js"

const MAIN_WORKBOOK = "eumi_tableau_main_dashboard_v_master"
const DETAIL_WORKBOOK = "eumi_tableau_main_dashboard_v2_0_6_connection_map_fixed"

/** Tableau Public 도구 모음 높이 (탭을 숨겼을 때 FirstVizSizeKnown의 chromeHeight) */
export const TABLEAU_TOOLBAR_HEIGHT = 27

export type TableauView = {
  /** ① ~ ⑥ */
  number: string
  /** 워크북 이름. 없으면 메인 워크북 */
  workbook?: string
  /** 임베드용 대시보드 이름. 아직 게시하지 않았으면 null */
  dashboard: string | null
  /** 대시보드 안의 워크시트 이름. 띄운 뒤 같은 이름인지 확인하고, 마크 선택을 여기서 받는다 */
  worksheet: string | null
  /** 대시보드 고정 크기 (도구 모음 제외) */
  width: number
  height: number
  /** 대시보드에서 이 부분만 보인다 (px, 대시보드 왼쪽 위 기준). 없으면 대시보드 전체 */
  crop?: { x: number; y: number; width: number; height: number }
}

/** 워크북 안의 뷰 주소 */
export const tableauViewUrl = (dashboard: string, workbook = MAIN_WORKBOOK) =>
  `https://public.tableau.com/views/${workbook}/${dashboard}`

/** ① 지도는 지표마다 대시보드가 따로 있다. 지표를 바꾸면 띄운 Tableau 안에서 대시보드만 바꾼다 */
export const TABLEAU_MAP_VIEWS: Record<RiskIndex, TableauView> = {
  risk: { number: "①", dashboard: "Embed01RiskMap", worksheet: "① 지도 · 종합 위험도", width: 640, height: 440 },
  background: {
    number: "①",
    dashboard: "Embed01VulnerabilityMap",
    worksheet: "① 지도 · 배경 취약성",
    width: 640,
    height: 440,
  },
  behavior: { number: "①", dashboard: "Embed01BehaviorMap", worksheet: "① 지도 · 행동 이상", width: 640, height: 440 },
}

export const TABLEAU_VIEWS = {
  distribution: {
    number: "②",
    dashboard: "Embed02RiskDistribution",
    worksheet: "② 월별 종합 위험도 단계 분포",
    width: 640,
    height: 240,
  },
  background: {
    number: "③",
    dashboard: "Embed03Vulnerability",
    worksheet: "③ 읍면동별 배경 취약성 분포",
    width: 430,
    height: 200,
  },
  dongChange: {
    number: "⑤",
    dashboard: "Embed05BehaviorChange",
    worksheet: "⑤ 읍면동별 전월 대비 행동 변화",
    width: 430,
    height: 480,
  },
  grid: {
    number: "⑥",
    workbook: DETAIL_WORKBOOK,
    dashboard: "EmbedDetailMap",
    worksheet: "DETAIL_MAP_100m",
    width: 640,
    height: 560,
    // 지도 그림만 보인다. 위쪽 워크시트 제목과 오른쪽 범례·선택 칸은 잘라 내고, 범례는 우리 화면이 그린다 (11/5 화면에서 잰 값).
    // 게시본 배치가 바뀌면 같이 바꾼다
    crop: { x: 13, y: 71, width: 451, height: 471 },
  },
} satisfies Record<string, TableauView>

/**
 * ⑥ 격자 지도의 색 범례. 게시본 범례(고정 범위 30~85, 연한 파랑 → 진한 남색)를 화면에서 읽어 옮겨 그린다 (11/5).
 * TODO(데이터 담당): 워크북의 색·범위가 바뀌면 같이 바꾼다
 */
export const TABLEAU_GRID_LEGEND = {
  title: "행동 이상 점수(점)",
  min: 30,
  max: 85,
  colors: ["#c3d9ef", "#869ec0", "#50688d"],
}

/** 지도 마크에서 행정동 코드(10자리)를 읽는 필드 */
export const TABLEAU_DONG_FIELD = "읍면동 코드"

/**
 * 모든 대시보드가 같은 매개변수를 쓴다: 시군구 p_city, 기간 p_start ~ p_end (날짜, 그 달 1일).
 * 기준 월(지도·③·⑤)은 p_end, 기간(②)은 p_start ~ p_end
 */
export function tableauParameters(sigunguCode: string, period: { from: string; to: string }): Record<string, string> {
  return { p_city: sigunguCode, p_start: `${period.from}-01`, p_end: `${period.to}-01` }
}

/**
 * ⑥ 격자 지도: 공통 매개변수에 행정동 p_detail_adm(10자리)을 더한다.
 * ⑥은 기준 월(p_end) 하나만 보여 주므로 위쪽 요약 카드와 같은 끝 월이 기준이 된다
 */
export function tableauDetailParameters(
  dongCode: string,
  sigunguCode: string,
  period: { from: string; to: string },
): Record<string, string> {
  return { ...tableauParameters(sigunguCode, period), p_detail_adm: dongCode }
}

/**
 * 게시본에 들어 있는 지역·월 (p_city·p_end에서 고를 수 있는 값). 메인·상세 워크북이 같다 (11/5 확인).
 * 화면의 월 목록은 API-10에서 받고, 이 범위 밖이면 잘못된 조건으로 띄우지 않고 '게시본 없음'을 보인다.
 * TODO(데이터 담당): 게시 범위·갱신 시점이 바뀌면 같이 바꾼다 (FE 월 목록과 게시본의 지역·기준 월이 같아야 한다)
 */
export const TABLEAU_PUBLISHED = {
  sigunguCodes: ["11680", "51110"],
  months: ["2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"],
}

/** 시군구와 기간이 모두 게시본 안에 있는지 */
export function isPublished(sigunguCode: string, period: { from: string; to: string }): boolean {
  return (
    TABLEAU_PUBLISHED.sigunguCodes.includes(sigunguCode) &&
    TABLEAU_PUBLISHED.months.includes(period.from) &&
    TABLEAU_PUBLISHED.months.includes(period.to)
  )
}
