import ReactDOM from "react-dom/client"
import { createBrowserRouter, RouterProvider } from "react-router"
import App from "./App"
import "./index.css"

// 화면 주소 연결: 저장하지 않은 내용 경고(뒤로 가기 막기, useBlocker)를 쓰려고 createBrowserRouter를 쓴다.
// 실제 화면 주소는 App.tsx의 <Routes>에서 정한다.
const router = createBrowserRouter([{ path: "*", element: <App /> }])

// React.StrictMode는 쓰지 않는다.
// 개발 모드의 StrictMode는 화면을 띄울 때 조회를 두 번 실행해서 API 기록이 중복으로 쌓인다.
ReactDOM.createRoot(document.getElementById("root")!).render(<RouterProvider router={router} />)
