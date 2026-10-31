import { devCases } from "@/devtools/devCases"
import { devResources } from "@/devtools/devResources"
import { PATHS } from "@/routes/paths"

// 화면 흐름도 (14단계) 데이터: 상자(화면·창·공통)와 화살표(화면 사이 이동).
// 좌표는 SVG(1090×950) 안의 위치다. 화살표는 꺾이는 점을 직접 적는다 (H1-A: 직접 배치).
// 상자마다 기능명세의 기능 ID와 그 화면이 부르는 API를 적는다 (H2-A). 점검 스크립트가 실제 API 기록과 비교한다.

export type FlowArea = "auth" | "risk" | "case" | "resource" | "my" | "common"

export const AREA_LABELS: Record<FlowArea, string> = {
  auth: "계정",
  risk: "고립 위험 탐색",
  case: "사례자",
  resource: "복지자원",
  my: "마이페이지",
  common: "공통",
}

/** 영역 색 (SVG 상자·범례) */
export const AREA_COLORS: Record<FlowArea, { fill: string; stroke: string }> = {
  auth: { fill: "#eef1f6", stroke: "#8a94a5" },
  risk: { fill: "#fdeeee", stroke: "#d97a7a" },
  case: { fill: "#eef6ee", stroke: "#6aa56f" },
  resource: { fill: "#eaf1fa", stroke: "#5b8fd6" },
  my: { fill: "#f3eefa", stroke: "#9278c4" },
  common: { fill: "#fff8e6", stroke: "#d6a23b" },
}

export type FlowOpen = {
  label: string
  /** 열 주소 (예시 대상이 없으면 null) */
  to: () => string | null
  /** 로그인해야 볼 수 있는 화면인지 (계정 화면은 로그아웃하고 연다) */
  member: boolean
  /** 연 뒤에 할 일 (예: AI 패널 열기) */
  after?: "openAgent"
}

export type FlowNode = {
  id: string
  title: string
  /** 화면 주소 (설명 칸에 표시) */
  path?: string
  /** 상자 안에 보이는 짧은 주소 (없으면 path) */
  boxPath?: string
  area: FlowArea
  /** screen: 화면 / overlay: 화면 위에 뜨는 창(점선) / common: 모든 화면에 붙는 것 */
  kind: "screen" | "overlay" | "common"
  x: number
  y: number
  w: number
  h: number
  /** 기능명세의 기능 ID */
  features: string[]
  /** 이 화면(창)이 부르는 API: "기능 ID 이름" */
  apis: string[]
  note?: string
  opens?: FlowOpen[]
}

export type FlowEdge = {
  id: string
  from: string
  to: string
  /** 화살표 위 글자 (기능 ID + 동작) */
  label: string
  /** 꺾이는 점 (시작 → 끝) */
  points: [number, number][]
  /** 글자 위치 */
  at: [number, number]
  /** 좁은 틈의 세로 화살표는 글자를 세로로 쓴다 */
  vertical?: boolean
  /** 먼 화면으로 가는 이동은 선을 끝까지 긋지 않고 글자 상자로 대신한다 */
  jump?: boolean
  /** 양쪽 화살표 */
  both?: boolean
  /** 메뉴바처럼 가늘게 */
  thin?: boolean
}

const W = 150
const H = 56

/** 예시 대상 주소 (개발용 데이터에서 찾음) */
const caseDetailPath = () => {
  const caseId = devCases.findCaseId("이영자")
  return caseId ? PATHS.caseDetail(caseId) : null
}
const caseEditPath = () => {
  const caseId = devCases.findCaseId("이영자")
  return caseId ? PATHS.caseEdit(caseId) : null
}
const resourceDetailPath = () => {
  const resourceId = devResources.findResourceId("어르신 안부 산책 모임")
  return resourceId ? PATHS.resourceDetail(resourceId) : null
}
const resourceEditPath = () => {
  const resourceId = devResources.findResourceId("어르신 안부 산책 모임")
  return resourceId ? PATHS.resourceEdit(resourceId) : null
}

const open = (label: string, to: () => string | null, member = true, after?: FlowOpen["after"]): FlowOpen => ({
  label,
  to,
  member,
  after,
})

