import { seedDongs } from "@/mock/seed/regions"
import type {
  CaseManager,
  CaseNumberSequence,
  CaseRecord,
  Consultation,
  ConsultationCategory,
  Gender,
} from "@/types/domain"

// 사례자·담당자·상담 기록 예시 데이터 (이름·생년월일 등은 모두 프로토타입용 가상 값)
//
// 우리복지관(orgId 1) 30명
// - 김지원(1) 담당 22명: 단독 17명, 박성민(2)과 공동 담당 5명 (모두 강남구 거주)
// - 박성민(2)만 담당 3명, 최상우(3)만 담당 3명, 정하늘(4)만 담당 2명 → 김지원 목록에는 안 보임
// - 2025년 등록 7명 (관리번호 2025-0001~0007)
// 햇살지역아동센터(orgId 3) 2명: 오서연(7) 담당. 관리번호가 우리복지관과 겹쳐도(2026-0001) 섞이지 않는지 확인용
//
// 관리번호(A-1): 기관마다, 최초 등록일의 연도별로 0001부터 등록일 순서대로 매긴다.

type CaseSeed = {
  orgId: number
  name: string
  birthDate: string
  gender: Gender
  sigunguCode: string
  dongName: string
  firstRegisteredAt: string
  managers: number[]
}

const GANGNAM = "11680"

