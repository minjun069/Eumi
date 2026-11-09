import { useEffect, useRef, useState } from "react"
import type { TableauArtifact, TableauFilterInput, TableauParameterInput } from "@/components/agent/artifactData"
import { TABLEAU_MODULE_URL } from "@/tableau/tableauConfig"
import type { Filter, Parameter, ParameterValue, Viz, Worksheet } from "@/tableau/tableauTypes"

/**
 * AI 패널 완료 행의 Tableau 카드 (docs/work-ref/내부_연동_변경_계획.md 2-7, ai/docs/TABLEAU.md 끝 절)
 * - 카드마다 Tableau를 새로 띄운다. 카드끼리 매개변수 · 필터를 나누지 않는다
 * - 패널에서 카드가 보일 때 처음 띄운다 (닫힌 패널, 스크롤 밖의 카드는 띄우지 않는다)
 * - 매개변수는 처음 띄울 때 넘기고, FirstInteractive 뒤 매개변수 → 대상 시트 필터 순서로 맞춘 다음 다시 읽어 확인한다.
 *   p_detail_adm은 표시값('강남구 신사동')으로 오고 다시 읽은 원값은 코드라서 표시값 · 별칭으로도 비교한다
 * - 대시보드는 크기가 고정이라 FirstVizSizeKnown의 크기로 띄우고 패널 폭에 맞춰 줄여 보인다
 * - 불러오지 못하거나, 값이 다르게 들어가거나, 제한 시간 안에 끝나지 않으면 "그래프를 불러오지 못했습니다"와 '다시 시도'
 */

const LOAD_ERROR = "그래프를 불러오지 못했습니다"
const LOAD_TIMEOUT_MS = 30_000
/** 크기를 알기 전 자리 (메인 대시보드 폭) */
const INITIAL_SIZE: Size = { width: 640, height: 480 }
const ERROR_HEIGHT = 120

type Size = { width: number; height: number }
type VizSizeDetail = {
  vizSize?: { chromeHeight?: number; sheetSize?: { behavior?: string; minSize?: Size; maxSize?: Size } }
}
type Phase = "waiting" | "loading" | "ready" | "error"

const sorted = (values: string[]) => JSON.stringify([...values].sort())

/** 크기 범위의 상한이 없으면 Tableau가 2147483647을 준다 (11/9 확인: EmbedDetailV02의 maxSize.width) */
const SIZE_LIMIT = 4096
const bounded = (value: number | undefined) => (value && value > 0 && value <= SIZE_LIMIT ? value : undefined)

/**
 * 폭 상한이 없는 대시보드를 펼칠 폭. 패널 폭(약 390px)으로 펼치면 글자가 겹쳐서(11/9 EmbedDetailV02),
 * 상세 시트의 설계 폭(docs/work-ref/tableau_views.json의 EmbedDetailV01~V08: 720, V06만 900)으로 펼치고 줄여 보인다
 */
const OPEN_WIDTH = 720

/**
 * 띄울 크기. 고정 · 상한이 있으면 그 크기, 폭 상한이 없으면 펼칠 폭(최소 폭이 더 크면 최소 폭),
 * 높이 상한도 없으면 최소 높이나 기본 높이. 도구 모음 높이(chromeHeight)를 더한다
 */
function vizFrameSize(detail: VizSizeDetail | undefined): Size | null {
  const sheet = detail?.vizSize?.sheetSize
  if (!sheet) return null
  const width = bounded(sheet.maxSize?.width) ?? Math.max(bounded(sheet.minSize?.width) ?? 0, OPEN_WIDTH)
  const height = bounded(sheet.maxSize?.height) ?? bounded(sheet.minSize?.height) ?? INITIAL_SIZE.height
  return { width, height: height + (detail?.vizSize?.chromeHeight ?? 0) }
}

/** 지금 값이 원하는 값인지: 원값, 표시값, 별칭 중 하나가 같으면 같다. 날짜는 앞 10자(YYYY-MM-DD)로 비교한다 */
function parameterMatches(current: ParameterValue, wanted: TableauParameterInput): boolean {
  const raw = String(current.value)
  const candidates = [raw, current.formattedValue, current.hasAlias ? current.aliasValue : undefined]
  if (wanted.dataType === "date") candidates.push(raw.slice(0, 10))
  return candidates.includes(wanted.value)
}

