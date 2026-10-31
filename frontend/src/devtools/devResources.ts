import { addLogNote } from "@/devtools/apiLogStore"
import { db } from "@/mock/db"
import { todayString } from "@/utils/datetime"

// 개발용: 복지자원 화면의 '다른 사람이 한 일' 재현.
// API 호출이 아니라 db를 직접 바꾸고, 기록에는 '※'로만 남긴다. 화면은 바로 바뀌지 않고,
// 그다음 삭제·조회 등을 하면 서버 응답으로 바뀐 상황을 알게 된다.

export const devResources = {
  /** 자원명으로 복지자원ID 찾기 (예시 데이터 바로 열기용, 삭제한 자원 포함) */
  findResourceId(resourceName: string): number | undefined {
    return db.resources.find((item) => item.resourceName === resourceName)?.resourceId
  },

  /** 다른 사람이 이 자원을 삭제함 (soft delete) */
  deleteResource(resourceId: number) {
    const resource = db.resources.find((item) => item.resourceId === resourceId)
    if (!resource || resource.deletedAt !== null) return
    resource.deletedAt = todayString()
    addLogNote(`다른 사람이 복지자원 '${resource.resourceName}'을(를) 삭제한 상황으로 바꿈`)
  },

  /** 담당자가 같은 기관의 다른 회원으로 바뀜 */
  changeManager(resourceId: number) {
    const resource = db.resources.find((item) => item.resourceId === resourceId)
    if (!resource) return
    const next = db.members.find(
      (member) =>
        member.orgId === resource.orgId && member.memberId !== resource.managerMemberId && member.withdrawnAt === null,
    )
    if (!next) {
      addLogNote(`복지자원 '${resource.resourceName}': 같은 기관에 담당자를 넘길 다른 회원이 없음`)
      return
    }
    resource.managerMemberId = next.memberId
    addLogNote(`복지자원 '${resource.resourceName}'의 담당자가 ${next.name}(으)로 바뀐 상황으로 바꿈`)
  },
}
