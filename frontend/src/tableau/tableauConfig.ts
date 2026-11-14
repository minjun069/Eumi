// Tableau Public 게시본 설정. 화면 자리마다 임베드용 대시보드가 있다.
// - 워크북 하나(eumi_tableau_main_dashboard_v2_0_6_connection_map_fixed, 11/12 09:57 데이터 팀 재게시)에
//   메인 화면 ①②③⑤, 읍면동 상세 ⑥, 인사이트 보고서 그래프(EmbedDetailV01~V08)가 모두 있다.
//   예전 메인 워크북(eumi_tableau_main_dashboard_v_master)은 11/2 이후 갱신이 없어 쓰지 않는다
// 지도·그래프는 서비스 API가 아니라 Tableau Embedding API v3로 띄우고, 자리마다 그 대시보드를 하나씩 띄운다.
// 대시보드는 Tableau에서 만든 그대로 띄운다 (도구 모음만 숨긴다). 예외는 ⑥: 위 선택 칸만 잘라 낸다 (지도 · 범례 · 격자 선택 카드 · 비교표는 보인다).
// 지역 · 기간 · 행정동은 우리 화면 위쪽 필터로만 고른다.
// 게시본이 없는 자리는 '준비 중'으로 두고 다른 뷰를 대신 넣지 않는다.
// 기준 문서: docs/work-ref의 대시보드_구현_확정안.md, tableau_views.json. 11/5 결정으로 메인 화면은 ①②③⑤만 띄운다.

import type { RiskIndex } from "@/screens/risk/riskQuery"
import type { TableauParameterInput } from "@/tableau/tableauTypes"

export const TABLEAU_MODULE_URL = "https://public.tableau.com/javascripts/api/tableau.embedding.3.latest.min.js"

const WORKBOOK = "eumi_tableau_main_dashboard_v2_0_6_connection_map_fixed"

/** Tableau Public 도구 모음 높이 (탭을 숨겼을 때 FirstVizSizeKnown의 chromeHeight) */
export const TABLEAU_TOOLBAR_HEIGHT = 27

export type TableauView = {
  /** ① ~ ⑥ */
  number: string
  /** 임베드용 대시보드 이름. 아직 게시하지 않았으면 null */
  dashboard: string | null
  /** 대시보드 안의 워크시트 이름. 띄운 뒤 같은 이름인지 확인하고, 마크 선택을 여기서 받는다 */
  worksheet: string | null
  /** 대시보드 고정 크기 (도구 모음 제외). 게시본 크기(activeSheet.size)와 같게 둔다 */
  width: number
  height: number
  /** 대시보드에서 이 부분만 보인다 (px, 대시보드 왼쪽 위 기준). 없으면 대시보드 전체 */
  crop?: { x: number; y: number; width: number; height: number }
  /** crop이 있을 때 마우스를 올린 동안 보일 높이. 아래 내용 위에 겹쳐 펼친다 (TableauWorksheet hoverHeight) */
  hoverHeight?: number
}

/** 워크북 안의 뷰 주소 */
export const tableauViewUrl = (dashboard: string) => `https://public.tableau.com/views/${WORKBOOK}/${dashboard}`

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
  // 대시보드(640×720)에서 위 줄 선택 칸(읍면동 · 기준월 · 지도 보기, y 8~60)을 잘라 내고, 지도 · 지도 위 범례 · 격자 선택 카드 · 비교표를 보인다
  // (11/13 재게시 배치, 대시보드 객체 위치로 확인: 지도 12,63 616×363 — 그 위에 범례 · '아파트 평균 매매금액' 표시 스위치,
  //  선택 카드 y 434~589 — 제목 12,434 485×40 · '전체 해제' 버튼 512,436 105×40 · 평균 두 칸 12,481 300×108 / 322,481 306×108,
  //  비교표 12,600 616×116).
  // 격자를 누르면 카드에 선택 요약(개수 · 평균 · 미산출), 비교표에 격자별 점수가 나온다 (매개변수 p_selected_grid, 우리가 넘기지 않는다).
  // 처음(고른 격자 없음)에는 카드 제목 줄까지만 보이고, 격자를 고르면 평균 두 칸과 비교표가 고른 줄 수만큼 늘어난다 (tableauGridCrop). 이 crop은 처음 값이다.
  // 조건은 우리 화면 위쪽 필터로만 고른다. 지도 보기(p_map_mode)는 기본값(점수 보기) 그대로 둔다. 게시본 배치가 바뀌면 crop을 같이 바꾼다
  grid: {
    number: "⑥",
    dashboard: "EmbedDetailMap",
    worksheet: "DETAIL_MAP_100m",
    width: 640,
    height: 720,
    // 고른 격자가 없으면 카드는 제목 줄('지도에서 격자를 선택하세요' · 전체 해제)만 있고 평균 두 칸은 비어 있다.
    // 그래서 처음에는 제목 줄 끝(476) + 여유 4px까지만 보인다.
    // 오른쪽은 대시보드 끝(640)까지 보인다 (오른쪽 끝 격자의 상세 정보가 640까지 나온다)
    crop: { x: 8, y: 61, width: 632, height: 419 },
    // 격자 상세 정보(툴팁, 격자 상세지표 포함 약 370×275)는 격자 아래로 나온다. 지도는 동 모양에 맞춰 확대돼
    // 맨 아래 격자가 y 373~386에 오고, 거기서 뜬 상세 정보는 y 676 근처에서 끝난다 (11/13 역삼1동 확인).
    // 상세 정보는 마우스 위치를 따라 붙으므로 격자 아래 끝을 가리켜도 들어가게 y 700까지만 겹쳐 펼친다.
    // 격자를 골라 이미 그보다 크게 보이면(3개 이상) 펼치지 않는다
    hoverHeight: 700 - 61,
  },
} satisfies Record<string, TableauView>

