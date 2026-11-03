import { useEffect } from "react"
import { Navigate, Route, Routes } from "react-router"
import { OverlayHost } from "@/components/common/OverlayHost"
import { AppLayout } from "@/components/layout/AppLayout"
import { LeaveGuardHost } from "@/components/routing/LeaveGuardHost"
import { RequireAuth } from "@/components/routing/RequireAuth"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { LoginScreen } from "@/screens/auth/LoginScreen"
import { PlaceholderScreen } from "@/screens/placeholder/PlaceholderScreen"
import { PLACEHOLDERS } from "@/screens/placeholder/placeholders"
import { RiskScreen } from "@/screens/risk/RiskScreen"
import { restoreSession } from "@/session/sessionActions"
import { useSession } from "@/session/sessionStore"

// 화면 주소 목록. 아직 만들지 않은 화면은 '준비 중'(PlaceholderScreen)으로 둔다.
// 페이지를 옮겨 올 때 해당 줄의 element만 실제 화면으로 바꾼다.

export default function App() {
  const session = useSession()

  // 앱을 열거나 새로고침하면 서버 세션으로 로그인 상태를 복원한다 (API-01)
  useEffect(() => {
    if (session.status === "restoring") void restoreSession()
  }, [session.status])

  return (
    <div className="app-shell">
      <div className="app-frame">
        {/* 저장하지 않은 내용이 있을 때 화면 이동을 막고 확인 창을 띄운다 */}
        <LeaveGuardHost />
        <Routes>
          {/* 로그인하지 않아도 볼 수 있는 화면 */}
          <Route path={PATHS.login} element={<LoginScreen />} />
          <Route path={PATHS.signup} element={<PlaceholderScreen spec={PLACEHOLDERS.signup} fullFrame />} />
          <Route path={PATHS.passwordFind} element={<PlaceholderScreen spec={PLACEHOLDERS.passwordFind} fullFrame />} />

          {/* 로그인한 경우에만 볼 수 있는 화면 (헤더 + 메뉴바) */}
          <Route
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route path={PATHS.risk} element={<RiskScreen />} />
            <Route path={PATHS.resources} element={<PlaceholderScreen spec={PLACEHOLDERS.resources} />} />
            <Route path={PATHS.resourceNew} element={<PlaceholderScreen spec={PLACEHOLDERS.resourceNew} />} />
            <Route path="/resources/:resourceId" element={<PlaceholderScreen spec={PLACEHOLDERS.resourceDetail} />} />
            <Route path="/resources/:resourceId/edit" element={<PlaceholderScreen spec={PLACEHOLDERS.resourceEdit} />} />
            <Route path={PATHS.cases} element={<PlaceholderScreen spec={PLACEHOLDERS.cases} />} />
            <Route path={PATHS.caseNew} element={<PlaceholderScreen spec={PLACEHOLDERS.caseNew} />} />
            <Route path="/cases/:caseId" element={<PlaceholderScreen spec={PLACEHOLDERS.caseDetail} />} />
            <Route path="/cases/:caseId/edit" element={<PlaceholderScreen spec={PLACEHOLDERS.caseEdit} />} />
            <Route path={PATHS.my} element={<PlaceholderScreen spec={PLACEHOLDERS.my} />} />
            <Route path={PATHS.myResources} element={<PlaceholderScreen spec={PLACEHOLDERS.myResources} />} />
            <Route path={PATHS.myConversations} element={<PlaceholderScreen spec={PLACEHOLDERS.myConversations} />} />
            <Route path={PATHS.myPassword} element={<PlaceholderScreen spec={PLACEHOLDERS.myPassword} />} />
            <Route path={PATHS.myWithdraw} element={<PlaceholderScreen spec={PLACEHOLDERS.myWithdraw} />} />
          </Route>

          {/* 첫 접근(/)과 없는 주소: 첫 화면으로 (로그인 안 했으면 로그인 화면으로 이어짐) */}
          <Route path="*" element={<Navigate to={HOME_PATH} replace />} />
        </Routes>
        <OverlayHost />
      </div>
    </div>
  )
}
