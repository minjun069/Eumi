import "@/styles/signup.css"
import { useMutation } from "@tanstack/react-query"
import { useEffect, useRef, useState, type FormEvent } from "react"
import { Link, Navigate, useNavigate } from "react-router"
import { CLIENT_ERROR_CODE, errorMessage, isApiError, type ApiError } from "@/api/errors"
import { signupApi, type OrganizationSearchItem } from "@/api/signupApi"
import { FieldError } from "@/components/common/FieldError"
import { PasswordInput } from "@/components/common/PasswordInput"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { OrgSearchField } from "@/screens/auth/OrgSearchField"
import { fieldErrorsOf } from "@/screens/case/caseErrors"
import { useSession } from "@/session/sessionStore"
import { showToast } from "@/stores/toastStore"
import { formatRemaining } from "@/utils/datetime"
import {
  PASSWORD_RULE_TEXT,
  emailDomain,
  isValidEmail,
  isValidPassword,
  isValidPhone,
  isValidVerificationCode,
} from "@/utils/validation"

/** 인증 단계. 가입 증명(token)은 이 화면 상태에만 둔다 (저장소·주소·로그·알림에 넣지 않는다) */
type VerifyState =
  | { stage: "idle" }
  | { stage: "sent"; expiresAt: number; resendAt: number; failures: number }
  | { stage: "verified"; token: string }

type FieldName = "org" | "email" | "code" | "name" | "password" | "passwordConfirm" | "title" | "phone"
type Errors = Partial<Record<FieldName, string>>

/** SignupRequest · SendVerificationRequest의 길이 제한 */
const EMAIL_MAX = 254
const NAME_MAX = 100
const PASSWORD_MAX = 128
const TITLE_MAX = 100

/** BE 정책 (SignupService 상수): 재발송 간격 60초, 코드 실패 5회 */
const RESEND_WAIT_MS = 60_000
const MAX_CODE_FAILURES = 5

const domainOnly = (domain: string) => `선택한 기관의 공식 메일(@${domain})로만 가입할 수 있습니다.`

const TEXT = {
  orgRequired: "소속기관을 검색해서 고르세요.",
  orgInvalid: "소속기관을 다시 검색해서 고르세요.",
  emailRequired: "이메일을 입력하세요.",
  emailInvalid: "이메일 형식이 올바르지 않습니다.",
  emailExists: "이미 가입된 이메일입니다. 탈퇴한 이메일로도 다시 가입할 수 없습니다.",
  sendLimited: "잠시 후 다시 보내 주세요. 같은 이메일은 60초에 한 번 보낼 수 있습니다.",
  sendFailed: "인증 메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.",
  sent: "인증 메일을 보냈습니다. 메일로 받은 6자리 코드를 입력하세요.",
  codeRequired: "인증 코드를 입력하세요.",
  codeInvalid: "6자리 숫자를 입력하세요.",
  codeExpired: "인증 시간이 지났습니다. '재발송'으로 새 코드를 받으세요.",
  codeLocked: `${MAX_CODE_FAILURES}번 틀려 이 코드는 더 쓸 수 없습니다. '재발송'으로 새 코드를 받으세요.`,
  verified: "이메일 인증을 마쳤습니다. 10분 안에 가입하기를 눌러 주세요.",
  verifyRequired: "이메일 인증을 완료하세요.",
  proofInvalid: "이메일 인증이 풀렸습니다. 인증 메일을 다시 받아 주세요.",
  proofExpired: "인증한 지 10분이 지났습니다. 인증 메일을 다시 받아 주세요.",
  nameRequired: "이름을 입력하세요.",
  nameInvalid: `이름은 ${NAME_MAX}자 이하로 입력하세요.`,
  passwordRequired: "비밀번호를 입력하세요.",
  passwordInvalid: `비밀번호는 ${PASSWORD_RULE_TEXT}해야 합니다. (${PASSWORD_MAX}자까지)`,
  passwordConfirmRequired: "비밀번호를 한 번 더 입력하세요.",
  passwordMismatch: "비밀번호가 일치하지 않습니다.",
  titleInvalid: `직함은 ${TITLE_MAX}자 이하로 입력하세요.`,
  phoneInvalid: "전화번호 형식이 올바르지 않습니다. (예: 010-1234-5678)",
  signupExists: "이미 가입된 이메일입니다.",
  validation: "입력값을 확인해 주세요.",
} as const

