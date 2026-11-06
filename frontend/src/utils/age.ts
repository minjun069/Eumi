import type { AgeGroup } from "@/api/caseApi"

// 만 나이와 연령대. 서버가 돌려주는 age·ageGroup과 같은 기준이다 (openapi CaseListItem.ageGroup).
// 화면에서는 입력 중인 생년월일의 미리 보기에만 쓴다.

/** 오늘 기준 만 나이 */
export function ageOn(birthDate: string, today: Date = new Date()): number {
  const [year, month, day] = birthDate.split("-").map(Number)
  let age = today.getFullYear() - year
  const beforeBirthday =
    today.getMonth() + 1 < month || (today.getMonth() + 1 === month && today.getDate() < day)
  if (beforeBirthday) age -= 1
  return age
}

/** 18세 이하 청소년, 19~39세 청년, 40~64세 중장년, 65세 이상 노년 */
export function ageGroupOf(age: number): AgeGroup {
  if (age <= 18) return "청소년"
  if (age <= 39) return "청년"
  if (age <= 64) return "중장년"
  return "노년"
}

export const AGE_GROUPS: AgeGroup[] = ["청소년", "청년", "중장년", "노년"]
