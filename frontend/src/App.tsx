import { useEffect } from "react"
import { Navigate, Route, Routes } from "react-router"
import { OverlayHost } from "@/components/common/OverlayHost"
import { AppLayout } from "@/components/layout/AppLayout"
import { LeaveGuardHost } from "@/components/routing/LeaveGuardHost"
import { RequireAuth } from "@/components/routing/RequireAuth"
import { DevPanel } from "@/devtools/DevPanel"
import { memberApi } from "@/mock/api/memberApi"
import { HOME_PATH, PATHS } from "@/routes/paths"
import { LoginScreen } from "@/screens/auth/LoginScreen"
import { PasswordFindScreen } from "@/screens/auth/PasswordFindScreen"
import { SignupScreen } from "@/screens/auth/SignupScreen"
import { CaseDetailScreen } from "@/screens/case/CaseDetailScreen"
import { CaseFormScreen } from "@/screens/case/CaseFormScreen"
import { CaseListScreen } from "@/screens/case/CaseListScreen"
import { FlowScreen } from "@/screens/flow/FlowScreen"
import { RiskScreen } from "@/screens/risk/RiskScreen"
import { MyPageScreen } from "@/screens/my/MyPageScreen"
import { PasswordChangeScreen } from "@/screens/my/PasswordChangeScreen"
import { WithdrawScreen } from "@/screens/my/WithdrawScreen"
import { ResourceDetailScreen } from "@/screens/resource/ResourceDetailScreen"
import { ResourceFormScreen } from "@/screens/resource/ResourceFormScreen"
import { ResourceListScreen } from "@/screens/resource/ResourceListScreen"
import { sessionStore, useSession } from "@/session/sessionStore"

export default function App() {
  const session = useSession()

  // 새로고침 후: 탭에 저장된 회원ID로 메뉴바 사용자 정보(0.1.1)를 다시 받아 로그인 상태를 복원
  useEffect(() => {
    if (session.status !== "restoring") return
    const result = memberApi.getMenuProfile()
    if (result.ok) sessionStore.completeRestore(result.data)
    else sessionStore.signOut()
  }, [session])

  return (
    <div className="app-shell">
      <div className="prototype-frame">
        {/* 저장하지 않은 내용이 있을 때 화면 이동을 막고 확인 창을 띄운다 */}
        <LeaveGuardHost />
        <Routes>
          {/* 로그인하지 않아도 볼 수 있는 화면 */}
          <Route path={PATHS.login} element={<LoginScreen />} />
          <Route path={PATHS.signup} element={<SignupScreen />} />
          <Route path={PATHS.passwordFind} element={<PasswordFindScreen />} />
          <Route path={PATHS.flow} element={<FlowScreen />} />

          {/* 로그인한 경우에만 볼 수 있는 화면 (헤더 + 메뉴바) */}
          <Route
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route path={PATHS.risk} element={<RiskScreen />} />
            <Route path={PATHS.resources} element={<ResourceListScreen />} />
            <Route path={PATHS.resourceNew} element={<ResourceFormScreen mode="new" />} />
            <Route path="/resources/:resourceId" element={<ResourceDetailScreen />} />
            <Route path="/resources/:resourceId/edit" element={<ResourceFormScreen mode="edit" />} />
            <Route path={PATHS.cases} element={<CaseListScreen />} />
            <Route path={PATHS.caseNew} element={<CaseFormScreen mode="new" />} />
            <Route path="/cases/:caseId" element={<CaseDetailScreen />} />
            <Route path="/cases/:caseId/edit" element={<CaseFormScreen mode="edit" />} />
            <Route path={PATHS.my} element={<MyPageScreen tab="info" />} />
            <Route path={PATHS.myResources} element={<MyPageScreen tab="resources" />} />
            <Route path={PATHS.myConversations} element={<MyPageScreen tab="conversations" />} />
            <Route path={PATHS.myPassword} element={<PasswordChangeScreen />} />
            <Route path={PATHS.myWithdraw} element={<WithdrawScreen />} />
          </Route>

          {/* 첫 접근(/)과 없는 주소: 첫 화면으로 (로그인 안 했으면 로그인 화면으로 이어짐) */}
          <Route path="*" element={<Navigate to={HOME_PATH} replace />} />
        </Routes>
        <OverlayHost />
      </div>
      <DevPanel />
    </div>
  )
}