/** ⑥에서 고른 격자를 담는 Tableau 매개변수. 값은 '행정동코드:|격자||격자|' 꼴이다 (11/12 확인) */
export const TABLEAU_GRID_SELECTION_PARAMETER = "p_selected_grid"

/** 고른 격자 수 */
export function gridSelectionCount(value: string): number {
  return value.match(/\|[^|]+\|/g)?.length ?? 0
}

// ⑥ 비교표 배치 (대시보드 y, 11/13 재게시본 화면에서 잼 · Noto Sans KR로 그린 상태): 칸 600~716, 머리줄 끝 620, 줄마다 29px.
// 칸 안에 세 줄까지 들어가고, 넷째 줄부터 Tableau가 표 안에 스크롤 막대를 만든다
const GRID_TABLE_HEADER_BOTTOM = 620
const GRID_TABLE_ROW_HEIGHT = 29
const GRID_TABLE_BOTTOM = 716
/** 마지막 줄 아래 여유 */
const GRID_TABLE_MARGIN = 2

/**
 * ⑥에서 보일 부분. 고른 격자가 없으면 선택 카드 제목 줄까지만 보인다.
 * 고르면 평균 두 칸 · 비교표 머리줄과 고른 줄 수만큼 늘리고(해제하면 다시 줄어든다), 넷째 격자부터는 비교표 칸 전체를 보인다.
 * 칸 전체가 보이므로 Tableau가 표 안에 만든 스크롤 막대로 아래 줄을 볼 수 있다
 */
export function tableauGridCrop(selectedCount: number) {
  const base = TABLEAU_VIEWS.grid.crop
  if (selectedCount <= 0) return base
  const rowsBottom = GRID_TABLE_HEADER_BOTTOM + GRID_TABLE_ROW_HEIGHT * selectedCount + GRID_TABLE_MARGIN
  const bottom = Math.min(rowsBottom, GRID_TABLE_BOTTOM + GRID_TABLE_MARGIN)
  return { ...base, height: bottom - base.y }
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

/** 시트 틀(TableauSheetFrame)에 넘길 꼴로 바꾼다. YYYY-MM-DD 값은 날짜 매개변수다 */
export function tableauParameterInputs(parameters: Record<string, string>): TableauParameterInput[] {
  return Object.entries(parameters).map(([name, value]) => ({
    name,
    value,
    dataType: /^\d{4}-\d{2}-\d{2}$/.test(value) ? "date" : "string",
  }))
}

/**
 * 인사이트 보고서 그래프로 쓸 수 있는 시트 (docs/api/insight-report.md 9절, tableau_views.json reportViews).
 * 크기는 게시본 데스크톱 배치의 고정 크기(도구 모음 제외, 11/12 게시본 8개 모두 확인)다. 이 크기로 띄워 시트 전체를 보이고,
 * 틀이 더 좁으면 틀 폭에 맞춰 줄인다. 데스크톱 배치로 띄워야 이 크기가 된다 (TableauSheetFrame desktopLayout).
 * 매개변수는 ⑥ 격자 지도와 같다 (tableauDetailParameters)
 */
export const TABLEAU_REPORT_SHEETS: Record<string, { title: string; width: number; height: number }> = {
  EmbedDetailV01: { title: "행동 이상 추이", width: 720, height: 420 },
  EmbedDetailV02: { title: "주요 행동 지표", width: 900, height: 600 },
  EmbedDetailV03: { title: "시간대 활동", width: 720, height: 580 },
  EmbedDetailV04: { title: "요일별 활동", width: 720, height: 420 },
  EmbedDetailV05: { title: "성 · 연령 활동 변화", width: 720, height: 440 },
  EmbedDetailV06: { title: "취약성 요인", width: 900, height: 440 },
  EmbedDetailV07: { title: "월별 활동 추이", width: 720, height: 700 },
  EmbedDetailV08: { title: "격자 점수 분포", width: 720, height: 580 },
}

/** 보고서 그래프 시트의 설정과 게시 뷰 주소. 목록에 없는 시트면 null (띄우지 않는다) */
export function reportSheet(sheet: string) {
  if (!Object.prototype.hasOwnProperty.call(TABLEAU_REPORT_SHEETS, sheet)) return null
  return { ...TABLEAU_REPORT_SHEETS[sheet], src: tableauViewUrl(sheet) }
}

/**
 * 게시본에 들어 있는 지역·월 (p_city·p_end에서 고를 수 있는 값) (11/5 확인).
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
