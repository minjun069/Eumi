import type { AgeGroup } from "@/types/domain"

// 만 나이와 연령대 (3.3.1 기준, 사례자·복지자원 공통)

/** 오늘 기준 만 나이 */
export function ageOn(birthDate: string, today: Date = new Date()): number {
  const [year, month, day] = birthDate.split("-").map(Number)
  let age = today.getFullYear() - year
  const beforeBirthday =
    today.getMonth() + 1 < month || (today.getMonth() + 1 === month && today.getDate() < day)
  if (beforeBirthday) age -= 1
  return age
}

/** 청소년 20세 미만, 청년 20세 이상 40세 미만, 중장년 40세 이상 60세 미만, 노년 60세 이상 */
export function ageGroupOf(age: number): AgeGroup {
  if (age < 20) return "청소년"
  if (age < 40) return "청년"
  if (age < 60) return "중장년"
  return "노년"
}

export const AGE_GROUPS: AgeGroup[] = ["청소년", "청년", "중장년", "노년"]
