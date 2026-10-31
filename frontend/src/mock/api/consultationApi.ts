import { db } from "@/mock/db"
import { ApiError, callApi, requireMember, serverNote } from "@/mock/api/core"
import { requireCaseAccess } from "@/mock/api/caseApi"
import type { Consultation, ConsultationCategory } from "@/types/domain"
import { CATEGORY_ETC_MAX, CONSULTATION_CATEGORIES } from "@/utils/consultation"
import { isValidDateString, todayString } from "@/utils/datetime"

// 4.2.2 상담 이력 관리. 모든 API는 그 사례자의 담당자만 쓸 수 있다 (requireCaseAccess).

export const CONSULTATION_NOT_FOUND_MESSAGE = "상담 기록을 찾을 수 없습니다."

export type ConsultationListItem = {
  consultationId: number
  consultedAt: string
  purpose: string
  category: ConsultationCategory
  /** 분류가 '기타'일 때 직접 입력한 내용 */
  categoryEtc: string | null
  recorderName: string
}

export type ConsultationDetail = ConsultationListItem & {
  content: string
  recorderMemberId: number
}

/** 상담 등록·수정 요청 공통 */
export type ConsultationInput = {
  consultedAt: string
  purpose: string
  category: ConsultationCategory
  categoryEtc: string | null
  content: string
}

function recorderNameOf(memberId: number): string {
  return db.members.find((member) => member.memberId === memberId)?.name ?? "(알 수 없음)"
}

function toListItem(record: Consultation): ConsultationListItem {
  return {
    consultationId: record.consultationId,
    consultedAt: record.consultedAt,
    purpose: record.purpose,
    category: record.category,
    categoryEtc: record.categoryEtc,
    recorderName: recorderNameOf(record.recorderMemberId),
  }
}

function findConsultation(caseId: number, consultationId: number): Consultation {
  const record = db.consultations.find(
    (item) => item.consultationId === consultationId && item.caseId === caseId,
  )
  if (!record) throw new ApiError(CONSULTATION_NOT_FOUND_MESSAGE)
  return record
}

/** 서버에서도 하는 입력 확인 (화면에서 먼저 확인하므로 보통은 여기까지 오지 않는다) */
function validateInput(input: ConsultationInput): ConsultationInput {
  if (!isValidDateString(input.consultedAt)) throw new ApiError("상담 일자가 올바른 날짜가 아닙니다.")
  if (input.consultedAt > todayString()) throw new ApiError("상담 일자는 오늘 이후 날짜로 정할 수 없습니다.")
  const purpose = input.purpose.trim()
  if (!purpose) throw new ApiError("상담 목적을 입력하세요.")
  if (!CONSULTATION_CATEGORIES.includes(input.category)) throw new ApiError("상담 분류를 선택하세요.")
  let categoryEtc: string | null = null
  if (input.category === "기타") {
    categoryEtc = (input.categoryEtc ?? "").trim()
    if (!categoryEtc) throw new ApiError("'기타' 분류의 내용을 입력하세요.")
    if (categoryEtc.length > CATEGORY_ETC_MAX) {
      throw new ApiError(`'기타' 분류의 내용은 ${CATEGORY_ETC_MAX}자 이내로 입력하세요.`)
    }
  } else if (input.categoryEtc) {
    serverNote("분류가 '기타'가 아니라서 기타 내용은 저장하지 않음")
  }
  const content = input.content.trim()
  if (!content) throw new ApiError("상담 내용을 입력하세요.")
  return { ...input, purpose, categoryEtc, content }
}

/** 새 상담ID (삭제한 상담의 ID는 다시 쓰지 않고, 늦게 등록할수록 큰 값) */
let lastConsultationId = db.consultations.reduce((max, item) => Math.max(max, item.consultationId), 0)

export const consultationApi = {
  /** 4.2.2 사례자 상담 목록 조회: 상담 일자 최신순, 같은 날이면 나중에 등록한 것부터. 페이지 없이 전체(D11-A) */
  getConsultations(request: { caseId: number }) {
    return callApi(
      { featureId: "4.2.2", featureName: "상담 목록 조회" },
      request,
      ({ caseId }): ConsultationListItem[] => {
        requireCaseAccess(requireMember(), caseId)
        return db.consultations
          .filter((item) => item.caseId === caseId)
          .sort(
            (a, b) => b.consultedAt.localeCompare(a.consultedAt) || b.consultationId - a.consultationId,
          )
          .map(toListItem)
      },
    )
  },

  /** 4.2.2 상담 내용 조회: 상담 창을 열 때 (D3-B) */
  getConsultation(request: { caseId: number; consultationId: number }) {
    return callApi(
      { featureId: "4.2.2", featureName: "상담 내용 조회" },
      request,
      ({ caseId, consultationId }): ConsultationDetail => {
        requireCaseAccess(requireMember(), caseId)
        const record = findConsultation(caseId, consultationId)
        return { ...toListItem(record), content: record.content, recorderMemberId: record.recorderMemberId }
      },
    )
  },

  /** 4.2.2 사례자 상담 등록: 기록자는 등록한 회원 (D7-A) */
  createConsultation(request: ConsultationInput & { caseId: number }) {
    return callApi(
      { featureId: "4.2.2", featureName: "상담 등록" },
      request,
      ({ caseId, ...input }): { consultationId: number } => {
        const member = requireMember()
        requireCaseAccess(member, caseId)
        const valid = validateInput(input)
        lastConsultationId += 1
        db.consultations.push({ consultationId: lastConsultationId, caseId, ...valid, recorderMemberId: member.memberId })
        serverNote(`기록자를 등록한 회원(${member.name})으로 지정함`)
        return { consultationId: lastConsultationId }
      },
    )
  },

  /** 4.2.2 사례자 상담 수정: 그 사례자의 담당자 누구나 (D7-A). 기록자는 바꾸지 않는다 */
  updateConsultation(request: ConsultationInput & { caseId: number; consultationId: number }) {
    return callApi(
      { featureId: "4.2.2", featureName: "상담 수정" },
      request,
      ({ caseId, consultationId, ...input }) => {
        requireCaseAccess(requireMember(), caseId)
        const record = findConsultation(caseId, consultationId)
        Object.assign(record, validateInput(input))
        serverNote(`기록자는 처음 등록한 회원(${recorderNameOf(record.recorderMemberId)})으로 그대로 둠`)
      },
    )
  },

  /** 4.2.2 사례자 상담 삭제: 그 사례자의 담당자 누구나 */
  deleteConsultation(request: { caseId: number; consultationId: number }) {
    return callApi({ featureId: "4.2.2", featureName: "상담 삭제" }, request, ({ caseId, consultationId }) => {
      requireCaseAccess(requireMember(), caseId)
      const record = findConsultation(caseId, consultationId)
      db.consultations = db.consultations.filter((item) => item !== record)
    })
  },
}
