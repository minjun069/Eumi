import type { CaseDetail, CaseInput, Gender } from "@/api/caseApi"
import type { MenuProfile } from "@/api/types"
import { isValidDateString, todayString } from "@/utils/datetime"

// 사례자 등록·수정 화면(4.2.1)의 입력값과 화면에서 하는 입력 확인 (서버도 같은 조건을 다시 검사한다)

/** CaseInput.name maxLength */
export const CASE_NAME_MAX = 100

export type CaseForm = {
  name: string
  birthDate: string
  gender: Gender | ""
  sidoCode: string | null
  sigunguCode: string | null
  dongCode: string | null
  firstRegisteredAt: string
  managerMemberIds: number[]
}

export type CaseFormField = "name" | "birthDate" | "gender" | "region" | "firstRegisteredAt" | "managers"
export type CaseFormErrors = Partial<Record<CaseFormField, string>>

/** 서버 fieldErrors의 field → 입력칸 */
export const CASE_FORM_FIELDS: Record<string, CaseFormField> = {
  name: "name",
  birthDate: "birthDate",
  gender: "gender",
  dongCode: "region",
  firstRegisteredAt: "firstRegisteredAt",
  managerMemberIds: "managers",
}

/** 등록 화면의 처음 값: 지역은 소속 기관 관할 시군구, 최초 등록일은 오늘, 담당자는 등록하는 본인 */
export function emptyCaseForm(profile: MenuProfile): CaseForm {
  return {
    name: "",
    birthDate: "",
    gender: "",
    sidoCode: profile.jurisdictionSidoCode || null,
    sigunguCode: profile.jurisdictionSigunguCode || null,
    dongCode: null,
    firstRegisteredAt: todayString(),
    managerMemberIds: [profile.memberId],
  }
}

export function formFromDetail(detail: CaseDetail): CaseForm {
  return {
    name: detail.name,
    birthDate: detail.birthDate,
    gender: detail.gender,
    sidoCode: detail.sidoCode,
    sigunguCode: detail.sigunguCode,
    dongCode: detail.dongCode,
    firstRegisteredAt: detail.firstRegisteredAt,
    managerMemberIds: detail.managers.map((item) => item.memberId),
  }
}

function dateError(label: string, value: string): string | undefined {
  if (!value) return `${label}을 입력하세요.`
  if (!isValidDateString(value)) return "올바른 날짜가 아닙니다."
  if (value > todayString()) return "오늘 이후 날짜는 입력할 수 없습니다."
  return undefined
}

export function validateCaseForm(form: CaseForm): CaseFormErrors {
  const errors: CaseFormErrors = {}
  const name = form.name.trim()
  if (!name) errors.name = "이름을 입력하세요."
  else if (name.length > CASE_NAME_MAX) errors.name = `${CASE_NAME_MAX}자 이내로 입력하세요.`
  const birth = dateError("생년월일", form.birthDate)
  if (birth) errors.birthDate = birth
  if (!form.gender) errors.gender = "성별을 선택하세요."
  if (!form.dongCode) errors.region = "지역을 읍면동까지 선택하세요."
  const registered = dateError("최초 등록일", form.firstRegisteredAt)
  if (registered) errors.firstRegisteredAt = registered
  if (form.managerMemberIds.length === 0) errors.managers = "담당자를 한 명 이상 선택하세요."
  return errors
}

/** 입력 확인을 통과한 값 → API 요청 */
export function toCaseInput(form: CaseForm): CaseInput {
  return {
    name: form.name.trim(),
    birthDate: form.birthDate,
    gender: form.gender as Gender,
    dongCode: form.dongCode ?? "",
    firstRegisteredAt: form.firstRegisteredAt,
    managerMemberIds: form.managerMemberIds,
  }
}

export function sameCaseForm(a: CaseForm, b: CaseForm): boolean {
  const normalize = (form: CaseForm) => ({
    ...form,
    managerMemberIds: [...form.managerMemberIds].sort((x, y) => x - y),
  })
  return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b))
}
