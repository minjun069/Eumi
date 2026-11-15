# 실행 모니터 수정 안내

저장된 `report.json`에서 요청·응답, 실행 흐름, 노드 상세, 실행 설정, 이전 대화를 확인하고, 별도 평가 JSON에서 단위별 지표와 판정 근거를 확인하는 로컬 뷰어다. 모델 호출·실행 상태(`State`)·실행기에는 값을 쓰지 않는다. 평가 파일 검사·지표 표시·예시는 `eval/viewers/report/`에서 관리하고, 실행 기록 표시와 HTML 생성은 공용 위치를 사용한다.

## 수정할 파일

| 바꾸려는 부분 | 파일 | 위치 |
| --- | --- | --- |
| 화면 순서, 영역 제목, 기본 구조 | [report_viewer.html](../report_viewer.html) | `sections`와 여섯 `section` |
| 색상, 글꼴, 여백, 카드, 반응형 배치 | [styles.css](styles.css) | 기본값은 맨 위 `:root`, 세부 스타일은 번호별 주석 아래 |
| 노드명, 상태명, 메시지 역할 | [data.js](data.js) | `nodeNames`, `statuses`, `roles` |
| 추적 기록 연결, 토큰 집계, 이전 대화 구분 | [data.js](data.js) | `inspect`, `sumTokens`, `conversation` |
| 각 영역의 표시 내용·클릭 동작 | [app.js](app.js) | `renderOverview`, `renderFlow`, `renderNodeDetail`, `renderSettings`, `renderConversation` |
| 평가 파일 검사·실행 범위·지표별 사례 연결 | [evaluation.js](../eval/viewers/report/evaluation.js) | 입력 검사, 트리거·대상 필터, 지표·검사 기록 연결 |
| 평가 단위별 지표·집계 기준 | [evaluation-catalog.js](../eval/viewers/report/evaluation-catalog.js) | 뷰어에 등록된 기능·운영·연동 지표 |
| 평가 파일 불러오기·평가 선택 | [app.js](app.js) | 실행·평가 파일 입력과 선택 상태 연결 |
| 평가 지표표·사례 상세 | [evaluation-view.js](../eval/viewers/report/evaluation-view.js) | 종류·실행 횟수, 평가 대상·지표 선택, 판정별 사례 목록과 상세 패널 |
| 실제 기록에 맞춘 임시 파일 | [build_evaluation_samples.py](../eval/scripts/build_evaluation_samples.py) | 저장된 실행의 대상·호출·입출력에서 UI 검토용 파일 생성 |
| 접기·펼치기, 원문 복사, Markdown, 표, 산출물 | [components.js](components.js) | 공통 표시 구성 요소 |
| 한 파일로 내보내기 | [report_html.py](../report_html.py) | HTML 생성 코드 |

HTML과 JavaScript는 요소의 `id`로 연결된다. `id`를 바꿀 때는 `app.js`의 같은 이름도 함께 바꾼다. CSS는 한 선택자의 속성을 한 줄씩 배치했다. 별도 프레임워크나 npm 설치는 필요 없다.

본문과 주요 목록·탭은 16px, 보조 설명과 JSON은 14px 이상으로 표시한다. 남색 실행 목록, 회색 배경, 흰 카드와 테두리로 영역을 구분한다. 폭 680px 이하에서는 실행 목록을 접어 표시하며, 실행을 선택하면 목록을 접고 현재 본문으로 이동한다. 평가 지표와 상세는 넓은 화면에서 나란히, 폭 1,100px 이하에서 세로로 표시한다. 긴 프롬프트·응답·JSON은 줄바꿈해 표시하며, 원문 복사에는 표시용 줄바꿈을 추가하지 않는다.

## 열기·다시 생성하기

`report_viewer.html`을 브라우저에서 직접 열고 **실행 기록 불러오기**로 JSON을 선택하면 분리된 소스의 변경을 확인할 수 있다. CSS·JS를 수정한 뒤에는 새로고침한다.

공유용 리포트는 `Eumi/ai`에서 생성한다.

```powershell
uv run python report_html.py outputs/scenarios --output outputs/scenarios/report.html
```

생성된 HTML에는 CSS·스크립트·데이터·Pretendard 글꼴이 모두 포함된다. 이 파일 하나로 오프라인에서 열 수 있다. 글꼴은 [로컬 자산](assets/PretendardVariable.woff2)과 [SIL Open Font License](assets/Pretendard.LICENSE.txt)를 사용하며, 생성 파일에도 글꼴과 라이선스를 포함한다. 기존에 생성한 HTML은 원본 소스 변경만으로 갱신되지 않으므로 위 명령으로 다시 생성하거나, 새 뷰어에 기존 JSON을 불러온다.

## 평가 결과 불러오기

