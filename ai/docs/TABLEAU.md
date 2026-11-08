# Tableau 시각화 실행

자연어 요청에서 게시된 Tableau 뷰와 조건을 선택하고, 결정론적 검증을 통과한 `tableau` 산출물을 반환한다. 요청마다 Tableau API·헤드리스 브라우저를 호출하지 않는다. 실제 화면 로딩·필터 적용 확인은 프론트의 책임이다.

## 지침과 실행 연결

- [시각화 작업 선택](../src/instructions/visualization-selection.md): 목적별 뷰, 기간 의미, 조건 결정, 지원하지 않는 요청 처리.
- [시각화 작업 선택 시 도구 사용](../src/instructions/visualization-tool.md): 입력·오류 처리·재작업·산출물 선택·프론트 전달 조건.
- `build_nodes(..., role="request" | "visualization")`가 두 지침을 읽는다. 작업 목적 파악에는 선택 지침·뷰 요약, 작업 선택에는 두 지침·뷰 요약·공유 입력 프로필을 제공한다. 검증·진행 판단·응답 작성·질문 작성에는 전체 지침·카탈로그를 반복 첨부하지 않고 실제 요청·호출 결과를 사용한다.
- `visualization_catalog.views`의 목적·한계는 등록 명세에서 가져온다. `input_profiles`는 같은 규격을 한 번만 전달하고, 매개변수별 전체 필터 목록은 생략한다. 기존 산출물·호출 이력으로 확인한 매개변수의 상세값은 `selected`에 제공한다. 처음 요청한 필터값은 사용자가 명시한 값으로 검증하며 부적합 사유에 해당 조건의 허용값이 반환된다. 상세 조회를 위한 모델 왕복은 추가하지 않는다.
- `create_tools()`의 `validate_visualization`을 실제 작업 선택 및 실행 노드에서 호출한다. 정상 결과는 기존 모델 검증에서 요청 목적과의 일치를 판단하고, 응답 작성에서 검증된 호출 ID로 원본 산출물을 선택한다.
- `valid=false`는 검사 완료 결과다. 부적합 사유를 별도 검증 이력에 남기고 공개 후보에서 제외한다. 모델은 조건을 수정하거나 필요한 정보를 요청하며, 부적합 결과를 보완하는 후속 호출은 인자 변경·대체 도구 여부와 관계없이 공유 retries.used에 누적한다.

HTML 렌더러는 직접 도구 사용 예제와 조회·가공 근거 비교표 생성에 남아 있다. Agent의 시각화 작업 선택에서는 게시된 Tableau 검증 도구를 사용한다. 합성 가구 비율로 임의 막대 차트를 생성하던 기존 S2 시나리오는 현재 Tableau 지원 범위를 검증하는 시나리오가 아니다.

## 등록 설정

### 이벤트별 허용 뷰

실행을 시작하는 코드가 `create_state(..., event="analysis_pipeline" | "user_request")`로 시작 종류를 설정한다. 이벤트의 원본은 `state["execution"]["event"]`다. `build_nodes`는 이벤트나 허용 목록을 별도 인자로 받지 않는다. 하위 Agent는 원래 이벤트를 상속하며 질문 재개는 저장된 이벤트를 유지한다. 최초 그래프 진입은 분석 파이프라인이면 작업 선택, 사용자 요청이면 목적 파악이다. 질문 답변 후에는 목적 파악으로 진입한다.

등록 명세의 `event_views`에서 이벤트별 허용 범위를 관리한다. 분석 이벤트의 State 값인 `analysis_pipeline`에는 실제 게시 이름 `EmbedDetailV01`~`EmbedDetailV08`만 배정한다. `user_request`는 `"all"`로 설정하여 등록된 임베드 뷰 전체를 허용한다. 새로 등록한 뷰도 사용자 요청에서는 자동 포함된다. `all`은 임의 URL이나 미등록 뷰를 허용한다는 뜻이 아니다. 명시 목록은 해당 ID만, 빈 목록은 사용 불가를 뜻한다. 이벤트 목록 누락·중복 ID·미등록 이벤트·미등록 뷰는 구성 오류다.

`visualization_context(state, ...)`가 해당 뷰와 사용되는 입력 프로필만 안내한다. 작업 선택 및 실행 노드는 현재 State로 `create_tools(providers, state=state)`를 구성하며, `validate_visualization(request, state=state)`도 같은 이벤트별 목록을 검사한다. 목록 밖의 뷰는 `valid=false`, `view_not_allowed`, `artifact=null`이며 오류의 `allowed`에도 이 이벤트의 허용 ID만 반환한다. `event`, `state`, `allowed_view_keys`는 모델의 JSON 도구 인자에 포함되지 않는다.

배포 명세는 프로세스에서 검사·캐시한다. 같은 배포의 재개에는 별도 허용 목록 재주입이 필요하지 않다. 배포 설정 변경 후 프로세스를 다시 시작하며, 배포 버전이 달라진 대기 실행의 재개 정책은 State 명세의 미정 계약을 따른다.