const CASE_SEEDS: CaseSeed[] = [
  // 김지원 담당 (강남구)
  { orgId: 1, name: "김이음", birthDate: "1968-04-12", gender: "남", sigunguCode: GANGNAM, dongName: "역삼1동", firstRegisteredAt: "2025-07-02", managers: [1] },
  { orgId: 1, name: "박상아", birthDate: "1983-02-19", gender: "여", sigunguCode: GANGNAM, dongName: "개포1동", firstRegisteredAt: "2025-08-12", managers: [1] },
  { orgId: 1, name: "정승현", birthDate: "1998-06-03", gender: "남", sigunguCode: GANGNAM, dongName: "논현1동", firstRegisteredAt: "2025-09-03", managers: [1] },
  { orgId: 1, name: "김한수", birthDate: "1959-11-27", gender: "남", sigunguCode: GANGNAM, dongName: "대치2동", firstRegisteredAt: "2025-10-15", managers: [1] },
  { orgId: 1, name: "이영자", birthDate: "1946-03-08", gender: "여", sigunguCode: GANGNAM, dongName: "개포1동", firstRegisteredAt: "2025-11-20", managers: [1, 2] },
  { orgId: 1, name: "최민준", birthDate: "2009-05-14", gender: "남", sigunguCode: GANGNAM, dongName: "수서동", firstRegisteredAt: "2025-12-04", managers: [1] },
  { orgId: 1, name: "한순례", birthDate: "1941-09-30", gender: "여", sigunguCode: GANGNAM, dongName: "일원본동", firstRegisteredAt: "2026-01-08", managers: [1] },
  { orgId: 1, name: "오지환", birthDate: "1987-12-01", gender: "남", sigunguCode: GANGNAM, dongName: "역삼2동", firstRegisteredAt: "2026-01-22", managers: [1, 2] },
  { orgId: 1, name: "윤미경", birthDate: "1972-07-17", gender: "여", sigunguCode: GANGNAM, dongName: "도곡2동", firstRegisteredAt: "2026-02-10", managers: [1] },
  { orgId: 1, name: "서동훈", birthDate: "1964-01-25", gender: "남", sigunguCode: GANGNAM, dongName: "개포4동", firstRegisteredAt: "2026-03-03", managers: [1] },
  { orgId: 1, name: "강은비", birthDate: "2008-10-09", gender: "여", sigunguCode: GANGNAM, dongName: "세곡동", firstRegisteredAt: "2026-03-19", managers: [1] },
  { orgId: 1, name: "임채원", birthDate: "1993-04-28", gender: "여", sigunguCode: GANGNAM, dongName: "삼성2동", firstRegisteredAt: "2026-04-07", managers: [1, 2] },
  { orgId: 1, name: "조말순", birthDate: "1938-12-12", gender: "여", sigunguCode: GANGNAM, dongName: "개포1동", firstRegisteredAt: "2026-04-30", managers: [1] },
  { orgId: 1, name: "백승호", birthDate: "1979-08-05", gender: "남", sigunguCode: GANGNAM, dongName: "논현2동", firstRegisteredAt: "2026-05-21", managers: [1] },
  { orgId: 1, name: "남궁현", birthDate: "1955-02-14", gender: "남", sigunguCode: GANGNAM, dongName: "대치4동", firstRegisteredAt: "2026-06-11", managers: [1, 2] },
  { orgId: 1, name: "문지아", birthDate: "2011-03-02", gender: "여", sigunguCode: GANGNAM, dongName: "일원1동", firstRegisteredAt: "2026-07-09", managers: [1] },
  { orgId: 1, name: "홍성철", birthDate: "1969-06-22", gender: "남", sigunguCode: GANGNAM, dongName: "개포2동", firstRegisteredAt: "2026-08-18", managers: [1] },
  { orgId: 1, name: "신옥자", birthDate: "1944-05-05", gender: "여", sigunguCode: GANGNAM, dongName: "수서동", firstRegisteredAt: "2026-09-24", managers: [1, 2] },
  { orgId: 1, name: "차유진", birthDate: "1990-11-11", gender: "여", sigunguCode: GANGNAM, dongName: "역삼1동", firstRegisteredAt: "2026-10-20", managers: [1] },
  { orgId: 1, name: "이도현", birthDate: "1961-09-19", gender: "남", sigunguCode: GANGNAM, dongName: "대치1동", firstRegisteredAt: "2026-02-27", managers: [1] },
  { orgId: 1, name: "장복순", birthDate: "1949-01-03", gender: "여", sigunguCode: GANGNAM, dongName: "신사동", firstRegisteredAt: "2026-05-12", managers: [1] },
  { orgId: 1, name: "권태윤", birthDate: "2000-07-29", gender: "남", sigunguCode: GANGNAM, dongName: "압구정동", firstRegisteredAt: "2026-08-02", managers: [1] },
  // 다른 직원만 담당 (김지원 목록에는 안 보임)
  { orgId: 1, name: "송미라", birthDate: "1975-10-30", gender: "여", sigunguCode: GANGNAM, dongName: "청담동", firstRegisteredAt: "2025-09-29", managers: [2] },
  { orgId: 1, name: "노상철", birthDate: "1952-04-18", gender: "남", sigunguCode: GANGNAM, dongName: "압구정동", firstRegisteredAt: "2026-02-14", managers: [2] },
  { orgId: 1, name: "하은지", birthDate: "1996-08-21", gender: "여", sigunguCode: GANGNAM, dongName: "신사동", firstRegisteredAt: "2026-06-30", managers: [2] },
  { orgId: 1, name: "엄기순", birthDate: "1947-06-09", gender: "여", sigunguCode: GANGNAM, dongName: "삼성1동", firstRegisteredAt: "2026-03-25", managers: [3] },
  { orgId: 1, name: "진우석", birthDate: "1985-01-16", gender: "남", sigunguCode: GANGNAM, dongName: "대치1동", firstRegisteredAt: "2026-07-14", managers: [3] },
  { orgId: 1, name: "손다인", birthDate: "2007-12-24", gender: "여", sigunguCode: GANGNAM, dongName: "도곡1동", firstRegisteredAt: "2026-09-02", managers: [3] },
  { orgId: 1, name: "탁명호", birthDate: "1958-03-27", gender: "남", sigunguCode: GANGNAM, dongName: "개포3동", firstRegisteredAt: "2026-04-16", managers: [4] },
  { orgId: 1, name: "피은숙", birthDate: "1966-11-02", gender: "여", sigunguCode: GANGNAM, dongName: "역삼2동", firstRegisteredAt: "2026-08-27", managers: [4] },
  // 햇살지역아동센터
  { orgId: 3, name: "김하준", birthDate: "2014-02-11", gender: "남", sigunguCode: GANGNAM, dongName: "개포4동", firstRegisteredAt: "2026-03-10", managers: [7] },
  { orgId: 3, name: "이서윤", birthDate: "2013-09-07", gender: "여", sigunguCode: GANGNAM, dongName: "세곡동", firstRegisteredAt: "2026-05-06", managers: [7] },
]

/** 상담 기록을 만들 마지막 날짜 (이 날짜 이후 상담은 만들지 않음) */
const LAST_CONSULTATION_DATE = "2026-10-26"

/** 상담 기록이 하나도 없는 사례자 (최근 기록일 '-' 확인용) */
const NO_CONSULTATION_NAMES = new Set(["차유진"])

const PURPOSES = [
  "생활·교류 변화 확인",
  "지원 욕구 확인",
  "건강·식사 상태 점검",
  "복지자원 연계 안내",
  "정서 지원 상담",
  "주거 환경 확인",
]

const CONTENTS = [
  "최근 외출 빈도가 줄었다고 함. 주 1회 이상 안부 전화를 이어가기로 함.",
  "필요한 지원으로 식사와 말벗을 꼽음. 지역 내 연계 가능한 자원을 찾아보기로 함.",
  "끼니를 거르는 날이 있다고 함. 식사 지원 자원을 안내하고 다음 상담에서 확인하기로 함.",
  "안내한 프로그램 참여 의사를 밝힘. 신청 방법을 함께 확인함.",
  "가족과의 연락이 뜸해 외로움을 느낀다고 함. 정기 방문 일정을 잡음.",
  "집 안 정리가 어려운 상태. 주거 환경 개선 지원 가능 여부를 확인하기로 함.",
]

