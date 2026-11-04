// 사례자 화면 사이에 넘기는 값 (브라우저 기록의 state. HTTP 요청에는 넣지 않는다)

export type CaseNavState = {
  /** 목록에서 왔을 때 목록 주소의 ?… 부분. 있으면 '목록으로'가 이전 검색 조건으로 돌아간다 */
  listSearch?: string
  /** 상세의 '수정'으로 수정 화면에 왔는지. 저장·취소하면 상세로 되돌아간다 */
  fromDetail?: boolean
}

export function readCaseNavState(state: unknown): CaseNavState {
  if (!state || typeof state !== "object") return {}
  const value = state as Record<string, unknown>
  return {
    listSearch: typeof value.listSearch === "string" ? value.listSearch : undefined,
    fromDetail: value.fromDetail === true,
  }
}
