/**
 * 시연용으로 미리 띄워 둘 읍면동: 시군구 코드 → 행정동 코드(10자리)
 * - 시군구 화면의 ① 지도가 다 뜬 뒤, 그 시군구 화면의 조건(기간 · 지표)으로 읍면동 화면을 숨긴 채 띄운다 (RiskScreen).
 *   지도에서 그 동을 누르면 ⑥ 격자 지도 · 보고서 그래프를 기다리지 않고 바로 보인다
 * - 목록에 없는 시군구에서는 미리 띄우지 않는다. 시연 동이 바뀌면 여기만 고친다
 */
export const PRELOAD_DONGS: Readonly<Record<string, string>> = {
  // 강남구 역삼1동
  "11680": "1168064000",
}

/** 미리 띄우는 동인지 (행정동 코드 앞 5자리가 시군구 코드다) */
export const isPreloadDong = (dongCode: string) => PRELOAD_DONGS[dongCode.slice(0, 5)] === dongCode
