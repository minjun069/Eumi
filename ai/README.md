# AI Agent

지역 분석 결과의 해석·시각화·사용자 요청을 처리한다. 공통 그래프와 State 기반 실행·질문 재개, OpenAI 모델 연결, 사용자 요청 API·DB 저장을 구현했다. 시각화는 등록된 Tableau 뷰를 사용한다.

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
| `SETTINGS_NOTIFICATION_URL` | 응답 저장 후 백엔드 POST 알림 |
| `LANGFUSE_*` | 선택적 원격 추적. 기본 비활성, 설정은 [모니터링 문서](docs/ai-agent-monitoring.md) 참조 |

## 사용자 요청 API

백엔드가 질문을 `public.ai_message`에 커밋한 뒤 호출한다. AI는 질문과 `public.region_result`를 조회하고, 실행 → 답변 저장·커밋 → 백엔드 알림 순서로 처리한다. 알림 실패 시 모델을 다시 실행하거나 저장된 답변을 삭제하지 않는다.

```powershell
uv run uvicorn api:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

아래는 현재 API 구현 기준이다.

| 항목 | 입출력·조건 |
| --- | --- |
| 실행 요청 | `POST /internal/agent/runs`, 본문 `{"conversation_id":"UUID","question_id":101}` |
| 접수 응답 | 본문 없는 202 |
| 오류 응답 | 422: 본문 오류, 404: 질문 없음, 409: 종료된 질문·실행 중인 대화, 503: DB·알림 설정 부재 또는 DB 장애 |
| 완료 알림 | `conversation_id`, 원래 질문의 `question_id`, 새 AI 행의 `message_id`를 POST |
| 알림 수신 | 백엔드는 AI 행을 재조회·전달하고 본문 없는 204 반환. 다른 상태·본문·timeout은 전달 실패 |
| 실행 기록 | `outputs/api/<conversation_id>/<실행 폴더>/`에 `trace.jsonl`, 종료 후 `report.json`·`report.html` 저장 |

중복 방지는 단일 프로세스의 실행 중 대화와 DB의 종료 행을 기준으로 한다. 재시작 복구·다중 워커 중복 방지·자동 재알림·질문 재개 및 취소 API는 없다. `waiting_input`·`partial`은 DB 대응 계약이 없어 완료로 저장하지 않고 `UnmappedResponse`로 기록한다. 실행 기록은 재개용 체크포인트가 아니다.

실제 PostgreSQL 저장·알림 왕복은 **미검증**이다. 확인하려면 DB에 커밋된 실제 질문 ID로 실행한다. `experiments.api_roundtrip`은 실제 모델을 호출하며, 기본 모델은 저비용 `gpt-5.6-luna`다. `--file-db`를 지정한 경우에만 DB를 임시 파일로 대체한다.

```powershell
uv run python -m experiments.api_roundtrip --conversation-id <실제-UUID> --question-id <실제-ID>
uv run pytest tests/test_api_roundtrip.py tests/test_database.py -q
```

단위 테스트는 외부 연결을 대체하므로 실제 DB 왕복의 검증 근거가 아니다.

파일 저장소로 실제 모델·HTTP 알림을 검증하는 준비·실행·모니터링·실패 확인 절차는 [API 왕복 검증](docs/api-roundtrip.md)을 따른다.

## 로컬 데모·리포트

| 실행 | 명령 |
| --- | --- |
| 모의 노드로 그래프 연결 확인 | `uv run python demo.py --suite` |
| 질문 재개 확인 | `uv run python demo.py --scenario question --answer "추가 정보"` |
| 실제 OpenAI 모델·합성 자료로 S1~S3 실행 | `uv run python scenario_demo.py --suite --output outputs/scenarios` |
| 저장한 결과를 HTML로 열람 | `uv run python report_html.py outputs/scenarios --output outputs/scenarios/report.html` |

모델 데모는 `--model`, `--env-file`로 모델·설정 파일을 지정한다. 결과 폴더에 `report.json`, `answer.txt`, 산출물과 `report.html`을 저장한다. 모의 데모도 `--output 경로`로 기록을 저장할 수 있다. HTML 리포트에서 요청·응답·호출·검증·사용량을 확인한다.

합성 자료와 기존 S2 HTML 차트 시나리오는 실제 통계·현재 Tableau 지원 범위의 검증 근거가 아니다. 시각화 실행은 [Tableau 안내](docs/TABLEAU.md)를 따른다. 현재 모델 연결·공유 실행 예산 변경은 전체 시나리오 재검증 전이며, 이전 계약에 의존하는 테스트는 갱신이 필요하다.

## 관련 문서

[설계 명세 목록](docs/README.md) · [API 초안](docs/ai-runtime-api-20261029.md) · [코드 작업 지침](docs/CODING_GUIDELINES.md) · [컨텍스트 구성](docs/context-composition.md)
