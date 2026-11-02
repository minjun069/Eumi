import type { components } from "@/api/schema"

// API 요청·응답 타입은 OpenAPI 2.2.0(src/api/schema.d.ts, 자동 생성)에서 꺼내 쓴다.
// 화면 코드에서 응답 모양을 직접 다시 정의하지 않는다.

export type Schemas = components["schemas"]

/** 공통 성공 응답 { success, data, meta }에서 data 부분 */
export type SuccessData<Name extends keyof Schemas> = Schemas[Name] extends { data: infer Data } ? Data : never

/** API-01 로그인 상태·메뉴 프로필 */
export type MenuProfile = SuccessData<"memberApi_getMenuProfile_Success">

export type FieldError = Schemas["FieldError"]
