import type { NavigateFunction } from "react-router"
import { addLogNote } from "@/devtools/apiLogStore"
import { authApi, isTempPasswordValid } from "@/mock/api/authApi"
import { toMenuProfile } from "@/mock/api/core"
import { db } from "@/mock/db"
import { PATHS } from "@/routes/paths"
import { profileFromLogin } from "@/session/loginProfile"
import { sessionStore } from "@/session/sessionStore"
import { leaveGuard } from "@/stores/leaveGuardStore"

// 개발용: 로그인 사용자 바로 바꾸기, 임시 비밀번호로 로그인한 상태 만들기

const TEMP_EXAMPLE = { email: "jung.haneul@woori.or.kr", tempPassword: "TEMP-7Q2K" }

export const devAuth = {
  /** 비밀번호 확인 없이 로그인 사용자를 바꾼다 (API 기록에는 '※'로만 남김). 바꾸지 못하면 false */
  switchMember(memberId: number): boolean {
    const member = db.members.find((item) => item.memberId === memberId && item.withdrawnAt === null)
    if (!member) return false
    // 개발용 바로 바꾸기라 '저장하지 않은 내용' 경고 없이 바꾼다
    leaveGuard.release()
    const profile = toMenuProfile(member)
    sessionStore.signIn(profile)
    addLogNote(`상황 전환: 로그인 사용자를 ${member.name}(${profile.orgName})(으)로 바꿈`)
    return true
  },

  /**
   * 정하늘이 임시 비밀번호로 로그인한 상태를 만든다: 실제 '1.2.1 로그인'을 임시 비밀번호로 부르고 비밀번호 변경 화면으로.
   * 임시 비밀번호가 없거나 지났으면 다시 발급해 둔다.
   */
  enterTempLogin(navigate: NavigateFunction) {
    const member = db.members.find((item) => item.email === TEMP_EXAMPLE.email)
    if (!member) return
    if (member.tempPassword === null || !isTempPasswordValid(member)) {
      member.tempPassword = TEMP_EXAMPLE.tempPassword
      member.tempPasswordIssuedAt = Date.now() - 2 * 60 * 60 * 1000
      addLogNote(`개발용: 정하늘에게 임시 비밀번호 ${TEMP_EXAMPLE.tempPassword}를 다시 발급해 둠`)
    }
    leaveGuard.release()
    const result = authApi.login({ email: member.email, password: member.tempPassword ?? "" })
    if (!result.ok) return
    sessionStore.signIn(profileFromLogin(result.data))
    addLogNote("개발용: 정하늘이 임시 비밀번호로 로그인한 상태로 바꿈 → 비밀번호 변경 화면만 쓸 수 있음")
    navigate(PATHS.myPassword)
  },

  /** 지금 로그인한 회원에게 발급된 임시 비밀번호 (없거나 지났으면 null) */
  currentTempPassword(): string | null {
    const member = db.members.find((item) => item.memberId === sessionStore.getMemberId())
    return member && member.tempPassword !== null && isTempPasswordValid(member) ? member.tempPassword : null
  },
}
