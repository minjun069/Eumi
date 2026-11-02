import { Outlet } from "react-router"
import { Header } from "@/components/layout/Header"
import { Sidebar } from "@/components/layout/Sidebar"
import { useSession } from "@/session/sessionStore"

/** 로그인 후 화면의 공통 틀: 헤더 + 좌측 메뉴바 + 본문 (AI Agent 패널은 AI 패널 작업에서 붙인다) */
export function AppLayout() {
  const session = useSession()
  if (session.status !== "authenticated") return null

  return (
    <>
      <Header />
      <Sidebar profile={session.profile} />
      {/* 로그인 사용자가 바뀌면 본문을 다시 그려 화면 데이터를 새로 조회하게 한다 */}
      <main className="workspace" key={session.memberId}>
        <Outlet />
      </main>
    </>
  )
}
