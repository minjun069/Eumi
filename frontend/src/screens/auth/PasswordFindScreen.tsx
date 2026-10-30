import { useState, type FormEvent } from "react"
import { Link, Navigate, useNavigate } from "react-router"
import { FieldError } from "@/components/common/FieldError"
import { peekTempPassword } from "@/devtools/devMailbox"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { authApi } from "@/mock/api/authApi"
import { DEMO_PASSWORD_FIND, PASSWORD_FIND_EXAMPLES } from "@/mock/seed/members"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { sessionStore, useSession } from "@/session/sessionStore"
import { isValidEmail } from "@/utils/validation"

type FieldErrors = { email?: string; name?: string }

/**
 * 1.3.1 비밀번호 찾기
 * 이메일과 이름(P1-B)을 입력하면 임시 비밀번호를 메일로 보낸다.
 * 가입 여부가 드러나지 않도록 결과와 관계없이 같은 안내를 보여 준다(P2-A).
 * 발급한 뒤에는 같은 화면에 안내와 '로그인 화면으로' 버튼을 보여 준다(P5-A).
 */
export function PasswordFindScreen() {
  const navigate = useNavigate()
  const session = useSession()
  const [openedWhileSignedIn] = useState(() => sessionStore.getState().status !== "anonymous")

  const [email, setEmail] = useState(DEMO_PASSWORD_FIND.email)
  const [name, setName] = useState(DEMO_PASSWORD_FIND.name)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [requestError, setRequestError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  // 발급 요청 횟수 (개발용 영역의 '발급된 임시 비밀번호'를 새로 읽기 위해)
  const [requestCount, setRequestCount] = useState(0)

  const issuedPassword = peekTempPassword(email.trim())

  useDevScenario(
    {
      screen: "비밀번호 찾기 화면",
      hint: "버튼을 누르면 입력칸이 채워집니다. 어떤 경우든 화면 안내는 같고, 실제로 메일을 보냈는지는 API 기록의 '서버 처리'에서 볼 수 있습니다.",
      actions: PASSWORD_FIND_EXAMPLES.map((example) => ({
        label: example.label,
        run: () => {
          setEmail(example.email)
          setName(example.name)
          setFieldErrors({})
          setRequestError(null)
          setSent(false)
        },
      })),
      infos: [{ label: "발급된 임시 비밀번호", value: issuedPassword ?? "없음" }],
    },
    [issuedPassword, requestCount],
  )

  // 이미 로그인한 상태로 들어오면 첫 화면으로 (로그인 화면과 같게)
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
    if (!name.trim()) errors.name = "이름을 입력하세요."
    setFieldErrors(errors)
    setRequestError(null)
    if (errors.email || errors.name) return

    const result = authApi.issueTempPassword({ email: trimmedEmail, name: name.trim() })
    setRequestCount((count) => count + 1)
    if (!result.ok) {
      setRequestError(result.message)
      return
    }
    setSent(true)
  }

  const goLogin = () => navigate(PATHS.login, { state: { email: email.trim() } })

  return (
    <section className="login-screen">
      <div className="logo-window logo-window-large" aria-label="이음이">
        <img src="/assets/logo.png" alt="" />
      </div>

      {sent ? (
        <div className="login-card" role="status">
          <h1>임시 비밀번호 발급</h1>
          <p className="password-find-done">
            입력한 이메일과 이름이 일치하는 계정이 있으면 임시 비밀번호를 메일로 보냈습니다.
          </p>
          <ul className="password-find-notes">
            <li>임시 비밀번호는 발급 후 24시간 동안 쓸 수 있습니다.</li>
            <li>임시 비밀번호로 로그인하면 비밀번호를 먼저 변경해야 합니다.</li>
            <li>기존 비밀번호가 기억나면 그대로 로그인할 수 있습니다.</li>
          </ul>
          <button type="button" className="btn btn-primary btn-block btn-large" onClick={goLogin}>
            로그인 화면으로
          </button>
          <button type="button" className="btn btn-outline btn-block" onClick={() => setSent(false)}>
            다시 입력하기
          </button>
        </div>
      ) : (
        <form className="login-card" onSubmit={submit} noValidate>
          <h1>비밀번호 찾기</h1>
          <p className="password-find-desc">
            가입한 이메일과 이름을 입력하면 임시 비밀번호를 메일로 보내 드립니다.
          </p>

          <label className="field">
            <span>이메일</span>
            <input
              className="input"
              type="email"
              autoComplete="username"
              value={email}
              aria-invalid={Boolean(fieldErrors.email)}
              onChange={(event) => {
                setEmail(event.target.value)
                setFieldErrors((prev) => ({ ...prev, email: undefined }))
              }}
            />
            <FieldError message={fieldErrors.email} />
          </label>

          <label className="field">
            <span>이름</span>
            <input
              className="input"
              value={name}
              aria-invalid={Boolean(fieldErrors.name)}
              onChange={(event) => {
                setName(event.target.value)
                setFieldErrors((prev) => ({ ...prev, name: undefined }))
              }}
            />
            <FieldError message={fieldErrors.name} />
          </label>

          {requestError && (
            <p className="login-error" role="alert">
              {requestError}
            </p>
          )}

          <button type="submit" className="btn btn-primary btn-block btn-large">
            임시 비밀번호 발급
          </button>

          <div className="login-links">
            <Link to={PATHS.login}>로그인 화면으로</Link>
          </div>
        </form>
      )}
    </section>
  )
}
