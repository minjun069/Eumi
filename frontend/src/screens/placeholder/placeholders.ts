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

const EXTRA = "11/9 이후 부가 기능 작업"

export const PLACEHOLDERS = {
  signup: {
    title: "회원가입",
    stage: EXTRA,
    features: ["소속기관 검색 (API-04)", "인증 메일 발송·코드 확인 (API-05·06)", "가입 (API-07)"],
  },
} satisfies Record<string, PlaceholderSpec>
