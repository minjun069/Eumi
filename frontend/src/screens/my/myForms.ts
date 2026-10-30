import { DEMO_PASSWORD } from "@/mock/seed/members"
import { isValidPassword, isValidPhone, PASSWORD_RULE_TEXT } from "@/utils/validation"

// 마이페이지 입력 확인과 예시값 (화면에서 API를 부르기 전에 확인)

// ── 5.1.2 내 정보 수정 (직함·전화번호, M2-A) ──

export type MyInfoForm = { title: string; phone: string }

export function validateMyInfoForm(form: MyInfoForm): Partial<Record<keyof MyInfoForm, string>> {
  const errors: Partial<Record<keyof MyInfoForm, string>> = {}
  if (form.phone.trim() && !isValidPhone(form.phone.trim())) {
    errors.phone = "전화번호 형식이 올바르지 않습니다. (예: 010-1234-5678)"
  }
  return errors
}

// ── 5.1.3 비밀번호 변경 ──

export type PasswordForm = { currentPassword: string; newPassword: string; confirmPassword: string }

/** 예시값: 예시 계정의 비밀번호 → 새 비밀번호 */
export const EXAMPLE_NEW_PASSWORD = "ieum5678!"

export const examplePasswordForm: PasswordForm = {
  currentPassword: DEMO_PASSWORD,
  newPassword: EXAMPLE_NEW_PASSWORD,
  confirmPassword: EXAMPLE_NEW_PASSWORD,
}

/**
 * 처음 채울 값. 임시 비밀번호로 로그인했으면 현재 비밀번호에 그 임시 비밀번호를 채운다
 * (프로토타입 예시값. 실제 화면은 임시 비밀번호를 알 수 없어 비워 둔다 — 메일로만 받음)
 */
export function initialPasswordForm(tempPassword: string | null): PasswordForm {
  return tempPassword ? { ...examplePasswordForm, currentPassword: tempPassword } : examplePasswordForm
}

/** 개발용 채우기. base = 지금 상황의 정상 값 (임시 비밀번호로 로그인했으면 현재 비밀번호가 임시 비밀번호) */
export function passwordFills(base: PasswordForm): { label: string; form: PasswordForm }[] {
  return [
    { label: "정상", form: base },
    { label: "현재 비밀번호 틀림", form: { ...base, currentPassword: "wrong-1234!" } },
    { label: "새 비밀번호 규칙 위반", form: { ...base, newPassword: "ieum5678", confirmPassword: "ieum5678" } },
    { label: "새 비밀번호 확인 불일치", form: { ...base, confirmPassword: "ieum5679!" } },
    { label: "현재와 같은 비밀번호", form: { ...base, newPassword: base.currentPassword, confirmPassword: base.currentPassword } },
    { label: "빈칸", form: { currentPassword: "", newPassword: "", confirmPassword: "" } },
  ]
}

export function validatePasswordForm(form: PasswordForm): Partial<Record<keyof PasswordForm, string>> {
  const errors: Partial<Record<keyof PasswordForm, string>> = {}
  if (!form.currentPassword) errors.currentPassword = "현재 비밀번호를 입력하세요."
  if (!form.newPassword) errors.newPassword = "새 비밀번호를 입력하세요."
  else if (!isValidPassword(form.newPassword)) errors.newPassword = `비밀번호는 ${PASSWORD_RULE_TEXT}해야 합니다.`
  else if (form.newPassword === form.currentPassword) errors.newPassword = "현재 비밀번호와 다른 비밀번호를 입력하세요."
  if (!form.confirmPassword) errors.confirmPassword = "새 비밀번호를 한 번 더 입력하세요."
  else if (form.newPassword !== form.confirmPassword) errors.confirmPassword = "새 비밀번호가 일치하지 않습니다."
  return errors
}
