import { api } from "@/api/http"
import type { SuccessData } from "@/api/types"

// 같은 기관 회원 (담당자 선택용)

export type OrgMembers = SuccessData<"memberApi_getOrgMembers_Success">
export type MemberOption = OrgMembers[number]

export const memberKeys = {
  orgMembers: ["members", "org"] as const,
}

export const memberApi = {
  /** API-42 GET /organizations/me/members — 로그인 회원과 같은 기관의 활성 회원 */
  getOrgMembers: () => api.get<OrgMembers>("/organizations/me/members"),
}
