import type { AgentBlock, AgentConversation, AgentTurn } from "@/types/domain"
import { addDays, addMonths, todayString } from "@/utils/datetime"

// 예시 AI 대화 기록 (0.2.4 저장, 5.3.1 이전 대화 조회).
// 날짜는 오늘을 기준으로 정한다 → 언제 열어도 '삭제 예정 2일 남음'과 '보관 기간 지남'이 그대로 보인다.
// 보관 기간: 마지막 대화일부터 3개월 (M10-A). 답변은 11단계 AI 흉내가 만든 답을 그대로 옮겼다.
// 저장된 값은 신원 정보를 가린 값이다 (질문에 적은 사례자 이름 → ○○○).
//
// 김지원(1): 6개 — 맞춤 추천, 현황 요약(질문 2개), 보고서 설명, 이름을 적은 질문(가려서 저장),
//            삭제 예정일이 2일 남은 대화, 보관 기간이 지나 목록에서 빠지는 대화
// 박성민(2): 1개 / 그 밖의 회원: 없음 ('저장된 대화가 없습니다.')

const RECOMMEND_BLOCKS: AgentBlock[] = [
  {
    kind: "text",
    text: "상담 기록과 기본 정보를 바탕으로 **진행 중인 자원 3개**를 추천해요.",
  },
  {
    kind: "resourceCards",
    expanded: false,
    cards: [
      {
        rank: 1,
        resourceId: 1,
        resourceName: "어르신 안부 산책 모임",
        operatingOrgName: "우리복지관",
        status: "진행 중",
        tags: ["개포1동", "관계·정서 지원", "무료"],
        reason: "상담에서 확인한 '관계·정서 지원'에 맞는 자원이에요. 같은 동(개포1동)에서 운영해요. '식사 지원, 주거 지원'은 다른 자원으로 함께 살펴보세요.",
        checks: [
          {
            label: "개포1동 지원",
            state: "met",
            note: "같은 동 — 자료상 확인",
          },
          {
            label: "노년 대상",
            state: "met",
            note: "자료상 확인",
          },
          {
            label: "관계·정서 지원",
            state: "met",
            note: "자료상 확인",
          },
          {
            label: "식사 지원",
            state: "unmet",
            note: "이 자원에는 없음",
          },
          {
            label: "주거 지원",
            state: "unmet",
            note: "이 자원에는 없음",
          },
          {
            label: "운영 상태",
            state: "met",
            note: "진행 중",
          },
          {
            label: "정원 여유",
            state: "met",
            note: "여유 있음 (11/15명)",
          },
          {
            label: "세부 신청 자격",
            state: "unknown",
            note: "기관 확인 필요",
          },
        ],
        beforeUse: ["신청 방법: 기관 전화 또는 방문 신청", "이용자 부담금: 무료", "운영 기간: 2026.10.01 ~ 2026.12.31"],
        evidence: "상담 기록 4건 · 기본 정보(연령대·성별·지역) · 복지자원 등록 정보",
      },
      {
        rank: 2,
        resourceId: 2,
        resourceName: "독거 어르신 반찬 나눔",
        operatingOrgName: "우리복지관",
        status: "진행 중",
        tags: ["개포1동", "식사 지원", "무료"],
        reason: "상담에서 확인한 '식사 지원'에 맞는 자원이에요. 같은 동(개포1동)에서 운영해요. '관계·정서 지원, 주거 지원'은 다른 자원으로 함께 살펴보세요.",
        checks: [
          {
            label: "개포1동 지원",
            state: "met",
            note: "같은 동 — 자료상 확인",
          },
          {
            label: "노년 대상",
            state: "met",
            note: "자료상 확인",
          },
          {
            label: "식사 지원",
            state: "met",
            note: "자료상 확인",
          },
          {
            label: "관계·정서 지원",
            state: "unmet",
            note: "이 자원에는 없음",
          },
          {
            label: "주거 지원",
            state: "unmet",
            note: "이 자원에는 없음",
          },
          {
            label: "운영 상태",
            state: "met",
            note: "진행 중",
          },
          {
            label: "정원 여유",
            state: "met",
            note: "여유 있음 (36/40명)",
          },
          {
            label: "세부 신청 자격",
            state: "unknown",
            note: "기관 확인 필요",
          },
        ],
        beforeUse: ["신청 방법: 주민센터 추천 또는 기관 방문 신청", "이용자 부담금: 무료", "운영 기간: 2026.03.02 ~ 2026.12.18"],
        evidence: "상담 기록 4건 · 기본 정보(연령대·성별·지역) · 복지자원 등록 정보",
      },
      {
        rank: 3,
        resourceId: 6,
        resourceName: "스마트플러그 안전 확인",
        operatingOrgName: "우리복지관",
        status: "진행 중",
        tags: ["개포1동", "관계·정서 지원", "무료"],
        reason: "상담에서 확인한 '관계·정서 지원'에 맞는 자원이에요. 같은 동(개포1동)에서 운영해요. '식사 지원, 주거 지원'은 다른 자원으로 함께 살펴보세요.",
        checks: [
          {
            label: "개포1동 지원",
            state: "met",
            note: "같은 동 — 자료상 확인",
          },
          {
            label: "노년 대상",
            state: "met",
            note: "자료상 확인",
          },
          {
            label: "관계·정서 지원",
            state: "met",
            note: "자료상 확인",
          },
          {
            label: "식사 지원",
            state: "unmet",
            note: "이 자원에는 없음",
          },
          {
            label: "주거 지원",
            state: "unmet",
            note: "이 자원에는 없음",
          },
          {
            label: "운영 상태",
            state: "met",
            note: "진행 중",
          },
          {
            label: "정원 여유",
            state: "met",
            note: "여유 있음 (27/50명)",
          },
          {
            label: "세부 신청 자격",
            state: "unknown",
            note: "기관 확인 필요",
          },
        ],
        beforeUse: ["신청 방법: 담당 사회복지사 추천", "이용자 부담금: 무료", "운영 기간: 2026.07.01 ~ 2027.06.30"],
        evidence: "상담 기록 4건 · 기본 정보(연령대·성별·지역) · 복지자원 등록 정보",
      },
    ],
  },
]

