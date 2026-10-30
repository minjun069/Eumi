import { db } from "@/mock/db"
import { callApi, requireMember, serverNote, toMenuProfile } from "@/mock/api/core"
import { sessionStore } from "@/session/sessionStore"

// 회원 정보 (0.1.1 메뉴바, 담당자 고르기). 마이페이지(5.1·5.2) API는 myApi.ts

export const memberApi = {
  /**
   * 0.1.1 메뉴바 사용자 정보 조회
   * 메뉴바 상단의 소속 기관명·이름·직함과, 검색 조건 처음 값에 쓰는 관할 시도·시군구 코드.
   * 로그인 직후에는 로그인 응답의 값을 쓰고, 새로고침으로 화면을 다시 띄울 때 이 조회로 다시 받아 온다.
   */
  getMenuProfile() {
    return callApi({ featureId: "0.1.1", featureName: "메뉴바 사용자 정보 조회" }, {}, () => {
      const member = requireMember({ duringPasswordChange: true })
      const mustChangePassword = sessionStore.getMustChangePassword()
      if (mustChangePassword) serverNote("로그인 정보(토큰)에 '비밀번호 변경 필요'가 있어 함께 돌려줌 → 화면은 비밀번호 변경만 보여 줌")
      return toMenuProfile(member, mustChangePassword)
    })
  },

  /**
   * 소속 기관 회원 목록 조회: 담당자를 고를 때 (사례자 4.2.1, 복지자원 3.3.1).
   * 기능 ID는 부르는 화면의 기능으로 기록한다.
   */
  getOrgMembers(featureId: string) {
    return callApi({ featureId, featureName: "소속 기관 회원 목록 조회" }, {}, () => {
      const member = requireMember()
      serverNote("로그인한 회원과 같은 기관의 회원 중 탈퇴하지 않은 회원만 돌려줌")
      return db.members
        .filter((item) => item.orgId === member.orgId && item.withdrawnAt === null)
        .map(({ memberId, name, title }) => ({ memberId, name, title }))
    })
  },
}
