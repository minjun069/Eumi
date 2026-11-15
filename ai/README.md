# AI 에이전트

지역 분석 결과를 해석하고 시각화하며 사용자의 추가 질문에 답한다. 공통 실행 흐름과 실행 상태(`State`)를 사용하고, OpenAI 모델 호출·사용자 요청 API·데이터베이스(DB) 저장을 구현했다. 시각화는 등록된 Tableau 뷰를 사용한다.

## 설치·설정

`Eumi/ai`에서 실행한다. Python·의존성 버전은 [pyproject.toml](pyproject.toml)과 [uv.lock](uv.lock)을 따른다.

```powershell
uv sync --locked
```

[환경변수 예시](.env.example)를 참고해 `.env`를 준비한다.

| 설정                                                | 용도                                                               |
| ------------------------------------------------- | ---------------------------------------------------------------- |
| `SETTINGS_API_KEY`                                | 실제 OpenAI 모델 호출                                                  |
| `SETTINGS_MODEL`                                  | 모델 선택. 기본값은 `gpt-6-sol`                                          |
| `SETTINGS_DATABASE_URL`                           | API의 PostgreSQL 연결                                               |
| `SETTINGS_BACKEND_URL` | INT-07·08 알림을 받을 백엔드 주소 |
| `SETTINGS_BACKEND_TOKEN` | INT-07·08의 Bearer 인증 토큰 |
| `SETTINGS_BASE_URL`                               | 모델 API 주소. 기본 OpenAI 직접 연결                                       |
| `SETTINGS_MAX_STEPS` | 공통 실행 단계 한도. 기본 50단계 |
| `SETTINGS_MAX_TOOL_CALLS` | 공통 도구 호출 한도. 기본 30회 |
| `SETTINGS_RUNTIME_TIMEOUT`                        | 공통 활성 실행 시간 한도. 기본 300초                                          |
| `LANGFUSE_*`                                      | 선택적 원격 추적. 기본 비활성, 설정은 [모니터링 문서](docs/runtime/monitoring.md) 참조 |

## API와 컨테이너 실행

사용자 요청은 각 상위 노드의 시작 안내와 마지막 답변·질문을 DB에 저장하고 행마다 백엔드에 알린다. 화면은 새 행을 1초마다 조회하며 산출물은 완료 행의 것만 표시한다. 보고서는 동별 결과를 저장한 뒤 요청 전체의 완료 집계를 알린다. 입력·상태 코드·저장·알림·재요청 기준은 [연동 API](docs/runtime/api.md)에서 관리한다.

