import { type CSSProperties, useEffect, useRef, useState } from "react"
import { TABLEAU_DONG_FIELD, TABLEAU_MODULE_URL, TABLEAU_TOOLBAR_HEIGHT, tableauViewUrl } from "@/tableau/tableauConfig"
import type { ChartState, MarksTable, Parameter, TableauWorksheetProps, Viz, Worksheet } from "@/tableau/tableauTypes"

/**
 * Tableau Public 임베드용 대시보드 하나 (Embedding API v3, 프로토타입 feat/dashboard-PoC의 TableauWorksheet.tsx를 바꿈)
 * - 대시보드는 Tableau에서 만든 그대로 고정 크기로 띄운다 (도구 모음만 숨길 수 있다).
 *   crop이 있으면 그 부분만 보인다 (⑥: 위 선택 칸만 잘라 내고 지도 · 범례 · 격자 선택 카드 · 비교표를 보인다).
 *   hoverHeight가 crop 높이보다 크면 마우스를 올린 동안 그 높이까지 아래 내용 위에 겹쳐 펼친다 (⑥ 격자 상세 정보가 잘리지 않게).
 *   Tableau iframe 안의 마우스 위치는 받을 수 없어 ⑥ 어디에 올려도 펼친다
 * - 매개변수는 처음 띄울 때부터 넘기고, FirstInteractive 뒤에 실제 값을 다시 읽어 확인한다. 다르면 바꾸고 다시 확인한다
 * - 대시보드 이름이 바뀌면(지도 지표 전환) 다시 띄우지 않고 같은 워크북 안에서 대시보드만 바꾼다
 * - 조건 적용은 한 번에 하나씩 하고, 적용하는 사이 조건이 바뀌면 최신 조건으로 다시 적용한다 (오래된 결과가 덮지 않게)
 * - 갱신 중에는 이전 결과를 보이며 안내하고 클릭을 막는다. 실패하면 안내와 '다시 시도'
 * - 마크 선택(MarkSelectionChanged → getMarksAsync)에서 행정동 코드를 하나 받았을 때만 알리고, 알린 뒤 그 선택을 지운다.
 *   시군구 지도는 읍면동 화면으로 넘어가는 동안 숨겨 두므로, 지우지 않으면 '이전으로'로 돌아왔을 때 그 동이 선택된 채 보이고
 *   같은 동을 다시 누르면 선택이 풀리기만 한다
 * - 조건은 우리 화면 위쪽 필터로만 바꾼다. 잘라 낸 선택 칸도 키보드로는 바꿀 수 있어,
 *   우리가 넘긴 매개변수(⑥의 읍면동·기준월)가 다른 값으로 바뀌면 우리 조건으로 되돌린다
 * - 매개변수 값은 onParameterValue로 알린다 (⑥ 고른 격자 p_selected_grid로 보일 높이를 정한다). 우리가 넘기지 않은 값은 되돌리지 않는다
 */

/** 게시본 설정이 잘못돼 다시 게시해야 하는 오류 (안내 문구를 그대로 보인다) */
class TableauConfigurationError extends Error {}

const LOAD_ERROR = "그래프 연결을 확인한 뒤 다시 시도해 주세요."
const APPLY_ERROR = "선택한 조건의 그래프를 불러오지 못했습니다."
const SELECTION_ERROR = `선택한 행정동을 읽지 못했습니다. Tableau 마크의 세부 정보에 '${TABLEAU_DONG_FIELD}'를 추가해 주세요.`

const sorted = (values: string[]) => JSON.stringify([...values].sort())

/**
 * changeParameterValueAsync에 넣을 값. 목록 매개변수의 값에 별칭이 있으면 별칭으로만 받는다
 * (11/5 확인: ⑥ p_detail_adm에 코드 '1168051000'을 넣으면 bad value, 별칭 '강남구 신사동'은 받는다)
 */
function parameterInput(parameter: Parameter, value: string) {
  const option = parameter.allowableValues?.allowableValues?.find((item) => String(item.value) === value)
  return option?.hasAlias && option.aliasValue ? option.aliasValue : value
}

