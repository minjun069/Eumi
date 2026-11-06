import "@/styles/detail.css"
import "@/styles/resource.css"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router"
import { errorMessage } from "@/api/errors"
import { resourceApi, resourceKeys } from "@/api/resourceApi"
import { PATHS } from "@/routes/paths"
import { resourceAccessErrorOf, RESOURCE_MESSAGES } from "@/screens/resource/resourceErrors"
import { formatAgeGroups, formatFee, formatManager, formatPeriod } from "@/screens/resource/resourceFormat"
import { readResourceNavState, type ResourceNavState } from "@/screens/resource/resourceNav"
import { ResourceAccessErrorView, ResourceLoadFailed, ResourceLoading } from "@/screens/resource/ResourceStatusViews"
import { confirmDialog } from "@/stores/confirmStore"
import { showToast } from "@/stores/toastStore"

/**
 * 3.2 복지자원 상세 조회 (API-14)
 * - 3.2.1 상세 정보: '기본 정보' 카드 + '지원 내용·신청 방법' 카드
 * - 3.2.2 수정(등록 양식 화면)·삭제(확인 창, API-16): 응답의 editable이 true일 때만 버튼을 보인다 (서버도 다시 검사)
 * - status는 표시 상태(종료일이 지나면 '종료'), autoEnded면 자동 종료 안내
 * - 종료된 자원의 담당자가 탈퇴했으면 서버가 이름을 '퇴사자'로 보낸다. 그대로 보여 준다
 */
export function ResourceDetailScreen() {
  const params = useParams()
  const parsedId = Number(params.resourceId)
  const resourceId = Number.isSafeInteger(parsedId) && parsedId > 0 ? parsedId : null
  const navigate = useNavigate()
  const location = useLocation()
  const nav = readResourceNavState(location.state)
  const queryClient = useQueryClient()

  const [deleted, setDeleted] = useState(false)

  const detailQuery = useQuery({
    queryKey: resourceKeys.detail(resourceId ?? 0),
    queryFn: () => resourceApi.getResource(resourceId ?? 0),
    enabled: resourceId !== null,
  })
  const deleteResource = useMutation({ mutationFn: () => resourceApi.deleteResource(resourceId ?? 0) })

  useEffect(() => setDeleted(false), [resourceId])

  /** 목록으로: 목록(3.1)이나 마이페이지 담당 복지자원(5.2.1)에서 왔으면 그 목록으로 되돌아간다 */
  const goList = (replace = false) => {
    if (nav.listSearch !== undefined || nav.fromMy) navigate(-1)
    else navigate(PATHS.resources, { replace })
  }

  // 상세 조회는 누구나 할 수 있어 404(없음·삭제됨)만 안내 화면으로 보낸다
  const notFound =
    deleted || resourceId === null || resourceAccessErrorOf(detailQuery.error) === "NOT_FOUND"

  if (notFound) {
    return (
      <section className="screen resource-detail">
        <button type="button" className="back-link" onClick={() => goList(true)}>
          &lt; 목록으로
        </button>
        <ResourceAccessErrorView error="NOT_FOUND" backLabel="목록으로" onBack={() => goList(true)} />
      </section>
    )
  }

  if (detailQuery.isError) {
    return (
      <section className="screen resource-detail">
        <button type="button" className="back-link" onClick={() => goList()}>
          &lt; 목록으로
        </button>
        <ResourceLoadFailed
          title="복지자원 정보를 불러오지 못했습니다."
          message={errorMessage(detailQuery.error)}
          onRetry={() => void detailQuery.refetch()}
        />
      </section>
    )
  }

  if (!detailQuery.data) {
    return (
      <section className="screen resource-detail">
        <ResourceLoading text="복지자원 정보를 불러오는 중입니다." />
      </section>
    )
  }

  const detail = detailQuery.data

  const remove = async () => {
    if (deleteResource.isPending) return
    const ok = await confirmDialog({
      title: "복지자원을 삭제할까요?",
      message: `'${detail.resourceName}'을(를) 삭제하면 목록·상세·추천에 나오지 않습니다.`,
      confirmLabel: "삭제",
      tone: "danger",
    })
    if (!ok) return
    try {
      await deleteResource.mutateAsync()
    } catch (error) {
      const code = resourceAccessErrorOf(error)
      if (code === "NOT_FOUND") {
        setDeleted(true)
      } else if (code === "FORBIDDEN") {
        // 그사이 담당자가 바뀐 경우: 알리고 다시 조회해 버튼을 맞춘다
        showToast(RESOURCE_MESSAGES.deleteForbidden, "error")
        void detailQuery.refetch()
      } else {
        showToast(errorMessage(error), "error")
      }
      return
    }
    // 지금 화면의 조회는 다시 부르지 않고(삭제된 자원이라 404), 목록은 돌아갈 때 다시 받는다
    void queryClient.invalidateQueries({ queryKey: resourceKeys.all, refetchType: "none" })
    showToast("복지자원을 삭제했습니다.")
    goList(true)
  }

  const edit = () => {
    const state: ResourceNavState = { listSearch: nav.listSearch, fromMy: nav.fromMy, fromDetail: true }
    navigate(PATHS.resourceEdit(detail.resourceId), { state })
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
            <button
              type="button"
              className="btn btn-outline btn-outline-danger"
              disabled={deleteResource.isPending}
              onClick={() => void remove()}
            >
              삭제
            </button>
          </div>
        )}
      </div>

      {detail.manager.withdrawn && <p className="notice-bar">담당자가 퇴사해 수정·삭제할 수 없습니다.</p>}

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
            note={detail.autoEnded ? "운영 종료일이 지나 자동으로 종료되었습니다." : undefined}
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
