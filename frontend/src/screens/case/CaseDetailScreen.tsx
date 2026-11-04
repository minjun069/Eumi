import "@/styles/list.css"
import "@/styles/detail.css"
import "@/styles/case.css"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router"
import { caseApi, caseKeys } from "@/api/caseApi"
import { errorMessage } from "@/api/errors"
import { EmptyState } from "@/components/common/EmptyState"
import { PATHS } from "@/routes/paths"
import { caseAccessErrorOf, type CaseAccessError } from "@/screens/case/caseErrors"
import { readCaseNavState, type CaseNavState } from "@/screens/case/caseNav"
import { CaseAccessErrorView, CaseLoadFailed, CaseLoading } from "@/screens/case/CaseStatusViews"
import { ConsultationDialog, type ConsultationTarget } from "@/screens/case/ConsultationDialog"
import { useSession } from "@/session/sessionStore"
import { confirmDialog } from "@/stores/confirmStore"
import { showToast } from "@/stores/toastStore"
import { formatCategory } from "@/utils/consultation"

/**
 * 4.2 사례자 상세 조회 (D1-A: 위 사례자 정보, 아래 상담 기록)
 * - 4.2.1 사례자 정보 조회(API-20)·수정(별도 화면, D5-B)·삭제(API-24)
 * - 4.2.2 상담 목록(API-25) → 행을 누르면 상담 창(보기·수정·삭제), '상담 등록'
 * - 본인이 담당자로 지정된 사례자만 볼 수 있다 (D10-B: 권한 없음 403 / 찾을 수 없음 404를 나눠 안내)
 */
