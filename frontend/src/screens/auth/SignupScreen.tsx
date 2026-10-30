import { useEffect, useState, type FormEvent } from "react"
import { Link, Navigate, useNavigate } from "react-router"
import { FieldError } from "@/components/common/FieldError"
import { PasswordInput } from "@/components/common/PasswordInput"
import { expireVerification, peekVerificationCode } from "@/devtools/devMailbox"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { signupApi, type OrganizationSearchItem } from "@/mock/api/signupApi"
import { DEMO_SIGNUP, SIGNUP_EXAMPLES } from "@/mock/seed/members"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { sessionStore, useSession } from "@/session/sessionStore"
import { OrgSearchField } from "@/screens/auth/OrgSearchField"
import { showToast } from "@/stores/toastStore"
import { formatRemaining } from "@/utils/datetime"
import {
  PASSWORD_RULE_TEXT,
  isValidEmail,
  isValidPassword,
  isValidPhone,
  isValidVerificationCode,
} from "@/utils/validation"

type VerifyState =
  | { stage: "idle" }
  | { stage: "sent"; expiresAt: number }
  | { stage: "verified"; token: string }

type FieldName = "org" | "email" | "code" | "name" | "password" | "passwordConfirm" | "phone"
type Errors = Partial<Record<FieldName, string>>

/**
 * 1.1.1 회원가입 (S1-A: 한 화면 두 칸)
 * 왼쪽 ① 소속기관 검색·선택 → 관할지역 자동 표시 → 이메일 인증(코드 6자리, 10분)
 * 오른쪽 ② 이름·비밀번호·직함(선택)·전화번호(선택)
 * 인증을 마친 뒤 '가입하기'를 누를 때 계정이 만들어지고, 로그인 화면으로 이동한다.
 */
