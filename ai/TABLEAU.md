# Tableau 시각화 실행

자연어 요청에서 게시된 Tableau 뷰와 조건을 선택하고, 결정론적 검증을 통과한 `tableau` 산출물을 반환한다. 요청마다 Tableau API·헤드리스 브라우저를 호출하지 않는다. 실제 화면 로딩·필터 적용 확인은 프론트의 책임이다.

## 지침과 실행 연결

- [시각화 작업 선택](src/instructions/visualization-selection.md): 목적별 뷰, 기간 의미, 조건 결정, 지원하지 않는 요청 처리.
- [시각화 작업 선택 시 도구 사용](src/instructions/visualization-tool.md): 입력·오류 처리·재작업·산출물 선택·프론트 전달 조건.
- `build_nodes(..., role="request" | "visualization")`가 두 지침을 읽는다. 작업 목적 파악에는 선택 지침·뷰 요약, 작업 선택에는 두 지침·뷰 요약·공유 입력 프로필을 제공한다. 검증·진행 판단·응답 작성·질문 작성에는 전체 지침·카탈로그를 반복 첨부하지 않고 실제 요청·호출 결과를 사용한다.
- `visualization_catalog.views`의 목적·한계는 등록 명세에서 가져온다. `input_profiles`는 같은 규격을 한 번만 전달하고, 매개변수별 전체 필터 목록은 생략한다. 기존 산출물·호출 이력으로 확인한 매개변수의 상세값은 `selected`에 제공한다. 처음 요청한 필터값은 사용자가 명시한 값으로 검증하며 부적합 사유에 해당 조건의 허용값이 반환된다. 상세 조회를 위한 모델 왕복은 추가하지 않는다.
- `create_tools()`의 `validate_visualization`을 실제 작업 선택 및 실행 노드에서 호출한다. 정상 결과는 기존 모델 검증에서 요청 목적과의 일치를 판단하고, 응답 작성에서 검증된 호출 ID로 원본 산출물을 선택한다.
- `valid=false`는 검사 완료 결과다. 부적합 사유를 별도 검증 이력에 남기고 공개 후보에서 제외한다. 모델은 조건을 수정하거나 필요한 정보를 요청하며, 같은 도구의 부적합 호출도 기존 재시도 한도에 포함한다.

HTML 렌더러는 직접 도구 사용 예제와 조회·가공 근거 비교표 생성에 남아 있다. Agent의 시각화 작업 선택에서는 게시된 Tableau 검증 도구를 사용한다. 합성 가구 비율로 임의 막대 차트를 생성하던 기존 S2 시나리오는 현재 Tableau 지원 범위를 검증하는 시나리오가 아니다.

## 등록 설정

### 실행별 허용 뷰

호출 측이 `allowed_view_keys`로 실행 범위를 주입한다. 데이터 분석 파이프라인·사용자 요청 등 이벤트를 판별하거나 실제 목록을 결정하는 라우팅은 호출 측의 책임이다. 현재 구현에는 이벤트 이름·두 이벤트의 실제 배정 목록을 넣지 않는다. 배포 카탈로그는 뷰 명세를 관리하고, 실행별 목록은 그중 사용할 수 있는 뷰를 고른다.

```python
nodes = build_nodes(
    model, providers, data_catalog, settings,
    role="request",
    allowed_view_keys=["Embed01RiskMap", "Embed02RiskDistribution"],
)
```

| 조건 | 동작 |
| --- | --- |
| 등록 ID 목록 | 실행 구성 시 `frozenset`으로 고정. 원래 목록을 수정해도 실행 중 범위는 유지 |
| 생략·빈 목록 | 허용 뷰 없음. 전체 허용으로 대체하지 않음 |
| `None`·문자열 단일값·미등록 ID | 실행 구성 오류 `ValueError`. 모델 호출 전에 수정 필요 |
| 허용 범위 밖 도구 호출 | `valid=false`, `view_not_allowed`, `artifact=null`. 오류의 `allowed`에도 허용된 ID만 반환 |
| 하위 Agent | 상위 실행의 고정 목록 상속. 모델이 전달하는 인자는 `goal`뿐이며 범위를 넓힐 수 없음 |
| 과거·전달받은 산출물 재사용 | 새 응답에 선택할 때도 허용 여부 검사. 범위 밖이면 공개 거부 |

같은 목록을 `create_tools(..., allowed_view_keys=...)`, `visualization_context(..., allowed_view_keys=...)`, `validate_visualization(..., allowed_view_keys=...)`에도 적용한다. 이 인자는 서버의 Python 호출 인자이며 모델용 JSON 입력에는 포함되지 않는다. 도구 스키마의 `view_key.enum`에는 허용된 ID만 들어간다. 빈 목록일 때는 호출 불가 설명을 제공하며 실제 함수가 모든 뷰를 거부한다.

