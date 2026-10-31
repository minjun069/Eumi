// 복지자원 화면 사이에 넘기는 값 (브라우저 기록의 state)

export type ResourceNavState = {
  /** 목록에서 왔을 때 목록 주소의 ?… 부분. 있으면 '목록으로'가 이전 검색 조건으로 돌아간다 */
  listSearch?: string
  /** 상세의 '수정'으로 수정 화면에 왔는지. 저장·취소하면 상세로 되돌아간다 (8단계) */
  fromDetail?: boolean
  /** 마이페이지 '담당 복지자원'(5.2.1)에서 왔는지. '목록으로'·삭제 뒤에 그 목록으로 돌아간다 */
  fromMy?: boolean
  /** AI 맞춤 추천(0.2.3)에서 왔을 때: 상세 위 안내와 '사례자 상세로' 링크 (A6-A) */
  recommendedFor?: { caseId: number; caseName: string }
}

export function readResourceNavState(state: unknown): ResourceNavState {
  if (!state || typeof state !== "object") return {}
  const value = state as Record<string, unknown>
  const recommended = value.recommendedFor as { caseId?: unknown; caseName?: unknown } | undefined
  return {
    listSearch: typeof value.listSearch === "string" ? value.listSearch : undefined,
    fromDetail: value.fromDetail === true,
    fromMy: value.fromMy === true,
    recommendedFor:
      recommended && typeof recommended.caseId === "number" && typeof recommended.caseName === "string"
        ? { caseId: recommended.caseId, caseName: recommended.caseName }
        : undefined,
  }
}