export function SignupScreen() {
  const navigate = useNavigate()
  const session = useSession()
  const [openedWhileSignedIn] = useState(() => sessionStore.getState().status !== "anonymous")

  const [orgKeyword, setOrgKeyword] = useState(DEMO_SIGNUP.orgKeyword)
  const [org, setOrg] = useState<OrganizationSearchItem | null>(null)
  const [email, setEmail] = useState(DEMO_SIGNUP.email)
  const [code, setCode] = useState("")
  const [verify, setVerify] = useState<VerifyState>({ stage: "idle" })
  const [sendCount, setSendCount] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const [notice, setNotice] = useState<string | null>(null)

  const [name, setName] = useState(DEMO_SIGNUP.name)
  const [password, setPassword] = useState(DEMO_SIGNUP.password)
  const [passwordConfirm, setPasswordConfirm] = useState(DEMO_SIGNUP.password)
  const [title, setTitle] = useState(DEMO_SIGNUP.title)
  const [phone, setPhone] = useState(DEMO_SIGNUP.phone)

  const [errors, setErrors] = useState<Errors>({})
  const [signupError, setSignupError] = useState<string | null>(null)

  const setError = (field: FieldName, message: string | null) =>
    setErrors((prev) => ({ ...prev, [field]: message ?? undefined }))

  // 인증 코드 남은 시간 (발송 후 인증 전까지 1초마다 갱신)
  useEffect(() => {
    if (verify.stage !== "sent") return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [verify])

  // 소속기관이나 이메일이 바뀌면 인증을 처음부터 다시 받아야 한다
  const resetVerification = () => {
    setVerify({ stage: "idle" })
    setCode("")
    setNotice(null)
    setError("code", null)
  }

  const changeOrgKeyword = (value: string) => {
    setOrgKeyword(value)
    if (org) {
      setOrg(null)
      resetVerification()
    }
    setError("org", null)
  }

  const selectOrg = (item: OrganizationSearchItem) => {
    if (org?.orgId !== item.orgId) resetVerification()
    setOrg(item)
    setOrgKeyword(item.orgName)
    setErrors((prev) => ({ ...prev, org: undefined, email: undefined }))
  }

  const changeEmail = (value: string) => {
    setEmail(value)
    if (verify.stage !== "idle") resetVerification()
    setError("email", null)
  }

  const sendEmail = () => {
    const trimmed = email.trim()
    const next: Errors = {}
    if (!org) next.org = "소속기관을 검색해서 고르세요."
    if (!trimmed) next.email = "이메일을 입력하세요."
    else if (!isValidEmail(trimmed)) next.email = "이메일 형식이 올바르지 않습니다."
    setErrors((prev) => ({ ...prev, org: next.org, email: next.email }))
    if (!org || next.email) return

    const result = signupApi.sendVerificationEmail({ orgId: org.orgId, email: trimmed })
    if (!result.ok) {
      setError("email", result.message)
      resetVerification()
      return
    }
    setVerify({
      stage: "sent",
      expiresAt: new Date(result.data.expiresAt.replace(" ", "T")).getTime(),
    })
    setCode("")
    setSendCount((count) => count + 1)
    setError("code", null)
    setNotice("인증 메일을 보냈습니다. 메일로 받은 6자리 코드를 입력하세요.")
  }

  const confirmCode = () => {
    if (verify.stage !== "sent") return
    if (!code) {
      setError("code", "인증 코드를 입력하세요.")
      return
    }
    if (!isValidVerificationCode(code)) {
      setError("code", "6자리 숫자를 입력하세요.")
      return
    }
    const result = signupApi.verifyCode({ email: email.trim(), code })
    if (!result.ok) {
      setError("code", result.message)
      return
    }
    setError("code", null)
    setVerify({ stage: "verified", token: result.data.verificationToken })
    setNotice("이메일 인증을 마쳤습니다.")
  }

  const fillExample = (example: (typeof SIGNUP_EXAMPLES)[number]) => {
    setOrgKeyword(example.orgName)
    if (org?.orgName !== example.orgName) setOrg(null)
    setEmail(example.email)
    resetVerification()
    setErrors({})
    setSignupError(null)
  }

  const sentCode = peekVerificationCode(email.trim())

  useDevScenario(
    {
      screen: "회원가입 화면",
      hint: "예시를 채운 뒤 '검색'으로 기관을 고르고 '인증 메일 발송'을 누르세요. 메일은 실제로 보내지 않고, 발송된 코드가 위에 표시됩니다.",
      actions: SIGNUP_EXAMPLES.map((example) => ({
        label: example.label,
        run: () => fillExample(example),
      })),
      groups: [
        {
          title: "인증 코드",
          actions: [
            {
              label: "틀린 코드 채우기",
              run: () => {
                const right = peekVerificationCode(email.trim())
                setCode(right === "000000" ? "111111" : "000000")
                setError("code", null)
              },
            },
            {
              label: "인증 시간 만료시키기",
              run: () => {
                if (!expireVerification(email.trim())) return
                const current = Date.now()
                setVerify((prev) =>
                  prev.stage === "sent" ? { stage: "sent", expiresAt: current - 1 } : prev,
                )
                // 다음 1초 갱신을 기다리지 않고 바로 '시간 지남'으로 보이게 한다
                setNow(current)
              },
            },
          ],
        },
      ],
      infos: [
        {
          label: "발송된 인증 코드",
          value: sentCode ?? "아직 발송하지 않음",
          action: sentCode
            ? {
                label: "채우기",
                run: () => {
                  setCode(sentCode)
                  setError("code", null)
                },
              }
            : undefined,
        },
      ],
    },
    [email, org?.orgId, sendCount, sentCode],
  )

  // 이미 로그인한 상태로 들어오면 첫 화면으로 (로그인 화면과 같게)
  if (openedWhileSignedIn && session.status === "restoring") return null
  if (openedWhileSignedIn && session.status === "authenticated") {
    return <Navigate to={HOME_PATH} replace />
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const next: Errors = {}
    if (!org) next.org = "소속기관을 검색해서 고르세요."
    if (verify.stage !== "verified") next.email = "이메일 인증을 완료하세요."
    if (!name.trim()) next.name = "이름을 입력하세요."
    if (!password) next.password = "비밀번호를 입력하세요."
    else if (!isValidPassword(password)) next.password = `비밀번호는 ${PASSWORD_RULE_TEXT}해야 합니다.`
    if (!passwordConfirm) next.passwordConfirm = "비밀번호를 한 번 더 입력하세요."
    else if (password !== passwordConfirm) next.passwordConfirm = "비밀번호가 일치하지 않습니다."
    if (phone.trim() && !isValidPhone(phone.trim())) {
      next.phone = "전화번호 형식이 올바르지 않습니다. (예: 010-1234-5678)"
    }
    setErrors(next)
    setSignupError(null)
    if (Object.values(next).some(Boolean) || !org || verify.stage !== "verified") return

    const result = signupApi.signup({
      verificationToken: verify.token,
      orgId: org.orgId,
      email: email.trim(),
      name: name.trim(),
      password,
      title: title.trim() || null,
      phone: phone.trim() || null,
    })
    if (!result.ok) {
      setSignupError(result.message)
      return
    }
    showToast("가입이 완료되었습니다. 로그인하세요.")
    navigate(PATHS.login, { replace: true, state: { email: email.trim() } })
  }

  const remaining = verify.stage === "sent" ? verify.expiresAt - now : 0
  const expired = verify.stage === "sent" && remaining <= 0

  return (
    <section className="signup-screen">
      <div className="logo-window logo-window-large" aria-label="이음이">
        <img src="/assets/logo.png" alt="" />
      </div>
      <form className="signup-card" onSubmit={submit} noValidate>
        <div className="signup-head">
          <h1>회원가입</h1>
          <p>
            <em className="required">*</em> 표시는 필수 항목입니다.
          </p>
        </div>

        <div className="signup-columns">
          <fieldset className="signup-column">
            <legend>① 소속기관·이메일 인증</legend>

            <OrgSearchField
              keyword={orgKeyword}
              onKeywordChange={changeOrgKeyword}
              selected={org}
              onSelect={selectOrg}
              error={errors.org}
              onError={(message) => setError("org", message)}
            />

            <div className="field">
              <span>
                관할지역 <em className="required">*</em>
              </span>
              <div className={`input input-readonly ${org ? "" : "is-empty"}`} aria-readonly="true">
                {org ? `${org.sidoName} ${org.sigunguName}` : "소속기관을 고르면 자동으로 표시됩니다."}
              </div>
            </div>

            <div className="field">
              <span>
                이메일 <em className="required">*</em>
              </span>
              <div className="input-with-button">
                <input
                  className="input"
                  type="email"
                  value={email}
                  autoComplete="username"
                  aria-invalid={Boolean(errors.email)}
                  onChange={(event) => changeEmail(event.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={sendEmail}
                  disabled={verify.stage === "verified"}
                >
                  {verify.stage === "idle" ? "인증 메일 발송" : verify.stage === "sent" ? "재발송" : "인증 완료"}
                </button>
              </div>
              {errors.email ? (
                <FieldError message={errors.email} />
              ) : notice ? (
                <p className={verify.stage === "verified" ? "field-success" : "field-notice"}>{notice}</p>
              ) : (
                <p className="field-hint">
                  {org?.officialDomain
                    ? `공식 메일(@${org.officialDomain})로만 인증할 수 있습니다.`
                    : org
                      ? "공식 메일 도메인이 없는 기관이라, 사용하는 메일로 인증합니다."
                      : "소속기관을 먼저 고르세요."}
                </p>
              )}
            </div>

            <div className="field">
              <span>
                인증 코드 <em className="required">*</em>
              </span>
              <div className="input-with-button">
                <input
                  className="input"
                  inputMode="numeric"
                  maxLength={6}
                  value={code}
                  placeholder={verify.stage === "idle" ? "인증 메일을 보내면 입력할 수 있습니다" : "6자리 숫자"}
                  disabled={verify.stage !== "sent"}
                  aria-invalid={Boolean(errors.code)}
                  onChange={(event) => {
                    setCode(event.target.value.replace(/\D/g, ""))
                    setError("code", null)
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault()
                      confirmCode()
                    }
                  }}
                />
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={confirmCode}
                  disabled={verify.stage !== "sent"}
                >
                  확인
                </button>
              </div>
              {verify.stage === "sent" && (
                <p className={`verify-timer ${expired || remaining < 60_000 ? "is-urgent" : ""}`}>
                  {expired
                    ? "인증 시간이 지났습니다. '재발송'으로 새 코드를 받으세요."
                    : `남은 시간 ${formatRemaining(remaining)}`}
                </p>
              )}
              {/* 시간이 지나면 위의 안내 한 줄만 보인다 (같은 내용의 실패 사유가 겹치지 않게). 실패 사유는 API 기록에 남는다 */}
              {!expired && <FieldError message={errors.code} />}
            </div>
          </fieldset>

          <fieldset className="signup-column">
            <legend>② 회원 정보</legend>

            <label className="field">
              <span>
                이름 <em className="required">*</em>
              </span>
              <input
                className="input"
                value={name}
                aria-invalid={Boolean(errors.name)}
                onChange={(event) => {
                  setName(event.target.value)
                  setError("name", null)
                }}
              />
              <FieldError message={errors.name} />
            </label>

            <label className="field">
              <span>
                비밀번호 <em className="required">*</em>
              </span>
              <PasswordInput
                autoComplete="new-password"
                value={password}
                aria-invalid={Boolean(errors.password)}
                onChange={(event) => {
                  setPassword(event.target.value)
                  setError("password", null)
                }}
              />
              {errors.password ? (
                <FieldError message={errors.password} />
              ) : (
                <p className="field-hint">{PASSWORD_RULE_TEXT}</p>
              )}
            </label>

            <label className="field">
              <span>
                비밀번호 확인 <em className="required">*</em>
              </span>
              <PasswordInput
                autoComplete="new-password"
                value={passwordConfirm}
                aria-invalid={Boolean(errors.passwordConfirm)}
                onChange={(event) => {
                  setPasswordConfirm(event.target.value)
                  setError("passwordConfirm", null)
                }}
              />
              <FieldError message={errors.passwordConfirm} />
            </label>

            <label className="field">
              <span>
                직함 <small className="optional">(선택)</small>
              </span>
              <input
                className="input"
                value={title}
                placeholder="예: 사회복지사"
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>

            <label className="field">
              <span>
                전화번호(비상연락망) <small className="optional">(선택)</small>
              </span>
              <input
                className="input"
                inputMode="tel"
                value={phone}
                placeholder="010-1234-5678"
                aria-invalid={Boolean(errors.phone)}
                onChange={(event) => {
                  setPhone(event.target.value)
                  setError("phone", null)
                }}
              />
              <FieldError message={errors.phone} />
            </label>
          </fieldset>
        </div>

        {signupError && (
          <p className="login-error" role="alert">
            {signupError}
          </p>
        )}

        <div className="signup-actions">
          <Link to={PATHS.login} className="btn btn-outline btn-large">
            로그인 화면으로
          </Link>
          <button type="submit" className="btn btn-primary btn-large">
            가입하기
          </button>
        </div>
      </form>
    </section>
  )
}
