import { useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { errorMessage, isApiError } from "@/api/errors"
import { ORG_SEARCH_LIMIT, signupApi, type OrganizationSearchItem } from "@/api/signupApi"
import { FieldError } from "@/components/common/FieldError"

const KEYWORD_REQUIRED = "기관명을 입력하세요."

/**
 * 회원가입 소속기관 선택 (S7-A: 기관명을 입력해 검색하고 목록에서 고른다, API-04)
 * - 검색어를 고치면 선택이 풀린다(부모가 처리). 검색 결과는 그 결과를 받은 검색어일 때만 보인다
 * - 결과는 최대 20개라, 20개가 오면 기관명을 더 입력하라고 안내한다
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
  const [results, setResults] = useState<{ keyword: string; items: OrganizationSearchItem[] } | null>(null)

  const searchMutation = useMutation({
    mutationFn: signupApi.searchOrganizations,
    onSuccess: (items, word) => {
      onError(null)
      setResults({ keyword: word, items })
    },
    onError: (failure) => {
      setResults(null)
      // 검색어 누락·공백은 400 VALIDATION_ERROR (화면에서 먼저 막지만 서버 검사도 같은 문구로)
      onError(isApiError(failure) && failure.code === "VALIDATION_ERROR" ? KEYWORD_REQUIRED : errorMessage(failure))
    },
  })

  const search = () => {
    if (searchMutation.isPending) return
    const word = keyword.trim()
    if (!word) {
      setResults(null)
      onError(KEYWORD_REQUIRED)
      return
    }
    searchMutation.mutate(word)
  }

  // 검색 뒤 검색어를 고쳤으면 이전 결과는 닫는다
  const shown = results !== null && results.keyword === keyword.trim() && !selected ? results.items : null

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
          maxLength={200}
          aria-invalid={Boolean(error)}
          onChange={(event) => onKeywordChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              search()
            }
          }}
        />
        <button type="button" className="btn btn-outline" onClick={search} disabled={searchMutation.isPending}>
          {searchMutation.isPending ? "검색 중…" : "검색"}
        </button>
      </div>

      {shown !== null && (
        <ul className="org-results" role="listbox" aria-label="기관 검색 결과">
          {shown.length === 0 ? (
            <li className="org-results-empty">검색 결과가 없습니다.</li>
          ) : (
            <>
              {shown.length >= ORG_SEARCH_LIMIT && (
                <li className="org-results-more">기관명을 더 입력하면 결과를 좁힐 수 있습니다.</li>
              )}
              {shown.map((org) => (
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
                      {org.sidoName} {org.sigunguName} · @{org.officialDomain}
                    </span>
                  </button>
                </li>
              ))}
            </>
          )}
        </ul>
      )}

      {selected ? (
        <p className="field-notice">
          선택함: {selected.orgName} · 공식 메일 @{selected.officialDomain}
        </p>
      ) : (
        !error && <p className="field-hint">기관명을 입력하고 '검색'을 눌러 목록에서 고르세요.</p>
      )}
      <FieldError message={error} />
    </div>
  )
}
