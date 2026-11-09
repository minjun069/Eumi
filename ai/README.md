# AI Agent 공통 실행 기반

현재 시각화 실행은 [Tableau 시각화 실행](TABLEAU.md)을 따른다. 작업 선택·도구 사용 지침을 모델 입력에 연결하고 등록된 뷰·조건을 결정론적으로 검증한다. 아래 S2 HTML 차트 결과는 변경 전 시험 기록이며 현재 Tableau 지원 범위의 검증 결과가 아니다.

현재 State 계약에 맞춘 공통 그래프 연결과 질문 재개를 구현했다. `src/graph.py`는 호출자가 제공한 업무 노드를 연결하고 State 갱신을 검사한다. `demo.py`는 모의 노드로 연결 계약을 확인한다. `scenario_demo.py`는 실제 OpenAI 모델·자료 도구·전문 Agent를 같은 그래프에 연결한다. `src/runtime.py`의 시작·질문 재개 함수를 모든 데모와 하위 Agent가 사용한다. 서비스 API·DB 연결은 아직 구현하지 않았다.

## OpenAI 시나리오 실행

`scenario_demo.py`는 [실행 시나리오](../../docs/ai-agent-scenarios.md)의 S1 기본 해석, S2 비율 차트, S3 선택 차트 후속 설명을 실행한다. D1~D3은 `experiments/scenario_fixtures.py`의 **시연용 예시 데이터**이며 실제 통계·DB가 아니다.

```powershell
cd C:\ssafy\free_proj\Eumi\ai
.\.venv\Scripts\python.exe scenario_demo.py --suite
# 모델을 명시적으로 지정
.\.venv\Scripts\python.exe scenario_demo.py --suite --model gpt-6-sol
# 개별 실행: --scenario S1 또는 --scenario S2
# 다른 모델을 명시적으로 지정: --model <OpenAI 모델 ID>
```

