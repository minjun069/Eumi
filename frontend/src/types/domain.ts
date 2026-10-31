// 예시 데이터에 쓰는 타입. 이름은 기능명세 항목명 기준의 임시 영문 이름이며,
// 화면·API 기록에서는 src/mock/fieldLabels.ts의 한글 이름과 함께 "한글(영문)"으로 표시한다.

/** 시도 */
export type Sido = {
  sidoCode: string
  sidoName: string
}

/** 시군구 */
export type Sigungu = {
  sigunguCode: string
  sidoCode: string
  sigunguName: string
}

/** 읍면동(행정동) */
export type Dong = {
  dongCode: string
  sigunguCode: string
  dongName: string
}

/** 소속기관 (운영자가 DB에서 관리) */
export type Organization = {
  orgId: number
  orgName: string
  /** 공식 메일 도메인. 공식 도메인이 없는 기관은 null */
  officialDomain: string | null
  /** 관할 시군구 (우선 시군구 단위로 등록) */
  jurisdictionSigunguCode: string
}

/** 회원 */
export type Member = {
  memberId: number
  name: string
  email: string
  password: string
  orgId: number
  /** 직함 (선택) */
  title: string | null
  /** 전화번호(비상연락망) */
  phone: string | null
  /**
   * 비밀번호 찾기(1.3.1)로 발급한 임시 비밀번호. 없으면 null.
   * 기존 비밀번호와 따로 보관하고(P3-B), 기존 비밀번호로 로그인하면 지운다.
   */
  tempPassword: string | null
  /** 임시 비밀번호 발급 시각(ms). 발급 후 24시간 동안만 쓸 수 있다(P4-B) */
  tempPasswordIssuedAt: number | null
  createdAt: string
  /** 탈퇴일. 탈퇴한 회원은 soft delete로 남긴다 */
  withdrawnAt: string | null
}

/** 회원가입 이메일 인증 (서버가 보관하는 값. 인증 코드는 메일로만 전달된다) */
export type EmailVerification = {
  verificationId: number
  email: string
  orgId: number
  code: string
  sentAt: number
  /** 이 시각이 지나면 인증 코드를 받지 않는다 (발송 후 10분) */
  expiresAt: number
  /** 재발송하면 이전 코드는 쓸 수 없다 */
  replaced: boolean
  verifiedAt: number | null
}

/** 인증 코드 확인에 성공하면 발급하는 인증 토큰. 회원가입 요청에 함께 보낸다 (한 번만 사용) */
export type VerificationToken = {
  token: string
  email: string
  orgId: number
  usedAt: number | null
}

/**
 * 로그인 사용자 정보 (0.1.1). 메뉴바에는 기관명·이름·직함을 보여 주고,
 * 관할 시도·시군구 코드는 검색 조건의 처음 값(사례자 목록 C7-B, 고립 위험 탐색 2.1.1)에 쓴다.
 */
export type MenuProfile = {
  memberId: number
  name: string
  orgName: string
  title: string | null
  jurisdictionSidoCode: string
  jurisdictionSigunguCode: string
  /**
   * 임시 비밀번호로 로그인해 비밀번호를 먼저 바꿔야 하는지 (M3-A).
   * 로그인 정보(토큰)에 담겨 있어 새로고침해도 0.1.1 응답으로 다시 받는다
   */
  mustChangePassword: boolean
}

export type Gender = "남" | "여"

/** 연령대 (만 나이, 3.3.1 기준): 청소년 20세 미만, 청년 20~39, 중장년 40~59, 노년 60세 이상 */
export type AgeGroup = "청소년" | "청년" | "중장년" | "노년"

/** 복지자원 지원 연령: 연령대 여러 개, 연령 조건이 없으면 ['무관'] 하나 (3.3.1) */
export type SupportAgeGroup = AgeGroup | "무관"

/** 복지자원 지원 성별: 성별 조건이 없으면 '무관' (3.3.1) */
export type SupportGender = Gender | "무관"

/** 복지자원 상태 (3.3.1). 운영 종료일이 지나면 조회할 때 '종료'로 돌려준다 */
export type ResourceStatus = "진행 중" | "종료"

/**
 * 복지자원 (3. RESOURCE). 모든 기관이 함께 조회하고(W1-A), 수정·삭제는 담당자만 한다.
 * 등록 양식(3.3.1)의 항목과 같다. *는 필수
 */
