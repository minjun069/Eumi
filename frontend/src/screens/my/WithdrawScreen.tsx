import { useCallback, useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { useNavigate } from "react-router"
import { FieldError } from "@/components/common/FieldError"
import { PasswordInput } from "@/components/common/PasswordInput"
import { devAuth } from "@/devtools/devAuth"
import { devCases } from "@/devtools/devCases"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { DEMO_PASSWORD } from "@/mock/seed/members"
import { myApi, WITHDRAW_PASSWORD_MISMATCH_MESSAGE, type SuccessorItem, type WithdrawalInfo } from "@/mock/api/myApi"
import { PATHS } from "@/routes/paths"
import { sessionStore } from "@/session/sessionStore"
import { leaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"

const successorLabel = (item: SuccessorItem) => [item.name, item.title].filter(Boolean).join(" ")

/**
 * 5.1.4 회원 탈퇴: 처리되는 데이터 안내 → 유일 담당 사례자 넘기기(M6-A, 사례자마다 담당자 고르기 + 한 번에 고르기)
 * → '탈퇴하기' → 확인 창에서 비밀번호 다시 입력(M7-B, 명세 추가) → 탈퇴 → 로그인 화면
 */
export function WithdrawScreen() {
  const navigate = useNavigate()
  const [info, setInfo] = useState<WithdrawalInfo | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  /** 사례자ID → 넘겨받을 담당자 회원ID */
  const [picks, setPicks] = useState<Record<number, number>>({})
  const [bulkPick, setBulkPick] = useState("")
  const [showErrors, setShowErrors] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)

  const load = useCallback(() => {
    const result = myApi.getWithdrawalInfo()
    if (!result.ok) {
      setLoadError(result.message)
      return
    }
    setInfo(result.data)
    // 고른 값은 남아 있는 사례자만 남긴다 (다시 불러온 경우)
    setPicks((previous) => {
      const next: Record<number, number> = {}
      result.data.soleCases.forEach((item) => {
        if (previous[item.caseId] && result.data.successors.some((member) => member.memberId === previous[item.caseId])) {
          next[item.caseId] = previous[item.caseId]
        }
      })
      return next
    })
  }, [])

  useEffect(load, [load])

  const blocked = info !== null && info.soleCases.length > 0 && info.successors.length === 0
  const unpicked = info ? info.soleCases.filter((item) => !picks[item.caseId]) : []

  const applyBulk = () => {
    if (!info || !bulkPick) return
    const next: Record<number, number> = {}
    info.soleCases.forEach((item) => {
      next[item.caseId] = Number(bulkPick)
    })
    setPicks(next)
  }

  const startWithdraw = () => {
    setShowErrors(true)
    if (!info || blocked || unpicked.length > 0) return
    setDialogOpen(true)
  }

  const withdraw = (password: string): string | null => {
    if (!info) return null
    const result = myApi.withdraw({
      password,
      transfers: info.soleCases.map((item) => ({ caseId: item.caseId, newManagerMemberId: picks[item.caseId] })),
    })
    if (!result.ok) {
      if (result.message === WITHDRAW_PASSWORD_MISMATCH_MESSAGE) return result.message
      // 그사이 넘길 사례자가 바뀐 경우 등: 창을 닫고 안내를 다시 불러온다
      setDialogOpen(false)
      showToast(result.message, "error")
      load()
      return null
    }
    leaveGuard.release()
    sessionStore.signOut()
    navigate(PATHS.login, { replace: true })
    showToast("회원 탈퇴가 완료되었습니다.")
    return null
  }

  const firstSole = info?.soleCases[0]
  useDevScenario(
    {
      screen: "회원 탈퇴",
      hint: "예시 계정으로 바꾸면 화면이 그 회원의 탈퇴 안내를 다시 불러옵니다. 새로고침하면 탈퇴한 회원도 처음 상태로 돌아옵니다.",
      actions: [
        { label: "최상우로 바꾸기 (넘길 사례자 3명)", run: () => void devAuth.switchMember(3) },
        { label: "김지원으로 바꾸기 (넘길 사례자 17명)", run: () => void devAuth.switchMember(1) },
        { label: "오서연으로 바꾸기 (넘겨받을 회원 없음)", run: () => void devAuth.switchMember(7) },
      ],
      groups: firstSole
        ? [
            {
              title: "다른 곳에서 한 일",
              actions: [
                { label: `넘길 사례자 '${firstSole.name}'를 삭제함`, run: () => devCases.deleteCase(firstSole.caseId) },
              ],
            },
          ]
        : [],
    },
    [firstSole?.caseId],
  )

  if (loadError) return <p className="notice-bar">{loadError}</p>
  if (!info) return null

  return (
    <section className="screen withdraw-screen">
      <button type="button" className="back-link" onClick={() => navigate(PATHS.my)}>
        &lt; 마이페이지로
      </button>
      <div className="page-heading">
        <div>
          <h1 className="page-title">회원 탈퇴</h1>
          <p className="page-desc">탈퇴하면 되돌릴 수 없습니다. 아래 내용을 확인한 뒤 탈퇴하세요.</p>
        </div>
      </div>

      <section className="detail-card">
        <h2 className="card-title">탈퇴하면</h2>
        <ul className="withdraw-effects">
          <li>
            <strong>담당 복지자원 {info.resourceCount}개</strong> — 담당자가 '퇴사자'로 바뀌고, 이후 조회만 할 수 있습니다.
          </li>
          <li>
            <strong>AI 대화 기록 {info.conversationCount}개</strong> — 모두 지웁니다.
          </li>
          <li>
            <strong>공동 담당 사례자 {info.sharedCaseCount}명</strong> — 내 담당자 지정만 지우고, 다른 담당자는 그대로입니다.
          </li>
          <li>
            <strong>회원 정보</strong> — 탈퇴 처리되어 로그인할 수 없고, 같은 이메일로 다시 가입할 수 없습니다.
          </li>
        </ul>
      </section>

      <section className="detail-card">
        <div className="card-head">
          <h2 className="card-title">
            넘길 사례자 <span className="card-count">{info.soleCases.length}명</span>
          </h2>
          {info.soleCases.length > 0 && !blocked && (
            <div className="bulk-pick">
              <select
                className="input"
                aria-label="모두 같은 담당자로"
                value={bulkPick}
                onChange={(event) => setBulkPick(event.target.value)}
              >
                <option value="">모두 같은 담당자로…</option>
                {info.successors.map((item) => (
                  <option key={item.memberId} value={item.memberId}>
                    {successorLabel(item)}
                  </option>
                ))}
              </select>
              <button type="button" className="btn btn-outline btn-small" disabled={!bulkPick} onClick={applyBulk}>
                모두 적용
              </button>
            </div>
          )}
        </div>
        <p className="field-hint my-card-hint">
          내가 유일한 담당자인 사례자는 탈퇴 전에 같은 기관의 다른 회원에게 넘겨야 합니다. 기관에서 정한 담당자를 고르세요.
        </p>
        {info.soleCases.length === 0 && <p className="withdraw-none">내가 유일한 담당자인 사례자가 없습니다.</p>}
        {blocked && (
          <p className="notice-bar notice-warning" role="alert">
            넘겨받을 회원이 없어 탈퇴할 수 없습니다. 기관에 다른 회원이 가입한 뒤 다시 시도하세요.
          </p>
        )}
        {info.soleCases.length > 0 && (
          <table className="data-table transfer-table">
            <thead>
              <tr>
                <th>관리번호</th>
                <th>이름</th>
                <th>연령대</th>
                <th>지역</th>
                <th>최근 기록일</th>
                <th>넘겨받을 담당자</th>
              </tr>
            </thead>
            <tbody>
              {info.soleCases.map((item) => {
                const missing = showErrors && !picks[item.caseId]
                return (
                  <tr key={item.caseId} className={missing ? "is-missing" : undefined}>
                    <td>{item.managementNo}</td>
                    <td>{item.name}</td>
                    <td>{item.ageGroup}</td>
                    <td>{item.dongName}</td>
                    <td>{item.lastRecordedAt ?? "-"}</td>
                    <td>
                      <select
                        className="input"
                        aria-label={`${item.name} 넘겨받을 담당자`}
                        aria-invalid={missing}
                        disabled={blocked}
                        value={picks[item.caseId] ?? ""}
                        onChange={(event) =>
                          setPicks({ ...picks, [item.caseId]: Number(event.target.value) || 0 })
                        }
                      >
                        <option value="">고르세요</option>
                        {info.successors.map((member) => (
                          <option key={member.memberId} value={member.memberId}>
                            {successorLabel(member)}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <div className="form-actions">
        <FieldError
          message={showErrors && !blocked && unpicked.length > 0 ? `넘겨받을 담당자를 모두 고르세요. (${unpicked.length}명 남음)` : null}
        />
        <div className="form-buttons">
          <button type="button" className="btn btn-outline" onClick={() => navigate(PATHS.my)}>
            취소
          </button>
          <button type="button" className="btn btn-danger" disabled={blocked} onClick={startWithdraw}>
            탈퇴하기
          </button>
        </div>
      </div>

      {dialogOpen && <WithdrawDialog onCancel={() => setDialogOpen(false)} onConfirm={withdraw} />}
    </section>
  )
}

/** 탈퇴 확인 창: 비밀번호를 한 번 더 입력 (M7-B). 틀리면 창 안에 안내 */
function WithdrawDialog({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void
  /** 실패 문구(비밀번호 불일치)를 돌려주면 창에 표시, null이면 창을 닫거나 화면이 바뀜 */
  onConfirm: (password: string) => string | null
}) {
  const [password, setPassword] = useState(DEMO_PASSWORD)
  const [error, setError] = useState<string | null>(null)

  useDevScenario(
    {
      screen: "회원 탈퇴 확인 창",
      actions: [
        { label: "맞는 비밀번호 채우기", run: () => setPassword(DEMO_PASSWORD) },
        { label: "틀린 비밀번호 채우기", run: () => setPassword("wrong-1234!") },
      ],
    },
    [],
  )

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [onCancel])

  const confirm = () => {
    if (!password) {
      setError("비밀번호를 입력하세요.")
      return
    }
    setError(onConfirm(password))
  }

  const frame = document.querySelector(".prototype-frame") ?? document.body
  return createPortal(
    <div className="dialog-backdrop" onClick={onCancel}>
      <div
        className="dialog withdraw-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="withdraw-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="withdraw-title">정말 탈퇴할까요?</h2>
        <p>탈퇴하면 되돌릴 수 없습니다. 계속하려면 비밀번호를 입력하세요.</p>
        <PasswordInput
          aria-label="탈퇴 확인 비밀번호"
          autoComplete="current-password"
          value={password}
          autoFocus
          aria-invalid={Boolean(error)}
          onChange={(event) => {
            setPassword(event.target.value)
            setError(null)
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") confirm()
          }}
        />
        <FieldError message={error} />
        <div className="dialog-actions">
          <button type="button" className="btn btn-outline" onClick={onCancel}>
            취소
          </button>
          <button type="button" className="btn btn-danger" onClick={confirm}>
            탈퇴
          </button>
        </div>
      </div>
    </div>,
    frame,
  )
}
