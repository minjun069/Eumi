import type { CaseDetail, CaseInput } from "@/mock/api/caseApi"
import type { Gender } from "@/types/domain"
import { isValidDateString, todayString } from "@/utils/datetime"

// 사례자 등록·수정 화면(4.2.1)의 입력값과 화면에서 하는 입력 확인

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

type Example = Omit<CaseForm, "managerMemberIds" | "firstRegisteredAt"> & { firstRegisteredAt?: string }

function region(dongCode: string) {
  return { sidoCode: dongCode.slice(0, 2), sigunguCode: dongCode.slice(0, 5), dongCode }
}

const EXAMPLES = {
  gangnamSenior: { name: "배정자", birthDate: "1950-08-15", gender: "여", ...region("1168066000") },
  gangnamYouth: { name: "김도윤", birthDate: "1998-03-21", gender: "남", ...region("1168065000") },
  lastYear: {
    name: "강태호",
    birthDate: "1957-06-30",
    gender: "남",
    ...region("1168075000"),
    firstRegisteredAt: "2025-12-15",
  },
  duplicateMine: { name: "조말순", birthDate: "1938-12-12", gender: "여", ...region("1168066000") },
  duplicateOthers: { name: "송미라", birthDate: "1975-10-30", gender: "여", ...region("1168056500") },
} satisfies Record<string, Example>

function fromExample(example: Example, managerMemberIds: number[]): CaseForm {
  return { ...example, firstRegisteredAt: example.firstRegisteredAt ?? todayString(), managerMemberIds }
}

/** 등록 화면을 열 때 미리 채우는 예시 (담당자: 등록하는 본인) */
export function exampleCaseForm(myMemberId: number): CaseForm {
  return fromExample(EXAMPLES.gangnamSenior, [myMemberId])
}

/** 등록 화면 개발용 '예외 상황'의 채우기 버튼 (담당자는 바꾸지 않는다) */
export const CASE_NEW_FILLS: { label: string; patch: () => Partial<CaseForm> }[] = [
  { label: "예시: 강남 노년 (배정자)", patch: () => fromExample(EXAMPLES.gangnamSenior, []) },
  { label: "예시: 강남 청년 (김도윤)", patch: () => fromExample(EXAMPLES.gangnamYouth, []) },
  { label: "예시: 작년 날짜로 등록", patch: () => fromExample(EXAMPLES.lastYear, []) },
  { label: "중복: 내 담당 조말순과 같음", patch: () => fromExample(EXAMPLES.duplicateMine, []) },
  { label: "중복 아님: 다른 직원 담당 송미라", patch: () => fromExample(EXAMPLES.duplicateOthers, []) },
  {
    label: "빈칸 채우기",
    patch: () => ({
      name: "",
      birthDate: "",
      gender: "",
      sidoCode: "11",
      sigunguCode: "11680",
      dongCode: null,
      firstRegisteredAt: "",
    }),
  },
  { label: "미래 날짜 채우기", patch: () => ({ birthDate: "2030-01-01", firstRegisteredAt: "2030-01-01" }) },
]

/** 채우기 버튼의 patch에서 담당자는 빼고 적용 */
export function applyFill(form: CaseForm, patch: Partial<CaseForm>): CaseForm {
  const { managerMemberIds: _ignored, ...rest } = patch
  return { ...form, ...rest }
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
  if (!form.name.trim()) errors.name = "이름을 입력하세요."
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