export const FLOW_NODES: FlowNode[] = [
  // 공통
  {
    id: "menu",
    title: "공통 메뉴바",
    area: "common",
    kind: "common",
    x: 230,
    y: 16,
    w: 810,
    h: 40,
    features: ["0.1.1", "0.1.2"],
    apis: ["0.1.1 메뉴바 사용자 정보 조회", "0.1.2 로그아웃"],
    note: "로그인한 모든 화면의 왼쪽. 0.1.1 메뉴바 사용자 정보 조회는 새로고침해서 로그인 상태를 복원할 때 부른다. 화살표는 메뉴 4개와 로그아웃만 그렸다.",
  },
  {
    id: "agent",
    title: "AI Agent 패널",
    area: "common",
    kind: "common",
    x: 560,
    y: 840,
    w: 260,
    h: 48,
    features: ["0.2.1", "0.2.2", "0.2.3", "0.2.4"],
    apis: ["0.2.2 AI 질문 보내기"],
    note: "헤더의 AI 아이콘으로 어느 화면에서나 열린다(0.2.1). 본문 오른쪽 위를 덮는다(A1-A, H5-A). 지금 보는 화면 정보를 함께 보내고(0.2.2), 사례자 상세에서는 맞춤 복지자원을 추천한다(0.2.3). 답을 끝까지 만들면 대화 기록에 저장한다(0.2.4).",
    opens: [open("패널 열기 (고립 위험 탐색에서)", () => PATHS.risk, true, "openAgent")],
  },

  // 계정
  {
    id: "signup",
    title: "회원가입",
    path: PATHS.signup,
    area: "auth",
    kind: "screen",
    x: 20,
    y: 170,
    w: W,
    h: H,
    features: ["1.1.1"],
    apis: ["1.1.1 소속기관 검색", "1.1.1 인증 메일 발송", "1.1.1 인증 코드 확인", "1.1.1 회원가입"],
    opens: [open("회원가입 열기", () => PATHS.signup, false)],
  },
  {
    id: "login",
    title: "로그인",
    path: PATHS.login,
    area: "auth",
    kind: "screen",
    x: 20,
    y: 340,
    w: W,
    h: H,
    features: ["1.2.1"],
    apis: ["1.2.1 로그인"],
    note: "로그인하지 않은 채 다른 화면을 열면 이 화면으로 온다. 로그인한 상태로 열면 첫 화면으로 간다.",
    opens: [open("로그인 열기", () => PATHS.login, false)],
  },
  {
    id: "passwordFind",
    title: "비밀번호 찾기",
    path: PATHS.passwordFind,
    area: "auth",
    kind: "screen",
    x: 20,
    y: 510,
    w: W,
    h: H,
    features: ["1.3.1"],
    apis: ["1.3.1 임시 비밀번호 발급"],
    opens: [open("비밀번호 찾기 열기", () => PATHS.passwordFind, false)],
  },

  // 고립 위험 탐색
  {
    id: "risk",
    title: "시군구 화면",
    path: PATHS.risk,
    area: "risk",
    kind: "screen",
    x: 230,
    y: 250,
    w: W,
    h: H,
    features: ["2.1.1", "2.1.2", "2.1.3", "2.1.4"],
    apis: ["2.1.1 시도 목록 조회", "2.1.1 시군구 목록 조회", "2.1.1 적재된 월 목록 조회"],
    note: "로그인 후 첫 화면. 지도·그래프 5개는 Tableau 화면이라 API가 아니다(넘기는 필터·매개변수는 API 기록에 '※ Tableau' 메모).",
    opens: [open("시군구 화면 열기", () => PATHS.risk)],
  },
  {
    id: "riskDong",
    title: "읍면동 화면",
    path: "/risk?dong=…",
    area: "risk",
    kind: "screen",
    x: 230,
    y: 420,
    w: W,
    h: H,
    features: ["2.1.1", "2.1.2", "2.1.3", "2.1.4"],
    apis: [
      "2.1.1 시도 목록 조회",
      "2.1.1 시군구 목록 조회",
      "2.1.1 적재된 월 목록 조회",
      "2.1.3 읍면동 인사이트 조회",
      "2.1.4 인사이트 보고서 조회",
    ],
    note: "예시: 개포1동. ⑥ 격자 지도는 Tableau, 인사이트 보고서 그래프는 저장된 값으로 화면이 그린다.",
    opens: [open("개포1동 열기", () => `${PATHS.risk}?dong=1168066000`)],
  },
  {
    id: "password",
    title: "비밀번호 변경",
    path: PATHS.myPassword,
    area: "my",
    kind: "screen",
    x: 230,
    y: 720,
    w: W,
    h: H,
    features: ["5.1.3"],
    apis: ["5.1.3 비밀번호 변경"],
    note: "임시 비밀번호로 로그인하면 이 화면만 쓸 수 있다(M3-A). 메뉴·AI 아이콘이 막히고, 서버도 0.1.1·0.1.2·5.1.3 말고는 거절한다.",
    opens: [open("비밀번호 변경 열기", () => PATHS.myPassword)],
  },

  // 사례자
  {
    id: "cases",
    title: "사례자 목록",
    path: PATHS.cases,
    area: "case",
    kind: "screen",
    x: 450,
    y: 170,
    w: W,
    h: H,
    features: ["4.1.1", "4.1.2", "4.1.3"],
    apis: ["4.1.1 시도 목록 조회", "4.1.1 시군구 목록 조회", "4.1.1 행정동 목록 조회", "4.1.2 사례자 목록 조회"],
    opens: [open("사례자 목록 열기", () => PATHS.cases)],
  },
  {
    id: "caseDetail",
    title: "사례자 상세",
    path: "/cases/:caseId",
    area: "case",
    kind: "screen",
    x: 450,
    y: 340,
    w: W,
    h: H,
    features: ["4.2.1", "4.2.2", "0.2.3"],
    apis: ["4.2.1 사례자 정보 조회", "4.2.1 사례자 정보 삭제", "4.2.2 상담 목록 조회"],
    note: "예시: 이영자. 'AI 맞춤 자원 추천'은 AI 패널을 열고 정해진 질문을 보낸다(0.2.3).",
    opens: [open("이영자 상세 열기", caseDetailPath)],
  },
  {
    id: "consultation",
    title: "상담 창",
    area: "case",
    kind: "overlay",
    x: 450,
    y: 404,
    w: 100,
    h: 28,
    features: ["4.2.2"],
    apis: ["4.2.2 상담 내용 조회", "4.2.2 상담 등록", "4.2.2 상담 수정", "4.2.2 상담 삭제"],
    note: "사례자 상세 위에 뜨는 창 하나를 보기·수정·등록 세 상태로 쓴다. 상담 행을 누르거나 '상담 등록'을 누르면 열린다.",
    opens: [open("이영자 상세 열기 (상담 행을 누름)", caseDetailPath)],
  },
  {
    id: "caseForm",
    title: "사례자 등록·수정",
    path: "/cases/new, /cases/:caseId/edit",
    boxPath: "/cases/new, …/edit",
    area: "case",
    kind: "screen",
    x: 450,
    y: 540,
    w: W,
    h: H,
    features: ["4.2.1"],
    apis: [
      "4.2.1 시도 목록 조회",
      "4.2.1 시군구 목록 조회",
      "4.2.1 행정동 목록 조회",
      "4.2.1 소속 기관 회원 목록 조회",
      "4.2.1 사례자 정보 조회",
      "4.2.1 사례자 중복 확인",
      "4.2.1 사례자 정보 등록",
      "4.2.1 사례자 정보 수정",
    ],
    note: "같은 양식. 취소는 온 곳으로 돌아간다(등록 → 목록, 수정 → 상세). 수정에서 본인을 담당자에서 빼고 저장하면 상세 대신 목록으로 간다(본인 뺌).",
    opens: [open("등록 열기", () => PATHS.caseNew), open("이영자 수정 열기", caseEditPath)],
  },

  // 복지자원
  {
    id: "resources",
    title: "복지자원 목록",
    path: PATHS.resources,
    area: "resource",
    kind: "screen",
    x: 670,
    y: 170,
    w: W,
    h: H,
    features: ["3.1.1", "3.1.2", "3.1.3"],
    apis: ["3.1.1 시도 목록 조회", "3.1.1 시군구 목록 조회", "3.1.1 행정동 목록 조회", "3.1.2 복지자원 목록 조회"],
    opens: [open("복지자원 목록 열기", () => PATHS.resources)],
  },
  {
    id: "resourceDetail",
    title: "복지자원 상세",
    path: "/resources/:resourceId",
    area: "resource",
    kind: "screen",
    x: 670,
    y: 340,
    w: W,
    h: H,
    features: ["3.2.1", "3.2.2"],
    apis: ["3.2.1 복지자원 상세 조회", "3.2.2 복지자원 삭제"],
    note: "예시: 어르신 안부 산책 모임. AI 추천 카드에서 오면 위에 '○○ 님을 위해 AI가 추천한 복지자원입니다.'와 '사례자 상세로'.",
    opens: [open("어르신 안부 산책 모임 열기", resourceDetailPath)],
  },
  {
    id: "resourceForm",
    title: "복지자원 등록·수정",
    path: "/resources/new, /resources/:resourceId/edit",
    boxPath: "/resources/new, …/edit",
    area: "resource",
    kind: "screen",
    x: 670,
    y: 540,
    w: W,
    h: H,
    features: ["3.3.1", "3.3.2", "3.3.3", "3.2.2"],
    apis: [
      "3.3.1 시도 목록 조회",
      "3.3.1 시군구 목록 조회",
      "3.3.1 행정동 목록 조회",
      "3.3.1 소속 기관 회원 목록 조회",
      "3.3.1 복지자원 등록",
      "3.3.2 문서 기반 자동 입력",
      "3.2.1 복지자원 상세 조회",
      "3.2.2 시도 목록 조회",
      "3.2.2 시군구 목록 조회",
      "3.2.2 행정동 목록 조회",
      "3.2.2 소속 기관 회원 목록 조회",
      "3.2.2 복지자원 수정",
    ],
    note: "같은 등록 양식(3.3.1). 등록 화면 위쪽에 PDF 자동 입력(3.3.2). 수정은 담당자만. 취소는 온 곳으로 돌아간다(등록 → 목록, 수정 → 상세).",
    opens: [open("등록 열기", () => PATHS.resourceNew), open("어르신 안부 산책 모임 수정 열기", resourceEditPath)],
  },

  // 마이페이지
  {
    id: "my",
    title: "내 정보",
    path: PATHS.my,
    area: "my",
    kind: "screen",
    x: 890,
    y: 170,
    w: W,
    h: H,
    features: ["5.1.1", "5.1.2"],
    apis: ["5.1.1 내 정보 조회", "5.1.2 내 정보 수정"],
    note: "마이페이지의 첫 탭. 직함·전화번호만 같은 카드에서 수정(M2-A).",
    opens: [open("내 정보 열기", () => PATHS.my)],
  },
  {
    id: "myResources",
    title: "담당 복지자원",
    path: PATHS.myResources,
    area: "my",
    kind: "screen",
    x: 890,
    y: 310,
    w: W,
    h: H,
    features: ["5.2.1"],
    apis: ["5.2.1 담당 복지자원 목록 조회"],
    opens: [open("담당 복지자원 열기", () => PATHS.myResources)],
  },
  {
    id: "myConversations",
    title: "AI 대화 기록",
    path: PATHS.myConversations,
    area: "my",
    kind: "screen",
    x: 890,
    y: 450,
    w: W,
    h: H,
    features: ["5.3.1", "0.2.4"],
    apis: ["5.3.1 대화 목록 조회", "5.3.1 대화 내용 조회", "5.3.1 대화 기록 삭제"],
    note: "대화를 고르면 AI 패널에서 이어서 대화한다(M11-A). 보관 기간은 마지막 대화일부터 3개월(M10-A).",
    opens: [open("AI 대화 기록 열기", () => PATHS.myConversations)],
  },
  {
    id: "withdraw",
    title: "회원 탈퇴",
    path: PATHS.myWithdraw,
    area: "my",
    kind: "screen",
    x: 890,
    y: 610,
    w: W,
    h: H,
    features: ["5.1.4"],
    apis: ["5.1.4 탈퇴 안내 조회"],
    note: "유일 담당 사례자마다 넘겨받을 담당자를 고른다(M6-A).",
    opens: [open("회원 탈퇴 열기", () => PATHS.myWithdraw)],
  },
  {
    id: "withdrawDialog",
    title: "탈퇴 확인 창",
    area: "my",
    kind: "overlay",
    x: 890,
    y: 674,
    w: 110,
    h: 28,
    features: ["5.1.4"],
    apis: ["5.1.4 회원 탈퇴"],
    note: "비밀번호를 다시 입력한다(M7-B, 명세 추가). 탈퇴하면 로그아웃되어 로그인 화면으로 간다.",
    opens: [open("회원 탈퇴 열기 ('탈퇴하기'를 누름)", () => PATHS.myWithdraw)],
  },
]

