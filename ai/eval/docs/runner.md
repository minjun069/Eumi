# 단위 평가 실행기

수정일: 2026-11-13.

준비한 JSON 사례에서 도구·노드·작업 선택·에이전트·보고서 생성 흐름을 골라 실행하고, 입력과 실제 결과를 사례별로 저장한다. 노드·작업 선택은 서비스와 같은 모델 입력을 만들어 원본 응답을 한 번 수집한다. 에이전트·생성 흐름은 실제 업무 코드를 실행하며 하위 호출에 준비한 응답을 제공할 수 있다. 실행과 채점은 다음 명령으로 나눈다.

| 명령 | 책임 |
| --- | --- |
| `run` | 선택한 범위의 입력·출력·호출 증거 수집. 에이전트·생성 흐름은 상태 변경도 기록 |
| `score` | 데이터 검색 및 조회·데이터 가공·시각화 검증 도구의 저장 결과를 독립 기대값과 비교하고 검사별 판정·도구별 지표 저장 |
| `score-nodes` | 저장된 노드의 원본 모델 응답을 규칙·LLM으로 평가하고 검사별 판정·노드 및 역할별 지표 저장 |
| `score-executions` | 에이전트·동별 보고서의 실행 시간·사용량 집계. 사용자 요청·동별 보고서는 전이·상태 전달·공유 한도·반환도 규칙으로 검사 |
| `score-outputs` | 실제 최종 반환에 채택된 답변·보고서 산출물을 작성 원문에 연결하고 응답 작성 기준으로 품질 평가 |

시나리오 실행기, 규칙 평가 실행기, LLM 평가 실행기의 책임과 노드 채점 사용법은 [평가 실행 안내](../README.md)를 따른다. 채점은 업무를 다시 실행하지 않으며 LLM 평가는 별도 평가 모델을 호출한다.