export type WelfareResource = {
  resourceId: number
  /** 등록한 기관 (담당자의 소속 기관) */
  orgId: number
  /** 자원명* */
  resourceName: string
  /** 수행·담당 기관* (글, W7-A: 구청·외부 기관도 적을 수 있음) */
  operatingOrgName: string
  /** 지원 대상* (글) */
  target: string
  /** 지원 연령* */
  supportAgeGroups: SupportAgeGroup[]
  /** 지원 성별* */
  supportGender: SupportGender
  /** 지역*: 시군구 */
  sigunguCode: string
  /** 지역: 행정동. null이면 시군구 전체 (W2-B) */
  dongCode: string | null
  /** 운영 기간* YYYY-MM-DD (시작일·종료일 모두 필수, W4-A) */
  periodStart: string
  periodEnd: string
  /** 이용자 부담금* (원 단위 금액, 0이면 '무료'. F1-A: 금액 순 정렬. '월'·'재료비' 같은 설명은 지원 내용에 적음) */
  fee: number
  /** 상태* (담당자가 고른 값) */
  status: ResourceStatus
  /** 담당자* (같은 기관 회원 한 명, W3-A). 탈퇴하면 '퇴사자'로 표시 */
  managerMemberId: number
  /** 정원* */
  capacity: number
  /** 지원 내용 */
  supportContent: string | null
  /** 실제 참여자 수 */
  actualParticipants: number | null
  /** 신청 방법 */
  applyMethod: string | null
  createdAt: string
  /** 삭제일 (soft delete). 삭제한 자원은 목록·상세·추천에 나오지 않는다 */
  deletedAt: string | null
}

/** 사례자 (4. CASE, 복지관 내에서만 다룬다) */
export type CaseRecord = {
  /** 내부 ID. 화면 주소·API에서 사례자를 구분하는 값 */
  caseId: number
  orgId: number
  /** 관리번호 (A-1: 연도-일련번호, 기관마다 0001부터). (기관ID + 관리번호)가 겹치지 않는다 */
  managementNo: string
  name: string
  /** 생년월일 YYYY-MM-DD (연령은 만 나이로 계산) */
  birthDate: string
  gender: Gender
  /** 지역 (행정동) */
  dongCode: string
  /** 최초 등록일 YYYY-MM-DD (등록할 때 입력) */
  firstRegisteredAt: string
}

/** 사례자 담당자 (같은 기관 회원 중 여러 명 가능) */
export type CaseManager = {
  caseId: number
  memberId: number
}

/** 관리번호 일련번호 (기관·연도별 마지막 번호). 사례자를 삭제해도 줄이지 않아 번호를 다시 쓰지 않는다 (D9-A) */
export type CaseNumberSequence = {
  orgId: number
  year: string
  lastNo: number
}

/** 상담 분류 (D8-C: 하나를 고르고, '기타'는 내용을 직접 입력) */
export type ConsultationCategory = "초기상담" | "중기상담" | "종료상담" | "정기상담" | "긴급상담" | "기타"

/** 상담 기록 (4.2.2). 사례자의 '최근 기록일'은 상담 일자 중 가장 최근 날짜 */
export type Consultation = {
  /** 늦게 등록한 기록일수록 큰 값 (같은 상담 일자의 정렬 순서에 쓴다) */
  consultationId: number
  caseId: number
  /** 상담 일자 YYYY-MM-DD */
  consultedAt: string
  /** 상담 목적 (상담 내용의 제목 역할) */
  purpose: string
  category: ConsultationCategory
  /** 분류가 '기타'일 때 직접 입력한 내용 (20자 이내). 그 밖의 분류는 null */
  categoryEtc: string | null
  content: string
  /** 기록자: 상담을 등록한 회원 (D7-A, 바꿀 수 없음) */
  recorderMemberId: number
}

/** 고립 위험 단계 (1~5, 숫자가 클수록 위험이 높음) */
export type RiskStage = 1 | 2 | 3 | 4 | 5

/** 고립 위험 탐색의 지표 */
export type RiskIndex = "background" | "behavior"

/**
 * 행정동·월별 분석 결과 (2.1). 월 데이터를 적재할 때 분석해 저장한다(2.2.1, 1차는 DB에 직접 넣음).
 * Tableau가 그리는 지도·그래프의 데이터이며, 우리 서버는 적재된 월 목록·읍면동 인사이트에 쓴다.
 */
