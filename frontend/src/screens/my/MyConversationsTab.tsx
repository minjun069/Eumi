import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router"
import { agentApi, conversationKeys, type ConversationListItem } from "@/api/agentApi"
import { errorMessage, isApiError } from "@/api/errors"
import { EmptyState } from "@/components/common/EmptyState"
import { Pagination } from "@/components/common/Pagination"
import { MyLoadFailed, MyLoading } from "@/screens/my/MyStatusViews"
import { agentStore, useAgentState } from "@/stores/agentStore"
import { confirmDialog } from "@/stores/confirmStore"
import { showToast } from "@/stores/toastStore"
import { daysUntil, formatDateTime } from "@/utils/datetime"

const PAGE_SIZE = 10
/** 삭제 예정일이 이 날 수 안이면 강조 */
const SOON_DAYS = 7

/**
 * 5.3 AI 대화 기록 (API-36 목록, API-37 대화 전체, API-38 삭제).
 * - 첫 질문(저장 당시 마스킹된 그대로)을 제목으로, 실행 종료 일시 최신순, 10개씩
 * - 행을 누르면 대화 전체를 받아 AI 패널에서 연다. 같은 대화로 이어서 질문한다 (패널의 메시지 표시를 그대로 쓴다)
 * - 마지막 질문에 끝 행이 없으면 패널이 열자마자 1초 조회를 이어 가고, 끝날 때까지 새 질문만 막는다 (FR-069)
 * - 삭제는 확인 창 뒤. 실행 중이어도 지울 수 있다(서버가 취소를 먼저 요청). 패널에 열린 대화면 패널을 새 대화로
 */
export function MyConversationsTab() {
  const [params, setParams] = useSearchParams()
  const parsedPage = Number(params.get("page") ?? "1")
  const page = Number.isSafeInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1
  const queryClient = useQueryClient()
  const agent = useAgentState()
  const busy = agent.running || agent.sending
  const [opening, setOpening] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: conversationKeys.list(page),
    queryFn: () => agentApi.listConversations(page, PAGE_SIZE),
    placeholderData: keepPreviousData,
  })
  const deleteConversation = useMutation({ mutationFn: agentApi.deleteConversation })

  // 패널에서 답이 끝나면 질문 수·실행 종료 일시·삭제 예정일이 바뀌므로 목록을 다시 받는다
  const wasBusy = useRef(busy)
  useEffect(() => {
    if (wasBusy.current && !busy) void queryClient.invalidateQueries({ queryKey: conversationKeys.all })
    wasBusy.current = busy
  }, [busy, queryClient])

  const refreshList = () => void queryClient.invalidateQueries({ queryKey: conversationKeys.all })

  const open = async (item: ConversationListItem) => {
    if (busy || opening) return
    setOpening(item.conversationId)
    try {
      const detail = await agentApi.getConversation(item.conversationId)
      if (!agentStore.loadConversation(detail)) {
        showToast("AI가 답을 만드는 중에는 다른 대화를 열 수 없습니다.", "error")
      }
    } catch (error) {
      // 다른 곳에서 지웠거나 보관 기간이 지났다
      if (isApiError(error) && error.status === 404) {
        showToast("대화를 찾을 수 없습니다. 목록을 새로 불러왔습니다.", "error")
        refreshList()
      } else {
        showToast(errorMessage(error), "error")
      }
    } finally {
      setOpening(null)
    }
  }

  const remove = async (item: ConversationListItem) => {
    if (deleteConversation.isPending) return
    const confirmed = await confirmDialog({
      title: "대화 기록을 삭제할까요?",
      message: `'${item.firstQuestion}' 대화의 질문 ${item.questionCount}개와 답변을 지웁니다. 되돌릴 수 없습니다.`,
      confirmLabel: "삭제",
      tone: "danger",
    })
    if (!confirmed) return
    try {
      await deleteConversation.mutateAsync(item.conversationId)
    } catch (error) {
      if (isApiError(error) && error.status === 404) {
        // 이미 지워졌다: 목록에서만 빼면 된다
        agentStore.forget(item.conversationId)
        showToast("이미 삭제된 대화입니다. 목록을 새로 불러왔습니다.", "error")
        refreshList()
        return
      }
      showToast(errorMessage(error), "error")
      return
    }
    agentStore.forget(item.conversationId)
    showToast("대화 기록을 삭제했습니다.")
    refreshList()
  }

  if (listQuery.isPending) return <MyLoading text="AI 대화 기록을 불러오는 중입니다." />
  if (listQuery.isError) {
    return (
      <MyLoadFailed
        title="AI 대화 기록을 불러오지 못했습니다."
        message={errorMessage(listQuery.error)}
        onRetry={() => void listQuery.refetch()}
      />
    )
  }

  const result = listQuery.data
  const goPage = (next: number) => setParams(next > 1 ? { page: String(next) } : {})

  return (
    <section className="detail-card my-conversations-card">
      <h2 className="card-title">AI 대화 기록</h2>
      <p className="field-hint my-card-hint">
        AI 패널에서 나눈 대화입니다. 누르면 패널에서 열어 이어서 질문할 수 있습니다. 마지막 대화일부터 3개월이 지나면
        자동으로 지웁니다.
      </p>
      {busy && <p className="notice-bar">AI가 답을 만드는 중에는 다른 대화를 열 수 없습니다. 삭제는 할 수 있습니다.</p>}
      <p className="result-count">
        저장된 대화 <strong>{result.totalCount}</strong>개
      </p>
      <div className={listQuery.isPlaceholderData ? "is-refreshing" : undefined}>
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
              const left = daysUntil(item.deleteScheduledAt)
              const current = agent.conversationId === item.conversationId
              const disabled = busy || opening !== null
              return (
                <tr
                  key={item.conversationId}
                  className={`${current ? "is-current" : ""} ${disabled ? "is-disabled" : ""}`}
                  tabIndex={0}
                  aria-disabled={disabled}
                  onClick={() => void open(item)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void open(item)
                  }}
                >
                  <td className="col-name" title={item.firstQuestion}>
                    {item.firstQuestion}
                    {current && <span className="current-badge">패널에서 보는 중</span>}
                  </td>
                  <td className="col-number">{item.questionCount}개</td>
                  <td>{formatDateTime(item.lastMessageAt)}</td>
                  <td className={left <= SOON_DAYS ? "is-soon" : undefined}>
                    {item.deleteScheduledAt} · {left}일 남음
                  </td>
                  <td className="col-action">
                    <button
                      type="button"
                      className="btn btn-outline btn-small btn-outline-danger"
                      aria-label={`'${item.firstQuestion}' 대화 삭제`}
                      disabled={deleteConversation.isPending}
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
      </div>
      {result.items.length === 0 && (
        <EmptyState title="저장된 대화가 없습니다." description="AI 패널에서 나눈 대화가 여기에 저장됩니다." />
      )}
      {/* 결과가 없으면 totalPages=0이라 페이지 번호를 그리지 않는다 */}
      {result.totalPages > 0 && <Pagination page={result.page} totalPages={result.totalPages} onPage={goPage} />}
    </section>
  )
}
