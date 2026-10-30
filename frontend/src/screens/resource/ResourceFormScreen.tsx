import { useEffect, useState, type FormEvent, type ReactNode } from "react"
import { useLocation, useNavigate, useParams } from "react-router"
import { EmptyState } from "@/components/common/EmptyState"
import { FieldError } from "@/components/common/FieldError"
import { devResources } from "@/devtools/devResources"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { memberApi } from "@/mock/api/memberApi"
import {
  DOCUMENT_MAX_BYTES,
  RESOURCE_EDIT_MANAGER_ONLY_MESSAGE,
  RESOURCE_NOT_FOUND_MESSAGE,
  RESOURCE_TEXT_LIMITS,
  resourceApi,
} from "@/mock/api/resourceApi"
import { PATHS } from "@/routes/paths"
import { RegionSelects } from "@/screens/case/RegionSelects"
import { formatFee } from "@/screens/resource/resourceFormat"
import {
  applyExtract,
  DOCUMENT_EXAMPLES,
  exampleResourceForm,
  fieldOf,
  formFromDetail,
  formNotices,
  hasFillableInput,
  RESOURCE_FILLS,
  sameResourceForm,
  toResourceInput,
  validateResourceForm,
  type ResourceForm,
  type ResourceFormField,
} from "@/screens/resource/resourceForm"
import { readResourceNavState } from "@/screens/resource/resourceNav"
import { useSession } from "@/session/sessionStore"
import { confirmDialog } from "@/stores/confirmStore"
import { leaveGuard, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"
import type { ResourceStatus, SupportAgeGroup, SupportGender } from "@/types/domain"
import { AGE_GROUPS } from "@/utils/age"

type Member = { memberId: number; name: string; title: string | null }
/** 올릴 파일 (실제 파일 또는 개발용 예시 파일의 이름·크기·형식) */
type PickedFile = { name: string; size: number; type: string }

const MEGABYTE = 1024 * 1024

/**
 * 3.3 복지자원 등록(/resources/new)·수정(/resources/:resourceId/edit) — 같은 등록 양식 (3.3.1)
 * - 등록: 3.3.3 수동 입력 + 3.3.2 PDF 자동 입력(위쪽 칸, E1-A). 등록 후 상세로
 * - 수정(3.2.2): 담당자만. 저장 후 상세로
 * - 담당자를 다른 사람으로 고르면 저장 전 확인 (E6-A), 바뀐 내용이 있으면 화면을 떠날 때 경고 (E5-A)
 */
export function ResourceFormScreen({ mode }: { mode: "new" | "edit" }) {
  const params = useParams()
  const resourceId = mode === "edit" ? Number(params.resourceId) : null
  const navigate = useNavigate()
  const location = useLocation()
  const nav = readResourceNavState(location.state)
  const session = useSession()
  const profile = session.status === "authenticated" ? session.profile : null
  const myMemberId = profile?.memberId ?? 0
  const featureId = mode === "new" ? "3.3.1" : "3.2.2"

  const [members, setMembers] = useState<Member[]>([])
  const [baseline, setBaseline] = useState<ResourceForm | null>(() =>
    mode === "new" && profile ? exampleResourceForm(profile) : null,
  )
  const [form, setForm] = useState<ResourceForm | null>(baseline)
  const [titleName, setTitleName] = useState("")
  const [showErrors, setShowErrors] = useState(false)
  const [accessError, setAccessError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  // PDF 자동 입력 (3.3.2)
  const [file, setFile] = useState<PickedFile | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [extractMessage, setExtractMessage] = useState<string | null>(null)
  const [aiFields, setAiFields] = useState<Set<ResourceFormField>>(new Set())
  const [missingFields, setMissingFields] = useState<Set<ResourceFormField>>(new Set())

  // 수정: 상세 조회(수정 가능 여부 확인) → 담당자 후보. 등록: 담당자 후보만
  useEffect(() => {
    if (resourceId !== null) {
      const result = resourceApi.getResource({ resourceId })
      if (!result.ok) {
        fail(result.message)
        return
      }
      if (!result.data.editable) {
        setAccessError(RESOURCE_EDIT_MANAGER_ONLY_MESSAGE)
        return
      }
      const loaded = formFromDetail(result.data)
      setTitleName(result.data.resourceName)
      setBaseline(loaded)
      setForm(loaded)
    }
    const membersResult = memberApi.getOrgMembers(featureId)
    if (membersResult.ok) setMembers(membersResult.data)
  }, [])

  const dirty = !accessError && form !== null && baseline !== null && !sameResourceForm(form, baseline)
  useLeaveGuard(dirty)

  /** 찾을 수 없음·권한 없음이면 안내 화면으로, 그 밖의 실패는 버튼 위에 표시 */
  function fail(message: string) {
    if (message === RESOURCE_NOT_FOUND_MESSAGE || message === RESOURCE_EDIT_MANAGER_ONLY_MESSAGE) setAccessError(message)
    else setSubmitError(message)
  }

  /** 직접 고친 항목은 'AI 입력'·'찾지 못함' 표시를 지운다 */
  const update = (patch: Partial<ResourceForm>) => {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev))
    const touched = new Set((Object.keys(patch) as (keyof ResourceForm)[]).map(fieldOf))
    const without = (set: Set<ResourceFormField>) => new Set([...set].filter((field) => !touched.has(field)))
    setAiFields(without)
    setMissingFields(without)
  }

  const pickFile = (picked: PickedFile | null) => {
    setFile(picked)
    setExtractMessage(null)
    if (!picked) {
      setFileError(null)
      return
    }
    const isPdf = picked.type === "application/pdf" || picked.name.toLowerCase().endsWith(".pdf")
    if (!isPdf) setFileError("PDF 파일만 올릴 수 있습니다.")
    else if (picked.size > DOCUMENT_MAX_BYTES) setFileError("20MB 이하 파일만 올릴 수 있습니다.")
    else setFileError(null)
  }

  useDevScenario(
    {
      screen: mode === "new" ? "복지자원 등록" : "복지자원 수정",
      hint:
        mode === "new"
          ? "채우기 버튼은 입력칸만 바꿉니다. 'PDF:' 버튼은 파일을 고른 것처럼 만들고, '문서로 자동 입력'을 눌러 결과를 확인하세요. 입력을 바꾼 뒤 화면을 떠나면 '저장하지 않은 내용' 경고가 뜹니다."
          : "'다른 사람이 한 일'은 데이터만 바꿉니다. 그다음 '저장'을 눌러 서버 응답을 확인하세요.",
      actions: [
        ...RESOURCE_FILLS.map((fill) => ({
          label: fill.label,
          run: () => setForm((prev) => (prev ? { ...prev, ...fill.patch(prev) } : prev)),
        })),
        {
          label: "다른 담당자 고르기",
          run: () => {
            const other = members.find((item) => item.memberId !== myMemberId)
            if (other) update({ managerMemberId: other.memberId })
          },
        },
      ],
      groups: [
        ...(mode === "new"
          ? [{ title: "PDF 자동 입력", actions: DOCUMENT_EXAMPLES.map((example) => ({ label: example.label, run: () => pickFile(example) })) }]
          : []),
        ...(resourceId !== null
          ? [
              {
                title: "다른 사람이 한 일",
                actions: [
                  { label: "이 자원을 삭제함", run: () => devResources.deleteResource(resourceId) },
                  { label: "담당자가 다른 사람으로 바뀜", run: () => devResources.changeManager(resourceId) },
                ],
              },
            ]
          : []),
      ],
      infos: [{ label: "저장하지 않은 내용", value: dirty ? "있음" : "없음" }],
    },
    [mode, resourceId, dirty, members],
  )

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

  if (accessError) {
    return (
      <section className="screen resource-form">
        <div className="resource-not-found">
          <EmptyState
            title={accessError}
            description={
              accessError === RESOURCE_EDIT_MANAGER_ONLY_MESSAGE
                ? "자원의 담당자만 수정할 수 있습니다."
                : "삭제되었거나 주소가 잘못되었습니다."
            }
          />
          {accessError === RESOURCE_EDIT_MANAGER_ONLY_MESSAGE && resourceId !== null ? (
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => navigate(PATHS.resourceDetail(resourceId), { replace: true })}
            >
              상세로
            </button>
          ) : (
            <button type="button" className="btn btn-outline" onClick={() => navigate(PATHS.resources, { replace: true })}>
              목록으로
            </button>
          )}
        </div>
      </section>
    )
  }

  if (!form) return null

  const errors = validateResourceForm(form)
  const visible = showErrors ? errors : {}
  const notices = formNotices(form)

  const runExtract = async () => {
    if (!file || fileError) return
    if (hasFillableInput(form)) {
      const ok = await confirmDialog({
        title: "문서 내용으로 바꿀까요?",
        message: "입력한 내용이 문서 내용으로 바뀝니다. 담당자·상태는 그대로 둡니다.",
        confirmLabel: "바꾸기",
      })
      if (!ok) return
    }
    const result = resourceApi.extractFromDocument({ fileName: file.name, fileSize: file.size })
    if (!result.ok) {
      setExtractMessage(null)
      setFileError(result.message)
      return
    }
    const applied = applyExtract(form, result.data.extracted, result.data.missingFields)
    setForm(applied.form)
    setAiFields(new Set(applied.filled))
    setMissingFields(new Set(applied.missing))
    setShowErrors(false)
    setExtractMessage(
      applied.missing.length > 0
        ? `문서에서 ${applied.filled.length}개 항목을 채웠습니다. 찾지 못한 항목 ${applied.missing.length}개는 직접 입력하세요.`
        : `문서에서 ${applied.filled.length}개 항목을 채웠습니다. 내용을 확인한 뒤 등록하세요.`,
    )
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitError(null)
    if (Object.keys(errors).length > 0) {
      setShowErrors(true)
      return
    }
    const input = toResourceInput(form)
    const handingOver = input.managerMemberId !== myMemberId
    if (handingOver) {
      const manager = members.find((item) => item.memberId === input.managerMemberId)
      const ok = await confirmDialog({
        title: `담당자를 ${manager?.name ?? "다른 사람"}(으)로 지정할까요?`,
        message: "저장하면 이 자원을 더 이상 수정·삭제할 수 없습니다.",
        confirmLabel: mode === "new" ? "등록" : "저장",
      })
      if (!ok) return
    }

    if (resourceId === null) {
      const result = resourceApi.createResource(input)
      if (!result.ok) {
        fail(result.message)
        return
      }
      leaveGuard.release()
      showToast("복지자원을 등록했습니다.")
      // 등록 화면은 뒤로 가기 기록에서 빼고 상세로 (뒤로 가면 목록)
      navigate(PATHS.resourceDetail(result.data.resourceId), { replace: true, state: { listSearch: nav.listSearch } })
      return
    }

    const result = resourceApi.updateResource({ resourceId, ...input })
    if (!result.ok) {
      fail(result.message)
      return
    }
    leaveGuard.release()
    showToast("복지자원을 수정했습니다.")
    if (nav.fromDetail) navigate(-1)
    else navigate(PATHS.resourceDetail(resourceId), { replace: true, state: { listSearch: nav.listSearch } })
  }

  const toggleAge = (age: SupportAgeGroup, checked: boolean) => {
    if (age === "무관") {
      update({ supportAgeGroups: checked ? ["무관"] : [] })
      return
    }
    const others = form.supportAgeGroups.filter((item) => item !== "무관" && item !== age)
    const next = checked ? [...others, age] : others
    update({ supportAgeGroups: AGE_GROUPS.filter((item) => next.includes(item)) })
  }

  const row = (field: ResourceFormField) => ({
    ai: aiFields.has(field),
    missing: missingFields.has(field),
    error: visible[field],
  })
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
            {mode === "new" ? "새 복지자원의 정보를 입력합니다." : `'${titleName}'의 정보를 수정합니다.`}{" "}
            <em className="required">*</em> 표시는 필수 항목입니다.
          </p>
        </div>
      </div>

      {mode === "new" && (
        <section className="pdf-import" aria-label="PDF로 자동 입력">
          <div className="pdf-import-head">
            <strong>
              <span className="sparkle" aria-hidden="true">
                ✦
              </span>{" "}
              PDF로 자동 입력
            </strong>
            <span className="field-hint-inline">
              안내문 PDF를 올리면 AI가 아래 양식을 채웁니다. PDF 1개, 20MB까지
            </span>
          </div>
          <div className="pdf-import-row">
            <label className="btn btn-outline pdf-pick">
              파일 선택
              <input
                type="file"
                accept=".pdf,application/pdf"
                aria-label="PDF 파일 선택"
                hidden
                onChange={(event) => {
                  const picked = event.target.files?.[0]
                  pickFile(picked ? { name: picked.name, size: picked.size, type: picked.type } : null)
                  event.target.value = ""
                }}
              />
            </label>
            <span className={`pdf-file-name ${file ? "" : "is-empty"}`}>
              {file ? `${file.name} (${(file.size / MEGABYTE).toFixed(1)}MB)` : "선택한 파일 없음"}
            </span>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!file || Boolean(fileError)}
              onClick={() => void runExtract()}
            >
              문서로 자동 입력
            </button>
          </div>
          <FieldError message={fileError} />
          {extractMessage && <p className="field-notice">{extractMessage}</p>}
          <p className="field-hint">올린 문서는 내용을 뽑아낸 뒤 바로 삭제되며 저장하지 않습니다.</p>
        </section>
      )}

      <form className="detail-card form-card" onSubmit={(event) => void submit(event)} noValidate>
        <FormRow label="자원명" required {...row("resourceName")}>
          <TextInput
            label="자원명"
            value={form.resourceName}
            limit={RESOURCE_TEXT_LIMITS.resourceName}
            invalid={Boolean(visible.resourceName)}
            onChange={(resourceName) => update({ resourceName })}
          />
        </FormRow>

        <FormRow label="수행·담당 기관" required {...row("operatingOrgName")}>
          <TextInput
            label="수행·담당 기관"
            value={form.operatingOrgName}
            limit={RESOURCE_TEXT_LIMITS.operatingOrgName}
            invalid={Boolean(visible.operatingOrgName)}
            onChange={(operatingOrgName) => update({ operatingOrgName })}
          />
          <p className="field-hint">구청·외부 기관이 수행하는 자원이면 그 기관명을 적습니다.</p>
        </FormRow>

        <FormRow label="지원 대상" required {...row("target")}>
          <TextInput
            label="지원 대상"
            value={form.target}
            limit={RESOURCE_TEXT_LIMITS.target}
            wide
            invalid={Boolean(visible.target)}
            onChange={(target) => update({ target })}
          />
        </FormRow>

        <FormRow label="지원 연령" required {...row("supportAgeGroups")}>
          <div className="radio-group" role="group" aria-label="지원 연령">
            {[...AGE_GROUPS, "무관" as const].map((age) => (
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

        <FormRow label="지원 성별" required {...row("supportGender")}>
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

        <FormRow label="지역" required {...row("region")}>
          <RegionSelects
            featureId={featureId}
            value={{ sidoCode: form.sidoCode, sigunguCode: form.sigunguCode, dongCode: form.dongCode }}
            invalid={Boolean(visible.region)}
            allowWholeSigungu
            onChange={(region) => update(region)}
          />
          <p className="field-hint">읍면동을 고르지 않으면 시군구 전체 자원입니다.</p>
        </FormRow>

        <FormRow label="운영 기간" required {...row("period")} notice={notices.period}>
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

        <FormRow label="이용자 부담금" required {...row("fee")}>
          <div className="inline-controls">
            <NumberInput
              label="이용자 부담금"
              value={form.fee}
              unit="원"
              invalid={Boolean(visible.fee)}
              onChange={(fee) => update({ fee })}
            />
            {feeOk && <span className="age-preview">{formatFee(Number(form.fee.trim()))}로 표시</span>}
          </div>
          <p className="field-hint">무료면 0을 입력합니다. '월'·'1회'·'재료비' 같은 설명은 지원 내용에 적습니다.</p>
        </FormRow>

        <FormRow label="상태" required {...row("status")}>
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
          <p className="field-hint">운영 종료일이 지나면 자동으로 '종료'로 표시됩니다.</p>
        </FormRow>

        <FormRow label="담당자" required {...row("manager")}>
          <select
            className="input select form-short"
            aria-label="담당자"
            value={form.managerMemberId ?? ""}
            aria-invalid={Boolean(visible.manager)}
            onChange={(event) => update({ managerMemberId: event.target.value ? Number(event.target.value) : null })}
          >
            <option value="">담당자 선택</option>
            {members.map((member) => (
              <option key={member.memberId} value={member.memberId}>
                {[member.name, member.title].filter(Boolean).join(" ")}
                {member.memberId === myMemberId ? " (본인)" : ""}
              </option>
            ))}
          </select>
          <p className="field-hint">같은 기관 회원 중 한 명입니다. 다른 사람을 고르면 저장한 뒤 이 자원을 수정·삭제할 수 없습니다.</p>
        </FormRow>

        <FormRow label="정원" required {...row("capacity")}>
          <NumberInput
            label="정원"
            value={form.capacity}
            unit="명"
            invalid={Boolean(visible.capacity)}
            onChange={(capacity) => update({ capacity })}
          />
        </FormRow>

        <FormRow label="실제 참여자 수" {...row("actualParticipants")} notice={notices.actualParticipants}>
          <NumberInput
            label="실제 참여자 수"
            value={form.actualParticipants}
            unit="명"
            invalid={Boolean(visible.actualParticipants)}
            onChange={(actualParticipants) => update({ actualParticipants })}
          />
          <p className="field-hint">지금 참여 중인 인원입니다. 비워 둘 수 있습니다.</p>
        </FormRow>

        <FormRow label="신청 방법" {...row("applyMethod")}>
          <TextInput
            label="신청 방법"
            value={form.applyMethod}
            limit={RESOURCE_TEXT_LIMITS.applyMethod}
            wide
            invalid={Boolean(visible.applyMethod)}
            onChange={(applyMethod) => update({ applyMethod })}
          />
        </FormRow>

        <FormRow label="지원 내용" {...row("supportContent")}>
          <textarea
            className="input consult-textarea"
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
            <button type="submit" className="btn btn-primary">
              {mode === "new" ? "등록" : "저장"}
            </button>
          </div>
        </div>
      </form>
    </section>
  )
}

/** 항목 줄: 이름(필수 *, 'AI 입력' 표시) | 입력칸 + 오류·찾지 못함·안내 */
function FormRow({
  label,
  required = false,
  ai = false,
  missing = false,
  error,
  notice,
  children,
}: {
  label: string
  required?: boolean
  ai?: boolean
  missing?: boolean
  error?: string
  notice?: string
  children: ReactNode
}) {
  return (
    <div className={`form-row ${ai ? "is-ai" : ""}`}>
      <span className="form-label">
        {label}
        {required && <em className="required"> *</em>}
        {ai && <span className="ai-badge">AI 입력</span>}
      </span>
      <div className="form-control">
        {children}
        <FieldError message={error} />
        {missing && !error && <p className="field-missing">문서에서 찾지 못했습니다. 직접 입력하세요.</p>}
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
