import { useState, type FormEvent } from "react"
import { Link, Navigate, useLocation, useNavigate } from "react-router"
import { FieldError } from "@/components/common/FieldError"
import { PasswordInput } from "@/components/common/PasswordInput"
import { expireTempPassword, isTempPasswordExpired, peekTempPassword } from "@/devtools/devMailbox"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { authApi } from "@/mock/api/authApi"
import { DEMO_LOGIN, LOGIN_EXAMPLES } from "@/mock/seed/members"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { clearSavedEmail, getSavedEmail, saveEmail } from "@/session/savedEmail"
import { profileFromLogin } from "@/session/loginProfile"
import { sessionStore, useSession } from "@/session/sessionStore"
import { isValidEmail } from "@/utils/validation"

type FieldErrors = { email?: string; password?: string }

/**
 * 1.2.1 로그인
 * - 이메일·비밀번호로 로그인하면 고립 위험 탐색(첫 화면)으로 이동
 * - 임시 비밀번호로 로그인하면 비밀번호 변경(5.1.3)으로 이동
 * - 빈칸·이메일 형식은 API를 부르기 전에 화면에서 먼저 확인
 * - 이메일 저장: 로그인에 성공했을 때 브라우저에 저장 (API 기록 없음)
 */
export function LoginScreen() {
  const navigate = useNavigate()
  const session = useSession()
  // 화면을 처음 띄울 때 이미 로그인한 상태였는지 (로그인 직후의 이동과 구분하기 위해 처음 값만 기억)
  const [openedWhileSignedIn] = useState(() => sessionStore.getState().status !== "anonymous")

  // 회원가입·비밀번호 찾기에서 왔으면 입력한 이메일만 채운다.
  // 저장된 이메일이 있으면 이메일만 채우고 비밀번호는 비운다. 둘 다 없으면 예시 계정을 채운다.
  const location = useLocation()
  const signedUpEmail = (location.state as { email?: string } | null)?.email ?? null
  const [savedEmail, setSavedEmail] = useState(getSavedEmail)
  const [email, setEmail] = useState(signedUpEmail ?? savedEmail ?? DEMO_LOGIN.email)
  const [password, setPassword] = useState(
    signedUpEmail || savedEmail ? "" : DEMO_LOGIN.password,
  )
  const [rememberEmail, setRememberEmail] = useState(savedEmail !== null)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [loginError, setLoginError] = useState<string | null>(null)

  // 개발용: 지금 입력한 이메일로 발급된 임시 비밀번호 (비밀번호 찾기 1.3.1)
  const [tempPasswordTick, setTempPasswordTick] = useState(0)
  const issuedTempPassword = peekTempPassword(email.trim())
  const tempPasswordExpired = isTempPasswordExpired(email.trim())

  const fillExample = (example: { email: string; password: string }) => {
    setEmail(example.email)
    setPassword(example.password)
    setFieldErrors({})
    setLoginError(null)
  }

  useDevScenario(
    {
      screen: "로그인 화면",
      hint: "버튼을 누르면 입력칸이 채워집니다. '로그인'을 눌러 결과를 확인하세요.",
      actions: LOGIN_EXAMPLES.map((example) => ({
        label: example.label,
        run: () => fillExample(example),
      })),
      groups: issuedTempPassword
        ? [
            {
              title: "지금 이메일의 임시 비밀번호",
              actions: [
                {
                  label: "임시 비밀번호 채우기",
                  run: () => fillExample({ email: email.trim(), password: issuedTempPassword }),
                },
                {
                  label: "임시 비밀번호 만료시키기",
                  run: () => {
                    expireTempPassword(email.trim())
                    setTempPasswordTick((tick) => tick + 1)
                  },
                },
              ],
            },
          ]
        : undefined,
      infos: [
        {
          label: "저장된 이메일",
          value: savedEmail ?? "없음",
          action: savedEmail
            ? {
                label: "지우기",
                run: () => {
                  clearSavedEmail()
                  setSavedEmail(null)
                },
              }
            : undefined,
        },
        {
          label: "발급된 임시 비밀번호",
          value: issuedTempPassword
            ? `${issuedTempPassword}${tempPasswordExpired ? " (24시간 지남)" : ""}`
            : "없음",
        },
      ],
    },
    [savedEmail, email, issuedTempPassword, tempPasswordExpired, tempPasswordTick],
  )

  // 이미 로그인한 상태로 로그인 화면에 들어오면 첫 화면으로 보낸다
  if (openedWhileSignedIn && session.status === "restoring") return null
  if (openedWhileSignedIn && session.status === "authenticated") {
    return <Navigate to={HOME_PATH} replace />
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const trimmedEmail = email.trim()

    const errors: FieldErrors = {}
    if (!trimmedEmail) errors.email = "이메일을 입력하세요."
    else if (!isValidEmail(trimmedEmail)) errors.email = "이메일 형식이 올바르지 않습니다."
    if (!password) errors.password = "비밀번호를 입력하세요."
    setFieldErrors(errors)
    setLoginError(null)
    if (errors.email || errors.password) return

    const result = authApi.login({ email: trimmedEmail, password })
    if (!result.ok) {
      setLoginError(result.message)
      return
    }

    if (rememberEmail) saveEmail(trimmedEmail)
    else clearSavedEmail()

    sessionStore.signIn(profileFromLogin(result.data))
    navigate(result.data.mustChangePassword ? PATHS.myPassword : HOME_PATH, { replace: true })
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

        <button type="submit" className="btn btn-primary btn-block btn-large">
          로그인
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
