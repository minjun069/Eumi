import DOMPurify from "dompurify"
import type { TableauFilterInput, TableauParameterInput } from "@/tableau/tableauTypes"

// AI 패널 완료 행의 artifacts (docs/work-ref/내부_연동_변경_계획.md 2-7)
// - ai_message.artifacts = [{type, data}, ...]. 완료 행만 그린다 (진행 행의 중간 산출물은 같은 그래프가 겹쳐 그리지 않는다)
// - tableau: schema_version 1만 Tableau 카드로 그린다 (src · parameters · filters)
// - table · chart · map: {mime_type: "text/html", content}를 DOMPurify로 정화해 그린다
// - 모르는 type · schema_version, 형식이 다른 항목은 건너뛴다 (AI의 data 등)

export type TableauArtifact = {
  kind: "tableau"
  key: string
  /** 같은 산출물인지 가리는 값 (artifact_id, 없으면 주소 · 조건) */
  identity: string
  title: string
  /** Tableau Public 게시 뷰 주소. 주소나 조건 형식이 틀리면 null (띄우지 않고 '불러오지 못했습니다') */
  src: string | null
  parameters: TableauParameterInput[]
  filters: TableauFilterInput[]
  source: { label: string; uri: string } | null
  warnings: string[]
}

export type HtmlArtifact = {
  kind: "html"
  key: string
  /** 같은 산출물인지 가리는 값 (종류와 HTML 내용) */
  identity: string
  type: "table" | "chart" | "map"
  content: string
}

export type PanelArtifact = TableauArtifact | HtmlArtifact

/** AI가 만드는 게시 뷰 주소 형식 (https://public.tableau.com/views/{워크북}/{뷰}). 다른 주소는 띄우지 않는다 */
const TABLEAU_VIEW_URL = /^https:\/\/public\.tableau\.com\/views\/[^/?#\s]+\/[^/?#\s]+$/
const isHtmlType = (value: unknown): value is HtmlArtifact["type"] => value === "table" || value === "chart" || value === "map"

type Json = Record<string, unknown>
const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value)
const isString = (value: unknown): value is string => typeof value === "string"
const isStringArray = (value: unknown): value is string[] => Array.isArray(value) && value.every(isString)

function readParameter(value: unknown): TableauParameterInput | null {
  if (!isRecord(value) || !isString(value.name) || !isString(value.value)) return null
  if (value.data_type !== "date" && value.data_type !== "string") return null
  return { name: value.name, dataType: value.data_type, value: value.value }
}

function readFilter(value: unknown): TableauFilterInput | null {
  if (!isRecord(value) || !isString(value.worksheet) || !isString(value.field) || !isStringArray(value.values)) return null
  if (value.operation === "all") return { worksheet: value.worksheet, field: value.field, operation: "all", values: [] }
  if (value.operation === "replace" && value.values.length > 0) {
    return { worksheet: value.worksheet, field: value.field, operation: "replace", values: value.values }
  }
  return null
}

function readTableau(data: Json, index: number): TableauArtifact | null {
  if (data.schema_version !== 1) return null
  const parameters = Array.isArray(data.parameters) ? data.parameters.map(readParameter) : []
  const filters = Array.isArray(data.filters) ? data.filters.map(readFilter) : []
  const conditionsValid =
    (data.parameters === undefined || Array.isArray(data.parameters)) &&
    (data.filters === undefined || Array.isArray(data.filters)) &&
    !parameters.includes(null) &&
    !filters.includes(null)
  const src = isString(data.src) && TABLEAU_VIEW_URL.test(data.src) && conditionsValid ? data.src : null
  const source =
    isRecord(data.source) && isString(data.source.label) && isString(data.source.uri) && TABLEAU_VIEW_URL.test(data.source.uri)
      ? { label: data.source.label, uri: data.source.uri }
      : null
  const validParameters = parameters.filter((item): item is TableauParameterInput => item !== null)
  const validFilters = filters.filter((item): item is TableauFilterInput => item !== null)
  return {
    kind: "tableau",
    key: `${index}-${isString(data.artifact_id) ? data.artifact_id : "tableau"}`,
    identity: `tableau:${isString(data.artifact_id) ? data.artifact_id : JSON.stringify([data.src, validParameters, validFilters])}`,
    title: isString(data.title) && data.title.trim() ? data.title : "Tableau 그래프",
    src,
    parameters: validParameters,
    filters: validFilters,
    source,
    warnings: isStringArray(data.warnings) ? data.warnings : [],
  }
}

function readHtml(type: HtmlArtifact["type"], data: Json, index: number): HtmlArtifact | null {
  if (data.schema_version !== undefined && data.schema_version !== 1) return null
  if (data.mime_type !== "text/html" || !isString(data.content) || !data.content.trim()) return null
  return { kind: "html", key: `${index}-${type}`, identity: `${type}:${data.content}`, type, content: data.content }
}

/** 완료 행의 artifacts에서 그릴 수 있는 항목만 순서대로 꺼낸다 */
export function readArtifacts(value: unknown): PanelArtifact[] {
  if (!Array.isArray(value)) return []
  const artifacts: PanelArtifact[] = []
  value.forEach((item, index) => {
    if (!isRecord(item) || !isRecord(item.data)) return
    const artifact =
      item.type === "tableau"
        ? readTableau(item.data, index)
        : isHtmlType(item.type)
          ? readHtml(item.type, item.data, index)
          : null
    if (artifact) artifacts.push(artifact)
  })
  return artifacts
}