### 뷰와 입력 프로필

[tableau_catalog.json](../src/tools/tableau_catalog.json)이 선택 설명과 실행 명세의 원본이다. 현재 새 워크북 `eumi_tableau_main_dashboard_v2_0_6_connection_map_fixed`의 임베드 뷰 15개, 강남구·춘천시, 2025년 7~12월이 등록돼 있다. 등록 목록에서 벗어난 요청을 다른 값으로 자동 보정하지 않는다.

| 등록 항목 | 내용 |
| --- | --- |
| `event_views` | 시작 이벤트별 허용 뷰 ID 목록 또는 전체 등록 뷰를 뜻하는 `all` |
| `views` | 서비스 내부 뷰 ID별 제목·목적·한계, 워크북·게시 뷰명, 입력 프로필 참조, 필터별 대상 시트 목록, 시간 의미·부분 선택 주의사항 |
| `input_profiles.parameters` | 이름별 `data_type`, `allowed`, 선택적 `default`·표시 이름 `labels`. 기본값 없는 항목은 필수 |
| `input_profiles.filters` | 고정 허용값 `allowed` 또는 참조 매개변수 `depends_on`과 값별 허용 목록 `allowed_by` |
| `input_profiles.date_orders` | 실제 선후 검사가 필요한 날짜 매개변수 쌍 `start/end` |

기존 6개 뷰는 `monthly_city` 프로필로 도시·기간·읍면동 필터를 사용한다. 상세 지도와 `EmbedDetailV01`~`V08`은 `monthly_detail` 프로필로 기간과 `p_detail_adm`을 사용한다. `p_detail_adm`에는 `춘천시 후평3동`처럼 Tableau 표시값을 전달한다. 코드 `5111061100`을 API에 직접 적용하면 실패하는 것을 확인했다. 상세 뷰의 내부 계산 필터는 게시 설정을 유지하며 도구 입력에 노출하지 않는다.

현재 입력 값은 문자열이며 매개변수 자료형은 `string/date`, 필터는 문자열 범주 목록을 지원한다. 새로운 숫자 범위·자료형이 필요하면 등록 스키마·공통 검증·프론트의 적용 지원을 함께 추가해야 한다.

새 뷰는 `views`에 추가하고 같은 조건이면 기존 프로필을 참조한다. 조건이 다르면 프로필을 추가하며, 도시·기간이 없는 뷰는 해당 항목을 등록하지 않는다. 각 필터에 여러 대상 시트를 지정할 수 있고 모든 대상에 같은 조건을 적용한다. 다른 워크북도 뷰별로 지정한다. 뷰 종류마다 별도 도구·Python 분기를 추가하지 않는다.

[tableau_catalog.py](../src/tools/tableau_catalog.py)의 `validate_catalog()`가 자료형·필수 필드, 프로필·필터 참조, 허용값·기본값·표시 이름, 날짜 규칙과 기본 날짜 순서, 의존 필터의 허용 목록 누락·중복을 검사한다. 구성 오류는 사용자 입력의 `valid=false`로 숨기지 않고 등록 오류로 거부한다. 파일은 프로세스에서 처음 읽을 때 검사·캐시하므로 갱신한 설정 배포 후 프로세스를 다시 시작한다.

2026-11-06 새 게시본의 15개 임베드 뷰 로딩·시트·매개변수·필터 명세를 확인했다. 기존 6개 뷰의 후평3동 필터와 상세 9개 뷰의 표시값 매개변수 적용·재조회를 확인하고 공개 워크북 계산식으로 기간 의미를 대조했다. 모든 지역·월 조합의 데이터 존재를 검사한 결과는 아니다. `catalog_revision`은 원자료 버전이 아니다.

검사 항목은 자료형·필수값·추가 필드, 선택한 뷰의 매개변수·필터 이름과 허용값, 선언한 날짜 순서·필터 의존 조건, 빈 목록·중복 값이다. 부적합 시 `issues`에 `code/path/message/requested/allowed/retryable`을 반환하며 `artifact`는 `null`이다. 필수 매개변수 누락은 `missing_parameter`, 고정·의존 필터 허용값 불일치는 `invalid_filter_value`다. `retryable=false`는 같은 입력의 자동 재시도가 무의미하다는 뜻이며 수정 후 호출은 가능하다.

```python
from src.state import create_state
from src.settings import Settings
from src.tools.tableau import validate_visualization

state = create_state(
    {"goal": "춘천시 배경 취약성 지도"}, Settings(),
    messages=[], version="배포 버전", event="user_request",
)
# 해당 뷰를 event_views.user_request에 배정한 경우
result = validate_visualization({
    "view_key": "Embed01VulnerabilityMap",
    "parameters": {
        "p_city": "51110", "p_start": "2025-07-01", "p_end": "2025-12-01"
    },
    "filters": {"읍면동": ["후평3동"]},
}, state=state)
```

