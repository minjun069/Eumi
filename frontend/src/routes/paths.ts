// 화면 주소 (프로토타입과 같은 주소를 쓴다). API 경로와 같을 필요는 없다.

export const PATHS = {
  login: "/login",
  signup: "/signup",
  passwordFind: "/password/find",

  risk: "/risk",

  resources: "/resources",
  resourceNew: "/resources/new",
  resourceDetail: (resourceId: number | string) => `/resources/${resourceId}`,
  resourceEdit: (resourceId: number | string) =>
    `/resources/${resourceId}/edit`,

  cases: "/cases",
  caseNew: "/cases/new",
  caseDetail: (caseId: number | string) => `/cases/${caseId}`,
  caseEdit: (caseId: number | string) => `/cases/${caseId}/edit`,

  /** 5. 마이페이지 (M1-A: 탭 3개는 주소를 따로, 비밀번호 변경·탈퇴는 별도 화면) */
  my: "/my",
  myResources: "/my/resources",
  myConversations: "/my/conversations",
  myPassword: "/my/password",
  myWithdraw: "/my/withdraw",
} as const

/** 로그인하면 처음 보여주는 화면 (0.1.1) */
export const HOME_PATH = PATHS.risk

/** 로그인하지 않아도 볼 수 있는 화면 */
export const PUBLIC_PATHS: string[] = [
  PATHS.login,
  PATHS.signup,
  PATHS.passwordFind,
]
