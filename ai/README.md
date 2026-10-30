# AI Agent 공통 실행 기반

LangGraph의 ReAct 실행 흐름, `ToolNode`, 체크포인트와 `interrupt`를 사용한다. 하나의 실행 전체가 하나의 `State`를 공유하며 Agent 호출은 순차적으로 처리한다. 현재 범위는 공통 실행 기반과 임시 프롬프트·도구를 이용한 로컬 모의 실행 검증이다. 업무 기준은 [현재 명세 목록](../../docs/README.md)을 따른다.

## 실행

Python 3.12 또는 3.13과 uv가 필요하다. `Eumi/ai`에서 실행한다.

```powershell
uv sync --locked
uv run python demo.py --suite
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

기본 실행은 API 키 없이 동작한다. 모의 모델이 표준 `AIMessage.tool_calls`를 반환하며, 그래프·도구·계산·HTML 생성·검증·질문 후 재개는 실제 코드를 실행한다. 저장 경로는 `outputs/experiment/report.json`과 각 시나리오의 HTML 파일이다. 이 출력 디렉터리는 Git에서 제외한다.

```powershell
uv run python demo.py --scenario ask --answer B
uv run python demo.py --scenario normal --agent analysis
uv run python demo.py --scenario normal --agent visualization
```

`--suite`는 기본 `request_handler`와 기본 답변 A로 아래 7개 시나리오를 재현한다. 출력의 `passed`는 종료 상태 비교 결과이며, 수치·산출물·실행 횟수 검증은 pytest에서 수행한다.

실제 모델 연결 경로도 있으나 이번 검증에서는 호출하지 않았다. 사용할 때는 `.env.example`을 `.env`로 복사하고 `SETTINGS_API_KEY`, 사용할 API 모델 ID인 `SETTINGS_MODEL`을 설정한 뒤 `uv run python demo.py --real --scenario normal`을 실행한다. 이 모드는 네트워크와 모델 사용 비용이 발생하며, 모의 실행의 결과를 보장하지 않는다.

## 구조와 선택 근거

```text
src/
  settings.py   모델 설정과 실행 한도
  state.py      요청·산출물·결과 자료형, 그래프 상태와 공유 실행 정보
  exceptions.py 실행 한도 초과·도구 실패의 공유 예외
  graph.py      행동 선택 → 도구 또는 하위 Agent → 결과 검증
  runtime.py    시작·조회·답변 재개·취소
experiments/
  prompts.py    세 Agent의 임시 지침
  tools.py      합성 자료 조회·변화율 계산·HTML 표 생성
  agents.py     Agent 구성과 업무 결과 검증
  models.py     표준 도구 호출을 반환하는 모의 모델과 실제 모델 연결
