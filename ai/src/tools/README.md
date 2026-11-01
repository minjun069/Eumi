# 자료 도구

DB 연결 없이 호출할 수 있는 Python 업무 함수다. 입력은 `TypedDict`, 경계 검증은 Pydantic `TypeAdapter`를 사용한다. State와 그래프 단계는 변경하지 않는다. 호출·검증 이력 기록과 재시도 판단은 작업 선택 및 실행 노드가 담당한다.

## 자료와 오류

`Dataset`은 `reference(id, version)`, `as_of`, `sources(label, uri)`, `columns`, `rows`를 전달한다. 열은 이름·자료형과 단위·공간 단위·시간 단위·분모 정의를 명시한다. 기간 값은 행에 두며 `temporal_unit`에는 월·연도 같은 비교 단위를 둔다. 모르는 비교 기준을 임의로 채우지 않는다.

행은 선언한 열과 정확히 일치해야 한다. 값은 문자열·정수·유한 실수·불리언·null만 받으며 자료형 자동 변환, NaN과 무한대는 허용하지 않는다. 자료 참조·버전·출처는 공급자가 실제 값으로 제공한다. 조회 결과는 `inputs`에 원본 참조를 보존하고, 내용 해시로 결과 참조를 만든다. 결과 객체는 원본과 격리된다.

형식·자료 오류는 `ToolFailure`로 전달한다. 형식 오류는 `invalid_input`, 공급 자료 오류는 `invalid_data`, 없는 필드는 `invalid_field`다. 예외 원인은 Python 예외 체인에 남긴다. 도구는 실패를 빈 결과로 바꾸거나 자동 재시도하지 않는다.

## 검색·조회

`query_data(request, providers)`는 등록된 대상의 공급 함수 `Callable[[], Dataset]`를 실행한다. 연결 코드는 접근이 허용된 공급자만 등록하고, 공급자는 실제 자료원의 권한을 검사한다. 이 등록 목록 자체가 서비스 사용자 인증을 대체하지 않는다.

| 입력 | 동작 |
| --- | --- |
| `target` | 등록된 자료 ID. 임의 SQL·테이블 이름은 받지 않음 |
| `version`, `as_of` | 제공된 경우 실제 버전·기준 시점과 정확히 일치 검사 |
| `filters` | AND 조건. `eq/ne/lt/le/gt/ge/contains/is_null` 지원. `contains`는 대소문자를 무시한 부분 문자열 검색 |
| `fields` | 반환할 열. 생략하면 전체 열 |
| `sort` | 열별 오름·내림차순. null은 항상 마지막, 동률은 공급 자료 순서 유지 |
| `offset`, `limit` | 기본 0·100, 최대 10,000행. 다음 페이지는 원본 `version` 필수 |

반환값은 `data`, 실제 적용한 `applied`, 필터 후 전체 건수 `total`, 반환 건수 `returned`, `next_offset`이다. 다음 페이지는 `applied`에 반환된 원본 버전을 유지하고 offset을 바꾸어 호출한다. 공급자는 한 버전에서 일관된 내용과 행 순서를 반환해야 한다. 현재는 공급된 전체 스냅샷을 메모리에서 조회하며 DB 쿼리 최적화·벡터 검색·문서 분할 RAG는 구현하지 않는다.

등록되지 않은 대상은 `reference_not_found`, 공급자 참조 불일치는 `reference_mismatch`, 페이지 버전 누락은 `version_required`, 버전·시점 불일치는 `version_mismatch/as_of_mismatch`, 조건 자료형 오류는 `invalid_condition`이다. `PermissionError`는 `permission_denied`, `TimeoutError/ConnectionError`는 재시도 가능한 `read_unavailable`로 전달한다. 그 외 공급자 예외는 그대로 전파하여 구현 오류를 숨기지 않는다. 정상 조회 0건은 성공이다.

## 데이터 가공

`process_data(request)`는 조회 결과의 `data` 또는 같은 계약의 전달 자료를 받아 `operations` 순서대로 처리한다. 원본을 수정하지 않고 결과 참조·모든 입력 참조·출처·연산과 행 수를 반환한다. 자료를 다시 읽지 않으므로 전달한 스냅샷의 실제 버전이 유지된다.

| 연산 | 입력·처리 |
| --- | --- |
| `calculate` | `before/after/output`, `difference`는 after−before, `ratio`는 after/before, `percent_change`는 (after−before)/before×100 |
| `aggregate` | `field/group_by/output`, `sum/mean/min/max/count`. count는 해당 필드의 행 수이며 결측 정책 적용 |
| `join` | 오른쪽 `right` 자료, 같은 이름의 `keys`, `inner/left`, 원본→출력 열 이름인 `fields`. 오른쪽 키 중복·null, 왼쪽 null 키, 열 덮어쓰기 거부 |
| `filter` | 조회와 같은 `conditions`를 순서 중간에 적용 |
| `cast` | `field/kind`로 string/integer/number 명시 변환. 소수의 정수 절삭과 불리언의 수치 변환 거부 |

계산 전 두 열의 단위·공간 및 시간 단위·분모 정의를 비교한다. 결합은 기준 시점이 같은 자료를 받으며 키의 자료형과 비교 기준도 검사한다. inner는 대응 없는 왼쪽 행을 제외하고, left는 새 열을 null로 보존한다. 다대다 결합이나 자동 열 이름 변경은 수행하지 않는다.

`missing`은 기본 `error`다. `drop`은 연산에 필요한 값이 없는 행을 제외하고, `preserve`는 계산 결과를 null로 보존한다. preserve 집계에서 한 그룹에 결측값이 있으면 그 그룹의 집계도 null이다. 필터의 null 조건과 결합의 대응 없음은 각 연산의 명시적 의미를 따른다. 결측을 0으로 채우지 않는다. `fields`는 최종 반환 열, `decimals`는 최종 실수 반올림 자릿수(0~12)다.

반환값의 `counts`는 각 연산의 입력·출력·제외 행 수이며, `excluded_rows`는 단계별 제외 수의 합이다. 집계로 합쳐진 행은 제외 수에 넣지 않는다. 빈 자료의 집계는 빈 결과이며 0이라는 측정값을 생성하지 않는다.

주요 실패 코드는 `incompatible_units`, `non_numeric_field`, `missing_value`, `zero_denominator`, `non_finite_result`, `duplicate_field`, `as_of_mismatch`, `join_key_mismatch`, `ambiguous_join`, `missing_join_key`, `invalid_cast`다. 위험지수 산출 모델이나 임의 Python·SQL 실행은 제공하지 않는다.

## 검증

`ai/`에서 `.venv/Scripts/python -m pytest tests/tools -q`를 실행한다. 외부 자료 공급만 합성 자료로 대체하며 실제 도구 함수를 검증한다. 실제 DB·인증·서비스 API와 Agent의 도구 선택 품질은 이 검증에 포함하지 않는다.