```powershell
uv run uvicorn api:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

`SETTINGS_BACKEND_URL`·`SETTINGS_BACKEND_TOKEN`이 없으면 시작하지 않는다.
`GET /health`는 서버 생존 확인이며 DB·모델 연결 성공을 뜻하지 않는다.

```powershell
docker build -t eumi-ai .
docker run --rm --env-file .env -p 8000:8000 --memory=2g eumi-ai
```

컨테이너는 `uv sync --locked --no-dev`로 설치하며 비루트 사용자·워커 1개로 실행한다.
실제 배포의 환경변수·네트워크·출력 볼륨은 인프라 담당 범위다.
OpenAI 직접 연결이 기본이며 GMS를 사용하면 `SETTINGS_BASE_URL`을 지정한다.
GMS의 Responses API·모델 호환성은 실제 키로 검증해야 한다.
GMS 전용 설정은 [.env.gms.example](.env.gms.example)을 `.env.gms`로 복사하고 키·기본 주소·정확한 모델 ID를 입력한다. 기본 주소는 마지막 `/responses`를 제외한 API 주소다. 평가 실행기에 `--env-file .env.gms`를 전달하면 이 파일을 읽는다. 같은 이름의 프로세스 환경변수가 있으면 파일보다 우선하며, `--model`은 설정의 모델명을 덮어쓴다.

사용자 요청은 작업 목적 파악 뒤 작업 진행 판단으로 이동하며, 분석 완료·보고서 실행은 진행 판단으로 시작한다. 진행 판단만 현재 정보의 충분성과 필요한 정보를 결정한다. 추가 작업이 필요하면 작업 선택이 그 판단에 맞는 도구·하위 에이전트와 입력 인자를 고른다. 작업 선택은 도구 명세를 시스템 프롬프트에 제공하고 선택 결과를 엄격한 JSON 형식으로 받는다. 입력 구성·응답 검증·실행 연결은 [모델 입력 구성](docs/runtime/prompts.md#api-설정과-응답-검증)을 따른다.

보고서는 같은 동의 State와 실행 예산으로 시각화 선정·시각화 설명·퀵 인사이트 에이전트를 순차 실행한다. 각 역할은 동일한 공통 노드 전이를 사용한다. 작성·검토 후 후속 작업이 필요하면 진행 판단이 이력을 읽어 추가 조회·가공 또는 재작성을 결정한다. 구현 위치와 앞 단계 산출물 보존·오류 재처리 계약은 [보고서 생성 흐름](docs/agent/report.md)을 따른다.
동별 기본 병렬 수는 2다. 실제 PostgreSQL 권한·NULL 제약과 백엔드 왕복은 미검증이다.
V06 기여도와 V01 중앙 50% 범위 자료원은 미연결 상태다.
2GB에서의 메모리 사용량은 측정하지 않았다.

```powershell
uv run pytest tests/test_api_roundtrip.py tests/test_database.py tests/test_reports.py tests/test_report_roundtrip.py -q
```

2026-11-08: API·DB·보고서·그래프·런타임·실행 상태·프롬프트·모니터링·추적 회귀 114개 통과.
변경한 Python 파일의 Ruff 검사도 통과했다. Docker 엔진이 실행되지 않아 이미지 빌드·2GB 메모리 측정은 수행하지 못했다.

위 테스트는 외부 모델·DB를 대체한다. 실제 모델을 사용하는 파일 DB 검증은
[API 왕복 검증](docs/runtime/api-verification.md)을 따른다. 실행·전송 실패는 실행 상태와
`outputs/api`의 추적 기록·`report.json`·`report.html`에서 확인한다.

2026-11-09: 세 보고서 역할을 분리하기 전 보고서·조회·가공·API·실행 상태 관련 회귀 146개와 Ruff 검사를 통과했다.
실제 모델(`gpt-5.6-luna`)·합성 자료·파일 DB 검증에서는 19단계·도구 9회로
V01·V02·V04의 설명과 퀵 인사이트를 작성·검토·저장했다. 전월 기여도 차이(1·0),
요일별 활동량 차이(-2), 도시 비교를 제외한 V01 설명 범위를 확인했다.
실제 PostgreSQL·운영 백엔드·Tableau 화면 검증은 포함하지 않는다. 이 기록을 새 보고서 역할별 품질 평가나 순차 실행 검증 결과로 대신하지 않는다.

2026-11-10: 세 보고서 에이전트 분리 후 전체 Python 회귀 309개와 추가 경계 사례
4개, 평가 화면 관련 JavaScript 검사 64개를 통과했다. 변경 Python 파일의 Ruff와
문서 참조 검사도 통과했다. 검증은 모의 모델·DB 및 합성 자료·파일 DB·로컬 알림을
사용하며, 새 역할의 실제 모델 품질 평가와 운영 DB·백엔드·Tableau 연동은 미검증이다.

설계 대조에서는 [보고서 실행기](src/report_flow.py)의 순차 그래프와
[업무 노드](src/agent_nodes.py)의 역할별 작업 선택·판단·작성 경로를 확인했다.
기존 State 필드를 그대로 사용하며 단계 진입·완료, 추가 근거와 검토 이력에서
진행 위치를 복원한다. 자기 단계의 추가 조회, 앞 단계 산출물 불변, 검증된 설명만
요약, 공유 예산·오류 재처리·부분 결과·저장 재시도·완료 알림을 각각 검사했다.
이 구조 변경에 추가로 필요한 State 결정은 없다. 기존 자료원·연동 제약은
[보고서의 남은 연결](docs/agent/report.md#6-구현-범위와-남은-연결)에 기록한다.

2026-11-11: 도구 명세를 시스템 프롬프트에 제공하고 선택 응답에 `strict=True`를 적용한 변경의 회귀 115개·Ruff·문서 참조 검사를 통과했다. OpenAI 직접 연결의 `gpt-6-sol`·`gpt-6-luna`로 “강남구 역삼1동의 2025년 12월 고립 위험 단계와 이유를 알려줘”를 각 1회 공통 그래프에서 실행하고 실제 서비스 DB를 읽기 전용으로 조회했다. 두 모델 모두 처음에 해석 에이전트를 선택하고 하위 조회를 성공했으며, 모든 선택 호출에서 `tools`·`tool_choice` 없이 `strict=True`가 전송되고 응답 해석을 통과했다. 조회 결과는 DB 값과 일치했다. 최종 답변은 동명·코드 대응과 산정 근거가 제공되지 않아 모두 부분 완료(`partial / incomplete`)였다. sol은 요청에 없는 시각화 설정 작업도 선택했으므로 전체 도구 선택의 적절성은 검증 완료로 판단하지 않는다. 이 시험은 GMS·보고서 생성·백엔드 알림 검증을 포함하지 않는다.

2026-11-11: 공통 그래프의 중간 응답을 작업 진행 판단으로 전달하도록 수정했다.
보고서 세 역할도 검토 이력을 진행 판단에 넘기며, 추가 조회는 작업 선택·실행으로,
현재 근거로 가능한 수정은 응답 작성으로 이어진다. 작성에서 작업 선택·질문으로
직접 이동하는 경로는 차단했다. 기존 State 필드와 단계 간 전달, 누적 예산,
부분 결과·NULL·오류 재처리 계약을 유지함을 설계와 대조했다.
관련 Python 테스트 151개를 확인했다. 통합 회귀의 1개는 Windows 기록 파일 교체
권한 오류로 실패했으며 새 임시 경로에서 재실행해 통과했다. 작성 후 진행 판단
진입에서 한도에 도달해도 승인 결과를 보존하는 추가 사례도 통과했다.
변경 Python 파일의 Ruff와 문서 참조 검사도 통과했다. 실제 업무 코드를 사용하되
모델·외부 연결은 대체했으며, 이 결과는 실제 모델 품질·운영 DB·백엔드·Tableau
연동 검증을 포함하지 않는다.

2026-11-11: 도구 명세를 시스템 프롬프트에 제공하고 선택 응답에 `strict=True`를 적용한 독립 브랜치에서 프롬프트·선택 HTTP·업무 노드·자료 전달·추적·보고서·그래프·State·런타임 회귀 97개와 변경 Python 파일 9개의 Ruff·포맷 검사를 통과했다.

브랜치 분리 전 개발 작업트리에서는 OpenAI 직접 연결의 `gpt-6-sol`·`gpt-6-luna`로 역삼1동의 2025년 12월 위험 단계·이유 질문을 각 1회 실행해 최초 해석 에이전트 선택·실제 서비스 DB의 읽기 전용 조회·선택 응답 해석을 확인했다. 모든 선택 요청은 `tools`·`tool_choice` 없이 `strict=True`를 사용했고 조회 결과는 DB 값과 일치했지만, 동명·코드 대응과 산정 근거 부족으로 모두 부분 완료(`partial / incomplete`)였으며 sol은 요청에 없는 시각화 설정도 선택했다. 실제 모델 결과는 이 독립 브랜치의 재실행이나 전체 도구 선택의 적절성, GMS·보고서 생성·BE 알림 검증을 뜻하지 않는다.

2026-11-11: `develop`의 `667450c`를 반영하고, 보고서 저장 SQL에서
11/10 마이그레이션으로 삭제된 `summary_lines`·`report` 참조를 제거했다.
현재 컬럼만 있는 로컬 SQLite에서 수정 전 컬럼 오류를 재현하고, 수정 후 신규
저장·같은 동·월의 덮어쓰기를 확인했다. DB 경계·보고서·모델 입력·추적 관련
회귀 111개와 Ruff·문서 참조 검사를 통과했다. 실제 PostgreSQL 저장·운영 호출은
수행하지 않았다. 부분 보고서의 NULL과 운영 스키마의 NOT NULL 제약 충돌은
[보고서 연동 대조](docs/runtime/api.md#26-연동-대조)에 남아 있다.

2026-11-12: 사용자 요청은 목적 파악 후 진행 판단으로, 분석 완료·보고서 각 역할은
진행 판단으로 진입하도록 변경했다. 현재 정보의 충분성과 필요한 정보는 진행 판단만
결정하며, 작업 선택은 그 기록에 따른 도구·하위 에이전트·인자를 선택한다.
기존 State의 판단 기록이 다음 작업 입력과 직렬화·복원 후에도 이어지는지,
자료가 충분하면 작업 선택 없이 응답하는지, 하위 호출·보고서 단계가 같은 예산을
유지하는지 코드와 실행 명세를 대조했다. 평가 영역을 제외한 서비스 회귀 239개와
변경 Python 파일 16개의 Ruff 검사·포맷 검사, 문서 참조 검사(28개 문서·619개 링크)를
통과했다. 모델·외부 연결은 대체했으며 실제 모델 품질·운영 DB·백엔드·Tableau 연동은
검증하지 않았다. 평가 문서·기준·데이터셋은 이번 변경 범위에서 제외했다.

## 로컬 데모·리포트

| 실행 | 명령 |
| --- | --- |
| 모의 노드로 그래프 연결 확인 | `uv run python -m demo.demo --suite` |
| 질문 재개 확인 | `uv run python -m demo.demo --scenario question --answer "추가 정보"` |
| 실제 OpenAI 모델·합성 자료로 S1~S3 실행 | `uv run python -m demo.scenario_demo --suite --output outputs/scenarios` |
| 저장한 결과를 HTML로 열람 | `uv run python report_html.py outputs/scenarios --output outputs/scenarios/report.html` |

모델 데모는 `--model`, `--env-file`로 모델·설정 파일을 지정한다. 결과 폴더에 `report.json`, `answer.txt`, 산출물과 `report.html`을 저장한다. 모의 데모도 `--output 경로`로 기록을 저장할 수 있다. HTML 리포트는 전체 입출력 → 실행 흐름 → 노드별 입출력 → 실행 설정 → 이전 대화 순서로 확인한다. HTML·CSS·JavaScript 수정 위치와 다시 생성하는 방법은 [실행 모니터 수정 안내](report_viewer/README.md)를 따른다.

평가 코드·기준·시나리오·화면·테스트·실행 결과는 `eval/`에 모아 둔다. [평가 실행 안내](eval/README.md)에서 `python -m eval`의 실행·채점 명령과 결과를 여는 방법을 확인한다. 입력·실행 범위는 [단위 평가 실행기](eval/docs/runner.md), 도구·노드·에이전트 실행별 기준은 [평가 문서 목록](docs/README.md#평가)을 따른다.

합성 자료와 S2 HTML 차트 시나리오는 실제 통계·현재 Tableau 지원 범위의 검증 근거가 아니다. 시각화 실행은 [Tableau 안내](docs/agent/tableau.md)를 따른다. 현재 모델 연결·공유 실행 예산을 적용한 실제 모델의 S1~S3 전체 시나리오는 아직 재검증하지 않았다.

## 관련 문서

[설계 명세 목록](docs/README.md) · [연동 API](docs/runtime/api.md) · [코드 작업 지침](docs/coding-guide.md) · [컨텍스트 구성](docs/runtime/prompts.md)
