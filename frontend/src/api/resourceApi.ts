import { api } from "@/api/http"
import type { operations } from "@/api/schema"
import type { Schemas, SuccessData } from "@/api/types"

// 복지자원 (모든 기관의 자원을 볼 수 있고, 수정·삭제는 지금 담당자 본인만).
// 삭제됐거나 없는 자원은 404 NOT_FOUND, 담당자가 아닌데 수정·삭제하면 403 FORBIDDEN.

export type ResourceSearchQuery = NonNullable<operations["resourceApi_searchResources"]["parameters"]["query"]>
export type ResourceSortKey = NonNullable<ResourceSearchQuery["sort"]>
export type ResourcePage = SuccessData<"resourceApi_searchResources_Success">
export type ResourceListItem = Schemas["ResourceListItem"]
export type ResourceDetail = SuccessData<"resourceApi_getResource_Success">
export type ResourceInput = Schemas["ResourceInput"]
export type ResourceCreated = SuccessData<"resourceApi_createResource_Success">
export type SupportAgeGroup = ResourceInput["supportAgeGroups"][number]
export type SupportGender = ResourceInput["supportGender"]
/** 담당자가 고르는 상태(manualStatus). 응답의 status는 종료일이 지나면 '종료'로 바뀐 표시 상태다 */
export type ResourceStatus = ResourceInput["status"]

/** ResourceInput 글자 수 상한 (openapi maxLength) */
export const RESOURCE_TEXT_LIMITS = {
  resourceName: 50,
  operatingOrgName: 50,
  target: 100,
  supportContent: 1000,
  applyMethod: 200,
} as const

// 목록·상세는 모두 ["resources", …] 아래에 둔다. 등록·수정·삭제 뒤 resourceKeys.all을 무효화한다
export const resourceKeys = {
  all: ["resources"] as const,
  list: (query: ResourceSearchQuery) => ["resources", "list", query] as const,
  detail: (resourceId: number) => ["resources", "detail", resourceId] as const,
}

const resourcePath = (resourceId: number) => `/resources/${resourceId}`

export const resourceApi = {
  /** API-13 GET /resources — 진행 중을 항상 먼저 둔다. 범위를 넘는 page는 마지막 페이지로 보정해 돌려준다 */
  searchResources: (query: ResourceSearchQuery) => api.get<ResourcePage>("/resources", { query }),

  /** API-14 GET /resources/{resourceId} — editable은 지금 담당자 본인에게만 true */
  getResource: (resourceId: number) => api.get<ResourceDetail>(resourcePath(resourceId)),

  /** API-15 PUT /resources/{resourceId} — 204. 담당자를 바꾸면 저장한 사람은 더 이상 수정·삭제할 수 없다 */
  updateResource: (resourceId: number, input: ResourceInput) => api.put<void>(resourcePath(resourceId), input),

  /** API-16 DELETE /resources/{resourceId} — 204 */
  deleteResource: (resourceId: number) => api.delete<void>(resourcePath(resourceId)),

  /** API-17 POST /resources — 201 */
  createResource: (input: ResourceInput) => api.post<ResourceCreated>("/resources", input),
}
