import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { caseApi, caseKeys, type ConsultationCategory, type ConsultationDetail, type ConsultationInput } from "@/api/caseApi"
import { errorMessage, isApiError } from "@/api/errors"
import { FieldError } from "@/components/common/FieldError"
import { caseAccessErrorOf, CASE_MESSAGES, fieldErrorsOf, type CaseAccessError } from "@/screens/case/caseErrors"
import {
  CONSULTATION_FORM_FIELDS,
  emptyConsultationForm,
  formFromConsultation,
  sameConsultationForm,
  toConsultationInput,
  validateConsultationForm,
  type ConsultationForm,
  type ConsultationFormErrors,
} from "@/screens/case/consultationForm"
import { confirmDialog, useConfirmRequest } from "@/stores/confirmStore"
import { LEAVE_CONFIRM, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"
import { CATEGORY_ETC_MAX, CONSULTATION_CATEGORIES, CONTENT_MAX, formatCategory, PURPOSE_MAX } from "@/utils/consultation"
import { todayString } from "@/utils/datetime"

export type ConsultationTarget = { mode: "view"; consultationId: number } | { mode: "new" }

type Phase = "view" | "edit" | "new"

/**
 * 4.2.2 상담 창 (D3-B, D4-A): 하나의 창을 세 상태로 쓴다.
 * - 보기: 행을 누르면 열림(API-26). 버튼 = 삭제(API-29), 수정
 * - 수정: '수정'을 누르면 창 안에서 입력칸으로 바뀜. 버튼 = 취소(보기로), 저장(API-28)
 * - 등록: '상담 등록'을 누르면 빈 입력 상태로 열림. 버튼 = 취소, 등록(API-27)
 * 등록·수정·삭제한 뒤 사례자 정보(최근 기록일)와 상담 목록을 다시 받는다.
 */
export function ConsultationDialog({
  caseId,
  caseName,
  myName,
  target,
  onClose,
  onAccessLost,
}: {
  caseId: number
  caseName: string
  /** 등록할 때 기록자로 보여 줄 로그인 회원 이름 */
  myName: string
  target: ConsultationTarget
  onClose: () => void
  /** 사례자를 더 볼 수 없게 됨 (담당자에서 빠짐·사례자 삭제). 부르는 화면이 안내 화면으로 바꾼다 */
  onAccessLost: (error: CaseAccessError) => void
}) {
  const queryClient = useQueryClient()
  const consultationId = target.mode === "view" ? target.consultationId : null
  const [phase, setPhase] = useState<Phase>(target.mode === "new" ? "new" : "view")
  const [baseline, setBaseline] = useState<ConsultationForm | null>(() =>
    target.mode === "new" ? emptyConsultationForm() : null,
  )
  const [form, setForm] = useState<ConsultationForm | null>(baseline)
  const [showErrors, setShowErrors] = useState(false)
  const [serverErrors, setServerErrors] = useState<ConsultationFormErrors>({})

  // 창을 열 때마다 서버의 최신 내용을 받는다 (다른 담당자가 바꿨을 수 있다)
  const detailQuery = useQuery({
    queryKey: caseKeys.consultation(caseId, consultationId ?? 0),
    queryFn: () => caseApi.getConsultation(caseId, consultationId ?? 0),
    enabled: consultationId !== null,
    staleTime: 0,
  })
  const detail = detailQuery.data ?? null

  /** 사례자 정보(최근 기록일)와 상담 목록을 다시 받는다 */
  const refreshCase = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: caseKeys.detail(caseId), exact: true }),
      queryClient.invalidateQueries({ queryKey: caseKeys.consultations(caseId), exact: true }),
    ])

  /**
   * API 실패: 사례자를 볼 수 없게 됐으면 부르는 화면에 알리고, 상담 기록이 없어졌으면 창을 닫고 목록을 다시 받는다.
   * 입력값 오류는 창 안에 표시하고 입력값을 그대로 둔다
   */
  const fail = (error: unknown, kind: "load" | "create" | "change") => {
    const access = caseAccessErrorOf(error)
    if (access === "FORBIDDEN" || (access === "NOT_FOUND" && kind === "create")) {
      onAccessLost(access)
      return
    }
    if (access === "NOT_FOUND") {
      // 상담 API의 404는 상담이 없어졌거나 사례자가 없어진 경우다. 사례자가 없어졌으면 다시 받을 때 안내 화면이 뜬다
      showToast(CASE_MESSAGES.consultationNotFound, "error")
      onClose()
      void refreshCase()
      return
    }
    if (isApiError(error) && error.code === "VALIDATION_ERROR") {
      setServerErrors(fieldErrorsOf(error, CONSULTATION_FORM_FIELDS))
      showToast(CASE_MESSAGES.validation, "error")
      return
    }
    if (kind !== "load") showToast(errorMessage(error), "error")
  }

  // 보기: 처음 받았을 때 입력칸의 처음 값을 정한다
  useEffect(() => {
    if (!detail || baseline !== null) return
    const loaded = formFromConsultation(detail)
    setBaseline(loaded)
    setForm(loaded)
  }, [detail, baseline])

  // 불러오기 실패 (권한 없음·없어짐은 창을 닫는다. 그 밖은 창 안에서 다시 시도)
  const loadError = detailQuery.error
  useEffect(() => {
    // fail은 렌더마다 새로 만들어지지만, 오류가 바뀔 때만 한 번 처리한다
    if (loadError) fail(loadError, "load")
  }, [loadError])

  const createMutation = useMutation({
    mutationFn: (input: ConsultationInput) => caseApi.createConsultation(caseId, input),
  })
  const updateMutation = useMutation({
    mutationFn: (input: ConsultationInput) => caseApi.updateConsultation(caseId, consultationId ?? 0, input),
  })
  const deleteMutation = useMutation({ mutationFn: () => caseApi.deleteConsultation(caseId, consultationId ?? 0) })
  const busy = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  const editing = phase === "edit" || phase === "new"
  const dirty = editing && form !== null && baseline !== null && !sameConsultationForm(form, baseline)
  useLeaveGuard(dirty)
  const errors = form ? validateConsultationForm(form) : {}
  const visible: ConsultationFormErrors = showErrors ? { ...serverErrors, ...errors } : serverErrors

  const close = async () => {
    if (dirty && !(await confirmDialog(LEAVE_CONFIRM))) return
    onClose()
  }

  // Esc로 닫기 (확인 창이 떠 있을 때는 확인 창만 닫힌다)
  const confirmOpen = useConfirmRequest() !== null
  const latest = useRef({ close, confirmOpen })
  latest.current = { close, confirmOpen }
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !latest.current.confirmOpen) void latest.current.close()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  const startEdit = () => {
    setShowErrors(false)
    setServerErrors({})
    setPhase("edit")
  }

  const cancelEdit = async () => {
    if (dirty && !(await confirmDialog(LEAVE_CONFIRM))) return
    setForm(baseline)
    setShowErrors(false)
    setServerErrors({})
    setPhase("view")
  }

  const save = async () => {
    if (!form || busy) return
    setServerErrors({})
    if (Object.keys(errors).length > 0) {
      setShowErrors(true)
      return
    }
    const input = toConsultationInput(form)
    if (phase === "new") {
      try {
        await createMutation.mutateAsync(input)
      } catch (error) {
        fail(error, "create")
        return
      }
      showToast("상담 기록을 등록했습니다.")
      onClose()
      void refreshCase()
      return
    }
    if (!detail) return
    try {
      await updateMutation.mutateAsync(input)
    } catch (error) {
      fail(error, "change")
      return
    }
    // 저장하면 창은 보기 상태로 남아 바뀐 내용을 보여 준다 (기록자는 바뀌지 않는다)
    const updated: ConsultationDetail = { ...detail, ...input, categoryEtc: input.categoryEtc ?? null }
    queryClient.setQueryData(caseKeys.consultation(caseId, detail.consultationId), updated)
    const savedForm = formFromConsultation(updated)
    setBaseline(savedForm)
    setForm(savedForm)
    setShowErrors(false)
    setPhase("view")
    showToast("상담 기록을 수정했습니다.")
    void refreshCase()
  }

  const remove = async () => {
    if (!detail || busy) return
    const ok = await confirmDialog({
      title: "상담 기록을 삭제할까요?",
      message: `${detail.consultedAt} '${detail.purpose}' 상담 기록을 삭제하면 되돌릴 수 없습니다.`,
      confirmLabel: "삭제",
      tone: "danger",
    })
    if (!ok) return
    try {
      await deleteMutation.mutateAsync()
    } catch (error) {
      fail(error, "change")
      return
    }
    showToast("상담 기록을 삭제했습니다.")
    onClose()
    void refreshCase()
  }

  const update = (patch: Partial<ConsultationForm>) => {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev))
    setServerErrors({})
  }

  const title = phase === "new" ? "상담 등록" : phase === "edit" ? "상담 기록 수정" : "상담 기록"
  const frame = document.querySelector(".app-frame") ?? document.body

  const body = () => {
    if (!form) {
      if (detailQuery.isError) {
        return (
          <div className="consult-loading" role="alert">
            <p>{errorMessage(detailQuery.error)}</p>
            <button type="button" className="btn btn-outline btn-small" onClick={() => void detailQuery.refetch()}>
              다시 시도
            </button>
          </div>
        )
      }
      return <p className="consult-loading">불러오는 중</p>
    }
    return (
      <div className="consult-body">
        <Row label="상담 일자" required={editing}>
          {editing ? (
            <>
              <input
                className="input consult-date"
                type="date"
                aria-label="상담 일자"
                max={todayString()}
                value={form.consultedAt}
                aria-invalid={Boolean(visible.consultedAt)}
                onChange={(event) => update({ consultedAt: event.target.value })}
              />
              <FieldError message={visible.consultedAt} />
            </>
          ) : (
            detail?.consultedAt
          )}
        </Row>
        <Row label="상담 분류" required={editing}>
          {editing ? (
            <>
              <div className="consult-category">
                <select
                  className="input select"
                  aria-label="상담 분류"
                  value={form.category}
                  onChange={(event) => update({ category: event.target.value as ConsultationCategory })}
                >
                  {CONSULTATION_CATEGORIES.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
                {form.category === "기타" && (
                  <input
                    className="input"
                    aria-label="기타 분류 내용"
                    placeholder={`기타 분류 내용 (${CATEGORY_ETC_MAX}자 이내)`}
                    maxLength={CATEGORY_ETC_MAX}
                    value={form.categoryEtc}
                    aria-invalid={Boolean(visible.categoryEtc)}
                    onChange={(event) => update({ categoryEtc: event.target.value })}
                  />
                )}
              </div>
              <FieldError message={visible.categoryEtc ?? visible.category} />
            </>
          ) : (
            detail && formatCategory(detail.category, detail.categoryEtc)
          )}
        </Row>
        <Row label="상담 목적" required={editing}>
          {editing ? (
            <>
              <input
                className="input"
                aria-label="상담 목적"
                placeholder="상담 내용의 제목"
                maxLength={PURPOSE_MAX}
                value={form.purpose}
                aria-invalid={Boolean(visible.purpose)}
                onChange={(event) => update({ purpose: event.target.value })}
              />
              <FieldError message={visible.purpose} />
            </>
          ) : (
            detail?.purpose
          )}
        </Row>
        <Row label="상담 내용" required={editing}>
          {editing ? (
            <>
              <textarea
                className="input consult-textarea"
                aria-label="상담 내용"
                maxLength={CONTENT_MAX}
                value={form.content}
                aria-invalid={Boolean(visible.content)}
                onChange={(event) => update({ content: event.target.value })}
              />
              <FieldError message={visible.content} />
            </>
          ) : (
            <p className="consult-content">{detail?.content}</p>
          )}
        </Row>
        <Row label="기록자">
          {phase === "new" ? (
            <span>
              {myName} <span className="field-hint-inline">(등록하면 자동으로 지정)</span>
            </span>
          ) : (
            <span>
              {detail?.recorderName}
              {phase === "edit" && <span className="field-hint-inline"> (바꿀 수 없음)</span>}
            </span>
          )}
        </Row>
      </div>
    )
  }

  return createPortal(
    <div className="dialog-backdrop consult-backdrop" onClick={() => void close()}>
      <div
        className="dialog consult-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="consult-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="consult-head">
          <div>
            <h2 id="consult-title">{title}</h2>
            <span className="consult-sub">{caseName} 님</span>
          </div>
          <button type="button" className="consult-close" aria-label="닫기" onClick={() => void close()}>
            ×
          </button>
        </div>

        {body()}

        <div className="dialog-actions">
          {phase === "view" && detail && (
            <>
              <button
                type="button"
                className="btn btn-outline btn-outline-danger"
                disabled={busy}
                onClick={() => void remove()}
              >
                삭제
              </button>
              <button type="button" className="btn btn-primary" disabled={busy || !form} onClick={startEdit}>
                수정
              </button>
            </>
          )}
          {phase === "edit" && (
            <>
              <button type="button" className="btn btn-outline" disabled={busy} onClick={() => void cancelEdit()}>
                취소
              </button>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void save()}>
                {busy ? "저장 중" : "저장"}
              </button>
            </>
          )}
          {phase === "new" && (
            <>
              <button type="button" className="btn btn-outline" disabled={busy} onClick={() => void close()}>
                취소
              </button>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void save()}>
                {busy ? "등록 중" : "등록"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>,
    frame,
  )
}

function Row({ label, required = false, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <div className="consult-row">
      <span className="consult-label">
        {label}
        {required && <em className="required"> *</em>}
      </span>
      <div className="consult-value">{children}</div>
    </div>
  )
}