const codeMismatch = (failures: number) =>
  failures >= MAX_CODE_FAILURES ? TEXT.codeLocked : `인증 코드가 맞지 않습니다. (${failures}/${MAX_CODE_FAILURES})`

/** 429는 BE 이메일별 60초 제한(JSON)이든 Nginx IP 제한(HTML)이든 같다 */
const isRateLimited = (error: ApiError) => error.status === 429 || error.code === CLIENT_ERROR_CODE.rateLimited

/** API-07 400 fieldErrors → 입력칸 · 화면 문구 (서버 문구는 공통 문구라 쓰지 않는다) */
type SignupServerField = "org" | "email" | "name" | "password" | "title" | "phone" | "verificationToken"
const SIGNUP_SERVER_FIELDS: Record<string, SignupServerField> = {
  orgId: "org",
  email: "email",
  name: "name",
  password: "password",
  title: "title",
  phone: "phone",
  verificationToken: "verificationToken",
}

/**
 * 1.1.1 회원가입 (FR-009~013, API-04~07 · S1-A: 한 화면 두 칸)
 * - 왼쪽 ① 소속기관 검색·선택 → 관할 표시 → 공식 메일로 인증 메일 발송(코드 6자리, 10분) → 코드 확인(가입 증명 10분)
 * - 오른쪽 ② 이름·비밀번호·직함(선택)·전화번호(선택) → 가입하기 → 이메일을 채운 로그인 화면 (자동 로그인 없음)
 * - 인증 뒤 기관이나 이메일을 바꾸면 증명·코드·타이머·재발송 대기를 버리고 인증 처음으로 돌아간다 (FR-012)
 * - 오류는 error.code로 문구를 고른다. 재발송 60초 · 실패 5회는 서버도 같은 기준으로 막는다
 */