const SUMMARY_BLOCKS: AgentBlock[] = [
  {
    kind: "text",
    text: "**강남구 2025년 12월** 고립 위험 현황을 요약했어요.",
  },
  {
    kind: "list",
    items: [
      "배경 취약성 4·5단계: 7개 동 (논현2동, 압구정동, 삼성1동, 대치1동, 역삼1동, 역삼2동, 수서동)",
      "행동 이상 4·5단계: 3개 동 (도곡1동, 도곡2동, 개포1동)",
      "전월보다 행동 이상 점수가 오른 동: 11개",
      "행동 이상 점수가 가장 높은 동: 도곡1동 (60.3점, 5단계)",
    ],
  },
  {
    kind: "text",
    text: "지도에서 동을 누르면 그 동의 인사이트 보고서를 볼 수 있어요.",
  },
]

const TOP_BLOCKS: AgentBlock[] = [
  {
    kind: "text",
    text: "2025년 12월 행동 이상 점수가 가장 많이 오른 동은 **도곡1동(+5.2점)**이에요.",
  },
  {
    kind: "list",
    items: ["도곡2동: +4.3점 (지금 4단계)", "개포1동: +3.4점 (지금 4단계)"],
  },
  {
    kind: "text",
    text: "지도에서 도곡1동을 누르면 원인을 설명한 인사이트 보고서를 볼 수 있어요.",
  },
]

const EXPLAIN_BLOCKS: AgentBlock[] = [
  {
    kind: "text",
    text: "개포1동의 행동이상 점수가 전월대비 3.4점 상승했어요.",
  },
  {
    kind: "text",
    text: "점수를 가장 많이 바꾼 요인은 다음과 같아요.",
  },
  {
    kind: "list",
    items: [
      "주말 활동이 주중보다 더 줄어듦 (+1.63)",
      "요일별 활동 패턴이 평소보다 고정적 (+0.97)",
      "요일 간 활동 편차 확대 (+0.47)",
    ],
  },
  {
    kind: "text",
    text: "쉽게 말해, 12월 들어 **주말에 동네 활동이 크게 줄었고** 요일마다 생활 리듬이 비슷하게 굳어졌어요. 한파와 연말 영향으로 가족 단위 외출이 줄어든 것이 가장 큰 이유로 보여요.",
  },
]

