import { useEffect, useState } from "react"
import { regionApi } from "@/mock/api/regionApi"

type Option = { code: string; name: string }

export type RegionValue = {
  sidoCode: string | null
  sigunguCode: string | null
  dongCode: string | null
}

/**
 * 시도 → 시군구 → 읍면동 고르기 (입력 화면용, 사례자는 읍면동까지 골라야 한다).
 * 위 단계를 바꾸면 아래 단계는 비운다. 목록은 위 단계를 고를 때마다 지역 목록 API로 받아 온다.
 * allowWholeSigungu: 읍면동을 비우면 '시군구 전체' (복지자원 W2-B)
 */
export function RegionSelects({
  featureId,
  value,
  invalid,
  allowWholeSigungu = false,
  onChange,
}: {
  /** API 기록에 남길 기능 ID (예: "4.2.1") */
  featureId: string
  value: RegionValue
  invalid: boolean
  allowWholeSigungu?: boolean
  onChange: (value: RegionValue) => void
}) {
  const [sidos, setSidos] = useState<Option[]>([])
  const [sigungus, setSigungus] = useState<Option[]>([])
  const [dongs, setDongs] = useState<Option[]>([])

  useEffect(() => {
    const result = regionApi.getSidos(featureId)
    if (result.ok) setSidos(result.data.map((item) => ({ code: item.sidoCode, name: item.sidoName })))
  }, [featureId])

  useEffect(() => {
    if (!value.sidoCode) {
      setSigungus([])
      return
    }
    const result = regionApi.getSigungus(featureId, { sidoCode: value.sidoCode })
    if (result.ok) {
      setSigungus(result.data.map((item) => ({ code: item.sigunguCode, name: item.sigunguName })))
    }
  }, [featureId, value.sidoCode])

  useEffect(() => {
    if (!value.sigunguCode) {
      setDongs([])
      return
    }
    const result = regionApi.getDongs(featureId, { sigunguCode: value.sigunguCode })
    if (result.ok) setDongs(result.data.map((item) => ({ code: item.dongCode, name: item.dongName })))
  }, [featureId, value.sigunguCode])

  return (
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
  )
}