export const FLOW_EDGES: FlowEdge[] = [
  // 메뉴바 (H4-A: 메뉴 4개와 로그아웃만)
  { id: "m-risk", from: "menu", to: "risk", label: "0.1.1", points: [[305, 56], [305, 250]], at: [322, 90], thin: true },
  { id: "m-cases", from: "menu", to: "cases", label: "0.1.1", points: [[525, 56], [525, 170]], at: [542, 90], thin: true },
  { id: "m-res", from: "menu", to: "resources", label: "0.1.1", points: [[745, 56], [745, 170]], at: [762, 90], thin: true },
  { id: "m-my", from: "menu", to: "my", label: "0.1.1", points: [[965, 56], [965, 170]], at: [982, 90], thin: true },
  {
    id: "m-logout",
    from: "menu",
    to: "login",
    label: "0.1.2 로그아웃",
    points: [[230, 36], [8, 36], [8, 352], [20, 352]],
    at: [116, 30],
    thin: true,
  },

  // 계정
  { id: "signup-login", from: "signup", to: "login", label: "1.1.1 가입 완료", points: [[110, 226], [110, 340]], at: [119, 283], vertical: true },
  { id: "login-signup", from: "login", to: "signup", label: "회원가입 링크", points: [[80, 340], [80, 226]], at: [71, 283], vertical: true },
  { id: "login-find", from: "login", to: "passwordFind", label: "비밀번호 찾기 링크", points: [[80, 396], [80, 510]], at: [71, 453], vertical: true },
  { id: "find-login", from: "passwordFind", to: "login", label: "1.3.1 로그인으로", points: [[110, 510], [110, 396]], at: [119, 453], vertical: true },
  {
    id: "login-risk",
    from: "login",
    to: "risk",
    label: "1.2.1 로그인",
    points: [[170, 358], [185, 358], [185, 270], [230, 270]],
    at: [193, 314],
    vertical: true,
  },
  {
    id: "login-password",
    from: "login",
    to: "password",
    label: "1.2.1 임시 비밀번호",
    points: [[170, 382], [200, 382], [200, 760], [230, 760]],
    at: [143, 640],
  },
  {
    id: "password-risk",
    from: "password",
    to: "risk",
    label: "5.1.3 변경 완료(임시)",
    points: [[230, 735], [215, 735], [215, 292], [230, 292]],
    at: [262, 640],
  },

  // 고립 위험 탐색
  { id: "risk-dong", from: "risk", to: "riskDong", label: "2.1.2 행정동 선택", points: [[290, 306], [290, 420]], at: [281, 363], vertical: true },
  { id: "dong-risk", from: "riskDong", to: "risk", label: "이전으로", points: [[320, 420], [320, 306]], at: [346, 350] },
  {
    id: "dong-cases",
    from: "riskDong",
    to: "cases",
    label: "2.1.3 사례자 탐색",
    points: [[380, 436], [415, 436], [415, 190], [450, 190]],
    at: [407, 313],
    vertical: true,
  },
  {
    id: "dong-res",
    from: "riskDong",
    to: "resources",
    label: "2.1.3 복지자원 찾기",
    points: [[380, 460], [430, 460], [430, 128], [700, 128], [700, 170]],
    at: [626, 122],
  },

  // 사례자
  { id: "cases-detail", from: "cases", to: "caseDetail", label: "4.1.2 행 선택", points: [[510, 226], [510, 340]], at: [501, 283], vertical: true },
  { id: "detail-cases", from: "caseDetail", to: "cases", label: "삭제·목록으로", points: [[540, 340], [540, 226]], at: [549, 283], vertical: true },
  {
    id: "cases-form",
    from: "cases",
    to: "caseForm",
    label: "4.1.3 등록 ⇄ 취소·본인 뺌",
    points: [[450, 212], [438, 212], [438, 568], [450, 568]],
    at: [446, 468],
    vertical: true,
    both: true,
  },
  { id: "detail-form", from: "caseDetail", to: "caseForm", label: "수정", points: [[560, 396], [560, 540]], at: [551, 468], vertical: true },
  { id: "form-detail", from: "caseForm", to: "caseDetail", label: "등록·저장·취소", points: [[585, 540], [585, 396]], at: [594, 468], vertical: true },

  // 복지자원
  { id: "res-detail", from: "resources", to: "resourceDetail", label: "3.1.2 행 선택", points: [[730, 226], [730, 340]], at: [721, 283], vertical: true },
  { id: "detail-res", from: "resourceDetail", to: "resources", label: "삭제·목록으로", points: [[760, 340], [760, 226]], at: [769, 283], vertical: true },
  {
    id: "res-form",
    from: "resources",
    to: "resourceForm",
    label: "3.1.3 등록 ⇄ 취소",
    points: [[820, 198], [845, 198], [845, 560], [820, 560]],
    at: [833, 470],
    vertical: true,
    both: true,
  },
  { id: "rdetail-form", from: "resourceDetail", to: "resourceForm", label: "3.2.2 수정", points: [[780, 396], [780, 540]], at: [771, 468], vertical: true },
  { id: "rform-detail", from: "resourceForm", to: "resourceDetail", label: "등록·저장·취소", points: [[805, 540], [805, 396]], at: [814, 468], vertical: true },

  // AI 추천 (0.2.3)
  {
    id: "detail-agent",
    from: "caseDetail",
    to: "agent",
    label: "0.2.3 AI 맞춤 자원 추천",
    points: [[600, 366], [625, 366], [625, 840]],
    at: [616, 640],
    vertical: true,
  },
  {
    id: "agent-rdetail",
    from: "agent",
    to: "resourceDetail",
    label: "추천 카드 → 자원 상세",
    points: [[645, 840], [645, 380], [670, 380]],
    at: [655, 640],
    vertical: true,
  },
  {
    id: "rdetail-case",
    from: "resourceDetail",
    to: "caseDetail",
    label: "사례자 상세로",
    points: [[670, 350], [600, 350]],
    at: [635, 338],
  },

  // 마이페이지
  { id: "my-myres", from: "my", to: "myResources", label: "탭", points: [[965, 226], [965, 310]], at: [985, 270], both: true },
  {
    id: "myres-conv",
    from: "myResources",
    to: "myConversations",
    label: "탭",
    points: [[965, 366], [965, 450]],
    at: [985, 410],
    both: true,
  },
  {
    id: "myres-rdetail",
    from: "myResources",
    to: "resourceDetail",
    label: "5.2.1",
    points: [[890, 350], [820, 350]],
    at: [855, 338],
    both: true,
  },
  {
    id: "conv-agent",
    from: "myConversations",
    to: "agent",
    label: "5.3.1 이어서 대화",
    points: [[890, 478], [865, 478], [865, 864], [820, 864]],
    at: [876, 700],
    vertical: true,
  },
  {
    id: "my-withdraw",
    from: "my",
    to: "withdraw",
    label: "회원 탈퇴",
    points: [[1040, 214], [1052, 214], [1052, 630], [1040, 630]],
    at: [1059, 560],
    vertical: true,
  },
  {
    id: "my-password",
    from: "my",
    to: "password",
    label: "5.1.3 비밀번호 변경 ⇄ 변경 완료(보통)",
    points: [[1040, 198], [1066, 198], [1066, 905], [305, 905], [305, 776]],
    at: [470, 905],
    both: true,
  },
  {
    id: "withdraw-login",
    from: "withdrawDialog",
    to: "login",
    label: "5.1.4 탈퇴 완료 → 로그인",
    points: [[945, 702], [945, 760]],
    at: [945, 774],
    jump: true,
  },
]

