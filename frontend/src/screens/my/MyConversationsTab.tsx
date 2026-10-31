import { useCallback, useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router"
import { EmptyState } from "@/components/common/EmptyState"
import { Pagination } from "@/components/common/Pagination"
import { devAgent } from "@/devtools/devAgent"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { daysUntilDelete } from "@/mock/agent/retention"
import { agentApi, type ConversationListItem, type ConversationListResponse } from "@/mock/api/agentApi"
import { agentStore, useAgentState } from "@/stores/agentStore"
import { confirmDialog } from "@/stores/confirmStore"
import { showToast } from "@/stores/toastStore"

const PAGE_SIZE = 10
/** 삭제 예정일이 이 날 수 안이면 강조 */
const SOON_DAYS = 7

/**
 * 5.3.1 이전 대화 조회 (0.2.4 저장한 대화): 첫 질문을 제목으로, 최근 대화 순, 10개씩.
 * 고르면 AI Agent 패널에서 이어서 대화 (M11-A). 삭제는 확인 창 뒤. 보관 기간: 마지막 대화일부터 3개월 (M10-A)
 */
export function MyConversationsTab() {
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get("page")) || 1)
  const [result, setResult] = useState<ConversationListResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const agent = useAgentState()

  const load = useCallback(() => {
    const response = agentApi.listConversations({ page, size: PAGE_SIZE })
    if (response.ok) setResult(response.data)
    else setError(response.message)
  }, [page])

  useEffect(load, [load])

  // 패널에서 답을 끝까지 받으면 저장된 대화가 바뀌므로 목록을 다시 받는다
  const wasBusy = useRef(agent.busy)
  useEffect(() => {
    if (wasBusy.current && !agent.busy) load()
    wasBusy.current = agent.busy
  }, [agent.busy, load])

  const goPage = (next: number) => setParams(next > 1 ? { page: String(next) } : {})

  const open = (item: ConversationListItem) => {
    if (agent.busy) return
    const response = agentApi.getConversation({ conversationId: item.conversationId })
    if (!response.ok) {
      showToast(response.message, "error")
      load()
      return
    }
    agentStore.loadConversation(response.data)
  }

  const remove = async (item: ConversationListItem) => {
    const confirmed = await confirmDialog({
      title: "대화 기록을 삭제할까요?",
      message: `'${item.firstQuestion}' 대화의 질문·답변 ${item.questionCount}개를 지웁니다. 되돌릴 수 없습니다.`,
      confirmLabel: "삭제",
      tone: "danger",
    })
    if (!confirmed) return
    const response = agentApi.deleteConversation({ conversationId: item.conversationId })
    if (!response.ok) {
      showToast(response.message, "error")
      load()
      return
    }
    agentStore.forget(item.conversationId)
    showToast("대화 기록을 삭제했습니다.")
    load()
  }

  const first = result?.items[0]
  useDevScenario(
    {
      screen: "마이페이지 · AI 대화 기록",
      hint: "'다른 곳에서 한 일'은 데이터만 바꿉니다. 그 대화를 누르거나 삭제하면 실패 응답을 볼 수 있습니다.",
      actions: [],
      groups: first
        ? [
            {
              title: "다른 곳에서 한 일",
              actions: [
                {
                  label: `첫 번째 대화를 다른 곳에서 삭제함`,
                  run: () => devAgent.deleteConversationElsewhere(first.conversationId),
                },
              ],
            },
          ]
        : [],
      infos: [{ label: "보관 기간이 지난 대화", value: `${devAgent.expiredConversationCount()}개 (목록에서 빠짐)` }],
    },
    [first?.conversationId, result],
  )

  if (error) return <p className="notice-bar">{error}</p>
  if (!result) return null

  return (
    <section className="detail-card my-conversations-card">
      <h2 className="card-title">AI 대화 기록</h2>
      <p className="field-hint my-card-hint">
        AI Agent 패널에서 나눈 대화입니다. 누르면 패널에서 이어서 대화할 수 있습니다. 마지막 대화일부터 3개월이 지나면
        자동으로 지웁니다.
      </p>
      {agent.busy && <p className="notice-bar">AI가 답을 만드는 중에는 다른 대화를 고를 수 없습니다.</p>}
      <p className="result-count">
        저장된 대화 <strong>{result.totalCount}</strong>개
      </p>
      <table className="data-table conversation-table">
        <thead>
          <tr>
            <th>첫 질문</th>
            <th>질문 수</th>
            <th>마지막 대화</th>
            <th>삭제 예정</th>
            <th aria-label="삭제" />
          </tr>
        </thead>
        <tbody>
          {result.items.map((item) => {
            const left = daysUntilDelete(item.deleteScheduledAt)
            const current = agent.conversationId === item.conversationId
            return (
              <tr
                key={item.conversationId}
                className={`${current ? "is-current" : ""} ${agent.busy ? "is-disabled" : ""}`}
                tabIndex={0}
                aria-disabled={agent.busy}
                onClick={() => open(item)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") open(item)
                }}
              >
                <td className="col-name" title={item.firstQuestion}>
                  {item.firstQuestion}
                  {current && <span className="current-badge">패널에서 보는 중</span>}
                </td>
                <td className="col-number">{item.questionCount}개</td>
                <td>{item.lastMessageAt.slice(0, 16)}</td>
                <td className={left <= SOON_DAYS ? "is-soon" : undefined}>
                  {item.deleteScheduledAt} · {left}일 남음
                </td>
                <td className="col-action">
                  <button
                    type="button"
                    className="btn btn-outline btn-small btn-outline-danger"
                    aria-label={`'${item.firstQuestion}' 대화 삭제`}
                    onClick={(event) => {
                      event.stopPropagation()
                      void remove(item)
                    }}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {result.items.length === 0 && (
        <EmptyState title="저장된 대화가 없습니다." description="AI Agent 패널에서 나눈 대화가 여기에 저장됩니다." />
      )}
      {result.totalCount > 0 && <Pagination page={result.page} totalPages={result.totalPages} onPage={goPage} />}
    </section>
  )
}