export function CaseDetailScreen() {
  const params = useParams()
  const parsedId = Number(params.caseId)
  const caseId = Number.isSafeInteger(parsedId) && parsedId > 0 ? parsedId : null
  const navigate = useNavigate()
  const location = useLocation()
  const nav = readCaseNavState(location.state)
  const session = useSession()
  const myName = session.status === "authenticated" ? session.profile.name : ""
  const queryClient = useQueryClient()

  const [accessError, setAccessError] = useState<CaseAccessError | null>(null)
  const [dialog, setDialog] = useState<ConsultationTarget | null>(null)

  // 사례자 정보 조회 + 상담 목록 조회 (D2-A: 두 API로 나눔, 함께 부른다)
  const caseQuery = useQuery({
    queryKey: caseKeys.detail(caseId ?? 0),
    queryFn: () => caseApi.getCase(caseId ?? 0),
    enabled: caseId !== null,
  })
  const consultationsQuery = useQuery({
    queryKey: caseKeys.consultations(caseId ?? 0),
    queryFn: () => caseApi.getConsultations(caseId ?? 0),
    enabled: caseId !== null,
  })
  const deleteCase = useMutation({ mutationFn: () => caseApi.deleteCase(caseId ?? 0) })

  // 다른 사례자로 옮기면 이전 사례자의 안내·창을 지운다
  useEffect(() => {
    setAccessError(null)
    setDialog(null)
  }, [caseId])

  const access: CaseAccessError | null =
    accessError ??
    caseAccessErrorOf(caseQuery.error) ??
    caseAccessErrorOf(consultationsQuery.error) ??
    (caseId === null ? "NOT_FOUND" : null)

  /** 목록으로: 목록에서 왔으면 이전 검색 조건 그대로 (브라우저 뒤로 가기와 같음) */
  const goList = (replace = false) => {
    if (nav.listSearch !== undefined) navigate(-1)
    else navigate(PATHS.cases, { replace })
  }

  if (access) {
    return (
      <section className="screen case-detail">
        <button type="button" className="back-link" onClick={() => goList(true)}>
          &lt; 목록으로
        </button>
        <CaseAccessErrorView error={access} onBack={() => goList(true)} />
      </section>
    )
  }

  if (caseQuery.isError) {
    return (
      <section className="screen case-detail">
        <button type="button" className="back-link" onClick={() => goList()}>
          &lt; 목록으로
        </button>
        <CaseLoadFailed
          title="사례자 정보를 불러오지 못했습니다."
          message={errorMessage(caseQuery.error)}
          onRetry={() => void caseQuery.refetch()}
        />
      </section>
    )
  }

  if (!caseQuery.data || caseId === null) {
    return (
      <section className="screen case-detail">
        <CaseLoading text="사례자 정보를 불러오는 중입니다." />
      </section>
    )
  }

  const detail = caseQuery.data
  const consultations = consultationsQuery.data ?? []

  const remove = async () => {
    if (deleteCase.isPending) return
    const ok = await confirmDialog({
      title: "사례자를 삭제할까요?",
      message: consultationsQuery.data
        ? `${detail.name} 님의 상담 기록 ${consultations.length}건과 담당자 지정도 함께 삭제되며 되돌릴 수 없습니다.`
        : `${detail.name} 님의 상담 기록과 담당자 지정도 함께 삭제되며 되돌릴 수 없습니다.`,
      confirmLabel: "삭제",
      tone: "danger",
    })
    if (!ok) return
    try {
      await deleteCase.mutateAsync()
    } catch (error) {
      const code = caseAccessErrorOf(error)
      if (code) setAccessError(code)
      else showToast(errorMessage(error), "error")
      return
    }
    // 지금 화면의 조회는 다시 부르지 않고(삭제된 사례자라 404), 목록은 돌아갈 때 다시 받는다
    void queryClient.invalidateQueries({ queryKey: caseKeys.all, refetchType: "none" })
    showToast("사례자를 삭제했습니다.")
    goList(true)
  }

  const edit = () => {
    const state: CaseNavState = { listSearch: nav.listSearch, fromDetail: true }
    navigate(PATHS.caseEdit(caseId), { state })
  }

  const managers = detail.managers.map((item) => [item.name, item.title].filter(Boolean).join(" ")).join(", ")

  const consultationBody = () => {
    if (consultationsQuery.isPending) return <CaseLoading text="상담 기록을 불러오는 중입니다." />
    if (consultationsQuery.isError) {
      return (
        <CaseLoadFailed
          title="상담 기록을 불러오지 못했습니다."
          message={errorMessage(consultationsQuery.error)}
          onRetry={() => void consultationsQuery.refetch()}
        />
      )
    }
    if (consultations.length === 0) {
      return <EmptyState title="등록된 상담 기록이 없습니다." description="'상담 등록'으로 상담 내용을 기록하세요." />
    }
    return (
      <table className="data-table consult-table">
        <thead>
          <tr>
            <th>상담 일자</th>
            <th>상담 목적</th>
            <th>상담 분류</th>
            <th>기록자</th>
          </tr>
        </thead>
        <tbody>
          {consultations.map((item) => (
            <tr
              key={item.consultationId}
              tabIndex={0}
              onClick={() => setDialog({ mode: "view", consultationId: item.consultationId })}
              onKeyDown={(event) => {
                if (event.key === "Enter") setDialog({ mode: "view", consultationId: item.consultationId })
              }}
            >
              <td>{item.consultedAt}</td>
              <td className="col-purpose">{item.purpose}</td>
              <td>{formatCategory(item.category, item.categoryEtc)}</td>
              <td>{item.recorderName}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }

  return (
    <section className="screen case-detail">
      <button type="button" className="back-link" onClick={() => goList()}>
        &lt; 목록으로
      </button>
      <div className="page-heading detail-heading">
        <div>
          <h1 className="page-title">
            {detail.name} 님 <span className="title-badge">{detail.managementNo}</span>
          </h1>
          <p className="page-desc">사례자 정보와 상담 기록을 확인합니다.</p>
        </div>
        <div className="heading-actions">
          <button type="button" className="btn btn-outline" onClick={edit}>
            수정
          </button>
          <button
            type="button"
            className="btn btn-outline btn-outline-danger"
            disabled={deleteCase.isPending}
            onClick={() => void remove()}
          >
            삭제
          </button>
        </div>
      </div>

      <section className="detail-card">
        <h2 className="card-title">사례자 정보</h2>
        <dl className="info-grid">
          <InfoItem label="관리번호" value={detail.managementNo} />
          <InfoItem label="이름" value={detail.name} />
          <InfoItem label="지역" value={`${detail.sidoName} ${detail.sigunguName} ${detail.dongName}`} />
          <InfoItem label="생년월일" value={`${detail.birthDate} (만 ${detail.age}세, ${detail.ageGroup})`} />
          <InfoItem label="성별" value={detail.gender} />
          <InfoItem label="최초 등록일" value={detail.firstRegisteredAt} />
          <InfoItem label="최근 기록일" value={detail.lastRecordedAt ?? "-"} />
          <InfoItem label="담당자" value={managers} />
        </dl>
      </section>

      <section className="detail-card">
        <div className="card-head">
          <h2 className="card-title">
            상담 기록 {consultationsQuery.data && <span className="card-count">{consultations.length}건</span>}
          </h2>
          <button type="button" className="btn btn-primary btn-small" onClick={() => setDialog({ mode: "new" })}>
            상담 등록
          </button>
        </div>
        {consultationBody()}
      </section>

      {dialog && (
        <ConsultationDialog
          key={dialog.mode === "view" ? dialog.consultationId : "new"}
          caseId={caseId}
          caseName={detail.name}
          myName={myName}
          target={dialog}
          onClose={() => setDialog(null)}
          onAccessLost={(code) => {
            setDialog(null)
            setAccessError(code)
          }}
        />
      )}
    </section>
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
