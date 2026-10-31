import { useCallback, useEffect, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router"
import { EmptyState } from "@/components/common/EmptyState"
import { devCases } from "@/devtools/devCases"
import { useDevScenario } from "@/devtools/devScenarioStore"
import {
  CASE_FORBIDDEN_MESSAGE,
  CASE_NOT_FOUND_MESSAGE,
  caseApi,
  type CaseDetail,
} from "@/mock/api/caseApi"
import {
  CONSULTATION_NOT_FOUND_MESSAGE,
  consultationApi,
  type ConsultationListItem,
} from "@/mock/api/consultationApi"
import { PATHS } from "@/routes/paths"
import { readCaseNavState, type CaseNavState } from "@/screens/case/caseNav"
import { ConsultationDialog, type ConsultationTarget } from "@/screens/case/ConsultationDialog"
import { RECOMMEND_QUESTION } from "@/mock/agent/agentExamples"
import { useSession } from "@/session/sessionStore"
import { useAgentContext, type AgentContext } from "@/stores/agentContextStore"
import { agentStore, useAgentState } from "@/stores/agentStore"
import { confirmDialog } from "@/stores/confirmStore"
import { showToast } from "@/stores/toastStore"
import { formatCategory } from "@/utils/consultation"

/**
 * 4.2 사례자 상세 조회 (D1-A: 위 사례자 정보, 아래 상담 기록)
 * - 4.2.1 사례자 정보 조회·수정(별도 화면, D5-B)·삭제
 * - 4.2.2 상담 목록 → 행을 누르면 상담 창(보기·수정·삭제), '상담 등록'
 * - 본인이 담당자로 지정된 사례자만 볼 수 있다 (D10-B: 권한 없음 / 찾을 수 없음을 나눠 안내)
 */
export function CaseDetailScreen() {
  const params = useParams()
  const caseId = Number(params.caseId)
  const navigate = useNavigate()
  const location = useLocation()
  const nav = readCaseNavState(location.state)
  const session = useSession()
  const myName = session.status === "authenticated" ? session.profile.name : ""

  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [consultations, setConsultations] = useState<ConsultationListItem[]>([])
  const [accessError, setAccessError] = useState<string | null>(null)
  const [dialog, setDialog] = useState<ConsultationTarget | null>(null)

  /** 권한 없음·찾을 수 없음이면 안내 화면으로 바꾸고, 그 밖의 실패는 알림으로 보여 준다 */
  const handleFailure = useCallback((message: string) => {
    if (message === CASE_FORBIDDEN_MESSAGE || message === CASE_NOT_FOUND_MESSAGE) {
      setDialog(null)
      setAccessError(message)
      return
    }
    showToast(message, "error")
  }, [])

  // 사례자 정보 조회 + 상담 목록 조회 (D2-A: 두 API로 나눔)
  const load = useCallback(() => {
    const caseResult = caseApi.getCase({ caseId })
    if (!caseResult.ok) {
      handleFailure(caseResult.message)
      return
    }
    setDetail(caseResult.data)
    const listResult = consultationApi.getConsultations({ caseId })
    if (listResult.ok) setConsultations(listResult.data)
    else handleFailure(listResult.message)
  }, [caseId, handleFailure])

  useEffect(() => {
    setAccessError(null)
    setDetail(null)
    setDialog(null)
    load()
  }, [load])

  /** 목록으로: 목록에서 왔으면 이전 검색 조건 그대로 (브라우저 뒤로 가기와 같음) */
  const goList = (replace = false) => {
    if (nav.listSearch !== undefined) navigate(-1)
    else navigate(PATHS.cases, { replace })
  }

  const openCase = (name: string) => {
    const id = devCases.findCaseId(name)
    navigate(PATHS.caseDetail(id ?? 9999), { state: location.state })
  }

  useDevScenario(
    {
      screen: "사례자 상세",
      hint: "'다른 담당자가 한 일'은 데이터만 바꿉니다. 그다음 상담을 열거나 수정·삭제·상담 등록을 눌러 서버 응답을 확인하세요. 상황 전환에서 박성민으로 바꾸면 공동 담당 사례자(이영자)는 그대로 보입니다.",
      actions: [
        { label: "공동 담당 사례자 (이영자)", run: () => openCase("이영자") },
        { label: "상담 기록 없는 사례자 (차유진)", run: () => openCase("차유진") },
        { label: "다른 직원 담당 사례자 (송미라)", run: () => openCase("송미라") },
        { label: "다른 기관 사례자 (김하준)", run: () => openCase("김하준") },
        { label: "없는 사례자 열기", run: () => navigate(PATHS.caseDetail(9999), { state: location.state }) },
      ],
      groups: [
        {
          title: "다른 담당자가 한 일",
          actions: [
            { label: "이 사례자를 삭제함", run: () => devCases.deleteCase(caseId) },
            { label: "나를 담당자에서 뺌", run: () => devCases.removeMe(caseId) },
          ],
        },
      ],
    },
    [caseId, location.state],
  )

  // AI Agent가 참고할 화면: 사례자ID만 보낸다. 이름은 화면 안 안내(추천 자원 상세)에만 쓴다 (A3-A, A6-A)
  const agentContext: AgentContext | null = detail
    ? {
        screen: { screenType: "case-detail", caseId },
        label: `사례자 상세 · 관리번호 ${detail.managementNo}`,
        caseRef: { caseId, caseName: detail.name },
      }
    : null
  useAgentContext(agentContext, [detail])
  const agentBusy = useAgentState().busy

  if (accessError) {
    return (
      <section className="screen case-detail">
        <button type="button" className="back-link" onClick={() => goList(true)}>
          &lt; 목록으로
        </button>
        <div className="case-access-error">
          <EmptyState
            title={accessError}
            description={
              accessError === CASE_FORBIDDEN_MESSAGE
                ? "담당자로 지정된 사례자만 볼 수 있습니다."
                : "삭제되었거나 주소가 잘못되었습니다."
            }
          />
          <button type="button" className="btn btn-outline" onClick={() => goList(true)}>
            목록으로
          </button>
        </div>
      </section>
    )
  }

  if (!detail) return null

  const remove = async () => {
    const ok = await confirmDialog({
      title: "사례자를 삭제할까요?",
      message: `${detail.name} 님의 상담 기록 ${consultations.length}건과 담당자 지정도 함께 삭제되며 되돌릴 수 없습니다.`,
      confirmLabel: "삭제",
      tone: "danger",
    })
    if (!ok) return
    const result = caseApi.deleteCase({ caseId })
    if (!result.ok) {
      handleFailure(result.message)
      return
    }
    showToast("사례자를 삭제했습니다.")
    goList(true)
  }

  const edit = () => {
    const state: CaseNavState = { listSearch: nav.listSearch, fromDetail: true }
    navigate(PATHS.caseEdit(caseId), { state })
  }

  const onDialogFailure = (message: string) => {
    if (message === CONSULTATION_NOT_FOUND_MESSAGE) {
      setDialog(null)
      showToast(message, "error")
      load()
      return
    }
    handleFailure(message)
  }

  const managers = detail.managers.map((item) => [item.name, item.title].filter(Boolean).join(" ")).join(", ")

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
          <button
            type="button"
            className="btn btn-outline btn-ai"
            disabled={agentBusy}
            title={agentBusy ? "AI가 다른 답변을 만드는 중이에요" : undefined}
            onClick={() => {
              if (!agentContext) return
              agentStore.open()
              agentStore.ask(RECOMMEND_QUESTION, agentContext)
            }}
          >
            <span className="sparkle" aria-hidden="true">
              ✦
            </span>{" "}
            AI 맞춤 자원 추천
          </button>
          <button type="button" className="btn btn-outline" onClick={edit}>
            수정
          </button>
          <button type="button" className="btn btn-outline btn-outline-danger" onClick={() => void remove()}>
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
            상담 기록 <span className="card-count">{consultations.length}건</span>
          </h2>
          <button type="button" className="btn btn-primary btn-small" onClick={() => setDialog({ mode: "new" })}>
            상담 등록
          </button>
        </div>
        {consultations.length === 0 ? (
          <EmptyState title="등록된 상담 기록이 없습니다." description="'상담 등록'으로 상담 내용을 기록하세요." />
        ) : (
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
        )}
      </section>

      {dialog && (
        <ConsultationDialog
          key={dialog.mode === "view" ? dialog.consultationId : "new"}
          caseId={caseId}
          caseName={detail.name}
          myName={myName}
          target={dialog}
          onClose={() => setDialog(null)}
          onChanged={load}
          onFailure={onDialogFailure}
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
