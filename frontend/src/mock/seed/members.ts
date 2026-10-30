import type { Member } from "@/types/domain"

// 회원 예시 데이터 (이름·이메일은 프로토타입용 가상 값)
// 우리복지관(orgId 1)에 여러 명을 두어 담당자/비담당자, 퇴사자, 임시 비밀번호 상황을 재현한다.
// 다른 기관 회원(한도윤·오서연·임채원·배준호·문정희)은 다른 기관 자료·복지자원 담당자 예시에 쓴다.

export const DEMO_PASSWORD = "ieum1234!"

/** 로그인 화면에 미리 채워 두는 기본 계정 */
export const DEMO_LOGIN = {
  email: "kim.jiwon@woori.or.kr",
  password: DEMO_PASSWORD,
}

/** 회원가입 화면에 미리 채워 두는 새 회원 예시 (우리복지관, 아직 가입하지 않은 이메일) */
export const DEMO_SIGNUP = {
  orgKeyword: "우리복지관",
  email: "yoon.harin@woori.or.kr",
  name: "윤하린",
  password: "ieum2026!",
  title: "사회복지사",
  phone: "010-4821-7730",
}

/** 개발용 영역 '예외 상황'에서 회원가입 기관·이메일을 채우는 예시 */
export const SIGNUP_EXAMPLES = [
  { label: "정상 (우리복지관)", orgName: "우리복지관", email: "yoon.harin@woori.or.kr" },
  { label: "도메인 불일치", orgName: "우리복지관", email: "yoon.harin@gmail.com" },
  { label: "공식 도메인 없는 기관", orgName: "햇살지역아동센터", email: "harin.yoon@gmail.com" },
  { label: "이미 가입된 이메일", orgName: "우리복지관", email: "kim.jiwon@woori.or.kr" },
  { label: "탈퇴 회원 이메일", orgName: "우리복지관", email: "lee.sujin@woori.or.kr" },
]

/** 개발용 영역 '예외 상황'에서 로그인 입력칸을 채우는 예시 */
export const LOGIN_EXAMPLES = [
  { label: "정상 (김지원)", email: "kim.jiwon@woori.or.kr", password: DEMO_PASSWORD },
  { label: "임시 비밀번호 (정하늘)", email: "jung.haneul@woori.or.kr", password: "TEMP-7Q2K" },
  { label: "탈퇴한 계정 (이수진)", email: "lee.sujin@woori.or.kr", password: DEMO_PASSWORD },
  { label: "틀린 비밀번호", email: "kim.jiwon@woori.or.kr", password: "wrong-1234" },
  // 임시 비밀번호를 받은 회원이 기존 비밀번호로 로그인 → 임시 비밀번호가 지워진다
  { label: "기존 비밀번호 (정하늘)", email: "jung.haneul@woori.or.kr", password: DEMO_PASSWORD },
]

/** 비밀번호 찾기 화면에 미리 채워 두는 예시 (기본 계정 김지원이 아닌 최상우) */
export const DEMO_PASSWORD_FIND = {
  email: "choi.sangwoo@woori.or.kr",
  name: "최상우",
}

/** 개발용 영역 '예외 상황'에서 비밀번호 찾기 입력칸을 채우는 예시 */
export const PASSWORD_FIND_EXAMPLES = [
  { label: "정상 (최상우)", email: "choi.sangwoo@woori.or.kr", name: "최상우" },
  { label: "이름 불일치", email: "choi.sangwoo@woori.or.kr", name: "최상윤" },
  { label: "가입되지 않은 이메일", email: "no.account@woori.or.kr", name: "홍길동" },
  { label: "탈퇴 회원 (이수진)", email: "lee.sujin@woori.or.kr", name: "이수진" },
]