export function TableauWorksheet({
  dashboard,
  worksheet,
  label,
  width,
  height,
  filters = {},
  parameters = {},
  toolbar = "bottom",
  crop,
  hoverHeight,
  onSelectDong,
  onStateChange,
  onParameterValue,
  refreshKey = 0,
}: TableauWorksheetProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const conditions = { dashboard, worksheet, filters, parameters }
  const conditionsKey = JSON.stringify(conditions)
  const conditionsRef = useRef({ key: conditionsKey, values: conditions })
  conditionsRef.current = { key: conditionsKey, values: conditions }
  const labelRef = useRef(label)
  labelRef.current = label
  const stateCallbackRef = useRef(onStateChange)
  stateCallbackRef.current = onStateChange
  const selectionCallbackRef = useRef(onSelectDong)
  selectionCallbackRef.current = onSelectDong
  const parameterCallbackRef = useRef(onParameterValue)
  parameterCallbackRef.current = onParameterValue
  const syncRef = useRef<(() => void) | null>(null)
  const [state, setState] = useState<ChartState>({ phase: "loading" })
  const [hasRendered, setHasRendered] = useState(false)
  const [retry, setRetry] = useState(0)
  const [selectionError, setSelectionError] = useState("")
  // Tableau Public은 toolbar=hidden을 넘겨도 도구 모음을 그린다 (11/5 확인: 대시보드 높이로 띄우면 아래가 잘린다).
  // 그래서 늘 도구 모음까지 포함한 높이로 띄우고, 숨길 때는 아래 도구 모음 높이만큼 잘라 보인다
  const vizHeight = height + TABLEAU_TOOLBAR_HEIGHT
  const frameHeight = crop ? crop.height : toolbar === "hidden" ? height : vizHeight
  // 일부만 보일 때는 틀을 그 크기로 만들고 Tableau를 위·왼쪽으로 밀어 넣는다 (잘린 부분은 보이지도 눌리지도 않는다)
  const cropStyle = crop
    ? ({ width: crop.width, "--crop-x": `${-crop.x}px`, "--crop-y": `${-crop.y}px` } as CSSProperties)
    : undefined
  // 마우스를 올린 동안 아래 내용 위에 겹쳐 펼친다 (자리는 frameHeight 그대로, CSS :hover가 최소 높이만 hoverHeight로 올린다).
  // 이미 hoverHeight보다 크게 보이면(⑥ 격자 3개 이상) 그대로라 펼쳐지지 않는다. 클래스는 바꾸지 않아 높이 전환이 끊기지 않는다
  const expandable = crop !== undefined && hoverHeight !== undefined
  const grows = expandable && hoverHeight > frameHeight
  const hostStyle: CSSProperties = expandable
    ? ({ ...cropStyle, "--frame-height": `${frameHeight}px`, "--hover-height": `${hoverHeight}px` } as CSSProperties)
    : { ...cropStyle, height: frameHeight }

  useEffect(() => {
    let disposed = false
    let viz: Viz | null = null
    let firstEvent = "firstinteractive"
    let selectionEvent = "markselectionchanged"
    let parameterEvent = "parameterchanged"
    let selectionRevision = 0
    let interactive = false
    let pending = false
    let syncing = false
    let replace: unknown
    let parameterCache: Parameter[] | null = null
    let parameterVersion = 0
    const notify = (next: ChartState) => {
      if (disposed) return
      setState(next)
      if (next.phase === "ready") setHasRendered(true)
      stateCallbackRef.current?.(next)
    }
    notify({ phase: "loading" })
    setHasRendered(false)
    setSelectionError("")

    /** 지금 대시보드 안에서 조건을 걸 워크시트 */
    const targetWorksheet = (dashboardName: string, worksheetName: string): Worksheet => {
      const sheet = viz!.workbook.activeSheet
      const target =
        sheet.name !== dashboardName
          ? undefined
          : sheet.sheetType === "dashboard"
            ? sheet.worksheets.find((item) => item.name === worksheetName)
            : sheet.sheetType === "worksheet" && sheet.name === worksheetName
              ? sheet
              : undefined
      if (!target) {
        throw new TableauConfigurationError(
          `Tableau 게시본에서 ${dashboardName}의 ${worksheetName} 워크시트를 찾지 못했습니다. 게시본 이름을 확인해 주세요.`,
        )
      }
      return target
    }

    // 적용을 한 번에 하나씩 하고, 끝날 때마다 React의 최신 조건과 같은지 본다
    const synchronize = async () => {
      pending = true
      if (!interactive || syncing || !viz) return
      syncing = true
      try {
        while (pending && !disposed) {
          pending = false
          const snapshot = conditionsRef.current
          const wanted = snapshot.values
          notify({ phase: "applying" })
          try {
            // 지표 전환: 같은 워크북 안에서 대시보드만 바꾼다 (매개변수는 워크북 단위라 그대로 남는다)
            if (viz.workbook.activeSheet.name !== wanted.dashboard) {
              await viz.workbook.activateSheetAsync(wanted.dashboard)
              if (disposed) return
            }
            const sheet = targetWorksheet(wanted.dashboard, wanted.worksheet)
            const parameterReadVersion = parameterVersion
            // 읽기는 함께 보내고, 값을 바꾸는 호출은 차례로 보낸다
            const [currentParameters, currentFilters] = await Promise.all([
              Object.keys(wanted.parameters).length
                ? (parameterCache ?? viz.workbook.getParametersAsync())
                : Promise.resolve([]),
              Object.keys(wanted.filters).length ? sheet.getFiltersAsync() : Promise.resolve([]),
            ])
            if (disposed) return

            let parametersChanged = false
            for (const [name, value] of Object.entries(wanted.parameters)) {
              const actual = currentParameters.find((item) => item.name === name)
              if (!actual) {
                throw new TableauConfigurationError(
                  `Tableau 워크북에 ${name} 매개변수가 없습니다. 공통 매개변수를 추가한 뒤 재게시해 주세요.`,
                )
              }
              if (String(actual.currentValue.value) !== value) {
                await viz.workbook.changeParameterValueAsync(name, parameterInput(actual, value))
                parametersChanged = true
                if (disposed) return
              }
            }

            let filtersChanged = false
            for (const [field, values] of Object.entries(wanted.filters)) {
              const actual = currentFilters.find((item) => item.fieldName === field)
              if (values.length) {
                const actualValues = actual?.appliedValues?.map((item) => String(item.value)) ?? []
                if (!actual || actual.isAllSelected || sorted(actualValues) !== sorted(values)) {
                  await sheet.applyFilterAsync(field, values, replace)
                  filtersChanged = true
                }
              } else if (actual && !actual.isAllSelected) {
                // clearFilterAsync는 걸려 있지 않은 필터를 풀면 실패한다
                await sheet.clearFilterAsync(field)
                filtersChanged = true
              }
              if (disposed) return
            }

            // 바꾼 값이 있으면 다시 읽어 실제로 들어갔는지 확인한다
            const parameterVerifyVersion = parameterVersion
            const [actualFilters, actualParameters] = await Promise.all([
              filtersChanged ? sheet.getFiltersAsync() : Promise.resolve(currentFilters),
              parametersChanged || parameterVerifyVersion !== parameterReadVersion
                ? viz.workbook.getParametersAsync()
                : Promise.resolve(currentParameters),
            ])
            if (disposed) return
            for (const [field, expected] of Object.entries(wanted.filters)) {
              const actual = actualFilters.find((item) => item.fieldName === field)
              if (!expected.length) {
                if (actual && !actual.isAllSelected) throw new Error(`Filter was not cleared: ${field}`)
                continue
              }
              const values = actual?.appliedValues?.map((item) => String(item.value)) ?? []
              if (!actual || actual.isAllSelected || sorted(values) !== sorted(expected)) {
                throw new Error(`Filter readback mismatch: ${field}; expected=${sorted(expected)}; actual=${sorted(values)}`)
              }
            }
            if (Object.keys(wanted.parameters).length) {
              for (const [name, expected] of Object.entries(wanted.parameters)) {
                if (String(actualParameters.find((item) => item.name === name)?.currentValue.value) !== expected) {
                  throw new Error(`Parameter readback mismatch: ${name}`)
                }
              }
              parameterCache = parameterVersion === parameterVerifyVersion ? actualParameters : null
            }
            if (snapshot.key !== conditionsRef.current.key) {
              pending = true
              continue
            }
            notify({ phase: "ready" })
          } catch (error) {
            if (disposed) return
            // 적용하는 사이 조건이 바뀌었으면 이번 실패는 버리고 최신 조건으로 다시 적용한다
            if (snapshot.key !== conditionsRef.current.key) {
              pending = true
              continue
            }
            console.error("[TableauWorksheet]", error)
            notify({
              phase: "error",
              message: error instanceof TableauConfigurationError ? error.message : APPLY_ERROR,
            })
          }
        }
      } finally {
        syncing = false
      }
    }
    const requestSync = () => {
      void synchronize()
    }
    syncRef.current = requestSync

    const onFirstInteractive = () => {
      interactive = true
      requestSync()
      // 다시 불러오면(다시 시도) Tableau 쪽 값이 기본값으로 돌아가므로 처음 값을 한 번 알린다
      if (parameterCallbackRef.current) {
        viz!.workbook
          .getParametersAsync()
          .then((list) => {
            if (disposed) return
            for (const item of list) parameterCallbackRef.current?.(item.name, String(item.currentValue.value))
          })
          .catch((error) => {
            if (!disposed) console.error("[TableauWorksheet] Parameter read error", error)
          })
      }
    }
    const onLoadError = (event: Event) => {
      interactive = false
      console.error("[TableauWorksheet] Load error", (event as CustomEvent).detail)
      notify({ phase: "error", message: LOAD_ERROR })
    }
    const onParameterChanged = async (event: Event) => {
      // Tableau 화면 안의 조작·도구 모음이 React 밖에서 값을 바꿀 수 있다
      parameterVersion += 1
      parameterCache = null
      // 대시보드 안의 선택 칸으로 우리가 넘긴 매개변수를 바꾸면 화면과 다른 동·월이 그려진다 (11/5 확인: ⑥ 읍면동).
      // 우리 조건과 다른 값이면 우리 조건으로 되돌린다. 우리가 넣은 값은 조건과 같아서 다시 적용하지 않는다
      if (!interactive) return
      try {
        const detail = (event as CustomEvent<{ getParameterAsync: () => Promise<Parameter> }>).detail
        const parameter = await detail.getParameterAsync()
        if (disposed) return
        parameterCallbackRef.current?.(parameter.name, String(parameter.currentValue.value))
        const wanted = conditionsRef.current.values.parameters[parameter.name]
        if (wanted !== undefined && String(parameter.currentValue.value) !== wanted) requestSync()
      } catch (error) {
        if (disposed) return
        console.error("[TableauWorksheet] Parameter change error", error)
        requestSync()
      }
    }
    const onMarkSelection = async (event: Event) => {
      if (!selectionCallbackRef.current || !interactive || syncing) return
      const revision = ++selectionRevision
      try {
        const detail = (event as CustomEvent<{ getMarksAsync: () => Promise<{ data: MarksTable[] }> }>).detail
        const marks = await detail.getMarksAsync()
        if (disposed || revision !== selectionRevision) return
        const codes = new Set<string>()
        for (const table of marks.data) {
          if (!table.data.length) continue
          const column = table.columns.find(
            (item) => item.fieldName === TABLEAU_DONG_FIELD || item.fieldName === `ATTR(${TABLEAU_DONG_FIELD})`,
          )
          if (!column) throw new Error(`${TABLEAU_DONG_FIELD} is missing from the selected marks`)
          for (const row of table.data) {
            const code = String(row[column.index]?.value ?? "")
            if (!/^\d{10}$/.test(code)) throw new Error("Expected a ten-digit dong code")
            codes.add(code)
          }
        }
        setSelectionError("")
        // 매개변수를 바꿔도 선택이 풀린다. 행정동 하나를 고른 경우만 알리고, 빈 선택으로 화면 조건을 되돌리지 않는다
        if (codes.size !== 1) return
        selectionCallbackRef.current?.([...codes][0])
        // 고른 동은 위에서 넘겼다 (주소에 들어간다). 지우면 빈 선택이 한 번 더 오지만 위에서 알리지 않고 지나간다
        const { dashboard: dashboardName, worksheet: worksheetName } = conditionsRef.current.values
        try {
          await targetWorksheet(dashboardName, worksheetName).clearSelectedMarksAsync()
        } catch (error) {
          // 지우지 못해도 선택이 남아 보일 뿐이다
          if (!disposed) console.error("[TableauWorksheet] Clear selection error", error)
        }
      } catch (error) {
        if (disposed || revision !== selectionRevision) return
        console.error("[TableauWorksheet] Selection error", error)
        setSelectionError(SELECTION_ERROR)
      }
    }

    void (async () => {
      try {
        const { TableauViz, TableauEventType, FilterUpdateType } = await import(/* @vite-ignore */ TABLEAU_MODULE_URL)
        if (disposed) return
        viz = new TableauViz() as Viz
        replace = FilterUpdateType.Replace
        // 대시보드 크기가 고정이라 같은 크기로 띄운다 (더 크면 빈 칸, 작으면 스크롤이 생긴다)
        viz.width = `${width}px`
        viz.height = `${vizHeight}px`
        viz.toolbar = "bottom"
        viz.hideTabs = true
        viz.setAttribute("aria-label", labelRef.current)
        firstEvent = TableauEventType.FirstInteractive
        selectionEvent = TableauEventType.MarkSelectionChanged
        parameterEvent = TableauEventType.ParameterChanged
        viz.addEventListener(firstEvent, onFirstInteractive, { once: true })
        viz.addEventListener(selectionEvent, onMarkSelection)
        viz.addEventListener(parameterEvent, onParameterChanged)
        viz.addEventListener("vizloaderror", onLoadError)
        // 매개변수(시군구·기간)는 첫 화면부터 그 값으로 그리게 한다. 받아들였는지는 FirstInteractive 뒤에 다시 읽어 확인한다
        for (const [name, value] of Object.entries(conditionsRef.current.values.parameters)) {
          const parameter = document.createElement("viz-parameter")
          parameter.setAttribute("name", name)
          parameter.setAttribute("value", value)
          viz.appendChild(parameter)
        }
        viz.src = tableauViewUrl(conditionsRef.current.values.dashboard)
        hostRef.current?.appendChild(viz)
      } catch (error) {
        console.error("[TableauWorksheet]", error)
        notify({ phase: "error", message: LOAD_ERROR })
      }
    })()

    return () => {
      disposed = true
      if (syncRef.current === requestSync) syncRef.current = null
      viz?.removeEventListener(firstEvent, onFirstInteractive)
      viz?.removeEventListener(selectionEvent, onMarkSelection)
      viz?.removeEventListener(parameterEvent, onParameterChanged)
      viz?.removeEventListener("vizloaderror", onLoadError)
      viz?.remove()
    }
  }, [width, vizHeight, retry])

  useEffect(() => {
    syncRef.current?.()
  }, [conditionsKey, refreshKey])

  const ready = state.phase === "ready"
  const updating = state.phase === "applying" && hasRendered
  return (
    <div
      className={expandable ? "tableau-embed has-expandable" : "tableau-embed"}
      style={{ height: frameHeight + (selectionError ? 50 : 0) }}
      aria-label={label}
      aria-busy={state.phase === "loading" || state.phase === "applying"}
      data-chart-state={state.phase}
    >
      {/* 확인 전에는 아래 '불러오는 중' 안내가 덮는다. visibility:hidden으로 숨기면 브라우저가 숨은 iframe을 느리게 돌려
          (11/3 측정: 화면 진입부터 4개 확인까지 4.6~7.3초 → 덮기만 하면 1.7~3.6초) 숨기지 않는다 */}
      <div
        ref={hostRef}
        className={["tableau-host", crop && "is-cropped", expandable && "is-expandable", grows && "is-growing"]
          .filter(Boolean)
          .join(" ")}
        style={{ ...hostStyle, pointerEvents: ready ? undefined : "none" }}
      />
      {updating && (
        <div className="tableau-updating" role="status">
          조건 적용 중 · 이전 결과가 보일 수 있습니다.
        </div>
      )}
      {!ready && !updating && (
        <div className="tableau-loading" role={state.phase === "error" ? "alert" : "status"}>
          <p>{state.phase === "error" ? state.message : "그래프를 불러오는 중입니다."}</p>
          {state.phase === "error" && (
            <button type="button" className="btn btn-outline" onClick={() => setRetry((value) => value + 1)}>
              다시 시도
            </button>
          )}
        </div>
      )}
      <span className="sr-only" role="status" aria-live="polite">
        {ready ? `${label} 조회가 완료되었습니다.` : ""}
      </span>
      {selectionError && (
        <p role="alert" className="tableau-error">
          {selectionError}
        </p>
      )}
    </div>
  )
}
