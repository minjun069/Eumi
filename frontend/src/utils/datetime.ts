// 날짜 입력 (이 PC의 시간대 기준)

const pad = (value: number) => String(value).padStart(2, "0")

/** 2026-10-27 */
export function formatDate(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** 남은 시간 mm:ss (인증 코드 남은 시간). 0 아래는 00:00 */
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

// 서버 일시 표시 (서울 기준). 서버는 UTC(…Z)로 보내기도 하므로 글자를 잘라 쓰지 않는다
const SEOUL_DATE_TIME = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
})

/** 2026-10-30T01:00:00Z → 2026-10-30 10:00 (서울) */
export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : SEOUL_DATE_TIME.format(date)
}

/** 오늘부터 그 날짜(YYYY-MM-DD)까지 남은 날 수 (오늘이면 0) */
export function daysUntil(date: string): number {
  const [year, month, day] = date.split("-").map(Number)
  const now = new Date()
  return Math.round((Date.UTC(year, month - 1, day) - Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())) / 86_400_000)
}