`ai/.env`의 OpenAI 키 `SETTINGS_API_KEY`를 사용한다. 다른 파일은 `--env-file 경로`, 결과 저장 위치는 `--output 경로`로 지정한다. `--model`을 생략하면 Settings가 읽은 모델을 사용하며, `SETTINGS_MODEL`도 없으면 현재 기본값 `gpt-6-sol`을 사용한다. 다른 모델로 자동 전환하지 않는다. 연결은 설치된 LangChain 클라이언트와 [OpenAI Responses API](https://developers.openai.com/api/docs/guides/responses)를 사용한다. 기존 `.env`·Settings·의존 패키지는 변경하지 않았다.

| 구성 | 동작 |
| --- | --- |
| `src/gemini.py` | OpenAI 모델 생성·Responses API 호출, 도구·출력 설정, TypeAdapter 검증, 사용량·시간 반환 |
| `src/tool_specs.py` | 기존 도구의 역할별 설명·입력 명세, 계산 결과 ID 참조와 전문 Agent 목표 입력 명세 구성 |
| `src/agent_nodes.py` | 실제 5개 업무 노드, 역할별 도구·전문 Agent 선택, 호출 후 검증, 응답 구성 |
| `src/graph.py` | State 갱신·전이·질문 재개, 실제 업무 단계 소비와 오류·한도 종료 |
| `src/execution.py` | State의 호출·재시도·활성 시간·종료 응답 예산 소비와 하위 사용량 반영 |
| `src/runtime.py` | State 기반 시작, 체크포인트의 현재 질문 확인과 동일 State 재개 |
| `src/tools/` | 실제 조회·가공·HTML/SVG 렌더링. percentage 계산·가공 후 정렬·가로 막대 지원 |
| `scenario_demo.py` | S1 이벤트를 초기 State에 지정, S2→S3 대화·차트 연결, 공통 실행 함수 호출과 결과 파일 저장 |

모델은 작업·인자·검증·진행 방향·설명을 JSON으로 반환한다. 계산·렌더 입력은 검증된 호출 결과 ID로 선택하며, 모델이 원본 자료를 다시 작성할 수 없다. 호출·검증은 별도 results 기록이다. 응답 작성은 검증된 결과의 ID를 선택하고, 도구가 생성한 차트·사용 자료·설정을 연결한다. S1 비교표도 실제 렌더러로 생성한다. S3는 `previous`로 기존 차트를 유지한다.

도구 명세는 `bind_tools()`, 기존 응답 스키마는 `with_structured_output()`으로 전달한다. 선택 입력의 생략 가능 여부를 유지하기 위해 `strict=False`를 사용하고 원본 응답 텍스트를 기존 TypeAdapter로 검증한다. 선택 결과와 실행 순서는 유지하며, 원본 SDK 응답에서 사용량을 읽는다. 프롬프트에는 업무 판단 지침·State 컨텍스트를 남긴다. 세부 구성은 [컨텍스트 구성](context-composition.md)을 따른다.

**2026-11-06 모델 연결 변경:** OpenAI Responses API로 연결하고 `temperature=0`을 제거했다. 사전 호환성 확인에서 `gpt-6-sol`의 합성 입력 9개가 통과했으나 전체 Agent 시나리오 결과는 아니다. 이후 구현 변경의 테스트·실제 모델 실행은 사용자 요청에 따라 수행하지 않았고 테스트 파일도 수정하지 않았다. 아래 Gemini 실행 결과는 과거 구현의 기록이다.

하위 Agent는 도구처럼 호출하며 반환된 `response`, `results`, `execution`을 상위 호출 기록의 `results[].output`에 저장한다. 하위 실행은 목적·상위 조건·대화·시작 이벤트·누적 예산으로 초기화하고 필요한 자료를 직접 조회한다. 상위·하위가 전체 실행의 남은 한도를 공유하며, 하위 반환 사용량에 이미 포함된 상위 사용량을 다시 더하지 않는다. 상위의 조회·계산 자료를 별도 인자로 주입하지 않는다. 상위 호출과 하위 호출 모두 검증을 통과한 결과만 재사용할 수 있다.

검증 모델은 현재 노드의 선택·호출 기록까지 반영한 State의 `results`를 읽는다. 응답 작성은 같은 이력과 `response`에서 결과를 선택하며, 기존 산출물은 `previous`로 유지한다. 모델 호출에 별도 선택·호출 결과·후보 ID 목록을 주입하지 않는다. 시작 이벤트와 모든 실행 한도·사용량은 `execution`에서 읽는다. `build_nodes`는 Settings나 실행별 자료 인자를 받지 않는다.

노드가 반환하거나 처리 오류·한도로 종료하면 공통 그래프가 해당 노드의 확보 기록과 누적 예산을 함께 반영한다. 프로세스 강제 종료에 대한 노드 내부 기록의 영속 복구와 호출 지점 자동 재개는 제공하지 않는다.

출력은 `outputs/gemini-scenarios/<S1|S2|S3>/`의 `report.json`(State·판단·호출·검증·토큰), `answer.txt`, `artifact-*.html`이며 전체 실행 요약은 `summary.json`이다. 모델 오류 시 공통 그래프가 확보 기록·누적 사용량·오류 종류와 기존 공개 산출물을 보존하고 실행을 종료한다. HTTP 상태는 관측 trace에서 확인한다. 모델 원본 오류 문자열과 키는 보고서에 기록하지 않는다.

`experiments/scenario_checks.py`는 완료 상태와 별도로 호출·계산값·실제 산출물을 검사한다. 검사 결과는 보고서의 `evaluation`에 저장한다. 모델이 `completed`라고 답해도 계산 도구·실제 차트·전문 Agent 호출·기존 차트 보존 등 해당 시나리오의 증거가 빠지면 데모는 실패 코드로 종료한다. 이 검사는 실행 경로를 강제하거나 모델 대신 업무 판단을 수행하지 않는다.

시나리오 데모는 최상위 State에 일반 실행 600초, 전체 업무 단계 80회, 도구 16회·하위 Agent 4회, 보완 호출 2회의 한도를 초기화한다. 모델 클라이언트의 개별 요청 timeout은 60초이며 SDK 자동 재시도는 꺼져 있다. 하위 호출·질문 재개는 동일 누적 예산을 이어 쓰며 별도 Settings 조회·데모 외부 timeout을 두지 않는다. `metrics.tool_calls`·`agent_calls`는 State의 budget.used를 읽고, 모델·토큰 통계는 완료되어 기록된 model_usage를 집계한다.

한도에 먼저 도달한 Agent는 공유 종료 응답 예산으로 모델 최대 1회·활성 시간 최대 30초를 사용한다. 추가 도구·하위 Agent·렌더링·재시도는 허용하지 않는다. 하위가 종료 응답을 작성하면 결과를 상위 results에 남기고 상위는 추가 모델 호출 없이 종료한다. 상위 검증이 끝나지 않은 하위 결과를 자동으로 공개하지 않는다. 자세한 집계·반환 기준은 [State의 실행 예산](../../docs/ieumi-agent-state.md#실행-예산)을 따른다.

**2026-11-06 코드·문서 변경 상태:** State 기반 시작·공유 예산·한도 종료·질문 재개를 연결했다. 사용자 요청에 따라 이번 변경의 테스트·정적 검사·실제 모델 호출은 실행하지 않았다. 아래 과거 시험 기록은 현재 수정본의 검증 결과가 아니다.

재시도 집계는 직전 실패·부적합 호출 이후의 호출을 세는 이전 처리로 돌아갔다. 여러 호출에 걸친 보완과 독립 작업의 구분은 미완료이며, 전체 재시도 정책을 구현했다고 볼 수 없다.

현재 범위는 S1~S3의 최종 응답이다. 중간 응답·진행 이벤트, 하위 Agent에서 사용자에게 질문한 작업의 중단 지점 재개, 서비스 API·DB·대시보드 게시·영속 저장·취소 API는 미구현이다. 전문 Agent는 정보가 부족하면 가능한 범위를 반환하고 상위 Agent가 질문 필요 여부를 판단한다. 최상위 질문 재개는 공통 그래프와 실제 노드로 검증했으며 CLI에서는 임의 답변을 자동 주입하지 않는다. 이전 Info·pending·별도 runs 저장소에 의존하던 실행기 코드는 제거하고 State 시작·체크포인트 재개 함수로 교체했다.

### 2026-11-01 확인 결과

- 실제 `gemini-2.5-flash` 요청: **HTTP 404 / 모델 사용 불가**. Google 응답은 신규 사용자에게 이 모델을 더 이상 제공하지 않는다는 내용이다. 호환 API와 공식 `generateContent` API에서 확인했다. S1~S3의 실제 모델 완료·응답 품질은 검증하지 못했다. 시도 결과는 `outputs/gemini-2.5-flash-attempt/summary.json`에 저장했다.
- 실제 업무 노드·그래프·도구 검증: 기존 도구·그래프·모니터링 검증 포함 **134개 통과**. 모델 응답 경계만 대체했다. 가구 비율·정렬, 검증 거부 후 재작업, 미검증 산출물 차단, 원자료 인자 위조 차단, 질문 재개·산출물 유지, 전문 Agent 호출·통합, 실패 한도·오류 체크포인트 보존을 확인했다. 상위 자료 재사용·하위 차트 참조·실행 증거 없는 완료 거부도 검증했다. 변경 파일의 Ruff 검사·포맷 검사도 통과했다.
- 기존 도구·그래프·모니터링 테스트를 포함한 검증 명령은 아래와 같다. 이전 State를 참조하는 기존 전체 테스트의 수집 오류는 별도로 남아 있다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_nodes.py tests/test_scenario_checks.py tests/tools tests/test_graph_contract.py tests/test_demo.py tests/test_monitoring.py -q
```

### gemini-3-flash-preview 실제 실행 결과

같은 날 실제 API 호출과 가상 자료 D1~D3으로 검증했다. 최종 통과 결과는 `outputs/gemini-3-flash-preview-result/`에 보관한다. S1·S2의 통과 결과를 유지하고 기존 차트 선택 목록 보완 후 S3만 다시 실행했다.

| 시나리오 | 결과·확인 사항 | 처리 시간 | 모델 / 도구 / 하위 Agent 호출 |
| --- | --- | ---: | ---: |
| S1 | 완료·검사 통과. D1·D2 조회, 6개 지역·연도 변화율 계산, 비교표·해석 | 54.84초 | 10 / 3 / 0 |
| S2 | 완료·검사 통과. 비율 계산·정렬, 시각화 Agent 호출, 실제 가로 막대 차트 | 78.94초 | 16 / 3 / 1 |
| S3 | 완료·검사 통과. 해석 Agent 호출, 12.5%의 의미 설명, S2 차트 유지 | 65.02초 | 10 / 1 / 1 |

통과한 세 실행의 합계는 198.80초, 모델 36회·도구 7회·하위 Agent 2회다. 입력 179,245토큰·출력 7,211토큰은 SDK가 보고한 해당 필드의 합이며, 초기 실패·보완 시도의 사용량과 비용은 이 합계에 포함하지 않는다. 모델이 보고한 토큰 상세는 각 results의 `model_usage`에 남는다.

최초 시험에서는 계산·실제 차트 생성 생략, 상하위 결과 참조 실패, 후속 응답의 기존 차트 누락을 확인했다. 역할별 지침과 원자료 참조·산출물 선택 목록을 수정하고 재검증했다. 이전 시도는 `gemini-3-flash-preview-attempt/`, `gemini-3-flash-preview-verified/`, `gemini-3-flash-preview-final/`에 남아 있다. 실행 실패를 성공 결과로 덮어쓰지 않았다.

S2 차트의 수치·정렬·0~20% 축·파란색 표현은 실제 브라우저에서도 확인했다. S3 텍스트는 비율과 위험 순위를 구분하고 기존 차트를 유지하지만, 분자·분모의 가구 수는 본문에 직접 반복하지 않았다. 연결된 자료에는 해당 수치가 보존된다. 자연어 답변의 모든 문장·출처 대응과 반복 실행 안정성은 추가 평가 대상이다. 현재 결과는 합성 자료를 사용한 시험이며 실제 DB·서비스 게시 검증이 아니다.

Langfuse 설정을 켜면 기존 콜백으로 모델 호출을 추적한다. 이번 실제 호출 시험에서는 `.env`에 Langfuse 활성 설정이 없어 원격 모니터링 수신을 검증하지 않았다.

## HTML 실행 리포트

`report_html.py`는 `report.json` 파일 또는 결과 폴더를 받아 실행 기록을 포함한 단일 HTML을 만든다. 생성한 파일은 브라우저에서 바로 열 수 있으며 서버나 추가 패키지가 필요하지 않다.

```powershell
.\.venv\Scripts\python.exe report_html.py outputs/gemini-3-flash-preview-result --output outputs/gemini-3-flash-preview-result/report.html
```

시나리오 전환, 호출·토큰 요약, 중첩 Agent 이력, 검색·단계·실패 필터, 최종 응답·차트·데이터 표, 요청·대화와 검사 결과를 제공한다. `report.json 불러오기`로 다른 보고서를 추가할 수 있으며 선택한 파일은 브라우저 내부에서 읽는다. HTML 산출물은 스크립트와 외부 요청을 차단한 미리보기로 표시한다. `report_viewer.html`은 보고서가 포함되지 않은 뷰어 템플릿이며, 직접 열어 파일을 불러올 수도 있다.

### 호출 당시 전체 입출력 기록

`scenario_demo.py`는 실행마다 `report.json`에 `trace`를 추가하고 종료 시 결과 폴더의 `report.html`을 자동 생성한다. 원격 Langfuse 설정과 독립적인 로컬 기록이다. `demo.py --output 경로`도 노드 입력·갱신·질문 대기/재개 기록과 HTML을 저장한다. 모의 데모에는 실제 모델 HTTP 호출이 없다.

| 대상 | 저장하는 내용 |
| --- | --- |
| 최상위·하위 Agent | 최초 State 전체, 카탈로그·역할, 반환 상태. 최상위 데모의 Settings는 인증정보를 제외한 관측 기록이며 하위 실행 입력으로 주입하지 않음 |
| 각 업무 노드 | 진입 시 State, 노드가 반환한 갱신·다음 이동, 공통 그래프 검사·누적 후 적용할 갱신 |
| 각 모델 호출 | 전체 시스템 프롬프트·응답 스키마, 실제 메시지·컨텍스트, SDK가 전송한 HTTP JSON 본문(모델·생성 설정 포함), HTTP 원문 응답·상태, SDK 응답·토큰·종료 사유, 스키마 검증 결과 |
| 도구·자료원 | 모델 선택 인자, 데이터 참조 치환 후 실제 전달 인자, 도구 입력 스키마, 전체 반환값, 필터 적용 전 자료원 반환값 |
| 연산·산출물 | 계산·정렬 등 각 연산 전후 자료·행 수, 응답에 연결할 검증된 결과·선택 ID·이전 응답, 비교표 생성 입력·출력 |
| 실행 연결·오류 | 호출 ID·부모 ID·순서, UTC 시작·종료 시각·경과 시간, 예외 종류·코드·HTTP 상태·스키마 오류 |

`src/execution_trace.py`의 ContextVar로 호출 관계를 연결한다. 스냅샷은 State와 모델 컨텍스트에 다시 넣지 않으므로 기록 자체가 다음 모델의 입력을 늘리지 않는다. 각 호출 시작·갱신·종료를 `trace.jsonl`에 즉시 저장하여, 노드가 State를 반영하기 전에 실패해도 호출 입력과 받은 응답을 보존한다. 프로세스가 강제 종료되면 마지막 시작/갱신 기록은 남지만, 최종 report.json·HTML 생성은 완료되지 않을 수 있다.

인증키·인증 헤더·쿠키는 제외하고 등록된 키 문자열은 마스킹한다. 공급자 예외 문자열은 인증 정보가 섞일 수 있어 제외하며 수신한 HTTP 응답과 구조화된 오류를 보존한다. 모델 내부 비공개 추론, 공급자 내부 기본값, TLS·압축 바이트는 관측 대상이 아니다. 기존 `compact()`가 모델 입력에서 제외한 HTML은 실제 전송 내용 그대로 기록되고, 노드·도구·Agent 스냅샷에는 전체 HTML이 남는다.

HTML의 **호출 상세**는 노드 실행 단위로 묶는다. 각 노드 안에 모델 판단·도구 실행·결과 검증·산출물을 순서대로 표시하고, 데이터는 표로, 조건·설정·판단은 항목과 본문으로 렌더링한다. 스키마 검증 오류는 전파된 상위 오류를 중복 집계하지 않고 별도 영역에 표시하며 일반 노드 내부 호출 목록에서 제외한다. 각 노드는 **모델 입력 전체 → 입력 State → 처리·판단 결과 → State 변경** 순서로 표시한다. 모델 입력은 실제 HTTP 요청의 메시지·설정을 독립된 영역에서 보여주며 노드 안의 호출을 선택할 수 있다. 모델 메시지는 JSON·스키마·줄바꿈을 포함한 원문 그대로 표시하며, 메시지 안의 JSON은 표나 한글 필드 UI로 변환하지 않는다. 메시지 구성에 사용한 입력과 응답 스키마도 JSON으로 제공한다. State는 한글명과 변수명을 함께 표시하고 주요 필드의 의미를 설명한다. 노드 상단의 `현재 작업 요청 (request.goal)`은 해당 노드 실행 직전의 요청이며, 사용자 입력 원문은 `messages`의 사용자 메시지로 구분한다. 요청·대화 탭의 요청은 보고서 저장 시점의 State 기준이다. 중첩 항목은 들여쓰기·연결선·제목 배경으로 구분한다. 응답 스키마는 모델 입력 영역에, HTTP 요청 전문은 접힌 JSON에 보존한다. 노드 간 이동, 전체 내용 검색, 노드 단계·오류 필터를 지원하며 실행 이력에서도 해당 노드로 이동한다. `trace.coverage`는 모델 시도·입력·HTTP 요청·응답 수를 구분한다. 기존 `metrics.model_calls`는 State에 반영된 모델 호출 수이므로 실패한 호출까지 보려면 coverage를 확인한다. 접힌 JSON은 펼칠 때 렌더링하며 값은 생략하지 않는다. 자료 표의 200행 표시 제한과 별도로 전체 원자료는 JSON에 보존한다.

### 2026-11-02 상세 기록 실제 실행

```powershell
.\.venv\Scripts\python.exe scenario_demo.py --suite --model gemini-3-flash-preview --output outputs/gemini-3-flash-preview-traced-20261102
```

한 차례 연속 실행한 결과는 해당 폴더의 `report.html`에서 확인한다. S1은 50.94초에 완료·검사 통과했다. S2(44.47초)·S3(28.75초)는 모델이 완료를 반환했지만 각각 시각화·해석 전문 Agent 호출을 생략하여 시나리오 검사에 미통과했다. S2의 비율 계산·정렬·차트와 S3의 기존 차트 보존 검사는 통과했다. 실패 결과를 성공 실행으로 덮어쓰지 않았다.

26회 모델 호출 전부에 전체 입력과 HTTP 요청·응답을 저장했다. 전송 메시지와 스냅샷의 일치, 완료된 추적과 JSONL의 일치, 참조 치환된 도구 인자, 인증키 제외를 검사했다. 이번 실제 실행에서는 하위 Agent 호출이 없었으므로 그 입력 기록은 실제 노드·그래프를 사용하는 모의 모델 테스트에서 검증했다. 모델 응답만 대체하여 하위 초기 State·전달 자료·카탈로그·부모 연결과 실제 반환 상태를 확인했다.

## 현재 그래프 실행

- `compile_graph(nodes, finish=..., checkpointer=None)`: 다섯 업무 노드와 종료 판단 함수를 받아 그래프 구성. 최초 진입은 State의 `execution.event`로 결정한다. 노드는 LangGraph `Command`로 부분 갱신과 다음 노드를 반환한다.
- `finish(state)`: 최종 응답까지 반영한 상태에서 `status`와 `error` 반환. 공통 그래프가 `execution`에 반영하며 한도 종료를 completed로 바꾸지 않는다.
- `run_graph(graph, state)`: queued State로 시작한다. thread_id는 State의 run_id로 만든다. 프레임워크 superstep 상한은 실행 예산으로 사용하지 않으며 실제 업무 진입을 steps.used로 제한한다.
- `experiments.fixtures.initial_state()`와 `mock_nodes(scenario)`: 임시 초기 상태, 모의 노드 및 종료 판단을 제공한다. 그래프 생성·실행은 수행하지 않는다.
- `python demo.py --suite`: 여섯 임시 시나리오를 실제 공통 그래프로 실행한다. `--analysis-event`는 작업 단계로 진입하며, `--scenario question --answer "추가 정보"`는 질문 재개를 확인한다. 질문 재개에는 체크포인터와 `resume_graph(graph, run_id, question_id, answer)`를 사용한다. 저장된 질문 ID·상태를 확인하고 같은 State의 예산을 이어 쓴다. `--output 경로`를 지정하면 State를 JSON 보고서로 저장한다.
- 검증 명령: `python -m pytest tests/test_graph_contract.py tests/test_demo.py -q`. 현재 업무 노드 출력은 모의 함수가 공급하므로 검증 범위는 공통 연결·상태 처리·질문 재개와 데모 조립이다. 실제 업무 노드 검증에서는 같은 노드를 실행하고 모델·외부 도구 경계만 대체한다. 모의 데모의 기록은 실제 도구 호출을 수행했다는 증거가 아니다. 이번 공유 예산 변경과 서비스 접근 권한·동시 재개는 검증하지 않았다.

## Langfuse 모니터링

구현 의도·상태·관측 항목은 [모니터링 문서](../../docs/ai-agent-monitoring.md)에서 관리한다.

`ai/`에서 `uv sync --locked`를 실행하고 [환경변수 예시](.env.example)의 `LANGFUSE_*` 항목을 `.env`에 추가한다. 기본은 비활성이며, `LANGFUSE_ENABLED=true`와 프로젝트의 `LANGFUSE_PUBLIC_KEY`·`LANGFUSE_SECRET_KEY`가 필요하다. `LANGFUSE_BASE_URL`은 프로젝트 주소로 지정한다. 환경은 `LANGFUSE_TRACING_ENVIRONMENT`, 수집 비율은 `LANGFUSE_SAMPLE_RATE`(0~1)로 설정한다.

```bash
uv run python demo.py --suite
uv run pytest tests/test_graph_contract.py tests/test_demo.py tests/test_monitoring.py -q
```

모의 데모는 콘솔의 `run_id`, OpenAI 시나리오는 `report.json`의 `state.execution.run_id`로 Langfuse Session을 찾는다. OpenAI 실행 방법은 위의 시나리오 안내를 따른다. 모의 데모는 실제 모델 비용이 발생하지 않으며 OpenAI 실행은 실제 API를 호출한다.

## 삭제한 부분

- `CallMetadata`와 scope·agent_path·retry_tool 기반 호출 식별·이력 선택·재시도 연결
- 결과 후보와 산출물을 `ToolMessage.artifact`에 기록하고 다시 수집하는 코드
- 하위 Agent 호출·복귀, 결과 제출·검증 노드와 그래프 연결
- 이에 의존하던 실험 Agent 구성·업무 결과 검증·표 산출물 저장 도구

`AgentRuntime`의 이전 State 계약·별도 실행 데이터 저장소는 제거했다. 현재 시작·재개는 `src/runtime.py`의 공통 함수를 사용한다. 이전 모의 모델·프롬프트와 `test_experiments.py` 등 이전 계약의 테스트는 삭제 전 흐름을 참조하는 자료로 남아 있으며 현재 동작을 보장하지 않는다.

## 남아 있는 코드

- `state.py`: 요청·메시지·내부 작업 이력·공개 응답·실행 정보의 자료형·어댑터와 초기 상태
- `settings.py`, `exceptions.py`: 설정과 공유 예외
- `graph.py`: 업무 노드 연결·갱신 검사·이력 누적·공개 응답의 대화 기록·질문 재개
- `runtime.py`: State로 시작하고 체크포인트에서 질문을 확인해 재개
- `execution.py`: 호출·재시도·실측 시간 누적, 하위 공유 예산 반영
- `experiments/tools.py`: 합성 자료 조회와 변화율 계산

`State`는 `MessagesState`를 상속한다. request는 goal·constraints, results는 모든 노드의 결정·호출·검증·재시도 기록, response는 공개 안내·중간/최종 결과·질문이다. 지침·도구·API 배포 구성은 execution.version으로 식별한다. 실제 자료 버전·출처·오류·검증 판정은 작업 output에 둔다. subject·info·pending·요청 수정 번호와 별도 sources·issues·result_refs·validation 필드는 제거했다.

`create_state(request, settings, messages=..., version=..., event=...)`는 메시지와 배포 버전을 호출자로부터 받으며 가짜 사용자 발화를 만들지 않는다. response는 null로 시작한다. action.arguments·output·artifacts[].data는 JSON 객체만 검사하며 업무별 상세 계약은 아직 미정이다. Reference 타입은 기존 조회 도구의 출력 참조용으로 유지하며 별도 State 필드가 아니다.

서비스 API·DB, 접근 권한·중복 및 동시 재개·취소 API, 영속 체크포인트는 아직 구현하지 않았다. 새 런타임은 메모리 체크포인터를 사용하는 로컬 시작·질문 재개를 제공한다. 이전 실행기·노드 함수 인자에 의존하는 테스트는 이번 변경에 맞춘 갱신·실행이 필요하며, 현재 동작을 보장하는 근거로 사용하지 않는다. 후속 연동은 [State](../../docs/ieumi-agent-state.md), [실행 흐름](../../docs/ieumi-agent-workflow-design.md), [API 초안](../docs/ai-runtime-api-20261029.md)를 따른다.

## State 계약 검증

2026-10-30, 프로젝트 가상환경에서 독립 계약 검사 53개와 Ruff 검사·포맷 검사를 통과했다. 초기화·시스템/실제 사용자 메시지 보존·입력 격리·제거 필드 거부·성공/실패 기록·검증 작업 기록·공개 응답·JSON 저장/복원 자료형을 확인했다. 문서의 표·로컬 링크·JSON/SSE 예시도 검사했다.

이는 state.py 계약 검증이다. 실제 체크포인트 저장·노드 실행·쓰기 제한·질문 재개·백엔드 연동의 동작 검증이 아니다. 기존 실행 테스트는 이전 계약에 의존하므로 이번 변경의 통과 근거로 사용하지 않았다.

## 모의 실행 검증 결과

아래는 삭제 전 구현의 과거 검증 기록이다. 현재 공통 그래프 데모의 검증 결과가 아니며, 당시의 하위 Agent·실제 표 생성·재시도 등의 실행 연결은 삭제되어 재검증하지 않았다.

2026-10-30, Python 3.12.10, 잠금 파일의 LangGraph 1.2.18 환경에서 확인했다. 조회 데이터는 가상 지역 A(120→108), B(100→92), C(80→72)의 합성 활동지수이며 실제 지역의 위험도 자료가 아니다.

| 시나리오 | 확인한 동작 | 종료 상태 | 모델/도구/하위 호출 |
| --- | --- | --- | --- |
| `normal` | A의 변화율 -10%, 해석과 실제 HTML 표 반환 | completed | 10 / 5 / 2 |
| `ask` | 하위 Agent에서 질문, A로 답변 후 중단 지점 재개 | completed | 11 / 5 / 2 |
| `rework` | 의도적으로 제출한 99%를 거부하고 -10%로 수정 | completed | 11 / 5 / 2 |
| `empty` | 조회 자료 없음 설명, 산출물 없이 부분 완료 | partial | 4 / 1 / 1 |
| `failure` | 조회 실패, 추가 시도 2회 후 재시도 한도 종료 | partial | 2 / 3 / 1 |
| `limit` | 공유 모델 호출 4회 한도 종료, 검증된 해석 보존 | partial | 4 / 2 / 1 |
| `cancel` | 하위 Agent 질문 대기 중 취소 | cancelled | 2 / 0 / 1 |

pytest **35개 통과**. 위 시나리오 외에 잘못된 도구 입력, 미허용 도구, 검증 재작업 한도, 하위 질문 재개 시 조회·상위 추론 중복 방지, 손자 Agent의 결과 보존, 안전한 재시도 조건, 오래된 질문·입력·자료 버전 거부, 상태 스냅샷 격리, 실행 중 취소·시간 제한을 확인했다. 답변 B에 따른 두 전문 Agent의 수치 변경(-8%), 전문 Agent 단독 실행, 저장된 HTML의 실제 셀 값도 검사했다. TypedDict 검증에서는 중첩 입력 오류·추가 필드 거부, 기본값 격리, 수정된 dict의 재검증, 메시지 객체 보존, 하위 Agent의 모델 전달용 도구 스키마를 확인했다.

이 결과는 실행 제어와 합성 자료 처리의 검증이다. 실제 모델의 도구 선택·자연어 해석 품질, 프롬프트 성능, 실제 데이터의 타당성, 시각화의 화면 품질은 평가하지 않았다. 체크포인트·실행 정보는 메모리에 있으며 프로세스 재시작 후 복구되지 않는다. DB, HTTP/SSE, 인증, 서비스 운영을 위한 실행 보관·정리 정책은 구현 범위 밖이다.


### 리포트 표시 의미 검토 (2026-11-02)

표시값의 출처를 `src/state.py`, `src/agent_nodes.py`, `src/graph.py`,
`scenario_demo.py`의 집계, `experiments/scenario_checks.py`의 검사와 대조했다.

| 표시 대상 | 화면에서 구분하는 의미 |
| --- | --- |
| `request.goal` / `messages` | 노드 실행 직전의 요청과 사용자 메시지 원문을 구분한다. 요청은 interpret 단계에서 바뀔 수 있다. |
| 모델 메시지 / State | 전송 메시지는 JSON을 포함한 원문이다. State의 필드 설명으로 메시지 내용을 치환하지 않는다. |
| `response.kind` | 최종 응답, 중간 응답, 진행 상황 안내, 추가 질문을 구분한다. 저장된 응답을 모두 최종 응답으로 부르지 않는다. |
| `accepted` / `outcome` | 결과 검증 미통과를 처리 성공으로 표시하지 않는다. 호출 정상 반환은 사용자 요청 전체의 성공을 뜻하지 않는다. 미기록 outcome도 성공으로 간주하지 않는다. |
| 모델 검증 / 스키마 오류 / 시나리오 검사 | 각각 호출 결과 적합성 판단, 입력·응답·State 형식 검사, 별도 실행 증거 검사다. 스키마 오류는 모델 응답뿐 아니라 도구 입력 등에서도 발생할 수 있다. |
| 통계 | 호출 수·토큰 수의 State 기록 기준을 명시하고, 모델 호출은 추적된 시도 수를 함께 표시한다. 사용량이 기록되지 않은 경우 0으로 추정하지 않는다. |
| `next` / `goto` | 모델이 제안한 다음 단계와 실행기가 지정한 전이를 구분한다. 실행기 제한에 따라 둘은 다를 수 있다. |
| `node_update` / `applied_update` | 둘 다 State의 부분 변경이다. 후자는 실행기가 누적 결과·실행 정보 등을 반영해 그래프에 전달한 값이다. |
| 값과 표시명 | 필드명은 한글 설명과 변수명을 함께 표시한다. 상태 enum은 원래 값을 병기하고, 일반 데이터 문자열은 임의로 번역하지 않는다. |
| 기록 부재 | 추적 기록이 없는 경우 스키마 오류가 없었다고 단정하지 않는다. 빈 목록·null·미기록을 구분한다. |

검증은 기존 실제 실행 S1~S3와 UI 전용 질문 대기·진행 응답·검증 미통과·상태 미기록·스키마 실패 사례를 사용했다.
UI 전용 사례는 모델을 호출하지 않는다. 이번 검토는 리포트의 표시 의미에 대한 검토이며, 모델 판단의 정확성이나 모든 외부 보고서 형식을 보증하는 검사는 아니다.