선택 카탈로그·공유 입력 프로필·선택된 조건 상세를 허용 뷰로 좁히며, 매 모델 호출에 `allowed_visualization_views`를 제공한다. 과거 대화·저장된 실행 이력을 삭제하는 기능은 아니다. 새 실행·재개 그래프를 구성하는 호출 측이 해당 실행의 동일한 허용 목록을 보관·재주입해야 하며, 사용자 메시지·도구 인자를 정책 원본으로 사용하지 않는다. 카탈로그에 새 뷰를 추가해도 이미 고정된 실행의 허용 범위는 자동 확대되지 않는다.

### 뷰와 입력 프로필

[tableau_catalog.json](src/tools/tableau_catalog.json)이 선택 설명과 실행 명세의 원본이다. 현재 6개 뷰, 강남구·춘천시, 2025년 7~12월이 등록돼 있다. 등록 목록에서 벗어난 요청을 다른 값으로 자동 보정하지 않는다.

| 등록 항목 | 내용 |
| --- | --- |
| `views` | 서비스 내부 뷰 ID별 제목·목적·한계, 워크북·게시 뷰명, 입력 프로필 참조, 필터별 대상 시트 목록, 시간 의미·부분 선택 주의사항 |
| `input_profiles.parameters` | 이름별 `data_type`, `allowed`, 선택적 `default`·표시 이름 `labels`. 기본값 없는 항목은 필수 |
| `input_profiles.filters` | 고정 허용값 `allowed` 또는 참조 매개변수 `depends_on`과 값별 허용 목록 `allowed_by` |
| `input_profiles.date_orders` | 실제 선후 검사가 필요한 날짜 매개변수 쌍 `start/end` |

현재 입력 값은 문자열이며 매개변수 자료형은 `string/date`, 필터는 문자열 범주 목록을 지원한다. 새로운 숫자 범위·자료형이 필요하면 등록 스키마·공통 검증·프론트의 적용 지원을 함께 추가해야 한다.

새 뷰는 `views`에 추가하고 같은 조건이면 기존 프로필을 참조한다. 조건이 다르면 프로필을 추가하며, 도시·기간이 없는 뷰는 해당 항목을 등록하지 않는다. 각 필터에 여러 대상 시트를 지정할 수 있고 모든 대상에 같은 조건을 적용한다. 다른 워크북도 뷰별로 지정한다. 뷰 종류마다 별도 도구·Python 분기를 추가하지 않는다.

[tableau_catalog.py](src/tools/tableau_catalog.py)의 `validate_catalog()`가 자료형·필수 필드, 프로필·필터 참조, 허용값·기본값·표시 이름, 날짜 규칙과 기본 날짜 순서, 의존 필터의 허용 목록 누락·중복을 검사한다. 구성 오류는 사용자 입력의 `valid=false`로 숨기지 않고 등록 오류로 거부한다. 파일은 프로세스에서 처음 읽을 때 검사·캐시하므로 갱신한 설정 배포 후 프로세스를 다시 시작한다.

2026-11-02 등록 시 실제 Embedding API로 6개 뷰 로딩, 매개변수 정의, 대상 시트, 두 도시 전환과 읍면동 필터 적용·재조회를 확인했다. 등록 시점의 설정 확인이며 모든 지역·월 조합의 데이터 존재나 향후 표시 성공을 보장하지 않는다. 게시 설정 갱신 시 등록 설정을 다시 확인하고 `revision`과 등록 시각을 변경한다. 이번 v2는 같은 확인 결과를 뷰별 명세로 옮겼으며 원래 확인 시각을 유지한다. `catalog_revision`은 원자료 버전이 아니다.

검사 항목은 자료형·필수값·추가 필드, 선택한 뷰의 매개변수·필터 이름과 허용값, 선언한 날짜 순서·필터 의존 조건, 빈 목록·중복 값이다. 부적합 시 `issues`에 `code/path/message/requested/allowed/retryable`을 반환하며 `artifact`는 `null`이다. 필수 매개변수 누락은 `missing_parameter`, 고정·의존 필터 허용값 불일치는 `invalid_filter_value`다. `retryable=false`는 같은 입력의 자동 재시도가 무의미하다는 뜻이며 수정 후 호출은 가능하다.

