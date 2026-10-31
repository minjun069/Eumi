import { isKept } from "@/mock/agent/retention"
import { isTempPasswordValid } from "@/mock/api/authApi"
import { lastRecordedAtOf } from "@/mock/api/caseApi"
import { ApiError, callApi, requireMember, serverNote } from "@/mock/api/core"
import { toResourceListItem, type ResourceListItem } from "@/mock/api/resourceApi"
import { db } from "@/mock/db"
import { sessionStore } from "@/session/sessionStore"
import type { AgeGroup, Member } from "@/types/domain"
import { ageGroupOf, ageOn } from "@/utils/age"
import { todayString } from "@/utils/datetime"
import { isValidPassword, isValidPhone } from "@/utils/validation"

// 5. MY 마이페이지
// - 5.1.1 내 정보 조회, 5.1.2 내 정보 수정(직함·전화번호), 5.1.3 비밀번호 변경, 5.1.4 탈퇴 안내 조회·회원 탈퇴
// - 5.2.1 담당 복지자원 목록 조회
// (5.3.1 AI 대화 기록은 agentApi.ts)

export const CURRENT_PASSWORD_MISMATCH_MESSAGE = "현재 비밀번호가 일치하지 않습니다."
export const WITHDRAW_PASSWORD_MISMATCH_MESSAGE = "비밀번호가 일치하지 않습니다."
export const WITHDRAW_NO_SUCCESSOR_MESSAGE = "넘겨받을 회원이 없어 탈퇴할 수 없습니다."
export const WITHDRAW_CASES_CHANGED_MESSAGE = "넘길 사례자가 바뀌었습니다. 다시 확인한 뒤 탈퇴해 주세요."
export const WITHDRAW_SUCCESSOR_INVALID_MESSAGE = "넘겨받을 담당자를 다시 골라 주세요."

export type MyInfo = {
  name: string
  email: string
  orgName: string
  /** 관할지역 (예: 서울특별시 강남구) */
  jurisdictionName: string
  title: string | null
  phone: string | null
}

export type MyInfoUpdateRequest = {
  title: string | null
  phone: string | null
}

export type PasswordChangeRequest = {
  currentPassword: string
  newPassword: string
}

export type SoleCaseItem = {
  caseId: number
  managementNo: string
  name: string
  ageGroup: AgeGroup
  dongName: string
  lastRecordedAt: string | null
}

export type SuccessorItem = {
  memberId: number
  name: string
  title: string | null
}

export type WithdrawalInfo = {
  /** 내가 유일한 담당자인 사례자 → 탈퇴 전에 넘겨야 함 */
  soleCases: SoleCaseItem[]
  /** 공동 담당 사례자 수 → 내 담당자 지정만 지움 */
  sharedCaseCount: number
  /** 넘겨받을 수 있는 회원 (같은 기관, 탈퇴하지 않은 다른 회원) */
  successors: SuccessorItem[]
  /** 담당 복지자원 수 → 담당자가 '퇴사자'로 표시됨 */
  resourceCount: number
  /** AI 대화 기록 수 → 모두 지움 */
  conversationCount: number
}

export type WithdrawRequest = {
  /** 확인 창에서 다시 입력한 비밀번호 (M7-B, 명세 추가) */
  password: string
  /** 유일 담당 사례자마다 넘겨받을 담당자 (M6-A) */
  transfers: { caseId: number; newManagerMemberId: number }[]
}

export type MyResourcesResponse = {
  totalCount: number
  items: ResourceListItem[]
}

function toMyInfo(member: Member): MyInfo {
  const org = db.organizations.find((item) => item.orgId === member.orgId)
  const sigungu = db.sigungus.find((item) => item.sigunguCode === org?.jurisdictionSigunguCode)
  const sido = db.sidos.find((item) => item.sidoCode === sigungu?.sidoCode)
  return {
    name: member.name,
    email: member.email,
    orgName: org?.orgName ?? "(알 수 없는 기관)",
    jurisdictionName: [sido?.sidoName, sigungu?.sigunguName].filter(Boolean).join(" "),
    title: member.title,
    phone: member.phone,
  }
}

/** 기존 비밀번호 또는 24시간 안의 임시 비밀번호와 같은지 (M4-A) */
function matchesPassword(member: Member, password: string): boolean {
  return member.password === password || (member.tempPassword === password && isTempPasswordValid(member))
}

/** 내가 담당자인 사례자: 유일 담당 / 공동 담당 */
function myCases(member: Member) {
  const caseIds = db.caseManagers.filter((item) => item.memberId === member.memberId).map((item) => item.caseId)
  const records = db.cases.filter((item) => caseIds.includes(item.caseId))
  const managerCount = (caseId: number) => db.caseManagers.filter((item) => item.caseId === caseId).length
  return {
    sole: records.filter((item) => managerCount(item.caseId) === 1),
    shared: records.filter((item) => managerCount(item.caseId) > 1),
  }
}

