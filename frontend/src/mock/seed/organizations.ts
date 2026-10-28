import type { Organization } from "@/types/domain"

// 소속기관 예시 데이터 (기관명·도메인은 프로토타입용 가상 값)
// - 공식 도메인이 있는 기관: 가입 이메일 도메인이 일치해야 인증 메일 발송
// - 공식 도메인이 없는 기관(officialDomain: null): 이메일 인증만으로 가입
// - 관할지역은 시군구 단위로 등록 (실제 서비스 지역인 강남구 5곳, 춘천시 5곳)

export const seedOrganizations: Organization[] = [
  {
    orgId: 1,
    orgName: "우리복지관",
    officialDomain: "woori.or.kr",
    jurisdictionSigunguCode: "11680",
  },
  {
    orgId: 2,
    orgName: "푸른마을복지관",
    officialDomain: "pureun.or.kr",
    jurisdictionSigunguCode: "51110",
  },
  {
    orgId: 3,
    orgName: "햇살지역아동센터",
    officialDomain: null,
    jurisdictionSigunguCode: "11680",
  },
  {
    orgId: 4,
    orgName: "어울림노인복지관",
    officialDomain: "eoullim.or.kr",
    jurisdictionSigunguCode: "51110",
  },
  {
    orgId: 5,
    orgName: "강남늘봄종합사회복지관",
    officialDomain: "neulbom.or.kr",
    jurisdictionSigunguCode: "11680",
  },
  {
    orgId: 6,
    orgName: "개포한빛복지관",
    officialDomain: "hanbit-welfare.or.kr",
    jurisdictionSigunguCode: "11680",
  },
  {
    orgId: 7,
    orgName: "춘천다온지역아동센터",
    officialDomain: null,
    jurisdictionSigunguCode: "51110",
  },
  {
    orgId: 8,
    orgName: "소양바른복지관",
    officialDomain: "bareun.or.kr",
    jurisdictionSigunguCode: "51110",
  },
  {
    orgId: 9,
    orgName: "수서바다마을복지관",
    officialDomain: "badamaeul.or.kr",
    jurisdictionSigunguCode: "11680",
  },
  {
    orgId: 10,
    orgName: "호반새싹지역아동센터",
    officialDomain: null,
    jurisdictionSigunguCode: "51110",
  },
]
