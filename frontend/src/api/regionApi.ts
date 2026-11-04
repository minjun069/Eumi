import { api } from "@/api/http"
import type { SuccessData } from "@/api/types"

// 지역 선택 목록 (시도 → 시군구 → 행정동)

export type SidoList = SuccessData<"regionApi_getSidos_Success">
export type SigunguList = SuccessData<"regionApi_getSigungus_Success">
export type DongList = SuccessData<"regionApi_getDongs_Success">

export const regionKeys = {
  sidos: ["regions", "sidos"] as const,
  sigungus: (sidoCode: string) => ["regions", "sigungus", sidoCode] as const,
  dongs: (sigunguCode: string) => ["regions", "dongs", sigunguCode] as const,
}

export const regionApi = {
  /** API-39 GET /regions/sidos */
  getSidos: () => api.get<SidoList>("/regions/sidos"),

  /** API-40 GET /regions/sidos/{sidoCode}/sigungus — 없는 시도는 404 */
  getSigungus: (sidoCode: string) =>
    api.get<SigunguList>(`/regions/sidos/${encodeURIComponent(sidoCode)}/sigungus`),

  /** API-41 GET /regions/sigungus/{sigunguCode}/dongs — 없는 시군구는 404 */
  getDongs: (sigunguCode: string) =>
    api.get<DongList>(`/regions/sigungus/${encodeURIComponent(sigunguCode)}/dongs`),
}