```python
from src.tools.tableau import validate_visualization

result = validate_visualization({
    "view_key": "Embed01VulnerabilityMap",
    "parameters": {
        "p_city": "51110", "p_start": "2025-07-01", "p_end": "2025-12-01"
    },
    "filters": {"읍면동": ["후평3동"]},
}, allowed_view_keys=["Embed01VulnerabilityMap"])
```

성공한 `artifact.data`는 `schema_version`, 결정론적 `artifact_id`, `catalog_revision`, `view_key`, `src`, `title`, `period_mode`, 확정 `parameters`, 대상 시트가 포함된 `filters`, `source`, `validation_scope`, `warnings`를 가진다. 같은 조건의 지역 순서를 바꿔도 같은 ID를 생성한다. 생략된 읍면동 필터도 `operation=all`로 명시하여 이전 카드의 선택이 남지 않도록 한다.

프론트는 `type=tableau`를 처리하는 카드에서 새 인스턴스를 생성하고, `FirstInteractive` 이후 자료형에 맞게 매개변수→대상 시트 필터 순서로 적용한 뒤 실제값을 재조회해야 한다. `date`는 제공된 YYYY-MM-DD의 UTC 날짜로 변환하며, 필터는 지정된 각 `worksheet`에 `replace/all`을 적용한다. 적용 중에는 로딩 상태를 표시하고 적용값이 다르면 해당 카드의 오류로 표시한다. `artifact_id`가 같은 카드는 중간·최종 응답에서 유지하고 서로 다른 카드의 인스턴스·필터 상태를 공유하지 않는다. 현재 Python 구현은 `response.artifacts`까지 연결하며, 채팅 프론트 렌더러·HTTP/SSE 전달 구현과 실제 사용자 화면 검증은 포함하지 않는다.

## 실행과 검증

`ai/`에서 실행한다. 모델 ID는 명시적으로 지정하며 `.env`의 `SETTINGS_API_KEY`를 사용한다. 이 명령은 지침·카탈로그·요청을 Gemini API로 전송한다.

```powershell
.\.venv\Scripts\python.exe tableau_demo.py --model gemini-3-flash-preview --allow-view Embed01VulnerabilityMap --goal "2025년 12월 춘천시 후평3동의 배경 취약성 지도를 보여줘." --output outputs/tableau/state.json
.\.venv\Scripts\python.exe -m pytest tests/tools/test_tableau.py tests/tools/test_tableau_catalog.py tests/tools/test_tableau_scope.py tests/test_visualization_instructions.py tests/test_tableau_agent.py -q
```

`tableau_demo.py`는 실제 `build_nodes`·공통 그래프·검증 도구를 호출한다. 합성 자료나 모의 모델 분기를 공통 실행 코드에 넣지 않는다. 기본 실행 제한은 180초이며 `--timeout`으로 지정한다. 이 제한은 모델 왕복을 포함하며 검증 함수만의 시간이 아니다.

2026-11-06 허용 범위 검증: 관련 테스트 218개 통과. 생략·빈 범위 거부, 잘못된 구성, 허용 목록 수정 시도, 실행별 격리, 카탈로그·입력 프로필 제한, 하위 Agent 상속과 과거 산출물 재사용 제한을 확인했다. 실제 이벤트 라우팅·HTTP API의 정책 저장·재주입은 구현 범위 밖이며 실제 모델 API 호출은 수행하지 않았다.

2026-11-02 검증: 도구·통합·관련 회귀 테스트 202개와 변경 코드의 Ruff 검사·포맷 검사가 통과했다. 기존 6개 뷰와 합성 등록 명세로 다른 워크북·연령대 필터·여러 대상 시트·기간 없는 뷰·다른 이름의 날짜 순서를 확인했다. 합성 명세는 테스트에만 존재하며 실제 지원 뷰 목록에 포함하지 않는다. 통합 테스트는 외부 모델 응답만 대체하고 실제 업무 노드·그래프·검증 함수·산출물 선택을 실행했다. 실제 Gemini API 시험은 자동 승인 검토에서 외부 전송 승인이 필요해 실행되지 않았다. 프론트 채팅 표시 성공을 확인한 결과가 아니다.

v2 로컬 검증 함수 1,000회 측정은 캐시 로딩 후 중앙값 0.020ms·95백분위 0.037ms였다. 네트워크·모델 호출·브라우저 렌더링 시간은 포함하지 않는다. 한 번의 작업 선택→검증→진행 판단→응답 작성에서 명시적으로 추가하는 시각화 지침·카탈로그 문자열 합계는 기존 27,004자에서 5,696자로 78.9% 감소했다. 기본 프롬프트·요청·누적 실행 이력은 제외했으며 실제 토큰·요금·응답 시간 감소율을 측정한 값은 아니다.
