import { db, nextId } from "@/mock/db"
import { ApiError, callApi } from "@/mock/api/core"
import { formatDate, formatDateTime } from "@/utils/datetime"
import { emailDomain, isValidPassword } from "@/utils/validation"

// 1.1.1 회원가입
// 순서: 소속기관 검색 → 인증 메일 발송 → 인증 코드 확인(인증 토큰 발급) → 회원가입(인증 토큰 함께 보냄)
// 계정은 이메일 인증을 마친 뒤 회원가입 요청을 받을 때 만든다.

/** 인증 코드 유효 시간 (S3-A: 10분) */
export const VERIFICATION_VALID_MS = 10 * 60 * 1000

export type OrganizationSearchItem = {
  orgId: number
  orgName: string
  sidoName: string
  sigunguName: string
  /** 공식 메일 도메인 (없으면 null → 이메일 인증만으로 가입) */
  officialDomain: string | null
}

export type SignupRequest = {
  verificationToken: string
  orgId: number
  email: string
  name: string
  password: string
  title: string | null
  phone: string | null
}

function findJurisdiction(sigunguCode: string) {
  const sigungu = db.sigungus.find((item) => item.sigunguCode === sigunguCode)
  const sido = db.sidos.find((item) => item.sidoCode === sigungu?.sidoCode)
  return { sidoName: sido?.sidoName ?? "", sigunguName: sigungu?.sigunguName ?? "" }
}

/** S8-B: 탈퇴한 회원의 이메일도 다시 쓸 수 없다 */
function isEmailTaken(email: string) {
  return db.members.some((member) => member.email.toLowerCase() === email.toLowerCase())
}

function createVerificationCode(): string {
  return String(Math.floor(100000 + Math.random() * 900000))
}

function createToken(): string {
  return `vt_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`
}

export const signupApi = {
  /** 소속기관 검색 (S7-A: 기관명으로 검색). 관할지역은 기관에 따라 정해진다 */
  searchOrganizations(request: { keyword: string }) {
    return callApi({ featureId: "1.1.1", featureName: "소속기관 검색" }, request, ({ keyword }) => {
      const word = keyword.trim()
      return db.organizations
        .filter((org) => org.orgName.includes(word))
        .map((org): OrganizationSearchItem => {
          const { sidoName, sigunguName } = findJurisdiction(org.jurisdictionSigunguCode)
          return {
            orgId: org.orgId,
            orgName: org.orgName,
            sidoName,
            sigunguName,
            officialDomain: org.officialDomain,
          }
        })
    })
  },

  /** 인증 메일 발송. 다시 부르면 새 코드를 보내고 이전 코드는 쓸 수 없게 된다(재발송) */
  sendVerificationEmail(request: { orgId: number; email: string }) {
    return callApi(
      { featureId: "1.1.1", featureName: "인증 메일 발송" },
      request,
      ({ orgId, email }) => {
        const org = db.organizations.find((item) => item.orgId === orgId)
        if (!org) throw new ApiError("소속기관을 찾을 수 없습니다.")
        if (isEmailTaken(email)) throw new ApiError("이미 가입된 이메일입니다.")
        if (org.officialDomain && emailDomain(email) !== org.officialDomain) {
          throw new ApiError(`선택한 기관의 공식 메일(@${org.officialDomain})로만 가입할 수 있습니다.`)
        }

        db.emailVerifications
          .filter((item) => item.email === email && !item.replaced)
          .forEach((item) => {
            item.replaced = true
          })
        const sentAt = Date.now()
        const verification = {
          verificationId: nextId(db.emailVerifications, (item) => item.verificationId),
          email,
          orgId,
          code: createVerificationCode(),
          sentAt,
          expiresAt: sentAt + VERIFICATION_VALID_MS,
          replaced: false,
          verifiedAt: null,
        }
        db.emailVerifications.push(verification)

        // 인증 코드는 응답에 넣지 않는다 (메일로만 전달)
        return { expiresAt: formatDateTime(new Date(verification.expiresAt)) }
      },
    )
  },

  /** 인증 코드 확인. 성공하면 회원가입 요청에 함께 보낼 인증 토큰을 준다 (S9-A) */
  verifyCode(request: { email: string; code: string }) {
    return callApi(
      { featureId: "1.1.1", featureName: "인증 코드 확인" },
      request,
      ({ email, code }) => {
        const verification = db.emailVerifications.find(
          (item) => item.email === email && !item.replaced,
        )
        if (!verification) throw new ApiError("인증 메일을 먼저 받으세요.")
        if (verification.verifiedAt !== null) throw new ApiError("이미 인증을 마친 코드입니다.")
        if (Date.now() > verification.expiresAt) {
          throw new ApiError("인증 시간이 지났습니다. 인증 메일을 다시 받으세요.")
        }
        if (verification.code !== code) throw new ApiError("인증 코드가 일치하지 않습니다.")

        verification.verifiedAt = Date.now()
        const token = createToken()
        db.verificationTokens.push({ token, email, orgId: verification.orgId, usedAt: null })
        return { verificationToken: token }
      },
    )
  },

  /** 회원가입. 인증 토큰의 이메일·기관과 요청 값이 같아야 한다. 관할지역은 기관으로 정해지므로 받지 않는다 */
  signup(request: SignupRequest) {
    return callApi({ featureId: "1.1.1", featureName: "회원가입" }, request, (input) => {
      const token = db.verificationTokens.find((item) => item.token === input.verificationToken)
      if (!token || token.usedAt !== null || token.email !== input.email || token.orgId !== input.orgId) {
        throw new ApiError("이메일 인증 정보가 올바르지 않습니다. 이메일 인증을 다시 하세요.")
      }
      if (isEmailTaken(input.email)) throw new ApiError("이미 가입된 이메일입니다.")
      if (!input.name.trim()) throw new ApiError("이름을 입력하세요.")
      if (!isValidPassword(input.password)) throw new ApiError("비밀번호 규칙에 맞지 않습니다.")

      token.usedAt = Date.now()
      const memberId = nextId(db.members, (member) => member.memberId)
      db.members.push({
        memberId,
        name: input.name.trim(),
        email: input.email,
        password: input.password,
        orgId: input.orgId,
        title: input.title,
        phone: input.phone,
        tempPassword: null,
        tempPasswordIssuedAt: null,
        createdAt: formatDate(new Date()),
        withdrawnAt: null,
      })
      return { memberId }
    })
  },
}