demo.py         시나리오 실행·결과 저장
tests/          실행 제어와 실험 결과 검증
```

공통 구현은 5개 모듈이다. `Agent`에 모델·프롬프트·허용 도구·검증 함수·호출 가능한 하위 Agent를 구성하고, `compile_graph`로 실행 전체의 그래프를 만든다. 상위·하위 Agent는 같은 State와 체크포인트를 사용한다. 두 전문 Agent는 각각 최상위 실행으로도 사용할 수 있다.

`exceptions.py`는 `LimitReached`, `ToolFailure`만 정의하며 다른 프로젝트 모듈을 참조하지 않는다. 재시도 판단과 예외 전파는 `graph.py`에, 예외에 따른 최종 실행 상태 결정은 `runtime.py`에 둔다.

요청·산출물·결과는 `TypedDict`, 값 제약은 `Annotated`와 `Field`로 정의한다. `State`도 `MessagesState`를 상속하는 `TypedDict`이며 관련 자료형과 `TypeAdapter`는 `state.py`에 둔다. 별도 `Execution`·`Run` 객체 없이 실행 데이터를 State에 모았다. 그래프 객체와 실행 중 `asyncio.Task`만 실행기가 보관한다.

현재는 필드 정리 전 단계로 기존 정보를 보존한다.

| State 필드 | 내용 |
| --- | --- |
| `request`, `info`, `messages`, `results`, `result` | 최초 요청, 공유 업무 정보, 전체 추론 이력, 검증된 산출물, 최종 결과 |
| `calls`, `active_call` | 호출별 요청·메시지·작업 산출물·결과 후보·결과·오류·상위 호출 연결과 현재 호출 ID |
| `settings`, `run_id`, `agent` | 키를 제외한 실행 설정, 실행 ID, 최상위 Agent 이름 |
| `data_versions`, `input_version`, `instruction_version` | 자료·입력·지침 버전 |
| `usage` | 실행 전체의 모델·도구·하위 호출·재시도 횟수와 활성 시간 |
| `initial`, `public_messages` | 최초 입력 스냅샷과 사용자에게 공개한 대화 이력 |
| `status`, `error`, `pending`, `cancel_requested` | 실행 상태, 종료 오류, 대기 질문, 취소 요청 여부 |

모델에는 현재 호출의 요청·메시지와 공유 업무 정보·산출물을 선택해 전달한다. `calls`는 동일 State 안의 호출 기록이며 별도의 실행 상태 객체가 아니다.

`TypedDict` 생성 자체는 검증을 수행하지 않는다. 요청 입력과 도구의 결과 제출은 해당 어댑터의 `validate_python()`으로 검증한다. 전체 `State`는 실행 생성 시 검증하며, 노드의 부분 갱신은 LangGraph가 처리한다. `@with_config(ConfigDict(extra="forbid"))`로 추가 필드를 거부한다. 생략 가능한 필드는 `NotRequired`로 표시하고, 기존 빈 목록·빈 객체·`partial=False` 기본값은 `Field`에 정의한다. 검증 후에도 데이터는 일반 dict이며 `model_dump()` 변환이 필요하지 않다.

| 책임 | 구현 선택 |
| --- | --- |
| 메시지와 행동 표현 | LangChain의 메시지와 표준 도구 호출을 사용한다. 별도 Action·Observation 변환 계층을 두지 않는다. |
| 도구 입력 검증·호출 | `@tool`과 `ToolNode`에 맡긴다. 자체 도구 레지스트리·디스패처를 두지 않는다. |
| 하위 호출과 질문 재개 | State의 `calls`·`active_call`로 호출 전환을 기록하며, 대기·재개는 LangGraph 체크포인트·`interrupt`를 사용한다. |
| 완료 판단 | `submit_result`로 제출한 후보를 업무 검증 함수가 확인한다. 문제 목록이 있으면 모델에 돌려주고 재작업한다. |
| 공통 실행 정책 | 공유 한도, 제한적인 도구 재시도, 검증된 결과 보존과 실행 수명 관리만 직접 구현한다. |

이 공통 정책과 결과 검증 때문에 단일 ReAct 예제보다 코드가 더 필요하다. HTTP 서버, 스트리밍 이벤트 변환, 저장소 추상화, 범용 플러그인 계층은 현재 구현에 포함하지 않는다.

## 입출력과 실행 조건

`AgentRuntime.start(agent, request, instruction_version=..., info=..., data_versions=...)`는 실행을 시작하고 완료 또는 질문 대기 시 스냅샷을 반환한다. `request`는 `Request(goal, subject, constraints)`다. 실행 중 조회·취소는 별도 asyncio 작업에서 호출할 수 있다.

공개 스냅샷은 다음 6개 필드를 갖는다.

| 필드 | 내용 |
| --- | --- |
| `request` | 최초 요청 목표·대상·제약 |
| `info` | 호출자가 제공한 JSON 정보 |
| `messages` | 사용자 요청, 질문, 답변, 완료 설명 |
| `results` | 검증을 통과한 해석·시각화 산출물 |
| `response` | 현재 설명과 참조 자료 |
| `execution` | 실행 ID·상태·입력/자료/지침 버전·대기 질문·사용량·오류 |

`get(run_id)`로 조회한다. 질문 대기의 상태는 `waiting_input`이며 `execution.pending`에 질문 ID와 질문이 들어간다. 재개는 `resume(run_id, pending_id=..., expected_input_version=..., content=..., data_versions=...)`로 수행한다. 질문 ID, 입력 버전, 전체 자료 버전이 일치하고 답변이 비어 있지 않아야 한다. 답변을 수락하면 입력 버전이 증가한다. 자료가 바뀌었다면 새 실행을 시작한다.

종료 상태는 `completed`, `partial`, `failed`, `cancelled`다. 실행 한도·활성 실행 시간 초과는 `partial`, 공통 실행 중 예기치 않은 오류는 `failed`가 된다. 업무 검증 함수가 받아들인 부분 결과도 `partial`이다. `cancel(run_id)`는 실행 중 또는 대기 중에 사용할 수 있으며, 종료된 실행을 다시 취소해도 상태가 바뀌지 않는다. 이미 발생한 외부 효과를 되돌리지는 않는다.

| 설정 | 기본값 | 계산 범위 |
| --- | ---: | --- |
| `max_steps` | 20 | 모델 호출 시도 |
| `max_tool_calls` | 10 | 업무 도구 호출 시도, 입력 오류·재시도 포함 |
| `max_agent_calls` | 10 | 입력 형식 검증을 통과한 하위 Agent 호출 |
| `max_tool_retries` | 2 | 자동 추가 시도 |
| `runtime_timeout` | 60초 | 사용자 답변 대기 시간을 제외한 전체 활성 실행 |
| `llm_timeout` | 30초 | 실제 모델 연결의 요청 timeout |

한도는 상위·하위 Agent 전체에서 공유한다. `ask_user`, `submit_result`는 업무 도구 횟수에서 제외하지만 이를 선택한 모델 호출은 단계 수에 포함한다. 한 번에 하나의 도구만 실행하며 여러 도구를 동시에 요청하면 실행 없이 수정 요청을 반환한다.

자동 재시도는 `metadata.retry_safe=True`인 도구가 `ToolFailure(..., retryable=True)`를 낸 경우에만 허용한다. 모델 SDK 자체 재시도는 끈다. 도구 실패는 모델에 오류 메시지로 전달하고, 실행 한도 도달은 전체 실행을 멈춘다. 앞서 검증된 산출물은 이후 상위 Agent 실패·취소·한도 초과에도 보존한다. 일반 예외의 상세 메시지는 공개 응답에 넣지 않는다.

모델 ID·키만 환경변수 또는 `.env`에서 읽는다. 실행 한도와 timeout은 `Settings` 기본값 또는 생성 인자로 지정한다. API 키는 실행 컨텍스트·체크포인트·공개 상태에 넣지 않는다.

## 모의 실행 검증 결과

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

## 구현 레퍼런스

- [LangChain react-agent](https://github.com/langchain-ai/react-agent/blob/87aac0fdcb811d05457314a42418f3fbe139933a/src/react_agent/graph.py): 모델 노드와 `ToolNode` 사이의 짧은 ReAct 루프를 기준으로 삼았다.
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts): 질문 대기와 `Command(resume=...)`를 적용했다. 호출 전 사용량을 체크포인트에 기록하고, 재개 시 대기 중이던 도구부터 이어간다.
- [Pydantic TypeAdapter](https://pydantic.dev/docs/validation/latest/concepts/type_adapter/): TypedDict의 검증과 하위 Agent 도구용 JSON Schema 생성에 사용한다.

공통 실행기는 임시 프롬프트·도구·모의 모델을 import하지 않는다. 실제 업무로 전환할 때는 `experiments/`의 구성·도구·검증 함수를 교체하고, 같은 공통 흐름으로 다시 검증한다.
