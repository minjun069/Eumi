// 날짜·시각 표시 (이 PC의 시간대 기준)

const pad = (value: number) => String(value).padStart(2, "0")

/** 2026-10-27 */
export function formatDate(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** 2026-10-27 15:12:30 */
export function formatDateTime(date: Date): string {
  return `${formatDate(date)} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** 남은 시간 09:42 (음수면 00:00) */
export function formatRemaining(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.ceil(milliseconds / 1000))
  return `${pad(Math.floor(totalSeconds / 60))}:${pad(totalSeconds % 60)}`
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

/** 날짜 문자열에 날 수를 더한다 (2026-10-27 + 2 → 2026-10-29) */
export function addDays(value: string, days: number): string {
  const date = new Date(`${value.slice(0, 10)}T00:00:00`)
  date.setDate(date.getDate() + days)
  return formatDate(date)
}

/** 날짜 문자열에 달 수를 더한다. 그 달에 없는 날이면 말일로 맞춘다 (2026-11-30 - 3달 → 2026-08-30, 05-31 + 1달 → 06-30) */
export function addMonths(value: string, months: number): string {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number)
  const first = new Date(year, month - 1 + months, 1)
  const lastDay = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate()
  return formatDate(new Date(first.getFullYear(), first.getMonth(), Math.min(day, lastDay)))
}

/** 두 날짜 사이의 날 수 (to - from) */
export function daysBetween(from: string, to: string): number {
  const start = new Date(`${from.slice(0, 10)}T00:00:00`).getTime()
  const end = new Date(`${to.slice(0, 10)}T00:00:00`).getTime()
  return Math.round((end - start) / 86_400_000)
}

/** 지금 시각 2026-10-27 15:12:30 (저장 시각에 쓴다) */
export function nowString(): string {
  return formatDateTime(new Date())
}