`score-nodes`의 운영 통계도 채점 대상으로 선택한 모델 호출만 사용한다. 모델 호출별 시간·토큰·오류를 부모 노드 단위로 합산하며, 부모 노드 전체 실행의 후처리 시간·도구 호출·상태 반영 오류는 원본 추적에 보존한다. 측정 범위는 [노드 운영 지표와 목표](../README.md#운영-지표와-목표)를 따른다.

노드 채점의 `--case`, `--check`, `--row`는 기존 사례 선언 안에서 채점 범위를 좁힌다. 모든 예정 반복의 실제 호출을 JSON의 적용 조건과 먼저 대조해 조건 불일치는 제외하고, 증거 부족은 미판정으로 유지한다. 선택·제외 사유와 반복별 계획을 별도 채점 결과에 남기며 원본 사례·실행 기록은 변경하지 않는다. 선택 옵션과 행별 기대 항목은 [노드 채점 실행](../README.md#실행)과 [평가 자료 준비](../README.md#평가-자료-준비)를 따른다.

노드 평가 기준은 JSON의 평탄한 검사 행(`checks`)에 원본 열과 표현을 보존한다. 실행 상황과 원칙 참조는 `bindings`로 연결하며, 선택한 행과 관련 원칙만 평가에 사용한다.

평가자가 준비할 기준 자료와 판정 원칙은 [평가 방법](methods.md), 검사 항목은 [단위별 평가 문서](../../docs/README.md#평가)를 따른다. 실행 완료는 평가 통과를 뜻하지 않는다. 제공 자료는 [합성자료 도구 사례](../scenarios/tools/README.md), [서비스 DB 조회 사례](../scenarios/database/README.md), [실행 연결 사례](../scenarios/execution/README.md)를 따른다. 새 사례의 시작 양식은 [빈 입력 양식](../suite-template.json)이다.

## 1. 실행 범위

| 실행 단위 | `unit` | `target` | 실행하는 범위 |
| --- | --- | --- | --- |
| 도구 | `tool` | `query_data`, `process_data`, `validate_visualization`, `render_visualization` | 지정한 도구의 실제 입력 검사·처리·반환 |
| 노드 | `node` | `interpret`, `act`, `decide`, `compose`, `ask` | 지정한 노드의 실제 모델 입력과 원본 응답 1회 수집 |
| 작업 선택 | `selection` | `act` | 작업 선택 모델의 실제 입력과 원본 응답 1회 수집. 노드 지표에서 제외 |
| 에이전트 | `agent` | `request`, `interpretation`, `visualization`, `report_selection`, `report_description`, `report_insight` | 지정한 역할의 실제 공통 업무 그래프 |
| 보고서 생성 흐름 | `workflow` | `report` | 한 동에서 선정 → 설명 → 인사이트 에이전트를 순차 실행하는 실제 생성 흐름 |

노드·작업 선택은 모델 응답을 업무 State에 반영하지 않고 도구·하위 에이전트·렌더링·다음 경로를 실행하지 않는다. 원본 응답의 형식·내용은 별도 채점 단계에서 확인한다. 보고서 작성·검토·재작성도 각각 기존 입력에서 독립 호출하며, 필요한 호출은 `model_call`로 지정한다. 생략하면 초기 상태에서 다음에 필요한 첫 모델 호출만 실행하고, 모델 호출 없이 끝나는 단계는 실행 오류로 기록한다. 작성 → 검토 → 진행 판단 → 추가 작업의 연결과 상태 반영은 에이전트·생성 흐름 단위에서 확인한다.

세 보고서 에이전트는 각각 자기 산출물을 위한 작업 선택·실행, 진행 판단, 작성·검토를 실행한다. `workflow/report`는 같은 동의 State와 누적 예산을 전달하며 세 에이전트를 순차 실행한다. `agent/report`는 허용하지 않는다. 업무 흐름과 이력 구조는 [보고서 생성](../../docs/agent/report.md)을 따른다.

이 단위 실행기는 HTTP 접수, 업무 결과의 데이터베이스 저장, 요청 전체의 실패 단계 재처리·완료 알림을 실행하지 않는다. 이 경계는 [보고서 업무 테스트](../../tests/test_reports.py)와 [파일 DB 왕복 테스트](../../tests/test_report_roundtrip.py)에서 실제 배치 코드를 실행해 별도로 검증한다. 파일 DB·모의 백엔드의 통과로 운영 연동을 판정하지 않는다.

### 하위 호출

| `dependencies` | 처리 | 확인할 범위 |
| --- | --- | --- |
| `real` | 실제 도구와 하위 에이전트를 호출. 생략 시 기본값 | 선택한 자료원의 처리 구현과 하위 실행 연결 |
| `stub` | 도구·하위 에이전트·표 렌더링 호출에 미리 정한 응답이나 오류를 제공 | 하위 결과가 주어졌을 때 평가 대상이 수행하는 판단과 처리 |

조회 자료의 제공 방식은 `data_source`로 선택한다. 기본값 `prepared`는 입력 파일의 `datasets`를 복사해 제공한다. `database`는 별도 평가 DB에 적재한 원본을 [실제 서비스 조회 코드](../../src/database.py)로 읽는다. `real`은 실제 도구 구현을 사용한다는 뜻이며 자료 제공 방식과는 구분한다. 결과의 보고 범위는 [평가 범위와 한계](#평가-범위와-한계)를 따른다. 노드·작업 선택·에이전트는 설정된 실제 모델을 호출한다. `stub`도 평가 대상의 판단 모델은 교체하지 않는다.

노드 단독은 도구 명세·카탈로그로 모델 입력을 구성하지만 하위 호출은 수행하지 않는다. 기존 노드 입력에 있는 `dependencies`·`stubs`는 실행에 사용하지 않으며, 준비한 하위 응답은 에이전트·생성 흐름에서 적용한다.

도구 자체를 평가할 때는 실제 구현을 실행하므로 `stub`을 사용할 수 없다. 작업 선택에는 하위 호출이 없으므로 `dependencies`와 `stubs`를 생략한다. 모의 응답 사용 결과는 실제 서비스 연동의 증거와 구분한다.

## 2. 입력 준비

입력 형식의 원본은 [입력 정의](../schema.py)다. 새 사례는 [빈 양식](../suite-template.json)을 복사해 작성한다. 기존 21개 시나리오를 사용할 때는 [시나리오 색인을 직접 전달](#기존-시나리오-직접-실행)한다. 빈 `cases`는 양식 검사에 통과하지만 실행할 사례가 없으면 실행 명령은 거부한다.

| 최상위 항목 | 필수 | 내용 |
| --- | --- | --- |
| `schema_version` | 필수 | `evaluation-suite-v1` |
| `id` | 필수 | 평가 묶음 이름. 영문·숫자로 시작하고 영문·숫자·밑줄·점·하이픈 사용 |
| `data_source` | 선택 | `prepared` 또는 `database`. 생략 시 `prepared` |
| `datasets` | 선택 | `prepared`에서 제공할 자료 이름별 조회 자료. 키와 자료의 `reference.id`가 일치해야 함 |
| `catalog` | 선택 | `prepared` 자료의 모델용 안내. 키는 `datasets`에 있는 자료 이름 |
| `database_fixture` | 조건부 | `database`에서 필수. 서비스 테이블 이름을 키로, 적재할 원본 행 배열을 값으로 지정 |
| `cases` | 필수 | 실행할 사례 배열. 사례 ID는 묶음 안에서 중복 불가 |
| `performance` | 선택 | 도구별 정상·오류 호출의 성능 시험 조건·목표. [도구 채점](#6-도구-채점) 참조 |
| `node_performance` | 선택 | 노드·역할별 응답시간·기술적 실패율의 시험 조건·목표. [노드 운영 지표와 목표](../README.md#운영-지표와-목표) 참조 |
| `execution_performance` | 선택 | 사용자 요청·동별 보고서 실행의 필수 운영 목표. [실행 채점](#8-실행-전체-채점) 참조 |
| `execution_prices` | 선택 | 실행 비용을 계산할 모델·도구 단가와 통화·버전. [실행 채점](#8-실행-전체-채점) 참조 |

준비 자료 방식의 열·행·출처·버전은 [도구 자료 형식](../../src/tools/data.py)의 `Dataset`을 따른다. 카탈로그를 생략한 자료는 행을 제외한 자료 설명으로 안내를 구성한다. 준비한 자료는 실행마다 복사하여 다른 사례나 반복 실행의 변경이 섞이지 않게 한다.

| 사례 항목 | 필수 | 내용 |
| --- | --- | --- |
| `id` | 필수 | 사례 식별자. 입력 묶음의 `id`와 같은 문자 규칙 |
| `unit` | 필수 | 실행 단위 |
| `target` | 필수 | 실행할 도구·노드·에이전트 이름 |
| `purpose` | 필수 | 이 사례에서 확인할 목적 |
| `role` | 조건부 | 노드·작업 선택에서 필수. [실행 범위](#1-실행-범위)의 에이전트 역할 중 선택. 도구·에이전트·생성 흐름에는 지정하지 않음 |
| `model_call` | 선택 | 보고서 역할의 `node/compose`에서 독립 실행할 모델 호출. [호출별 준비](../README.md#평가-자료-준비) 참조 |
| `initial` | 조건부 | 노드·작업 선택·에이전트·생성 흐름의 초기 입력. 시각화 검증 도구에도 필수 |
| `arguments` | 조건부 | 도구에 전달할 입력. 도구에서만 사용 |
| `providers` | 선택 | 이번 사례에 제공할 자료 이름. 생략하면 선택한 방식의 등록 자료원 전체 제공 |
| `provider_failures` | 선택 | 자료원 이름별로 발생시킬 예외. [자료원 장애](#자료원-장애) 참조 |
| `dependencies` | 선택 | 하위 호출 방식 |
| `stubs` | 선택 | 하위 호출에 제공할 응답 목록. 에이전트·생성 흐름의 `stub` 실행에서 사용 |
| `assessment` | 선택 | 검사 ID·호출 범위·필수 여부와 규칙 검사에 필요한 독립 기준·기대값·허용 범위 |
| `tags` | 선택 | 사례를 설명하는 분류 이름. 현재 명령줄 필터에는 사용하지 않음 |

`initial`에는 작업 요청 `request`, 시작 이벤트 `event`, 대화 `messages`를 넣는다. 필요하면 이전 이력 `results`와 현재 공개 응답 `response`를 제공한다. 실행 메타데이터는 다음 두 방식 중 하나로 준비하며 기존 [State 계약](../../docs/agent/state.md)을 사용한다.

| 준비 방식 | 제공 항목 | 실행기가 구성하는 상태 |
| --- | --- | --- |
| 새 실행 시작 | `execution` 생략. 필요하면 `budget`, `execution_error` 지정 | 초기 실행 상태를 생성하고 제공한 예산·오류 적용 |
| 기존 실행 시점·재진입 준비 | 기존 `Execution` 전체를 `execution`에 지정 | 제공한 상태·버전·누적 예산·오류 보존 |

`execution.event`는 `initial.event`와 같아야 하며, `execution`과 `budget`·`execution_error`를 함께 지정하면 입력 오류다. 두 방식 모두 실행 ID는 현재 평가 실행 ID를 사용한다. 초기 입력은 각 반복마다 새로 복사하므로 한 반복의 상태 변경이 다음 반복의 입력에 영향을 주지 않는다.

보고서 세 역할과 생성 흐름은 `event`가 `analysis_pipeline`이어야 한다. `results`에 기존 형식의 `report_input` 이력과 `report_source` 이력을 넣는다. 전자는 [보고서 입력 형식](../../src/state.py)의 `ReportInput`, 후자는 근거 수정 시각인 `updated_at` 문자열을 포함한다. 선정 에이전트는 이 입력에서 자료를 확보한다. 설명 에이전트는 검토를 통과한 선정과 근거를, 인사이트 에이전트는 검증된 설명과 근거를 초기 이력으로 받는다. 선정·작성·검토 도중의 노드를 평가할 때도 해당 단계가 읽는 앞선 이력을 준비한다. 평가 기준·기대 답안은 이 이력에 넣지 않는다.

`assessment`의 `reference`, `expected`, `tolerance`, `checks`, `required`는 평가 자료다. 업무 모델 입력과 State로 전달하지 않는다. `score`가 해석하는 기대값은 [도구 채점](#6-도구-채점), `score-nodes`의 `node-expectations-v1` 형식과 규칙 비교·LLM 대상 선택은 [노드 평가 자료 준비](../README.md#평가-자료-준비), `score-executions`의 `execution-expectations-v1` 형식은 [실행 채점](#8-실행-전체-채점)을 따른다. 기존 자유 형식의 기대값은 보존하지만 자동 해석하지 않는다.

모든 노드 LLM 검사는 실행 당시 모델 호출 입력 전체·실제 출력과 현행 검사 기준으로 판정한다. 입력은 선택한 호출에 저장된 모든 메시지와 당시 응답 스키마를 원본 그대로 제공한다. 사례의 항목 ID·검사 ID·호출 범위는 선택과 결과 연결에 사용하며, 기대답안·별도 기준 자료·허용 오차·비교 조건은 평가 프롬프트에 전달하지 않는다. 규칙 검사에서는 각 검사에 정한 기대값·기준 자료·허용 오차를 계속 사용한다.

### DB 원본 자료

`database_fixture`는 서비스 DB에 넣을 원본이며 정답은 `assessment`에 따로 작성한다. 서비스의 기존 마이그레이션을 적용한 별도 평가 DB를 사용한다. 접속 정보는 환경 설정의 `SETTINGS_DATABASE_URL`로 받고 시나리오에는 넣지 않는다. DB 이름은 `eumi_eval` 또는 `eumi_eval_`로 시작해야 한다.

| 원본 테이블 | 실제 서비스 자료원에서 사용하는 내용 |
| --- | --- |
| `public.dim_region` | 지역 식별자와 이름. 분석 결과·격자의 참조 대상 |
| `public.region_result` | 읍면동 월별 점수·단계 |
| `analysis.dim_grid100` | 격자와 읍면동의 대응 |
| `analysis.bh_region_contribution` | 읍면동·월·지표별 기여도 |
| `analysis.bh_grid_anomaly` | 격자 이상 점수. 격자 테이블과 결합해 읍면동을 반환 |
| `analysis.flow_detail` | 격자별 활동 합계·관측일 수. 읍면동별 일평균 활동량으로 계산·합산 |

행에는 허용된 모든 열을 명시한다. 결측 가능한 열은 `null`로, 날짜와 수정 시각은 ISO 문자열로 지정한다. 생략한 테이블은 빈 테이블로 간주한다. 허용 열·형식은 [DB 입력 검사](../database.py), 완성 예시는 [서비스 조회 입력](../scenarios/database/service-query.json)을 따른다. `validate`는 자료형·숫자 정밀도를 검사하며, 월 첫날·등급 범위·기본 키·외래 키 조건은 적재 시 DB 제약으로 확인한다. 제약 위반 시 해당 적재 전체를 롤백한다.

DB 방식에서는 `datasets`, `catalog`, `provider_failures`를 지정할 수 없다. 실제 서비스의 `Database.report_sources()`가 등록한 `public.region_result`, `analysis.bh_region_contribution`, `analysis.bh_grid_anomaly`, `analysis.flow_detail`을 사용한다. `providers`로 이 중 제공할 자료원을 선택하며 원본 테이블 두 개(`dim_region`, `dim_grid100`)를 직접 조회 자료원으로 등록하지 않는다.

`prepare-db`는 빈 평가 테이블에 원본을 한 트랜잭션으로 적재한다. 이미 같은 원본이면 변경하지 않고, 다른 자료가 있으면 삭제·덮어쓰기 없이 거부한다. `run`은 시작 전에 여섯 테이블 전체와 원본의 일치를 읽기 전용으로 검사하며 자료를 적재하지 않는다. 검사 뒤 평가가 끝날 때까지 다른 프로세스에서 해당 DB를 수정하지 않아야 한다. 각 조회는 서비스 코드로 다시 읽으므로 실행 중 변경을 고정하는 스냅샷 기능은 없다.

### 자료원 장애

`prepared` 방식의 사례에서 `provider_failures`에 자료원별 예외를 지정하면 해당 자료원을 실제로 호출할 때마다 예외가 발생한다. 실제 `query_data`가 이 예외를 도구 오류로 변환하므로 자료원 장애에 대한 오류 처리와 저장 증거를 평가할 수 있다. DB 방식에서는 이 모의 장애 설정을 허용하지 않는다.

```json
"provider_failures": {"activity": "TimeoutError"}
```

| 설정값 | 조회 오류 코드 | 재시도 가능 |
| --- | --- | --- |
| `PermissionError` | `permission_denied` | `false` |
| `TimeoutError` | `read_unavailable` | `true` |
| `ConnectionError` | `read_unavailable` | `true` |

키는 `datasets`에 등록되고 이번 사례의 `providers`에도 포함된 자료원이어야 한다. `providers`를 생략하면 등록 자료원 전체를 제공하고, 빈 배열이면 아무 자료원도 제공하지 않는다. 위 세 예외명만 허용하며 잘못된 값이나 제공하지 않는 자료원은 입력 검사에서 거부한다.

설정하지 않은 자료원은 준비한 자료를 반환한다. 호출되지 않은 자료원의 장애는 발생하지 않으며, 설정은 다른 사례나 반복에 누적되지 않는다. 설정 원본은 평가 묶음·사례 입력에 보존하고 업무 State나 모델 입력에는 추가하지 않는다. `stub`으로 도구 호출 자체를 대체하면 자료원도 호출하지 않으므로 이 장애 설정은 실행되지 않는다.

기대 오류는 원본 실행에서 `error`로 기록되더라도 채점에서 통과할 수 있다. 오류 코드·재시도 여부에 더해 자료원 호출 기록, `failure.cause`의 원인 예외, 정상 출력 부재를 기대값으로 비교한다. 데이터 검색 및 조회 도구의 [권한·읽기 장애 및 설정 격리 사례](../scenarios/tools/README.md#권한읽기-장애-및-설정-격리)는 정상 0건과 오류의 구분도 확인한다. `TimeoutError` 설정은 시간 초과 예외의 처리를 시험하며 실제 호출을 제한 시간에 중단하지 않는다.

### 준비된 하위 응답

각 `stubs` 항목은 호출 이름 `name`, 일치시킬 입력 `arguments`, 반환할 `output` 또는 발생시킬 `error` 하나를 갖는다. `uses`로 사용할 횟수를 정하며 기본값은 1이다. 같은 이름·입력의 항목을 중복 작성하지 않고 `uses`를 늘린다.

도구는 참조를 풀어 실제 호출에 전달하는 인자와 대조한다. 하위 에이전트 이름은 `interpretation_agent`, `visualization_agent`이며 호출 목적 `goal`을 대조한다. 하위 에이전트 반환은 기존 형식의 `response`, `results`, `status`, `error`를 포함해야 한다.

모의 응답은 도구 구현을 호출하는 지점에서 반환하므로 그 도구 내부의 입력 검사와 처리는 실행하지 않는다. 에이전트·생성 흐름 안의 선택·인자 해석·이력·예산 처리는 그대로 수행한다. 정상 결과를 전제로 평가하려면 작성자가 실제 도구의 반환 형식과 의미에 맞는 `output`을 준비해야 한다.

호출 이름과 인자가 모두 같고 남은 사용 횟수가 있는 응답만 제공한다. 인자의 객체 키 순서는 무시하되 논리값·숫자·문자열 등 값의 종류는 구분한다. 일치하지 않거나 횟수를 소진한 호출은 실제 도구로 넘기지 않고 예상 밖 호출로 기록한다. 사용한 응답, 남은 응답, 예상 밖 호출을 실행 결과에서 확인할 수 있다. 미사용 응답 자체를 평가 실패로 판정하지는 않는다.

## 3. 실행

명령은 `Eumi/ai`에서 실행한다. 설치·모델 환경 설정은 [실행 안내](../../README.md#설치설정)를 따른다. 도구만 실행할 때는 모델을 생성하지 않는다. 나머지 단위는 실제 모델 호출을 위한 설정이 필요하다.

```powershell
uv run python -m eval schema --output eval/outputs/evaluation-schema.json
uv run python -m eval validate eval/suite-template.json
uv run python -m eval validate eval/scenarios/tools/visualization.json
```

`schema`는 입력 구조를 JSON Schema로 내보내며 `--output`을 생략하면 표준 출력으로 보낸다. `validate`는 모델·도구를 호출하지 않고 형식, 대상 조합, 중복, 자료 참조, 준비 자료와 보고서 초기 입력을 검사한다. 조건부 입력 규칙도 있으므로 JSON Schema 검사에 더해 `validate`를 사용한다. 잘못된 도구 인자에 대한 시험은 도구 실행 시 실제 도구의 검사 결과로 확인한다.

사례를 작성한 `suite.json`을 다음과 같이 실행한다.

```powershell
uv run python -m eval run suite.json --output eval/outputs/evaluations
uv run python -m eval run suite.json --unit tool --target query_data --repeat 3
uv run python -m eval run suite.json --unit node --target act
uv run python -m eval run suite.json --unit selection
uv run python -m eval run suite.json --unit agent --target report_selection
uv run python -m eval run suite.json --unit agent --target report_description
uv run python -m eval run suite.json --unit agent --target report_insight
uv run python -m eval run suite.json --unit workflow --target report
uv run python -m eval run suite.json --case case-a --case case-b
uv run python -m eval score eval/outputs/evaluations/<묶음-ID>
uv run python -m eval score-nodes eval/outputs/evaluations/<노드명>/<묶음-ID>
uv run python -m eval score-nodes eval/outputs/evaluations/<묶음-ID> --method all --judge-model <평가 모델 이름>
```

아래 옵션은 `run`에 적용한다. 채점 옵션은 [도구 채점](#실행과-저장)과 [노드 채점 실행](../README.md#실행)을 따른다.

| 옵션 | 동작 |
| --- | --- |
| `--output` | 출력 루트. 기본값 `eval/outputs/evaluations` |
| `--case` | 사례 ID 선택. 여러 번 지정 가능 |
| `--unit` | 실행 단위 선택 |
| `--target` | 대상 이름 선택 |
| `--repeat` | 선택한 사례별 반복 횟수. 기본값 1, 양의 정수 |
| `--env-file` | 환경 파일. 기본값 `.env` |
| `--model` | 실행에 사용할 모델 이름 변경 |
| `--prices` | [실행 비용 단가](#운영-측정과-목표) 형식의 JSON 파일. 묶음의 `execution_prices`에 기록하며 기존 값이 있으면 명시한 값으로 대체 |

필터를 함께 지정하면 모든 조건을 만족하는 사례만 실행한다. 사례 배열 순서대로 각 사례의 반복을 마친 뒤 다음 사례로 이동한다. 병렬 실행은 제공하지 않는다. 매 반복은 새 실행 ID·State·모의 응답 사용 횟수·출력 폴더를 사용한다. 여러 노드·에이전트가 선택되면 대상별 저장 묶음을 만들며, 실행 순서는 그대로 유지한다. 명령줄에는 각 묶음의 경로·상태·실행 수를 출력한다. Python의 `run_suite`는 묶음 하나일 때 `Path`, 여러 개일 때 처음 선택된 대상 순서의 `list[Path]`를 반환한다.

개별 실행 예외는 결과에 남기고 다음 실행을 계속한다. 저장 실패는 실행을 중단하며, 취소는 가능한 종료 기록을 저장한 뒤 호출자에게 전달한다. 각 묶음의 계획은 첫 실행 전에 저장한다. 중단 시 이미 끝난 묶음의 상태를 보존하고, 진행 중이거나 시작 전인 묶음에 중단 상태·사유를 남긴다. 에이전트 실행 중 취소되면 이미 완료한 노드의 마지막 State를 보존한다. 다시 실행하면 새 묶음을 만들며 기존 묶음의 이어 실행은 제공하지 않는다.

| 종료 코드 | 의미 |
| --- | --- |
| `0` | 입력 검사·스키마 출력 성공, 선택한 실행이 모두 반환됨 또는 채점 결과 저장 성공 |
| `1` | 실행 예외 또는 저장 실패 |
| `2` | 입력 형식·조합·설정 검증 오류, 없는 사례 ID, 선택된 사례 없음 |
| `130` | 사용자 취소 |

반환된 업무 State가 실패·부분 완료·질문 대기일 수 있다. 종료 코드 `0`과 실행 상태 `returned`는 정답이나 업무 완료를 보증하지 않는다.

### 기존 시나리오 직접 실행

[21개 기본 시나리오](../scenarios/nodes/README.md)의 `scenarios.json` 색인을 `run`·`validate`에 직접 전달할 수 있다. 프로그램이 선택한 시나리오의 역할·시작 상태·참조 스냅샷을 읽어 메모리에서 기존 실행 입력을 구성한다. 별도의 실행용 입력 파일을 준비하지 않는다. 실행 결과 폴더의 `suite.json`은 실제 사용한 입력을 보존하는 기존 증거 파일이다.

```powershell
uv run python -m eval validate eval/scenarios/nodes/scenarios.json
uv run python -m eval run eval/scenarios/nodes/scenarios.json --unit agent --case basic-request-revision --repeat 3
uv run python -m eval run eval/scenarios/nodes/scenarios.json --unit agent --target interpretation
uv run python -m eval run eval/scenarios/nodes/scenarios.json --unit workflow --target report
uv run python -m eval score-executions <실행묶음경로>
```

| 선택 | 실제 실행 | EX 자동 검사 | 운영 측정 |
| --- | --- | --- | --- |
| `--unit agent` 또는 단위 생략 | 선택한 역할의 `start_state`에서 실행. 전체 선택 시 여섯 역할 21개 | 사용자 요청 4개에 EX-1~5. 나머지 17개 역할 단독 실행은 기능 판정 범위 밖 | 모든 선택 역할 |
| `--unit workflow --target report` | 선정 시나리오의 `entry_transition.before_state`에서 세 역할을 순차 실행. 전체 선택 시 동별 3개 | EX-1~5, EX-R1~5 | 모든 선택 동별 실행 |

`--case`는 원본 시나리오 ID이며 여러 번 지정할 수 있다. 보고서 전체에서 특정 동을 고를 때는 `--case basic-report_selection-1168065500`처럼 선정 시나리오 ID를 사용한다. 설명·인사이트 시나리오를 전체 보고서의 시작점으로 지정하면 입력 오류다. `--target`은 역할 이름 또는 전체 흐름의 `report`이며, 시나리오 색인에는 `tool`·`node`·`selection` 단위를 사용할 수 없다. `validate`에도 같은 선택 옵션과 `--prices`를 사용할 수 있다. 기존 `evaluation-suite-v1` 입력의 선택 옵션은 해당 묶음의 사례 필터로 동작한다.

각 역할의 기존 대화·앞 단계 승인 결과·근거·공개 응답·누적 한도·버전을 보존하고 실행 ID만 새로 부여한다. 역할 단독 실행에는 역할 진입 기록이 있는 `start_state`를 사용하며, 전체 보고서는 역할 진입 전부터 시작해 실행기가 진입 기록을 만든다. 각 시나리오는 독립적으로 실행하며 앞서 실행한 시나리오의 새 결과를 다음 시나리오에 자동 전달하지 않는다.

자료는 색인이 참조한 고정 스냅샷의 `datasets`·`catalog`와 기존 사례의 자료원 범위를 사용한다. 준비된 자료를 실제 조회·가공 도구에 연결하고 DB를 다시 읽지 않는다. 이후 단계 상태·예시 답변·고정 모델 응답·모의 하위 결과·노드 품질 기대값은 실행 입력으로 옮기지 않는다. 실제 실행에는 설정된 업무 모델이 필요하며, `score-executions`는 평가 모델을 호출하지 않는다.

시나리오 실행은 지원 범위의 EX 검사만 선언하고, 생성 당시의 노드 경로·응답 내용·보고서 완성 결과를 정답으로 강제하지 않는다. `score-executions`는 기능 검사와 시간·호출량·토큰·비용을 확인하고, [최종 출력 품질](#9-최종-출력-품질)은 `score-outputs`로 별도 평가한다. 단가를 제공하려면 `run ... --prices <단가-JSON>`을 추가한다. 토큰·단가가 없으면 비용은 산출 불가이며, 운영 목표를 임의로 만들지 않는다. 단가 파일은 실행 입력 묶음과 구분되는 평가 설정이다.

### DB 평가 준비와 실행

로컬 서버는 [개발 DB 실행 안내](../../../infra/README.md#로컬-개발-db)를 따른다. 처음 한 번 `Eumi/infra`에서 별도 DB를 생성하고 서비스 마이그레이션·권한을 적용한다. 기존 `eumi` DB를 복제하거나 서비스용 seed를 적재하지 않는다. 이미 DB가 있으면 생성 단계는 생략한다.

```powershell
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres -c "CREATE DATABASE eumi_eval OWNER eumi_owner" -c "ALTER DATABASE eumi_eval SET timezone TO 'Asia/Seoul'"
docker compose run --rm --no-deps -e FLYWAY_URL=jdbc:postgresql://postgres:5432/eumi_eval -e FLYWAY_LOCATIONS=filesystem:/flyway/sql flyway
```

`Eumi/ai/eval/`에 평가용 환경 파일 두 개를 준비한다. 모두 같은 서버의 `eumi_eval`을 가리키고 기존 로컬 계정의 비밀번호를 사용한다. `Eumi/ai/`를 기준으로 `eval/.env.evaluation-seed`의 `SETTINGS_DATABASE_URL`은 적재 권한이 있는 `eumi_pipeline`, `eval/.env.evaluation`은 서비스와 같은 읽기 권한의 `eumi_ai`로 설정한다. 비밀값이 들어 있는 파일은 버전 관리에 넣지 않는다.

```powershell
uv run python -m eval validate eval/scenarios/database/service-query.json
uv run python -m eval prepare-db eval/scenarios/database/service-query.json --env-file eval/.env.evaluation-seed
uv run python -m eval run eval/scenarios/database/service-query.json --env-file eval/.env.evaluation --repeat 3
uv run python -m eval score eval/outputs/evaluations/<묶음-ID>
```

입력 검사는 DB에 접속하지 않는다. 적재와 실행은 DB 접속이 필요하며 모델을 호출하지 않는 도구 사례에는 모델 API 키가 필요 없다. 다른 원본을 시험하려면 새로운 `eumi_eval_*` DB에 같은 마이그레이션을 적용한다. 자료 삭제·DB 초기화 명령은 제공하지 않는다.

## 4. 저장 결과

실행 입력·결과와 채점 결과는 아래 필드 구조의 일반 JSON으로 저장한다. 시간순 추적은 호출의 전체 스냅샷을 한 줄씩 기록하는 JSONL 파일이다.

노드·작업 선택 평가는 `<출력 루트>/<노드명>/평가대상_실행시작일_실행번호`에, 독립 에이전트 실행은 `<출력 루트>/<에이전트명>/평가대상_실행시작일_실행번호`에 저장한다. 예를 들어 `evaluations/decide/노드평가_2026-11-12_실행01`은 decide 노드의 묶음이고, `evaluations/request/실행평가_2026-11-12_실행01`은 사용자 요청 에이전트의 묶음이다. 여러 노드·에이전트를 함께 선택해도 대상별 실행 계획·원본·채점을 각각 저장한다. 같은 노드의 여러 역할과 작업 선택은 함께 저장한다. 도구와 보고서 전체 생성 흐름은 출력 루트 바로 아래에 저장한다. 폴더 이름과 `batch.json`의 `id`는 같으며, 전체 경로로 묶음을 구분한다.

| 선택한 실행 단위 | 이름의 평가 대상 |
| --- | --- |
| 도구 | `도구평가` |
| 노드·작업 선택 | `노드평가` |
| 에이전트·보고서 생성 흐름 | `실행평가` |
| 도구와 보고서 생성 흐름을 함께 선택 | `통합평가` |

실행 번호는 같은 출력 폴더 안에서 평가 대상·한국 기준 시작일별로 증가한다. 채점 결과는 같은 실행 이름에 `_채점01`, `_채점02`를 붙여 구분한다. 같은 묶음의 도구·노드·실행 전체·최종 출력 품질 채점은 채점 번호를 함께 사용한다. 예를 들어 `assessments/노드평가_2026-11-12_실행01_채점02.json`는 해당 원본 실행에 대한 두 번째 채점 기록이다. 다시 채점해도 업무를 재실행하거나 실행 이름을 바꾸지 않는다. 이름의 날짜와 실제 채점 일시는 다를 수 있다.

번호는 기존 채점 JSON과 예약 번호를 확인하여 배정한다. 채점 시작 후 중단·저장 실패가 발생하면 번호가 비어 있을 수 있다. 채점 명령의 `--output`은 기존에 없는 새 JSON 파일 경로를 지정한다. 출력 위치를 지정해도 평가 ID와 채점 번호는 같은 규칙으로 배정한다. 개별 사례·반복의 실행 ID와 업무 State의 `execution.run_id`는 기존 UUID를 사용한다.

| 상대 경로 | 내용 |
| --- | --- |
| `suite.json` | 필터·대상별 분리 전 입력 묶음 전체 스냅샷 |
| `batch.json` | 해당 묶음의 선택 사례·반복 계획, 상태, 예정 실행 수, 사례·반복별 실행 ID·상태·상대 결과 경로. 묶음 중단 예외·취소 사유는 `failure`에 기록 |
| `runs/<실행 ID>/case.json` | 실행한 사례와 평가 준비 자료 |
| `runs/<실행 ID>/manifest.json` | 코드·설정·입력 파일·평가 실행기 해시 등 실행 조건 |
| `runs/<실행 ID>/trace.jsonl` | 호출 시작·갱신·종료 시점의 전체 호출 스냅샷 |
| `runs/<실행 ID>/report.json` | 실행 범위·시간·결과·오류, 존재하는 State·추적 원문, 모의 응답 사용 내역 |
| `assessments/<실행 이름>_채점NN.json` | 해당 실행의 전체 채점 결과. 재채점마다 새 번호로 저장 |

기록 시점·비밀값 가림은 [공통 로컬 추적](../../docs/runtime/monitoring.md#4-로컬-실행-증거)을 재사용한다. 평가 입력과 기대 결과는 업무 State를 확장하지 않고 실행 사례 파일에 보관한다.

`score`, `score-nodes`, `score-executions`, `score-outputs`는 각각의 논리 결과 전체를 채점 JSON 한 파일에 저장한다. 결과에는 사용한 평가 기준·원문·버전, 반복·노드·도구·실행별 판정과 지표, 해당하는 평가 모델의 원본 응답·사용량·추적이 포함된다. 노드 LLM 검사의 실제 메시지와 응답은 `assessments[].checks[].calls[].judge`에서 확인한다.

[채점 결과 읽기](../assessment_store.py)의 `load_assessment(path)`는 JSON 파일을 읽어 `tool-evaluation-v1`·`node-evaluation-v1`·`execution-evaluation-v1`·`output-evaluation-v1` 결과를 반환한다. 취소된 채점도 확보한 판정과 미완료 항목을 저장한다. 저장 성공은 평가 통과를 뜻하지 않는다.

[평가 결과 뷰어](../viewers/results/README.md)는 `score`의 도구 판정과 지표를, [노드 평가 뷰어](../viewers/nodes/README.md)는 `score-nodes`의 노드·역할별 결과를, [에이전트 실행 평가 뷰어](../viewers/execution/README.md)는 `score-executions`의 기능·운영 결과와 `score-outputs`의 최종 출력 품질을 구분해 표시한다. 저장된 판정과 원본 실행 기록은 변경하지 않는다.

자동 조회는 `Eumi/ai`를 루트로 제공하는 로컬 HTTP 서버에서 사용한다. 처음에는 `eval/outputs/evaluation-viewer/catalog.json`의 작은 목록만 읽는다. 목록은 `evaluation-viewer-local-v2` 형식이며 원본 경로·파일 크기·수정 시각, 묶음의 실행 단위·상태와 채점 파일 경로를 담는다. 목록 생성기는 묶음·채점 JSON을 읽어 식별자·상태·채점 시각·평가 종류만 추출하며 판정·모델 원문을 목록에 복사하지 않는다. 실행 결과·추적·시나리오는 경로와 파일 크기만 기록한다.

묶음을 선택하면 해당 실행 목록을 읽고, 채점을 선택하면 그 JSON의 판정·지표·근거를 읽는다. 실행 기록은 선택한 사례에 필요한 파일을 요청하며 아직 읽지 않은 자료를 누락·실패로 판정하지 않는다. JSON의 형식과 묶음·사례·반복의 식별 연결을 확인한다.

기본 `eval/outputs/evaluations`와 `eval/outputs/database-evaluations` 아래에서는 실행·채점 저장 완료 후 목록을 갱신한다. 원문 전체를 합친 `results.js`는 사용하지 않는다. 수동 복사 후 목록 갱신, 서버 실행과 수동 파일·폴더 열기는 [뷰어 사용 방법](../viewers/results/README.md#1-사용-방법)을 따른다. 목록 갱신 실패는 경고로 남기고 원본 실행·채점의 성공 여부를 바꾸지 않는다.

### 4.1 출력 형식의 공통 규칙

아래 표는 현재 저장하는 JSON의 필드·타입·필수 여부다. 필수 필드는 키가 항상 존재한다는 뜻이며, 값이 없을 때 `null`을 허용하는지는 타입에 별도로 표시한다. 선택 필드는 해당 조건이 없으면 키를 생략한다. 묶음 시작·종료와 채점 일시는 한국시간 오프셋 `+09:00`을 포함한 ISO 8601 문자열로 저장한다. 개별 실행·호출 추적의 UTC 시각과 기존 결과의 시각도 읽을 수 있으며, 세 평가 뷰어는 한국시간으로 변환해 표시한다. 소요 시간은 초 단위 숫자다.

평가 실행기의 출력 정의는 [실행 결과 자료형](../runner.py)의 `RunReport`·`BatchReport`와 [모의 호출 자료형](../fixtures.py)의 `FixtureSummary`를 따른다. `schema` 명령은 입력용 JSON Schema만 내보내며, 출력용 JSON Schema 파일을 생성하지 않는다.

| 실행 상태 | 의미 |
| --- | --- |
| `running` | 시작했지만 반환·오류·취소가 아직 확정되지 않음 |
| `returned` | 지정한 실행 범위가 반환됨. 업무 완료나 평가 통과를 뜻하지 않음 |
| `error` | 실행 예외 또는 예상 밖 모의 호출 발생. 묶음에서는 개별 실행 오류나 묶음 중단 오류를 나타냄 |
| `cancelled` | 실행 취소를 받아 종료 기록을 남김 |

`report.json`은 실행 종료 시 저장하므로 저장된 `run.status`는 `returned`, `error`, `cancelled` 중 하나다. 실행 중 상태는 `batch.json`과 누적 추적 파일에서 확인한다. 업무 코드가 실패 상태를 정상 반환하면 `run.status`는 `returned`, `state.execution.status`는 `failed`일 수 있다. 평가 판정은 이 두 상태와 별개다.

### 4.2 사례별 결과

`report.json`은 한 사례를 한 번 실행한 결과다. 반복 실행마다 별도 실행 ID와 파일을 갖는다.

| 필드 | 타입 | 필수 여부 | 내용 |
| --- | --- | --- | --- |
| `schema_version` | 문자열 | 필수 | `evaluation-run-v1` |
| `run` | 객체 | 필수 | 실행 대상·방식·시간·상태. 아래 실행 정보 표 참조 |
| `state` | 객체 | 선택 | `initial`로 State를 준비한 경우 저장. 기존 [State 계약](../../docs/agent/state.md)을 JSON으로 직렬화한 실행 상태 |
| `output` | 객체 또는 `null` | 필수 | 단위별 직접 반환값. 아래 반환 형식 표 참조 |
| `failure` | 객체 또는 `null` | 필수 | 실행기가 받은 예외·취소 또는 예상 밖 모의 호출 정보. 없으면 `null` |
| `trace` | 객체 | 필수 | 공통 로거의 추적 스냅샷. [추적과 실행 조건](#46-추적과-실행-조건) 참조 |
| `assessment` | 객체 | 필수 | 채점 수행 여부와 현재 판정 |
| `fixtures` | 객체 | 필수 | 준비된 하위 응답의 사용·불일치·잔여 내역 |
| `journal_saved` | 논리값 | 필수 | 종료 시 누적 추적 파일 기록이 활성 상태면 `true`. 파일 생성·추가 실패로 기록을 중단했으면 `false` |

State가 없는 도구 실행에는 표시용 State를 만들지 않는다. 노드·작업 선택의 `state`는 모델 결과를 반영하지 않은 초기 상태다. 에이전트가 취소되면 `state`에는 마지막으로 완료한 노드까지의 상태가 남는다. 진행 중 노드에서 소비한 예산·호출 이력은 `trace`의 `output.observed_state`에 관측용으로 보존하며, 완료한 노드의 반영 결과나 호출자 반환으로 취급하지 않는다. `journal_saved=false`여도 메모리에 수집한 추적은 `trace`에 저장한다.

`run`의 모든 필드는 필수다.

| 필드 | 타입 | 내용 |
| --- | --- | --- |
| `id` | 문자열 | 이번 실행의 UUID. State가 있으면 `execution.run_id`와 동일 |
| `suite_id` | 문자열 | 입력 묶음의 `id` |
| `case_id` | 문자열 | 입력 사례의 `id` |
| `repetition` | 정수 | 이 사례의 반복 순번. 1부터 시작 |
| `unit` | 문자열 | `tool`, `node`, `selection`, `agent`, `workflow` |
| `target` | 문자열 | 실행한 도구·노드·에이전트 이름. [실행 범위](#1-실행-범위)의 허용값 사용 |
| `role` | 문자열 또는 `null` | [실행 범위](#1-실행-범위)의 에이전트 역할. 도구·생성 흐름 단위이면 `null` |
| `dependencies` | 문자열 | `real` 또는 `stub`. 입력에서 생략했으면 `real` |
| `evaluation_scope` | 문자열 | 노드·작업 선택은 `model_output`, 나머지 실행 단위는 `execution` |
| `status` | 문자열 | [실행 상태](#41-출력-형식의-공통-규칙) |
| `started_at` | 문자열 | 단위 실행 시작 시각 |
| `ended_at` | 문자열 또는 `null` | 단위 실행 종료 시각. 초기값은 `null`이며 결과 저장 전에 설정 |
| `elapsed_seconds` | 숫자 또는 `null` | 단위 실행 소요 시간. 초기값은 `null`이며 결과 저장 전에 설정. 사전 자료 준비와 최종 파일 저장 시간은 제외 |

`output`은 실행 단위에 따라 다음 형식을 사용한다. 반환값을 받기 전에 예외나 취소가 발생하면 `null`일 수 있다.

| 단위 | 반환 형식 | 내용 |
| --- | --- | --- |
| 도구 | 객체 | 실제 도구의 반환값. `query_data`는 [QueryResult](../../src/tools/query.py), `process_data`는 [ProcessResult](../../src/tools/process.py), `validate_visualization`은 [VisualizationResult](../../src/tools/tableau.py), `render_visualization`은 [RenderResult](../../src/tools/render.py)를 따름 |
| 노드·작업 선택 | `{"model_call": 문자열, "raw": 문자열}` | 호출에 사용한 응답 스키마 이름과 모델 원문. 형식 오류가 있는 원문도 그대로 저장 |
| 에이전트·생성 흐름 | `null` | 업무 결과는 `state`에 저장 |

### 4.3 판정과 모의 호출

`report.json`의 `assessment`는 `run`이 남긴 채점 미실행 기록이며 모든 필드가 필수다. `score`의 [도구 판정](#6-도구-채점), `score-nodes`의 [노드 판정](../README.md#저장-결과와-기준-버전), `score-executions`의 [실행 판정](#8-실행-전체-채점), `score-outputs`의 [최종 출력 품질](#9-최종-출력-품질)은 별도 채점 결과에 저장하므로 이 값은 바꾸지 않는다.

| 필드 | 타입 | 현재 값과 의미 |
| --- | --- | --- |
| `verdict` | 문자열 | `미판정` |
| `executed` | 논리값 | `false`. 채점을 실행하지 않았음을 표시 |
| `reason` | 문자열 | 채점하지 않은 이유 |
| `checks` | 문자열 배열 | 입력 사례의 `assessment.checks`. 생략했으면 빈 배열 |

입력의 `reference`, `expected`, `tolerance`, `required`는 `case.json`에 보존하며 결과 판정 필드로 복사하지 않는다.

`fixtures`에는 아래 세 배열이 항상 있으며 해당 내역이 없으면 빈 배열이다. 배열 항목 내부 필드도 모두 필수다. `stub`은 `case.json`의 `stubs` 배열에서 0부터 시작하는 위치다.

| 필드 경로 | 타입 | 내용 |
| --- | --- | --- |
| `calls` | 객체 배열 | 준비된 응답과 일치하여 사용 횟수를 차감한 호출. 준비된 오류를 발생시킨 호출도 포함 |
| `calls[].name` | 문자열 | 호출한 도구 또는 하위 에이전트 이름 |
| `calls[].arguments` | 객체 | 일치 검사에 사용한 실제 인자 |
| `calls[].stub` | 정수 | 사용한 준비 응답의 위치 |
| `unexpected` | 객체 배열 | 일치하는 준비 응답이 없거나 사용 횟수를 소진한 호출 |
| `unexpected[].name` | 문자열 | 일치하지 않은 호출 이름 |
| `unexpected[].arguments` | 객체 | 일치하지 않은 실제 인자 |
| `unused` | 객체 배열 | 실행 종료 시 사용 가능 횟수가 남은 준비 응답 |
| `unused[].stub` | 정수 | 남은 준비 응답의 위치 |
| `unused[].remaining` | 정수 | 남은 사용 가능 횟수. 1 이상 |

### 4.4 묶음 결과

`batch.json`은 선택한 사례와 반복 실행의 진행·종료 정보를 보관한다. 실행 시작 전과 각 실행 전후, 묶음 종료 시 갱신한다.

| 필드 | 타입 | 필수 여부 | 내용 |
| --- | --- | --- | --- |
| `schema_version` | 문자열 | 필수 | `evaluation-batch-v1` |
| `id` | 문자열 | 필수 | 평가 대상·한국 기준 시작일·실행 번호로 구성한 이름. 출력 폴더 이름과 동일. 기존 UUID 기록도 읽기 지원 |
| `suite_id` | 문자열 | 필수 | 입력 묶음의 `id` |
| `status` | 문자열 | 필수 | [실행 상태](#41-출력-형식의-공통-규칙) |
| `started_at` | 문자열 | 필수 | 묶음 시작 시각 |
| `ended_at` | 문자열 또는 `null` | 필수 | 묶음 종료 시각. 실행 중에는 `null` |
| `planned_runs` | 정수 | 필수 | 필터로 선택한 사례 수 × 반복 횟수 |
| `plan` | 객체 | 필수 | 실행 전에 확정한 `case_ids` 문자열 배열과 `repeat` 양의 정수. 중단되어 시작하지 못한 사례·반복도 보존 |
| `runs` | 객체 배열 | 필수 | 실행을 시작하려고 등록한 항목. 아직 시작하지 않은 예정 실행은 포함하지 않음 |
| `failure` | 객체 | 선택 | 묶음을 중단시킨 예외·취소 정보. 개별 실행 오류만으로는 생성하지 않음 |

`runs`의 각 항목은 다음 필드를 모두 포함한다.

| 필드 | 타입 | 내용 |
| --- | --- | --- |
| `case_id` | 문자열 | 입력 사례의 `id` |
| `run_id` | 문자열 | 실행 UUID. 해당 `report.json`의 `run.id`와 동일 |
| `unit` | 문자열 | `tool`, `node`, `selection`, `agent`, `workflow` |
| `target` | 문자열 | 실행 대상 이름 |
| `repetition` | 정수 | 사례별 반복 순번. 1부터 시작 |
| `status` | 문자열 | [실행 상태](#41-출력-형식의-공통-규칙) |
| `path` | 문자열 | 묶음 폴더 기준 상대 경로. `runs/<실행 ID>/report.json` |

개별 실행이 오류로 끝나도 다음 실행을 계속하며, 하나라도 `error`이면 최종 묶음 상태도 `error`다. 따라서 `status=error`여도 묶음의 `failure`는 없을 수 있다. 실행 등록 직후·강제 종료·저장 실패 시에는 `path`가 가리키는 결과 파일이 아직 없거나 생성되지 않았을 수 있다.

### 4.5 오류 정보

`report.failure`와 `batch.failure`는 공통 로거의 [오류 변환](../../src/execution_trace.py)을 사용한다. 업무 State의 `execution.error`와는 별도 형식이다. 예상 밖 모의 호출을 보완 기록할 때는 `type`과 `code`만 저장할 수 있다.

| 필드 | 타입 | 필수 여부 | 내용 |
| --- | --- | --- | --- |
| `type` | 문자열 | 필수 | 예외 종류 또는 `UnexpectedStubCall` |
| `code` | 문자열 또는 `null` | 필수 | 예외의 코드. 없으면 `null`. 예상 밖 모의 호출은 `unexpected_stub_call` |
| `http_status` | 정수 또는 `null` | 선택 | 공통 오류 변환 시 포함. 예외에 HTTP 상태가 없으면 `null` |
| `validation_errors` | 객체 배열 | 선택 | 형식 검사 오류의 상세. 검증 라이브러리가 제공한 구조를 보존 |
| `details` | JSON 값 | 선택 | 예외가 제공한 구조화된 상세 정보 |
| `retryable` | 논리값 | 선택 | 예외가 제공한 재시도 가능 여부 |
| `cause` | 오류 객체 | 선택 | 원인이 된 예외. 같은 오류 형식을 재귀적으로 사용 |

외부 예외의 메시지 문자열은 저장하지 않는다. 준비한 도구 오류를 업무 코드가 처리하여 반환한 경우, 해당 오류는 State의 작업 이력과 추적에 남고 `report.failure`는 `null`일 수 있다.

### 4.6 추적과 실행 조건

`trace`는 공통 로거의 `local-execution-trace-v1` 형식이다. 아래 필드는 모두 필수이며, 개별 호출의 상세 구조는 [공통 추적 정의](../../src/execution_trace.py)의 `SpanRecord`를 따른다. 수집 범위와 비밀값 가림은 [로컬 실행 증거](../../docs/runtime/monitoring.md#4-로컬-실행-증거)에서 관리한다.

| 필드 | 타입 | 내용 |
| --- | --- | --- |
| `version` | 문자열 | `local-execution-trace-v1` |
| `scope` | 문자열 | 기록 범위 설명 |
| `limitations` | 문자열 배열 | 관측 한계 |
| `counts` | 객체 | 호출 종류별 개수. 키는 호출 종류, 값은 정수 |
| `coverage` | 객체 | 모델 기록과 미종료 호출의 수집 현황 |
| `spans` | 객체 배열 | 호출 순서대로 모은 개별 호출 스냅샷 |

`coverage`에는 정수 필드 `model_attempts`, `model_inputs`, `http_requests`, `http_responses`, `sdk_responses`, `model_errors`, `unfinished_spans`가 모두 포함된다. 각각 모델 호출 수, 메시지가 있는 호출 수, HTTP 요청·응답이 있는 호출 수, SDK 반환값이 있는 호출 수, 오류로 끝난 모델 호출 수, 종료 시각이 없는 전체 호출 수다. 자동 품질 점수가 아니다.

`trace.jsonl`은 한 줄에 `{"event": 문자열, "span": 객체}`를 저장한다. `span`은 해당 시점의 전체 호출 스냅샷이다. 같은 호출 ID의 여러 이벤트를 서로 다른 호출로 세지 않는다.

`runs/<실행 ID>/manifest.json`은 공통 `ExecutionManifest`에 `evaluation` 객체를 추가한 형식이다. 공통 필드 `version`, `captured_at`, `git`, `content_sha256`, `files_sha256`, `settings`는 [공통 실행 조건 정의](../../src/execution_trace.py)를 따른다. 평가용 `evaluation`은 아래에서 선택으로 표시한 출처 정보 외에는 모든 필드가 필수다.

| 필드 | 타입 | 내용 |
| --- | --- | --- |
| `suite_id` | 문자열 | 입력 묶음의 `id` |
| `suite_sha256` | 문자열 | 검증된 입력 묶음을 직렬화한 값의 SHA-256 해시 |
| `source` | 문자열 또는 `null` | 원본 입력 파일의 절대 경로. 파일 경로 없이 코드에서 실행하면 `null` |
| `source_sha256` | 문자열 또는 `null` | 원본 입력 파일 바이트의 SHA-256 해시. 파일 경로가 없으면 `null` |
| `runner_sha256` | 객체 | 평가 실행기 파일 이름별 SHA-256 해시. 키는 `evaluation` 디렉터리의 Python 파일 이름, 값은 문자열 |
| `data_source` | 문자열 | `prepared` 또는 `database` |
| `database_fixture_sha256` | 문자열 또는 `null` | DB 적재 원본의 해시. 준비 자료 방식은 `null` |
| `database` | 객체 또는 `null` | DB 방식의 `host`, `port`, `dbname`. 계정·비밀번호 제외. 준비 자료 방식은 `null` |
| `source_files_sha256` | 객체, 선택 | 시나리오 색인·선택 본문·참조 노드 파일·스냅샷의 상대 경로별 해시. `--prices` 파일은 절대 경로별 해시로 함께 기록 |
| `source_selection` | 배열, 선택 | 선택 시나리오 ID·본문 경로·단위·대상·시작 상태 위치·자료원. 업무 State로 전달하지 않는 출처 정보 |

## 5. 구현과 검증 범위

| 코드 | 책임 |
| --- | --- |
| [입력 정의](../schema.py) | 사례·자료·초기 입력 형식과 조합 검사 |
| [실행 명령](../__main__.py) | 스키마 출력·입력 검사·필터·반복·종료 코드 |
| [평가 실행](../runner.py) | 실행별 입력 준비, 단위별 호출, 묶음·실행 기록 저장 |
| [시나리오 입력 연결](../scenario_input.py) | 기존 시나리오 선택, 역할·전체 흐름의 시작점 구분, 참조 자료와 출처 해시를 읽어 기존 입력 구성 |
| [최종 출력 연결](../output_evidence.py)·[품질 채점](../output_scoring.py) | 실제 반환에 채택된 작성 원문을 식별하고 기존 노드 평가기로 품질 판정 |
| [노드 원문 수집](../nodes/runner.py) | 서비스의 입력 준비·원문 호출 경계를 재사용해 모델 응답 1회 수집. 업무 State 결과 반영 없음 |
| [DB 자료 준비](../database.py) | 허용된 서비스 테이블 원본 검사·트랜잭션 적재·실행 전 원본 일치 확인 |
| [하위 응답](../fixtures.py) | 준비한 응답 일치·사용 횟수·예상 밖 호출 처리 |
| [기대값 대조](../tools/assessment.py) | 도구 평가 입력·검사별 기대값 비교·증거 연결 |
| [도구 지표](../tools/metrics.py) | 예정 반복·필수 사례 집계, 정상·오류별 시간 통계와 성능 판정 |
| [도구 채점](../tools/scoring.py) | 저장한 도구 실행의 채점과 재채점 |
| [공통 증거·저장 준비](../batch_store.py) | 저장 묶음·계획·실행 증거 검사, 채점기의 결과 경로 준비와 저장 연결 |
| [채점 결과 저장·읽기](../assessment_store.py) | 기준·판정·지표·원문을 포함한 전체 채점 JSON 저장·읽기 |
| [평가 코드·기준 지문](../provenance.py) | 실행·채점 코드 해시 수집, 과거 기록의 평가 문서 경로를 현재 기준과 대조 |
| [노드 기준 읽기](../nodes/criteria.py) | 현행 노드 평가 JSON의 검사 정의·관련 원칙·원문·출처·해시 수집 |
| [노드 평가 범위 선택](../nodes/selection.py) | 사례 선언·선택 옵션·실제 호출 조건을 대조하고 반복별 선택·제외·미판정 계획 작성 |
| [노드 증거 추출](../nodes/evidence.py) | 부모 호출을 따라 노드·역할·직접 모델 호출을 연결하고 원문·오류·누락 보존 |
| [노드 규칙 평가](../nodes/rules.py) | 출력 형식, 독립 기대값, 실제 입력의 사용 범위·참조 대조 |
| [노드 LLM 평가](../nodes/llm.py) | 전체 모델 호출 입력·선택한 출력·검사 기준을 전송, 판정 항목 번호·증거 표식을 원래 ID·경로로 복원하고 판정 근거 검사 |
| [노드 단계별 판정](../nodes/assessment.py) | 요청한 모델 호출별 형식·필수 내용·정확성 순서 제어와 검사·세부 판정 종합 |
| [노드 지표](../nodes/metrics.py) | 반복별 선택 계획의 기능·운영 지표를 노드·역할별로 집계하고 제외 반복·미완료·원래 운영 목표 구분 |
| [노드 채점 저장](../nodes/scoring.py) | 계획별 증거 읽기, 기준 버전 대조, 노드 판정·평가 모델 추적의 저장 연결 |
| [실행 평가 입력](../execution/schema.py) | 기대 경로·반환 조건·운영 목표·단가 형식 검사 |
| [실행 증거 읽기](../execution/evidence.py) | 저장 결과 읽기, 결과 파일이 없는 실행의 누적 기록 복구와 손상·미종료 구분 |
| [실행 규칙 검사](../execution/rules.py) | 공통·보고서 검사별 경계 대조와 세부 판정·증거 연결 |
| [실행 지표](../execution/metrics.py) | 예정 반복의 기능 완료 여부, 진입 이후 운영 사용량·보고서 완성률·목표 판정 |
| [실행 채점 저장](../execution/scoring.py) | 사례·검사 선택, 기준 원문·버전 대조, 실행 판정의 저장 연결 |

실제 모델·운영 자료·데이터베이스·백엔드·Tableau 화면의 연동 성공은 입력 검사나 모의 실행만으로 확인할 수 없다. 검증된 범위와 남은 연결은 실행 증거와 함께 구분한다.

[실행기 테스트](../tests/test_evaluation_runner.py)는 입력 검사, 실제 도구 처리, 노드 원문 수집과 State 격리, 반복 격리, 모의 호출, 오류·취소 보존, 질문 대기, 보고서 세 역할의 개별 실행과 순차 흐름을 검증한다. [단위 실행 연결 테스트](../../tests/test_unit_execution.py)는 서비스의 공통 노드 경계와 하위 호출 교체를 검증한다. 모델 응답은 테스트에서 준비하며 외부 모델 API의 실제 응답 품질은 검증하지 않는다. 역할별 판단·산출물·검토 정확성은 [노드 평가](nodes/README.md), 한 동·월의 순차 실행·보고서 구성은 [동별 보고서 실행 평가](execution/dashboard-report.md), 에이전트 진입부터 반환까지의 내부 실행과 성능·안정성은 [에이전트 실행 평가](execution/README.md)에서 확인한다.

[모델 호출 경계 테스트](../../tests/test_model_boundary.py)는 서비스와 평가가 같은 입력·응답 스키마를 준비하는지, 보고서 호출 준비가 원본 State를 바꾸지 않는지, 형식이 잘못된 원문도 수집하는지와 서비스의 응답 검증이 유지되는지를 확인한다.

[시나리오 입력 테스트](../tests/test_scenario_input.py)는 21개 역할 입력과 3개 보고서 전체 입력의 상태·자료원 보존, 선택 오류, 원본 해시와 평가 자료 분리를 확인한다. [명령 연결 테스트](../tests/test_scenario_cli.py)는 별도 입력 파일 없이 선택·단가·출처를 전달하는지 확인하며, [실제 그래프 테스트](../tests/test_scenario_execution.py)는 모델 응답만 대체해 기존 대화·승인 결과·누적 예산 보존, 실제 조회·시각화 검사, 세 보고서 역할의 순차 실행을 검증한다.

```powershell
uv run python -m pytest eval/tests/test_evaluation_runner.py tests/test_unit_execution.py -q
uv run python -m pytest tests/test_model_boundary.py -q
uv run python -m pytest eval/tests/test_tool_assessment.py eval/tests/test_evaluation_metrics.py eval/tests/test_evaluation_scoring.py -q
```

채점 테스트는 합성 기준·증거로 값의 일치·불일치, 기준·증거 누락, 기대한 거부, 반복 집계·시간 통계, 결과 파일 보존과 실행 후 채점 명령의 연결을 검증한다. 정식 시나리오에 대한 실제 도구 품질 평가 결과는 아니다.

뷰어의 모의 모델·소규모 임시 결과를 사용하는 통합 검증은 원본 보존과 판정·지표 연결을 확인한다. 실제 누적 결과 전체의 로딩·표시·응답성까지 확인한 결과는 아니다. 경량 목록의 생성 검사는 원문 미열람과 메타데이터 제한을 확인하며, 실제 누적 자료의 HTTP 요청 범위·크기·선택 전환과 오류는 별도로 검증한다.

노드 채점은 [구현 검증 범위](../README.md#구현-검증-범위)의 테스트로 정형 평가 정의 읽기, 원본 응답의 형식·내용 비교, 적용 행 선택과 전체 모델 호출 입력 전달, 단계별 중단, 중첩 호출의 증거 분리, 지표·미완료 집계와 저장을 확인한다. 준비한 모델 응답을 사용한 구현 검증이며, 실제 모델의 판단 품질·사람과의 일치·대표 환경의 운영 성능은 별도 평가한다.

LLM 프롬프트는 모든 검사 행에서 저장된 `messages` 배열과 `response_schema` 전체를 원래 값으로 복원할 수 있는 JSON으로 제공한다. 메시지의 순서·역할·본문·부가 필드, 도구 명세·중복·실패·검토 이력을 보존하며 입력 일부를 추출하거나 압축하지 않는다. 출력 필드와 판정 기준 조항은 현재 검사에 맞게 선택한다. 실제 전송 문자열과 기준 원문·출처·해시·원본 자료를 구분해 보존하고, 짧은 항목·증거 표식의 원문 연결도 남긴다.

원문에 포함된 업무 지침은 입력·출력을 대조하는 근거이며 평가 모델 자신의 지시로 실행하지 않는다. 승인된 설명처럼 근거로 쓸 수 있는 범위와 자료 간 연결은 평가 모델이 전체 원문을 보고 기존 기준으로 판단한다. 메시지 목록 부재·메시지 형식 손상·보관된 응답 스키마의 형식 손상은 호출을 보류한다. 과거 기록에 응답 스키마가 없으면 현재 코드로 보충하지 않으며 미보관 자체로 호출을 차단하지 않는다. 승인 연결의 의미를 코드가 미리 판정해 자료를 걸러내지 않는다. 전송 내용과 원문 연결은 [평가 프롬프트와 원문 추적](../README.md#평가-프롬프트와-원문-추적), 아직 실행하지 않은 실제 판정 품질 비교는 [비교 절차](../README.md#프롬프트-변경의-품질-비교)를 따른다.

[DB 준비 테스트](../tests/test_evaluation_database.py)는 대상 DB 제한, 입력 검사, 매개변수 적재·롤백, 동일 자료 재사용과 불일치 거부를 검증한다. [DB 자료원 연결 테스트](../tests/test_evaluation_database_sources.py)는 실제 서비스 공급자 재사용, 준비 자료 방식과의 분리, 조회 증거·원본·해시 보존과 DB 재접속 없는 채점을 검증한다. State와 도구 인자는 기존 계약을 유지하며, 평가 원본은 `suite.json`, 실제 조회 결과는 기존 도구 반환과 추적에 보존한다.

2026-11-11 로컬 PostgreSQL 17의 별도 `eumi_eval` DB에 공통 Flyway 마이그레이션 9개를 적용하고 [서비스 조회 사례](../scenarios/database/service-query.json)의 원본을 `eumi_pipeline`으로 적재했다. 실제 서비스와 같은 `eumi_ai` 계정으로 `run --repeat 3`을 실행해 8개 사례의 24회 실행이 모두 반환됐으며, 별도 `score` 명령이 필수 8개 사례를 통과로 판정했다. 동일 원본의 재적재는 `unchanged`로 종료됐다. 실행 묶음은 `eval/outputs/database-evaluations/도구평가_2026-11-11_실행02`, 채점 파일은 그 안의 `assessments/도구평가_2026-11-11_실행02_채점01.json`이다. 실제 장애 재현·운영 성능은 이 검증에 포함하지 않았다.

## 6. 도구 채점

`score`는 업무 코드·모델을 호출하지 않고 저장된 `suite.json`, `batch.json`, 사례별 `report.json`을 읽는다. `query_data`, `process_data`, `validate_visualization`의 지정된 검사만 채점한다. 제공 사례의 독립 기대값·구성·실행 방법·검증 결과는 [도구 평가 시나리오](../scenarios/tools/README.md)를 따른다. 성능 목표는 지정하지 않았다.

### 기대값 형식

`assessment.checks`에 적용할 `T-I.1`, `T-O.1`, `T-O.2`, `T-O.5`를 나열한다. `reference`에는 독립 기준 자료나 그 참조를 넣고, `expected`는 `schema_version="tool-expectations-v1"`과 `items` 배열을 갖는다. 기준의 독립성과 검사 대상의 충분성은 사례 작성자가 확인한다. 실행 결과에서 기대값을 자동 생성하지 않는다.

| `items` 항목 | 필수 여부 | 의미 |
| --- | --- | --- |
| `check` | 필수 | 해당 항목의 검사 ID. `assessment.checks`에 포함되어야 함 |
| `path` | 필수 | 실제 결과를 찾을 JSON Pointer. 예: `/output/data/rows`, `/failure/code`, `/run/status` |
| `value` | 선택 | 독립 기대값. 생략은 미판정이며 명시한 `null`과 구분 |
| `match` | 선택 | `equal` 기본값, `subset`, `present`, `absent` |
| `tolerance` | 선택 | 이 항목의 수치 허용 오차. 전역 `assessment.tolerance`보다 우선 |
| `applicable` | 선택 | `false`면 해당 대상은 비적용. 생략하면 적용 |
| `reason` | 조건부 | 비적용일 때 필수인 사유 |

`equal`은 객체 키·배열 길이와 순서까지 비교한다. `subset`은 객체의 추가 키만 허용하며 배열의 길이·순서는 유지한다. `present`와 `absent`는 키의 존재를 검사하고 `value`·항목별 `tolerance`를 받지 않는다. 키가 있고 값이 `null`이면 존재하는 것이다. 논리값·문자열·숫자는 서로 다르게 취급하며, 정수와 실수는 수치로 비교한다.

허용 오차는 `{absolute: 숫자, relative: 숫자}`이며 각 값은 생략 가능하고 기본 0이다. 차이가 절대 오차와 `relative × max(|실제값|, |기대값|)` 중 큰 값 이하면 일치한다. 음수·비유한 오차는 거부한다. 경로의 `/`와 `~`가 이름의 일부이면 각각 `~1`, `~0`으로 표기한다. 검사 ID와 경로가 같은 중복 항목, 알 수 없는 기대값 버전은 입력 오류다.

비교 경로의 첫 항목은 `output`, `failure`, `run`, `trace`, `observations` 중 하나다. 앞의 네 항목은 실제 실행 기록이다. `/observations/provider_calls`는 완료한 해당 도구의 추적에서 직접 하위 자료원 호출 수를 센 값이다. 추적 자체를 비교하거나 이 파생 값을 사용할 때 완료한 도구 추적이 없거나 손상되었으면 미판정이다. 원본 파일에 들어 있는 `observations`는 사용하지 않는다. 정답·평가 자료를 실제값으로 참조할 수 없다.

### 판정과 집계

| 상황 | 판정 |
| --- | --- |
| 독립 기준과 실제 값이 일치 | 통과 |
| 실제 값 불일치 또는 정상 반환의 필수 비교 대상 누락 | 실패 |
| 독립 기준·기대값·적용 검사·실행 증거 부족 | 미판정 |
| 사전에 비적용으로 지정하고 사유를 제공 | 비적용 |

기대 오류 코드는 `/failure/code`, 시각화 부적합은 `/output/valid`처럼 실제 반환 위치와 비교한다. 실행 상태 `error`만으로 평가 실패를 부여하지 않는다. 오류로 출력 자체를 확보하지 못했다면 그 내부 값은 미판정이다. 기록된 `/output`의 `null` 자체는 기대한 거부의 증거로 비교할 수 있다.

검사별 수행 여부·판정·실제값·기대값·비교 방식·허용 오차·사유·증거 위치를 남긴다. 확인된 실패가 있으면 종합 실패를 유지하되 미실행·미판정과 완료 여부도 따로 기록한다. 비적용 항목만 있거나 검사 목록이 비어 있으면 사례를 통과시키지 않는다. 종료되지 않은 실행 결과도 미판정이다.

사례별 예정 반복이 모두 적용 검사를 통과해야 그 사례를 통과로 센다. `required=true`인 사례는 ID별 한 번 분모에 포함하고, 미실행·미판정도 제외하지 않는다. `required=false`는 제외하며 필수 여부를 생략한 사례가 있으면 종합 통과를 보류한다. 분모 0은 비율 `null`, 판정 미판정이다. 완료 사례와 미완료 사례의 합은 전체 필수 사례 수와 같아야 한다.

### 호출 시간과 성능 목표

`performance` 배열의 각 항목은 아래 형식이다. 같은 도구·호출 종료 종류는 한 번만 지정하며 사례 ID는 중복할 수 없다.

| 항목 | 필수 여부 | 의미 |
| --- | --- | --- |
| `target` | 필수 | 채점 대상 도구 이름 |
| `group` | 필수 | `normal` 또는 `error`. 도구 추적의 정상 반환·예외 종료를 뜻하며 기능 판정과 별개 |
| `case_ids` | 필수 | 해당 도구의 대표 시험 사례 ID 배열 |
| `statistic` | 선택 | 판정할 `median` 또는 `p95` |
| `max_seconds` | 선택 | 최대 허용 시간. 0 이상의 유한 숫자 |
| `environment` | 선택 | 실행 환경 설명 |
| `data_size` | 선택 | 대표 자료 크기 설명 |

선택 항목이 미확정이면 측정값은 남기고 성능 판정은 미판정으로 둔다. 반복 횟수는 `batch.plan.repeat`를 사용한다. 대상 사례가 계획에서 빠졌거나 예정 반복의 해당 종료 종류 측정이 누락되어도 통과시키지 않는다.

시간 통계는 도구 호출 추적의 `elapsed_seconds`로 계산한다. 전체 실행 시간이나 하위 호출 시간을 더하지 않으며, 정상·오류별 중앙값과 정렬한 표본의 `ceil(0.95 × 표본 수)`번째 값인 p95를 저장한다. 중복 호출 ID는 한 번만 반영하고 상충 기록은 미판정 사유로 남긴다. 미종료 호출은 통계에서 제외하고 관측된 경과 시간을 따로 남긴다. 실행 한도 초과가 기록되면 성능 실패로 판정하지만 이 명령이 호출을 강제로 중단하지는 않는다.

### 실행과 저장

```powershell
uv run python -m eval score eval/outputs/evaluations/<묶음-ID>
uv run python -m eval score eval/outputs/evaluations/<묶음-ID> --output eval/outputs/tool-assessment
```

기본 출력은 묶음 폴더의 `assessments/<채점 ID>.json`이며 이름·파일·읽기 방법은 [공통 저장 계약](#4-저장-결과)을 따른다. `--output`에는 기존에 없는 새 JSON 파일 경로를 지정한다. 종료 코드 0은 채점 결과 저장 성공이며 평가 통과를 뜻하지 않는다. 입력·계획 오류는 2, 읽기·저장 오류는 1이다.

읽은 결과는 `tool-evaluation-v1` 형식이며 원본 실행 ID를 참조하는 `runs`의 검사별 판정과 `tools`의 기능 집계·시간 통계·성능 판정을 갖는다. `criteria`에는 현재 선택 사례·독립 기준·허용 오차·성능 조건·실행 계획과 자료 제공 방식을 보존하며, DB 방식은 적재 원본도 포함한다. 평가 ID·시각, 기준·실행 증거·평가 코드의 해시를 함께 저장해 재평가를 구분한다. 현재 `suite.json`을 기준으로 재판정하며 실행 전에 준비한 기준과 동일한지는 확인하지 않는다. 세부 출력 자료형은 [검사 결과](../tools/assessment.py), [도구 집계](../tools/metrics.py), [도구 채점 결과](../tools/scoring.py)를 따른다.

실행 등록이 없는 예정 반복과 등록은 있으나 결과 파일이 없는 반복을 구분하여 미판정 사유를 기록한다. 계획이 없는 과거 묶음은 반복 수나 평가 대상을 추측하지 않고 거부한다. 식별자 불일치·중복 실행·폴더 밖 경로·링크 경로도 거부한다. 원본 `report.json`의 채점 미실행 기록과 별도 채점 결과의 판정은 서로 다른 기록이다.

## 7. 현재 제약과 후속 작업

### 평가 범위와 한계

조회 평가는 자료 제공 방식에 따라 확인 범위가 다르다. `prepared`는 JSON 자료를 복사하거나 지정한 예외를 발생시키는 시험용 공급 함수를 사용한다. `database`는 서비스와 같은 구조의 별도 평가 DB를 실제 서비스 코드로 읽고, 조인·집계·자료 변환을 거쳐 조회 도구에 전달한다. 두 방식 모두 [조회 도구](../../src/tools/query.py)가 공급받은 전체 자료를 메모리에서 필터링·정렬하고 반환 열과 페이지를 선택한다. 요청 조건을 SQL로 내려보내는 기능은 없다.

| 항목 | 준비 자료 방식 | DB 방식 |
| --- | --- | --- |
| 조회 결과 | 주어진 자료에 조건·정렬·페이지·반환 열 적용 | 서비스 SQL의 읽기·조인·집계·자료 변환과 이후 도구 처리 |
| 입력과 상태 | 잘못된 입력의 거부, 정상 0건과 실행 오류 구분 | 같은 검사와 설정한 계정의 실제 접속·읽기 성공 |
| 자료원 장애 | 주입한 예외의 오류 코드·원인·재시도 표시 | 모의 장애 설정을 금지. 실제 장애 재현은 별도 준비 필요 |
| 출처와 버전 | 제공한 메타데이터 보존 | DB 조회 행으로 계산한 버전·수정 시각과 서비스 출처 보존 |
| 응답시간 | 로컬 공급·메모리 처리 시간 | 현재 평가 서버의 DB 읽기와 이후 도구 처리 시간. 사전 적재·원본 대조 시간은 제외 |

DB 자료도 평가용 합성자료이므로 운영 자료의 정확성·최신성은 검증하지 않는다. 정상 조회 성공만으로 권한 거부·연결 단절·시간 초과 처리가 검증되지는 않는다. 현재 서비스 DB 코드는 psycopg 예외를 그대로 전달하고 조회 도구는 Python 기본 권한·시간 초과·연결 예외를 변환하므로, 두 경계의 오류 대응도 실제 장애 시험에서 확인해야 한다. 운영 성능은 대표 자료 규모·동시 부하·목표값을 정한 별도 시험이 필요하다.

현재 제공 사례에서 가공 평가는 합성자료에 대한 지정 연산·계산·거부 처리를, 시각화 평가는 등록 설정에 따른 입력 검사와 산출물 구성을 확인한다. 이 결과만으로 실제 입력 자료의 품질이나 게시된 Tableau 화면의 표시·서비스 연동을 검증했다고 보고하지 않는다.

규칙 채점기는 사례에 작성한 기대값·비교 항목·허용 오차와 저장된 실행 증거를 대조한다. 노드 LLM 검사는 실제 입력·출력을 현행 검사 기준으로 판정한다. 통과는 해당 검사 기준의 충족을 뜻하며, 자료 자체의 사실성이나 사례가 모든 조건을 포함하는지를 보증하지 않는다. `run`만 완료한 기록은 실행 증거이며 기능·품질 판정은 별도 채점 결과로 확인한다.

노드 채점은 지정한 검사 범위에서 호출별로 형식 준수 → 필수 내용 충족 → 내용 정확성의 순서를 지킨다. 기본 `rules` 방식은 선택한 LLM 검사에서 미판정으로 보류하며, `all`은 별도 평가 모델로 그 단계를 수행한다. 실제 전송 입력·원문이나 필요한 검사 기준을 확인할 수 없으면 해당 판정을 보류한다. 규칙 검사에는 독립 비교 자료와 구현에 대응하는 정형 평가 정의 버전도 필요하다. 업무 State 반영 성공은 모델 품질의 통과 조건이 아니며 실행 오류와 품질 판정은 분리한다. 적용 조건과 미완료·운영 목표의 분리는 [노드 단계와 판정](../README.md#단계와-판정)을 따른다.

기존 사례는 내부 처리의 정확성을 확인하고 코드 변경으로 기존 동작이 깨지는지 검사하는 데 유지한다. 조회 결과의 보고 범위는 [조회 평가 기준](tools.md#11-데이터-검색-및-조회)을 따른다.

DB 방식은 **조회 요청 → 실제 DB 읽기 → 처리 → 반환**의 연결을 확인한다. 기존 `process_data` 사례는 인자에 담긴 자료를 직접 처리하므로 DB 자료원 선택만으로 DB 연동 사례가 되지 않는다. HTTP 접수부터 결과 저장·알림까지의 서비스 전체 연동은 별도로 확인한다.

### 실행 제약

| 항목 | 현재 동작과 남은 작업 |
| --- | --- |
| 평가 기준과 시나리오 | 세 도구의 [합성자료 사례](../scenarios/tools/README.md)·[서비스 DB 조회 사례](../scenarios/database/README.md), [노드 시나리오 데이터셋](../scenarios/nodes/README.md), [실행 연결 사례](../scenarios/execution/README.md) 제공. 21개 시나리오의 역할 실행과 선정 시나리오의 보고서 전체 실행 지원. 사용자 요청·동별 보고서 실행은 §8의 공통·보고서 규칙 검사 지원. HTML 렌더러 채점은 미구현 |
| 자료원 장애 시험 | 준비 자료 방식의 `provider_failures`로 예외 변환을 평가. DB 방식의 실제 장애 재현과 호출 중단은 포함하지 않음 |
| 하위 결과 격리 | 준비된 응답의 정확성은 사례 작성자가 확인. 실제 도구 품질은 도구 단위 실행으로 별도 확인 |
| 실행과 재개 | 순차 실행. 기존 이력·응답·누적 예산을 사례 초기 입력으로 제공하는 별도 재진입 실행과 채점 지원. 질문 대기에서 종료하며 답변 주입·체크포인트 재개·실행 간 자동 State 전달·중단 묶음 이어 실행은 제공하지 않음 |
| 동기 도구 취소 | 도구를 직접 동기 호출. 도구 실행 중 즉시 취소하거나 별도 프로세스에서 강제 종료하는 기능은 없음 |
| 저장 용량 | 전체 입력·중간 결과를 저장하므로 자료 크기와 반복 수에 따라 증가. 자동 보관 기간·정리 기능은 없음 |
| 서비스 연동 | 별도 평가 DB의 서비스 조회 경로 제공. 운영 자료·HTTP 접수·업무 결과 저장·완료 알림은 별도 연동 실행에서 확인 |
| 결과 화면 | 도구·노드·에이전트 실행별 전용 뷰어에서 원본 실행 증거와 해당 채점의 판정·근거·기능·운영 지표·재평가 확인 |

## 8. 실행 전체 채점

`score-executions`는 여섯 역할의 에이전트 실행과 한 동·월의 보고서 작성 실행의 운영 지표를 집계한다. 기능 판정은 사용자 요청 전체(`agent/request`)의 [EX-1~5](execution/common.md#공통-실행-검사), 보고서 전체(`workflow/report`)의 공통 검사와 [EX-R1~5](execution/dashboard-report.md#보고서-검사)에 적용한다. 다른 역할의 단독 실행은 운영 측정만 제공하며 기능 통과·실패로 판정하지 않는다. 업무·평가 모델을 호출하지 않으며 답변 내용 품질은 이 명령의 평가 대상이 아니다.

### 명령과 선택 범위

```powershell
uv run python -m eval score-executions <실행묶음경로>
uv run python -m eval score-executions <실행묶음경로> --case <사례-ID> --check EX-3 --check EX-5
uv run python -m eval score-executions <실행묶음경로> --output eval/outputs/execution-assessment
```

`--case`와 `--check`는 여러 번 지정할 수 있으며 저장된 실행 계획·사례의 검사 선언 안에서 범위를 좁힌다. 보고서 전용 검사는 `workflow/report`에서만 선언한다. 지원 사례 중 선택 검사와 겹치지 않는 사례는 이유와 함께 제외하며, 예정 반복 수는 원래 `batch.plan.repeat`를 유지한다. 기능 판정 범위 밖인 역할은 `selection.functional_excluded`에 사유를 남기고 운영 측정을 유지한다. 선택한 사례에 선언되지 않은 `--check`는 입력 오류이며, 운영 측정만 지원하는 역할을 단독 선택할 때는 `--check`를 생략한다. 일부 검사만 선택한 통과는 선택 범위의 결과다. 전체 업무의 검증 완료로 확대하지 않는다.

기본 출력은 `assessments/<채점 ID>.json`이며 이름·파일·읽기 방법은 [공통 저장 계약](#4-저장-결과)을 따른다. `--output`에는 기존에 없는 새 JSON 파일 경로를 지정한다. 실행 묶음의 `runs/` 아래 경로는 원본 파일이 아직 없어도 거부한다. 종료 코드 0은 저장 성공, 2는 입력·계획 오류, 1은 읽기·저장 오류다. JSON의 기능·운영 판정은 종료 코드와 별도로 확인한다.

### 기대 조건

사례의 `assessment.checks`에 적용 검사 ID를 중복 없이 넣고, `assessment.required`로 필수 여부를 지정한다. `assessment.expected`는 다음 형식을 사용한다. 이 평가 자료는 업무 State·모델 입력에 전달하지 않는다.

| 항목 | 필수 여부 | 값과 의미 |
| --- | --- | --- |
| `schema_version` | 필수 | `execution-expectations-v1` |
| `situation` | 필수 | 정상 `normal`, 자료 부족 `data_shortage`, 오류·재시도 `fault`, 한도·취소 `limit_cancel` |
| `entry` | 필수 | 최초 진입 `initial`, 기존 상태로 별도 재진입 `reentry` |
| `environment` | 선택 | 이번 시험의 모델·자료 연결·실행 환경 설명 |
| `data_size` | 선택 | 요청·대상 동·자료 규모 설명 |
| `node_path` | 선택 | 기대하는 상위 업무 노드 순서. `interpret`, `decide`, `act`, `compose`, `ask` 배열. 하위 에이전트 내부 노드와 질문 대기 `wait`는 제외 |
| `role_path` | 선택 | 보고서의 `report_selection`, `report_description`, `report_insight` 실행 순서 |
| `run_status` | 선택 | 실행 호출의 `running`, `returned`, `error`, `cancelled` |
| `execution_status` | 선택 | 반환 State의 `queued`, `running`, `waiting_input`, `completed`, `partial`, `failed`, `cancelled` |
| `response_kind` | 선택 | 응답의 `progress`, `intermediate`, `final`, `question` 또는 `null` |
| `error_code` | 선택 | 반환 State의 오류 코드 또는 오류 없음 `null` |
| `report_completeness` | 선택 | 보고서 완성 `complete`, 부분 `partial`, 생성 결과 없음 `none` |

선택 조건을 생략하면 그 값을 정답으로 추정하지 않는다. 각 EX 검사의 명세에 따른 경계 비교는 계속 수행한다. `role_path`와 `report_completeness`는 보고서에서만 사용한다. 재진입 사례는 기존 승인·초안·검토·오류 이력, 응답과 누적 예산을 `initial`로 직접 준비한다. 실행 간 결과 자동 전달이나 중단 묶음 이어 실행은 하지 않는다.

실행 1회당 검사 ID별 판정 1건과 전달 경계·참조·항목별 세부 결과를 남긴다. 확인된 위반은 실패, 증거 부족은 미판정, 실제 적용 조건에 해당하지 않으면 비적용이다. 실패와 미판정이 함께 있으면 실패를 유지하고 검증 미완료를 별도 표시한다. 필수 사례는 선택한 모든 예정 반복의 적용 검사가 통과해야 통과이며, 검사·필수 사례 통과율은 통과·실패가 판정된 대상만 분모에 넣는다. 미실행·미판정·필수 여부 미지정과 반복 누락은 따로 집계한다. 분모 0은 비율 `null`이다.

### 운영 측정과 목표

실행 시간은 `kind=execution` 추적의 진입부터 반환·오류·취소까지 측정한다. 사용자 요청의 그래프 구성, 실행 전 자료 준비와 결과 파일 저장은 제외한다. 보고서 작성에 진입한 뒤의 역할 그래프 구성·노드·도구·하위 실행 시간은 포함하며 하위 시간을 다시 더하지 않는다. 이 경계가 없는 이전 기록의 `evaluation` 시간은 준비를 포함한 진단값으로 남기고 실행 시간 목표의 합격에 쓰지 않는다.

호출량은 이번 실행의 실제 추적을 중복 없이 센다. 보고서 역할 전환은 하위 에이전트 호출 수에 넣지 않는다. `node_entries`는 질문 대기 `wait`도 포함한 노드 진입 수이고, `budget_delta.steps`는 업무 단계 예산의 증가분이므로 두 값은 다를 수 있다. 재진입 전 누적 사용량은 제외하며 재시도는 명시적으로 기록된 이번 예산 증가분만 사용한다. 같은 작업·인자가 다시 보인다는 이유로 새 재시도를 추정하지 않는다.

`execution_performance` 배열에 지정한 항목을 필수 운영 목표로 판정한다. 각 항목에는 `target`(`request` 또는 `report`), 중복 없는 `case_ids`, 아래 `metric`을 넣는다. 합격하려면 시험 전에 `environment`, `data_size`와 지표별 목표를 확정하고 예정 반복의 측정을 완료해야 한다. 목표가 없거나 필요한 조건·사용량·종료 증거가 없으면 측정 가능한 값은 남기고 해당 운영 판정은 미판정이다. 호출 개수·수집 현황·상위 호출 연결·상태 기록이 상충해 증거가 불완전한 실행도 운영 목표 판정을 보류한다. `dependencies=stub`인 실행은 실제 연결 환경의 운영 합격에 쓰지 않는다.

| `metric` | 판정에 필요한 조건 | 비교할 값 |
| --- | --- | --- |
| `latency` | `statistic`: `median`, `p95`, `mean` 중 하나, `max_seconds` | 지정한 실행 시간 통계 ≤ 초 단위 상한 |
| `failure_rate` | `max_rate`: 0~1 | 기술적 실패가 확인된 실행 수 ÷ 종료한 실행 수 ≤ 상한. 평가 과정 실패는 분모에서 제외하며, 종료 결과 미분류가 있으면 분모에 남기고 비율·판정 보류 |
| `cost` | `statistic`: `median`, `p95`, `mean` 중 하나, `max_cost` | 지정한 실행 비용 통계 ≤ 해당 통화 상한 |
| `repeat_spread` | `measure`, `max_spread`, 같은 사례의 2회 이상 전체 반복 | 사례별 최댓값−최솟값 중 최대 차이 ≤ 상한 |

`failure_rate`를 제외한 목표에는 종료 종류 `group`을 선택할 수 있다. `normal`은 완료·부분·질문·거부·자료 없음, `technical_failure`는 기술적 실패, `cancelled`는 취소이며 생략하면 해당 목표의 종료 표본 전체를 사용한다. 반복 편차의 `measure`는 `elapsed_seconds`, `model_calls`, `tool_calls`, `agent_calls`, `node_entries`, `retries`, `input_tokens`, `output_tokens`, `cost` 중 하나다. 숫자 상한은 0 이상의 유한 값이며 지표에 맞지 않는 목표 필드는 입력 오류다. p95는 정렬한 표본의 `ceil(0.95 × 표본 수)`번째 값이다.

비용을 계산하려면 묶음의 `execution_prices`에 단가 `version`, `currency`, `models`, `tools`를 준비한다. `models`는 실제 SDK 응답의 모델 이름을 키로, 백만 입력·출력 토큰당 `input_per_million`, `output_per_million`을 지정한다. `tools`는 호출 이름을 키로 호출당 `per_call`을 지정한다. 비용이 없는 호출도 0을 명시하며 누락된 단가를 무료로 처리하지 않는다. 실제 사용량·모델 이름·단가가 부족하면 해당 비용과 합계는 산출하지 않는다. 가격을 외부에서 자동 조회하지 않는다.

보고서 완성률은 시작한 동별 작성 실행 중 검토 통과한 3개 뷰·모든 설명·인사이트를 실제 반환하고 EX-R4·5와 EX-5를 통과한 실행의 비율이다. 올바른 부분 반환도 기능 검사를 통과할 수 있지만 완성률 분자에는 들어가지 않는다. 조건별 집계는 [운영 지표](execution/common.md#운영-지표)의 구분을 따르며 대상 지역·기간은 개별 실행 측정의 `dong_code`·`month`에 보존한다. 기능 합격과 운영 합격은 별도로 기록한다.

### 중단 증거와 저장 결과

`report.json`이 없으면 같은 실행 폴더의 `trace.jsonl`과 연속 추적 파일을 읽는다. 새 저장 형식의 참조·변경분을 복원한 뒤 같은 호출 ID의 `start`·`update`·`end`를 최신 전체 스냅샷으로 합치고 호출 한 번으로 센다. 잘린 마지막 행, 시작 누락, 동일 ID의 상충 입력·종료, 상위 호출 누락·순환은 복구 사유로 보존한다. 확인하지 못한 경계를 정상 반환이나 소비량 0으로 채우지 않는다. 완료한 실행 경계와 반환 State가 있어야 반환을 확인할 수 있다.

복구 기록에는 관측 종료 시각, 마지막으로 확인한 시각, 실행 진입 여부와 손상 사유를 남긴다. 미종료의 경과 시간·확인된 호출·토큰·예산은 관측량으로 구분하고 종료 통계에 합산하지 않는다. 취소 노드의 `observed_state`는 관측 증거이며 업무 State나 체크포인트로 복원하지 않는다. 증거 읽기는 원본 결과·누적 기록을 변경하지 않는다.

채점 JSON은 `execution-evaluation-v1` 형식이다. 아래 표는 저장한 결과의 항목이다.

| 결과 항목 | 저장 내용 |
| --- | --- |
| `runs` | 기능 검사 지원 사례의 예정 반복별 공통·보고서 검사 판정, 세부 이유·증거 위치, 검증 완료 여부 |
| `summary.functional` | 검사·필수 사례 통과율, 미판정·누락 반복과 검증 완료 현황 |
| `summary.report_completion` | 보고서 완성률의 분자·분모·비율 |
| `summary.operational` | 실행별 종료·시간·호출·예산 증가분·토큰·비용, 조건별 통계, 필수 목표 판정, 미종료 관측량 |
| `criteria` | 현재 기준 문서 원문·해시, 선택 사례·기대 조건, 원래 반복 계획, 운영 목표·단가 |
| `selection` | 요청한 사례·검사 필터, 선택 사례와 제외 사유 |
| `criteria_sha256`, `evidence_sha256`, `evaluator_sha256` | 사용한 기준, 읽은 원본 파일, 채점 코드의 해시 |
| `provenance` | 실행 당시 `case.json`·`manifest.json`과 현재 사례 기준·문서의 대조 결과 `same`, `changed`, `unknown` |

현재 기준으로 재채점하며 기준 변경 자체를 과거 실행의 실패나 변경 승인으로 해석하지 않는다. 실행 당시의 기준을 확인할 수 없으면 `unknown`으로 남긴다. [규칙 검사](../tests/test_execution_rules.py), [지표 집계](../tests/test_execution_metrics.py), [중단 증거 복구](../tests/test_execution_evidence.py), [채점 저장·명령 연결](../tests/test_execution_scoring.py)을 합성 증거와 모의 모델로 검증한다. 실제 모델 품질·대표 환경의 운영 성능은 별도 실행 결과로 확인한다.

## 9. 최종 출력 품질

`score-outputs`는 여섯 역할의 `agent` 실행과 `workflow/report`가 실제 반환한 답변·산출물을 평가한다. [응답 작성 기준](nodes/compose.md)과 해당 공통 기준을 기존 노드 평가기로 판정하고, 품질 결과를 EX 기능·운영 결과와 별도로 저장한다. 업무를 다시 실행하거나 업무 State를 변경하지 않는다.

```powershell
uv run python -m eval score-outputs <실행묶음경로>
uv run python -m eval score-outputs <실행묶음경로> --method all --judge-model <평가 모델 이름>
uv run python -m eval score-outputs <실행묶음경로> --case <사례-ID> --check N04-O.1 --method all --judge-model <평가 모델 이름>
```

기본 `rules`는 규칙 검사만 수행하고 LLM 검사는 미판정으로 남긴다. `all`에는 별도 평가 모델을 명시한다. `--case`, `--check`, `--row`는 반복 지정할 수 있다. `--env-file`로 모델 연결 환경, `--output`으로 새 채점 JSON 파일를 지정한다. 출력 저장·원본 보존·종료 코드는 기존 채점 명령과 같다.

| 반환 대상 | 평가할 작성 결과 |
| --- | --- |
| 사용자 요청·해석·시각화 | 실제 반환 본문을 작성한 최종 `Composition` 호출과 공개 산출물 선택 |
| 보고서 선정 역할 | 최종 반환에 사용한 승인 선정의 작성 호출 |
| 보고서 설명 역할 | 실제 반환한 각 뷰의 최종 승인 설명 작성 호출 |
| 보고서 인사이트 역할 | 실제 반환한 최종 승인 인사이트 작성 호출 |
| 보고서 전체 | 반환 `analysis_report`의 뷰·설명·인사이트에 대응하는 최종 작성 호출 |

원래 노드·모델 호출 ID와 순서를 유지한다. 수정 전 초안·대체된 산출물·검토자의 `Verification` 응답은 최종 품질 집계에 넣지 않으며, 원본 실행 기록에는 보존한다. 한 작성 호출이 여러 반환 항목에 연결되면 판정은 한 번만 수행하고 항목들이 그 판정을 참조한다. 부분 보고서는 실제 제공한 구성품을 평가하며, 품질 통과를 전체 보고서 완성으로 해석하지 않는다.

최종 본문·산출물과 작성 결과의 연결을 먼저 대조한다. 다른 실행의 결과, 반환 전 오류·취소로 남은 이전 응답, 작성 원문이 없는 기존 승인본을 새 작성 호출로 만들어 평가하지 않는다. 반환물과 원문이 다르거나 연결 증거가 부족하면 그 범위는 미판정으로 남긴다. 실제 전달·조립 오류의 기능 판정은 EX-5·EX-R4 등 기존 실행 검사에서 확인한다. 질문 반환에는 응답 작성 기준을 강제로 적용하지 않는다.

기본 검사는 현행 기준 중 `compose`에 적용되는 공통·작성 검사이며, 검토 판단 검사 `N04-O.3`은 제외한다. 역할·작성 목적별 행은 기존 적용 조건으로 선택한다. EX만 선언된 21개 시나리오에도 채점 시 품질 검사 사본을 구성하므로 별도 실행용 입력이나 모범 답안이 필요하지 않다. 원본 사례의 EX 선언은 변경하지 않는다.

LLM에는 실제 작성 당시의 메시지 전체·응답 명세와 원본 출력을 제공한다. 최종 State로 과거 모델 입력을 재구성하거나 예시 답변·향후 결과를 보충하지 않는다. 규칙 비교에 이미 제공된 독립 기대 항목은 해당 최종 호출에 맞는 범위만 사용한다. 독립 수치·출처·유지할 산출물 목록 등 필요한 비교 자료가 없으면 해당 규칙을 미판정으로 남긴다. LLM 검사의 통과로 빠진 규칙 판정을 대신하지 않는다.

결과 형식은 `output-evaluation-v1`이다. `runs`에는 예정 반복별 반환 항목·작성 원문 연결·품질 판정을, `assessments`에는 작성 호출별 기존 노드 검사 판정을, `summary`에는 품질 집계를 둔다. 실제 반환 경로·원본 결과 ID·노드와 모델 호출 ID를 따라 근거를 확인할 수 있다. 기준·증거·평가 코드 해시와 평가 모델 추적도 보존한다. 평가 모델의 사용량은 업무 실행의 시간·토큰·비용에 합산하지 않는다.

집계의 통과율은 통과 건수 ÷ (통과 + 실패 건수)다. 실행별 집계와 작성 호출별 검사 집계를 구분하며, 미판정·비적용 건수를 따로 기록한다. 누락된 예정 반복과 채점 취소 뒤 남은 반복도 실행 결과에 미판정으로 남긴다. 통과율만으로 검증 완료를 판단하지 않고 `complete`와 미판정 사유를 함께 확인한다.

보고서 설명·인사이트의 분량은 실제 반환에 채택된 승인 작성본을 개별 섹션으로 검사한다. 전체 보고서가 부분 반환됐더라도 제공한 섹션의 분량 기준은 적용한다. 이 적용 조건과 근거 위치는 `criteria.call_cases.format_observation`에 남긴다. 기존에 명시한 적용 조건과 충돌하면 덮어쓰지 않고 해당 호출의 판정을 보류한다.

재채점은 기본적으로 새 판정을 수행한다. `--reuse <기존 품질 채점 경로>`를 지정하면 같은 묶음·평가 방식·모델·기준·증거·평가 코드의 완료된 작성 호출 판정만 재사용한다. 조건이 다르거나 이전 판정이 미완료이면 새로 평가하고 사유를 기록한다. 이전 `score-nodes` 결과를 최종 품질 결과로 자동 전환하지 않는다. 재사용한 판정의 원본 경로·해시를 남기며, 이번 평가 모델 호출량은 새 추적에서 확인한다.

[최종 출력 연결](../tests/test_output_evidence.py), [기존 채점기 연결](../tests/test_output_scoring.py), [판정 재사용·저장](../tests/test_output_reuse.py), [명령 연결](../tests/test_output_cli.py), [기존 시나리오 실행 연결](../tests/test_scenario_execution.py)을 실제 그래프와 준비한 외부 모델 응답으로 검증한다. 실제 업무 모델의 답변 품질과 평가 모델의 판정 정확도는 이 구현 검증에 포함하지 않는다.
