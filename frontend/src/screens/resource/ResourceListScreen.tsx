import { useEffect, useMemo, useState, type FormEvent } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router"
import { EmptyState } from "@/components/common/EmptyState"
import { FieldError } from "@/components/common/FieldError"
import { useDevScenario } from "@/devtools/devScenarioStore"
import { regionApi } from "@/mock/api/regionApi"
import { resourceApi, type ResourceSearchResponse, type ResourceSortKey } from "@/mock/api/resourceApi"
import { PATHS } from "@/routes/paths"
import { ResourceTable } from "@/screens/resource/ResourceTable"
import {
  buildSearch,
  capacityError,
  DEFAULT_FILTERS,
  parseQuery,
  pickFilters,
  toSearchRequest,
  type ResourceListFilters,
  type ResourceListQuery,
} from "@/screens/resource/resourceListQuery"
import type { AgeGroup, Gender } from "@/types/domain"
import { AGE_GROUPS } from "@/utils/age"

type RegionOption = { code: string; name: string }

/**
 * 3.1 복지자원 조회 (6단계)
 * - 3.1.1 검색 필터(지역·연령·성별·정원·담당자 이름), 처음 값은 모두 전체. '검색'을 눌러야 적용
 * - 3.1.2 모든 기관의 복지자원 목록 (W1-A), 진행 중 먼저 + 열 제목 정렬(W6-B), 10개씩 페이지
 * - 3.1.3 등록 이동
 * - 조건·정렬·페이지는 주소에 남는다 (src/screens/resource/resourceListQuery.ts)
 */
