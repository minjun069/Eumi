import type { SupportAgeGroup, SupportGender } from "@/types/domain"

// 3.3.2 문서 기반 자동 입력 예시 결과. 프로토타입은 PDF를 실제로 읽지 않고, 파일 이름으로 예시 결과를 고른다.
// - 이름에 '읽기불가'가 있으면: 읽지 못함 (스캔 이미지 등)
// - 이름에 '일부'가 있으면: 일부 항목만 찾음
// - 그 밖의 PDF: 모든 항목을 찾음
// 담당자·상태·실제 참여자 수는 문서에서 뽑지 않는다 (등록하는 사람이 정함).

/** 문서에서 뽑아내는 항목 (찾지 못하면 null) */
export type DocumentExtract = {
  resourceName: string | null
  operatingOrgName: string | null
  target: string | null
  supportAgeGroups: SupportAgeGroup[] | null
  supportGender: SupportGender | null
  /** 지역 이름을 행정동 코드로 바꾼 값. 시군구만 찾으면 dongCode는 null */
  sigunguCode: string | null
  dongCode: string | null
  periodStart: string | null
  periodEnd: string | null
  fee: number | null
  capacity: number | null
  supportContent: string | null
  applyMethod: string | null
}

export const FULL_EXTRACT: DocumentExtract = {
  resourceName: "어르신 건강 걷기 교실",
  operatingOrgName: "강남구보건소",
  target: "65세 이상 지역 어르신",
  supportAgeGroups: ["노년"],
  supportGender: "무관",
  sigunguCode: "11680",
  dongCode: "1168066000",
  periodStart: "2026-11-02",
  periodEnd: "2027-03-31",
  fee: 0,
  capacity: 25,
  supportContent: "주 2회 양재천 걷기와 스트레칭, 매회 혈압 측정",
  applyMethod: "보건소 방문 또는 전화 신청",
}

/** 지원 성별·지역·이용자 부담금·정원·신청 방법을 찾지 못함 */
export const PARTIAL_EXTRACT: DocumentExtract = {
  resourceName: "청소년 진로 멘토링",
  operatingOrgName: "강남구청소년수련관",
  target: "진로를 고민하는 중·고등학생",
  supportAgeGroups: ["청소년"],
  supportGender: null,
  sigunguCode: null,
  dongCode: null,
  periodStart: "2026-11-09",
  periodEnd: "2027-02-19",
  fee: null,
  capacity: null,
  supportContent: "대학생 멘토와 격주 1:1 진로 상담",
  applyMethod: null,
}
