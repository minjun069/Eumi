# API 왕복 검증

파일 저장소·실제 모델·HTTP 알림을 사용하는 임시 검증 절차다. 명령은 `Eumi/ai/`에서 실행한다.

[검증 스크립트](../experiments/api_roundtrip.py)는 다음 흐름을 한 번 실행한다.

`질문 파일 생성 → 임시 호출자 POST → API 202 접수 → 실제 AI 실행 → 응답 파일 저장 → POST 알림 → 임시 수신자 재조회·204 응답`

DB 조회·저장만 JSON 파일로 대체한다. 공통 API·State·업무 노드와 실제 모델 호출은 그대로 사용한다. 임시 API와 수신기는 `127.0.0.1`의 빈 포트에서 자동으로 시작하고 종료하므로 별도 백엔드·PostgreSQL·uvicorn 실행은 필요하지 않다.

## 1. 준비

PowerShell에서 `Eumi/ai`로 이동해 `uv sync --locked`를 실행한다. 기존 `.env`를 보존하고 `SETTINGS_API_KEY`에 사용할 API 키를 설정한다. 모델을 호출할 수 있는 계정과 인터넷 연결이 필요하다.

파일 모드에서는 DB 연결이 필요 없으며 백엔드 주소·토큰은 검증기가 로컬 수신기에 맞게 지정한다. 이 스크립트는 Langfuse를 비활성화한다.

## 2. 실행

```powershell
$roundtripDir = "outputs/roundtrip-01"
uv run python -m experiments.api_roundtrip --file-db "$roundtripDir/messages.json" --output $roundtripDir --model gpt-5.6-luna
```

기본 질문은 **2025년 12월 강남구 전체 읍면동의 종합 위험도 지도 요청**이다. 개별 읍면동 필터·수치 조회·원인 해석 없이 등록된 Tableau 설정을 사용한다. 대화 UUID는 자동 생성하고, 질문 ID는 기본 101로 저장한다. 실제 모델의 판단에 따라 실행 경로와 호출 수는 달라질 수 있다.

| 옵션 | 사용 방법 |
| --- | --- |
| `--file-db` | 새 메시지 JSON 파일 경로. 생략하면 PostgreSQL 모드로 실행 |
| `--output` | trace·보고서·왕복 검사 결과를 저장할 폴더 |
| `--question "질문 내용"` | 기본 질문 변경. 파일 모드에는 통계 조회 자료원이 연결되어 있지 않음 |
| `--model` | 검증 모델 지정. 생략해도 `gpt-5.6-luna`를 사용하며 `.env`의 모델 선택보다 우선 |
| `--conversation-id`, `--question-id` | 직접 지정할 경우 유효한 UUID와 양의 정수 사용 |

한 번 실행해도 여러 업무 단계에서 유료 모델 호출이 발생한다. 일반 실행 한도는 16단계·도구 4회·하위 Agent 1회·활성 시간 150초이며, 한도 종료 시 공통 실행기의 별도 종료 응답 예산을 사용할 수 있다. 호출당 timeout은 30초, 출력 상한은 2,048토큰, 추론 강도는 `low`다. 작업·SDK 자동 재시도는 0회이며 전체 시나리오도 자동 재실행하지 않는다.

## 3. 실행 중 모니터링

콘솔의 `HTTP 202 accepted`는 접수만 의미한다. `trace.jsonl`이 생성되면 **다른 PowerShell 창**에서 같은 `Eumi/ai` 경로와 출력 폴더를 지정해 확인한다.

```powershell
$roundtripDir = "outputs/roundtrip-01"
$traceFile = Get-ChildItem -LiteralPath $roundtripDir -Recurse -Filter trace.jsonl | Select-Object -First 1
Get-Content -LiteralPath $traceFile.FullName -Encoding UTF8 -Tail 5 -Wait
```

모델·노드·도구의 시작, 입력, 반환값, 검증, 저장·알림 기록이 추가된다. 도구가 산출물을 반환하면 해당 내용도 기록에서 확인할 수 있다. `Ctrl+C`로 이 모니터링 명령만 종료한다. HTML 보고서는 전체 실행이 끝난 뒤 생성된다.

## 4. 종료 후 확인

```powershell
Get-Content -LiteralPath "$roundtripDir/roundtrip.json" -Encoding UTF8
Get-Content -LiteralPath "$roundtripDir/messages.json" -Encoding UTF8
```

| 파일 | 확인할 내용 |
| --- | --- |
| `roundtrip.json` | 전체 검사 결과, 모델 호출 수, 수신한 세 식별자, 상세 보고서 경로 |
| `messages.json` | 원래 질문과 저장된 AI 응답·상태·산출물 |
| `<대화 UUID>/<실행 폴더>/trace.jsonl` | 실행 중 누적한 호출·중간 작업 기록 |
| 같은 폴더의 `report.json`·`report.html` | 최종 State와 전체 추적. HTML을 브라우저에서 열어 요청·도구 반환·산출물·저장·알림 확인 |

자동 검사의 통과 조건은 `passed=true`와 종료 코드 0이다. 작업 상태가 `completed`이고, 실제 모델 HTTP 호출·실행 중 trace 생성·파일 저장 후 알림·요청 질문 ID·저장 행 ID·알림의 연결가 확인되어야 한다. 정상 흐름의 접수 상태는 202, 알림 응답은 204다.

