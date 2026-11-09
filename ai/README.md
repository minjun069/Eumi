# AI Agent

지역 분석 결과의 해석·시각화·사용자 요청을 처리한다. 공통 그래프와 State 기반 실행, OpenAI 모델 연결, 사용자 요청 API·DB 저장을 구현했다. 시각화는 등록된 Tableau 뷰를 사용한다.

## 설치·설정

`Eumi/ai`에서 실행한다. Python·의존성 버전은 [pyproject.toml](pyproject.toml)과 [uv.lock](uv.lock)을 따른다.

```powershell
uv sync --locked
```

[환경변수 예시](.env.example)를 참고해 `.env`를 준비한다.

| 설정 | 용도 |
| --- | --- |
| `SETTINGS_API_KEY` | 실제 OpenAI 모델 호출 |
| `SETTINGS_MODEL` | 모델 선택. 기본값은 `gpt-6-sol` |
| `SETTINGS_DATABASE_URL` | API의 PostgreSQL 연결 |
| `SETTINGS_BACKEND_URL` · `SETTINGS_BACKEND_TOKEN` | INT-07·08 주소와 Bearer 인증 |
| `SETTINGS_BASE_URL` | 모델 API 주소. 기본 OpenAI 직접 연결 |
| `LANGFUSE_*` | 선택적 원격 추적. 기본 비활성, 설정은 [모니터링 문서](docs/ai-agent-monitoring.md) 참조 |

## API와 컨테이너 실행

[연동 API](docs/ai-runtime-api-20261029.md)가 입력·상태 코드·저장·알림·재요청 기준이다.
사용자 요청은 단계별 행 저장과 INT-07, 보고서 요청은 직접 저장과 INT-08을 연결한다.
되묻기는 완료 행으로 저장하고 다음 질문은 대화 기록을 읽는 새 실행이다.
보고서 생성 생략·시점 비교·기존 실행 중 거절은 없다.

```powershell
uv run uvicorn api:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

`SETTINGS_BACKEND_URL`·`SETTINGS_BACKEND_TOKEN`이 없으면 시작하지 않는다.
`GET /health`는 서버 생존 확인이며 DB·모델 연결 성공을 뜻하지 않는다.

```powershell
docker build -t eumi-ai .
docker run --rm --env-file .env -p 8000:8000 --memory=2g eumi-ai
```

컨테이너는 `uv sync --locked --no-dev`로 설치하며 비루트 사용자·1 worker로 실행한다.
실제 배포의 환경변수·네트워크·출력 볼륨은 인프라 담당 범위다.
OpenAI 직접 연결이 기본이며 GMS를 사용하면 `SETTINGS_BASE_URL`을 지정한다.
GMS의 Responses API·모델 호환성은 실제 키로 검증해야 한다.

보고서 작성·검토는 [보고서 생성 흐름](docs/temp/analysis-report-workflow.md)을 따른다.
동별 기본 병렬 수는 2다. 실제 PostgreSQL 권한·NULL 제약과 BE 왕복은 미검증이다.
V06 기여도와 V01 중앙 50% 범위 자료원은 기존 미연결 상태다.
2GB에서의 메모리 사용량은 측정하지 않았다.

```powershell
uv run pytest tests/test_api_roundtrip.py tests/test_database.py tests/test_reports.py tests/test_report_roundtrip.py -q
```

2026-11-08: API·DB·보고서·그래프·런타임·State·프롬프트·모니터링·추적 회귀 114개 통과.
변경한 Python 파일의 Ruff 검사도 통과했다. Docker 엔진이 실행되지 않아 이미지 빌드·2GB 메모리 측정은 수행하지 못했다.

위 테스트는 외부 모델·DB를 대체한다. 실제 모델을 사용하는 파일 DB 검증은
[API 왕복 검증](docs/api-roundtrip.md)을 따른다. 실행·전송 실패는 State와
`outputs/api`의 trace·report.json·report.html에서 확인한다.

## 로컬 데모·리포트

| 실행 | 명령 |
| --- | --- |
| 모의 노드로 그래프 연결 확인 | `uv run python -m demo.demo --suite` |
| 질문 재개 확인 | `uv run python -m demo.demo --scenario question --answer "추가 정보"` |
| 실제 OpenAI 모델·합성 자료로 S1~S3 실행 | `uv run python -m demo.scenario_demo --suite --output outputs/scenarios` |
| 저장한 결과를 HTML로 열람 | `uv run python report_html.py outputs/scenarios --output outputs/scenarios/report.html` |

모델 데모는 `--model`, `--env-file`로 모델·설정 파일을 지정한다. 결과 폴더에 `report.json`, `answer.txt`, 산출물과 `report.html`을 저장한다. 모의 데모도 `--output 경로`로 기록을 저장할 수 있다. HTML 리포트는 전체 입출력 → 실행 흐름 → 노드별 입출력 → 실행 설정 → 이전 대화 순서로 확인한다. HTML·CSS·JavaScript 수정 위치와 다시 생성하는 방법은 [실행 모니터 수정 안내](report_viewer/README.md)를 따른다.

합성 자료와 기존 S2 HTML 차트 시나리오는 실제 통계·현재 Tableau 지원 범위의 검증 근거가 아니다. 시각화 실행은 [Tableau 안내](docs/TABLEAU.md)를 따른다. 현재 모델 연결·공유 실행 예산 변경은 전체 시나리오 재검증 전이며, 이전 계약에 의존하는 테스트는 갱신이 필요하다.

## 관련 문서

[설계 명세 목록](docs/README.md) · [연동 API](docs/ai-runtime-api-20261029.md) · [코드 작업 지침](docs/CODING_GUIDELINES.md) · [컨텍스트 구성](docs/context-composition.md)
