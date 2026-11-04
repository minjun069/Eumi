import { api } from "@/api/http"
import type { Schemas, SuccessData } from "@/api/types"

// 마이페이지 (로그인한 회원 본인 정보만)

export type MyInfo = SuccessData<"myApi_getMyInfo_Success">
export type MyInfoPatch = Schemas["MyInfoPatch"]
export type MyResources = SuccessData<"myApi_getMyResources_Success">

export const myKeys = {
  info: ["my", "info"] as const,
  // 복지자원 쿼리(["resources", …]) 아래에 둬서 자원을 등록·수정·삭제하면 함께 무효화된다
  resources: ["resources", "mine"] as const,
}

export const myApi = {
  /** API-30 GET /members/me */
  getMyInfo: () => api.get<MyInfo>("/members/me"),

  /** API-31 PATCH /members/me — 직함·전화만. 보낸 필드만 바꾸고(생략은 유지) null은 비움. 바뀐 내 정보를 돌려준다 */
  updateMyInfo: (patch: MyInfoPatch) => api.patch<MyInfo>("/members/me", patch),

  /** API-35 GET /members/me/resources — 본인이 담당하는 자원 전체 (페이지 없음, 진행 중 먼저·종료일 순) */
  getMyResources: () => api.get<MyResources>("/members/me/resources"),
}