/** 화면 상자에 붙은 창 (상자 아래에 점선으로 잇는다) */
export const OVERLAY_PARENTS: Record<string, string> = {
  consultation: "caseDetail",
  withdrawDialog: "withdraw",
}

/** 기능명세의 기능 이름 (설명 칸 표시용) */
export const FEATURE_NAMES: Record<string, string> = {
  "0.1.1": "메뉴 이동",
  "0.1.2": "로그아웃",
  "0.2.1": "패널 열기",
  "0.2.2": "화면 기반 응답",
  "0.2.3": "사례자 맞춤 복지자원 추천",
  "0.2.4": "대화 기록 저장",
  "1.1.1": "회원가입",
  "1.2.1": "로그인",
  "1.3.1": "비밀번호 찾기",
  "2.1.1": "조회 기준·필터",
  "2.1.2": "위험도 시각화 (시군구 지도·읍면동 격자 지도)",
  "2.1.3": "퀵 인사이트 (분포 변화·읍면동 인사이트·업무 연계 이동)",
  "2.1.4": "우측 패널 (인사이트 보고서·행정동별 그래프)",
  "3.1.1": "검색 필터",
  "3.1.2": "목록 조회·정렬",
  "3.1.3": "등록 이동",
  "3.2.1": "상세 정보 조회",
  "3.2.2": "복지자원 관리 (수정·삭제)",
  "3.3.1": "등록 양식",
  "3.3.2": "AI 기반 등록 (문서 기반 자동 입력·검토 및 수정)",
  "3.3.3": "수동 입력",
  "4.1.1": "검색 필터 및 정렬",
  "4.1.2": "고립 사례자 목록",
  "4.1.3": "사례자 등록 이동",
  "4.2.1": "사례자 정보 관리 (조회·등록·수정·삭제)",
  "4.2.2": "상담 이력 관리",
  "5.1.1": "내 정보 조회",
  "5.1.2": "내 정보 수정",
  "5.1.3": "비밀번호 변경",
  "5.1.4": "회원 탈퇴",
  "5.2.1": "담당 복지자원 목록 조회",
  "5.3.1": "이전 대화 조회",
}

