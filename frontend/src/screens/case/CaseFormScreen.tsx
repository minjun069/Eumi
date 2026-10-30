import { useEffect, useState, type FormEvent, type ReactNode } from "react"
import { useLocation, useNavigate, useParams } from "react-router"
import { EmptyState } from "@/components/common/EmptyState"
import { FieldError } from "@/components/common/FieldError"
import { devCases } from "@/devtools/devCases"
import { useDevScenario } from "@/devtools/devScenarioStore"
import {
  CASE_FORBIDDEN_MESSAGE,
  CASE_NOT_FOUND_MESSAGE,
  caseApi,
  type CaseDetail,
  type CaseManagerItem,
} from "@/mock/api/caseApi"
import { memberApi } from "@/mock/api/memberApi"
import { PATHS } from "@/routes/paths"
import {
  applyFill,
  CASE_NEW_FILLS,
  exampleCaseForm,
  formFromDetail,
  sameCaseForm,
  toCaseInput,
  validateCaseForm,
  type CaseForm,
} from "@/screens/case/caseForm"
import { readCaseNavState } from "@/screens/case/caseNav"
import { RegionSelects } from "@/screens/case/RegionSelects"
import { useSession } from "@/session/sessionStore"
import { confirmDialog } from "@/stores/confirmStore"
import { leaveGuard, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"
import type { Gender } from "@/types/domain"
import { ageGroupOf, ageOn } from "@/utils/age"
import { isValidDateString, todayString } from "@/utils/datetime"

/**
 * 4.2.1 사례자 정보 등록(/cases/new)·수정(/cases/:caseId/edit) — 같은 양식 (D5-B)
 * - 등록: 등록한 회원이 담당자(뺄 수 없음), 관리번호 자동 부여, 등록 후 상세로
 * - 수정: 관리번호는 바꿀 수 없음(D9-A), 본인도 담당자에서 뺄 수 있음(D6-B, 확인 창 → 저장 후 목록)
 * - 저장 전 같은 이름·생년월일 중복 확인 (내 담당 사례자 안에서, 확인 창 후 계속 가능)
 * - 바뀐 내용이 있으면 화면을 떠날 때 경고
 */
export function CaseFormScreen({ mode }: { mode: "new" | "edit" }) {
  const params = useParams()
  const caseId = mode === "edit" ? Number(params.caseId) : null
  const navigate = useNavigate()
  const location = useLocation()
  const nav = readCaseNavState(location.state)
  const session = useSession()
  const myMemberId = session.status === "authenticated" ? session.memberId : 0

  const [members, setMembers] = useState<CaseManagerItem[]>([])
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [baseline, setBaseline] = useState<CaseForm | null>(() =>
    mode === "new" ? exampleCaseForm(myMemberId) : null,
  )
  const [form, setForm] = useState<CaseForm | null>(baseline)
  const [showErrors, setShowErrors] = useState(false)
  const [accessError, setAccessError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // 수정: 사례자 정보 조회 → 담당자 후보(같은 기관 회원) 조회. 등록: 담당자 후보만
  useEffect(() => {
    if (caseId !== null) {
      const result = caseApi.getCase({ caseId })
      if (!result.ok) {
        fail(result.message)
        return
      }
      const loaded = formFromDetail(result.data)
      setDetail(result.data)
      setBaseline(loaded)
      setForm(loaded)
    }
    const membersResult = memberApi.getOrgMembers("4.2.1")
    if (membersResult.ok) setMembers(membersResult.data)
  }, [])

  const dirty = !accessError && form !== null && baseline !== null && !sameCaseForm(form, baseline)
  useLeaveGuard(dirty)

  /** 권한 없음·찾을 수 없음이면 안내 화면으로, 그 밖의 실패는 버튼 위에 표시 */
  function fail(message: string) {
    if (message === CASE_FORBIDDEN_MESSAGE || message === CASE_NOT_FOUND_MESSAGE) setAccessError(message)
    else setSubmitError(message)
  }

  const update = (patch: Partial<CaseForm>) => setForm((prev) => (prev ? { ...prev, ...patch } : prev))

  const fills =
    mode === "new"
      ? CASE_NEW_FILLS
      : [
          { label: "중복: 조말순과 같게", patch: () => ({ name: "조말순", birthDate: "1938-12-12" }) },
          { label: "최초 등록일을 작년으로", patch: () => ({ firstRegisteredAt: "2025-06-01" }) },
          {
            label: "빈칸 채우기",
            patch: () => ({ name: "", birthDate: "", gender: "" as const, dongCode: null, firstRegisteredAt: "" }),
          },
          { label: "미래 날짜 채우기", patch: () => ({ birthDate: "2030-01-01", firstRegisteredAt: "2030-01-01" }) },
        ]

  useDevScenario(
    {
      screen: mode === "new" ? "사례자 등록" : "사례자 수정",
      hint: "채우기 버튼은 입력칸만 바꿉니다. 저장을 눌러 결과를 확인하세요. 입력을 바꾼 뒤 메뉴·취소·뒤로 가기·로그아웃을 누르면 '저장하지 않은 내용' 경고가 뜹니다.",
      actions: [
        ...fills.map((fill) => ({
          label: fill.label,
          run: () => setForm((prev) => (prev ? applyFill(prev, fill.patch()) : prev)),
        })),
        ...(mode === "edit"
          ? [
              {
                label: "담당자에서 본인 빼기",
                run: () =>
                  setForm((prev) => {
                    if (!prev) return prev
                    const others = prev.managerMemberIds.filter((id) => id !== myMemberId)
                    const substitute = members.find((item) => item.memberId !== myMemberId)?.memberId
                    return {
                      ...prev,
                      managerMemberIds: others.length > 0 || !substitute ? others : [substitute],
                    }
                  }),
              },
            ]
          : []),
      ],
      groups:
        caseId !== null
          ? [
              {
                title: "다른 담당자가 한 일",
                actions: [
                  { label: "이 사례자를 삭제함", run: () => devCases.deleteCase(caseId) },
                  { label: "나를 담당자에서 뺌", run: () => devCases.removeMe(caseId) },
                ],
              },
            ]
          : [],
      infos: [{ label: "저장하지 않은 내용", value: dirty ? "있음" : "없음" }],
    },
    [mode, caseId, dirty, members],
  )

  const backLabel = mode === "new" ? "< 목록으로" : "< 사례자 상세로"

  /** 취소: 온 곳으로 돌아간다 (바뀐 내용이 있으면 경고) */
  const cancel = () => {
    if (mode === "edit") {
      if (nav.fromDetail) navigate(-1)
      else navigate(PATHS.caseDetail(caseId ?? ""), { state: { listSearch: nav.listSearch } })
      return
    }
    if (nav.listSearch !== undefined) navigate(-1)
    else navigate(PATHS.cases)
  }

  if (accessError) {
    return (
      <section className="screen case-form">
        <div className="case-access-error">
          <EmptyState
            title={accessError}
            description={
              accessError === CASE_FORBIDDEN_MESSAGE
                ? "담당자로 지정된 사례자만 수정할 수 있습니다."
                : "삭제되었거나 주소가 잘못되었습니다."
            }
          />
          <button type="button" className="btn btn-outline" onClick={() => navigate(PATHS.cases, { replace: true })}>
            목록으로
          </button>
        </div>
      </section>
    )
  }

  if (!form) return null

  const errors = validateCaseForm(form)
  const visible = showErrors ? errors : {}
  const birthOk = isValidDateString(form.birthDate) && form.birthDate <= todayString()
  const age = birthOk ? ageOn(form.birthDate) : null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitError(null)
    if (Object.keys(errors).length > 0) {
      setShowErrors(true)
      return
    }
    const input = toCaseInput(form)

    // 같은 이름·생년월일 확인: 등록할 때, 수정에서는 이름이나 생년월일을 바꿨을 때
    const identityChanged = !detail || input.name !== detail.name || input.birthDate !== detail.birthDate
    if (identityChanged) {
      const check = caseApi.checkDuplicate({
        name: input.name,
        birthDate: input.birthDate,
        excludeCaseId: caseId,
      })
      if (!check.ok) {
        fail(check.message)
        return
      }
      if (check.data.duplicates.length > 0) {
        const list = check.data.duplicates.map((item) => `${item.managementNo} ${item.name}`).join("\n")
        const ok = await confirmDialog({
          title: "이름과 생년월일이 같은 사례자가 있습니다.",
          message: `내가 담당하는 사례자 중 같은 사례자가 있습니다.\n${list}\n같은 사람인지 확인하세요.`,
          confirmLabel: mode === "new" ? "그래도 등록" : "그래도 저장",
        })
        if (!ok) return
      }
    }

    if (caseId === null) {
      const result = caseApi.createCase(input)
      if (!result.ok) {
        fail(result.message)
        return
      }
      leaveGuard.release()
      showToast(`사례자를 등록했습니다. (관리번호 ${result.data.managementNo})`)
      // 등록 화면은 뒤로 가기 기록에서 빼고 상세로 (뒤로 가면 목록)
      navigate(PATHS.caseDetail(result.data.caseId), { replace: true, state: { listSearch: nav.listSearch } })
      return
    }

    const removingMe = !input.managerMemberIds.includes(myMemberId)
    if (removingMe) {
      const ok = await confirmDialog({
        title: "담당자에서 본인을 뺄까요?",
        message: "저장하면 이 사례자를 더 이상 볼 수 없습니다.",
        confirmLabel: "저장",
      })
      if (!ok) return
    }
    const result = caseApi.updateCase({ caseId, ...input })
    if (!result.ok) {
      fail(result.message)
      return
    }
    leaveGuard.release()
    if (removingMe) {
      showToast("담당자에서 빠져 사례자 목록으로 이동했습니다.")
      navigate(`${PATHS.cases}${nav.listSearch ?? ""}`, { replace: true })
      return
    }
    showToast("사례자 정보를 수정했습니다.")
    if (nav.fromDetail) navigate(-1)
    else navigate(PATHS.caseDetail(caseId), { replace: true, state: { listSearch: nav.listSearch } })
  }

  const toggleManager = (memberId: number, checked: boolean) =>
    update({
      managerMemberIds: checked
        ? [...form.managerMemberIds, memberId]
        : form.managerMemberIds.filter((id) => id !== memberId),
    })

  return (
    <section className="screen case-form">
      <button type="button" className="back-link" onClick={cancel}>
        {backLabel}
      </button>
      <div className="page-heading">
        <div>
          <h1 className="page-title">{mode === "new" ? "사례자 등록" : "사례자 정보 수정"}</h1>
          <p className="page-desc">
            {mode === "new" ? "새 사례자의 정보를 입력합니다." : `${detail?.name} 님의 정보를 수정합니다.`}{" "}
            <em className="required">*</em> 표시는 필수 항목입니다.
          </p>
        </div>
      </div>

      <form className="detail-card form-card case-form-card" onSubmit={(event) => void submit(event)} noValidate>
        <FormRow label="관리번호">
          <div className="input input-readonly form-short">
            {detail ? detail.managementNo : <span className="text-muted">등록하면 자동으로 부여됩니다.</span>}
          </div>
          {detail && <p className="field-hint">관리번호는 바꿀 수 없습니다. 최초 등록일을 고쳐도 그대로입니다.</p>}
        </FormRow>

        <FormRow label="이름" required>
          <input
            className="input form-short"
            aria-label="이름"
            value={form.name}
            aria-invalid={Boolean(visible.name)}
            onChange={(event) => update({ name: event.target.value })}
          />
          <FieldError message={visible.name} />
        </FormRow>

        <FormRow label="생년월일" required>
          <div className="inline-controls">
            <input
              className="input form-date"
              type="date"
              aria-label="생년월일"
              max={todayString()}
              value={form.birthDate}
              aria-invalid={Boolean(visible.birthDate)}
              onChange={(event) => update({ birthDate: event.target.value })}
            />
            <span className="age-preview">{age !== null ? `만 ${age}세 · ${ageGroupOf(age)}` : ""}</span>
          </div>
          <FieldError message={visible.birthDate} />
        </FormRow>

        <FormRow label="성별" required>
          <div className="radio-group" role="radiogroup" aria-label="성별">
            {(["남", "여"] as Gender[]).map((gender) => (
              <label key={gender} className="checkbox">
                <input
                  type="radio"
                  name="gender"
                  value={gender}
                  checked={form.gender === gender}
                  onChange={() => update({ gender })}
                />
                {gender}
              </label>
            ))}
          </div>
          <FieldError message={visible.gender} />
        </FormRow>

        <FormRow label="지역" required>
          <RegionSelects
            featureId="4.2.1"
            value={{ sidoCode: form.sidoCode, sigunguCode: form.sigunguCode, dongCode: form.dongCode }}
            invalid={Boolean(visible.region)}
            onChange={(region) => update(region)}
          />
          <FieldError message={visible.region} />
        </FormRow>

        <FormRow label="최초 등록일" required>
          <input
            className="input form-date"
            type="date"
            aria-label="최초 등록일"
            max={todayString()}
            value={form.firstRegisteredAt}
            aria-invalid={Boolean(visible.firstRegisteredAt)}
            onChange={(event) => update({ firstRegisteredAt: event.target.value })}
          />
          <FieldError message={visible.firstRegisteredAt} />
        </FormRow>

        <FormRow label="담당자" required>
          <div className="manager-list" role="group" aria-label="담당자">
            {members.map((member) => {
              const isMe = member.memberId === myMemberId
              const locked = mode === "new" && isMe
              return (
                <label key={member.memberId} className="checkbox manager-option">
                  <input
                    type="checkbox"
                    checked={locked || form.managerMemberIds.includes(member.memberId)}
                    disabled={locked}
                    onChange={(event) => toggleManager(member.memberId, event.target.checked)}
                  />
                  {[member.name, member.title].filter(Boolean).join(" ")}
                  {isMe && (
                    <span className="field-hint-inline">
                      {locked ? " (본인, 등록하면 자동으로 지정)" : " (본인)"}
                    </span>
                  )}
                </label>
              )
            })}
          </div>
          {mode === "edit" && (
            <p className="field-hint">본인을 빼면 저장한 뒤 이 사례자를 더 이상 볼 수 없습니다.</p>
          )}
          <FieldError message={visible.managers} />
        </FormRow>

        <div className="form-actions">
          <FieldError message={submitError} />
          <div className="form-buttons">
            <button type="button" className="btn btn-outline" onClick={cancel}>
              취소
            </button>
            <button type="submit" className="btn btn-primary">
              {mode === "new" ? "등록" : "저장"}
            </button>
          </div>
        </div>
      </form>
    </section>
  )
}

function FormRow({ label, required = false, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <div className="form-row">
      <span className="form-label">
        {label}
        {required && <em className="required"> *</em>}
      </span>
      <div className="form-control">{children}</div>
    </div>
  )
}