**평가 → 평가 결과 불러오기**에서 평가 JSON을 선택한다. 여러 파일을 불러올 수 있고, 같은 평가 `id`를 다시 불러오면 해당 평가를 교체한다. 실행 기록 없이 평가 파일만 열 수도 있다.

실행과 함께 열 때는 평가 대상의 실행 ID 범위가 선택한 실행 하나와 일치해야 한다. 여러 실행을 합친 지표를 특정 실행의 수치로 표시하지 않는다. 단위별 `run_ids`가 없으면 파일의 `run_ids`를 사용하며, 파일의 `event`와 실행의 시작 이벤트가 다르면 연결하지 않는다. 범위가 맞지 않아 제외한 대상과 확인할 수 없는 조건은 화면에 안내한다.

| 실행 트리거 | 표시할 업무 평가 | 제외할 대상 |
| --- | --- | --- |
| 사용자 요청 (`user_request`) | 사용자 질문별 요청 처리 | 세부 대시보드 보고서 |
| 보고서 생성 (`analysis_pipeline`) | 동·월별 보고서와 생성 요청 | 사용자 요청 처리, 목적 파악 노드 N01 |

도구·공통 노드는 평가 파일에 기록한 대상을 표시한다. 보고서 내부의 선정·검토 단계는 공통 노드로 세지 않는다. 해석·시각화 전문 에이전트는 별도 전문 작업을 배정·호출한 경우에 포함하며, 보고서에 설명·차트가 있다는 이유만으로 추가하지 않는다. 저장 도구 T04 전용 행동 지표와 진행 판단 노드 N03 전용 진단 지표도 해당 대상에만 표시한다.

평가 대상과 기능·운영·연동 분류를 고르면 **지표명·실측값·판정·사례 수를 표에서 비교**할 수 있다. 지표를 선택하면 옆 패널의 **사례 확인**에서 해당 지표의 검사 사례를 확인한다. 전체·통과·실패·미판정·미실행 필터로 사례를 고르면 검사별 입력, 기대 결과, 실제 결과, 판정 근거, 원인과 증거 위치를 볼 수 있다. **집계·판정 기준**에서는 분자·분모의 의미와 기준을 확인한다. 지표에 연결하지 않은 검사 원본은 별도로 펼쳐 볼 수 있다. 기능·운영·연동 판정은 파일의 값을 표시하며 화면에서 재판정하거나 서로 다른 지표를 평균 내지 않는다.

화면 확인용 임시 파일은 **실제 실행 기록과 UI 검토용 판정을 구분**한다. 평가 대상·호출 식별자·종류·횟수·입출력·실행 상태·시간은 연결한 `report.json`에서 가져온다. 품질 검사의 통과·실패와 그 집계는 화면 검토용 예시이며 실제 품질 채점 결과가 아니다. 임시 실패 판정을 보여 주려고 원본 결과에 결함을 추가하거나 실제 발언을 바꾸지 않는다.

임시 파일의 평가 분류·검사 ID·기준 문서 위치는 `versions.evaluation`에 적힌 작성 당시 기록이다. 삭제된 에이전트별 평가 문서 위치도 과거 기준의 식별 정보로 보존하며, 현행 노드·런타임 기준으로 채점한 결과로 해석하지 않는다.

| 임시 파일 | 연결할 실행 | 공통 노드 | 도구 | 별도 전문 작업 |
| --- | --- | --- | --- | --- |
| [보고서 평가 예시](../eval/viewers/report/evaluation-sample.json) | `c697bdf2-a3ac-42a6-a228-8a94c07a4344` | N02 9회, N03 9회, N04 1회: **3종·19회** | T01 조회 3회, T02 가공 6회: **2종·9회** | 없음 |
| [사용자 요청 평가 예시](../eval/viewers/report/evaluation-user-request-sample.json) | `5897f877-1313-42eb-b4b9-ceaefe0ccb5a` | N01~N04 각각 상위 1회·하위 1회: **4종·8회** | T03 설정 검사 **1종·1회** | 시각화 1회 |

보고서 평가 대상은 실제 동 코드 `1168066000`의 `2025-12` 보고서 1건이다. 사용자 요청은 질문 1건이며 하위 시각화 실행을 포함한다. 공통 노드 안의 모델 호출·결과 레코드, 보고서 내부 선정·작성·검토, DB 저장은 별도 노드·도구 호출로 더하지 않는다. 실제 하위 실행 ID와 호출자는 실행 목록에 보존한다.