/** 화면이 없는 기능 (흐름도 아래 메모) */
export const FLOW_FOOTNOTE =
  "2.2.1 월 단위 데이터 갱신은 화면이 없다(운영자가 DB에 적재 → 분석·AI 인사이트 생성). 1차는 미리 만든 결과를 DB에 직접 넣는다."

/** SVG 안에 넣는 스타일 (화면 표시와 'SVG로 저장'에 같이 쓴다) */
export const FLOW_SVG_STYLE = `
.flow-node rect { stroke-width: 1.5; rx: 8; }
.flow-node text { font-family: 'Noto Sans KR:Medium', 'Noto Sans KR', sans-serif; font-size: 14px; fill: #1f2a3d; text-anchor: middle; dominant-baseline: middle; }
.flow-node .flow-path { font-family: 'Noto Sans KR:Regular', 'Noto Sans KR', sans-serif; font-size: 10.5px; fill: #6b7686; }
.flow-node.is-overlay rect { stroke-dasharray: 5 3; fill: #fff; }
.flow-node.is-overlay text { font-size: 12px; }
.flow-node.area-auth rect { fill: #eef1f6; stroke: #8a94a5; }
.flow-node.area-risk rect { fill: #fdeeee; stroke: #d97a7a; }
.flow-node.area-case rect { fill: #eef6ee; stroke: #6aa56f; }
.flow-node.area-resource rect { fill: #eaf1fa; stroke: #5b8fd6; }
.flow-node.area-my rect { fill: #f3eefa; stroke: #9278c4; }
.flow-node.area-common rect { fill: #fff8e6; stroke: #d6a23b; }
.flow-node.is-overlay.area-case rect { stroke: #6aa56f; }
.flow-node.is-overlay.area-my rect { stroke: #9278c4; }
.flow-node.is-selected rect { stroke-width: 3; stroke: #324085; }
.flow-edge path { fill: none; stroke: #6b7686; stroke-width: 1.4; }
.flow-edge.is-thin path { stroke: #b7bfcc; stroke-width: 1; }
.flow-edge text { font-family: 'Noto Sans KR:Regular', 'Noto Sans KR', sans-serif; font-size: 10.5px; fill: #3c4a5e; text-anchor: middle; dominant-baseline: middle; paint-order: stroke; stroke: #fff; stroke-width: 4px; stroke-linejoin: round; }
.flow-edge.is-thin text { fill: #8a94a5; }
.flow-edge.is-active path { stroke: #324085; stroke-width: 2.2; }
.flow-edge.is-active text { fill: #324085; }
.flow-edge .flow-jump { fill: #fff; stroke: #9aa4b5; stroke-width: 1; }
.flow-edge.is-active .flow-jump { stroke: #324085; }
.flow-dim { opacity: 0.25; }
.flow-attach { stroke: #9aa4b5; stroke-dasharray: 3 3; }
.flow-footnote { font-family: 'Noto Sans KR:Regular', 'Noto Sans KR', sans-serif; font-size: 11px; fill: #6b7686; }
`