산출물 내용은 HTML에서 별도로 확인한다. 기본 질문이라면 `Embed01RiskMap`, 강남구(`p_city=11680`), 종료 월 `2025-12-01`, 읍면동 필터 전체 조건과 최종 안내를 대조한다. `passed`는 이 내용의 정확성이나 Tableau 화면 표시까지 판정하지 않는다.

## 5. 실패 확인·재실행

`passed=false` 또는 종료 코드 1이면 `status`, `failure` 또는 콘솔의 `error_type`을 먼저 확인한다. 모델 작업이 실패해도 실패 행 저장과 알림 자체는 성공할 수 있으므로 204 수신만으로 작업 완료를 판단하지 않는다. `waiting_input`은 되묻기 내용을 완료 행으로, `partial`은 유효 결과·한계를 완료 행으로 저장한다. 모델 인증·사용량 오류는 보고서의 모델 HTTP 응답에서 확인한다.

시작 단계에서 실패하면 `roundtrip.json`이 없을 수 있다. `FileExistsError`이면 기존 메시지 파일을 재사용한 것이므로 `roundtrip-02`처럼 **새 출력 폴더와 새 파일 경로**를 지정한다. 기존 기록을 보존하고 원인을 확인한 뒤 필요한 경우에만 재실행한다.

이 검증은 단일 질문·단일 프로세스의 임시 파일 왕복이다. 실제 PostgreSQL의 트랜잭션·권한·동시성, 운영 백엔드·SSE, 분석 보고서 저장, Tableau 브라우저 표시 검증은 포함하지 않는다. `outputs`는 로컬 검증 자료이며 Git에 포함하지 않는다.


## 6. 보고서 생성 API의 임시 DB 검증

[보고서 검증기](../experiments/report_roundtrip.py)는 로컬 HTTP로
`POST /internal/insight-reports/runs`를 호출하고, 보고서 실행이 끝나면 파일 저장과 상세 기록을 확인한다.
조회·저장 경계만 임시 JSON 파일로 대체한다. 실행 API·업무 노드·모델 호출·State는 서비스와 같으며,
완료 알림은 검증기가 띄운 로컬 수신기로 보내고 본문 없는 204 응답을 확인한다.

```powershell
.\.venv\Scripts\python.exe -m experiments.report_roundtrip --file-db outputs/report-01/db --output outputs/report-01/runs
```

`--file-db` 디렉터리가 없으면 요청 동·월의 최근 6개월 **합성 자료**로 새 DB를 만든다.
기본 대상은 `2025-12`, `1168066000`이다. `--month`, `--dong-codes`로 변경할 수 있다.
합성 자료는 월별 점수, 예시 행동 지표 기여도, 요일별 활동량, 격자별 이상 점수를 제공한다.
V01 도시 중앙 범위·V06 요인별 기여도·시간대·성연령 자료는 포함하지 않는다.
실제 통계·화면 수치와 비교하는 자료로 사용하지 않는다.

기존 디렉터리는 다시 읽는다. 생성 전에는 요청 동·월의 분석 결과와 수정 시각만 확인하며,
기존 보고서와 비교해 생략하지 않는다. 같은 요청을 다시 보내도 새로 생성해 동·월별 보고서를 덮어쓴다.
성공 판정에는 이번 실행에서 새로 생성된 기록만 사용하고 이전 실행 기록은 보존한다.
다른 자료를 사용하려면 `sources.json`의 기존 Dataset 구조에 맞춰 내용을 준비한다.

| 파일 | 내용 |
| --- | --- |
| `<file-db>/sources.json` | 자료원별 조회 자료·열 정의·출처. 조회마다 파일을 다시 읽음 |
| `<file-db>/reports.json` | 저장된 보고서 목록. 동·월별 덮어쓰기와 NULL 항목 허용 |
| `<output>/<run_id>/report.json` | 최종 State와 상세 trace. 요청과 분석 결과 확인 기록도 State에 포함 |
| 같은 폴더의 `trace.jsonl`, `report.html` | 누적 호출 기록과 기존 HTML 뷰어. 재처리·저장 재시도도 같은 동의 기록에 포함 |

기본 모델은 기존 왕복 검증기와 같은 `gpt-5.6-luna`이며 `--model`로 변경한다.
실제 실행에는 `SETTINGS_API_KEY`와 인터넷 연결이 필요하고 모델 호출 비용이 발생한다.
실행 한도는 기존 Settings를 그대로 따른다. 기본 활성 시간은 60초이며 필요하면 실행 전에
`$env:SETTINGS_RUNTIME_TIMEOUT='180'`처럼 설정한다. 실행별 한도·사용량은 State에서 확인한다.

202 접수 후 요청한 모든 동의 보고서 완료 상태, 파일 재조회 결과 일치, 모델 입력 기록과 닫힌 추적 기록,
로컬 완료 알림의 요청 ID·월·저장 건수·실패 동 목록을 확인해 `passed=true`·종료 코드 0을 반환한다.
실패·부분 완료는 종료 코드 1이다. 저장된 NULL 항목, State의 오류와 상세 trace를 확인한다.
이 검사는 설명의 정확성, 실제 PostgreSQL 권한·제약, Tableau 화면 표시를 검증하지 않는다.

[AI 실행 안내](../README.md) · [AI 문서 목록](README.md)
