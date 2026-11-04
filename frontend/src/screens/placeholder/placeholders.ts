import { PATHS } from "@/routes/paths"

// 아직 만들지 않은 화면의 자리 표시 내용 ('준비 중').
// 페이지를 프로토타입 원본(초기화 직전 develop 커밋 c96cf85의 frontend/)에서 옮겨 실제 API로 연결하면 그 항목을 지운다.
// stage는 "○○에서 만들 화면입니다." 문장에 들어간다.

export type PlaceholderSpec = {
  title: string
  stage: string
  features: string[]
  /** 이 화면으로 오게 되는 상황 설명 */
  note?: string
  /** 이 자리에서 이어지는 화면 (주소 확인용) */
  links?: PlaceholderLink[]
}

export type PlaceholderLink = {
  label: string
  to: string
}

const MY = "11/5~11/6 마이페이지 작업"
const EXTRA = "11/9 이후 부가 기능 작업"

export const PLACEHOLDERS = {
  signup: {
    title: "회원가입",
    stage: EXTRA,
    features: ["소속기관 검색 (API-04)", "인증 메일 발송·코드 확인 (API-05·06)", "가입 (API-07)"],
  },
  passwordFind: {
    title: "비밀번호 찾기",
    stage: EXTRA,
    features: ["임시 비밀번호 발급 (API-09)"],
  },

  my: {
    title: "마이페이지 · 내 정보",
    stage: MY,
    features: ["내 정보 조회, 직함·전화 수정 (API-30·31)"],
    links: [
      { label: "내 담당 복지자원", to: PATHS.myResources },
      { label: "대화 이력", to: PATHS.myConversations },
      { label: "비밀번호 변경", to: PATHS.myPassword },
    ],
  },
  myResources: {
    title: "마이페이지 · 내 담당 복지자원",
    stage: MY,
    features: ["담당 복지자원 목록 (API-35)"],
  },
  myConversations: {
    title: "마이페이지 · 대화 이력",
    stage: MY,
    features: ["대화 목록·조회·삭제 (API-36~38)"],
  },
  myPassword: {
    title: "비밀번호 변경",
    stage: MY,
    features: ["비밀번호 변경 (API-32)"],
    note: "임시 비밀번호로 로그인하면 비밀번호를 바꿀 때까지 이 화면만 쓸 수 있습니다.",
  },
  myWithdraw: {
    title: "회원 탈퇴",
    stage: EXTRA,
    features: ["탈퇴 안내·업무 인계 (API-33·34)"],
  },
} satisfies Record<string, PlaceholderSpec>
