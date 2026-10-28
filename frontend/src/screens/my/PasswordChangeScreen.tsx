import { useState, type FormEvent, type ReactNode } from "react"
import { useNavigate } from "react-router"
import { FieldError } from "@/components/common/FieldError"
import { PasswordInput } from "@/components/common/PasswordInput"
import { devAuth } from "@/devtools/devAuth"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { myApi } from "@/mock/api/myApi"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { DEMO_PASSWORD } from "@/mock/seed/members"
import { initialPasswordForm, passwordFills, validatePasswordForm, type PasswordForm } from "@/screens/my/myForms"
import { sessionStore, useSession } from "@/session/sessionStore"
import { leaveGuard, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"
import { PASSWORD_RULE_TEXT } from "@/utils/validation"

/**
 * 5.1.3 비밀번호 변경: 현재 비밀번호 확인 → 새 비밀번호 (규칙은 회원가입과 같음).
 * 임시 비밀번호로 로그인했으면(M3-A) 이 화면만 쓸 수 있고, '현재 비밀번호'에 임시 또는 기존 비밀번호를 넣는다(M4-A).
 * 바꾼 뒤에도 로그인은 유지 (M5-A): 보통은 내 정보로, 임시 비밀번호로 들어왔으면 첫 화면으로
 */
export function PasswordChangeScreen() {
  const session = useSession()
  const locked = session.status === "authenticated" && session.profile.mustChangePassword
  // 같은 화면에서 임시 비밀번호 로그인 상태로 바뀌어도 처음 값을 다시 채우도록 상태마다 새로 그린다
  return <PasswordChangeForm key={locked ? "temp" : "normal"} locked={locked} />
}

function PasswordChangeForm({ locked }: { locked: boolean }) {
  const navigate = useNavigate()
  const session = useSession()
  const tempPassword = devAuth.currentTempPassword()
  // 임시 비밀번호로 로그인했으면 현재 비밀번호에 그 임시 비밀번호를 채운다 (프로토타입 예시값)
  const [baseline] = useState<PasswordForm>(() => initialPasswordForm(locked ? tempPassword : null))
  const [form, setForm] = useState<PasswordForm>(baseline)
  const [showErrors, setShowErrors] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const dirty = JSON.stringify(form) !== JSON.stringify(baseline)
  // 임시 비밀번호로 들어온 경우에는 다른 화면으로 갈 수 없으므로 경고가 필요 없다 (로그아웃 때만 물음)
  useLeaveGuard(dirty)
  const errors = showErrors ? validatePasswordForm(form) : {}

  const update = (patch: Partial<PasswordForm>) => {
    setForm({ ...form, ...patch })
    setSubmitError(null)
  }

  const fill = (next: PasswordForm) => {
    setForm(next)
    setShowErrors(false)
    setSubmitError(null)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setShowErrors(true)
    if (Object.keys(validatePasswordForm(form)).length > 0) return
    const result = myApi.changePassword({ currentPassword: form.currentPassword, newPassword: form.newPassword })
    if (!result.ok) {
      setSubmitError(result.message)
      return
    }
    leaveGuard.release()
    showToast("비밀번호를 변경했습니다.")
    if (locked && session.status === "authenticated") {
      // 다시 발급된 로그인 정보(토큰)에는 '비밀번호 변경 필요'가 없다
      sessionStore.updateProfile({ ...session.profile, mustChangePassword: false })
      navigate(HOME_PATH, { replace: true })
    } else {
      navigate(PATHS.my)
    }
  }

  useDevScenario(
    {
      screen: "비밀번호 변경",
      hint: locked
        ? "임시 비밀번호로 로그인한 상태입니다. 현재 비밀번호에 임시 비밀번호를 채워 두었고, 기존 비밀번호(ieum1234!)도 됩니다. 메뉴·AI 아이콘이 막히고 로그아웃만 할 수 있습니다."
        : "예시 계정의 비밀번호는 ieum1234!입니다.",
      actions: [
        ...passwordFills(baseline).map((item) => ({ label: `채우기: ${item.label}`, run: () => fill(item.form) })),
        ...(locked
          ? [{ label: "채우기: 기존 비밀번호로", run: () => fill({ ...baseline, currentPassword: DEMO_PASSWORD }) }]
          : [{ label: "임시 비밀번호로 로그인한 상태 만들기 (정하늘)", run: () => devAuth.enterTempLogin(navigate) }]),
      ],
      infos: [{ label: "발급된 임시 비밀번호", value: tempPassword ?? "없음" }],
    },
    [locked, tempPassword, baseline],
  )

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
          <p className="page-desc">현재 비밀번호를 확인한 뒤 새 비밀번호로 바꿉니다.</p>
        </div>
      </div>

      {locked && (
        <p className="notice-bar notice-warning" role="status">
          임시 비밀번호로 로그인했습니다. 비밀번호를 변경해야 다른 화면을 쓸 수 있습니다.
        </p>
      )}

      <form className="detail-card form-card password-card" onSubmit={submit} noValidate>
        <PasswordRow
          label="현재 비밀번호"
          hint={locked ? "메일로 받은 임시 비밀번호를 입력하세요. (기존 비밀번호도 됩니다)" : undefined}
          error={errors.currentPassword}
        >
          <PasswordInput
            aria-label="현재 비밀번호"
            autoComplete="current-password"
            value={form.currentPassword}
            aria-invalid={Boolean(errors.currentPassword)}
            onChange={(event) => update({ currentPassword: event.target.value })}
          />
        </PasswordRow>
        <PasswordRow label="새 비밀번호" hint={PASSWORD_RULE_TEXT} error={errors.newPassword}>
          <PasswordInput
            aria-label="새 비밀번호"
            autoComplete="new-password"
            value={form.newPassword}
            aria-invalid={Boolean(errors.newPassword)}
            onChange={(event) => update({ newPassword: event.target.value })}
          />
        </PasswordRow>
        <PasswordRow label="새 비밀번호 확인" error={errors.confirmPassword}>
          <PasswordInput
            aria-label="새 비밀번호 확인"
            autoComplete="new-password"
            value={form.confirmPassword}
            aria-invalid={Boolean(errors.confirmPassword)}
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
            <button type="submit" className="btn btn-primary">
              변경하기
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
