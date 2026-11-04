import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useNavigate } from "react-router"
import { errorMessage, isApiError } from "@/api/errors"
import { myApi, myKeys } from "@/api/myApi"
import { FieldError } from "@/components/common/FieldError"
import { PATHS } from "@/routes/paths"
import { fieldErrorsOf } from "@/screens/case/caseErrors"
import {
  formOfMyInfo,
  TITLE_MAX,
  toMyInfoPatch,
  validateMyInfoForm,
  type MyInfoErrors,
  type MyInfoField,
  type MyInfoForm,
} from "@/screens/my/myForms"
import { MyLoadFailed, MyLoading } from "@/screens/my/MyStatusViews"
import { refreshProfile } from "@/session/sessionActions"
import { leaveGuard, useLeaveGuard } from "@/stores/leaveGuardStore"
import { showToast } from "@/stores/toastStore"

/** 서버 fieldErrors의 field → 입력칸 */
const MY_INFO_FIELDS: Record<string, MyInfoField> = { title: "title", phone: "phone" }

/**
 * 5.1.1 내 정보 조회(API-30) + 5.1.2 내 정보 수정(API-31).
 * '수정'을 누르면 직함·전화번호만 입력칸으로 바뀌고 '저장'·'취소'. 이름·이메일·소속기관·관할지역은 바꿀 수 없다.
 * 저장하면 바뀐 항목만 보내고, 메뉴 프로필(/auth/me)을 다시 받아 머리글·메뉴의 직함을 맞춘다
 */
export function MyInfoTab() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const infoQuery = useQuery({ queryKey: myKeys.info, queryFn: myApi.getMyInfo })
  const updateInfo = useMutation({ mutationFn: myApi.updateMyInfo })

  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<MyInfoForm>({ title: "", phone: "" })
  const [showErrors, setShowErrors] = useState(false)
  const [serverErrors, setServerErrors] = useState<MyInfoErrors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)

  const info = infoQuery.data ?? null
  const dirty = editing && info !== null && toMyInfoPatch(form, info) !== null
  useLeaveGuard(dirty)

  if (infoQuery.isPending) return <MyLoading text="내 정보를 불러오는 중입니다." />
  if (infoQuery.isError || !info) {
    return (
      <MyLoadFailed
        title="내 정보를 불러오지 못했습니다."
        message={errorMessage(infoQuery.error)}
        onRetry={() => void infoQuery.refetch()}
      />
    )
  }

  const errors = validateMyInfoForm(form)
  const visible: MyInfoErrors = showErrors ? { ...serverErrors, ...errors } : serverErrors

  const startEdit = () => {
    setForm(formOfMyInfo(info))
    setEditing(true)
    setShowErrors(false)
    setServerErrors({})
    setSubmitError(null)
  }

  const cancel = () => {
    setEditing(false)
    setShowErrors(false)
    setServerErrors({})
    setSubmitError(null)
  }

  const update = (patch: Partial<MyInfoForm>) => {
    setForm({ ...form, ...patch })
    setServerErrors({})
  }

  const save = async () => {
    if (updateInfo.isPending) return
    setSubmitError(null)
    setServerErrors({})
    if (Object.keys(errors).length > 0) {
      setShowErrors(true)
      return
    }
    const patch = toMyInfoPatch(form, info)
    // 바뀐 것이 없으면 보내지 않는다 (계약 minProperties 1)
    if (!patch) {
      cancel()
      return
    }
    let saved
    try {
      saved = await updateInfo.mutateAsync(patch)
    } catch (error) {
      if (isApiError(error) && error.code === "VALIDATION_ERROR") {
        const fields = fieldErrorsOf(error, MY_INFO_FIELDS)
        setServerErrors(fields)
        setSubmitError("입력값을 확인해 주세요.")
        return
      }
      setSubmitError(errorMessage(error))
      return
    }
    leaveGuard.release()
    queryClient.setQueryData(myKeys.info, saved)
    setEditing(false)
    setShowErrors(false)
    void refreshProfile()
    showToast("내 정보를 수정했습니다.")
  }

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
              <button
                type="button"
                className="btn btn-primary btn-small"
                disabled={updateInfo.isPending}
                onClick={() => void save()}
              >
                {updateInfo.isPending ? "저장 중" : "저장"}
              </button>
            </div>
          ) : (
            <button type="button" className="btn btn-outline btn-small" onClick={startEdit}>
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
                <>
                  <input
                    className="input"
                    aria-label="직함"
                    placeholder="예: 사회복지사"
                    value={form.title}
                    aria-invalid={Boolean(visible.title)}
                    onChange={(event) => update({ title: event.target.value })}
                  />
                  <FieldError message={visible.title} />
                </>
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
                    inputMode="tel"
                    placeholder="010-1234-5678"
                    value={form.phone}
                    aria-invalid={Boolean(visible.phone)}
                    onChange={(event) => update({ phone: event.target.value })}
                  />
                  <FieldError message={visible.phone} />
                </>
              ) : (
                (info.phone ?? "-")
              )}
            </dd>
          </div>
        </dl>
        {editing && (
          <p className="field-hint my-edit-hint">
            직함({TITLE_MAX}자까지)·전화번호만 바꿀 수 있습니다. 비워 두면 표시하지 않습니다.
          </p>
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