export function SignupScreen() {
  const session = useSession()
  const navigate = useNavigate()

  const [orgKeyword, setOrgKeyword] = useState("")
  const [org, setOrg] = useState<OrganizationSearchItem | null>(null)
  const [email, setEmail] = useState("")
  const [code, setCode] = useState("")
  const [verify, setVerify] = useState<VerifyState>({ stage: "idle" })
  const [now, setNow] = useState(() => Date.now())
  const [notice, setNotice] = useState<string | null>(null)

  const [name, setName] = useState("")
  const [password, setPassword] = useState("")
  const [passwordConfirm, setPasswordConfirm] = useState("")
  const [title, setTitle] = useState("")
  const [phone, setPhone] = useState("")

  const [errors, setErrors] = useState<Errors>({})
  const [signupError, setSignupError] = useState<{ message: string; loginLink: boolean } | null>(null)

  // 기관·이메일을 바꾸거나 인증을 처음으로 되돌릴 때마다 올린다.
  // 그 전에 보낸 발송·확인 요청의 응답은 지금 입력과 맞지 않으므로 반영하지 않는다
  const attempt = useRef(0)

  const setError = (field: FieldName, message: string | null) =>
    setErrors((prev) => ({ ...prev, [field]: message ?? undefined }))

  // 코드를 보낸 뒤 인증 전까지 1초마다 남은 시간 · 재발송 대기를 갱신한다
  useEffect(() => {
    if (verify.stage !== "sent") return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [verify.stage])

  const resetVerification = () => {
    attempt.current += 1
    setVerify({ stage: "idle" })
    setCode("")
    setNotice(null)
    setError("code", null)
  }

  const sendMutation = useMutation({ mutationFn: signupApi.sendVerificationEmail })
  const verifyMutation = useMutation({ mutationFn: signupApi.verifyCode })
  const signupMutation = useMutation({ mutationFn: signupApi.signup })

  // 로그인 상태를 복원하는 중에는 아무것도 그리지 않는다. 이미 로그인했으면 로그인 화면과 같이 첫 화면으로
  if (session.status === "restoring") return null
  if (session.status === "authenticated") {
    return <Navigate to={session.profile.mustChangePassword ? PATHS.myPassword : HOME_PATH} replace />
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
    resetVerification()
    setError("email", null)
  }

  const remaining = verify.stage === "sent" ? verify.expiresAt - now : 0
  const expired = verify.stage === "sent" && remaining <= 0
  const resendWait = verify.stage === "sent" ? Math.max(0, Math.ceil((verify.resendAt - now) / 1000)) : 0
  const locked = verify.stage === "sent" && verify.failures >= MAX_CODE_FAILURES

  // ── ② 인증 메일 발송 (API-05) ──

  const sendFailed = (error: unknown, domain: string) => {
    if (!isApiError(error)) return setError("email", errorMessage(error))
    if (isRateLimited(error)) return setError("email", TEXT.sendLimited)
    if (error.code === "EMAIL_DOMAIN_MISMATCH") return setError("email", domainOnly(domain))
    if (error.code === "EMAIL_ALREADY_EXISTS") return setError("email", TEXT.emailExists)
    if (error.code === "VALIDATION_ERROR") {
      const fields = fieldErrorsOf(error, { orgId: "org", email: "email" } as const)
      if (fields.org) setError("org", TEXT.orgInvalid)
      setError("email", fields.email ? TEXT.emailInvalid : fields.org ? null : TEXT.validation)
      return
    }
    // 메일 발송 실패(500)는 서버가 되돌리므로 바로 다시 보내도 된다
    if (error.status >= 500) return setError("email", TEXT.sendFailed)
    setError("email", errorMessage(error))
  }

  const sendEmail = () => {
    if (sendMutation.isPending || verify.stage === "verified" || resendWait > 0) return
    const trimmed = email.trim()
    const next: Errors = {}
    if (!org) next.org = TEXT.orgRequired
    if (!trimmed) next.email = TEXT.emailRequired
    else if (trimmed.length > EMAIL_MAX || !isValidEmail(trimmed)) next.email = TEXT.emailInvalid
    else if (org && emailDomain(trimmed) !== org.officialDomain.toLowerCase()) next.email = domainOnly(org.officialDomain)
    setErrors((prev) => ({ ...prev, org: next.org, email: next.email }))
    if (!org || next.email) return

    const sentAttempt = attempt.current
    sendMutation.mutate(
      { orgId: org.orgId, email: trimmed },
      {
        onSuccess: (data) => {
          if (attempt.current !== sentAttempt) return
          // 재발송이 성공하면 옛 코드는 버려지므로, 옛 코드로 보낸 확인 요청의 응답도 반영하지 않는다
          attempt.current += 1
          const sentAt = Date.now()
          setNow(sentAt)
          setVerify({ stage: "sent", expiresAt: Date.parse(data.expiresAt), resendAt: sentAt + RESEND_WAIT_MS, failures: 0 })
          setCode("")
          setError("code", null)
          setNotice(TEXT.sent)
        },
        // 실패하면 단계와 재발송 대기를 바꾸지 않는다
        onError: (error) => {
          if (attempt.current === sentAttempt) sendFailed(error, org.officialDomain)
        },
      },
    )
  }

  // ── ③ 코드 확인 (API-06) ──

  const confirmCode = () => {
    if (verify.stage !== "sent" || expired || locked || verifyMutation.isPending) return
    if (!code) return setError("code", TEXT.codeRequired)
    if (!isValidVerificationCode(code)) return setError("code", TEXT.codeInvalid)

    const sentAttempt = attempt.current
    verifyMutation.mutate(
      { email: email.trim(), code },
      {
        onSuccess: (data) => {
          if (attempt.current !== sentAttempt) return
          setVerify({ stage: "verified", token: data.verificationToken })
          // 다 쓴 코드는 화면에 남기지 않는다
          setCode("")
          setErrors((prev) => ({ ...prev, code: undefined, email: undefined }))
          setNotice(TEXT.verified)
        },
        onError: (error) => {
          if (attempt.current !== sentAttempt) return
          if (isApiError(error) && error.code === "VERIFICATION_INVALID") {
            // 실패 횟수는 화면에서도 센다 (발송할 때마다 0). 서버도 400이어도 횟수를 남긴다
            const failures = verify.failures + 1
            setVerify((prev) => (prev.stage === "sent" ? { ...prev, failures } : prev))
            setError("code", codeMismatch(failures))
            return
          }
          if (isApiError(error) && error.code === "VERIFICATION_EXPIRED") {
            // 서버 시각으로 만료됐으면 화면도 만료로 바꿔 같은 안내 한 줄만 보인다
            const at = Date.now()
            setNow(at)
            setVerify((prev) => (prev.stage === "sent" ? { ...prev, expiresAt: at } : prev))
            setError("code", null)
            return
          }
          if (isApiError(error) && error.code === "VALIDATION_ERROR") return setError("code", TEXT.codeInvalid)
          setError("code", errorMessage(error))
        },
      },
    )
  }

  // ── ⑤ 가입 (API-07) ──

  const signupFailed = (error: unknown) => {
    if (!isApiError(error)) return setSignupError({ message: errorMessage(error), loginLink: false })
    if (error.code === "PROOF_INVALID" || error.code === "PROOF_EXPIRED") {
      resetVerification()
      setError("email", error.code === "PROOF_INVALID" ? TEXT.proofInvalid : TEXT.proofExpired)
      return
    }
    if (error.code === "EMAIL_ALREADY_EXISTS") return setSignupError({ message: TEXT.signupExists, loginLink: true })
    if (error.code === "VALIDATION_ERROR") {
      const fields = fieldErrorsOf(error, SIGNUP_SERVER_FIELDS)
      const shown: Errors = {}
      if (fields.org) shown.org = TEXT.orgInvalid
      if (fields.email) shown.email = TEXT.emailInvalid
      if (fields.name) shown.name = TEXT.nameInvalid
      if (fields.password) shown.password = TEXT.passwordInvalid
      if (fields.title) shown.title = TEXT.titleInvalid
      if (fields.phone) shown.phone = TEXT.phoneInvalid
      // 증명은 입력칸이 없다. 인증 단계로 되돌려 다시 받게 한다
      if (fields.verificationToken) {
        resetVerification()
        shown.email = TEXT.proofInvalid
      }
      setErrors((prev) => ({ ...prev, ...shown }))
      if (Object.keys(shown).length === 0) setSignupError({ message: TEXT.validation, loginLink: false })
      return
    }
    setSignupError({ message: errorMessage(error), loginLink: false })
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (signupMutation.isPending) return
    const trimmedEmail = email.trim()
    const trimmedName = name.trim()
    const trimmedTitle = title.trim()
    const trimmedPhone = phone.trim()

    const next: Errors = {}
    if (!org) next.org = TEXT.orgRequired
    if (verify.stage !== "verified") next.email = TEXT.verifyRequired
    if (!trimmedName) next.name = TEXT.nameRequired
    else if (trimmedName.length > NAME_MAX) next.name = TEXT.nameInvalid
    // 비밀번호는 앞뒤 공백도 그대로 쓴다 (trim하지 않는다)
    if (!password) next.password = TEXT.passwordRequired
    else if (!isValidPassword(password) || password.length > PASSWORD_MAX) next.password = TEXT.passwordInvalid
    if (!passwordConfirm) next.passwordConfirm = TEXT.passwordConfirmRequired
    else if (password !== passwordConfirm) next.passwordConfirm = TEXT.passwordMismatch
    if (trimmedTitle.length > TITLE_MAX) next.title = TEXT.titleInvalid
    if (trimmedPhone && !isValidPhone(trimmedPhone)) next.phone = TEXT.phoneInvalid
    // 코드 칸의 안내(틀린 횟수 등)는 그대로 둔다
    setErrors((prev) => ({ ...next, code: prev.code }))
    setSignupError(null)
    if (Object.values(next).some(Boolean) || !org || verify.stage !== "verified") return

    signupMutation.mutate(
      {
        verificationToken: verify.token,
        orgId: org.orgId,
        email: trimmedEmail,
        name: trimmedName,
        password,
        title: trimmedTitle || null,
        phone: trimmedPhone || null,
      },
      {
        onSuccess: (_data, request) => {
          showToast("가입이 완료되었습니다. 로그인해 주세요.")
          navigate(PATHS.login, { replace: true, state: { email: request.email } })
        },
        onError: signupFailed,
      },
    )
  }

  const sendLabel =
    verify.stage === "verified"
      ? "인증 완료"
      : sendMutation.isPending
        ? "보내는 중…"
        : verify.stage === "idle"
          ? "인증 메일 발송"
          : resendWait > 0
            ? `재발송 (${resendWait}초)`
            : "재발송"

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
                  maxLength={EMAIL_MAX}
                  placeholder={org ? `name@${org.officialDomain}` : undefined}
                  aria-invalid={Boolean(errors.email)}
                  onChange={(event) => changeEmail(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault()
                      sendEmail()
                    }
                  }}
                />
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={sendEmail}
                  disabled={verify.stage === "verified" || sendMutation.isPending || resendWait > 0}
                >
                  {sendLabel}
                </button>
              </div>
              {errors.email ? (
                <FieldError message={errors.email} />
              ) : notice ? (
                <p className={verify.stage === "verified" ? "field-success" : "field-notice"}>{notice}</p>
              ) : (
                <p className="field-hint">
                  {org ? `공식 메일(@${org.officialDomain})로만 인증할 수 있습니다.` : "소속기관을 먼저 고르세요."}
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
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={code}
                  placeholder={
                    verify.stage === "idle"
                      ? "인증 메일을 보내면 입력할 수 있습니다"
                      : verify.stage === "verified"
                        ? "인증을 마쳤습니다"
                        : "6자리 숫자"
                  }
                  disabled={verify.stage !== "sent"}
                  aria-invalid={Boolean(errors.code)}
                  onChange={(event) => {
                    setCode(event.target.value.replace(/\D/g, ""))
                    if (!locked) setError("code", null)
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
                  disabled={verify.stage !== "sent" || expired || locked || verifyMutation.isPending}
                >
                  {verifyMutation.isPending ? "확인 중…" : "확인"}
                </button>
              </div>
              {verify.stage === "sent" && (
                <p className={`verify-timer ${expired || remaining < 60_000 ? "is-urgent" : ""}`}>
                  {expired ? TEXT.codeExpired : `남은 시간 ${formatRemaining(remaining)}`}
                </p>
              )}
              {/* 시간이 지나면 위의 안내 한 줄만 보인다 (같은 내용의 실패 사유가 겹치지 않게) */}
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
                autoComplete="name"
                maxLength={NAME_MAX}
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
                maxLength={PASSWORD_MAX}
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
                maxLength={PASSWORD_MAX}
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
                maxLength={TITLE_MAX}
                value={title}
                placeholder="예: 사회복지사"
                aria-invalid={Boolean(errors.title)}
                onChange={(event) => {
                  setTitle(event.target.value)
                  setError("title", null)
                }}
              />
              <FieldError message={errors.title} />
            </label>

            <label className="field">
              <span>
                전화번호(비상연락망) <small className="optional">(선택)</small>
              </span>
              <input
                className="input"
                inputMode="tel"
                autoComplete="tel"
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
            {signupError.message}
            {signupError.loginLink && (
              <>
                {" "}
                <Link className="signup-error-link" to={PATHS.login} state={{ email: email.trim() }}>
                  로그인 화면으로
                </Link>
              </>
            )}
          </p>
        )}

        <div className="signup-actions">
          <Link to={PATHS.login} className="btn btn-outline btn-large">
            로그인 화면으로
          </Link>
          <button type="submit" className="btn btn-primary btn-large" disabled={signupMutation.isPending}>
            {signupMutation.isPending ? "가입하는 중…" : "가입하기"}
          </button>
        </div>
      </form>
    </section>
  )
}
