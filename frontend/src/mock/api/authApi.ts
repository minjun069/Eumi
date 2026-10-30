import { db } from "@/mock/db"
import {
  ApiError,
  callApi,
  requireMember,
  serverNote,
  toMenuProfile,
} from "@/mock/api/core"
import type { Member } from "@/types/domain"

// 1. AUTH 사용자 계정 (1.2.1 로그인, 1.3.1 비밀번호 찾기) + 0.1.2 로그아웃

/** 임시 비밀번호 유효 시간 (P4-B: 발급 후 24시간) */
export const TEMP_PASSWORD_VALID_MS = 24 * 60 * 60 * 1000

/** 로그인 실패 문구 (불일치·탈퇴·임시 비밀번호 만료 모두 같은 문구) */
const LOGIN_FAILED = "이메일 또는 비밀번호가 일치하지 않습니다."

export type LoginRequest = {
  email: string
  password: string
}

export type LoginResponse = {
  memberId: number
  name: string
  email: string
  orgId: number
  orgName: string
  title: string | null
  /** 소속 기관 관할 시도·시군구 코드 (검색 조건 처음 값에 씀) */
  jurisdictionSidoCode: string
  jurisdictionSigunguCode: string
  /**
   * 비밀번호 변경 필요: 임시 비밀번호로 로그인했으면 true → 비밀번호 변경 화면(5.1.3)으로 먼저 이동.
   * 로그인 정보(토큰)에도 담아, 바꿀 때까지 다른 API를 거절한다 (M3-A)
   */
  mustChangePassword: boolean
}

export type IssueTempPasswordRequest = {
  email: string
  name: string
}

function toLoginResponse(member: Member, mustChangePassword: boolean): LoginResponse {
  const profile = toMenuProfile(member, mustChangePassword)
  return {
    memberId: member.memberId,
    name: member.name,
    email: member.email,
    orgId: member.orgId,
    orgName: profile.orgName,
    title: member.title,
    jurisdictionSidoCode: profile.jurisdictionSidoCode,
    jurisdictionSigunguCode: profile.jurisdictionSigunguCode,
    mustChangePassword,
  }
}

/** 발급 후 24시간 안의 임시 비밀번호가 있는지 */
export function isTempPasswordValid(member: Member) {
  return (
    member.tempPassword !== null &&
    member.tempPasswordIssuedAt !== null &&
    Date.now() - member.tempPasswordIssuedAt < TEMP_PASSWORD_VALID_MS
  )
}

/** 영문·숫자·특수문자를 모두 넣은 10자 (헷갈리는 글자 0·O·1·l·I는 뺌) */
function createTempPassword(): string {
  const letters = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz"
  const digits = "23456789"
  const specials = "!@#$%*"
  const pick = (chars: string) => chars[Math.floor(Math.random() * chars.length)]
  const chars = [
    ...Array.from({ length: 6 }, () => pick(letters)),
    ...Array.from({ length: 3 }, () => pick(digits)),
    pick(specials),
  ]
  return chars.sort(() => Math.random() - 0.5).join("")
}

export const authApi = {
  /**
   * 1.2.1 로그인
   * - 기존 비밀번호와 일치 → 로그인. 발급된 임시 비밀번호가 있으면 지운다
   * - 발급 후 24시간 이내의 임시 비밀번호와 일치 → 로그인하고 비밀번호 변경으로 보낸다
   * - 그 밖(불일치, 탈퇴, 24시간이 지난 임시 비밀번호) → 같은 실패 문구
   */
  login(request: LoginRequest) {
    return callApi({ featureId: "1.2.1", featureName: "로그인" }, request, ({ email, password }) => {
      const member = db.members.find((item) => item.email === email && item.withdrawnAt === null)
      if (!member) throw new ApiError(LOGIN_FAILED)

      if (member.password === password) {
        if (member.tempPassword !== null) {
          member.tempPassword = null
          member.tempPasswordIssuedAt = null
          serverNote("기존 비밀번호로 로그인해 발급되어 있던 임시 비밀번호를 지움")
        }
        return toLoginResponse(member, false)
      }

      if (member.tempPassword !== null && member.tempPassword === password) {
        if (isTempPasswordValid(member)) {
          serverNote("임시 비밀번호로 로그인함 → 로그인 정보(토큰)에 '비밀번호 변경 필요'를 담음. 비밀번호를 바꿀 때까지 0.1.1·0.1.2·5.1.3 말고는 거절")
          return toLoginResponse(member, true)
        }
        serverNote("임시 비밀번호의 유효 시간(24시간)이 지남")
      }
      throw new ApiError(LOGIN_FAILED)
    })
  },

  /**
   * 1.3.1 비밀번호 찾기: 임시 비밀번호 발급 (이메일 + 이름, P1-B)
   * 가입 여부가 드러나지 않도록 결과와 관계없이 항상 같은 응답을 준다 (P2-A).
   * 기존 비밀번호는 그대로 두고 임시 비밀번호를 따로 보관한다 (P3-B). 다시 발급하면 이전 임시 비밀번호는 쓸 수 없다.
   */
  issueTempPassword(request: IssueTempPasswordRequest) {
    return callApi(
      { featureId: "1.3.1", featureName: "임시 비밀번호 발급" },
      request,
      ({ email, name }) => {
        const member = db.members.find((item) => item.email === email)
        if (!member) {
          serverNote("가입된 계정이 없어 메일을 보내지 않음")
          return undefined
        }
        if (member.withdrawnAt !== null) {
          serverNote("탈퇴한 회원이라 메일을 보내지 않음")
          return undefined
        }
        if (member.name !== name) {
          serverNote("이름이 일치하지 않아 메일을 보내지 않음")
          return undefined
        }
        if (member.tempPassword !== null) serverNote("이전에 발급한 임시 비밀번호는 쓸 수 없게 됨")
        member.tempPassword = createTempPassword()
        member.tempPasswordIssuedAt = Date.now()
        serverNote(
          `임시 비밀번호를 발급해 ${email}로 메일을 보냄 (24시간 동안 사용 가능, 기존 비밀번호도 계속 사용 가능)`,
        )
        return undefined
      },
    )
  },

  /** 0.1.2 로그아웃 */
  logout() {
    return callApi({ featureId: "0.1.2", featureName: "로그아웃" }, {}, () => {
      requireMember({ duringPasswordChange: true })
      return undefined
    })
  },
}
