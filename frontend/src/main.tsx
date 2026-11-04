// 공통 스타일을 먼저 불러온다. 화면 파일이 import하는 화면 CSS가 그 뒤에 붙어야 같은 우선순위의 규칙에서 화면 쪽이 이긴다
import "./index.css"
import { QueryClientProvider } from "@tanstack/react-query"
import ReactDOM from "react-dom/client"
import { createBrowserRouter, RouterProvider } from "react-router"
import { queryClient } from "@/api/queryClient"
import { registerAuthHandlers } from "@/session/sessionActions"
import App from "./App"

// 다른 요청에서 받은 401·비밀번호 변경 필요를 로그인 상태에 반영한다
registerAuthHandlers()

// 화면 주소 연결: 저장하지 않은 내용 경고(뒤로 가기 막기, useBlocker)를 쓰려고 createBrowserRouter를 쓴다.
// 실제 화면 주소는 App.tsx의 <Routes>에서 정한다.
const router = createBrowserRouter([{ path: "*", element: <App /> }])

// React.StrictMode는 쓰지 않는다 (프로토타입에서 옮겨 오는 화면과 동작을 맞춘다).
ReactDOM.createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={queryClient}>
    <RouterProvider router={router} />
  </QueryClientProvider>,
)