export function ResourceListScreen() {
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const search = params.toString()

  const applied = useMemo<ResourceListQuery>(() => parseQuery(new URLSearchParams(search)), [search])

  const [form, setForm] = useState<ResourceListFilters>(pickFilters(applied))
  // 정원 범위 오류는 '검색'을 누른 뒤에 보여 준다
  const [showCapacityError, setShowCapacityError] = useState(false)
  const [nonce, setNonce] = useState(0)
  const [result, setResult] = useState<ResourceSearchResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [sidos, setSidos] = useState<RegionOption[]>([])
  const [sigungus, setSigungus] = useState<RegionOption[]>([])
  const [dongs, setDongs] = useState<RegionOption[]>([])

  // 주소가 바뀌면(검색·정렬·페이지·뒤로 가기) 입력칸도 적용된 조건으로 맞춘다
  useEffect(() => {
    setForm(pickFilters(applied))
    setShowCapacityError(false)
  }, [applied])

  // 적용된 조건으로 목록 조회 (주소가 같아도 '검색'을 누르면 다시 조회)
  useEffect(() => {
    const response = resourceApi.searchResources(toSearchRequest(applied))
    if (response.ok) {
      setResult(response.data)
      setLoadError(null)
    } else {
      setLoadError(response.message)
    }
  }, [applied, nonce])

  // 지역 목록: 시도는 한 번, 시군구·행정동은 위 단계를 고를 때마다
  useEffect(() => {
    const response = regionApi.getSidos("3.1.1")
    if (response.ok) setSidos(response.data.map((item) => ({ code: item.sidoCode, name: item.sidoName })))
  }, [])
  useEffect(() => {
    if (!form.sidoCode) {
      setSigungus([])
      return
    }
    const response = regionApi.getSigungus("3.1.1", { sidoCode: form.sidoCode })
    if (response.ok) {
      setSigungus(response.data.map((item) => ({ code: item.sigunguCode, name: item.sigunguName })))
    }
  }, [form.sidoCode])
  useEffect(() => {
    if (!form.sigunguCode) {
      setDongs([])
      return
    }
    const response = regionApi.getDongs("3.1.1", { sigunguCode: form.sigunguCode })
    if (response.ok) setDongs(response.data.map((item) => ({ code: item.dongCode, name: item.dongName })))
  }, [form.sigunguCode])

  const fill = (patch: Partial<ResourceListFilters>) => setForm((prev) => ({ ...prev, ...patch }))

  useDevScenario(
    {
      screen: "복지자원 목록",
      hint: "채우기 버튼은 입력칸만 바꿉니다. '검색'을 눌러 결과를 확인하세요. 모든 기관의 자원이 보이고, 처음 지역은 전체입니다.",
      actions: [
        {
          label: "고립 위험 탐색에서 옴 (개포1동)",
          run: () => navigate(`${PATHS.resources}?dongCode=1168066000`),
        },
        { label: "노년·여 채우기 ('무관' 포함)", run: () => fill({ ageGroup: "노년", gender: "여" }) },
        { label: "담당자 '박성민' 채우기", run: () => fill({ managerName: "박성민" }) },
        { label: "탈퇴한 담당자 '이수진' 채우기", run: () => fill({ managerName: "이수진" }) },
        { label: "정원 범위 오류 채우기 (50 ~ 10)", run: () => fill({ capacityMin: "50", capacityMax: "10" }) },
        { label: "결과 없는 조건 채우기", run: () => fill({ capacityMin: "500", capacityMax: "" }) },
      ],
    },
    [],
  )

  const rangeError = capacityError(form.capacityMin, form.capacityMax)

  // 주소가 바뀌면 주소 변경으로 조회된다. 주소가 그대로면(같은 조건 재검색) 직접 다시 조회한다.
  const go = (query: ResourceListQuery) => {
    const to = `${PATHS.resources}${buildSearch(query)}`
    if (to === `${location.pathname}${location.search}`) setNonce((value) => value + 1)
    else navigate(to)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (rangeError) {
      setShowCapacityError(true)
      return
    }
    setShowCapacityError(false)
    go({ ...form, sort: applied.sort, direction: applied.direction, page: 1 })
  }

  const reset = () => {
    setForm(DEFAULT_FILTERS)
    setShowCapacityError(false)
  }

  const sortBy = (key: ResourceSortKey) => {
    const direction = applied.sort === key ? (applied.direction === "asc" ? "desc" : "asc") : "asc"
    go({ ...applied, sort: key, direction, page: 1 })
  }

  const update = (patch: Partial<ResourceListFilters>) => setForm({ ...form, ...patch })

  return (
    <section className="screen resource-list">
      <div className="page-heading">
        <div>
          <h1 className="page-title">복지자원 조회</h1>
          <p className="page-desc">지역 복지자원을 검색합니다. 다른 기관의 자원도 함께 보입니다.</p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => navigate(PATHS.resourceNew, { state: { listSearch: location.search } })}
        >
          복지자원 등록
        </button>
      </div>

      <form className="search-panel" onSubmit={submit} noValidate>
        <div className="search-row">
          <span className="search-label">지역</span>
          <div className="search-controls">
            <select
              className="input select"
              aria-label="시도"
              value={form.sidoCode ?? ""}
              onChange={(event) => update({ sidoCode: event.target.value || null, sigunguCode: null, dongCode: null })}
            >
              <option value="">시도 전체</option>
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
              onChange={(event) => update({ sigunguCode: event.target.value || null, dongCode: null })}
            >
              <option value="">시군구 전체</option>
              {sigungus.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}
                </option>
              ))}
            </select>
            <select
              className="input select"
              aria-label="읍면동"
              value={form.dongCode ?? ""}
              disabled={!form.sigunguCode}
              onChange={(event) => update({ dongCode: event.target.value || null })}
            >
              <option value="">읍면동 전체</option>
              {dongs.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
          <span className="search-label">연령</span>
          <select
            className="input select search-short"
            aria-label="연령"
            value={form.ageGroup}
            onChange={(event) => update({ ageGroup: event.target.value as AgeGroup | "전체" })}
          >
            <option value="전체">전체</option>
            {AGE_GROUPS.map((group) => (
              <option key={group} value={group}>
                {group}
              </option>
            ))}
          </select>
          <span className="search-label">성별</span>
          <select
            className="input select search-short"
            aria-label="성별"
            value={form.gender}
            onChange={(event) => update({ gender: event.target.value as Gender | "전체" })}
          >
            <option value="전체">전체</option>
            <option value="남">남</option>
            <option value="여">여</option>
          </select>
        </div>

        <div className="search-row">
          <span className="search-label">정원</span>
          <div className="capacity-range">
            <div className="capacity-inputs">
              <input
                className="input"
                inputMode="numeric"
                aria-label="최소 정원"
                placeholder="최소"
                value={form.capacityMin}
                aria-invalid={showCapacityError && Boolean(rangeError)}
                onChange={(event) => update({ capacityMin: event.target.value })}
              />
              <span aria-hidden="true">~</span>
              <input
                className="input"
                inputMode="numeric"
                aria-label="최대 정원"
                placeholder="최대"
                value={form.capacityMax}
                aria-invalid={showCapacityError && Boolean(rangeError)}
                onChange={(event) => update({ capacityMax: event.target.value })}
              />
              <span className="capacity-unit">명</span>
            </div>
            <FieldError message={showCapacityError ? rangeError : null} />
          </div>
          <span className="search-label">담당자</span>
          <input
            className="input search-manager"
            aria-label="담당자 이름"
            placeholder="담당자 이름"
            value={form.managerName}
            onChange={(event) => update({ managerName: event.target.value })}
          />
          <div className="search-actions">
            <button type="button" className="btn btn-outline" onClick={reset}>
              초기화
            </button>
            <button type="submit" className="btn btn-primary">
              검색
            </button>
          </div>
        </div>
      </form>

      {loadError ? (
        <EmptyState title="목록을 불러오지 못했습니다." description={loadError} />
      ) : result ? (
        <ResourceTable
          result={result}
          sorting={{ sort: applied.sort, direction: applied.direction, onSort: sortBy }}
          onPage={(page) => go({ ...applied, page })}
          onOpen={(resourceId) =>
            navigate(PATHS.resourceDetail(resourceId), { state: { listSearch: location.search } })
          }
        />
      ) : null}
    </section>
  )
}
