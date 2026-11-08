# 자료 도구

## Tableau 시각화 검증

`validate_visualization(request, state=state)`는 선택한 뷰의 입력 프로필에 따라 매개변수·필터·필수값·날짜 순서·필터 의존 조건을 검사하고 `valid`, `issues`, `artifact`를 반환한다. 외부 호출은 없으며 부적합한 입력은 산출물 없이 구체적인 수정 정보를 반환한다. 입력·반환 계약과 실제 Agent 연결은 [Tableau 시각화 실행](../../docs/TABLEAU.md)을 따른다. 아래 HTML 렌더러는 직접 사용 예제와 비교 근거표 생성용으로 유지하며 Agent가 선택하는 시각화는 Tableau 검증 도구다.

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
| `calculate` | `before/after/output`, `difference`는 after−before, `ratio`는 after/before, `percentage`는 after/before×100, `percent_change`는 (after−before)/before×100 |
| `sort` | `by: [{field, descending}]` 순서로 정렬. null은 항상 마지막, 동률은 이전 순서 유지 |
| `aggregate` | `field/group_by/output`, `sum/mean/min/max/count`. count는 해당 필드의 행 수이며 결측 정책 적용 |
| `join` | 오른쪽 `right` 자료, 같은 이름의 `keys`, `inner/left`, 원본→출력 열 이름인 `fields`. 오른쪽 키 중복·null, 왼쪽 null 키, 열 덮어쓰기 거부 |
| `filter` | 조회와 같은 `conditions`를 순서 중간에 적용 |
| `cast` | `field/kind`로 string/integer/number 명시 변환. 소수의 정수 절삭과 불리언의 수치 변환 거부 |

계산 전 두 열의 단위·공간 및 시간 단위·분모 정의를 비교한다. 결합은 기준 시점이 같은 자료를 받으며 키의 자료형과 비교 기준도 검사한다. inner는 대응 없는 왼쪽 행을 제외하고, left는 새 열을 null로 보존한다. 다대다 결합이나 자동 열 이름 변경은 수행하지 않는다.

`missing`은 기본 `error`다. `drop`은 연산에 필요한 값이 없는 행을 제외하고, `preserve`는 계산 결과를 null로 보존한다. preserve 집계에서 한 그룹에 결측값이 있으면 그 그룹의 집계도 null이다. 필터의 null 조건과 결합의 대응 없음은 각 연산의 명시적 의미를 따른다. 결측을 0으로 채우지 않는다. `fields`는 최종 반환 열, `decimals`는 최종 실수 반올림 자릿수(0~12)다.

반환값의 `counts`는 각 연산의 입력·출력·제외 행 수이며, `excluded_rows`는 단계별 제외 수의 합이다. 집계로 합쳐진 행은 제외 수에 넣지 않는다. 빈 자료의 집계는 빈 결과이며 0이라는 측정값을 생성하지 않는다.

주요 실패 코드는 `incompatible_units`, `non_numeric_field`, `missing_value`, `zero_denominator`, `non_finite_result`, `duplicate_field`, `as_of_mismatch`, `join_key_mismatch`, `ambiguous_join`, `missing_join_key`, `invalid_cast`다. 위험지수 산출 모델이나 임의 Python·SQL 실행은 제공하지 않는다.

## 시각화 렌더링

`render_visualization({data, spec})`는 독립 HTML 내용을 담은 `artifact`, 적용한 `applied`, 자료 참조·출처·기준 시점·주의사항을 반환한다. artifact는 현재 `response.artifacts`의 `{type, data}` 형식에 맞으며 `data`는 `mime_type="text/html"`, `content`다. 응답 작성 노드가 공개할 산출물을 선택한다. 렌더러는 State를 갱신하거나 파일을 저장하지 않는다.

| 유형 | 명세와 결과 |
| --- | --- |
| `table` | title, 선택 fields. 실제 값·단위·결측을 HTML 셀에 표시. 빈 자료는 빈 표와 안내 |
| `bar/line` | title, x, y, unit. 축 이름 x_label/y_label, legend, HEX color, value_range 선택. SVG와 원본 수치 표 생성. bar는 orientation=horizontal로 가로 막대·소수점 첫째 자리 수치 표시 가능 |
| `map` | title, region, value, unit, code_system, boundaries. legend, HEX color, value_range 선택. SVG 지역별 색상 지도와 수치 표 생성 |

수치 열의 단위가 요청 단위와 같아야 한다. 차트 가로축은 중복·결측이 없는 입력 행 순서의 등간격 범주다. 선 차트는 날짜 간격 비례 축을 제공하지 않으며 해당 안내를 반환한다. 최대 200개 행을 받으며 더 큰 자료는 먼저 가공한다. 결측은 0으로 표시하지 않고 선도 연결하지 않는다. 막대 범위는 반드시 0과 모든 값을 포함하며 임의 범위에 맞춰 값을 잘라내지 않는다. 전체가 결측이거나 빈 자료면 `no_plottable_data`로 실패한다.

지도 `boundaries`에는 참조·버전·기준 시점·출처, `code_system`, `crs="EPSG:4326"`, `features`를 전달한다. 각 feature는 code와 GeoJSON 형식의 Polygon/MultiPolygon geometry를 가진다. 경위도 쌍·닫힌 고리·면적을 검사한다. 데이터 지역 열의 unit은 같은 지역코드 체계명이어야 한다. 중복 코드·대응 경계 없음·다른 좌표계는 거부한다. 자료가 없는 경계는 회색으로 표시한다. 경계 기준 시점은 수치 자료와 별도로 보존한다. 중심 위도로 보정한 참고 지도이며 전문 GIS 투영·위상 검증·타일 서비스·좌표 점 지도는 제공하지 않는다.

