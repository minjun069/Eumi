import { useLocation, useNavigate } from "react-router"
import { addLogNote } from "@/devtools/apiLogStore"
import { devAuth } from "@/devtools/devAuth"
import { db } from "@/mock/db"
import { HOME_PATH, PATHS, PUBLIC_PATHS } from "@/routes/paths"
import { sessionStore, useSession } from "@/session/sessionStore"
import { leaveGuard } from "@/stores/leaveGuardStore"

/**
 * 상황 전환 도구 (개발용).
 * 로그인 사용자를 비밀번호 확인 없이 바로 바꿔 담당자/비담당자 화면을 비교한다.
 * API 호출이 아니므로 API 기록에는 '※' 표시로만 남긴다.
 */
export function ScenarioSwitcher() {
  const session = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const currentValue =
    session.status === "anonymous" ? "" : String(session.memberId)

  const groups = db.organizations
    .map((org) => ({
      org,
      members: db.members.filter(
        (member) => member.orgId === org.orgId && member.withdrawnAt === null,
      ),
    }))
    .filter((group) => group.members.length > 0)

  const change = (value: string) => {
    // 개발용 바로 바꾸기라 '저장하지 않은 내용' 경고 없이 바꾼다
    leaveGuard.release()
    if (value === "") {
      sessionStore.signOut()
      addLogNote("상황 전환: 로그아웃 상태로 바꿈")
      navigate(PATHS.login)
      return
    }
    if (!devAuth.switchMember(Number(value))) return
    if (PUBLIC_PATHS.includes(location.pathname)) navigate(HOME_PATH)
  }

  return (
    <section className="dev-section">
      <h2 className="dev-title">상황 전환</h2>
      <label className="dev-field">
        <span>로그인 사용자</span>
        <select
          value={currentValue}
          onChange={(event) => change(event.target.value)}
        >
          <option value="">로그인 안 함</option>
          {groups.map(({ org, members }) => (
            <optgroup key={org.orgId} label={org.orgName}>
              {members.map((member) => (
                <option key={member.memberId} value={member.memberId}>
                  {member.name}
                  {member.title ? ` · ${member.title}` : ""}
                  {member.tempPassword ? " (임시 비밀번호 발급됨)" : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <p className="dev-hint">
        비밀번호 확인 없이 바로 바뀝니다. 지금 보고 있는 화면은 바뀐 사용자로
        다시 조회됩니다.
      </p>
    </section>
  )
}