/** changeParameterValueAsync에 넣을 값. 목록 값에 별칭이 있으면 별칭으로만 받는다 (TableauWorksheet와 같음) */
function parameterInput(parameter: Parameter, wanted: TableauParameterInput): string {
  const option = parameter.allowableValues?.allowableValues?.find((item) => String(item.value) === wanted.value)
  return option?.hasAlias && option.aliasValue ? option.aliasValue : wanted.value
}

function filterMatches(current: Filter | undefined, wanted: TableauFilterInput): boolean {
  if (wanted.operation === "all") return !current || Boolean(current.isAllSelected)
  if (!current || current.isAllSelected) return false
  const applied = current.appliedValues ?? []
  return (
    sorted(applied.map((item) => String(item.value))) === sorted(wanted.values) ||
    sorted(applied.map((item) => String(item.formattedValue))) === sorted(wanted.values)
  )
}

function findWorksheet(viz: Viz, name: string): Worksheet {
  const sheet = viz.workbook.activeSheet
  if (sheet.sheetType === "worksheet" && sheet.name === name) return sheet
  const found = sheet.sheetType === "dashboard" ? sheet.worksheets.find((item) => item.name === name) : undefined
  if (!found) throw new Error(`Worksheet not found: ${name}`)
  return found
}

/** 매개변수 → 시트별 필터 순서로 맞추고, 바꾼 것은 다시 읽어 확인한다 */
async function applyConditions(
  viz: Viz,
  parameters: TableauParameterInput[],
  filters: TableauFilterInput[],
  replace: unknown,
  isCurrent: () => boolean,
) {
  if (parameters.length > 0) {
    const current = await viz.workbook.getParametersAsync()
    let changed = false
    for (const wanted of parameters) {
      const actual = current.find((item) => item.name === wanted.name)
      if (!actual) throw new Error(`Parameter not found: ${wanted.name}`)
      if (parameterMatches(actual.currentValue, wanted)) continue
      await viz.workbook.changeParameterValueAsync(wanted.name, parameterInput(actual, wanted))
      if (!isCurrent()) return
      changed = true
    }
    if (changed) {
      const applied = await viz.workbook.getParametersAsync()
      for (const wanted of parameters) {
        const actual = applied.find((item) => item.name === wanted.name)
        if (!actual || !parameterMatches(actual.currentValue, wanted)) {
          throw new Error(`Parameter readback mismatch: ${wanted.name}`)
        }
      }
    }
  }

  const byWorksheet = new Map<string, TableauFilterInput[]>()
  for (const filter of filters) byWorksheet.set(filter.worksheet, [...(byWorksheet.get(filter.worksheet) ?? []), filter])
  for (const [name, group] of byWorksheet) {
    if (!isCurrent()) return
    const sheet = findWorksheet(viz, name)
    const current = await sheet.getFiltersAsync()
    let changed = false
    for (const wanted of group) {
      if (filterMatches(current.find((item) => item.fieldName === wanted.field), wanted)) continue
      // clearFilterAsync는 걸려 있지 않은 필터를 풀면 실패한다 (걸려 있을 때만 여기로 온다)
      if (wanted.operation === "all") await sheet.clearFilterAsync(wanted.field)
      else await sheet.applyFilterAsync(wanted.field, wanted.values, replace)
      if (!isCurrent()) return
      changed = true
    }
    if (changed) {
      const applied = await sheet.getFiltersAsync()
      for (const wanted of group) {
        if (!filterMatches(applied.find((item) => item.fieldName === wanted.field), wanted)) {
          throw new Error(`Filter readback mismatch: ${name} / ${wanted.field}`)
        }
      }
    }
  }
}