export type AnswerArtifacts = { artifacts: PanelArtifact[]; /** 앞 답변에 이미 나와 다시 그리지 않은 개수 */ repeated: number }

/**
 * 대화의 완료 행(messageId 오름차순)마다 그릴 산출물. 앞 완료 행에서 이미 그린 산출물은 빼고 개수만 센다.
 * AI는 되묻기 · 실행 한도 종료 행 등에 이전 답의 산출물을 그대로 다시 넣는다 (ai/src/graph.py:
 * 진행 · 되묻기 응답은 기존 artifacts를 유지해야 함). 같은 그래프를 답마다 다시 띄우지 않게 처음 나온 답에만 그린다
 */
export function artifactsByAnswer(answers: { messageId: number; artifacts: unknown }[]): Map<number, AnswerArtifacts> {
  const seen = new Set<string>()
  const result = new Map<number, AnswerArtifacts>()
  for (const answer of answers) {
    const shown: PanelArtifact[] = []
    let repeated = 0
    for (const artifact of readArtifacts(answer.artifacts)) {
      if (seen.has(artifact.identity)) {
        repeated += 1
        continue
      }
      seen.add(artifact.identity)
      shown.push(artifact)
    }
    result.set(answer.messageId, { artifacts: shown, repeated })
  }
  return result
}

// ---------- HTML 정화 ----------
// AI가 글자를 이스케이프해 만든 독립 HTML 문서(표 · SVG)다. 본문만 남기고(head의 style · title은 버린다)
// 스크립트 · 이벤트 속성(DOMPurify 기본), 외부 리소스(주소 속성, url(...), 이미지 · 프레임 · 개체), 앱 화면을 바꿀 수 있는
// style 태그 · style · class 속성을 지운다. 같은 문서 안의 참조(#id)만 남기고, id는 산출물마다 앞에 붙여 겹치지 않게 한다

const purifier = DOMPurify(window)

/** 주소를 값으로 갖는 속성: 문서 안 참조(#id)가 아니면 지운다 */
const URI_ATTRIBUTES = new Set([
  "href",
  "xlink:href",
  "src",
  "srcset",
  "action",
  "formaction",
  "poster",
  "background",
  "ping",
  "cite",
  "longdesc",
  "data",
  "codebase",
  "manifest",
])
/** fill="url(https://…)" 처럼 문서 밖을 가리키는 url(...) */
const EXTERNAL_URL_FUNCTION = /url\s*\(\s*(?!['"]?\s*#)/i

purifier.addHook("uponSanitizeAttribute", (_node, data) => {
  const name = data.attrName.toLowerCase()
  const value = data.attrValue.trim()
  if ((URI_ATTRIBUTES.has(name) && !value.startsWith("#")) || EXTERNAL_URL_FUNCTION.test(value)) data.keepAttr = false
})

const FORBID_TAGS = [
  "style",
  "link",
  "meta",
  "base",
  "img",
  "image",
  "picture",
  "source",
  "video",
  "audio",
  "track",
  "iframe",
  "frame",
  "frameset",
  "object",
  "embed",
  "use",
  "foreignobject",
  "form",
  "input",
  "button",
  "textarea",
  "select",
]

/** 같은 문서 안 참조 url(#id) · href="#id" · aria-labelledby 등을 앞붙임 id로 바꾼다 */
function scopeIds(root: DocumentFragment, prefix: string) {
  const ids = new Set<string>()
  for (const element of root.querySelectorAll("[id]")) {
    ids.add(element.id)
    element.id = prefix + element.id
  }
  if (ids.size === 0) return
  const scoped = (id: string) => (ids.has(id) ? prefix + id : id)
  for (const element of root.querySelectorAll("*")) {
    for (const attribute of Array.from(element.attributes)) {
      if (attribute.name === "id") continue
      let value = attribute.value.replace(
        /url\(\s*(['"]?)#([^'")\s]+)\1\s*\)/g,
        (_match, _quote, id: string) => `url(#${scoped(id)})`,
      )
      if ((attribute.name === "href" || attribute.name === "xlink:href") && value.startsWith("#")) {
        value = `#${scoped(value.slice(1))}`
      }
      if (attribute.name === "aria-labelledby" || attribute.name === "aria-describedby") {
        value = value.split(/\s+/).map(scoped).join(" ")
      }
      if (value !== attribute.value) attribute.value = value
    }
  }
}

/** 정화한 HTML 조각. idPrefix는 산출물마다 달라야 한다 (영문 · 숫자 · '-') */
export function sanitizeArtifactHtml(html: string, idPrefix: string): DocumentFragment {
  const fragment = purifier.sanitize(html, {
    USE_PROFILES: { html: true, svg: true },
    FORBID_TAGS,
    FORBID_ATTR: ["style", "class"],
    RETURN_DOM_FRAGMENT: true,
  })
  scopeIds(fragment, idPrefix)
  return fragment
}
