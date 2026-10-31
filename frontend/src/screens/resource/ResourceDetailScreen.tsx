import { useCallback, useEffect, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router"
import { EmptyState } from "@/components/common/EmptyState"
import { devResources } from "@/devtools/devResources"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { RESOURCE_NOT_FOUND_MESSAGE, resourceApi, type ResourceDetail } from "@/mock/api/resourceApi"
import { PATHS } from "@/routes/paths"
import {
  formatAgeGroups,
  formatFee,
  formatManager,
  formatPeriod,
} from "@/screens/resource/resourceFormat"
import { readResourceNavState, type ResourceNavState } from "@/screens/resource/resourceNav"
import { useAgentContext } from "@/stores/agentContextStore"
import { confirmDialog } from "@/stores/confirmStore"
import { showToast } from "@/stores/toastStore"

/**
 * 3.2 복지자원 상세 조회 (7단계)
 * - 3.2.1 상세 정보: '기본 정보' 카드 + '지원 내용·신청 방법' 카드 (V2-B)
 * - 3.2.2 수정(등록 양식 화면)·삭제(확인 창, soft delete): 담당자만, 아니면 버튼을 숨김 (V1-A)
 * - 수정·삭제 가능 여부는 상세 조회 응답의 editable로 정한다 (V5-A)
 * - 담당자가 탈퇴한 자원은 '퇴사자'로 표시하고 조회만 가능 (5.1.4, V4-A)
 */
export function ResourceDetailScreen() {
  const params = useParams()
  const resourceId = Number(params.resourceId)
  const navigate = useNavigate()
  const location = useLocation()
  const nav = readResourceNavState(location.state)

  const [detail, setDetail] = useState<ResourceDetail | null>(null)
  const [notFound, setNotFound] = useState(false)

  const load = useCallback(() => {
    const result = resourceApi.getResource({ resourceId })
    if (result.ok) {
      setDetail(result.data)
      setNotFound(false)
    } else if (result.message === RESOURCE_NOT_FOUND_MESSAGE) {
      setNotFound(true)
    } else {
      showToast(result.message, "error")
    }
  }, [resourceId])

  useEffect(() => {
    setDetail(null)
    setNotFound(false)
    load()
  }, [load])

  /** 목록으로: 목록에서 왔으면 이전 검색 조건 그대로 (브라우저 뒤로 가기와 같음) */
  const goList = (replace = false) => {
    // 목록(3.1)이나 마이페이지 담당 복지자원(5.2.1)에서 왔으면 그 목록으로 되돌아간다
    if (nav.listSearch !== undefined || nav.fromMy) navigate(-1)
    else navigate(PATHS.resources, { replace })
  }

  // 개발용 바로 열기는 지금 기록을 바꿔치기해, '목록으로'(뒤로 가기)가 목록으로 돌아가게 한다
  const open = (resourceName: string) => {
    const id = devResources.findResourceId(resourceName)
    navigate(PATHS.resourceDetail(id ?? 9999), { state: location.state, replace: true })
  }

  useDevScenario(
    {
      screen: "복지자원 상세",
      hint: "'다른 사람이 한 일'은 데이터만 바꿉니다. 그다음 '삭제'를 눌러 서버 응답을 확인하세요. 상황 전환에서 박성민으로 바꾸면 박성민 담당 자원에 수정·삭제 버튼이 보입니다.",
      actions: [
        { label: "내 담당 자원", run: () => open("어르신 안부 산책 모임") },
        { label: "같은 기관 다른 직원 자원 (박성민)", run: () => open("어르신 스마트폰 교실") },
        { label: "다른 기관 자원 (임채원)", run: () => open("1인 가구 이웃 만들기") },
        { label: "퇴사자 자원 (이수진)", run: () => open("어르신 이동 목욕 서비스") },
        { label: "기간이 끝나 종료된 자원", run: () => open("청년 마음건강 상담") },
        { label: "직접 종료한 자원 (박성민)", run: () => open("어르신 건강 체조") },
        {
          label: "없는 자원 열기",
          run: () => navigate(PATHS.resourceDetail(9999), { state: location.state, replace: true }),
        },
        { label: "삭제된 자원 열기", run: () => open("여름 무더위 쉼터 운영") },
      ],
      groups: [
        {
          title: "다른 사람이 한 일",
          actions: [
            { label: "이 자원을 삭제함", run: () => devResources.deleteResource(resourceId) },
            { label: "담당자가 다른 사람으로 바뀜", run: () => devResources.changeManager(resourceId) },
          ],
        },
      ],
    },
    [resourceId, location.state],
  )

  // AI Agent가 참고할 화면: 복지자원ID (0.2.2)
  useAgentContext(
    detail
      ? { screen: { screenType: "resource-detail", resourceId: detail.resourceId }, label: `복지자원 상세 · ${detail.resourceName}` }
      : null,
    [detail],
  )

  if (notFound) {
    return (
      <section className="screen resource-detail">
        <button type="button" className="back-link" onClick={() => goList(true)}>
          &lt; 목록으로
        </button>
        <div className="resource-not-found">
          <EmptyState title={RESOURCE_NOT_FOUND_MESSAGE} description="삭제되었거나 주소가 잘못되었습니다." />
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
      title: "복지자원을 삭제할까요?",
      message: `'${detail.resourceName}'을(를) 삭제하면 목록·상세·추천에 나오지 않습니다.`,
      confirmLabel: "삭제",
      tone: "danger",
    })
    if (!ok) return
    const result = resourceApi.deleteResource({ resourceId })
    if (!result.ok) {
      if (result.message === RESOURCE_NOT_FOUND_MESSAGE) {
        setNotFound(true)
        return
      }
      // 그사이 담당자가 바뀐 경우 등: 알리고 다시 조회해 버튼을 맞춘다
      showToast(result.message, "error")
      load()
      return
    }
    showToast("복지자원을 삭제했습니다.")
    goList(true)
  }

  const edit = () => {
    const state: ResourceNavState = { listSearch: nav.listSearch, fromMy: nav.fromMy, fromDetail: true }
    navigate(PATHS.resourceEdit(resourceId), { state })
  }

  const region = `${detail.sidoName} ${detail.sigunguName} ${detail.dongName ?? "전체"}`

  return (
    <section className="screen resource-detail">
      <button type="button" className="back-link" onClick={() => goList()}>
        &lt; 목록으로
      </button>
      <div className="page-heading detail-heading">
        <div>
          <h1 className="page-title">
            {detail.resourceName}{" "}
            <span className={`status-badge title-status ${detail.status === "종료" ? "is-ended" : "is-active"}`}>
              {detail.status}
            </span>
          </h1>
          <p className="page-desc">복지자원 정보를 확인합니다.</p>
        </div>
        {detail.editable && (
          <div className="heading-actions">
            <button type="button" className="btn btn-outline" onClick={edit}>
              수정
            </button>
            <button type="button" className="btn btn-outline btn-outline-danger" onClick={() => void remove()}>
              삭제
            </button>
          </div>
        )}
      </div>

      {nav.recommendedFor && (
        <p className="notice-bar notice-ai">
          <span>
            <span className="sparkle" aria-hidden="true">
              ✦
            </span>{" "}
            {nav.recommendedFor.caseName} 님을 위해 AI가 추천한 복지자원입니다.
          </span>
          <button
            type="button"
            className="link-button"
            onClick={() => navigate(PATHS.caseDetail(nav.recommendedFor?.caseId ?? ""))}
          >
            사례자 상세로 →
          </button>
        </p>
      )}
      {!detail.manager && <p className="notice-bar">담당자가 퇴사해 수정·삭제할 수 없습니다.</p>}

      <section className="detail-card">
        <h2 className="card-title">기본 정보</h2>
        <dl className="info-grid">
          <InfoItem label="수행·담당 기관" value={detail.operatingOrgName} />
          <InfoItem label="지원 대상" value={detail.target} />
          <InfoItem label="지원 연령" value={formatAgeGroups(detail.supportAgeGroups)} />
          <InfoItem label="지원 성별" value={detail.supportGender} />
          <InfoItem label="지역" value={region} />
          <InfoItem label="운영 기간" value={formatPeriod(detail.periodStart, detail.periodEnd)} />
          <InfoItem label="이용자 부담금" value={formatFee(detail.fee)} />
          <InfoItem
            label="상태"
            value={detail.status}
            note={detail.autoEnded ? "운영 기간이 끝나 종료되었습니다." : undefined}
          />
          <InfoItem label="담당자" value={formatManager(detail.manager)} />
          <InfoItem label="정원" value={`${detail.capacity}명`} />
          <InfoItem
            label="실제 참여자 수"
            value={detail.actualParticipants === null ? "-" : `${detail.actualParticipants}명`}
          />
        </dl>
      </section>

      <section className="detail-card">
        <h2 className="card-title">지원 내용·신청 방법</h2>
        <dl className="info-grid info-grid-single">
          <InfoItem label="지원 내용" value={detail.supportContent ?? "-"} multiline />
          <InfoItem label="신청 방법" value={detail.applyMethod ?? "-"} multiline />
        </dl>
      </section>
    </section>
  )
}

function InfoItem({
  label,
  value,
  note,
  multiline = false,
}: {
  label: string
  value: string
  note?: string
  multiline?: boolean
}) {
  return (
    <div className="info-item">
      <dt>{label}</dt>
      <dd className={multiline ? "info-multiline" : undefined}>
        {value}
        {note && <span className="info-note">{note}</span>}
      </dd>
    </div>
  )
}