export function TableauArtifactCard({ artifact }: { artifact: TableauArtifact }) {
  const { src, title, source, warnings } = artifact
  const parametersKey = JSON.stringify(artifact.parameters)
  const filtersKey = JSON.stringify(artifact.filters)
  const frameRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef(title)
  titleRef.current = title
  const [visible, setVisible] = useState(false)
  const [phase, setPhase] = useState<Phase>("waiting")
  const [size, setSize] = useState<Size>(INITIAL_SIZE)
  const [frameWidth, setFrameWidth] = useState(0)
  const [retry, setRetry] = useState(0)

  // 보일 때 처음 띄운다. 한 번 띄운 뒤에는 스크롤로 가려져도 그대로 둔다
  useEffect(() => {
    const frame = frameRef.current
    if (!frame || visible) return
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setVisible(true)
    })
    observer.observe(frame)
    return () => observer.disconnect()
  }, [visible])

  useEffect(() => {
    const frame = frameRef.current
    if (!frame) return
    const observer = new ResizeObserver(() => setFrameWidth(frame.clientWidth))
    observer.observe(frame)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!visible || !src) return
    let disposed = false
    let viz: Viz | null = null
    let sizeEvent = "firstvizsizeknown"
    let firstEvent = "firstinteractive"
    let errorEvent = "vizloaderror"
    const parameters = JSON.parse(parametersKey) as TableauParameterInput[]
    const filters = JSON.parse(filtersKey) as TableauFilterInput[]
    setPhase("loading")
    setSize(INITIAL_SIZE)

    const fail = (reason: unknown) => {
      if (disposed) return
      window.clearTimeout(timeout)
      console.error("[TableauArtifactCard]", reason)
      setPhase("error")
    }
    const timeout = window.setTimeout(() => fail(new Error("Tableau load timed out")), LOAD_TIMEOUT_MS)

    const onSize = (event: Event) => {
      const next = vizFrameSize((event as CustomEvent<VizSizeDetail>).detail)
      if (!disposed && next) setSize(next)
    }
    const onLoadError = (event: Event) => fail((event as CustomEvent).detail)

    void (async () => {
      try {
        const { TableauViz, TableauEventType, FilterUpdateType } = await import(/* @vite-ignore */ TABLEAU_MODULE_URL)
        if (disposed) return
        const created = new TableauViz() as Viz
        viz = created
        // 틀(.agent-tableau-host) 크기를 따라간다. 크기를 알면 틀만 바꾼다 (Tableau 속성을 바꾸면 다시 불러온다)
        created.width = "100%"
        created.height = "100%"
        created.toolbar = "bottom"
        created.hideTabs = true
        created.setAttribute("aria-label", titleRef.current)
        sizeEvent = TableauEventType.FirstVizSizeKnown ?? sizeEvent
        firstEvent = TableauEventType.FirstInteractive ?? firstEvent
        errorEvent = TableauEventType.VizLoadError ?? errorEvent
        created.addEventListener(sizeEvent, onSize, { once: true })
        created.addEventListener(
          firstEvent,
          () => {
            applyConditions(created, parameters, filters, FilterUpdateType.Replace, () => !disposed)
              .then(() => {
                if (disposed) return
                window.clearTimeout(timeout)
                setPhase("ready")
              })
              .catch(fail)
          },
          { once: true },
        )
        created.addEventListener(errorEvent, onLoadError)
        for (const parameter of parameters) {
          const element = document.createElement("viz-parameter")
          element.setAttribute("name", parameter.name)
          element.setAttribute("value", parameter.value)
          created.appendChild(element)
        }
        created.src = src
        hostRef.current?.appendChild(created)
      } catch (error) {
        fail(error)
      }
    })()

    return () => {
      disposed = true
      window.clearTimeout(timeout)
      viz?.removeEventListener(sizeEvent, onSize)
      viz?.removeEventListener(errorEvent, onLoadError)
      viz?.remove()
    }
  }, [visible, src, parametersKey, filtersKey, retry])

  const shown: Phase = src ? phase : "error"
  const scale = frameWidth > 0 ? Math.min(1, frameWidth / size.width) : 1
  return (
    <figure className="agent-artifact agent-tableau">
      <figcaption className="agent-artifact-title">{title}</figcaption>
      <div
        ref={frameRef}
        className="agent-tableau-frame"
        style={{ height: shown === "error" ? ERROR_HEIGHT : Math.round(size.height * scale) }}
        aria-busy={shown === "waiting" || shown === "loading"}
      >
        {src && (
          <div
            ref={hostRef}
            className="agent-tableau-host"
            style={{
              width: size.width,
              height: size.height,
              transform: scale < 1 ? `scale(${scale})` : undefined,
              pointerEvents: shown === "ready" ? undefined : "none",
            }}
          />
        )}
        {shown !== "ready" && (
          <div className="agent-tableau-cover" role={shown === "error" ? "alert" : "status"}>
            <p>{shown === "error" ? LOAD_ERROR : "그래프를 불러오는 중…"}</p>
            {shown === "error" && src && (
              <button type="button" className="btn btn-outline btn-small" onClick={() => setRetry((value) => value + 1)}>
                다시 시도
              </button>
            )}
          </div>
        )}
      </div>
      {source && (
        <a className="agent-artifact-source" href={source.uri} target="_blank" rel="noopener noreferrer">
          출처: {source.label}
        </a>
      )}
      {warnings.length > 0 && (
        <details className="agent-artifact-notes">
          <summary>참고 사항 {warnings.length}개</summary>
          <ul>
            {warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
    </figure>
  )
}
