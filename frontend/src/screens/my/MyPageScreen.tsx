import { NavLink } from "react-router"
import { PATHS } from "@/routes/paths"
import { MyConversationsTab } from "@/screens/my/MyConversationsTab"
import { MyInfoTab } from "@/screens/my/MyInfoTab"
import { MyResourcesTab } from "@/screens/my/MyResourcesTab"

const TABS = [
  { key: "info", label: "내 정보", to: PATHS.my },
  { key: "resources", label: "담당 복지자원", to: PATHS.myResources },
  { key: "conversations", label: "AI 대화 기록", to: PATHS.myConversations },
] as const

export type MyTab = (typeof TABS)[number]["key"]

/**
 * 5. 마이페이지 (M1-A): 탭 3개 — 5.1 내 정보 관리 / 5.2 담당 복지자원 관리 / 5.3 AI 대화 기록.
 * 탭마다 주소가 있어 새로고침·뒤로 가기에도 같은 탭이 열린다. 비밀번호 변경·회원 탈퇴는 별도 화면
 */
export function MyPageScreen({ tab }: { tab: MyTab }) {
  return (
    <section className="screen my-page">
      <div className="page-heading">
        <div>
          <h1 className="page-title">마이페이지</h1>
          <p className="page-desc">내 정보와 담당 복지자원, AI 대화 기록을 관리합니다.</p>
        </div>
      </div>
      <nav className="my-tabs" aria-label="마이페이지 메뉴">
        {TABS.map((item) => (
          <NavLink
            key={item.key}
            to={item.to}
            end
            className={({ isActive }) => `my-tab ${isActive ? "is-active" : ""}`}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      {tab === "info" && <MyInfoTab />}
      {tab === "resources" && <MyResourcesTab />}
      {tab === "conversations" && <MyConversationsTab />}
    </section>
  )
}
