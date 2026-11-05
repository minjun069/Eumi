// Tableau Embedding API v3에서 이 화면이 쓰는 부분만 적은 타입 (모듈을 실행 중에 불러오므로 공식 타입이 없다)

export type ChartState = {
  phase: "loading" | "applying" | "ready" | "error"
  message?: string
}

export type Conditions = {
  /** 필드 이름 → 값 목록. 빈 목록이면 필터를 푼다 */
  filters: Record<string, string[]>
  /** 매개변수 이름 → 문자열 값 (날짜 매개변수는 YYYY-MM-DD) */
  parameters: Record<string, string>
}

export type Filter = {
  fieldName: string
  isAllSelected?: boolean
  appliedValues?: { value: unknown }[]
}

export type Parameter = { name: string; currentValue: { value: unknown } }

export type MarksTable = {
  columns: { fieldName: string; index: number }[]
  data: { value: unknown }[][]
}

export type Worksheet = {
  name: string
  sheetType: "worksheet"
  applyFilterAsync: (field: string, values: string[], updateType: unknown) => Promise<unknown>
  clearFilterAsync: (field: string) => Promise<unknown>
  getFiltersAsync: () => Promise<Filter[]>
}

export type Dashboard = {
  name: string
  sheetType: "dashboard"
  worksheets: Worksheet[]
}

export type Viz = HTMLElement & {
  src: string
  width: string
  height: string
  toolbar: string
  hideTabs: boolean
  workbook: {
    activeSheet: Worksheet | Dashboard | { name: string; sheetType: "story" }
    activateSheetAsync: (name: string) => Promise<unknown>
    changeParameterValueAsync: (name: string, value: string) => Promise<unknown>
    getParametersAsync: () => Promise<Parameter[]>
  }
}

export type TableauWorksheetProps = {
  /** 같은 워크북 안의 대시보드 이름. 바뀌면 다시 띄우지 않고 띄운 Tableau 안에서 대시보드를 바꾼다 */
  dashboard: string
  /** 대시보드 안의 워크시트 이름 (확인·필터·마크 선택 대상) */
  worksheet: string
  label: string
  /** 대시보드 고정 크기 (도구 모음 제외) */
  width: number
  height: number
  filters?: Conditions["filters"]
  parameters?: Conditions["parameters"]
  /** hidden이면 Tableau가 그린 도구 모음을 아래에서 잘라 숨긴다 (Tableau Public은 숨김 설정을 받지 않는다) */
  toolbar?: "hidden" | "bottom"
  /** 마크에서 행정동 하나를 골랐을 때 (빈 선택은 알리지 않는다) */
  onSelectDong?: (dongCode: string) => void
  onStateChange?: (state: ChartState) => void
  /** 같은 조건으로 '적용'을 다시 눌렀을 때 값을 다시 확인한다 */
  refreshKey?: number
}
