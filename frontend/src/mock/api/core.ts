import { addApiLog } from "@/devtools/apiLogStore"
import { db } from "@/mock/db"
import { sessionStore } from "@/session/sessionStore"
import type { Member, MenuProfile } from "@/types/domain"

// API 흉내 계층의 공통 부분.
// 화면은 src/mock/api/*Api.ts의 함수만 호출하고, 각 함수는 callApi로 감싸져 있다.
// callApi는 요청을 처리한 뒤 결과를 API 기록에 남긴다. 함수 하나가 나중의 API 하나에 해당한다.
// URL·HTTP 메서드·상태 코드는 정하지 않는다(API 명세에서 정한다).

export type ApiMeta = {
  /** 기능명세의 기능 ID (예: "1.2.1") */
  featureId: string
  /** 기능명세의 기능 이름 (예: "로그인") */
  featureName: string
}

export type ApiResult<T> =
  | {
      ok: true
      data: T
    }
  | {
      ok: false
      message: string
    }

/** 요청을 처리할 수 없을 때 던지는 오류. message가 화면과 API 기록에 실패 사유로 표시된다 */
export class ApiError extends Error {}

// 처리 중인 API 호출의 '서버 처리' 메모 (callApi 안에서만 모은다)
let pendingServerNotes: string[] | null = null

/**
 * 응답에는 드러나지 않지만 API 명세에 적어야 할 서버 동작을 API 기록에 함께 남긴다.
 * 예: serverNote("가입된 계정이 없어 메일을 보내지 않음")
 */
export function serverNote(message: string) {
  pendingServerNotes?.push(message)
}

export function callApi<Req extends object, Res>(
  meta: ApiMeta,
  request: Req,
  handler: (request: Req) => Res,
): ApiResult<Res> {
  const requestCopy = structuredClone(request)
  pendingServerNotes = []
  const takeNotes = () => {
    const notes = pendingServerNotes ?? []
    pendingServerNotes = null
    return notes.length > 0 ? notes : undefined
  }
  try {
    const result = handler(structuredClone(request))
    // 화면이 DB 객체를 직접 고치지 못하도록 응답은 복사해서 넘긴다 (실제 네트워크 경계와 같은 효과)
    const response = result === undefined ? undefined : structuredClone(result)
    addApiLog({ ...meta, request: requestCopy, ok: true, response, serverNotes: takeNotes() })
    return { ok: true, data: response as Res }
  } catch (error) {
    if (error instanceof ApiError) {
      addApiLog({
        ...meta,
        request: requestCopy,
        ok: false,
        errorMessage: error.message,
        serverNotes: takeNotes(),
      })
      return { ok: false, message: error.message }
    }
    pendingServerNotes = null
    throw error
  }
}

export const PASSWORD_CHANGE_REQUIRED_MESSAGE = "비밀번호를 먼저 변경해야 합니다."

/**
 * 로그인한 회원을 찾는다. 로그인하지 않았거나 탈퇴한 회원이면 실패.
 * 임시 비밀번호로 로그인해 비밀번호를 바꿔야 하는 동안에는(M3-A) 0.1.1·0.1.2·5.1.3만 받고 나머지는 거절한다
 * (그 API들은 duringPasswordChange: true로 부른다).
 */
export function requireMember(options: { duringPasswordChange?: boolean } = {}): Member {
  const memberId = sessionStore.getMemberId()
  const member = db.members.find(
    (item) => item.memberId === memberId && item.withdrawnAt === null,
  )
  if (!member) throw new ApiError("로그인이 필요합니다.")
  if (sessionStore.getMustChangePassword() && !options.duringPasswordChange) {
    serverNote("로그인 정보(토큰)에 '비밀번호 변경 필요'가 있어 비밀번호 변경 전까지 거절함")
    throw new ApiError(PASSWORD_CHANGE_REQUIRED_MESSAGE)
  }
  return member
}

/** 회원 → 로그인 사용자 정보 (로그인 응답·0.1.1 메뉴바 사용자 정보 조회 공통) */
export function toMenuProfile(member: Member, mustChangePassword = false): MenuProfile {
  const org = db.organizations.find((item) => item.orgId === member.orgId)
  const sigunguCode = org?.jurisdictionSigunguCode ?? ""
  const sidoCode = db.sigungus.find((item) => item.sigunguCode === sigunguCode)?.sidoCode ?? ""
  return {
    memberId: member.memberId,
    name: member.name,
    orgName: org?.orgName ?? "(알 수 없는 기관)",
    title: member.title,
    jurisdictionSidoCode: sidoCode,
    jurisdictionSigunguCode: sigunguCode,
    mustChangePassword,
  }
}

export function findOrganizationName(orgId: number): string {
  return (
    db.organizations.find((org) => org.orgId === orgId)?.orgName ??
    "(알 수 없는 기관)"
  )
}