export const seedMembers: Member[] = [
  {
    memberId: 1,
    name: "김지원",
    email: "kim.jiwon@woori.or.kr",
    password: DEMO_PASSWORD,
    orgId: 1,
    title: "사회복지사",
    phone: "010-2481-3307",
    tempPassword: null,
    tempPasswordIssuedAt: null,
    createdAt: "2026-03-02",
    withdrawnAt: null,
  },
  {
    memberId: 2,
    name: "박성민",
    email: "park.sungmin@woori.or.kr",
    password: DEMO_PASSWORD,
    orgId: 1,
    title: "팀장",
    phone: "010-5520-1184",
    tempPassword: null,
    tempPasswordIssuedAt: null,
    createdAt: "2026-03-02",
    withdrawnAt: null,
  },
  {
    memberId: 3,
    name: "최상우",
    email: "choi.sangwoo@woori.or.kr",
    password: DEMO_PASSWORD,
    orgId: 1,
    // 직함은 선택 항목이라 비어 있는 경우도 둔다
    title: null,
    phone: null,
    tempPassword: null,
    tempPasswordIssuedAt: null,
    createdAt: "2026-04-15",
    withdrawnAt: null,
  },
  {
    memberId: 4,
    name: "정하늘",
    email: "jung.haneul@woori.or.kr",
    password: DEMO_PASSWORD,
    orgId: 1,
    title: "사회복지사",
    phone: "010-7731-0926",
    // 비밀번호 찾기로 2시간 전에 임시 비밀번호를 받은 상태 (기존 비밀번호도 그대로 쓸 수 있음)
    tempPassword: "TEMP-7Q2K",
    tempPasswordIssuedAt: Date.now() - 2 * 60 * 60 * 1000,
    createdAt: "2026-05-20",
    withdrawnAt: null,
  },
  {
    memberId: 5,
    name: "이수진",
    email: "lee.sujin@woori.or.kr",
    password: DEMO_PASSWORD,
    orgId: 1,
    title: "사회복지사",
    phone: "010-3309-4412",
    tempPassword: null,
    tempPasswordIssuedAt: null,
    createdAt: "2026-03-02",
    // 탈퇴한 회원 (담당 복지자원에는 '퇴사자'로 표시)
    withdrawnAt: "2026-09-30",
  },
  {
    memberId: 6,
    name: "한도윤",
    email: "han.doyun@pureun.or.kr",
    password: DEMO_PASSWORD,
    orgId: 2,
    title: "사회복지사",
    phone: "010-6612-7350",
    tempPassword: null,
    tempPasswordIssuedAt: null,
    createdAt: "2026-04-01",
    withdrawnAt: null,
  },
  {
    memberId: 7,
    name: "오서연",
    email: "sunny.center@gmail.com",
    password: DEMO_PASSWORD,
    orgId: 3,
    title: "센터장",
    phone: "010-9024-5561",
    tempPassword: null,
    tempPasswordIssuedAt: null,
    createdAt: "2026-06-11",
    withdrawnAt: null,
  },
  // 다른 기관 복지자원의 담당자 (6단계 추가)
  {
    memberId: 8,
    name: "임채원",
    email: "lim.chaewon@neulbom.or.kr",
    password: DEMO_PASSWORD,
    orgId: 5,
    title: "사회복지사",
    phone: "010-3348-1902",
    tempPassword: null,
    tempPasswordIssuedAt: null,
    createdAt: "2026-05-12",
    withdrawnAt: null,
  },
  {
    memberId: 9,
    name: "배준호",
    email: "bae.junho@hanbit-welfare.or.kr",
    password: DEMO_PASSWORD,
    orgId: 6,
    title: "팀장",
    phone: "010-7720-4415",
    tempPassword: null,
    tempPasswordIssuedAt: null,
    createdAt: "2026-04-20",
    withdrawnAt: null,
  },
  {
    memberId: 10,
    name: "문정희",
    email: "moon.junghee@eoullim.or.kr",
    password: DEMO_PASSWORD,
    orgId: 4,
    title: "사회복지사",
    phone: "010-5531-2867",
    tempPassword: null,
    tempPasswordIssuedAt: null,
    createdAt: "2026-03-16",
    withdrawnAt: null,
  },
]