function successorsOf(member: Member): SuccessorItem[] {
  return db.members
    .filter((item) => item.orgId === member.orgId && item.withdrawnAt === null && item.memberId !== member.memberId)
    .map(({ memberId, name, title }) => ({ memberId, name, title }))
}

function myLiveResources(member: Member) {
  return db.resources.filter((item) => item.managerMemberId === member.memberId && item.deletedAt === null)
}

export const myApi = {
  /** 5.1.1 내 정보 조회 (비밀번호 제외) */
  getMyInfo() {
    return callApi({ featureId: "5.1.1", featureName: "내 정보 조회" }, {}, () => toMyInfo(requireMember()))
  },

  /** 5.1.2 내 정보 수정: 직함·전화번호만 (비밀번호는 5.1.3) */
  updateMyInfo(request: MyInfoUpdateRequest) {
    return callApi({ featureId: "5.1.2", featureName: "내 정보 수정" }, request, (input): MyInfo => {
      const member = requireMember()
      const title = input.title?.trim() || null
      const phone = input.phone?.trim() || null
      if (phone !== null && !isValidPhone(phone)) throw new ApiError("전화번호 형식이 올바르지 않습니다.")
      member.title = title
      member.phone = phone
      serverNote("직함·전화번호만 바꿈 (이름·이메일·소속기관·관할지역은 바꿀 수 없음). 빈 값은 비움(null)")
      serverNote("바뀐 직함은 메뉴바(0.1.1)·담당자 표시(복지자원·사례자)에도 바로 반영됨")
      return toMyInfo(member)
    })
  },

  /**
   * 5.1.3 비밀번호 변경: 현재 비밀번호(기존 또는 임시)를 확인한 뒤 새 비밀번호로.
   * 임시 비밀번호로 로그인해 '비밀번호 변경 필요'인 동안에도 부를 수 있다 (M3-A)
   */
  changePassword(request: PasswordChangeRequest) {
    return callApi({ featureId: "5.1.3", featureName: "비밀번호 변경" }, request, (input) => {
      const member = requireMember({ duringPasswordChange: true })
      if (!matchesPassword(member, input.currentPassword)) throw new ApiError(CURRENT_PASSWORD_MISMATCH_MESSAGE)
      if (!isValidPassword(input.newPassword)) throw new ApiError("새 비밀번호가 규칙에 맞지 않습니다.")
      serverNote("현재 비밀번호는 기존 비밀번호 또는 24시간 안의 임시 비밀번호와 비교함 (M4-A). 새 비밀번호 규칙도 다시 확인")
      member.password = input.newPassword
      serverNote("새 비밀번호를 암호화해 저장함")
      if (member.tempPassword !== null) {
        member.tempPassword = null
        member.tempPasswordIssuedAt = null
        serverNote("발급되어 있던 임시 비밀번호를 지움")
      }
      if (sessionStore.getMustChangePassword()) {
        serverNote("로그인 정보(토큰)를 '비밀번호 변경 필요' 없이 다시 발급함 → 다른 화면·API를 쓸 수 있음. 로그인은 유지 (M5-A)")
      } else {
        serverNote("로그인은 유지 (M5-A)")
      }
      return undefined
    })
  },

  /** 5.1.4 탈퇴 안내 조회: 탈퇴하면 처리되는 데이터와 넘겨야 할 사례자 */
  getWithdrawalInfo() {
    return callApi({ featureId: "5.1.4", featureName: "탈퇴 안내 조회" }, {}, (): WithdrawalInfo => {
      const member = requireMember()
      const { sole, shared } = myCases(member)
      const today = new Date()
      const successors = successorsOf(member)
      serverNote("유일 담당 사례자 = 담당자가 나 한 명뿐인 사례자. 넘겨받을 회원 = 같은 기관의 탈퇴하지 않은 다른 회원")
      if (sole.length > 0 && successors.length === 0) serverNote("넘겨받을 회원이 없어 탈퇴할 수 없는 상태")
      return {
        soleCases: sole.map((record) => ({
          caseId: record.caseId,
          managementNo: record.managementNo,
          name: record.name,
          ageGroup: ageGroupOf(ageOn(record.birthDate, today)),
          dongName: db.dongs.find((item) => item.dongCode === record.dongCode)?.dongName ?? "",
          lastRecordedAt: lastRecordedAtOf(record.caseId),
        })),
        sharedCaseCount: shared.length,
        successors,
        resourceCount: myLiveResources(member).length,
        conversationCount: db.agentConversations.filter((item) => item.memberId === member.memberId && isKept(item)).length,
      }
    })
  },

  /**
   * 5.1.4 회원 탈퇴: 비밀번호 확인(M7-B) → 유일 담당 사례자 넘기기(M6-A) → 공동 담당 지정 지움 →
   * AI 대화 기록 전체 삭제 → 회원 soft delete. 담당 복지자원은 '퇴사자'로 표시된다.
   */
  withdraw(request: WithdrawRequest) {
    return callApi({ featureId: "5.1.4", featureName: "회원 탈퇴" }, request, (input) => {
      const member = requireMember()
      if (!matchesPassword(member, input.password)) throw new ApiError(WITHDRAW_PASSWORD_MISMATCH_MESSAGE)
      serverNote("비밀번호를 다시 확인함 (M7-B, 명세 추가)")

      const { sole, shared } = myCases(member)
      const successors = successorsOf(member)
      if (sole.length > 0 && successors.length === 0) throw new ApiError(WITHDRAW_NO_SUCCESSOR_MESSAGE)
      const soleIds = sole.map((item) => item.caseId).sort((a, b) => a - b)
      const transferIds = input.transfers.map((item) => item.caseId).sort((a, b) => a - b)
      if (soleIds.join() !== transferIds.join()) {
        serverNote(`지금 유일 담당 사례자(${soleIds.length}명)와 보낸 넘기기 목록(${transferIds.length}명)이 달라 탈퇴하지 않음`)
        throw new ApiError(WITHDRAW_CASES_CHANGED_MESSAGE)
      }
      const successorIds = successors.map((item) => item.memberId)
      if (input.transfers.some((item) => !successorIds.includes(item.newManagerMemberId))) {
        serverNote("넘겨받을 담당자가 같은 기관의 탈퇴하지 않은 다른 회원이 아님")
        throw new ApiError(WITHDRAW_SUCCESSOR_INVALID_MESSAGE)
      }

      // 여기부터 한 번에 처리 (하나라도 실패하면 모두 되돌림)
      for (const transfer of input.transfers) {
        db.caseManagers.push({ caseId: transfer.caseId, memberId: transfer.newManagerMemberId })
      }
      db.caseManagers = db.caseManagers.filter((item) => item.memberId !== member.memberId)
      const conversationIds = db.agentConversations
        .filter((item) => item.memberId === member.memberId)
        .map((item) => item.conversationId)
      db.agentTurns = db.agentTurns.filter((item) => !conversationIds.includes(item.conversationId))
      db.agentConversations = db.agentConversations.filter((item) => item.memberId !== member.memberId)
      member.withdrawnAt = todayString()
      member.tempPassword = null
      member.tempPasswordIssuedAt = null

      if (input.transfers.length > 0) {
        const byManager = new Map<string, number>()
        input.transfers.forEach((item) => {
          const name = db.members.find((candidate) => candidate.memberId === item.newManagerMemberId)?.name ?? ""
          byManager.set(name, (byManager.get(name) ?? 0) + 1)
        })
        serverNote(
          `유일 담당 사례자 ${input.transfers.length}명을 넘김 (${[...byManager].map(([name, count]) => `${name} ${count}명`).join(", ")})`,
        )
      }
      if (shared.length > 0) serverNote(`공동 담당 사례자 ${shared.length}명에서 내 담당자 지정만 지움 (다른 담당자는 그대로)`)
      serverNote(
        `담당 복지자원 ${myLiveResources(member).length}개는 담당자ID를 그대로 두고, 회원의 탈퇴일로 '퇴사자'로 표시함 → 조회만 가능`,
      )
      serverNote(`AI 대화 기록 ${conversationIds.length}개(보관 기간이 지난 것 포함)와 질문·답변을 모두 지움`)
      serverNote("회원 정보는 탈퇴일을 기록해 soft delete (같은 이메일로 다시 가입할 수 없음, 로그인 불가)")
      serverNote("로그인 정보(토큰)를 끊음 → 화면은 로그인 화면으로")
      return undefined
    })
  },

  /** 5.2.1 담당 복지자원 목록 조회: 내가 담당자인 자원 (M8-A: 진행 중 먼저·마감일 순, 페이지 없이 전체) */
  getMyResources() {
    return callApi({ featureId: "5.2.1", featureName: "담당 복지자원 목록 조회" }, {}, (): MyResourcesResponse => {
      const member = requireMember()
      const today = todayString()
      serverNote("내가 담당자인 자원만 (삭제한 자원 제외). 진행 중 먼저, 그 안에서 운영 종료일이 이른 순. 페이지 없이 전체")
      const items = myLiveResources(member)
        .map((resource) => toResourceListItem(resource, today))
        .sort(
          (a, b) =>
            Number(a.status === "종료") - Number(b.status === "종료") ||
            a.periodEnd.localeCompare(b.periodEnd) ||
            a.resourceId - b.resourceId,
        )
      return { totalCount: items.length, items }
    })
  },
}