이 보고서 예시는 세 에이전트 분리 전 실행을 보존한 자료이며 새 역할의 평가 결과가 아니다. 새 선정·설명·인사이트 역할과 전체 순차 흐름의 실행 증거는 [평가 결과 뷰어](../eval/viewers/results/README.md)에서 각각 확인한다. 현행 검사 배정과 합격 판정은 역할별 판단·작성·검토의 정확성에 [노드 평가](../eval/docs/nodes/README.md), 한 동·월의 순차 실행·보고서 구성에 [동별 보고서 실행 평가](../eval/docs/execution/dashboard-report.md), 에이전트 내부 실행과 성능·안정성에 [에이전트 실행 평가](../eval/docs/execution/README.md)를 적용한다.

한 호출의 여러 검사는 같은 사례로 묶는다. 따라서 종류 수, 실행 횟수, 사례 수, 지표 분모는 서로 다를 수 있다. 노드·도구 탭은 종류 수와 실행 횟수를 구분하며, 실행 정보가 없는 평가 파일의 횟수는 **미기록**으로 표시한다. 호출 시간의 중앙값과 p95는 고유 호출의 기록값에서 계산하고 상위·하위 시간을 합산하지 않는다. 0초도 원본 정밀도 그대로 남긴다. 비용·반복시험처럼 근거가 없는 값은 만들지 않는다.

실제 기록에 맞춘 임시 파일은 `Eumi/ai`에서 다시 생성한다. 모델이나 도구를 재실행하지 않으며 입력한 실행 기록은 변경하지 않는다.

```powershell
python -m eval.scripts.build_evaluation_samples
```

평가를 포함한 공유용 HTML은 다음처럼 만든다. `--evaluation` 뒤에는 하나 이상의 JSON 파일을 지정할 수 있다.

```powershell
uv run python report_html.py outputs/report-improved-20261109-r2 --evaluation eval/viewers/report/evaluation-sample.json --output eval/outputs/evaluation-preview/report.html
```

### 뷰어 입력 형식