export type DongMonthlyAnalysis = {
  dongCode: string
  /** YYYY-MM */
  month: string
  /** 배경 취약성 지수 */
  backgroundScore: number
  backgroundStage: RiskStage
  /** 행동 이상 지수 */
  behaviorScore: number
  behaviorStage: RiskStage
  /** 행동 이상 지수의 전월 대비 변화량 (첫 적재 월은 null). 기간 필터와 관계없이 미리 계산해 둔다 */
  behaviorChange: number | null
}

/**
 * 읍면동 인사이트 (2.1.4 왼쪽 '인사이트'). 월 데이터를 분석할 때 AI가 행정동·월마다 만들어 저장한다.
 * 문장 안의 **…**는 굵게 보여 줄 부분.
 */
export type DongInsight = {
  dongCode: string
  /** YYYY-MM */
  month: string
  /** 요약 문장 2~3개 */
  summary: string[]
  /** 만든 시각 YYYY-MM-DD HH:mm:ss */
  generatedAt: string
}

/** 인사이트 보고서 그래프 (화면이 그리는 그래프, 저장할 때 JSON으로 저장) */
export type ReportChart =
  | {
      /** 행동 이상 지수 추이: 이 동의 점수·단계·순위와 시군구 안 중앙값·사분위수 범위 */
      type: "trend"
      heading: string
      /** 순위를 매긴 행정동 수 */
      total: number
      points: { month: string; score: number; stage: RiskStage; rank: number; median: number; q1: number; q3: number }[]
    }
  | {
      /** 전월 대비 점수를 올린(+)·내린(-) 요인 */
      type: "factors"
      heading: string
      items: { label: string; value: number }[]
    }
  | {
      /** 요일별 일평균 활동 인구: 전월·이번 달 막대와 요일별 변화율(%) */
      type: "weekday"
      heading: string
      caption: string
      unit: string
      days: string[]
      series: { label: string; values: number[] }[]
      changes: number[]
    }
  | {
      /** 이 동과 비교 대상의 가로 막대 */
      type: "compare"
      heading: string
      items: { label: string; value: number; highlight: boolean }[]
    }
  | {
      /** 사람 그림 비율 (10명 중 3명 등) */
      type: "ratio"
      count: number
      total: number
      caption: string
    }

export type ReportBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "bullets"; items: { label: string; text: string }[] }
  | { kind: "chart"; chart: ReportChart }

export type ReportSection = {
  /** 질문 (null이면 제목 문장 바로 아래 내용) */
  question: string | null
  blocks: ReportBlock[]
}

/** 인사이트 보고서 (2.1.4 오른쪽). 월 데이터를 분석할 때 AI가 행정동·월마다 만들어 저장한다 */
export type InsightReport = {
  dongCode: string
  /** YYYY-MM */
  month: string
  headline: string
  sections: ReportSection[]
  /** 만든 시각 YYYY-MM-DD HH:mm:ss */
  generatedAt: string
}

/** 추천 카드의 조건 확인 결과: 충족(met)·부족(unmet)·확인 필요(unknown) */
export type CheckState = "met" | "unmet" | "unknown"

/** 0.2.3 사례자 맞춤 복지자원 추천 카드 */
export type RecommendationCard = {
  rank: number
  resourceId: number
  resourceName: string
  operatingOrgName: string
  status: ResourceStatus
  /** 카드 위 요약 표시 (지역·필요한 지원·부담금) */
  tags: string[]
  reason: string
  checks: { label: string; state: CheckState; note: string }[]
  beforeUse: string[]
  evidence: string
}

/** AI 답변 블록: 문장(**…**는 굵게)·목록·추천 카드 */
export type AgentBlock =
  | { kind: "text"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "resourceCards"; expanded: boolean; cards: RecommendationCard[] }

/**
 * AI Agent 대화 (0.2.4). 첫 답을 끝까지 만들면 생긴다.
 * 보관 기간: 마지막 대화일부터 3개월 (M10-A). 지난 대화는 서버가 매일 지운다
 */
export type AgentConversation = {
  conversationId: string
  memberId: number
  /** 첫 질문 (목록의 제목, 신원 정보를 가린 값) */
  firstQuestion: string
  /** YYYY-MM-DD HH:mm:ss */
  createdAt: string
  lastMessageAt: string
}

/** 대화 기록의 질문·답변 하나 (M9-A: 진행 단계는 저장하지 않음, 신원 정보를 가린 값) */
export type AgentTurn = {
  turnId: number
  conversationId: string
  question: string
  blocks: AgentBlock[]
  /** YYYY-MM-DD HH:mm:ss */
  askedAt: string
}
