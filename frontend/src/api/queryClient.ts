import { QueryClient } from "@tanstack/react-query"
import { isApiError } from "@/api/errors"

// 서버 데이터는 TanStack Query로, 입력 폼·모달·패널 개폐는 화면 로컬 상태로 관리한다.
// 로그아웃·사용자 전환 때 sessionStore.signOut()이 queryClient.clear()로 개인 데이터를 비운다.

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 4xx는 다시 보내도 결과가 같으므로 재시도하지 않는다. 통신 오류·5xx만 한 번 더 시도한다
      retry: (failureCount, error) =>
        failureCount < 1 && !(isApiError(error) && error.status >= 400 && error.status < 500),
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
    // 변경 요청은 자동으로 다시 보내지 않는다
    mutations: { retry: false },
  },
})