const TARGETS_BLOCKS: AgentBlock[] = [
  {
    kind: "text",
    text: "**개포1동**에서 먼저 살펴볼 대상을 보고서의 조치 제안으로 정리했어요.",
  },
  {
    kind: "list",
    items: [
      "정확한 타겟 확인: 대대적인 조사보다는 취약 가구를 빠르게 확인하는 게 먼저예요! 75세 이상 독거 어르신 중 11월에 돌봄 서비스가 종료된 가구를 한파가 오기 전에 파악해서, 'AI 안부전화'나 '스마트플러그' 관리 대상에 신속히 편입해 주세요.",
      "데이터 모니터링: 1월 데이터에서 주말 활동량이 원래대로 돌아오면 상황을 종결해도 좋아요. 하지만 행동이상 4단계가 계속 유지된다면 해당 지역을 '우선 검토 구역'으로 지정하는 것을 권장해 드려요.",
    ],
  },
  {
    kind: "text",
    text: "이 동에 내가 담당하는 사례자는 **3명**이에요 (중장년 1명, 노년 2명). '사례자 탐색'에서 이 동으로 찾아볼 수 있어요.",
  },
]

const HELP_BLOCKS: AgentBlock[] = [
  {
    kind: "text",
    text: "복지자원을 지역·연령·성별·정원·담당자로 찾을 수 있어요. 다른 기관의 자원도 함께 보여요.",
  },
]

const NAMED_BLOCKS: AgentBlock[] = [
  { kind: "text", text: "사례자 정보는 이름 없이 다뤄요. 사례자 상세 화면에서 **AI 맞춤 자원 추천**을 누르면 그 사례자에게 맞는 복지자원을 찾아 드려요." },
]

type SeedConversation = {
  memberId: number
  /** 마지막 대화일 */
  date: string
  turns: { question: string; blocks: AgentBlock[]; time: string }[]
}

const today = todayString()

const SEEDS: SeedConversation[] = [
  {
    memberId: 1,
    date: addDays(today, -3),
    turns: [{ question: "이 사례자에게 맞는 복지자원을 추천해 줘", blocks: RECOMMEND_BLOCKS, time: "10:12:05" }],
  },
  {
    memberId: 1,
    date: addDays(today, -12),
    turns: [
      { question: "고립 위험 현황을 요약해 줘", blocks: SUMMARY_BLOCKS, time: "14:03:11" },
      { question: "행동 이상이 가장 많이 오른 동은 어디야?", blocks: TOP_BLOCKS, time: "14:05:40" },
    ],
  },
  {
    memberId: 1,
    date: addDays(today, -40),
    turns: [{ question: "보고서의 주요 원인을 쉽게 설명해 줘", blocks: EXPLAIN_BLOCKS, time: "09:30:22" }],
  },
  {
    memberId: 1,
    date: addDays(today, -58),
    turns: [{ question: "○○○ 님한테 맞는 프로그램이 있을까?", blocks: NAMED_BLOCKS, time: "16:20:48" }],
  },
  {
    // 삭제 예정일이 2일 남음
    memberId: 1,
    date: addMonths(addDays(today, 2), -3),
    turns: [{ question: "이 동에서 먼저 살펴볼 대상은 누구야?", blocks: TARGETS_BLOCKS, time: "11:02:37" }],
  },
  {
    // 보관 기간이 지남 → 목록·조회에서 빠짐 (실제로는 매일 지우는 작업이 이미 지웠을 대화)
    memberId: 1,
    date: addMonths(addDays(today, -5), -3),
    turns: [{ question: "이 화면에서 무엇을 할 수 있어?", blocks: HELP_BLOCKS, time: "15:45:09" }],
  },
  {
    memberId: 2,
    date: addDays(today, -5),
    turns: [{ question: "고립 위험 현황을 요약해 줘", blocks: SUMMARY_BLOCKS, time: "13:20:15" }],
  },
]

export const seedAgentConversations: AgentConversation[] = SEEDS.map((seed, index) => ({
  conversationId: `conv-${index + 1}`,
  memberId: seed.memberId,
  firstQuestion: seed.turns[0].question,
  createdAt: `${seed.date} ${seed.turns[0].time}`,
  lastMessageAt: `${seed.date} ${seed.turns[seed.turns.length - 1].time}`,
}))

export const seedAgentTurns: AgentTurn[] = SEEDS.flatMap((seed, index) =>
  seed.turns.map((turn) => ({
    turnId: 0,
    conversationId: `conv-${index + 1}`,
    question: turn.question,
    blocks: turn.blocks,
    askedAt: `${seed.date} ${turn.time}`,
  })),
).map((turn, index) => ({ ...turn, turnId: index + 1 }))
