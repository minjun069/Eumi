import "@/styles/detail.css"
import "@/styles/form.css"
import "@/styles/my.css"
import { useMutation } from "@tanstack/react-query"
import { useState, type FormEvent, type ReactNode } from "react"
import { useNavigate } from "react-router"
import { errorMessage, isApiError } from "@/api/errors"
import { myApi } from "@/api/myApi"
import { FieldError } from "@/components/common/FieldError"
import { PasswordInput } from "@/components/common/PasswordInput"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { fieldErrorsOf } from "@/screens/case/caseErrors"
import {
  EMPTY_PASSWORD_FORM,
  PASSWORD_MESSAGES,
  validatePasswordForm,
  type PasswordErrors,
  type PasswordField,
  type PasswordForm,
} from "@/screens/my/myForms"
import { completeLogin } from "@/session/sessionActions"
import { useSession } from "@/session/sessionStore"
import { leaveGuard, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"
import { PASSWORD_RULE_TEXT } from "@/utils/validation"

/** 서버 fieldErrors의 field → 입력칸 */
const PASSWORD_FIELDS: Record<string, PasswordField> = { currentPassword: "currentPassword", newPassword: "newPassword" }

/**
 * 5.1.3 비밀번호 변경 (API-32): 현재 비밀번호 확인 → 새 비밀번호 (규칙은 회원가입과 같음, 앞뒤 공백도 그대로).
 * - 임시 비밀번호로 로그인했으면 이 화면만 쓸 수 있다(RequireAuth). '현재 비밀번호'에 메일로 받은 임시 비밀번호를 넣는다
 * - 성공하면 서버가 다른 기기의 로그인을 모두 끝내고 현재 세션 ID를 바꾼다. 응답의 user로 로그인 정보를 갱신하고
 *   (임시 비밀번호 제한 해제) CSRF 토큰을 다시 준비한다. 임시 비밀번호로 왔으면 첫 화면, 아니면 마이페이지로
 */
export function PasswordChangeScreen() {
  const session = useSession()
  const locked = session.status === "authenticated" && session.profile.mustChangePassword
  // 같은 화면에서 임시 비밀번호 제한 상태가 바뀌면 입력을 처음부터 다시 그린다
  return <PasswordChangeForm key={locked ? "temp" : "normal"} locked={locked} />
}

function PasswordChangeForm({ locked }: { locked: boolean }) {
  const navigate = useNavigate()
  const [form, setForm] = useState<PasswordForm>(EMPTY_PASSWORD_FORM)
  const [showErrors, setShowErrors] = useState(false)
  const [serverErrors, setServerErrors] = useState<PasswordErrors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const changePassword = useMutation({ mutationFn: myApi.changePassword })

  const dirty = JSON.stringify(form) !== JSON.stringify(EMPTY_PASSWORD_FORM)
  useLeaveGuard(dirty)
  const errors = validatePasswordForm(form)
  const visible: PasswordErrors = showErrors ? { ...serverErrors, ...errors } : serverErrors

  const update = (patch: Partial<PasswordForm>) => {
    setForm({ ...form, ...patch })
    setServerErrors({})
    setSubmitError(null)
  }

  const fail = (error: unknown) => {
    if (!isApiError(error)) {
      setSubmitError(errorMessage(error))
      return
    }
    switch (error.code) {
      // 임시 비밀번호가 만료된 경우도 이 코드다
      case "CURRENT_PASSWORD_MISMATCH":
        setServerErrors({ currentPassword: PASSWORD_MESSAGES.currentMismatch })
        return
      case "NEW_PASSWORD_EQUALS_CURRENT":
        setServerErrors({ newPassword: PASSWORD_MESSAGES.sameAsCurrent })
        return
      case "VALIDATION_ERROR": {
        const fields = fieldErrorsOf(error, PASSWORD_FIELDS)
        setServerErrors(fields)
        setSubmitError(Object.keys(fields).length > 0 ? null : "입력값을 확인해 주세요.")
        return
      }
      default:
        setSubmitError(errorMessage(error))
    }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (changePassword.isPending) return
    setSubmitError(null)
    setServerErrors({})
    if (Object.keys(errors).length > 0) {
      setShowErrors(true)
      return
    }
    let changed
    try {
      changed = await changePassword.mutateAsync({ currentPassword: form.currentPassword, newPassword: form.newPassword })
    } catch (error) {
      fail(error)
      return
    }
    leaveGuard.release()
    // 새 세션의 로그인 정보로 바꾼다 (mustChangePassword=false). 세션 ID가 바뀌었으므로 CSRF 토큰도 다시 준비한다
    completeLogin(changed.user)
    showToast("비밀번호를 변경했습니다. 다른 기기의 로그인은 모두 끝났습니다.")
    navigate(locked ? HOME_PATH : PATHS.my, { replace: true })
  }

  return (
    <section className="screen password-change">
      {!locked && (
        <button type="button" className="back-link" onClick={() => navigate(PATHS.my)}>
          &lt; 마이페이지로
        </button>
      )}
      <div className="page-heading">
        <div>
          <h1 className="page-title">비밀번호 변경</h1>
          <p className="page-desc">현재 비밀번호를 확인한 뒤 새 비밀번호로 바꿉니다. 바꾸면 다른 기기의 로그인은 모두 끝납니다.</p>
        </div>
      </div>

      {locked && (
        <p className="notice-bar notice-warning" role="status">
          임시 비밀번호로 로그인했습니다. 비밀번호를 변경해야 다른 화면을 쓸 수 있습니다.
        </p>
      )}

      <form className="detail-card form-card password-card" onSubmit={(event) => void submit(event)} noValidate>
        <PasswordRow
          label="현재 비밀번호"
          hint={locked ? "메일로 받은 임시 비밀번호를 입력하세요." : undefined}
          error={visible.currentPassword}
        >
          <PasswordInput
            aria-label="현재 비밀번호"
            autoComplete="current-password"
            value={form.currentPassword}
            aria-invalid={Boolean(visible.currentPassword)}
            onChange={(event) => update({ currentPassword: event.target.value })}
          />
        </PasswordRow>
        <PasswordRow label="새 비밀번호" hint={PASSWORD_RULE_TEXT} error={visible.newPassword}>
          <PasswordInput
            aria-label="새 비밀번호"
            autoComplete="new-password"
            value={form.newPassword}
            aria-invalid={Boolean(visible.newPassword)}
            onChange={(event) => update({ newPassword: event.target.value })}
          />
        </PasswordRow>
        <PasswordRow label="새 비밀번호 확인" error={visible.confirmPassword}>
          <PasswordInput
            aria-label="새 비밀번호 확인"
            autoComplete="new-password"
            value={form.confirmPassword}
            aria-invalid={Boolean(visible.confirmPassword)}
            onChange={(event) => update({ confirmPassword: event.target.value })}
          />
        </PasswordRow>
        <div className="form-actions">
          <FieldError message={submitError} />
          <div className="form-buttons">
            {!locked && (
              <button type="button" className="btn btn-outline" onClick={() => navigate(PATHS.my)}>
                취소
              </button>
            )}
            <button type="submit" className="btn btn-primary" disabled={changePassword.isPending}>
              {changePassword.isPending ? "변경 중" : "변경하기"}
            </button>
          </div>
        </div>
      </form>
    </section>
  )
}

function PasswordRow({
  label,
  hint,
  error,
  children,
}: {
  label: string
  hint?: string
  error?: string
  children: ReactNode
}) {
  return (
    <div className="form-row">
      <span className="form-label">
        {label}
        <em className="required"> *</em>
      </span>
      <div className="form-control form-short-wide">
        {children}
        {hint && <p className="field-hint">{hint}</p>}
        <FieldError message={error} />
      </div>
    </div>
  )
}