아래는 이 뷰어가 현재 읽는 파일 형식이다. 평가기의 생성·자동 채점 기능은 포함하지 않는다. 평가 기준과 기록 원칙은 [평가 방법](../eval/docs/methods.md) 및 [단위별 평가 문서 목록](../docs/README.md#평가)을 따른다.

| 위치 | 값과 의미 |
| --- | --- |
| 파일 최상위 | `type: "evaluation"`, `schema_version: 1`, 평가를 구분하는 `id`, 화면 제목 `title`, 임시 여부 `sample`, 평가 대상 실행 ID 배열 `run_ids`, `units` 배열이 필수 |
| 평가 조건 | 생성 시각 `generated_at`, 평가 범위 `scope`, 코드·자료·모델·설정·평가 기준의 `versions`를 기록. 시작 이벤트 `event`는 `user_request` 또는 `analysis_pipeline` |
| `units[]` | 고유 `id`, 평가 종류 `kind`, 대상 이름 `target`, 지표 배열 `metrics`가 필수. `scope`로 사례 유형·조건을 구분하고 단위별 실행 범위가 있으면 `run_ids`에 기록 |
| 실행 목록 | `units[].executions`에 고유 호출 `id`, `name`, 호출자 `caller`, 실제 `run_id`, 원본 실행 `status`, `elapsed_seconds`, 원본 위치 `evidence`를 기록. 목록 길이를 실행 횟수로 사용하며 검사 수로 추정하지 않음 |
| 도구·노드 식별 | `target_id`에 T01~T04 또는 N01~N05를 기록. 전용 지표의 적용 대상을 구분하며 노드 식별이 불가능하면 그 노드의 평가를 실행 화면에서 제외 |
| `kind` | `tools`, `nodes`, `interpretation`, `visualization`, `user-request`, `report` 중 하나 |
| `verdicts` | `functional`, `operational`, `integration`별 종합 판정. 값은 `통과`, `실패`, `미판정`, `비적용` |
| `metrics[]` | 해당 단위 문서의 정확한 지표명 `name`. 비율은 `numerator`·`denominator`, 시간·비용은 `measurements: [{label, value, unit}]` 사용 |
| 지표별 기록 | `verdict`, 합격 반영 여부 `required`, 시험 기준 `criterion`, 판정 근거 `reason`, 설명 `note`, 증거 위치 `evidence` |
| 지표별 건수 | `unjudged`는 미판정, `not_applicable`은 비적용, `not_executed`는 미실행. 분모 포함 여부는 각 지표의 집계 기준을 따르며 세 건수를 더해 분모를 재계산하지 않음 |
| `checks[]` | 사례 `case_id`, 검사 `check_id`, 판정 대상 `target`, 실행 여부 `executed`, `verdict`가 필수. 지표별 사례 목록에 연결할 정확한 지표명들을 `metrics` 배열에 기록 |
| 사례와 실제 실행 연결 | `checks[].execution_id`는 같은 단위의 `executions[].id`를 참조. `checks[].run_id`는 뷰어가 선택한 상위 실행 범위이며 하위 호출의 실제 실행 ID는 실행 목록에 보존 |
| 사례 상세 | 입력 `input`, 기대 결과 `expected`, 실제 결과 `actual`, 증거 위치 `evidence`, 판정 근거 `reason`, 원인 `cause`, 해당 `run_id`를 기록. 입력·기대·실제 값은 문자열과 JSON 객체를 표시 가능 |

같은 종류에서도 대상·사례 범위별로 `units`를 여러 개 기록할 수 있다. 임시 파일의 사례 입력·실제 결과는 `evidence`의 원본 JSON 위치와 대조할 수 있다. 지표별 사례는 `checks[].metrics`의 명시적 연결을 사용하며 검사 ID의 비슷한 이름으로 추측하지 않는다. 하나의 검사 결과를 여러 지표에서 확인할 수 있지만, 표시한 검사 건수가 지표의 분모와 항상 같지는 않다. 예를 들어 보고서 완성률의 분모는 검사 수가 아니라 보고서 수다.

적용 지표의 누락은 **미기록**, 분모 0은 **산출 불가**로 표시한다. 수치 0을 미기록으로 바꾸지 않는다. 비적용과 달리 필요한 검사의 미실행·미판정은 숨기지 않는다. 미실행은 판정과 별도로 표시하며, 미실행 검사를 통과·실패로 기록한 파일이나 잘못된 비율·중복 지표는 오류로 안내한다. 읽기에 실패한 파일은 기존에 불러온 결과를 덮어쓰지 않는다.

뷰어는 기록된 집계값과 검사 원본을 표시한다. 분모 포함 대상, 목표값, 필수 검사 충족 여부와 파일의 종합 판정이 맞는지는 평가 결과를 생성하는 쪽에서 확인해야 한다. 옛 평가 JSON처럼 다른 형식인 파일은 자동 변환하지 않는다.

## 표시 기준

| 항목 | 표시 내용 | 집계·해석 시 주의점 |
| --- | --- | --- |
| 전체 입출력 | 초기 실행 상태의 마지막 사용자 메시지를 이번 실행의 최초 입력으로 표시. `request.goal`은 별도 작업 요청으로 열람 | 분석 이벤트 실행은 사용자 질문 없이 시작된 것으로 표시 |
| 실행 흐름 | 부모 호출별로 노드를 묶어 호출 시작 순서 표시 | 상위 노드 시간에 하위 호출 시간이 포함될 수 있으므로 행별 시간을 합산하지 않음 |
| 토큰 | 가장 가까운 부모 노드에 모델 호출을 한 번만 집계. 실패한 호출도 포함 | 실제 0과 미기록을 구분하고 일부 호출만 기록되면 기록 비율 표시 |
| 노드 상세 | 노드 진입 시 실행 상태, 모델 호출별 입력·반환 결과, 실행 상태 변경. HTTP 원문과 SDK 스냅샷은 접힌 원본에서 확인 | 모델 호출 중간의 실행 상태를 추정하지 않음 |
| 실행 상태 변화 | 실행 전 필드와 `applied_update` 비교. 노드가 반환한 `node_update`는 별도로 보존 | `messages`는 병합용 변경값일 수 있으므로 완성된 실행 후 상태로 표시하지 않음 |
| 실행 설정 | 추적 기록에 저장된 `settings`, HTTP 생성 옵션, 실행 예산 | PC의 현재 `.env`를 읽거나 누락된 설정을 추정하지 않음 |
| 이전 대화 | 초기 실행 상태에서 이번 질문 전까지의 사용자·에이전트 메시지 | 시작 기록이 없으면 범위를 확정하지 않고 저장된 메시지 전체 표시 |
| 추적 기록 없는 과거 파일 | 연속된 결과를 노드별로 묶어 표시 | 실제 노드 수·시간·모델 입력은 미기록으로 표시 |

## 검증

```powershell
node --test tests/test_report_viewer_data.cjs
node --test eval/tests/test_report_evaluation.cjs
node --test eval/tests/test_report_evaluation_view.cjs
uv run pytest tests/test_report_html.py -q
```

데이터 검증은 중첩 토큰 집계, 실패 호출, 원본 보존, 대화 경계, HTTP 형식 차이와 평가의 실행·트리거 범위, 대상별 적용 지표, 지표별 사례 연결, 누락·0분모·입력 오류를 확인한다. HTML 검증은 분리된 소스가 포함되는지, 실행·평가 데이터 안의 `script` 태그가 실행되지 않도록 변환됐는지 확인한다. 화면 수정 후에는 전체 입출력, 노드 이동, 호출 전환, 검색·오류 필터, 평가 파일·대상·지표·사례 선택, 좁은 화면도 브라우저에서 확인한다.
