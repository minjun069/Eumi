import { PATHS } from "@/routes/paths"

// 아직 만들지 않은 화면의 자리 표시 내용. 해당 단계에서 실제 화면으로 바꾼다.

export type PlaceholderSpec = {
  title: string
  stage: string
  features: string[]
  /** 이 화면으로 오게 되는 상황 설명 */
  note?: string
  /** 이 자리에서 이어지는 화면 (주소 확인용) */
  links?: PlaceholderLink[]
}

export type PlaceholderLink = {
  label: string
  to: string
}

// 12단계까지 모든 화면을 만들어 지금은 비어 있다. 새로 자리를 잡을 화면이 생기면 여기에 추가한다.
export const PLACEHOLDERS = {} satisfies Record<string, PlaceholderSpec>
