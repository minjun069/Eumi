import type { MyInfo, MyInfoPatch } from "@/api/myApi"
import { isValidPassword, isValidPhone, PASSWORD_RULE_TEXT } from "@/utils/validation"

// 마이페이지 입력 확인 (화면에서 API를 부르기 전에 확인한다. 서버도 같은 조건을 다시 검사한다)

// ── 5.1.2 내 정보 수정 (직함·전화번호) ──

/** MyInfoPatch.title maxLength */
export const TITLE_MAX = 100

export type MyInfoForm = { title: string; phone: string }
export type MyInfoField = keyof MyInfoForm
export type MyInfoErrors = Partial<Record<MyInfoField, string>>

export const formOfMyInfo = (info: MyInfo): MyInfoForm => ({ title: info.title ?? "", phone: info.phone ?? "" })

export function validateMyInfoForm(form: MyInfoForm): MyInfoErrors {
  const errors: MyInfoErrors = {}
  if (form.title.trim().length > TITLE_MAX) errors.title = `${TITLE_MAX}자 이내로 입력하세요.`
  if (form.phone.trim() && !isValidPhone(form.phone.trim())) {
    errors.phone = "전화번호 형식이 올바르지 않습니다. (예: 010-1234-5678)"
  }
  return errors
}

/** 바뀐 항목만 보낸다. 비운 칸은 null (전화 빈 문자열은 계약상 보내지 않는다). 바뀐 것이 없으면 null */
export function toMyInfoPatch(form: MyInfoForm, info: MyInfo): MyInfoPatch | null {
  const patch: MyInfoPatch = {}
  const title = form.title.trim() || null
  const phone = form.phone.trim() || null
  if (title !== info.title) patch.title = title
  if (phone !== info.phone) patch.phone = phone
  return Object.keys(patch).length > 0 ? patch : null
}

// ── 5.1.3 비밀번호 변경 ──

/** PasswordChangeRequest maxLength */
export const PASSWORD_MAX = 128

export type PasswordForm = { currentPassword: string; newPassword: string; confirmPassword: string }
export type PasswordField = keyof PasswordForm
export type PasswordErrors = Partial<Record<PasswordField, string>>

export const EMPTY_PASSWORD_FORM: PasswordForm = { currentPassword: "", newPassword: "", confirmPassword: "" }

export const PASSWORD_MESSAGES = {
  currentMismatch: "현재 비밀번호가 맞지 않습니다.",
  sameAsCurrent: "현재 비밀번호와 다른 비밀번호를 입력하세요.",
} as const

/** 비밀번호는 앞뒤 공백도 그대로 쓴다 (trim하지 않는다) */
export function validatePasswordForm(form: PasswordForm): PasswordErrors {
  const errors: PasswordErrors = {}
  if (!form.currentPassword) errors.currentPassword = "현재 비밀번호를 입력하세요."
  else if (form.currentPassword.length > PASSWORD_MAX) errors.currentPassword = `${PASSWORD_MAX}자 이내로 입력하세요.`
  if (!form.newPassword) errors.newPassword = "새 비밀번호를 입력하세요."
  else if (!isValidPassword(form.newPassword) || form.newPassword.length > PASSWORD_MAX)
    errors.newPassword = `비밀번호는 ${PASSWORD_RULE_TEXT}해야 합니다. (${PASSWORD_MAX}자까지)`
  else if (form.newPassword === form.currentPassword) errors.newPassword = PASSWORD_MESSAGES.sameAsCurrent
  if (!form.confirmPassword) errors.confirmPassword = "새 비밀번호를 한 번 더 입력하세요."
  else if (form.newPassword !== form.confirmPassword) errors.confirmPassword = "새 비밀번호가 일치하지 않습니다."
  return errors
}
