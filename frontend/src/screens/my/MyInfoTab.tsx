import { useEffect, useState } from "react"
import { useNavigate } from "react-router"
import { FieldError } from "@/components/common/FieldError"
import { devAuth } from "@/devtools/devAuth"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { myApi, type MyInfo } from "@/mock/api/myApi"
import { PATHS } from "@/routes/paths"
import { validateMyInfoForm, type MyInfoForm } from "@/screens/my/myForms"
import { sessionStore } from "@/session/sessionStore"
import { leaveGuard, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"

const formOf = (info: MyInfo): MyInfoForm => ({ title: info.title ?? "", phone: info.phone ?? "" })

/**
 * 5.1.1 내 정보 조회 + 5.1.2 내 정보 수정 (M2-A).
 * '수정'을 누르면 직함·전화번호만 입력칸으로 바뀌고 '저장'·'취소'. 이름·이메일·소속기관·관할지역은 바꿀 수 없다
 */
export function MyInfoTab() {
  const navigate = useNavigate()
  const [info, setInfo] = useState<MyInfo | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<MyInfoForm>({ title: "", phone: "" })
  const [showErrors, setShowErrors] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    const result = myApi.getMyInfo()
    if (result.ok) setInfo(result.data)
    else setLoadError(result.message)
  }, [])

  const dirty = editing && info !== null && JSON.stringify(form) !== JSON.stringify(formOf(info))
  useLeaveGuard(dirty)
  const errors = showErrors ? validateMyInfoForm(form) : {}

  const startEdit = (next?: MyInfoForm) => {
    if (!info) return
    setForm(next ?? formOf(info))
    setEditing(true)
    setShowErrors(false)
    setSubmitError(null)
  }

  const cancel = () => {
    setEditing(false)
    setShowErrors(false)
    setSubmitError(null)
  }

  const save = () => {
    setShowErrors(true)
    if (Object.keys(validateMyInfoForm(form)).length > 0) return
    const result = myApi.updateMyInfo({ title: form.title.trim() || null, phone: form.phone.trim() || null })
    if (!result.ok) {
      setSubmitError(result.message)
      return
    }
    leaveGuard.release()
    setInfo(result.data)
    setEditing(false)
    setShowErrors(false)
    // 메뉴바의 직함도 바로 바꾼다 (응답 값으로)
    const session = sessionStore.getState()
    if (session.status === "authenticated") sessionStore.updateProfile({ ...session.profile, title: result.data.title })
    showToast("내 정보를 수정했습니다.")
  }

  useDevScenario(
    {
      screen: "마이페이지 · 내 정보",
      hint: "채우기 버튼은 수정 상태로 바꾼 뒤 입력칸을 채웁니다.",
      actions: [
        { label: "전화번호 형식 오류 채우기", run: () => startEdit({ title: info?.title ?? "", phone: "02-123-45" }) },
        { label: "직함·전화번호 비우기", run: () => startEdit({ title: "", phone: "" }) },
        { label: "임시 비밀번호로 로그인한 상태 만들기 (정하늘)", run: () => devAuth.enterTempLogin(navigate) },
      ],
    },
    [info],
  )

  if (loadError) return <p className="notice-bar">{loadError}</p>
  if (!info) return null

  return (
    <>
      <section className="detail-card my-info-card">
        <div className="card-head">
          <h2 className="card-title">내 정보</h2>
          {editing ? (
            <div className="heading-actions">
              <button type="button" className="btn btn-outline btn-small" onClick={cancel}>
                취소
              </button>
              <button type="button" className="btn btn-primary btn-small" onClick={save}>
                저장
              </button>
            </div>
          ) : (
            <button type="button" className="btn btn-outline btn-small" onClick={() => startEdit()}>
              수정
            </button>
          )}
        </div>
        <dl className="info-grid">
          <InfoItem label="이름" value={info.name} />
          <InfoItem label="이메일" value={info.email} />
          <InfoItem label="소속기관" value={info.orgName} />
          <InfoItem label="관할지역" value={info.jurisdictionName} />
          <div className={`info-item ${editing ? "is-editing" : ""}`}>
            <dt>직함</dt>
            <dd>
              {editing ? (
                <input
                  className="input"
                  aria-label="직함"
                  placeholder="예: 사회복지사"
                  value={form.title}
                  onChange={(event) => setForm({ ...form, title: event.target.value })}
                />
              ) : (
                (info.title ?? "-")
              )}
            </dd>
          </div>
          <div className={`info-item ${editing ? "is-editing" : ""}`}>
            <dt>전화번호(비상연락망)</dt>
            <dd>
              {editing ? (
                <>
                  <input
                    className="input"
                    aria-label="전화번호"
                    placeholder="010-1234-5678"
                    value={form.phone}
                    aria-invalid={Boolean(errors.phone)}
                    onChange={(event) => setForm({ ...form, phone: event.target.value })}
                  />
                  <FieldError message={errors.phone} />
                </>
              ) : (
                (info.phone ?? "-")
              )}
            </dd>
          </div>
        </dl>
        {editing && (
          <p className="field-hint my-edit-hint">직함·전화번호만 바꿀 수 있습니다. 비워 두면 표시하지 않습니다.</p>
        )}
        <FieldError message={submitError} />
      </section>

      <section className="detail-card my-account-card">
        <h2 className="card-title">계정 관리</h2>
        <div className="my-account-row">
          <div>
            <strong>비밀번호 변경</strong>
            <p>현재 비밀번호를 확인한 뒤 새 비밀번호로 바꿉니다.</p>
          </div>
          <button type="button" className="btn btn-outline" onClick={() => navigate(PATHS.myPassword)}>
            비밀번호 변경
          </button>
        </div>
        <div className="my-account-row">
          <div>
            <strong>회원 탈퇴</strong>
            <p>담당 사례자를 넘긴 뒤 탈퇴합니다. 탈퇴하면 되돌릴 수 없습니다.</p>
          </div>
          <button type="button" className="btn btn-outline btn-outline-danger" onClick={() => navigate(PATHS.myWithdraw)}>
            회원 탈퇴
          </button>
        </div>
      </section>
    </>
  )
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="info-item">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}
