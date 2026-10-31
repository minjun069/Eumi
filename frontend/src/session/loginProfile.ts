import type { LoginResponse } from "@/mock/api/authApi"
import type { MenuProfile } from "@/types/domain"

/** 로그인 응답(1.2.1) → 메뉴바에 쓰는 로그인 사용자 정보 */
export function profileFromLogin(data: LoginResponse): MenuProfile {
  return {
    memberId: data.memberId,
    name: data.name,
    orgName: data.orgName,
    title: data.title,
    jurisdictionSidoCode: data.jurisdictionSidoCode,
    jurisdictionSigunguCode: data.jurisdictionSigunguCode,
    mustChangePassword: data.mustChangePassword,
  }
}
