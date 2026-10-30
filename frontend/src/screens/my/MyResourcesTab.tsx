import { useEffect, useState } from "react"
import { useNavigate } from "react-router"
import { myApi, type MyResourcesResponse } from "@/mock/api/myApi"
import { PATHS } from "@/routes/paths"
import type { ResourceNavState } from "@/screens/resource/resourceNav"
import { ResourceTable } from "@/screens/resource/ResourceTable"

/**
 * 5.2.1 담당 복지자원 목록 조회: 내가 담당자인 자원 (M8-A: 3.1과 같은 표, 정렬 버튼·페이지 없이 전체).
 * 행을 누르면 3.2 상세. 상세의 '목록으로'·삭제 뒤에는 이 탭으로 돌아온다
 */
export function MyResourcesTab() {
  const navigate = useNavigate()
  const [result, setResult] = useState<MyResourcesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const response = myApi.getMyResources()
    if (response.ok) setResult(response.data)
    else setError(response.message)
  }, [])

  if (error) return <p className="notice-bar">{error}</p>
  if (!result) return null

  return (
    <section className="detail-card my-resources-card">
      <h2 className="card-title">담당 복지자원</h2>
      <p className="field-hint my-card-hint">
        내가 담당자로 등록된 복지자원입니다. 진행 중인 자원이 먼저, 운영 종료일이 이른 순으로 보입니다.
      </p>
      <ResourceTable
        result={result}
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
