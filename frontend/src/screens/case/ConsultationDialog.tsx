import { useEffect, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { FieldError } from "@/components/common/FieldError"
import { devCases } from "@/devtools/devCases"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { consultationApi, type ConsultationDetail } from "@/mock/api/consultationApi"
import {
  CONSULTATION_FILLS,
  exampleConsultationForm,
  formFromConsultation,
  sameConsultationForm,
  toConsultationInput,
  validateConsultationForm,
  type ConsultationForm,
} from "@/screens/case/consultationForm"
import { confirmDialog, useConfirmRequest } from "@/stores/confirmStore"
import { LEAVE_CONFIRM, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"
import type { ConsultationCategory } from "@/types/domain"
import { CATEGORY_ETC_MAX, CONSULTATION_CATEGORIES, formatCategory } from "@/utils/consultation"
import { todayString } from "@/utils/datetime"

export type ConsultationTarget = { mode: "view"; consultationId: number } | { mode: "new" }

type Phase = "loading" | "view" | "edit" | "new"

/**
 * 4.2.2 상담 창 (D3-B, D4-A): 하나의 창을 세 상태로 쓴다.
 * - 보기: 행을 누르면 열림(상담 내용 조회). 버튼 = 삭제, 수정
 * - 수정: '수정'을 누르면 창 안에서 입력칸으로 바뀜. 버튼 = 취소(보기로), 저장(수정 자리)
 * - 등록: '상담 등록'을 누르면 빈 입력 상태로 열림. 버튼 = 취소, 등록
 */
export function ConsultationDialog({
  caseId,
  caseName,
  myName,
  target,
  onClose,
  onChanged,
  onFailure,
}: {
  caseId: number
  caseName: string
  /** 등록할 때 기록자로 보여 줄 로그인 회원 이름 */
  myName: string
  target: ConsultationTarget
  onClose: () => void
  /** 등록·수정·삭제한 뒤: 사례자 정보와 상담 목록을 다시 조회 (D2-A) */
  onChanged: () => void
  /** API 실패 (권한 없음·사례자 없음·상담 없음 등). 창을 닫을지는 부르는 화면이 정한다 */
  onFailure: (message: string) => void
}) {
  const [phase, setPhase] = useState<Phase>(target.mode === "new" ? "new" : "loading")
  const [detail, setDetail] = useState<ConsultationDetail | null>(null)
  const [baseline, setBaseline] = useState<ConsultationForm>(exampleConsultationForm)
  const [form, setForm] = useState<ConsultationForm>(baseline)
  const [showErrors, setShowErrors] = useState(false)

  // 창을 열 때 상담 내용 조회 (한 번만)
  useEffect(() => {
    if (target.mode !== "view") return
    const result = consultationApi.getConsultation({ caseId, consultationId: target.consultationId })
    if (!result.ok) {
      onFailure(result.message)
      return
    }
    const loaded = formFromConsultation(result.data)
    setDetail(result.data)
    setBaseline(loaded)
    setForm(loaded)
    setPhase("view")
  }, [])

  const editing = phase === "edit" || phase === "new"
  const dirty = editing && !sameConsultationForm(form, baseline)
  useLeaveGuard(dirty)
  const errors = validateConsultationForm(form)
  const visible = showErrors ? errors : {}

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
    setPhase("edit")
  }

  const cancelEdit = async () => {
    if (dirty && !(await confirmDialog(LEAVE_CONFIRM))) return
    setForm(baseline)
    setShowErrors(false)
    setPhase("view")
  }

  const save = () => {
    if (Object.keys(errors).length > 0) {
      setShowErrors(true)
      return
    }
    const input = toConsultationInput(form)
    if (phase === "new") {
      const result = consultationApi.createConsultation({ caseId, ...input })
      if (!result.ok) {
        onFailure(result.message)
        return
      }
      showToast("상담 기록을 등록했습니다.")
      onClose()
      onChanged()
      return
    }
    if (!detail) return
    const result = consultationApi.updateConsultation({
      caseId,
      consultationId: detail.consultationId,
      ...input,
    })
    if (!result.ok) {
      onFailure(result.message)
      return
    }
    // 저장하면 창은 보기 상태로 남아 바뀐 내용을 보여 준다
    const updated: ConsultationDetail = { ...detail, ...input }
    const saved = formFromConsultation(updated)
    setDetail(updated)
    setBaseline(saved)
    setForm(saved)
    setShowErrors(false)
    setPhase("view")
    showToast("상담 기록을 수정했습니다.")
    onChanged()
  }

  const remove = async () => {
    if (!detail) return
    const ok = await confirmDialog({
      title: "상담 기록을 삭제할까요?",
      message: `${detail.consultedAt} '${detail.purpose}' 상담 기록을 삭제하면 되돌릴 수 없습니다.`,
      confirmLabel: "삭제",
      tone: "danger",
    })
    if (!ok) return
    const result = consultationApi.deleteConsultation({ caseId, consultationId: detail.consultationId })
    if (!result.ok) {
      onFailure(result.message)
      return
    }
    showToast("상담 기록을 삭제했습니다.")
    onClose()
    onChanged()
  }

  const update = (patch: Partial<ConsultationForm>) => setForm((prev) => ({ ...prev, ...patch }))

  useDevScenario(
    {
      screen: phase === "new" ? "상담 등록 창" : phase === "edit" ? "상담 수정 창" : "상담 기록 창",
      hint: editing
        ? "채우기 버튼은 입력칸만 바꿉니다. 저장·등록을 눌러 확인하세요."
        : "'수정'을 누르면 입력값 채우기 버튼이 나타납니다. '다른 담당자가 한 일'은 데이터만 바꾸니, 그다음 수정·삭제를 눌러 보세요.",
      actions: editing
        ? CONSULTATION_FILLS.map((fill) => ({ label: fill.label, run: () => update(fill.patch()) }))
        : [],
      groups: [
        {
          title: "다른 담당자가 한 일",
          actions: [
            ...(detail
              ? [{ label: "이 상담 기록을 삭제함", run: () => devCases.deleteConsultation(detail.consultationId) }]
              : []),
            { label: "이 사례자를 삭제함", run: () => devCases.deleteCase(caseId) },
            { label: "나를 담당자에서 뺌", run: () => devCases.removeMe(caseId) },
          ],
        },
      ],
    },
    [phase, detail?.consultationId],
  )

  const title = phase === "new" ? "상담 등록" : phase === "edit" ? "상담 기록 수정" : "상담 기록"
  const frame = document.querySelector(".prototype-frame") ?? document.body

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

        {phase === "loading" ? (
          <p className="consult-loading">불러오는 중</p>
        ) : (
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
                  <FieldError message={visible.categoryEtc} />
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
        )}

        <div className="dialog-actions">
          {phase === "view" && (
            <>
              <button type="button" className="btn btn-outline btn-outline-danger" onClick={() => void remove()}>
                삭제
              </button>
              <button type="button" className="btn btn-primary" onClick={startEdit}>
                수정
              </button>
            </>
          )}
          {phase === "edit" && (
            <>
              <button type="button" className="btn btn-outline" onClick={() => void cancelEdit()}>
                취소
              </button>
              <button type="button" className="btn btn-primary" onClick={save}>
                저장
              </button>
            </>
          )}
          {phase === "new" && (
            <>
              <button type="button" className="btn btn-outline" onClick={() => void close()}>
                취소
              </button>
              <button type="button" className="btn btn-primary" onClick={save}>
                등록
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
