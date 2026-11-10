import "@/styles/detail.css"
import "@/styles/form.css"
import "@/styles/list.css"
import "@/styles/my.css"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react"
import { createPortal } from "react-dom"
import { useNavigate } from "react-router"
import { authApi } from "@/api/authApi"
import { errorMessage, fieldErrorMap, isApiError } from "@/api/errors"
import { runExclusive } from "@/api/http"
import { myApi, myKeys, type WithdrawalInfo, type WithdrawalRequest } from "@/api/myApi"
import { FieldError } from "@/components/common/FieldError"
import { PasswordInput } from "@/components/common/PasswordInput"
import { PATHS } from "@/routes/paths"
import { MyLoadFailed, MyLoading } from "@/screens/my/MyStatusViews"
import {
  describeReconciled,
  reconcilePicks,
  successorLabel,
  validPick,
  type Marks,
  type Picks,
  type RowMark,
} from "@/screens/my/withdrawTransfers"
import { completeWithdrawal } from "@/session/sessionActions"
import { leaveGuard, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"

const WITHDRAW_MESSAGES = {
  done: "회원 탈퇴가 완료되었습니다.",
  alreadyWithdrawn: "이미 탈퇴 처리된 계정입니다.",
  passwordRequired: "비밀번호를 입력하세요.",
  validation: "입력값을 확인해 주세요.",
  failed: "탈퇴하지 못했습니다. 다시 시도해 주세요.",
  unknown: "탈퇴 결과를 확인하지 못했습니다. 잠시 후 이 화면을 다시 열어 확인해 주세요.",
  noSuccessor: "같은 기관에 넘겨받을 수 있는 회원이 없어 탈퇴할 수 없습니다.",
  invalidTransfers: "넘길 대상 또는 넘겨받을 사람이 올바르지 않습니다. 다시 골라 주세요.",
  reloadFailed: "탈퇴 안내를 다시 불러오지 못했습니다.",
  changed: "넘길 대상이 바뀌어 안내를 다시 불러왔습니다.",
  recheck: "바뀐 내용을 확인한 뒤 다시 탈퇴해 주세요.",
} as const

type Members = WithdrawalInfo["successors"]

/** 다시 불러온 결과 안내 (409 · 500 뒤) */
type Notice = { title: string; lines: string[]; retry?: boolean }

/**
 * 5.1.4 회원 탈퇴 (API-33 안내 · API-34 탈퇴, FR-063~066).
 * - 들어올 때마다 안내를 새로 받는다. 유일 담당 사례자와 진행 중 복지자원은 행마다(또는 일괄로) 넘겨받을 사람을 고른다
 * - 넘길 대상이 있으면 모두 골라야 '탈퇴하기'가 켜진다. 넘길 대상이 없으면 바로 켜진다.
 *   넘길 대상이 있는데 넘겨받을 수 있는 회원이 없으면 탈퇴할 수 없다
 * - '탈퇴하기' → 비밀번호 확인 창. 비밀번호 오류는 창 안에 보이고 창은 그대로 둔다
 * - 409(넘길 대상이 바뀜): 창을 닫고 안내를 다시 받아 유효한 선택만 남긴다 (withdrawTransfers.reconcilePicks)
 * - 성공: 서버가 모든 세션을 지웠으므로 로그아웃 API 없이 화면만 로그아웃 상태로 바꾸고 로그인 화면으로
 * - 500·통신 오류: 탈퇴됐는지 로그인 상태(API-01)로 확인한다
 */
export function WithdrawScreen() {
  const navigate = useNavigate()
  // 들어올 때마다 새로 받는다 (이전 캐시로 그리지 않음). 고르는 동안에는 저절로 다시 받지 않는다 (바뀌면 제출 때 409)
  const infoQuery = useQuery({
    queryKey: myKeys.withdrawal,
    queryFn: myApi.getWithdrawalInfo,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  const withdrawMutation = useMutation({ mutationFn: myApi.withdraw })

  const [casePicks, setCasePicks] = useState<Picks>({})
  const [resourcePicks, setResourcePicks] = useState<Picks>({})
  const [caseBulk, setCaseBulk] = useState("")
  const [resourceBulk, setResourceBulk] = useState("")
  const [caseMarks, setCaseMarks] = useState<Marks>({})
  const [resourceMarks, setResourceMarks] = useState<Marks>({})
  const [notice, setNotice] = useState<Notice | null>(null)
  const [pageError, setPageError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [password, setPassword] = useState("")
  const [dialogError, setDialogError] = useState<string | null>(null)
  /** 탈퇴 요청을 보내고 결과를 처리하는 중 (500 뒤 확인 포함). 버튼 표시용 */
  const [submitting, setSubmitting] = useState(false)
  /** 같은 일을 다시 그리기 전에도 바로 막는다: 보낸 직후 Esc · 바깥 클릭 · 두 번 누름 */
  const submittingRef = useRef(false)
  /** 탈퇴가 끝나 떠나는 중 (나가기 확인을 끈다) */
  const [leaving, setLeaving] = useState(false)
  const alertRef = useRef<HTMLDivElement>(null)

  const dirty =
    !leaving && (Object.keys(casePicks).length > 0 || Object.keys(resourcePicks).length > 0 || password !== "")
  useLeaveGuard(dirty)

  // 다시 불러온 결과·오류 안내가 보이게 화면 위로
  useEffect(() => {
    if (notice || pageError) alertRef.current?.scrollIntoView({ block: "start" })
  }, [notice, pageError])

  const info = infoQuery.data
  if (infoQuery.isPending) {
    return (
      <WithdrawFrame onBack={() => navigate(PATHS.my)}>
        <MyLoading text="탈퇴 안내를 불러오는 중입니다." />
      </WithdrawFrame>
    )
  }
  if (!info) {
    return (
      <WithdrawFrame onBack={() => navigate(PATHS.my)}>
        <MyLoadFailed
          title="탈퇴 안내를 불러오지 못했습니다."
          message={errorMessage(infoQuery.error)}
          onRetry={() => void infoQuery.refetch()}
        />
      </WithdrawFrame>
    )
  }

  const successorIds = new Set(info.successors.map((member) => member.memberId))
  const needsTransfer = info.soleCases.length > 0 || info.ongoingResources.length > 0
  const noSuccessor = needsTransfer && info.successors.length === 0
  const missingCases = info.soleCases.filter((item) => validPick(casePicks, item.caseId, successorIds) === undefined).length
  const missingResources = info.ongoingResources.filter(
    (item) => validPick(resourcePicks, item.resourceId, successorIds) === undefined,
  ).length
  const reloading = infoQuery.isFetching
  const busy = submitting || withdrawMutation.isPending
  const canWithdraw = !noSuccessor && missingCases === 0 && missingResources === 0 && !reloading

  const closeDialog = () => {
    setDialogOpen(false)
    setPassword("")
    setDialogError(null)
  }

  /** 취소 · Esc · 바깥 클릭: 요청 중에는 닫지 않는다 */
  const requestClose = () => {
    if (submittingRef.current) return
    closeDialog()
  }

  const openDialog = () => {
    if (!canWithdraw) return
    setNotice(null)
    setPageError(null)
    setPassword("")
    setDialogError(null)
    setDialogOpen(true)
  }

  /** 안내를 다시 받아 유효한 선택만 남기고, 바뀐 행을 표시한다. title이 있으면(409) 바뀐 것이 없어도 안내한다 */
  const reload = async (title: string | null) => {
    const previous = info
    const result = await infoQuery.refetch()
    if (result.status === "error" || !result.data) {
      setNotice({ title: WITHDRAW_MESSAGES.reloadFailed, lines: [errorMessage(result.error)], retry: true })
      return
    }
    const next = result.data
    const reconciled = reconcilePicks(previous, next, casePicks, resourcePicks)
    setCasePicks(reconciled.cases.picks)
    setResourcePicks(reconciled.resources.picks)
    setCaseMarks(reconciled.cases.marks)
    setResourceMarks(reconciled.resources.marks)
    const nextIds = new Set(next.successors.map((member) => member.memberId))
    if (caseBulk && !nextIds.has(Number(caseBulk))) setCaseBulk("")
    if (resourceBulk && !nextIds.has(Number(resourceBulk))) setResourceBulk("")
    const lines = describeReconciled(reconciled)
    if (title) setNotice({ title, lines: lines.length > 0 ? lines : [WITHDRAW_MESSAGES.recheck] })
    else if (lines.length > 0) setNotice({ title: WITHDRAW_MESSAGES.changed, lines })
  }

  /** 탈퇴됨(성공 · 이미 탈퇴 · 결과 확인 뒤 로그인 만료): 나가기 확인을 끄고 로그아웃 상태로 바꾼 뒤 로그인 화면으로 */
  const finish = async (message: string) => {
    setLeaving(true)
    leaveGuard.release()
    await completeWithdrawal()
    navigate(PATHS.login, { replace: true })
    showToast(message)
  }

  /** 500 · 통신 오류: 서버에서 탈퇴가 처리됐는지 알 수 없다. 로그인 상태로 확인하고 자동으로 다시 보내지 않는다 */
  const checkUnknownResult = async () => {
    try {
      await authApi.getMe()
    } catch (error) {
      if (isApiError(error) && error.status === 401) {
        await finish(WITHDRAW_MESSAGES.done)
        return
      }
      closeDialog()
      setPageError(WITHDRAW_MESSAGES.unknown)
      return
    }
    closeDialog()
    setPageError(WITHDRAW_MESSAGES.failed)
    await reload(null)
  }

  const fail = async (error: unknown) => {
    if (!isApiError(error)) {
      setDialogError(errorMessage(error))
      return
    }
    if (error.status === 0 || error.status >= 500) {
      await checkUnknownResult()
      return
    }
    switch (error.code) {
      case "WITHDRAW_PASSWORD_MISMATCH":
        setDialogError(error.message)
        return
      case "VALIDATION_ERROR": {
        // 화면이 먼저 막으므로 보통 오지 않는다. 비밀번호는 창 안에, 넘길 대상은 화면 위에
        const fields = fieldErrorMap(error)
        if (fields.transfers || fields.resourceTransfers) {
          closeDialog()
          setPageError(WITHDRAW_MESSAGES.invalidTransfers)
          return
        }
        setDialogError(fields.password ?? WITHDRAW_MESSAGES.validation)
        return
      }
      case "STATE_CONFLICT":
        closeDialog()
        await reload(error.message)
        return
      case "NOT_FOUND":
        await finish(WITHDRAW_MESSAGES.alreadyWithdrawn)
        return
      default:
        // 401 · 403 PASSWORD_CHANGE_REQUIRED는 공통 처리가 화면을 바꾼다
        if (error.status === 401 || error.code === "PASSWORD_CHANGE_REQUIRED") {
          closeDialog()
          return
        }
        setDialogError(errorMessage(error))
    }
  }

  const submit = async () => {
    if (submittingRef.current) return
    // 비밀번호는 앞뒤 공백도 그대로 보낸다
    if (password === "") {
      setDialogError(WITHDRAW_MESSAGES.passwordRequired)
      return
    }
    setDialogError(null)
    const request: WithdrawalRequest = {
      password,
      transfers: info.soleCases.map((item) => ({ caseId: item.caseId, newManagerMemberId: casePicks[item.caseId] })),
      resourceTransfers: info.ongoingResources.map((item) => ({
        resourceId: item.resourceId,
        newManagerMemberId: resourcePicks[item.resourceId],
      })),
    }
    submittingRef.current = true
    setSubmitting(true)
    try {
      // 탈퇴하면 서버가 현재 세션까지 지운다. 로그아웃 상태로 바꾸고 새 CSRF 토큰을 준비할 때까지 다른 요청을 멈춘다
      await runExclusive(async () => {
        await withdrawMutation.mutateAsync(request)
        setLeaving(true)
        leaveGuard.release()
        await completeWithdrawal()
      })
    } catch (error) {
      try {
        await fail(error)
      } finally {
        submittingRef.current = false
        setSubmitting(false)
      }
      return
    }
    navigate(PATHS.login, { replace: true })
    showToast(WITHDRAW_MESSAGES.done)
  }

  const applyBulk = (ids: number[], value: string, setPicks: Dispatch<SetStateAction<Picks>>, setMarks: Dispatch<SetStateAction<Marks>>) => {
    if (!value) return
    const memberId = Number(value)
    // 개별로 고른 행도 덮어쓴다 (FR-064)
    setPicks(Object.fromEntries(ids.map((id) => [id, memberId])))
    setMarks({})
  }

  const remainText = [
    missingCases > 0 ? `사례자 ${missingCases}명` : null,
    missingResources > 0 ? `복지자원 ${missingResources}개` : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <WithdrawFrame onBack={() => navigate(PATHS.my)}>
      <div ref={alertRef} className="withdraw-alerts">
        {pageError && (
          <p className="withdraw-alert" role="alert">
            {pageError}
          </p>
        )}
        {notice && (
          <div className="withdraw-alert withdraw-changed" role="alert">
            <strong>{notice.title}</strong>
            {notice.lines.length > 0 && (
              <ul>
                {notice.lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            {notice.retry && (
              <button type="button" className="btn btn-outline btn-small" disabled={reloading} onClick={() => void reload(null)}>
                다시 불러오기
              </button>
            )}
          </div>
        )}
      </div>

      <section className="detail-card">
        <h2 className="card-title">탈퇴하면</h2>
        <ul className="withdraw-effects">
          <li>
            <strong>유일 담당 사례자 {info.soleCases.length}명</strong> —{" "}
            {info.soleCases.length > 0 ? "아래에서 넘겨받을 사람을 지정해야 합니다." : "넘길 사례자가 없습니다."}
          </li>
          <li>
            <strong>공동 담당 사례자 {info.sharedCaseCount}명</strong> — 내 담당만 빠지고 다른 담당자가 계속 관리합니다.
          </li>
          <li>
            <strong>진행 중 복지자원 {info.ongoingResources.length}개</strong> —{" "}
            {info.ongoingResources.length > 0 ? "아래에서 넘겨받을 사람을 지정해야 합니다." : "넘길 자원이 없습니다."}
          </li>
          <li>
            <strong>종료된 복지자원 {info.endedResourceCount}개</strong> — 담당 기록은 남고 담당자가 '퇴사자'로 표시됩니다.
          </li>
          <li>
            <strong>저장된 AI 대화 {info.conversationCount}건</strong> — 모두 삭제합니다.
          </li>
        </ul>
        <p className="withdraw-warning">
          탈퇴하면 되돌릴 수 없고, 같은 이메일로 다시 가입할 수 없습니다. 이 안내는 지금 기준이며, 탈퇴할 때 바뀌어 있으면 다시
          확인해 달라고 안내합니다.
        </p>
      </section>

      {noSuccessor && (
        <p className="withdraw-alert" role="alert">
          {WITHDRAW_MESSAGES.noSuccessor}
        </p>
      )}

      {info.soleCases.length > 0 && (
        <section className={`detail-card ${reloading ? "is-refreshing" : ""}`} aria-busy={reloading}>
          <div className="card-head">
            <h2 className="card-title">
              넘길 사례자 <span className="card-count">{info.soleCases.length}명</span>
            </h2>
            {!noSuccessor && (
              <BulkPick
                label="모든 사례자를 넘겨받을 사람 (일괄 지정)"
                value={caseBulk}
                successors={info.successors}
                disabled={busy || reloading}
                onChange={setCaseBulk}
                onApply={() =>
                  applyBulk(
                    info.soleCases.map((item) => item.caseId),
                    caseBulk,
                    setCasePicks,
                    setCaseMarks,
                  )
                }
              />
            )}
          </div>
          <p className="field-hint my-card-hint">
            내가 유일한 담당자인 사례자입니다. 같은 기관의 다른 회원에게 넘겨야 탈퇴할 수 있습니다.
          </p>
          <table className="data-table transfer-table">
            <thead>
              <tr>
                <th>관리번호</th>
                <th>이름</th>
                <th>연령대</th>
                <th>행정동</th>
                <th>최근 상담일</th>
                <th>넘겨받을 사람</th>
              </tr>
            </thead>
            <tbody>
              {info.soleCases.map((item) => (
                <tr key={item.caseId} className={rowClass(caseMarks[item.caseId])}>
                  <td>{item.managementNo}</td>
                  <td>{item.name}</td>
                  <td>{item.ageGroup}</td>
                  <td>{item.dongName}</td>
                  <td>{item.lastRecordedAt ?? "—"}</td>
                  <td>
                    <div className="transfer-pick">
                      <SuccessorSelect
                        label={`${item.managementNo} ${item.name} 사례자를 넘겨받을 사람`}
                        value={validPick(casePicks, item.caseId, successorIds)}
                        successors={info.successors}
                        disabled={noSuccessor || busy || reloading}
                        onChange={(value) => setPick(setCasePicks, setCaseMarks, item.caseId, value)}
                      />
                      <RowMarkBadge mark={caseMarks[item.caseId]} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {info.ongoingResources.length > 0 && (
        <section className={`detail-card ${reloading ? "is-refreshing" : ""}`} aria-busy={reloading}>
          <div className="card-head">
            <h2 className="card-title">
              넘길 복지자원 <span className="card-count">진행 중 {info.ongoingResources.length}개</span>
            </h2>
            {!noSuccessor && (
              <BulkPick
                label="모든 복지자원을 넘겨받을 사람 (일괄 지정)"
                value={resourceBulk}
                successors={info.successors}
                disabled={busy || reloading}
                onChange={setResourceBulk}
                onApply={() =>
                  applyBulk(
                    info.ongoingResources.map((item) => item.resourceId),
                    resourceBulk,
                    setResourcePicks,
                    setResourceMarks,
                  )
                }
              />
            )}
          </div>
          <p className="field-hint my-card-hint">
            내가 담당하는 진행 중 복지자원입니다. 종료된 자원은 넘기지 않고 담당자가 '퇴사자'로 표시됩니다.
          </p>
          <table className="data-table transfer-table">
            <thead>
              <tr>
                <th>자원명</th>
                <th>운영 종료일</th>
                <th>넘겨받을 사람</th>
              </tr>
            </thead>
            <tbody>
              {info.ongoingResources.map((item) => (
                <tr key={item.resourceId} className={rowClass(resourceMarks[item.resourceId])}>
                  <td>{item.resourceName}</td>
                  <td>{item.periodEnd}</td>
                  <td>
                    <div className="transfer-pick">
                      <SuccessorSelect
                        label={`${item.resourceName} 자원을 넘겨받을 사람`}
                        value={validPick(resourcePicks, item.resourceId, successorIds)}
                        successors={info.successors}
                        disabled={noSuccessor || busy || reloading}
                        onChange={(value) => setPick(setResourcePicks, setResourceMarks, item.resourceId, value)}
                      />
                      <RowMarkBadge mark={resourceMarks[item.resourceId]} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <div className="form-actions">
        {!noSuccessor && remainText && (
          <p className="field-hint">넘겨받을 사람을 모두 고르면 탈퇴할 수 있습니다. (남은 {remainText})</p>
        )}
        <div className="form-buttons">
          <button type="button" className="btn btn-outline" onClick={() => navigate(PATHS.my)}>
            취소
          </button>
          <button type="button" className="btn btn-danger" disabled={!canWithdraw || busy} onClick={openDialog}>
            탈퇴하기
          </button>
        </div>
      </div>

      {dialogOpen && (
        <WithdrawDialog
          password={password}
          error={dialogError}
          busy={busy}
          onPasswordChange={(value) => {
            setPassword(value)
            setDialogError(null)
          }}
          onCancel={requestClose}
          onSubmit={() => void submit()}
        />
      )}
    </WithdrawFrame>
  )
}

/** 고른 값을 바꾸면 그 행의 '새로 추가 · 다시 고르세요' 표시를 지운다 */
function setPick(
  setPicks: Dispatch<SetStateAction<Picks>>,
  setMarks: Dispatch<SetStateAction<Marks>>,
  id: number,
  value: string,
) {
  setPicks((previous) => {
    const next = { ...previous }
    if (value) next[id] = Number(value)
    else delete next[id]
    return next
  })
  setMarks((previous) => {
    if (!(id in previous)) return previous
    const next = { ...previous }
    delete next[id]
    return next
  })
}

function rowClass(mark: RowMark | undefined): string | undefined {
  return mark ? `is-${mark}` : undefined
}

function WithdrawFrame({ onBack, children }: { onBack: () => void; children: ReactNode }) {
  return (
    <section className="screen withdraw-screen">
      <button type="button" className="back-link" onClick={onBack}>
        &lt; 마이페이지로
      </button>
      <div className="page-heading">
        <div>
          <h1 className="page-title">회원 탈퇴</h1>
          <p className="page-desc">
            탈퇴하면 되돌릴 수 없습니다. 아래 내용을 확인하고, 넘길 사례자 · 복지자원이 있으면 넘겨받을 사람을 고른 뒤 탈퇴하세요.
          </p>
        </div>
      </div>
      {children}
    </section>
  )
}

function SuccessorSelect({
  label,
  value,
  successors,
  disabled,
  placeholder = "선택하세요",
  onChange,
}: {
  label: string
  value: number | undefined
  successors: Members
  disabled?: boolean
  placeholder?: string
  onChange: (value: string) => void
}) {
  return (
    <select
      className="input select"
      aria-label={label}
      value={value === undefined ? "" : String(value)}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">{placeholder}</option>
      {successors.map((member) => (
        <option key={member.memberId} value={member.memberId}>
          {successorLabel(member)}
        </option>
      ))}
    </select>
  )
}

/** 일괄 지정: 고른 뒤 '모두 적용'을 누르면 모든 행에 넣는다 */
function BulkPick({
  label,
  value,
  successors,
  disabled,
  onChange,
  onApply,
}: {
  label: string
  value: string
  successors: Members
  disabled: boolean
  onChange: (value: string) => void
  onApply: () => void
}) {
  return (
    <div className="bulk-pick">
      <SuccessorSelect
        label={label}
        value={value ? Number(value) : undefined}
        successors={successors}
        disabled={disabled}
        placeholder="일괄 지정"
        onChange={onChange}
      />
      <button type="button" className="btn btn-outline btn-small" disabled={disabled || !value} onClick={onApply}>
        모두 적용
      </button>
    </div>
  )
}

function RowMarkBadge({ mark }: { mark: RowMark | undefined }) {
  if (!mark) return null
  return <span className={`row-mark row-mark-${mark}`}>{mark === "new" ? "새로 추가" : "다시 고르세요"}</span>
}

/** 탈퇴 확인 창: 비밀번호를 한 번 더 입력. 오류는 창 안에 보이고, 요청 중에는 닫히지 않는다 */
function WithdrawDialog({
  password,
  error,
  busy,
  onPasswordChange,
  onCancel,
  onSubmit,
}: {
  password: string
  error: string | null
  busy: boolean
  onPasswordChange: (value: string) => void
  onCancel: () => void
  onSubmit: () => void
}) {
  // Esc로 닫기 (요청 중에는 닫지 않는다)
  const latest = useRef({ busy, onCancel })
  latest.current = { busy, onCancel }
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !latest.current.busy) latest.current.onCancel()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  const frame = document.querySelector(".app-frame") ?? document.body
  return createPortal(
    <div
      className="dialog-backdrop"
      onClick={() => {
        if (!busy) onCancel()
      }}
    >
      <form
        className="dialog withdraw-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="withdraw-title"
        aria-describedby="withdraw-desc"
        noValidate
        onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit()
        }}
      >
        <h2 id="withdraw-title">정말 탈퇴할까요?</h2>
        <p id="withdraw-desc">탈퇴하면 되돌릴 수 없습니다. 계속하려면 비밀번호를 입력하세요.</p>
        <PasswordInput
          aria-label="비밀번호"
          autoComplete="current-password"
          autoFocus
          value={password}
          readOnly={busy}
          aria-invalid={Boolean(error)}
          onChange={(event) => onPasswordChange(event.target.value)}
        />
        <FieldError message={error} />
        <div className="dialog-actions">
          <button type="button" className="btn btn-outline" disabled={busy} onClick={onCancel}>
            취소
          </button>
          <button type="submit" className="btn btn-danger" disabled={busy}>
            {busy ? "탈퇴 중" : "탈퇴"}
          </button>
        </div>
      </form>
    </div>,
    frame,
  )
}
