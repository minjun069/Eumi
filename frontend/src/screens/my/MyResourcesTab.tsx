import "@/styles/resource.css"
import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "react-router"
import { errorMessage } from "@/api/errors"
import { myApi, myKeys } from "@/api/myApi"
import { PATHS } from "@/routes/paths"
import { MyLoadFailed, MyLoading } from "@/screens/my/MyStatusViews"
import type { ResourceNavState } from "@/screens/resource/resourceNav"
import { ResourceTable } from "@/screens/resource/ResourceTable"

/**
 * 5.2.1 담당 복지자원 목록 조회(API-35): 내가 담당자인 자원 (3.1과 같은 표, 정렬 버튼·페이지 없이 전체).
 * 행을 누르면 3.2 상세. 상세의 '목록으로'·삭제 뒤에는 이 탭으로 돌아온다 (navigation state fromMy)
 */
export function MyResourcesTab() {
  const navigate = useNavigate()
  const resourcesQuery = useQuery({ queryKey: myKeys.resources, queryFn: myApi.getMyResources })

  if (resourcesQuery.isPending) return <MyLoading text="담당 복지자원을 불러오는 중입니다." />
  if (resourcesQuery.isError) {
    return (
      <MyLoadFailed
        title="담당 복지자원을 불러오지 못했습니다."
        message={errorMessage(resourcesQuery.error)}
        onRetry={() => void resourcesQuery.refetch()}
      />
    )
  }

  return (
    <section className="detail-card my-resources-card">
      <h2 className="card-title">담당 복지자원</h2>
      <p className="field-hint my-card-hint">
        내가 담당자로 등록된 복지자원입니다. 진행 중인 자원이 먼저, 운영 종료일이 이른 순으로 보입니다.
      </p>
      <ResourceTable
        result={resourcesQuery.data}
        countLabel="담당 복지자원"
        emptyTitle="담당하는 복지자원이 없습니다."
        onOpen={(resourceId) => {
          const state: ResourceNavState = { fromMy: true }
          navigate(PATHS.resourceDetail(resourceId), { state })
        }}
      />
    </section>
  )
}
