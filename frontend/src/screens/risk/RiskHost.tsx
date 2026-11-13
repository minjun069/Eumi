import { useState } from "react"
import type { Location } from "react-router"
import { PATHS } from "@/routes/paths"
import type { DistrictState } from "@/screens/risk/riskQuery"
import { RiskScreen } from "@/screens/risk/RiskScreen"

/** 메뉴 링크가 갈 곳 */
export type RiskMenuLink = { pathname: string; search: string; state: unknown }

/**
 * 메뉴의 '고립 위험 탐색'이 갈 곳: 마지막으로 본 주소와 navigation state.
 * 시군구 지도에서 온 읍면동 화면이면 메뉴로 돌아왔다고 표시한다 ('이전으로'가 뒤로 가기로 다른 메뉴에 가지 않게)
 */
export function riskMenuLink(location: Location): RiskMenuLink {
  const state = location.state as DistrictState | null
  return {
    pathname: location.pathname,
    search: location.search,
    state: state?.fromDistrict ? { ...state, viaMenu: true } : location.state,
  }
}

/**
 * 고립 위험 탐색 화면을 둘 주소. 지금 /risk이면 지금 주소, 다른 메뉴에 있으면 마지막으로 본 /risk 주소(navigation state 포함).
 * 한 번도 보지 않았거나 로그인 사용자가 바뀌었으면 null
 */
export function useKeptRiskLocation(location: Location, memberId: number | null): Location | null {
  const onRisk = location.pathname === PATHS.risk
  const [kept, setKept] = useState<{ memberId: number | null; location: Location } | null>(null)
  // 렌더 중에 마지막 주소를 기억한다 (값이 같으면 다시 정하지 않는다)
  if (onRisk && (kept?.location !== location || kept.memberId !== memberId)) setKept({ memberId, location })
  if (onRisk) return location
  return kept && kept.memberId === memberId ? kept.location : null
}

/**
 * 고립 위험 탐색 화면을 메뉴를 옮겨도 지우지 않고 숨겨 두는 자리 (AppLayout 본문, 각 메뉴 화면 앞)
 * - 다른 메뉴로 가면 마지막 /risk 주소로 멈춘 채 숨긴다(높이 0 · 보이지 않음 · inert). 돌아오면 Tableau를 다시 띄우지 않고 바로 보인다
 * - 숨긴 동안에도 Tableau는 떠 있다 (메모리: 시군구 · 시연 동 · 다른 읍면동을 모두 두면 약 1.0GB, 11/12 측정)
 * - 로그인 사용자가 바뀌면 AppLayout이 본문을 다시 그리므로 함께 비워진다
 */
export function RiskHost({ location, active }: { location: Location; active: boolean }) {
  return (
    <div className={active ? undefined : "risk-kept"} inert={!active}>
      <RiskScreen location={location} active={active} />
    </div>
  )
}
