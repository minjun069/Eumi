import { db } from "@/mock/db"

// 개발용 '메일함'. 실제 메일을 보내지 않으므로, 발송된 인증 코드를 개발용 영역에서 보여 주고
// 유효 시간을 지나게 만드는 데 쓴다. (서비스 화면에서는 쓰지 않는다)

function latestVerification(email: string) {
  return db.emailVerifications.find((item) => item.email === email && !item.replaced)
}

/** 이 이메일로 마지막에 발송된 인증 코드 */
export function peekVerificationCode(email: string): string | null {
  return latestVerification(email)?.code ?? null
}

/** 마지막 인증 코드의 유효 시간을 지금 끝나게 만든다 */
export function expireVerification(email: string): boolean {
  const verification = latestVerification(email)
  if (!verification) return false
  verification.expiresAt = Date.now() - 1
  return true
}

/** 이 이메일 회원에게 발급된 임시 비밀번호 (비밀번호 찾기 1.3.1) */
export function peekTempPassword(email: string): string | null {
  return db.members.find((member) => member.email === email)?.tempPassword ?? null
}

/** 이 이메일 회원의 임시 비밀번호가 발급 후 24시간이 지났는지 */
export function isTempPasswordExpired(email: string): boolean {
  const member = db.members.find((item) => item.email === email)
  if (!member?.tempPassword || member.tempPasswordIssuedAt === null) return false
  return Date.now() - member.tempPasswordIssuedAt >= 24 * 60 * 60 * 1000
}

/** 이 이메일 회원의 임시 비밀번호를 발급한 지 24시간이 지난 것으로 만든다 */
export function expireTempPassword(email: string): boolean {
  const member = db.members.find((item) => item.email === email)
  if (!member?.tempPassword) return false
  member.tempPasswordIssuedAt = Date.now() - 24 * 60 * 60 * 1000 - 1000
  return true
}
