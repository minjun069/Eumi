import "@/styles/detail.css"
import "@/styles/form.css"
import "@/styles/resource.css"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState, type FormEvent, type ReactNode } from "react"
import { useLocation, useNavigate, useParams } from "react-router"
import { errorMessage, isApiError } from "@/api/errors"
import { memberApi, memberKeys, type MemberOption } from "@/api/memberApi"
import {
  RESOURCE_TEXT_LIMITS,
  resourceApi,
  resourceKeys,
  type ResourceInput,
  type ResourceStatus,
  type SupportAgeGroup,
  type SupportGender,
} from "@/api/resourceApi"
import { FieldError } from "@/components/common/FieldError"
import { PATHS } from "@/routes/paths"
import { fieldErrorsOf } from "@/screens/case/caseErrors"
import { RegionSelects } from "@/screens/case/RegionSelects"
import { resourceAccessErrorOf, RESOURCE_MESSAGES, type ResourceAccessError } from "@/screens/resource/resourceErrors"
import {
  emptyResourceForm,
  fieldOf,
  formFromDetail,
  formNotices,
  RESOURCE_FORM_FIELDS,
  sameResourceForm,
  toResourceInput,
  validateResourceForm,
  type ResourceForm,
  type ResourceFormErrors,
  type ResourceFormField,
} from "@/screens/resource/resourceForm"
import { formatFee } from "@/screens/resource/resourceFormat"
import { readResourceNavState } from "@/screens/resource/resourceNav"
import { ResourceAccessErrorView, ResourceLoadFailed, ResourceLoading } from "@/screens/resource/ResourceStatusViews"
import { useSession } from "@/session/sessionStore"
import { confirmDialog } from "@/stores/confirmStore"
import { leaveGuard, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"
import { AGE_GROUPS } from "@/utils/age"

const SUPPORT_AGE_GROUPS: SupportAgeGroup[] = [...AGE_GROUPS, "무관"]

/**
 * 3.3 복지자원 등록(/resources/new, API-17)·수정(/resources/:resourceId/edit, API-15) — 같은 등록 양식 (3.3.1)
 * - 등록: 담당자 처음 값은 본인. 등록 후 상세로
 * - 수정: 지금 담당자 본인만(상세의 editable, 서버도 다시 검사). 저장 후 상세로
 * - 담당자를 다른 사람으로 고르면 저장 전에 확인 (저장하면 수정·삭제할 수 없게 됨)
 * - 바뀐 내용이 있으면 화면을 떠날 때 경고. 저장에 실패하면 입력값을 그대로 둔다
 * - PDF 자동 입력(3.3.2, API-18)은 아직 붙이지 않았다
 */
export function ResourceFormScreen({ mode }: { mode: "new" | "edit" }) {
  const params = useParams()
  const parsedId = Number(params.resourceId)
  const resourceId = mode === "edit" && Number.isSafeInteger(parsedId) && parsedId > 0 ? parsedId : null
  const navigate = useNavigate()
  const location = useLocation()
  const nav = readResourceNavState(location.state)
  const session = useSession()
  const profile = session.status === "authenticated" ? session.profile : null
  const myMemberId = profile?.memberId ?? 0
  const queryClient = useQueryClient()

  const detailQuery = useQuery({
    queryKey: resourceKeys.detail(resourceId ?? 0),
    queryFn: () => resourceApi.getResource(resourceId ?? 0),
    enabled: resourceId !== null,
  })
  const membersQuery = useQuery({ queryKey: memberKeys.orgMembers, queryFn: memberApi.getOrgMembers })
  const detail = detailQuery.data ?? null

  const [baseline, setBaseline] = useState<ResourceForm | null>(() =>
    mode === "new" && profile ? emptyResourceForm(profile) : null,
  )
  const [form, setForm] = useState<ResourceForm | null>(baseline)
  const [showErrors, setShowErrors] = useState(false)
  const [serverErrors, setServerErrors] = useState<ResourceFormErrors>({})
  const [accessError, setAccessError] = useState<ResourceAccessError | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // 수정: 자원 정보를 처음 받았을 때 한 번만 입력칸을 채운다 (다시 받아도 입력 중인 값을 덮지 않는다)
  useEffect(() => {
    if (mode !== "edit" || !detail || baseline !== null) return
    const loaded = formFromDetail(detail)
    setBaseline(loaded)
    setForm(loaded)
  }, [mode, detail, baseline])

  const createResource = useMutation({ mutationFn: resourceApi.createResource })
  const updateResource = useMutation({
    mutationFn: (input: ResourceInput) => resourceApi.updateResource(resourceId ?? 0, input),
  })

  // 수정 화면을 연 사람이 지금 담당자가 아니면(상세의 editable=false) 처음부터 막는다
  const access: ResourceAccessError | null =
    accessError ??
    resourceAccessErrorOf(detailQuery.error) ??
    (mode === "edit" && resourceId === null ? "NOT_FOUND" : null) ??
    (detail && !detail.editable ? "FORBIDDEN" : null)
  const dirty = !access && form !== null && baseline !== null && !sameResourceForm(form, baseline)
  useLeaveGuard(dirty)

  /** 취소: 온 곳으로 돌아간다 (바뀐 내용이 있으면 경고) */
  const cancel = () => {
    if (mode === "edit") {
      if (nav.fromDetail) navigate(-1)
      else navigate(PATHS.resourceDetail(resourceId ?? ""), { state: { listSearch: nav.listSearch } })
      return
    }
    if (nav.listSearch !== undefined) navigate(-1)
    else navigate(PATHS.resources)
  }

  if (access) {
    return (
      <section className="screen resource-form">
        {access === "FORBIDDEN" && resourceId !== null ? (
          <ResourceAccessErrorView
            error={access}
            backLabel="상세로"
            onBack={() => navigate(PATHS.resourceDetail(resourceId), { replace: true })}
          />
        ) : (
          <ResourceAccessErrorView
            error={access}
            backLabel="목록으로"
            onBack={() => navigate(PATHS.resources, { replace: true })}
          />
        )}
      </section>
    )
  }

  if (mode === "edit" && detailQuery.isError) {
    return (
      <section className="screen resource-form">
        <ResourceLoadFailed
          title="복지자원 정보를 불러오지 못했습니다."
          message={errorMessage(detailQuery.error)}
          onRetry={() => void detailQuery.refetch()}
        />
      </section>
    )
  }

  if (!form) {
    return (
      <section className="screen resource-form">
        <ResourceLoading text="복지자원 정보를 불러오는 중입니다." />
      </section>
    )
  }

  const errors = validateResourceForm(form)
  const visible: ResourceFormErrors = showErrors ? { ...serverErrors, ...errors } : serverErrors
  const notices = formNotices(form)

  // 담당자 후보: 같은 기관 활성 회원 (API-42). 목록을 못 받았거나 본인이 빠져 있어도 본인은 고를 수 있게 둔다
  const members: MemberOption[] = membersQuery.data ?? []
  const options: MemberOption[] =
    profile && !members.some((item) => item.memberId === myMemberId)
      ? [{ memberId: profile.memberId, name: profile.name, title: profile.title }, ...members]
      : members

  /** 저장 실패: 담당자 아님·찾을 수 없음은 안내 화면으로, 그 밖은 입력값을 두고 버튼 위·입력칸 아래에 표시 */
  const fail = (error: unknown) => {
    const accessCode = mode === "edit" ? resourceAccessErrorOf(error) : null
    if (accessCode) {
      setAccessError(accessCode)
      // 상세로 돌아가면 최신 담당자로 다시 그린다
      void queryClient.invalidateQueries({ queryKey: resourceKeys.all, refetchType: "none" })
      return
    }
    if (isApiError(error) && error.code === "VALIDATION_ERROR") {
      const fields = fieldErrorsOf(error, RESOURCE_FORM_FIELDS)
      // 담당자 오류: 고른 사람이 그사이 퇴사·기관 이동해 같은 기관 활성 회원이 아니다. 후보를 다시 받는다
      if (fields.manager) {
        fields.manager = RESOURCE_MESSAGES.managerInactive
        void membersQuery.refetch()
      }
      setServerErrors(fields)
      setSubmitError(Object.keys(fields).length > 0 ? RESOURCE_MESSAGES.validation : RESOURCE_MESSAGES.validationWithoutField)
      return
    }
    setSubmitError(errorMessage(error))
  }

  /** 저장한 뒤: 목록·상세는 다음에 열 때 다시 받는다 (지금 화면의 조회는 다시 부르지 않는다) */
  const saved = () => {
    leaveGuard.release()
    void queryClient.invalidateQueries({ queryKey: resourceKeys.all, refetchType: "none" })
  }

  const save = async (input: ResourceInput) => {
    // 담당자를 다른 사람으로 고르면 저장 뒤에는 이 자원을 수정·삭제할 수 없다
    const handingOver = input.managerMemberId !== myMemberId
    if (handingOver) {
      const manager = options.find((item) => item.memberId === input.managerMemberId)
      const ok = await confirmDialog({
        title: `담당자를 ${manager?.name ?? "다른 사람"}(으)로 지정할까요?`,
        message: "저장하면 이 자원을 수정·삭제할 수 없게 됩니다.",
        confirmLabel: mode === "new" ? "등록" : "저장",
      })
      if (!ok) return
    }

    if (resourceId === null) {
      let created
      try {
        created = await createResource.mutateAsync(input)
      } catch (error) {
        fail(error)
        return
      }
      saved()
      showToast("복지자원을 등록했습니다.")
      // 등록 화면은 뒤로 가기 기록에서 빼고 상세로 (뒤로 가면 목록)
      navigate(PATHS.resourceDetail(created.resourceId), { replace: true, state: { listSearch: nav.listSearch } })
      return
    }

    try {
      await updateResource.mutateAsync(input)
    } catch (error) {
      fail(error)
      return
    }
    saved()
    showToast(handingOver ? "담당자를 바꿔 저장했습니다. 이제 이 자원은 조회만 할 수 있습니다." : "복지자원을 수정했습니다.")
    if (nav.fromDetail) navigate(-1)
    else navigate(PATHS.resourceDetail(resourceId), { replace: true, state: { listSearch: nav.listSearch } })
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
    setSubmitting(true)
    try {
      await save(toResourceInput(form))
    } finally {
      setSubmitting(false)
    }
  }

  /** 직접 고친 항목은 서버가 알려 준 오류 표시를 지운다 */
  const update = (patch: Partial<ResourceForm>) => {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev))
    const touched = new Set((Object.keys(patch) as (keyof ResourceForm)[]).map(fieldOf))
    setServerErrors((prev) =>
      Object.fromEntries(Object.entries(prev).filter(([field]) => !touched.has(field as ResourceFormField))),
    )
  }

  /** '무관'은 단독 선택: 고르면 다른 연령대를 비우고, 다른 연령대를 고르면 '무관'을 뺀다 */
  const toggleAge = (age: SupportAgeGroup, checked: boolean) => {
    if (age === "무관") {
      update({ supportAgeGroups: checked ? ["무관"] : [] })
      return
    }
    const others = form.supportAgeGroups.filter((item) => item !== "무관" && item !== age)
    const next = checked ? [...others, age] : others
    update({ supportAgeGroups: SUPPORT_AGE_GROUPS.filter((item) => next.includes(item)) })
  }

  const feeOk = /^\d+$/.test(form.fee.trim())

  return (
    <section className="screen resource-form">
      <button type="button" className="back-link" onClick={cancel}>
        {mode === "new" ? "< 목록으로" : "< 복지자원 상세로"}
      </button>
      <div className="page-heading">
        <div>
          <h1 className="page-title">{mode === "new" ? "복지자원 등록" : "복지자원 수정"}</h1>
          <p className="page-desc">
            {mode === "new" ? "새 복지자원의 정보를 입력합니다." : `'${detail?.resourceName}'의 정보를 수정합니다.`}{" "}
            <em className="required">*</em> 표시는 필수 항목입니다.
          </p>
        </div>
      </div>

      <form className="detail-card form-card" onSubmit={(event) => void submit(event)} noValidate>
        <FormRow label="자원명" required error={visible.resourceName}>
          <TextInput
            label="자원명"
            value={form.resourceName}
            limit={RESOURCE_TEXT_LIMITS.resourceName}
            invalid={Boolean(visible.resourceName)}
            onChange={(resourceName) => update({ resourceName })}
          />
        </FormRow>

        <FormRow label="수행·담당 기관" required error={visible.operatingOrgName}>
          <TextInput
            label="수행·담당 기관"
            value={form.operatingOrgName}
            limit={RESOURCE_TEXT_LIMITS.operatingOrgName}
            invalid={Boolean(visible.operatingOrgName)}
            onChange={(operatingOrgName) => update({ operatingOrgName })}
          />
          <p className="field-hint">구청·외부 기관이 수행하는 자원이면 그 기관명을 적습니다.</p>
        </FormRow>

        <FormRow label="지원 대상" required error={visible.target}>
          <TextInput
            label="지원 대상"
            value={form.target}
            limit={RESOURCE_TEXT_LIMITS.target}
            wide
            invalid={Boolean(visible.target)}
            onChange={(target) => update({ target })}
          />
        </FormRow>

        <FormRow label="지원 연령" required error={visible.supportAgeGroups}>
          <div className="radio-group" role="group" aria-label="지원 연령">
            {SUPPORT_AGE_GROUPS.map((age) => (
              <label key={age} className="checkbox">
                <input
                  type="checkbox"
                  checked={form.supportAgeGroups.includes(age)}
                  onChange={(event) => toggleAge(age, event.target.checked)}
                />
                {age}
              </label>
            ))}
          </div>
          <p className="field-hint">여러 개를 고를 수 있습니다. 연령 조건이 없으면 '무관'을 고르세요.</p>
        </FormRow>

        <FormRow label="지원 성별" required error={visible.supportGender}>
          <div className="radio-group" role="radiogroup" aria-label="지원 성별">
            {(["남", "여", "무관"] as SupportGender[]).map((gender) => (
              <label key={gender} className="checkbox">
                <input
                  type="radio"
                  name="supportGender"
                  checked={form.supportGender === gender}
                  onChange={() => update({ supportGender: gender })}
                />
                {gender}
              </label>
            ))}
          </div>
        </FormRow>

        <FormRow label="지역" required error={visible.region}>
          <RegionSelects
            value={{ sidoCode: form.sidoCode, sigunguCode: form.sigunguCode, dongCode: form.dongCode }}
            invalid={Boolean(visible.region)}
            allowWholeSigungu
            onChange={(region) => update(region)}
          />
          <p className="field-hint">읍면동을 고르지 않으면 시군구 전체 자원입니다.</p>
        </FormRow>

        <FormRow label="운영 기간" required error={visible.period} notice={notices.period}>
          <div className="date-range-inputs">
            <input
              className="input form-date"
              type="date"
              aria-label="운영 시작일"
              value={form.periodStart}
              aria-invalid={Boolean(visible.period)}
              onChange={(event) => update({ periodStart: event.target.value })}
            />
            <span aria-hidden="true">~</span>
            <input
              className="input form-date"
              type="date"
              aria-label="운영 종료일"
              value={form.periodEnd}
              aria-invalid={Boolean(visible.period)}
              onChange={(event) => update({ periodEnd: event.target.value })}
            />
          </div>
        </FormRow>

        <FormRow label="이용자 부담금" required error={visible.fee}>
          <div className="inline-controls">
            <NumberInput
              label="이용자 부담금"
              value={form.fee}
              unit="원"
              invalid={Boolean(visible.fee)}
              onChange={(fee) => update({ fee })}
            />
            {feeOk && (
              <span className="age-preview">
                {formatFee(Number(form.fee.trim()))}
                {Number(form.fee.trim()) === 0 ? "로" : "으로"} 표시
              </span>
            )}
          </div>
          <p className="field-hint">무료면 0을 입력합니다. '월'·'1회'·'재료비' 같은 설명은 지원 내용에 적습니다.</p>
        </FormRow>

        <FormRow label="상태" required error={visible.status}>
          <div className="radio-group" role="radiogroup" aria-label="상태">
            {(["진행 중", "종료"] as ResourceStatus[]).map((status) => (
              <label key={status} className="checkbox">
                <input
                  type="radio"
                  name="status"
                  checked={form.status === status}
                  onChange={() => update({ status })}
                />
                {status}
              </label>
            ))}
          </div>
          <p className="field-hint">
            {detail?.autoEnded
              ? "운영 종료일이 지나 지금은 '종료'로 표시되고 있습니다. 종료일을 늦추면 다시 '진행 중'으로 표시됩니다."
              : "운영 종료일이 지나면 자동으로 '종료'로 표시됩니다."}
          </p>
        </FormRow>

        <FormRow label="담당자" required error={visible.manager}>
          <select
            className="input select form-short"
            aria-label="담당자"
            value={form.managerMemberId ?? ""}
            aria-invalid={Boolean(visible.manager)}
            onChange={(event) => update({ managerMemberId: event.target.value ? Number(event.target.value) : null })}
          >
            <option value="">담당자 선택</option>
            {options.map((member) => (
              <option key={member.memberId} value={member.memberId}>
                {[member.name, member.title].filter(Boolean).join(" ")}
                {member.memberId === myMemberId ? " (본인)" : ""}
              </option>
            ))}
          </select>
          {membersQuery.isPending && <p className="field-hint">담당자 목록을 불러오는 중입니다.</p>}
          {membersQuery.isError && (
            <p className="field-hint">담당자 목록을 불러오지 못했습니다. {errorMessage(membersQuery.error)}</p>
          )}
          <p className="field-hint">
            같은 기관 회원 중 한 명입니다. 다른 사람을 고르면 저장한 뒤 이 자원을 수정·삭제할 수 없습니다.
          </p>
        </FormRow>

        <FormRow label="정원" required error={visible.capacity}>
          <NumberInput
            label="정원"
            value={form.capacity}
            unit="명"
            invalid={Boolean(visible.capacity)}
            onChange={(capacity) => update({ capacity })}
          />
        </FormRow>

        <FormRow label="실제 참여자 수" error={visible.actualParticipants} notice={notices.actualParticipants}>
          <NumberInput
            label="실제 참여자 수"
            value={form.actualParticipants}
            unit="명"
            invalid={Boolean(visible.actualParticipants)}
            onChange={(actualParticipants) => update({ actualParticipants })}
          />
          <p className="field-hint">지금 참여 중인 인원입니다. 비워 둘 수 있습니다.</p>
        </FormRow>

        <FormRow label="신청 방법" error={visible.applyMethod}>
          <TextInput
            label="신청 방법"
            value={form.applyMethod}
            limit={RESOURCE_TEXT_LIMITS.applyMethod}
            wide
            invalid={Boolean(visible.applyMethod)}
            onChange={(applyMethod) => update({ applyMethod })}
          />
        </FormRow>

        <FormRow label="지원 내용" error={visible.supportContent}>
          <textarea
            className="input resource-textarea"
            aria-label="지원 내용"
            value={form.supportContent}
            aria-invalid={Boolean(visible.supportContent)}
            onChange={(event) => update({ supportContent: event.target.value })}
          />
          <p className="char-count">
            {form.supportContent.trim().length}/{RESOURCE_TEXT_LIMITS.supportContent}
          </p>
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

/** 항목 줄: 이름(필수 *) | 입력칸 + 오류·안내 */
function FormRow({
  label,
  required = false,
  error,
  notice,
  children,
}: {
  label: string
  required?: boolean
  error?: string
  notice?: string
  children: ReactNode
}) {
  return (
    <div className="form-row">
      <span className="form-label">
        {label}
        {required && <em className="required"> *</em>}
      </span>
      <div className="form-control">
        {children}
        <FieldError message={error} />
        {notice && <p className="field-notice">{notice}</p>}
      </div>
    </div>
  )
}

function TextInput({
  label,
  value,
  limit,
  wide = false,
  invalid,
  onChange,
}: {
  label: string
  value: string
  limit: number
  wide?: boolean
  invalid: boolean
  onChange: (value: string) => void
}) {
  return (
    <div className="inline-controls">
      <input
        className={`input ${wide ? "form-wide" : "form-short"}`}
        aria-label={label}
        value={value}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
      />
      <span className="char-count">
        {value.trim().length}/{limit}
      </span>
    </div>
  )
}

function NumberInput({
  label,
  value,
  unit,
  invalid,
  onChange,
}: {
  label: string
  value: string
  unit: string
  invalid: boolean
  onChange: (value: string) => void
}) {
  return (
    <div className="inline-controls number-input">
      <input
        className="input"
        inputMode="numeric"
        aria-label={label}
        value={value}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
      />
      <span className="capacity-unit">{unit}</span>
    </div>
  )
}