function findDongCode(sigunguCode: string, dongName: string): string {
  const dong = seedDongs.find((item) => item.sigunguCode === sigunguCode && item.dongName === dongName)
  if (!dong) throw new Error(`예시 데이터의 행정동을 찾을 수 없습니다: ${sigunguCode} ${dongName}`)
  return dong.dongCode
}

function addDays(date: string, days: number): string {
  const value = new Date(`${date}T00:00:00`)
  value.setDate(value.getDate() + days)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
}

/** 관리번호: 기관마다, 최초 등록일의 연도별로 등록일 순서대로 0001부터 */
function assignManagementNumbers(seeds: CaseSeed[]): Map<CaseSeed, string> {
  const result = new Map<CaseSeed, string>()
  const ordered = [...seeds].sort((a, b) => a.firstRegisteredAt.localeCompare(b.firstRegisteredAt))
  const counters = new Map<string, number>()
  for (const seed of ordered) {
    const year = seed.firstRegisteredAt.slice(0, 4)
    const key = `${seed.orgId}-${year}`
    const next = (counters.get(key) ?? 0) + 1
    counters.set(key, next)
    result.set(seed, `${year}-${String(next).padStart(4, "0")}`)
  }
  return result
}

const managementNumbers = assignManagementNumbers(CASE_SEEDS)

export const seedCases: CaseRecord[] = CASE_SEEDS.map((seed, index) => ({
  caseId: index + 1,
  orgId: seed.orgId,
  managementNo: managementNumbers.get(seed) ?? "",
  name: seed.name,
  birthDate: seed.birthDate,
  gender: seed.gender,
  dongCode: findDongCode(seed.sigunguCode, seed.dongName),
  firstRegisteredAt: seed.firstRegisteredAt,
}))

export const seedCaseManagers: CaseManager[] = CASE_SEEDS.flatMap((seed, index) =>
  seed.managers.map((memberId) => ({ caseId: index + 1, memberId })),
)

/** 관리번호 일련번호: 예시 데이터에서 기관·연도별로 마지막으로 쓴 번호 */
export const seedCaseNumberSequences: CaseNumberSequence[] = []
for (const seed of CASE_SEEDS) {
  const [year, no] = (managementNumbers.get(seed) ?? "").split("-")
  const found = seedCaseNumberSequences.find((item) => item.orgId === seed.orgId && item.year === year)
  if (found) found.lastNo = Math.max(found.lastNo, Number(no))
  else seedCaseNumberSequences.push({ orgId: seed.orgId, year, lastNo: Number(no) })
}

/** 상담 분류: 첫 상담은 초기상담, 이후는 정기상담 위주로 중기·종료·긴급·기타를 섞는다 */
function categoryOf(index: number, round: number): { category: ConsultationCategory; categoryEtc: string | null } {
  if (round === 0) return { category: "초기상담", categoryEtc: null }
  if (round === 1 && index % 7 === 3) return { category: "기타", categoryEtc: "가정 방문" }
  if (round === 1 && index % 3 === 0) return { category: "중기상담", categoryEtc: null }
  if (round === 2 && index % 5 === 0) return { category: "긴급상담", categoryEtc: null }
  if (round === 3 && index % 4 === 1) return { category: "종료상담", categoryEtc: null }
  return { category: "정기상담", categoryEtc: null }
}

// 상담 기록: 최초 등록일에 초기상담을 하고, 그 뒤 약 5주마다 한 번씩 (사례자마다 최대 4건)
export const seedConsultations: Consultation[] = CASE_SEEDS.flatMap((seed, index) => {
  if (NO_CONSULTATION_NAMES.has(seed.name)) return []
  const caseId = index + 1
  const records: Omit<Consultation, "consultationId">[] = []
  for (let round = 0; round < 4; round += 1) {
    const consultedAt = addDays(seed.firstRegisteredAt, round * 35 + (round === 0 ? 0 : index % 6))
    if (consultedAt > LAST_CONSULTATION_DATE) break
    const pick = (index + round) % PURPOSES.length
    records.push({
      caseId,
      consultedAt,
      purpose: round === 0 ? "초기 생활 상태 확인" : PURPOSES[pick],
      ...categoryOf(index, round),
      content: round === 0 ? "첫 상담. 생활 상태와 연락 가능한 가족·이웃을 확인함." : CONTENTS[pick],
      recorderMemberId: seed.managers[round % seed.managers.length],
    })
  }
  return records
}).map((record, index) => ({ consultationId: index + 1, ...record }))