성공한 `artifact.data`는 `schema_version`, 결정론적 `artifact_id`, `catalog_revision`, `view_key`, `src`, `title`, `period_mode`, 확정 `parameters`, 대상 시트가 포함된 `filters`, `source`, `validation_scope`, `warnings`를 가진다. 같은 조건의 지역 순서를 바꿔도 같은 ID를 생성한다. 생략된 읍면동 필터도 `operation=all`로 명시하여 이전 카드의 선택이 남지 않도록 한다.

프론트는 `type=tableau`를 처리하는 카드에서 새 인스턴스를 생성하고, `FirstInteractive` 이후 자료형에 맞게 매개변수→대상 시트 필터 순서로 적용한 뒤 실제값을 재조회해야 한다. `date`는 제공된 YYYY-MM-DD의 UTC 날짜로 변환하며, 필터는 지정된 각 `worksheet`에 `replace/all`을 적용한다. `p_detail_adm`은 적용 시 표시값을 사용하고 재조회 시 `formattedValue`로 비교한다. 원값 `value`는 행정동 코드이므로 표시값과 직접 비교하지 않는다. 적용 중에는 로딩 상태를 표시하고 적용값이 다르면 해당 카드의 오류로 표시한다. `artifact_id`가 같은 카드는 중간·최종 응답에서 유지하고 서로 다른 카드의 인스턴스·필터 상태를 공유하지 않는다. 현재 Python 구현은 `response.artifacts`까지 연결하며, 채팅 프론트 렌더러·HTTP/SSE 전달 구현과 실제 사용자 화면 검증은 포함하지 않는다.

## 실행과 검증

2026-11-06 이벤트별 뷰 설정 검증: 관련 테스트 80개와 변경 코드의 Ruff 검사 통과. 실제 배포 카탈로그에서 분석 이벤트의 상세 8개 제한, 사용자 요청의 전체 15개 허용, 새 등록 뷰의 `all` 자동 포함, 상세 행정동 표시값 검증, 하위 실행·재개·동시 실행을 확인했다. 외부 모델 호출은 수행하지 않았다.

`ai/`에서 실행한다. `.env`의 OpenAI 키 `SETTINGS_API_KEY`를 사용한다. `--model`을 생략하면 Settings의 모델을 사용하며 현재 기본값은 `gpt-6-sol`이다. 이 명령은 지침·카탈로그·요청과 도구 명세·응답 스키마를 OpenAI Responses API로 전송한다.

```powershell
.\.venv\Scripts\python.exe tableau_demo.py --model gpt-6-sol --goal "2025년 12월 춘천시 후평3동의 배경 취약성 지도를 보여줘." --output outputs/tableau/state.json
.\.venv\Scripts\python.exe -m pytest tests/tools/test_tableau.py tests/tools/test_tableau_catalog.py tests/test_visualization_events.py tests/test_visualization_instructions.py tests/test_tableau_agent.py -q
```

`tableau_demo.py`는 실제 `build_nodes`·공통 그래프·검증 도구를 호출한다. 합성 자료나 모의 모델 분기를 공통 실행 코드에 넣지 않는다. 일반 실행 시간의 기본 한도는 180초이며 `--timeout` 값을 최초 State에 반영한다. 모델·도구·하위 Agent가 같은 잔여 시간과 누적 사용량을 공유한다. 한도 도달 후 별도 종료 예산은 [State의 실행 예산](ieumi-agent-state.md#실행-예산)을 따른다. 데모 외부에서 별도 timeout이나 호출 한도를 다시 설정하지 않는다. 이번 State 실행 경로 변경의 테스트·검사는 실행하지 않았다.


2026-11-02 검증: 도구·통합·관련 회귀 테스트 202개와 변경 코드의 Ruff 검사·포맷 검사가 통과했다. 기존 6개 뷰와 합성 등록 명세로 다른 워크북·연령대 필터·여러 대상 시트·기간 없는 뷰·다른 이름의 날짜 순서를 확인했다. 합성 명세는 테스트에만 존재하며 실제 지원 뷰 목록에 포함하지 않는다. 통합 테스트는 외부 모델 응답만 대체하고 실제 업무 노드·그래프·검증 함수·산출물 선택을 실행했다. 실제 Gemini API 시험은 자동 승인 검토에서 외부 전송 승인이 필요해 실행되지 않았다. 프론트 채팅 표시 성공을 확인한 결과가 아니다.

v2 로컬 검증 함수 1,000회 측정은 캐시 로딩 후 중앙값 0.020ms·95백분위 0.037ms였다. 네트워크·모델 호출·브라우저 렌더링 시간은 포함하지 않는다. 한 번의 작업 선택→검증→진행 판단→응답 작성에서 명시적으로 추가하는 시각화 지침·카탈로그 문자열 합계는 기존 27,004자에서 5,696자로 78.9% 감소했다. 기본 프롬프트·요청·누적 실행 이력은 제외했으며 실제 토큰·요금·응답 시간 감소율을 측정한 값은 아니다.
