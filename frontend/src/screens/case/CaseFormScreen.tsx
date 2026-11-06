import "@/styles/list.css"
import "@/styles/detail.css"
import "@/styles/form.css"
import "@/styles/case.css"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState, type FormEvent, type ReactNode } from "react"
import { useLocation, useNavigate, useParams } from "react-router"
import { caseApi, caseKeys, type CaseInput, type Gender } from "@/api/caseApi"
import { errorMessage, isApiError } from "@/api/errors"
import { memberApi, memberKeys, type MemberOption } from "@/api/memberApi"
import { FieldError } from "@/components/common/FieldError"
import { PATHS } from "@/routes/paths"
import { caseAccessErrorOf, CASE_MESSAGES, fieldErrorsOf, type CaseAccessError } from "@/screens/case/caseErrors"
import {
  CASE_FORM_FIELDS,
  CASE_NAME_MAX,
  emptyCaseForm,
  formFromDetail,
  sameCaseForm,
  toCaseInput,
  validateCaseForm,
  type CaseForm,
  type CaseFormErrors,
} from "@/screens/case/caseForm"
import { readCaseNavState } from "@/screens/case/caseNav"
import { CaseAccessErrorView, CaseLoadFailed, CaseLoading } from "@/screens/case/CaseStatusViews"
import { RegionSelects } from "@/screens/case/RegionSelects"
import { useSession } from "@/session/sessionStore"
import { confirmDialog } from "@/stores/confirmStore"
import { leaveGuard, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"
import { ageGroupOf, ageOn } from "@/utils/age"
import { isValidDateString, todayString } from "@/utils/datetime"

/**
 * 4.2.1 사례자 정보 등록(/cases/new, API-22)·수정(/cases/:caseId/edit, API-23) — 같은 양식 (D5-B)
 * - 등록: 등록한 회원이 담당자(뺄 수 없음, 서버도 자동 추가), 관리번호는 서버가 발급, 등록 후 상세로
 * - 수정: 관리번호는 바꿀 수 없음(D9-A), 본인도 담당자에서 뺄 수 있음(D6-B, 확인 창 → 저장 후 목록)
 * - 저장 전 같은 이름·생년월일 중복 확인 (API-21, 내 담당 사례자 안에서, 확인 창 후 계속 가능)
 * - 바뀐 내용이 있으면 화면을 떠날 때 경고. 저장에 실패하면 입력값을 그대로 둔다
 */
export function CaseFormScreen({ mode }: { mode: "new" | "edit" }) {
  const params = useParams()
  const parsedId = Number(params.caseId)
  const caseId = mode === "edit" && Number.isSafeInteger(parsedId) && parsedId > 0 ? parsedId : null
  const navigate = useNavigate()
  const location = useLocation()
  const nav = readCaseNavState(location.state)
  const session = useSession()
  const profile = session.status === "authenticated" ? session.profile : null
  const myMemberId = profile?.memberId ?? 0
  const queryClient = useQueryClient()

  const detailQuery = useQuery({
    queryKey: caseKeys.detail(caseId ?? 0),
    queryFn: () => caseApi.getCase(caseId ?? 0),
    enabled: caseId !== null,
  })
  const membersQuery = useQuery({ queryKey: memberKeys.orgMembers, queryFn: memberApi.getOrgMembers })
  const detail = detailQuery.data ?? null

  const [baseline, setBaseline] = useState<CaseForm | null>(() =>
    mode === "new" && profile ? emptyCaseForm(profile) : null,
  )
  const [form, setForm] = useState<CaseForm | null>(baseline)
  const [showErrors, setShowErrors] = useState(false)
  const [serverErrors, setServerErrors] = useState<CaseFormErrors>({})
  const [accessError, setAccessError] = useState<CaseAccessError | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // 수정: 사례자 정보를 처음 받았을 때 한 번만 입력칸을 채운다 (다시 받아도 입력 중인 값을 덮지 않는다)
  useEffect(() => {
    if (mode !== "edit" || !detail || baseline !== null) return
    const loaded = formFromDetail(detail)
    setBaseline(loaded)
    setForm(loaded)
  }, [mode, detail, baseline])

  const duplicateCheck = useMutation({ mutationFn: caseApi.checkDuplicate })
  const createCase = useMutation({ mutationFn: caseApi.createCase })
  const updateCase = useMutation({ mutationFn: (input: CaseInput) => caseApi.updateCase(caseId ?? 0, input) })

  const access: CaseAccessError | null =
    accessError ?? caseAccessErrorOf(detailQuery.error) ?? (mode === "edit" && caseId === null ? "NOT_FOUND" : null)
  const dirty = !access && form !== null && baseline !== null && !sameCaseForm(form, baseline)
  useLeaveGuard(dirty)

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

  if (access) {
    return (
      <section className="screen case-form">
        <CaseAccessErrorView
          error={access}
          forbiddenDescription="담당자로 지정된 사례자만 수정할 수 있습니다."
          onBack={() => navigate(PATHS.cases, { replace: true })}
        />
      </section>
    )
  }

  if (mode === "edit" && detailQuery.isError) {
    return (
      <section className="screen case-form">
        <CaseLoadFailed
          title="사례자 정보를 불러오지 못했습니다."
          message={errorMessage(detailQuery.error)}
          onRetry={() => void detailQuery.refetch()}
        />
      </section>
    )
  }

  if (!form) {
    return (
      <section className="screen case-form">
        <CaseLoading text="사례자 정보를 불러오는 중입니다." />
      </section>
    )
  }

  const errors = validateCaseForm(form)
  const visible: CaseFormErrors = showErrors ? { ...serverErrors, ...errors } : serverErrors
  const birthOk = isValidDateString(form.birthDate) && form.birthDate <= todayString()
  const age = birthOk ? ageOn(form.birthDate) : null

  // 담당자 후보: 같은 기관 활성 회원. 지금 담당자 중 목록에 없는 사람도 빼지 않고 보여 준다
  const members: MemberOption[] = membersQuery.data ?? []
  const options: MemberOption[] = [
    ...members,
    ...(detail?.managers ?? []).filter((manager) => !members.some((item) => item.memberId === manager.memberId)),
  ]

  /** 저장 실패: 권한 없음·찾을 수 없음은 안내 화면으로, 그 밖은 입력값을 두고 버튼 위·입력칸 아래에 표시 */
  const fail = (error: unknown) => {
    const accessCode = mode === "edit" ? caseAccessErrorOf(error) : null
    if (accessCode) {
      setAccessError(accessCode)
      return
    }
    if (!isApiError(error)) {
      setSubmitError(errorMessage(error))
      return
    }
    switch (error.code) {
      case "VALIDATION_ERROR": {
        const fields = fieldErrorsOf(error, CASE_FORM_FIELDS)
        setServerErrors(fields)
        if (Object.keys(fields).length > 0) {
          setSubmitError(CASE_MESSAGES.validation)
          return
        }
        // 화면 검사를 통과했는데 칸 표시 없이 거절되면 대개 담당자가 더 이상 같은 기관 활성 회원이 아닌 경우다
        setSubmitError(CASE_MESSAGES.validationWithoutField)
        void membersQuery.refetch()
        return
      }
      case "MANAGEMENT_NUMBER_EXHAUSTED":
        setSubmitError(CASE_MESSAGES.managementNumberExhausted)
        return
      case "STATE_CONFLICT":
        setSubmitError(CASE_MESSAGES.stateConflict)
        void reloadDetail()
        return
      default:
        setSubmitError(errorMessage(error))
    }
  }

  /** 다른 곳에서 바뀐 경우(409 STATE_CONFLICT): 사례자 정보·담당자 후보를 다시 받아 입력칸을 최신 내용으로 채운다.
   *  다시 받다가 403·404가 나면 detailQuery.error로 안내 화면이 뜬다 */
  const reloadDetail = async () => {
    const [result] = await Promise.all([detailQuery.refetch(), membersQuery.refetch()])
    if (!result.isSuccess) return
    const loaded = formFromDetail(result.data)
    setBaseline(loaded)
    setForm(loaded)
    setShowErrors(false)
  }

  /** 저장한 뒤: 목록·상세는 다음에 열 때 다시 받는다 (지금 화면의 조회는 다시 부르지 않는다) */
  const saved = () => {
    leaveGuard.release()
    void queryClient.invalidateQueries({ queryKey: caseKeys.all, refetchType: "none" })
  }

  const save = async (input: CaseInput) => {
    // 같은 이름·생년월일 확인: 등록할 때, 수정에서는 이름이나 생년월일을 바꿨을 때
    const identityChanged = !detail || input.name !== detail.name || input.birthDate !== detail.birthDate
    if (identityChanged) {
      let duplicates
      try {
        duplicates = (
          await duplicateCheck.mutateAsync({ name: input.name, birthDate: input.birthDate, excludeCaseId: caseId })
        ).duplicates
      } catch (error) {
        fail(error)
        return
      }
      if (duplicates.length > 0) {
        const list = duplicates.map((item) => `${item.managementNo} ${item.name}`).join("\n")
        const ok = await confirmDialog({
          title: "이름과 생년월일이 같은 사례자가 있습니다.",
          message: `내가 담당하는 사례자 중 같은 사례자가 있습니다.\n${list}\n같은 사람인지 확인하세요.`,
          confirmLabel: mode === "new" ? "그래도 등록" : "그래도 저장",
        })
        if (!ok) return
      }
    }

    if (caseId === null) {
      let created
      try {
        created = await createCase.mutateAsync(input)
      } catch (error) {
        fail(error)
        return
      }
      saved()
      showToast(`사례자를 등록했습니다. (관리번호 ${created.managementNo})`)
      // 등록 화면은 뒤로 가기 기록에서 빼고 상세로 (뒤로 가면 목록)
      navigate(PATHS.caseDetail(created.caseId), { replace: true, state: { listSearch: nav.listSearch } })
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
    try {
      await updateCase.mutateAsync(input)
    } catch (error) {
      fail(error)
      return
    }
    saved()
    if (removingMe) {
      showToast("담당자에서 빠져 사례자 목록으로 이동했습니다.")
      navigate(`${PATHS.cases}${nav.listSearch ?? ""}`, { replace: true })
      return
    }
    showToast("사례자 정보를 수정했습니다.")
    if (nav.fromDetail) navigate(-1)
    else navigate(PATHS.caseDetail(caseId), { replace: true, state: { listSearch: nav.listSearch } })
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (submitting) return
    setSubmitError(null)
    setServerErrors({})
    if (Object.keys(errors).length > 0) {
      setShowErrors(true)
      return
    }
    const input = toCaseInput(form)
    // 등록: 본인을 담당자에 넣어 보낸다 (계약 minItems 1. 서버도 본인을 자동 추가한다)
    if (caseId === null && !input.managerMemberIds.includes(myMemberId)) {
      input.managerMemberIds = [myMemberId, ...input.managerMemberIds]
    }
    setSubmitting(true)
    try {
      await save(input)
    } finally {
      setSubmitting(false)
    }
  }

  const update = (patch: Partial<CaseForm>) => {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev))
    setServerErrors({})
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
            maxLength={CASE_NAME_MAX}
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
            {options.map((member) => {
              const isMe = member.memberId === myMemberId
              const locked = mode === "new" && isMe
              // 지금 담당자지만 같은 기관 활성 회원 목록(API-42)에 없는 사람: 그대로 저장하면 서버가 400으로 거절한다
              const inactive = membersQuery.isSuccess && !members.some((item) => item.memberId === member.memberId)
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
                  {inactive && <span className="field-hint-inline"> (기관 회원 목록에 없음, 빼고 저장하세요)</span>}
                </label>
              )
            })}
          </div>
          {membersQuery.isPending && <p className="field-hint">담당자 목록을 불러오는 중입니다.</p>}
          {membersQuery.isError && <p className="field-hint">담당자 목록을 불러오지 못했습니다. {errorMessage(membersQuery.error)}</p>}
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
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? "저장 중" : mode === "new" ? "등록" : "저장"}
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
