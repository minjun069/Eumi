import { useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router"
import { EmptyState } from "@/components/common/EmptyState"
import { FieldError } from "@/components/common/FieldError"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { analysisApi } from "@/mock/api/analysisApi"
import { regionApi } from "@/mock/api/regionApi"
import { noteTableau } from "@/mock/tableau/tableauBridge"
import { TABLEAU_VIEWS, tableauViews, type MapTile } from "@/mock/tableau/tableauViews"
import { PATHS } from "@/routes/paths"
import {
  BackgroundDistributionChart,
  DongChangeChart,
  MonthlyBehaviorChart,
  StageDistributionChart,
  TableauMessage,
  TableauPanel,
} from "@/screens/risk/RiskCharts"
import { RiskDongScreen } from "@/screens/risk/RiskDongScreen"
import { DistrictMap } from "@/screens/risk/RiskMaps"
import {
  buildRiskSearch,
  compactPeriod,
  effectivePeriod,
  filtersOf,
  formatMonth,
  INDEX_LABELS,
  parseRiskQuery,
  type RiskFilters,
  type RiskQuery,
} from "@/screens/risk/riskQuery"
import { useSession } from "@/session/sessionStore"
import { useAgentContext } from "@/stores/agentContextStore"
import type { RiskIndex } from "@/types/domain"

type Option = { code: string; name: string }
type MonthsResult = { ok: true; months: string[] } | { ok: false; message: string }
/** 시군구 지도에서 읍면동으로 갈 때 남기는 값: 돌아갈 때 기간이 그대로면 뒤로 가기 */
type DistrictState = { fromDistrict: true; from: string | null; to: string | null }

/**
 * 2.1 고립 위험 탐색 — 시군구 화면 (4단계)
 * - 2.1.1 지역(시도→시군구)·기간(시작 월~종료 월) 필터, '적용'을 눌러야 반영
 * - 2.1.2 ~ 2.1.4 지도·그래프 5개는 Tableau Public 화면을 패널마다 하나씩 넣는다 (T2-B, 여기서는 예시 그림)
 * - 지표 전환(배경 취약성 ↔ 행동 이상)은 우리 화면의 버튼으로 ①·②에 매개변수를 넘긴다 (T3-A)
 * - 지도에서 행정동을 누르면 읍면동 화면으로 (주소에 dong, src/screens/risk/RiskDongScreen.tsx)
 * - 조건은 주소에 남긴다 (R5-A, src/screens/risk/riskQuery.ts)
 */
export function RiskScreen() {
  const session = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const search = params.toString()
  const profile = session.status === "authenticated" ? session.profile : null

  const applied = useMemo<RiskQuery | null>(
    () => (profile ? parseRiskQuery(new URLSearchParams(search), profile) : null),
    [search, profile],
  )

  const [form, setForm] = useState<RiskFilters | null>(applied ? filtersOf(applied) : null)
  const [errors, setErrors] = useState<{ region?: string; period?: string }>({})
  const [nonce, setNonce] = useState(0)
  const [sidos, setSidos] = useState<Option[]>([])
  const [sigungus, setSigungus] = useState<Option[]>([])
  const [sigunguNames, setSigunguNames] = useState<Record<string, string>>({})
  // 시군구별 적재된 월 목록 (이 화면에 있는 동안 시군구마다 한 번만 조회)
  const [monthsBySigungu, setMonthsBySigungu] = useState<Record<string, MonthsResult>>({})
  const requested = useRef(new Set<string>())

  const loadMonths = (sigunguCode: string | null) => {
    if (!sigunguCode || requested.current.has(sigunguCode)) return
    requested.current.add(sigunguCode)
    const result = analysisApi.getLoadedMonths({ sigunguCode })
    setMonthsBySigungu((prev) => ({
      ...prev,
      [sigunguCode]: result.ok ? { ok: true, months: result.data.months } : { ok: false, message: result.message },
    }))
  }

  const appliedSigungu = applied?.sigunguCode ?? null
  const formSigungu = form?.sigunguCode ?? null
  const formSido = form?.sidoCode ?? null

  useEffect(() => loadMonths(appliedSigungu), [appliedSigungu])
  useEffect(() => loadMonths(formSigungu), [formSigungu])

  // 주소가 바뀌면(적용·뒤로 가기) 입력칸도 적용된 조건으로 맞춘다
  useEffect(() => {
    if (!applied) return
    setForm(filtersOf(applied))
    setErrors({})
  }, [applied?.sigunguCode, applied?.from, applied?.to])

  useEffect(() => {
    const result = regionApi.getSidos("2.1.1")
    if (result.ok) setSidos(result.data.map((item) => ({ code: item.sidoCode, name: item.sidoName })))
  }, [])
  useEffect(() => {
    if (!formSido) {
      setSigungus([])
      return
    }
    const result = regionApi.getSigungus("2.1.1", { sidoCode: formSido })
    if (!result.ok) return
    setSigungus(result.data.map((item) => ({ code: item.sigunguCode, name: item.sigunguName })))
    setSigunguNames((prev) => ({
      ...prev,
      ...Object.fromEntries(result.data.map((item) => [item.sigunguCode, item.sigunguName])),
    }))
  }, [formSido])

  const go = (query: RiskQuery, options?: { replace?: boolean; state?: unknown }) => {
    if (!profile) return
    navigate(`${PATHS.risk}${buildRiskSearch(query, profile)}`, options)
  }

  const formMonthsResult = formSigungu ? monthsBySigungu[formSigungu] : undefined
  const formMonths = formMonthsResult?.ok ? formMonthsResult.months : []

  useDevScenario(
    {
      screen: "고립 위험 탐색 (시군구)",
      hint: "채우기 버튼은 입력칸만 바꿉니다. '적용'을 눌러 확인하세요. 지도에서 행정동을 누르면 읍면동 화면으로 갑니다. 상황 전환에서 한도윤(춘천시 관할)으로 바꾸면 데이터 없는 시군구로 열립니다.",
      actions: [
        {
          label: "개포1동 누르기",
          run: () => {
            if (!applied) return
            noteTableau(`${TABLEAU_VIEWS.map}에서 행정동 선택 이벤트`, ["행정동=1168066000(개포1동)"])
            go(
              { ...applied, sigunguCode: "11680", dongCode: "1168066000" },
              { state: { fromDistrict: true, from: applied.from, to: applied.to } satisfies DistrictState },
            )
          },
        },
        {
          label: "데이터 없는 시군구 (춘천시)",
          run: () => setForm({ sidoCode: "51", sigunguCode: "51110", from: null, to: null }),
        },
        {
          label: "시도만 고른 상태",
          run: () => setForm((prev) => (prev ? { ...prev, sidoCode: "11", sigunguCode: null } : prev)),
        },
        {
          label: "기간 오류 (2025-12 ~ 2025-07)",
          run: () => setForm((prev) => (prev ? { ...prev, from: "2025-12", to: "2025-07" } : prev)),
        },
        {
          label: "단일 월 (2025-12)",
          run: () => setForm((prev) => (prev ? { ...prev, from: "2025-12", to: "2025-12" } : prev)),
        },
        {
          label: "첫 적재 월만 (2025-07)",
          run: () => setForm((prev) => (prev ? { ...prev, from: "2025-07", to: "2025-07" } : prev)),
        },
      ],
    },
    [applied],
  )

  if (!profile || !applied || !form) return null

  const appliedMonthsResult = monthsBySigungu[applied.sigunguCode]
  const sigunguName = sigunguNames[applied.sigunguCode] ?? ""

  if (applied.dongCode) {
    if (!appliedMonthsResult) return null
    const months = appliedMonthsResult.ok ? appliedMonthsResult.months : []
    const state = location.state as DistrictState | null
    return (
      <RiskDongScreen
        key={applied.dongCode}
        query={{ ...applied, dongCode: applied.dongCode }}
        months={months}
        nonce={nonce}
        onBack={() => {
          // 시군구 지도에서 왔고 기간을 바꾸지 않았으면 뒤로 가기, 아니면 지금 기간으로 시군구 화면
          if (state?.fromDistrict && state.from === applied.from && state.to === applied.to) navigate(-1)
          else go({ ...applied, dongCode: null }, { replace: true })
        }}
        onApply={(period) => {
          const next: RiskQuery = { ...applied, ...compactPeriod(period, months) }
          const nextUrl = `${PATHS.risk}${buildRiskSearch(next, profile)}`
          if (nextUrl === `${location.pathname}${location.search}`) setNonce((value) => value + 1)
          else navigate(nextUrl, { replace: true, state: location.state })
        }}
      />
    )
  }

  const apply = () => {
    if (!form.sigunguCode) {
      setErrors({ region: "시군구를 선택하세요." })
      return
    }
    const period = effectivePeriod(form, formMonths)
    if (period && period.from > period.to) {
      setErrors({ period: "시작 월이 종료 월보다 늦습니다." })
      return
    }
    setErrors({})
    // 적재된 전체 기간의 끝과 같은 값은 비워 둔다 (주소에서 빠짐)
    const next: RiskQuery = {
      sigunguCode: form.sigunguCode,
      ...(period ? compactPeriod(period, formMonths) : { from: null, to: null }),
      index: applied.index,
      dongCode: null,
    }
    const nextUrl = `${PATHS.risk}${buildRiskSearch(next, profile)}`
    if (nextUrl === `${location.pathname}${location.search}`) setNonce((value) => value + 1)
    else navigate(nextUrl)
  }

  const formPeriod = effectivePeriod(form, formMonths)

  return (
    <section className="screen risk-screen">
      <div className="risk-heading">
        <div>
          <h1 className="page-title">고립 위험 탐색</h1>
          <p className="page-desc">시군구 행정동의 고립 위험을 지도와 그래프로 살펴봅니다.</p>
        </div>
        <div className="risk-filters">
          <div className="risk-filter-group">
            <span className="risk-filter-label">지역</span>
            <div className="risk-filter-controls">
              <select
                className="input select"
                aria-label="시도"
                value={form.sidoCode ?? ""}
                aria-invalid={Boolean(errors.region) && !form.sidoCode}
                onChange={(event) =>
                  setForm({ sidoCode: event.target.value || null, sigunguCode: null, from: null, to: null })
                }
              >
                <option value="">시도 선택</option>
                {sidos.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
              </select>
              <select
                className="input select"
                aria-label="시군구"
                value={form.sigunguCode ?? ""}
                disabled={!form.sidoCode}
                aria-invalid={Boolean(errors.region)}
                onChange={(event) =>
                  setForm({ ...form, sigunguCode: event.target.value || null, from: null, to: null })
                }
              >
                <option value="">시군구 선택</option>
                {sigungus.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
            <FieldError message={errors.region} />
          </div>
          <div className="risk-filter-group">
            <span className="risk-filter-label">기간</span>
            <div className="risk-filter-controls">
              <select
                className="input select risk-month"
                aria-label="시작 월"
                value={formPeriod?.from ?? ""}
                disabled={formMonths.length === 0}
                aria-invalid={Boolean(errors.period)}
                onChange={(event) => setForm({ ...form, from: event.target.value })}
              >
                {formMonths.length === 0 && <option value="">-</option>}
                {formMonths.map((month) => (
                  <option key={month} value={month}>
                    {formatMonth(month)}
                  </option>
                ))}
              </select>
              <span aria-hidden="true">~</span>
              <select
                className="input select risk-month"
                aria-label="종료 월"
                value={formPeriod?.to ?? ""}
                disabled={formMonths.length === 0}
                aria-invalid={Boolean(errors.period)}
                onChange={(event) => setForm({ ...form, to: event.target.value })}
              >
                {formMonths.length === 0 && <option value="">-</option>}
                {formMonths.map((month) => (
                  <option key={month} value={month}>
                    {formatMonth(month)}
                  </option>
                ))}
              </select>
            </div>
            <FieldError message={errors.period} />
          </div>
          <button type="button" className="btn btn-primary risk-apply" onClick={apply}>
            적용
          </button>
        </div>
      </div>

      {!appliedMonthsResult ? null : !appliedMonthsResult.ok ? (
        <EmptyState title={appliedMonthsResult.message} />
      ) : appliedMonthsResult.months.length === 0 ? (
        <EmptyState
          title="적재된 분석 데이터가 없습니다."
          description={`${sigunguName || "이 시군구"}의 분석 결과가 아직 적재되지 않았습니다.`}
        />
      ) : (
        <RiskDashboard
          query={applied}
          sigunguName={sigunguName}
          months={appliedMonthsResult.months}
          nonce={nonce}
          onIndex={(index) => go({ ...applied, index }, { replace: true })}
          onSelectDong={(tile) => {
            noteTableau(`${TABLEAU_VIEWS.map}에서 행정동 선택 이벤트`, [`행정동=${tile.dongCode}(${tile.dongName})`])
            go(
              { ...applied, dongCode: tile.dongCode },
              { state: { fromDistrict: true, from: applied.from, to: applied.to } satisfies DistrictState },
            )
          }}
        />
      )}
    </section>
  )
}

/** Tableau 패널 5개. 화면에 나타날 때·조건이 바뀔 때 Tableau에 넘긴 값을 메모한다 */
function RiskDashboard({
  query,
  sigunguName,
  months,
  nonce,
  onIndex,
  onSelectDong,
}: {
  query: RiskQuery
  sigunguName: string
  months: string[]
  nonce: number
  onIndex: (index: RiskIndex) => void
  onSelectDong: (tile: MapTile) => void
}) {
  const period = effectivePeriod(query, months) ?? { from: months[0], to: months[months.length - 1] }
  const baseMonth = period.to
  const region = `시군구=${query.sigunguCode}(${sigunguName})`
  const indexLabel = INDEX_LABELS[query.index]

  // 처음 띄울 때(<viz-filter>·<viz-parameter>)와 '적용'으로 필터를 바꿀 때
  const shown = useRef(false)
  useEffect(() => {
    noteTableau(shown.current ? "화면 5개에 필터·매개변수 다시 전달 ('적용')" : "화면 5개를 띄우며 넘긴 필터·매개변수", [
      `${TABLEAU_VIEWS.map}: ${region}, 기준 월=${baseMonth}, 지표=${indexLabel}`,
      `${TABLEAU_VIEWS.distribution}: ${region}, 기간=${period.from}~${period.to}, 지표=${indexLabel}`,
      `${TABLEAU_VIEWS.background}: ${region}, 기준 월=${baseMonth}`,
      `${TABLEAU_VIEWS.monthly}: ${region}, 기간=${period.from}~${period.to}`,
      `${TABLEAU_VIEWS.dongChange}: ${region}, 기준 월=${baseMonth}`,
    ])
    shown.current = true
  }, [query.sigunguCode, period.from, period.to, nonce])

  // 지표 전환: ①·②에 매개변수만 넘긴다
  const indexShown = useRef(false)
  useEffect(() => {
    if (indexShown.current) {
      noteTableau("①·②에 지표 매개변수 전달", [
        `${TABLEAU_VIEWS.map}: 지표=${indexLabel}`,
        `${TABLEAU_VIEWS.distribution}: 지표=${indexLabel}`,
      ])
    }
    indexShown.current = true
  }, [query.index])

  const map = tableauViews.map(query.sigunguCode, baseMonth, query.index)
  const distribution = tableauViews.distribution(query.sigunguCode, period.from, period.to, query.index)
  const background = tableauViews.background(query.sigunguCode, baseMonth)
  const monthly = tableauViews.monthly(query.sigunguCode, period.from, period.to)
  const dongChange = tableauViews.dongChange(query.sigunguCode, baseMonth)
  const periodText =
    period.from === period.to ? formatMonth(period.from) : `${formatMonth(period.from)} ~ ${formatMonth(period.to)}`

  // AI Agent가 참고할 화면: 시군구·기간·지표 (0.2.2)
  useAgentContext(
    {
      screen: { screenType: "risk-district", sigunguCode: query.sigunguCode, from: period.from, to: period.to, index: query.index },
      label: `고립 위험 탐색 · ${sigunguName} (${periodText})`,
    },
    [query.sigunguCode, period.from, period.to, query.index, sigunguName],
  )

  return (
    <div className="risk-dashboard">
      <div className="risk-column">
        <TableauPanel
          view="①"
          title={`${sigunguName} 행정동별 고립 위험도 · ${formatMonth(baseMonth)}`}
          actions={
            <div className="index-toggle" role="group" aria-label="지표">
              {(["background", "behavior"] as RiskIndex[]).map((index) => (
                <button
                  key={index}
                  type="button"
                  className={query.index === index ? "is-active" : undefined}
                  aria-pressed={query.index === index}
                  onClick={() => query.index !== index && onIndex(index)}
                >
                  {INDEX_LABELS[index]}
                </button>
              ))}
            </div>
          }
        >
          <DistrictMap tiles={map.tiles} counts={map.counts} onSelect={onSelectDong} />
          <p className="tableau-hint">행정동을 누르면 읍면동 화면으로 이동합니다.</p>
        </TableauPanel>
        <TableauPanel view="②" title={`${sigunguName} 고립 위험도 분포 변화 · ${indexLabel} · ${periodText}`}>
          <StageDistributionChart rows={distribution} />
        </TableauPanel>
      </div>
      <div className="risk-column">
        <TableauPanel view="③" title={`${sigunguName} 행정동별 배경 취약성 분포 · ${formatMonth(baseMonth)}`}>
          {background ? (
            <BackgroundDistributionChart data={background} />
          ) : (
            <TableauMessage>표시할 데이터가 없습니다.</TableauMessage>
          )}
        </TableauPanel>
        <TableauPanel view="④" title={`${sigunguName} 월별 행동 이상 지수 변화 · ${periodText}`}>
          <MonthlyBehaviorChart points={monthly} />
        </TableauPanel>
        <TableauPanel view="⑤" title={`${sigunguName} 행정동별 전월 대비 행동 이상 지수 변화 · ${formatMonth(baseMonth)}`}>
          {dongChange ? (
            <DongChangeChart items={dongChange} />
          ) : (
            <TableauMessage>비교할 전월 데이터가 없습니다.</TableauMessage>
          )}
        </TableauPanel>
      </div>
    </div>
  )
}
