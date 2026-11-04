import { api } from "@/api/http"
import type { operations } from "@/api/schema"
import type { Schemas, SuccessData } from "@/api/types"

// 사례자·상담 (본인이 담당자로 지정된 사례자만).
// 같은 기관 미담당은 403 FORBIDDEN, 다른 기관이거나 없는 사례자는 404 NOT_FOUND. 상담 API도 사례자 접근을 먼저 검사한다.

export type CaseSearchQuery = NonNullable<operations["caseApi_searchCases"]["parameters"]["query"]>
export type CaseSortKey = NonNullable<CaseSearchQuery["sort"]>
export type SortDirection = NonNullable<CaseSearchQuery["direction"]>
export type CasePage = SuccessData<"caseApi_searchCases_Success">
export type CaseListItem = Schemas["CaseListItem"]
export type CaseDetail = SuccessData<"caseApi_getCase_Success">
export type CaseInput = Schemas["CaseInput"]
export type CaseCreated = SuccessData<"caseApi_createCase_Success">
export type DuplicateCheckRequest = Schemas["DuplicateCheckRequest"]
export type DuplicateCheckData = SuccessData<"caseApi_checkDuplicate_Success">
export type Gender = CaseInput["gender"]
export type AgeGroup = CaseListItem["ageGroup"]

export type ConsultationListItem = Schemas["ConsultationListItem"]
export type ConsultationDetail = SuccessData<"consultationApi_getConsultation_Success">
export type ConsultationInput = Schemas["ConsultationInput"]
export type ConsultationCreated = SuccessData<"consultationApi_createConsultation_Success">
export type ConsultationCategory = ConsultationListItem["category"]

// 사례자 한 명의 정보·상담은 detail(caseId) 아래에 둔다. 상담을 바꾸면 그 아래를 함께 무효화해 최근 기록일도 다시 받는다
export const caseKeys = {
  all: ["cases"] as const,
  list: (query: CaseSearchQuery) => ["cases", "list", query] as const,
  detail: (caseId: number) => ["cases", "detail", caseId] as const,
  consultations: (caseId: number) => ["cases", "detail", caseId, "consultations"] as const,
  consultation: (caseId: number, consultationId: number) =>
    ["cases", "detail", caseId, "consultations", consultationId] as const,
}

const casePath = (caseId: number) => `/cases/${caseId}`
const consultationPath = (caseId: number, consultationId: number) =>
  `${casePath(caseId)}/consultations/${consultationId}`

export const caseApi = {
  /** API-19 GET /cases — 본인 담당 사례자. 범위를 넘는 page는 마지막 페이지로 보정해 돌려준다 */
  searchCases: (query: CaseSearchQuery) => api.get<CasePage>("/cases", { query }),

  /** API-20 GET /cases/{caseId} */
  getCase: (caseId: number) => api.get<CaseDetail>(casePath(caseId)),

  /** API-21 POST /cases/duplicate-check — 본인 담당 사례자 중 이름·생년월일이 같은 사례자 (경고용) */
  checkDuplicate: (body: DuplicateCheckRequest) => api.post<DuplicateCheckData>("/cases/duplicate-check", body),

  /** API-22 POST /cases — 관리번호는 서버가 발급. 등록한 회원은 서버가 담당자에 넣는다 */
  createCase: (input: CaseInput) => api.post<CaseCreated>("/cases", input),

  /** API-23 PUT /cases/{caseId} — 204 */
  updateCase: (caseId: number, input: CaseInput) => api.put<void>(casePath(caseId), input),

  /** API-24 DELETE /cases/{caseId} — 204. 담당자 연결·상담 기록도 함께 삭제된다 */
  deleteCase: (caseId: number) => api.delete<void>(casePath(caseId)),

  /** API-25 GET /cases/{caseId}/consultations — 상담 일자 최신순 */
  getConsultations: (caseId: number) =>
    api.get<ConsultationListItem[]>(`${casePath(caseId)}/consultations`),

  /** API-26 GET /cases/{caseId}/consultations/{consultationId} */
  getConsultation: (caseId: number, consultationId: number) =>
    api.get<ConsultationDetail>(consultationPath(caseId, consultationId)),

  /** API-27 POST /cases/{caseId}/consultations — 기록자는 로그인 회원으로 서버가 정한다 */
  createConsultation: (caseId: number, input: ConsultationInput) =>
    api.post<ConsultationCreated>(`${casePath(caseId)}/consultations`, input),

  /** API-28 PUT /cases/{caseId}/consultations/{consultationId} — 204. 최초 기록자는 바뀌지 않는다 */
  updateConsultation: (caseId: number, consultationId: number, input: ConsultationInput) =>
    api.put<void>(consultationPath(caseId, consultationId), input),

  /** API-29 DELETE /cases/{caseId}/consultations/{consultationId} — 204 */
  deleteConsultation: (caseId: number, consultationId: number) =>
    api.delete<void>(consultationPath(caseId, consultationId)),
}
