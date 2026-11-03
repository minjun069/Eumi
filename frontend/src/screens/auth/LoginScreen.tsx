import "@/styles/auth.css"
import { useMutation } from "@tanstack/react-query"
import { useState, type FormEvent } from "react"
import { Link, Navigate, useLocation } from "react-router"
import { authApi } from "@/api/authApi"
import { errorMessage, fieldErrorMap, isApiError } from "@/api/errors"
import { FieldError } from "@/components/common/FieldError"
import { PasswordInput } from "@/components/common/PasswordInput"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { clearSavedEmail, getSavedEmail, saveEmail } from "@/session/savedEmail"
import { completeLogin, restoreSession } from "@/session/sessionActions"
import { useSession } from "@/session/sessionStore"
import { showToast } from "@/stores/toastStore"
import { isValidEmail } from "@/utils/validation"

type FieldErrors = { email?: string; password?: string }

const RESTRICTED_SESSION = "임시 비밀번호로 로그인된 상태예요. 비밀번호를 변경하거나 로그아웃한 뒤 다시 로그인하세요."

/**
 * 로그인 (FR-006·007·008, API-08)
 * - 로그인하면 고립 위험 탐색(첫 화면)으로, 임시 비밀번호로 로그인하면 비밀번호 변경으로 이동한다
 * - 빈칸·이메일 형식은 API를 부르기 전에 화면에서 먼저 확인한다
 * - 실패 사유(미가입·탈퇴·비밀번호 불일치·만료된 임시 비밀번호)는 서버가 같은 문구로 돌려준다
 * - 이메일 저장: 로그인에 성공했을 때만 브라우저에 이메일을 저장한다. 비밀번호는 저장하지 않는다
 */
export function LoginScreen() {
  const session = useSession()

  // 회원가입·비밀번호 찾기에서 왔으면 입력한 이메일을, 아니면 저장된 이메일을 채운다
  const location = useLocation()
  const signedUpEmail = (location.state as { email?: string } | null)?.email ?? null
  const [savedEmail] = useState(getSavedEmail)
  const [email, setEmail] = useState(signedUpEmail ?? savedEmail ?? "")
  const [password, setPassword] = useState("")
  const [rememberEmail, setRememberEmail] = useState(savedEmail !== null)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [loginError, setLoginError] = useState<string | null>(null)

  const login = useMutation({
    mutationFn: authApi.login,
    onSuccess: ({ user }, request) => {
      if (rememberEmail) saveEmail(request.email)
      else clearSavedEmail()
      // 로그인 상태가 되면 아래에서 첫 화면(또는 비밀번호 변경)으로 이동한다
      completeLogin(user)
    },
    onError: (error) => {
      // 이 브라우저가 이미 임시 비밀번호로 로그인된 제한 세션이면 서버가 새 로그인을 거절한다 (API-08 403).
      // 그 세션을 다시 불러오면 비밀번호 변경 화면으로 간다. 다른 계정으로는 로그아웃한 뒤 로그인한다
      if (isApiError(error) && error.code === "PASSWORD_CHANGE_REQUIRED") {
        setLoginError(RESTRICTED_SESSION)
        showToast(RESTRICTED_SESSION, "error")
        void restoreSession()
        return
      }
      const fields = fieldErrorMap(error)
      if (fields.email || fields.password) setFieldErrors({ email: fields.email, password: fields.password })
      else setLoginError(errorMessage(error))
    },
  })

  // 로그인 상태를 복원하는 중에는 아무것도 그리지 않는다
  if (session.status === "restoring") return null
  // 이미 로그인했거나 방금 로그인했으면 첫 화면으로. 임시 비밀번호 로그인이면 비밀번호 변경으로
  if (session.status === "authenticated") {
    return <Navigate to={session.profile.mustChangePassword ? PATHS.myPassword : HOME_PATH} replace />
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (login.isPending) return
    const trimmedEmail = email.trim()

    const errors: FieldErrors = {}
    if (!trimmedEmail) errors.email = "이메일을 입력하세요."
    else if (!isValidEmail(trimmedEmail)) errors.email = "이메일 형식이 올바르지 않습니다."
    if (!password) errors.password = "비밀번호를 입력하세요."
    setFieldErrors(errors)
    setLoginError(null)
    if (errors.email || errors.password) return

    // 비밀번호는 앞뒤 공백을 지우지 않고 그대로 보낸다
    login.mutate({ email: trimmedEmail, password })
  }

  return (
    <section className="login-screen">
      <div className="logo-window logo-window-large" aria-label="이음이">
        <img src="/assets/logo.png" alt="" />
      </div>
      <form className="login-card" onSubmit={submit} noValidate>
        <h1>로그인</h1>

        <label className="field">
          <span>이메일</span>
          <input
            className="input"
            type="email"
            autoComplete="username"
            placeholder="name@organization.or.kr"
            value={email}
            aria-invalid={Boolean(fieldErrors.email)}
            onChange={(event) => {
              setEmail(event.target.value)
              setFieldErrors((prev) => ({ ...prev, email: undefined }))
              setLoginError(null)
            }}
          />
          <FieldError message={fieldErrors.email} />
        </label>

        <label className="field">
          <span>비밀번호</span>
          <PasswordInput
            autoComplete="current-password"
            value={password}
            aria-invalid={Boolean(fieldErrors.password)}
            onChange={(event) => {
              setPassword(event.target.value)
              setFieldErrors((prev) => ({ ...prev, password: undefined }))
              setLoginError(null)
            }}
          />
          <FieldError message={fieldErrors.password} />
        </label>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={rememberEmail}
            onChange={(event) => setRememberEmail(event.target.checked)}
          />
          <span>이메일 저장</span>
        </label>

        {loginError && (
          <p className="login-error" role="alert">
            {loginError}
          </p>
        )}

        <button type="submit" className="btn btn-primary btn-block btn-large" disabled={login.isPending}>
          {login.isPending ? "로그인 중…" : "로그인"}
        </button>

        <div className="login-links">
          <Link to={PATHS.signup}>회원가입</Link>
          <span aria-hidden="true">|</span>
          <Link to={PATHS.passwordFind}>비밀번호 찾기</Link>
        </div>
      </form>
    </section>
  )
}
