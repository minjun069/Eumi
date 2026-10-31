import { addLogNote } from "@/devtools/apiLogStore"
import { db } from "@/mock/db"
import { sessionStore } from "@/session/sessionStore"

// 개발용: 사례자 화면의 '다른 담당자가 한 일' 재현.
// 다른 담당자가 그사이 데이터를 바꾼 상황을 만든다 (API 호출이 아니라 db를 직접 바꾸고, 기록에는 '※'로만 남긴다).
// 화면은 바로 바뀌지 않는다. 그다음 저장·조회 등을 하면 서버 응답으로 바뀐 상황을 알게 된다.

export const devCases = {
  /** 이름으로 사례자ID 찾기 (예시 데이터 바로 열기용) */
  findCaseId(name: string): number | undefined {
    return db.cases.find((item) => item.name === name)?.caseId
  },

  /** 다른 담당자가 이 사례자를 삭제함 */
  deleteCase(caseId: number) {
    const record = db.cases.find((item) => item.caseId === caseId)
    if (!record) return
    db.cases = db.cases.filter((item) => item.caseId !== caseId)
    db.caseManagers = db.caseManagers.filter((item) => item.caseId !== caseId)
    db.consultations = db.consultations.filter((item) => item.caseId !== caseId)
    addLogNote(`다른 담당자가 사례자 '${record.name}'을(를) 삭제한 상황으로 바꿈`)
  },

  /** 다른 담당자가 로그인한 회원을 이 사례자의 담당자에서 뺌 (담당자가 나 혼자면 같은 기관의 다른 회원을 담당자로 남김) */
  removeMe(caseId: number) {
    const memberId = sessionStore.getMemberId()
    const record = db.cases.find((item) => item.caseId === caseId)
    if (!record || memberId === null) return
    const others = db.caseManagers.filter((item) => item.caseId === caseId && item.memberId !== memberId)
    if (others.length === 0) {
      const substitute = db.members.find(
        (member) => member.orgId === record.orgId && member.memberId !== memberId && member.withdrawnAt === null,
      )
      if (substitute) db.caseManagers.push({ caseId, memberId: substitute.memberId })
    }
    db.caseManagers = db.caseManagers.filter((item) => !(item.caseId === caseId && item.memberId === memberId))
    addLogNote(`다른 담당자가 로그인한 회원을 사례자 '${record.name}'의 담당자에서 뺀 상황으로 바꿈`)
  },

  /** 다른 담당자가 이 상담 기록을 삭제함 */
  deleteConsultation(consultationId: number) {
    const record = db.consultations.find((item) => item.consultationId === consultationId)
    if (!record) return
    db.consultations = db.consultations.filter((item) => item !== record)
    addLogNote(`다른 담당자가 상담 기록(${record.consultedAt} ${record.purpose})을 삭제한 상황으로 바꿈`)
  },
}
