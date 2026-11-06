import { useQuery } from "@tanstack/react-query"
import { regionApi, regionKeys } from "@/api/regionApi"

type Option = { code: string; name: string }

export type RegionValue = {
  sidoCode: string | null
  sigunguCode: string | null
  dongCode: string | null
}

/**
 * 지역 목록 (API-39~41): 시도는 한 번, 시군구·행정동은 위 단계를 고를 때마다 받는다.
 * 사례자 목록의 검색 조건과 등록·수정 화면이 함께 쓴다
 */
export function useRegionOptions(sidoCode: string | null, sigunguCode: string | null) {
  const sidos = useQuery({ queryKey: regionKeys.sidos, queryFn: regionApi.getSidos })
  const sigungus = useQuery({
    queryKey: regionKeys.sigungus(sidoCode ?? ""),
    queryFn: () => regionApi.getSigungus(sidoCode ?? ""),
    enabled: Boolean(sidoCode),
  })
  const dongs = useQuery({
    queryKey: regionKeys.dongs(sigunguCode ?? ""),
    queryFn: () => regionApi.getDongs(sigunguCode ?? ""),
    enabled: Boolean(sigunguCode),
  })
  return {
    sidos: (sidos.data ?? []).map((item): Option => ({ code: item.sidoCode, name: item.sidoName })),
    sigungus: sidoCode
      ? (sigungus.data ?? []).map((item): Option => ({ code: item.sigunguCode, name: item.sigunguName }))
      : [],
    dongs: sigunguCode ? (dongs.data ?? []).map((item): Option => ({ code: item.dongCode, name: item.dongName })) : [],
    /** 목록을 받지 못했을 때 입력칸 아래에 보여 줄 문구 */
    error:
      sidos.isError || (sidoCode && sigungus.isError) || (sigunguCode && dongs.isError)
        ? "지역 목록을 불러오지 못했습니다."
        : null,
  }
}

/**
 * 시도 → 시군구 → 읍면동 고르기 (입력 화면용, 사례자는 읍면동까지 골라야 한다).
 * 위 단계를 바꾸면 아래 단계는 비운다.
 * allowWholeSigungu: 읍면동을 비우면 '시군구 전체' (복지자원 W2-B)
 */
export function RegionSelects({
  value,
  invalid,
  allowWholeSigungu = false,
  onChange,
}: {
  value: RegionValue
  invalid: boolean
  allowWholeSigungu?: boolean
  onChange: (value: RegionValue) => void
}) {
  const { sidos, sigungus, dongs, error } = useRegionOptions(value.sidoCode, value.sigunguCode)

  return (
    <>
      <div className="region-selects">
        <select
          className="input select"
          aria-label="시도"
          value={value.sidoCode ?? ""}
          aria-invalid={invalid && !value.sidoCode}
          onChange={(event) => onChange({ sidoCode: event.target.value || null, sigunguCode: null, dongCode: null })}
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
          value={value.sigunguCode ?? ""}
          disabled={!value.sidoCode}
          aria-invalid={invalid && Boolean(value.sidoCode) && !value.sigunguCode}
          onChange={(event) => onChange({ ...value, sigunguCode: event.target.value || null, dongCode: null })}
        >
          <option value="">시군구 선택</option>
          {sigungus.map((item) => (
            <option key={item.code} value={item.code}>
              {item.name}
            </option>
          ))}
        </select>
        <select
          className="input select"
          aria-label="읍면동"
          value={value.dongCode ?? ""}
          disabled={!value.sigunguCode}
          aria-invalid={invalid && Boolean(value.sigunguCode) && !allowWholeSigungu}
          onChange={(event) => onChange({ ...value, dongCode: event.target.value || null })}
        >
          <option value="">{allowWholeSigungu && value.sigunguCode ? "시군구 전체" : "읍면동 선택"}</option>
          {dongs.map((item) => (
            <option key={item.code} value={item.code}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      {error && <p className="field-hint">{error}</p>}
    </>
  )
}
