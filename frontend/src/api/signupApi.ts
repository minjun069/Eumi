import { api } from "@/api/http"
import type { Schemas, SuccessData } from "@/api/types"

// 회원가입 (API-04~07). 로그인 전 화면이라 401 처리를 하지 않는다 (POST 전 CSRF 준비는 http.ts가 한다)

export type OrganizationSearchItem = Schemas["OrganizationSearchItem"]
export type SendVerificationRequest = Schemas["SendVerificationRequest"]
export type VerifyCodeRequest = Schemas["VerifyCodeRequest"]
export type SignupRequest = Schemas["SignupRequest"]
export type OrganizationSearchResult = SuccessData<"signupApi_searchOrganizations_Success">
export type VerificationSent = SuccessData<"signupApi_sendVerificationEmail_Success">
export type VerificationTokenData = SuccessData<"signupApi_verifyCode_Success">
export type MemberCreated = SuccessData<"signupApi_signup_Success">

/** API-04가 돌려주는 최대 개수 */
export const ORG_SEARCH_LIMIT = 20

export const signupApi = {
  /** API-04 GET /organizations?keyword= — 기관명 부분 검색(문자 그대로 비교), 이름순 최대 20개. 검색어가 비거나 공백뿐이면 400 */
  searchOrganizations: (keyword: string) =>
    api.get<OrganizationSearchResult>("/organizations", { query: { keyword }, skipAuthHandling: true }),

  /**
   * API-05 POST /signup/email-verifications — 201 {expiresAt}(발송 후 10분, 서울 오프셋 ISO 8601).
   * 성공한 재발송은 옛 코드와 증명을 버린다. 같은 이메일 60초 안 재발송은 429 RATE_LIMITED
   */
  sendVerificationEmail: (request: SendVerificationRequest) =>
    api.post<VerificationSent>("/signup/email-verifications", request, { skipAuthHandling: true }),

  /** API-06 POST /signup/email-verifications/verify — 200 {verificationToken}(10분, 가입에서 한 번). 다시 확인하면 새 토큰 */
  verifyCode: (request: VerifyCodeRequest) =>
    api.post<VerificationTokenData>("/signup/email-verifications/verify", request, { skipAuthHandling: true }),

  /** API-07 POST /members — 201 {memberId}. 자동 로그인하지 않는다 */
  signup: (request: SignupRequest) => api.post<MemberCreated>("/members", request, { skipAuthHandling: true }),
}
