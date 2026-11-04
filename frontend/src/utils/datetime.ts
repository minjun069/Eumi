// 날짜 입력 (이 PC의 시간대 기준)

const pad = (value: number) => String(value).padStart(2, "0")

/** 2026-10-27 */
export function formatDate(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** 오늘 날짜 2026-10-27 (날짜 입력칸의 기본값·미래 날짜 확인에 쓴다) */
export function todayString(): string {
  return formatDate(new Date())
}

/** YYYY-MM-DD 형식의 실제 있는 날짜인지 */
export function isValidDateString(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(`${value}T00:00:00`)
  return !Number.isNaN(date.getTime()) && formatDate(date) === value
}