HTML/SVG는 입력 텍스트를 이스케이프하고 스크립트·외부 리소스를 넣지 않는다. 출처 주소는 텍스트로 보존한다. 파일 보관·조회 URL·프론트 삽입 방식·접근 권한은 서비스 연동에서 결정한다. 브라우저에서 `content`를 표시할 때는 서비스의 산출물 표시 정책을 적용해야 한다.

주요 실패 코드는 `incompatible_units`, `invalid_range`, `ambiguous_axis`, `too_many_marks`, `region_code_mismatch`, `ambiguous_region`, `boundary_not_found`, `invalid_boundary`, `unsupported_bounds`다.

## 호출 인터페이스와 실행 예제

`create_tools(providers, state=state)`는 LangChain `BaseTool` 목록을 반환한다. 도구 이름은 `query_data`, `process_data`, `render_visualization`, `validate_visualization`이며 인자와 결과는 위 Python 함수와 같다. 공급자 목록은 생성 시 복사한다. 현재 실행의 State를 전달하며 시각화 명세·검증은 execution.event에 배정된 뷰만 허용한다. 입력 JSON 스키마는 같은 TypeAdapter에서 생성하고 실제 함수 경계에서도 검사한다. 도구 호출 결과는 일반 결과 객체 또는 표준 ToolMessage로 전달되며 `ToolMessage.artifact`에 별도 상태를 숨기지 않는다.

```python
from src.tools.interface import create_tools

# read_activity는 실제 버전·출처와 열 정의가 있는 Dataset을 반환하는 함수다.
tools = {tool.name: tool for tool in create_tools({"activity": read_activity}, state=state)}
queried = tools["query_data"].invoke({"target": "activity", "limit": 100})
processed = tools["process_data"].invoke(
    {
        "data": queried["data"],
        "operations": [
            {
                "operation": "calculate",
                "method": "percent_change",
                "before": "before",
                "after": "after",
                "output": "change",
            }
        ],
        "missing": "preserve",
        "decimals": 1,
    }
)
rendered = tools["render_visualization"].invoke(
    {
        "data": processed["data"],
        "spec": {
            "type": "bar",
            "title": "변화율",
            "x": "region",
            "y": "change",
            "unit": "%",
        },
    }
)
```

`ainvoke`도 LangChain의 표준 비동기 인터페이스로 호출할 수 있다. 현재 공급 함수는 동기 함수이며 비동기 호출 시 라이브러리의 실행 스레드를 사용한다. 도구는 자동 재시도하지 않는다. 조회는 공급자에게 읽기 작업만 연결한다. `retry_safe` 메타데이터는 읽기·순수 계산·메모리 렌더링의 재실행 가능 여부를 나타내며 재시도 횟수·한도 판단을 대신하지 않는다.

`ai/`에서 `python tool_demo.py --output outputs/tool-demo`를 실행하면 합성 자료 공급자를 실제 도구에 연결해 A/B/C의 -10%/-8%/-10% 변화율을 계산하고 `table.html`, `bar.html`, `line.html`, `map.html`, `report.json`을 생성한다. 합성 자료는 `experiments/tool_fixtures.py`, 예제 조립과 파일 저장은 `tool_demo.py`에 둔다. 도구 모듈에는 모의 응답이나 데모 분기를 넣지 않는다.

`src/agent_nodes.py`는 공통 그래프에 실제 업무 노드·모델·도구 선택을 연결한다. 작업 선택 및 실행 노드가 호출 결과를 `results[].output`에 기록하고 응답 작성 노드가 검증된 `artifact`를 선택한다. DB·HTTP·프론트 채팅 서비스 연동은 별도 구현 대상이다.

## 검증

`ai/`에서 `.venv/Scripts/python -m pytest tests/tools -q`를 실행한다. 외부 자료 공급만 합성 자료로 대체하며 실제 도구 함수를 검증한다. 실제 DB·인증·서비스 API와 Agent의 도구 선택 품질은 이 검증에 포함하지 않는다.

렌더러 검증은 HTML 셀·SVG 구조·실제 수치·출처·안전한 텍스트·현재 산출물 계약을 확인한다. 자동 브라우저의 로컬 파일 접근이 차단되어 실제 브라우저 화면의 시각적 검수는 수행하지 않았다.

2026-11-01 검증: 도구 테스트 73개, 기존 공통 그래프·데모 29개, 합계 **102개 통과**. 새 코드의 Ruff 검사·포맷 검사와 실제 예제 실행도 통과했다. Windows 샌드박스에서 asyncio 내부 socketpair 생성이 대기해 해당 검증은 샌드박스 밖에서 수행했다. pytest 임시 경로는 작업 폴더의 `outputs/` 아래에 지정했다.

기존 전체 테스트는 제거된 `Agent`, `Info`, `result_adapter`를 참조하는 세 파일의 수집 오류가 있어 전체 통과로 보고하지 않는다. 이 문제는 도구 변경 전에도 존재했으며 기존 사용자 변경과 함께 유지했다.
