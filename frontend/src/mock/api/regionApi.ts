import { db } from "@/mock/db"
import { callApi } from "@/mock/api/core"

// 지역 목록 (시도 → 시군구 → 행정동). 사례자 목록(4.1.1), 복지자원 조회(3.1.1), 고립 위험 탐색(2.1.1)이 같이 쓴다.
// 기능 ID는 부르는 화면의 기능으로 기록한다.

export const regionApi = {
  getSidos(featureId: string) {
    return callApi({ featureId, featureName: "시도 목록 조회" }, {}, () =>
      db.sidos.map(({ sidoCode, sidoName }) => ({ sidoCode, sidoName })),
    )
  },

  getSigungus(featureId: string, request: { sidoCode: string }) {
    return callApi({ featureId, featureName: "시군구 목록 조회" }, request, ({ sidoCode }) =>
      db.sigungus
        .filter((item) => item.sidoCode === sidoCode)
        .map(({ sigunguCode, sigunguName }) => ({ sigunguCode, sigunguName })),
    )
  },

  getDongs(featureId: string, request: { sigunguCode: string }) {
    return callApi({ featureId, featureName: "행정동 목록 조회" }, request, ({ sigunguCode }) =>
      db.dongs
        .filter((item) => item.sigunguCode === sigunguCode)
        .map(({ dongCode, dongName }) => ({ dongCode, dongName })),
    )
  },
}
