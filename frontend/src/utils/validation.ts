// 화면에서 API를 부르기 전에 하는 입력 확인

/** 이메일 형식 (아이디@도메인.최상위도메인) */
export function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
}

/** 이메일의 도메인 부분 (kim@woori.or.kr → woori.or.kr) */
export function emailDomain(value: string): string {
  return value.split("@")[1]?.toLowerCase() ?? ""
}

/** 비밀번호 규칙 (S5-A): 8자 이상, 영문·숫자·특수문자 모두 포함. 회원가입·비밀번호 변경 공통 */
export const PASSWORD_RULE_TEXT = "8자 이상, 영문·숫자·특수문자를 모두 포함"

export function isValidPassword(value: string): boolean {
  return (
    value.length >= 8 &&
    /[A-Za-z]/.test(value) &&
    /\d/.test(value) &&
    /[^A-Za-z0-9]/.test(value)
  )
}

/** 휴대전화 번호 형식 010-1234-5678 */
export function isValidPhone(value: string): boolean {
  return /^01[016789]-\d{3,4}-\d{4}$/.test(value)
}

/** 인증 코드 6자리 숫자 */
export function isValidVerificationCode(value: string): boolean {
  return /^\d{6}$/.test(value)
}
