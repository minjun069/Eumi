import { useEffect, useState } from "react"
import { FieldError } from "@/components/common/FieldError"
import { signupApi, type OrganizationSearchItem } from "@/mock/api/signupApi"

/**
 * 회원가입 소속기관 선택 (S7-A: 기관명을 입력해 검색하고 목록에서 고른다)
 * 검색어를 고치면 선택이 풀린다(부모가 처리).
 */
export function OrgSearchField({
  keyword,
  onKeywordChange,
  selected,
  onSelect,
  error,
  onError,
}: {
  keyword: string
  onKeywordChange: (keyword: string) => void
  selected: OrganizationSearchItem | null
  onSelect: (org: OrganizationSearchItem) => void
  error?: string | null
  onError: (message: string | null) => void
}) {
  // null: 검색 전이거나 목록을 닫은 상태
  const [results, setResults] = useState<OrganizationSearchItem[] | null>(null)

  // 검색어가 바뀌면 이전 검색 결과는 닫는다
  useEffect(() => {
    setResults(null)
  }, [keyword])

  const search = () => {
    const word = keyword.trim()
    if (!word) {
      onError("기관명을 입력하세요.")
      return
    }
    const result = signupApi.searchOrganizations({ keyword: word })
    if (!result.ok) {
      onError(result.message)
      return
    }
    onError(null)
    setResults(result.data)
  }

  return (
    <div className="field org-search">
      <span>
        소속기관 <em className="required">*</em>
      </span>
      <div className="input-with-button">
        <input
          className="input"
          value={keyword}
          placeholder="기관명으로 검색"
          aria-invalid={Boolean(error)}
          onChange={(event) => onKeywordChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              search()
            }
          }}
        />
        <button type="button" className="btn btn-outline" onClick={search}>
          검색
        </button>
      </div>

      {results !== null && !selected && (
        <ul className="org-results" role="listbox" aria-label="기관 검색 결과">
          {results.length === 0 ? (
            <li className="org-results-empty">검색 결과가 없습니다.</li>
          ) : (
            results.map((org) => (
              <li key={org.orgId}>
                <button
                  type="button"
                  role="option"
                  aria-selected={false}
                  onClick={() => {
                    onSelect(org)
                    setResults(null)
                  }}
                >
                  <strong>{org.orgName}</strong>
                  <span>
                    {org.sidoName} {org.sigunguName} ·{" "}
                    {org.officialDomain ? `@${org.officialDomain}` : "공식 메일 도메인 없음"}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}

      {selected ? (
        <p className="field-notice">
          선택함: {selected.orgName} ·{" "}
          {selected.officialDomain
            ? `공식 메일 @${selected.officialDomain}`
            : "공식 메일 도메인 없음"}
        </p>
      ) : (
        !error && <p className="field-hint">기관명을 입력하고 '검색'을 눌러 목록에서 고르세요.</p>
      )}
      <FieldError message={error} />
    </div>
  )
}
