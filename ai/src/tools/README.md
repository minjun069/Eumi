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

## 검증

`ai/`에서 `.venv/Scripts/python -m pytest tests/tools -q`를 실행한다. 외부 자료 공급만 합성 자료로 대체하며 실제 도구 함수를 검증한다. 실제 DB·인증·서비스 API와 Agent의 도구 선택 품질은 이 검증에 포함하지 않는다.
