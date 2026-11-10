import "@/styles/auth.css"
import { useMutation } from "@tanstack/react-query"
import { useState, type FormEvent } from "react"
import { Link, Navigate, useNavigate } from "react-router"
import { authApi } from "@/api/authApi"
import { CLIENT_ERROR_CODE, errorMessage, isApiError, MESSAGES } from "@/api/errors"
import { FieldError } from "@/components/common/FieldError"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { fieldErrorsOf } from "@/screens/case/caseErrors"
import { useSession } from "@/session/sessionStore"
import { isValidEmail } from "@/utils/validation"

type Field = "email" | "name"
type FieldErrors = Partial<Record<Field, string>>

/** openapi TempPasswordRequest의 길이 제한 */
const EMAIL_MAX = 254
const NAME_MAX = 100

const MESSAGES_FIND = {
  emailRequired: "이메일을 입력하세요.",
  emailInvalid: "이메일 형식이 올바르지 않습니다.",
  nameRequired: "이름을 입력하세요.",
  nameTooLong: `이름은 ${NAME_MAX}자 이하로 입력하세요.`,
  validation: "입력값을 확인해 주세요.",
  mailFailed: "임시 비밀번호를 보내지 못했습니다. 잠시 후 다시 시도해 주세요.",
} as const

/** 서버 fieldErrors의 field → 입력칸 (서버 문구는 공통 문구라 화면 문구로 바꾼다) */
const SERVER_FIELDS: Record<string, Field> = { email: "email", name: "name" }
const SERVER_FIELD_TEXT: Record<Field, string> = {
  email: MESSAGES_FIND.emailInvalid,
  name: `이름을 확인해 주세요. (${NAME_MAX}자 이하)`,
}

function validate(email: string, name: string): FieldErrors {
  const errors: FieldErrors = {}
  if (!email) errors.email = MESSAGES_FIND.emailRequired
  else if (email.length > EMAIL_MAX || !isValidEmail(email)) errors.email = MESSAGES_FIND.emailInvalid
  if (!name) errors.name = MESSAGES_FIND.nameRequired
  else if (name.length > NAME_MAX) errors.name = MESSAGES_FIND.nameTooLong
  return errors
}

/**
 * 1.3.1 비밀번호 찾기 (FR-014·015, API-09)
 * - 이메일과 이름을 입력하면 임시 비밀번호를 메일로 보낸다
 * - 가입 여부가 드러나지 않도록 서버는 항상 204를 주고, 화면도 결과와 관계없이 같은 안내를 보인 뒤 로그인으로 보낸다(P2-A·P5-A)
 * - 임시 비밀번호로 로그인하면 비밀번호 변경 화면만 쓸 수 있다 (LoginScreen · RequireAuth · sessionActions가 처리)
 * - 실패: 400 입력 오류는 입력칸 아래, 429 요청 제한은 "잠시 후 다시 시도", 500(메일 발송 실패)은 변경 없이 되돌려지므로 다시 보내도 된다
 */
export function PasswordFindScreen() {
  const session = useSession()
  const navigate = useNavigate()
  const [email, setEmail] = useState("")
  const [name, setName] = useState("")
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [requestError, setRequestError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)

  const fail = (error: unknown) => {
    if (!isApiError(error)) {
      setRequestError(errorMessage(error))
      return
    }
    // Nginx 요청 제한(분당 3 + 순간 3, 인증 메일과 합산). JSON 본문이든 HTML이든 같은 안내
    if (error.status === 429 || error.code === CLIENT_ERROR_CODE.rateLimited) {
      setRequestError(MESSAGES.rateLimited)
      return
    }
    if (error.status === 400) {
      const fields = fieldErrorsOf(error, SERVER_FIELDS)
      const shown: FieldErrors = {}
      for (const field of Object.keys(fields) as Field[]) shown[field] = SERVER_FIELD_TEXT[field]
      setFieldErrors(shown)
      setRequestError(Object.keys(shown).length > 0 ? null : MESSAGES_FIND.validation)
      return
    }
    // 메일 발송 실패는 발급을 되돌리므로(계획 3-3) 다시 보내도 안전하다. 응답을 받지 못한 경우는 공통 문구
    if (error.status >= 500) {
      setRequestError(MESSAGES_FIND.mailFailed)
      return
    }
    setRequestError(errorMessage(error))
  }

  const issue = useMutation({
    mutationFn: authApi.issueTempPassword,
    onSuccess: () => setSent(true),
    onError: fail,
  })

  // 로그인 상태를 복원하는 중에는 아무것도 그리지 않는다. 이미 로그인했으면 로그인 화면과 같이 첫 화면으로
  if (session.status === "restoring") return null
  if (session.status === "authenticated") {
    return <Navigate to={session.profile.mustChangePassword ? PATHS.myPassword : HOME_PATH} replace />
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (issue.isPending) return
    const trimmedEmail = email.trim()
    const trimmedName = name.trim()
    const errors = validate(trimmedEmail, trimmedName)
    setFieldErrors(errors)
    setRequestError(null)
    if (errors.email || errors.name) return
    issue.mutate({ email: trimmedEmail, name: trimmedName })
  }

  const goLogin = () => navigate(PATHS.login, { state: { email: email.trim() } })

  const edit = (field: Field, value: string) => {
    if (field === "email") setEmail(value)
    else setName(value)
    setFieldErrors((prev) => ({ ...prev, [field]: undefined }))
    setRequestError(null)
  }

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
            <li>임시 비밀번호가 발급되면 기존 비밀번호로는 로그인할 수 없습니다.</li>
            <li>임시 비밀번호로 로그인하면 비밀번호를 먼저 변경해야 합니다.</li>
            <li>24시간 안에 이미 받은 임시 비밀번호가 있으면 새로 보내지 않습니다. 먼저 받은 메일을 확인해 주세요.</li>
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
              placeholder="name@organization.or.kr"
              maxLength={EMAIL_MAX}
              value={email}
              aria-invalid={Boolean(fieldErrors.email)}
              onChange={(event) => edit("email", event.target.value)}
            />
            <FieldError message={fieldErrors.email} />
          </label>

          <label className="field">
            <span>이름</span>
            <input
              className="input"
              autoComplete="name"
              maxLength={NAME_MAX}
              value={name}
              aria-invalid={Boolean(fieldErrors.name)}
              onChange={(event) => edit("name", event.target.value)}
            />
            <FieldError message={fieldErrors.name} />
          </label>

          {requestError && (
            <p className="login-error" role="alert">
              {requestError}
            </p>
          )}

          <button type="submit" className="btn btn-primary btn-block btn-large" disabled={issue.isPending}>
            {issue.isPending ? "보내는 중…" : "임시 비밀번호 발급"}
          </button>

          <div className="login-links">
            <Link to={PATHS.login}>로그인 화면으로</Link>
          </div>
        </form>
      )}
    </section>
  )
}
