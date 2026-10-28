// API 기록에 "한글(영문)"으로 표시할 항목 이름 사전.
// 새 항목을 요청·응답에 넣으면 여기에 한글 이름을 함께 추가한다.
// 사전에 없는 항목은 영문 이름만 표시되고, 개발 중에는 콘솔에 경고가 뜬다.

export const fieldLabels: Record<string, string> = {
  // 회원
  memberId: "회원ID",
  name: "이름",
  email: "이메일",
  password: "비밀번호",
  title: "직함",
  phone: "전화번호",
  mustChangePassword: "비밀번호 변경 필요",
  createdAt: "가입일",
  withdrawnAt: "탈퇴일",

  // 소속기관
  orgId: "소속기관ID",
  orgName: "소속기관명",
  officialDomain: "공식 메일 도메인",
  jurisdictionSigunguCode: "관할 시군구 코드",

  // 회원가입
  keyword: "검색어",
  code: "인증 코드",
  expiresAt: "인증 만료 시각",
  verificationToken: "인증 토큰",

  // 관할지역 (로그인 응답·0.1.1)
  jurisdictionSidoCode: "관할 시도 코드",

  // 복지자원 (3. RESOURCE)
  resourceId: "복지자원ID",
  resourceName: "자원명",
  operatingOrgName: "수행·담당 기관",
  target: "지원 대상",
  capacity: "정원",
  capacityMin: "최소 정원",
  capacityMax: "최대 정원",
  managerName: "담당자 이름",
  periodStart: "운영 시작일",
  periodEnd: "운영 종료일",
  fee: "이용자 부담금",
  status: "상태",
  supportAgeGroups: "지원 연령",
  supportGender: "지원 성별",
  autoEnded: "자동 종료 여부",
  actualParticipants: "실제 참여자 수",
  supportContent: "지원 내용",
  applyMethod: "신청 방법",
  manager: "담당자",
  editable: "수정·삭제 가능 여부",
  managerMemberId: "담당자 회원ID",
  fileName: "파일 이름",
  fileSize: "파일 크기(바이트)",
  extracted: "뽑아낸 항목",
  missingFields: "찾지 못한 항목",

  // 사례자 (4. CASE)
  caseId: "사례자ID",
  managementNo: "관리번호",
  birthDate: "생년월일",
  age: "나이(만)",
  ageGroup: "연령대",
  gender: "성별",
  firstRegisteredAt: "최초 등록일",
  lastRecordedAt: "최근 기록일",
  registeredFrom: "최초 등록일 시작",
  registeredTo: "최초 등록일 끝",
  recordedFrom: "최근 기록일 시작",
  recordedTo: "최근 기록일 끝",
  managers: "담당자",
  managerMemberIds: "담당자 회원ID 목록",
  excludeCaseId: "제외할 사례자ID",
  duplicates: "같은 사례자 목록",

  // 상담 기록 (4.2.2)
  consultationId: "상담ID",
  consultedAt: "상담 일자",
  purpose: "상담 목적",
  category: "상담 분류",
  categoryEtc: "기타 분류 내용",
  content: "상담 내용",
  recorderMemberId: "기록자 회원ID",
  recorderName: "기록자",

  // 목록·정렬·페이지 (공통)
  sort: "정렬 기준",
  direction: "정렬 방향",
  page: "페이지",
  size: "페이지당 개수",
  totalCount: "전체 건수",
  totalPages: "전체 페이지 수",
  items: "목록",

  // 고립 위험 탐색 (2.1)
  months: "적재된 월 목록",
  month: "월",
  background: "배경 취약성",
  behavior: "행동 이상",
  score: "점수",
  stage: "단계",
  insight: "인사이트",
  summary: "요약 문장",
  generatedAt: "생성 시각",

  // 인사이트 보고서 (2.1.4)
  report: "인사이트 보고서",
  headline: "제목 문장",
  sections: "질문별 내용",
  question: "질문",
  blocks: "내용 블록",
  kind: "블록 종류",
  text: "문장",
  label: "항목명",
  chart: "그래프",
  type: "그래프 종류",
  heading: "그래프 제목",
  total: "전체 수",
  points: "점 목록",
  rank: "순위",
  median: "중앙값",
  q1: "1사분위수",
  q3: "3사분위수",
  value: "값",
  values: "값 목록",
  caption: "설명",
  unit: "단위",
  days: "요일 목록",
  series: "막대 묶음",
  changes: "변화율 목록(%)",
  highlight: "강조 여부",
  count: "해당 수",

  // AI Agent (0.2)
  conversationId: "대화ID",
  screen: "화면 정보",
  screenType: "화면 종류",
  from: "기간 시작 월",
  to: "기간 끝 월",
  index: "지표",
  path: "화면 주소",
  events: "응답 이벤트(스트림)",
  event: "이벤트 종류",
  stepId: "단계ID",
  stepName: "단계 이름",
  detail: "단계 결과",
  expanded: "종료 자원까지 넓혀 찾음",
  cards: "추천 카드",
  tags: "요약 표시",
  reason: "추천 이유",
  checks: "조건 확인",
  state: "확인 결과",
  note: "설명",
  beforeUse: "이용 전 확인",
  evidence: "근거",
  errorMessage: "오류 사유",

  // 마이페이지 (5.1 내 정보·비밀번호·탈퇴, 5.2 담당 복지자원)
  jurisdictionName: "관할지역",
  currentPassword: "현재 비밀번호",
  newPassword: "새 비밀번호",
  soleCases: "유일 담당 사례자",
  sharedCaseCount: "공동 담당 사례자 수",
  successors: "넘겨받을 수 있는 회원",
  resourceCount: "담당 복지자원 수",
  conversationCount: "AI 대화 기록 수",
  transfers: "사례자 넘기기 목록",
  newManagerMemberId: "넘겨받을 담당자 회원ID",

  // AI 대화 기록 (0.2.4, 5.3.1)
  firstQuestion: "첫 질문(제목)",
  questionCount: "질문 수",
  lastMessageAt: "마지막 대화 시각",
  deleteScheduledAt: "삭제 예정일",
  turns: "질문·답변 목록",
  askedAt: "질문 시각",

  // 지역
  sidoCode: "시도 코드",
  sidoName: "시도명",
  sigunguCode: "시군구 코드",
  sigunguName: "시군구명",
  dongCode: "행정동 코드",
  dongName: "행정동명",
}

const warned = new Set<string>()

export function labelOf(key: string): string {
  const korean = fieldLabels[key]
  if (korean) return `${korean}(${key})`
  if (import.meta.env.DEV && !warned.has(key)) {
    warned.add(key)
    console.warn(`[fieldLabels] 한글 이름이 없는 항목: ${key}`)
  }
  return key
}
