// 신원 정보 가리기 (0.2.2 AI에 넘길 때, 0.2.4 대화 기록에 저장할 때 같은 규칙).
// - 알려 준 이름(사례자 이름 등)을 ○○○로
// - '성씨로 시작하는 2~3글자 + 씨/님' (예: 박미정 씨) → ○○○ 씨  (pattern: true일 때)
// - 관리번호 형식(2025-0006) → ○○○○-○○○○
// 실제 규칙은 AI 담당과 정한다 (프로토타입 예시 규칙).

const SURNAMES = "김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경부"

const NAME_PATTERN = new RegExp(`([${SURNAMES}][가-힣]{1,2})(\\s?)(씨|님)`, "g")
const MANAGEMENT_NO_PATTERN = /(?<![\d-])\d{4}-\d{4}(?![\d-])/g

export type MaskResult = { text: string; count: number }

export function maskIdentity(text: string, names: string[], options: { pattern?: boolean } = {}): MaskResult {
  let count = 0
  let masked = text
  // 긴 이름부터 (이영자 ↔ 이영 같이 겹치는 경우)
  for (const name of [...new Set(names)].filter((item) => item.length >= 2).sort((a, b) => b.length - a.length)) {
    const parts = masked.split(name)
    count += parts.length - 1
    masked = parts.join("○○○")
  }
  if (options.pattern !== false) {
    masked = masked.replace(NAME_PATTERN, (_match, _name, space, suffix) => {
      count += 1
      return `○○○${space}${suffix}`
    })
  }
  masked = masked.replace(MANAGEMENT_NO_PATTERN, () => {
    count += 1
    return "○○○○-○○○○"
  })
  return { text: masked, count }
}
