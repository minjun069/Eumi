# infra — 실행 환경

## 로컬 개발 DB

| 파일 | 용도 |
|---|---|
| `docker-compose.yml` | PostgreSQL 17 + Flyway(스키마 · 권한 적용) + Mailpit. profile `ai`: AI 서버(`ai/Dockerfile`). profile `data`: MinIO · Kafka · pipeline(Spark + Airflow) (데이터 파트만, 아래 참고) |
| `.env.example` | 로컬 비밀번호 목록. `.env`로 복사해서 쓴다 (`.env`는 커밋하지 않음) |
| `postgres-init/01-eumi-roles.sh` | DB를 처음 만들 때 계정 5개와 `eumi` DB 생성 (`db/roles/eumi_db_roles.sql` 실행) |
| `pipeline/` | 데이터 파이프라인 실행 이미지 (`Dockerfile`: Python 3.12 + Spark 3.5.9 + Airflow 2.10, `spark-defaults.conf`, `requirements.txt`). profile `data`에서 빌드 |
| `grafana/provisioning/` | Grafana 설정 파일: `datasources/`(eumi · airflow DB), `dashboards/`(json/ 의 대시보드 자동 등록), 알림. profile `data`의 grafana 컨테이너가 읽는다 |

### 처음 실행

```bash
cd infra
cp .env.example .env
docker compose up -d
docker compose ps -a         # postgres: healthy / flyway: Exited (0) / mailpit: running
docker compose logs flyway   # "Successfully applied …" (처음이면 V1부터 전부)
```

- 끌 때: `docker compose down`
- 처음부터 다시 만들기(로컬 DB 삭제): `docker compose down -v` 후 `up -d`
- 새 마이그레이션이나 seed(`db/seed/R__*.sql`)를 받은 뒤: `docker compose up -d flyway`
- develop을 받은 뒤 `required variable … is missing a value`로 멈추면: `.env.example`에 새로 생긴 줄을 `.env` 끝에 추가한다. 이미 있는 줄(DB 비밀번호)은 바꾸지 않는다 (바꾸면 기존 로컬 DB 계정과 맞지 않는다)

### 파트별 접속 정보 (로컬 전용)

| 쓰는 곳 | 계정 | 비밀번호 | 비고 |
|---|---|---|---|
| Spring Boot | `eumi_app` | `app_local` | `application-local.yml`에 들어 있음 |
| FastAPI | `eumi_ai` | `ai_local` | 기본 스키마: analysis, public |
| 데이터 분석 파이프라인 | `eumi_pipeline` | `pipeline_local` | 기본 스키마: analysis, public |
| DB 클라이언트로 구조 보기 | `eumi_owner` | `owner_local` | 테이블 소유자. 데이터를 직접 고치는 용도로 쓰지 않는다 |

공통: `localhost:5432`, DB `eumi`. 계정마다 볼 수 있는 테이블이 다르다 (`db/migration/afterMigrate.sql`).

### 메일 확인

- 화면: http://localhost:8025
- SMTP(Spring 설정): `localhost:1025`, 인증 없음

## AI 서버 (profile `ai`)

운영과 같은 `ai/Dockerfile`(AI 담당 관리)로 빌드한다. 의존성은 `ai/pyproject.toml` · `ai/uv.lock` 그대로(`uv sync --locked --no-dev`, Python 3.12)이고, `ai/Dockerfile`과 서버 코드(`ai/api.py`)가 있어야 뜬다. 주고받는 형식은 [docs/api](../docs/api/README.md)와 진행 중인 [내부 연동 변경 계획](../docs/work-ref/내부_연동_변경_계획.md)을 따른다.

| 항목 | 값 |
|---|---|
| 주소 | 호스트 `http://localhost:8000` (backend 기본값 `AI_BASE_URL`과 같음), 운영은 내부망 `http://ai:8000`만 |
| DB | `eumi_ai` 계정. compose가 `SETTINGS_DATABASE_URL`을 넣는다 |
| LLM 키 | `ai/.env`의 `SETTINGS_API_KEY` (각자 발급, 커밋 금지). 없으면 ai가 시작되지 않는다. GMS 키면 같은 파일에 `SETTINGS_BASE_URL` · `SETTINGS_MODEL`도 넣는다 (값은 AI 담당 안내, 없으면 OpenAI 주소로 보낸다) |
| backend 주소 · AI 토큰 | compose가 `SETTINGS_BACKEND_URL`(호스트 backend 8080) · `SETTINGS_BACKEND_TOKEN`(기본 `ai_token_local`)을 넣는다. 없으면 ai가 시작되지 않는다 |
| 헬스체크 | `GET /health` → `{"status":"UP"}` (`ai/Dockerfile`의 HEALTHCHECK). 서버가 떠 있다는 뜻이고 DB · 모델 연결을 보장하지는 않는다 |
| 실행 기록 | 컨테이너 `/app/outputs` (볼륨 `aioutputs`). 보기: `MSYS_NO_PATHCONV=1 docker compose cp ai:/app/outputs ../ai/outputs/docker` |

```bash
cd infra
docker compose up -d                              # DB가 먼저 떠 있어야 한다
docker compose --profile ai up -d --build ai      # ai/ 코드가 바뀌면 --build로 다시 빌드
docker compose --profile ai ps ai                 # ai: Up … (healthy)
docker compose --profile ai logs --tail=50 ai     # "Uvicorn running on http://0.0.0.0:8000"
curl -s http://localhost:8000/health              # {"status":"UP"}
# ai → DB (eumi_ai 계정)
MSYS_NO_PATHCONV=1 docker compose --profile ai exec ai /app/.venv/bin/python -c "import os, psycopg; psycopg.connect(os.environ['SETTINGS_DATABASE_URL']).close(); print('db ok')"
docker compose --profile ai stop ai               # 끄기
```

Git Bash는 `/app/...` 같은 컨테이너 안 경로를 Windows 경로(`C:/Program Files/Git/app/...`)로 바꿔 버린다. 컨테이너 경로가 들어가는 명령 앞에는 `MSYS_NO_PATHCONV=1`을 붙인다 (서버의 리눅스 셸에서는 필요 없음).

backend를 ai에 붙여 보려면 호스트에서 http 모드로 실행한다(Git Bash). 변수는 이 명령에만 적용된다.

- 시간 값 4개는 AI 담당이 확정하기 전까지 제안값(AI `runtime_timeout` 300초 기준, [ai-agent-panel.md](../docs/api/ai-agent-panel.md) 5절)으로 둔다.
- http 모드는 내부 연동 토큰 두 개가 없으면 backend가 뜨지 않는다.
  - `EUMI_AI_TOKEN`은 로컬 compose가 ai에 넣는 `SETTINGS_BACKEND_TOKEN`과 같아야 한다 (기본 `ai_token_local`, `infra/.env`에 `EUMI_AI_TOKEN`을 따로 넣었으면 그 값).
  - `EUMI_PIPELINE_TOKEN`은 로컬용으로 아무 값이나 넣되 AI 토큰과 달라야 한다.

```bash
cd backend
EUMI_AI_MODE=http EUMI_AI_EXECUTION_LIMIT=330s EUMI_AI_GRACE_PERIOD=5s \
EUMI_AI_UNRESPONSIVE_AFTER=40s EUMI_AI_CANCEL_WAIT=3s \
EUMI_AI_TOKEN=ai_token_local EUMI_PIPELINE_TOKEN=pipeline_token_local ./gradlew bootRun
```

## 데이터 파이프라인 (MinIO · Kafka · Spark · Airflow)

데이터 파트만 쓴다. compose profile `data`에 있어 다른 파트의 `docker compose up -d`에는 영향이 없다.

| 서비스 | 이미지 | 호스트에서 | 컨테이너 안에서 | 용도 |
|---|---|---|---|---|
| minio | `bitnamilegacy/minio` 2025.7.23 | S3 API `localhost:9000` | `http://minio:9000` | 원본(`raw/`) · 가상 유동(`synth/`) 저장소. 버킷 `sgi`는 시작할 때 자동 생성. 이 빌드에는 내장 웹 콘솔이 없다 |
| s3manager | `cloudlena/s3manager` v0.12.0 | http://localhost:9001 | — | MinIO 버킷을 브라우저로 보는 웹 UI (목록 · 다운로드 · 업로드). 로그인 없음, 데이터는 갖지 않음 |
| kafka | `apache/kafka` 3.9.2 (KRaft 단일 노드) | `localhost:9092` | `kafka:19092` | 토픽 `flow_hourly` (파티션 6, 키 grid_cd). kafka-init이 만들고 끝난다 |
| pipeline | `pipeline/Dockerfile` (python 3.12 + pyspark 3.5.9 + Java 17 + S3A · PostgreSQL JDBC · Kafka 커넥터 + Airflow 2.10 + `data/requirements.txt`) | Spark 잡 UI http://localhost:4040 | — | Airflow 스케줄러. 모든 배치 · 스트리밍 스크립트가 이 안에서 돈다 (local[*]). 저장소 `data/`가 `/opt/eumi/data`로 마운트 |
| pipeline-web | 같은 이미지 | http://localhost:8081 (계정 `.env` AIRFLOW_ADMIN_*) | — | Airflow 웹 UI (DAG 실행 · 로그) |
| pipeline-init | 같은 이미지 | — | — | Airflow 메타 DB 마이그레이션 + 관리자 계정 + Grafana 계정의 실행 이력 읽기 권한(`data/airflow/grant_monitor.py`) (한 번 돌고 종료) |
| grafana | `grafana/grafana-oss` 12.4.3 | http://localhost:3000 (계정 `.env` GRAFANA_ADMIN_*) | — | 파이프라인 모니터링. Prometheus 없이 PostgreSQL을 읽기 전용 계정 `eumi_monitor`로 직접 조회(eumi DB 결과 테이블 + airflow DB 실행 이력). 데이터소스 · 대시보드 · 알림은 `grafana/provisioning/` 파일로 등록되어 화면에서 고칠 수 없다 |

### 켜기 · 끄기

```bash
cd infra
docker compose --profile data up -d --build   # 처음(또는 pipeline/ 변경 후)에는 --build
docker compose --profile data ps -a           # minio · kafka: healthy, flyway · kafka-init: Exited (0)
docker compose --profile data down            # 끌 때도 --profile data (없으면 파이프라인 컨테이너가 남는다)
```

- 데이터까지 지우고 처음부터: `docker compose --profile data down -v` (DB · MinIO · Kafka · Spark 체크포인트 볼륨 모두 삭제)
- Airflow 메타 DB: 새 볼륨이면 `postgres-init/02-airflow-db.sh`가 `airflow` 계정 · DB를 만든다. **이미 있는 로컬 DB**에는 한 번 수동으로: `docker compose exec postgres psql -U postgres -c "CREATE ROLE airflow LOGIN PASSWORD 'airflow_local'" -c "CREATE DATABASE airflow OWNER airflow"`
- Grafana 계정 `eumi_monitor`: 새 볼륨이면 `postgres-init/01-eumi-roles.sh`가 만든다. **이미 있는 로컬 DB**에는 한 번 수동으로 만든 뒤 Flyway와 pipeline-init을 다시 돌려 권한을 준다:
  ```bash
  docker compose exec postgres psql -U postgres -c "CREATE ROLE eumi_monitor LOGIN PASSWORD 'monitor_local' CONNECTION LIMIT 10" -c "ALTER ROLE eumi_monitor SET statement_timeout = '30s'" -c "GRANT pg_read_all_stats TO eumi_monitor"
  docker compose run --rm flyway migrate && docker compose --profile data up -d pipeline-init
  ```
  확인: http://localhost:3000 → Connections → Data sources → `eumi` · `airflow` 각각 Test 가 초록색
- 연결 확인: `docker compose --profile data exec pipeline spark-submit pipeline/ops/check_infra.py` → 마지막 줄 `CHECK_INFRA PASS` (s3a 쓰기 · 읽기, 테이블 11개, JDBC, DML 권한, Kafka 메시지 1건 왕복)

### 접속 정보 (로컬 전용, `.env.example`)

| 항목 | 값 |
|---|---|
| MinIO | 루트 계정 `eumi_minio` / `minio_local123` (스크립트 · Spark · s3manager 공통), 버킷 `sgi` |
| Kafka | 호스트 `localhost:9092`, 컨테이너 `kafka:19092`, 토픽 `flow_hourly` |
| PostgreSQL | `eumi_pipeline` / `pipeline_local` (위 표와 같음) |
| Grafana | 웹 `admin` / `grafana_local`, DB 조회 계정 `eumi_monitor` / `monitor_local` |

### Spark 잡 실행

```bash
docker compose --profile data exec pipeline spark-submit pipeline/<잡>.py
```

- 컨테이너 안 환경변수: `MINIO_ENDPOINT` · `MINIO_BUCKET` · `AWS_ACCESS_KEY_ID` · `AWS_SECRET_ACCESS_KEY`(S3A용), `KAFKA_BOOTSTRAP` · `KAFKA_TOPIC_FLOW`, `PIPELINE_DB_URL`(JDBC) · `PIPELINE_DB_DSN`(psycopg) · `PIPELINE_DB_USER` · `PIPELINE_DB_PASSWORD`
- S3A 엔드포인트 등 기본 설정은 `pipeline/spark-defaults.conf`. 드라이버 메모리 기본 4g (`--driver-memory`로 조정)
- 스트리밍 체크포인트 위치: `/opt/eumi/checkpoint` (볼륨)

### MinIO 이미지

MinIO가 2025년에 커뮤니티 에디션 이미지 배포를 중단해 `docker.io/minio/minio`, `quay.io/minio/minio` 모두 받을 수 없다. Bitnami가 마지막으로 빌드한 RELEASE.2025-07-23 이미지(`bitnamilegacy/minio`)를 쓴다. 더 갱신되지 않으므로 운영 반영 때는 RustFS(`rustfs/rustfs`) 같은 대안을 검토한다.

### 모니터링 대시보드 (Grafana)

http://localhost:3000/d/eumi-pipeline — "Eumi 파이프라인" (월 배치). 실시간 처리는 아래 "스트리밍 대시보드". 파일 `grafana/provisioning/dashboards/json/eumi_pipeline.json`이 원본이고 Grafana가 30초마다 다시 읽는다. **화면에서 고친 것은 저장되지 않는다.** 고치려면 파일을 바꾸고 커밋한다 (패널 하나를 화면에서 만들어 본 뒤 Inspect → Panel JSON 을 복사해 파일에 넣는 방법이 편하다).

한 화면에 네 줄을 위에서 아래로 읽는다. 평소에는 첫 줄이 전부 초록이면 더 볼 게 없고, 빨강이 뜨면 그 아래 줄에서 어디가 문제인지 찾는다.

| 줄 | 패널 | 읽는 곳 | 보는 것 |
|---|---|---|---|
| 현재 상태 | 마지막 실행 · 다음 실행 · 적재된 최신 달 · 검사 결과 · 울린 알림 | airflow · eumi | 지금 상태 한 줄씩. 실패 · 멈춤은 빨강 |
| 실행 현황 | 실행 × 단계 상태판 · 실행 시간 추이(구간별 합산) | airflow (`dag_run` · `task_instance`) | 어느 실행의 어느 단계가 왜 멈췄나, 어느 구간이 달마다 길어지나 |
| 데이터 현황 | 테이블 최신성(전월 대비 열 포함) · 실패한 검사 · 위험 단계 분포 추이 · 실거래가 수집 | eumi (결과 테이블 · `analysis.pipeline_check`) | 결과가 계약대로 채워졌나, 결과 분포가 흔들리나 |
| 시스템 상태 | Airflow 스케줄러 · DB 접속 수 · DB 크기 · 증가 | airflow `job` · `pg_stat_*` | 조용히 죽는 것들, 디스크가 몇 달 남았나 |
| 상세 정보 (접힘) | 실행 이력 · 달별 검사 결과 격자 · 단계별 소요 시간 · 테이블 크기 · 오래 도는 쿼리 | — | 위에서 이상이 보일 때 펼쳐서 파고드는 용도 |

- 패널 제목 옆 ⓘ 에 뜻과 조치가 적혀 있다.
- 숫자 칸은 canvas 패널이다 (이름 13px 회색 → 값 30px → 부가 정보 12px 회색). 값 · 색은 SQL 의 `status` 열에, 부가 정보는 `sub` 열에 묶여 있다.
- 달 단위 표 · 막대는 대시보드 기간(기본 최근 6개월)과 무관하게 DB 에 있는 달을 전부 보여준다. 기간이 걸리는 것은 실행 이력 · 실패 · 재시도뿐이다.
- 단계 이름(01 원본 확인 … 17 결과 검증)은 SQL 안의 `tasks` 표에 적혀 있다. DAG 에 단계를 넣거나 빼면 실행 줄 패널 3개의 그 표를 같이 고친다. 검사 이름 목록(달별 검사 결과)도 `verify_outputs.py` 와 맞춘다.
- 테이블 최신성은 `flow_detail`(월 127만 행)을 두 달치 세느라 1~2초 걸린다.
- Grafana 계정 `eumi_monitor`는 쿼리 30초 제한 · 동시 접속 10개라 대시보드가 DB 를 멈추게 하지는 않는다.

#### 스트리밍 대시보드

http://localhost:3000/d/eumi-streaming — "Eumi 스트리밍". 파일 `grafana/provisioning/dashboards/json/eumi_streaming.json`. 두 대시보드는 화면 위쪽 링크로 오간다 (태그 `eumi`).

유동 상세 스트리밍(`stream_flow_detail.py`)이 배치가 끝날 때마다 `analysis.stream_progress` 에 한 행을 남기고(메시지가 없으면 약 10초마다), 이 화면이 그 표를 5초마다 읽는다. 스트리밍은 시연 때만 돌리므로 **평소에는 "멈춤"이 정상**이다. 기본 기간은 최근 15분.

| 줄 | 패널 | 보는 것 |
|---|---|---|
| 현재 상태 | 스트림 상태 · 밀린 메시지 · 받은 데이터 시각 · 적재(이번 실행) | 살아 있나(처리 중 · 적재 중 · 대기 중 · 멈춤), 따라잡았나, 어느 시각 데이터까지 왔나, 며칠이 닫혀 `flow_detail` 에 더해졌나 |
| 처리 흐름 | 수신 · 처리 속도 · 밀린 메시지 추이 · 배치 소요 시간 · 집계 중인 행(메모리) · 닫힌 날짜 표 | 처리가 수신을 따라가나, 배치가 간격(5초)보다 오래 걸리나, 하루 윈도가 제때 닫히나 |

- 밀린 메시지는 배치가 끝날 때 Kafka 에 최신 위치를 물어 Spark 가 읽은 위치를 뺀 값이다. Spark 진행 정보에도 비슷한 값이 있지만 배치를 계획한 시점 기준이라 거의 항상 0 이어서 쓰지 않는다. Spark 는 읽은 위치를 Kafka 가 아니라 체크포인트에 두므로 Kafka 쪽 도구(consumer group lag)로는 보이지 않는다.
- 스트림을 `pkill` 로 끝내면 종료 기록이 남지 않는다. 그래서 "멈춤"은 마지막 기록이 30초보다 오래됐는지로 판단한다.
- 하루 윈도를 `flow_detail` 에 더하는 배치는 약 50초 걸리고 그동안은 다른 기록이 없다. 잡이 더하기 직전에 표시 행(닫힌 날짜만 있고 더한 행 수는 없음)을 남겨 화면이 "멈춤" 대신 "적재 중"으로 보인다 (10분이 지나도 끝나지 않으면 멈춤).
- 진행 기록은 스트림을 시작할 때 7일 지난 행을 지운다. 기록이 실패해도 스트림은 멈추지 않는다.

#### 알림 (Mattermost)

Grafana 가 대시보드와 같은 쿼리로 1분마다(행 수는 10분마다) 조건을 보고, 걸리면 Mattermost 채널로 메시지를 보낸다. 설정은 `grafana/provisioning/alerting/` 의 파일 4개이고 화면에서는 고칠 수 없다. 알림별로 무엇을 하면 되는지는 `data/README.md` 의 "알림이 오면".

| 파일 | 내용 |
|---|---|
| `rules.yml` | 알림 규칙 8개 (조건 SQL · 기준값 · 메시지 문구) |
| `contact-points.yml` | 보낼 곳. Mattermost 수신 웹훅은 Slack 형식을 받으므로 Slack 연동을 쓴다 |
| `policies.yml` | 어느 알림을 몇 시간마다 다시 보내는지 |
| `templates.yml` | 메시지 제목 · 본문 틀 |

| 알림 | 조건 | 보내는 방식 |
|---|---|---|
| 월 배치 실패 | 끝난 실행 중 가장 최근 것이 실패 | 바로, 해결될 때까지 24시간마다 |
| 월 배치가 돌지 않음 | 6일 09:00 이 지났는데 전월을 처리한 실행이 없음 | 24시간마다 |
| 원본이 없어 월 배치를 건너뜀 | 전월 실행이 건너뜀뿐 (6일 09:00 부터 4일 동안만 본다) | 한 번 (알려만 줌) |
| 월 배치 성공 | 성공으로 끝난 지 30분 이내 | 한 번 (알려만 줌) |
| 결과 검사 실패 | `analysis.pipeline_check` 최신 달에 실패가 있음 | 바로, 24시간마다 |
| 행 수 급변 | 결과 테이블 9개 중 최신 달 행 수가 전월과 30% 넘게 다름 | 24시간마다 |
| DB 접속 과다 | 접속 80개 이상이 5분 지속 | 4시간마다 |
| Airflow 스케줄러 멈춤 | 스케줄러 신호가 60초 넘게 없음이 2분 지속 | 4시간마다 |

- **켜는 법**: `.env` 에 `MATTERMOST_WEBHOOK_URL`(Mattermost 통합 → Incoming Webhook 에서 만든 `https://meeting.ssafy.com/hooks/…`)을 넣고 `docker compose --profile data up -d grafana`. 비밀값이라 커밋하지 않는다.
- **한 사람만 채운다**: 알림은 이 값을 넣은 사람의 Grafana 만 보낸다. 값이 없으면 Grafana 는 그대로 뜨고 전송만 실패한다(로그에 남음). 여러 사람이 넣으면 같은 알림이 사람 수만큼 간다.
- **Grafana 가 떠 있어야 온다**: 도커를 내린 동안에는 조건을 보지 않는다. "월 배치가 돌지 않음"은 6일 09:00 이후 Grafana 가 켜질 때 울린다.
- **DB 가 내려가 있으면 오지 않는다**: 모든 규칙이 DB 를 읽으므로, DB 에 닿지 않는 동안에는 직전 상태를 유지하고 새 알림을 보내지 않는다.
- 해결되면 "[해결] …" 메시지가 한 번 더 온다 (알려만 주는 두 알림은 제외). 지금 울리는 알림은 파이프라인 대시보드의 "울린 알림" 칸과 Grafana 의 Alerting 메뉴에서도 보인다.
- **환경 표시**: 제목 맨 앞에 환경 이름이 붙고(`[로컬] 월 배치 실패`), 본문 끝에 "대시보드 열기 · Airflow 열기" 링크가 붙는다. 로컬과 운영 알림이 같은 채널에 와도 구분하기 위한 것이다. 값은 compose 의 `EUMI_ALERT_ENV`(기본 `로컬`) · `EUMI_AIRFLOW_URL`(기본 `http://localhost:8081`)이고, 규칙 문구에는 환경마다 달라지는 주소를 적지 않는다. 운영에 올릴 때 넣을 값과 절차는 `docs/work-ref/Grafana_서버_배포_인계.md`.
- **고치는 법**: 파일을 바꾸고 `docker compose --profile data restart grafana`. 규칙을 파일에서 지웠는데 Grafana 에 남아 있으면 `rules.yml` 에 `deleteRules` 항목(orgId · uid)을 적는다. 단계 이름 · 기준월 계산식은 대시보드 쿼리와 같으니 DAG 를 바꾸면 같이 본다.
- **다시 띄운 직후 1분**: Grafana 는 뜨자마자 이전에 저장해 둔 알림 설정(보낼 곳 · 제목)으로 동작하고, 파일에서 읽은 새 설정은 약 1분 뒤에 적용된다. 웹훅 주소나 문구를 바꾼 뒤 시험할 때는 로그에 `Applying new configuration to Alertmanager` 가 두 번째로 찍힌 다음에 한다.
- 확인(2026-11-10): 결과 검사 실패 · 월 배치 실패 · 스케줄러 멈춤을 실제로 만들어 발동(약 1분 뒤) · 해결 메시지를 확인했다. 돌지 않음 · 건너뜀은 날짜 조건이라 시각을 바꿔 가며 쿼리로만 확인했고, 행 수 급변 · DB 접속 과다는 조건을 만들지 않아 평소 값(0~2% · 10개)에서 울리지 않는 것만 확인했다.

## 운영 (https://k15b201.p.ssafy.io)

`develop` → `master` MR을 병합하면 Jenkins가 바뀐 서비스만 빌드 · 배포한다. 담당: 인프라 (김민재).

```
사용자 ─ https ─> Nginx(443) ─┬─ /api/      → backend   127.0.0.1:8080 ─> postgres (내부망, 포트 없음)
                              │                 └─ http://ai:8000 → ai (내부망, 포트 없음) ─> postgres · LLM API
                              ├─ /jenkins/  → Jenkins   127.0.0.1:9090
                              ├─ /airflow/  → pipeline-web (Airflow 화면) 127.0.0.1:8081 ─> postgres(airflow DB)
                              ├─ /grafana/  → grafana   127.0.0.1:3001 ─> postgres(eumi · airflow DB, 읽기 전용)
                              └─ /          → web       127.0.0.1:3000
내부망만: pipeline(Airflow 스케줄러 + Spark) ─> minio · kafka · postgres(eumi_pipeline)
master 병합 ─> GitLab 웹훅 ─> Jenkins: Plan → Sync → Build → Migrate(백업 → Flyway) → Deploy(헬스체크 · 실패 시 되돌림) → Pipeline → Monitoring → Cleanup
```

| 파일 | 서버 위치 | 용도 |
|---|---|---|
| `deploy/docker-compose.prod.yml` | `/srv/eumi/` | 운영 서비스 (postgres · ai · backend · web · mailpit, flyway는 실행할 때만) + 데이터 파이프라인(minio · kafka · pipeline · pipeline-web) · grafana |
| `deploy/.env.config.example` | `/srv/eumi/.env.config` | 운영 비밀값 키 목록. 값은 서버에서 무작위로 만들고 git에 두지 않는다 |
| `deploy/nginx/eumi.conf` | `/etc/nginx/sites-available/eumi` | HTTPS · 경로 연결. 인프라 담당이 손으로 반영 (Jenkins는 다르면 경고만) |
| `deploy/nginx/eumi-bootstrap.conf` | (인증서 첫 발급 때만) | |
| `deploy/jenkins/override.conf` | `/etc/systemd/system/jenkins.service.d/` | Jenkins를 127.0.0.1:9090, `/jenkins` 경로로 |
| `deploy/cron/eumi-backup` | `/etc/cron.d/` | 매일 04:30 DB 백업 |
| `scripts/sync.sh` | `/srv/eumi/scripts/` | 저장소 → `/srv/eumi` 복사 (비밀값 · 태그 · 백업 · `data/raw` · `data/processed`는 건드리지 않음). `data/pipeline` · `data/airflow` · Grafana 설정도 복사한다 |
| `scripts/migrate.sh` | 〃 | DB 기동 → 백업 → Flyway |
| `scripts/deploy.sh` | 〃 | 서비스 하나 교체 + 헬스체크, 실패하면 이전 태그로 (`pipeline`은 minio · kafka · 초기화 · 스케줄러 · 화면을 순서대로) |
| `scripts/grafana.sh` | 〃 | Grafana 띄우기 · 설정 다시 읽기 (`--restart`). 공식 이미지라 태그가 없다 |
| `scripts/backup.sh` · `restore-test.sh` | 〃 | 백업 (deploy 10개 · daily 7개 보관) · 복원 시험 (운영 DB는 건드리지 않음) |
| `scripts/cleanup-images.sh` | 〃 | 서비스별 최근 이미지 3개만 보관 (= 롤백 가능한 버전) |
| `scripts/dc.sh` | 〃 | 상태 보기 (`ps`, `logs`) |

운영 규칙

- 운영 서버의 파일은 직접 고치지 않는다. 저장소에서 고쳐 MR → master 병합으로 반영한다 (Nginx 설정만 예외: 병합 후 인프라 담당이 반영).
- 운영 DB 비밀번호 · 키는 서버 `/srv/eumi/.env.config`(jenkins 소유, 권한 600)에만 있다. 필요하면 인프라 담당에게 요청한다.
- 병합된 마이그레이션은 운영 DB에 그대로 적용된다. 컬럼 삭제 · 이름 변경처럼 이전 버전 코드가 깨지는 변경은 "추가 → 코드 전환 → 다음 배포에서 삭제" 두 번에 나눈다.
- 배포 결과는 `https://k15b201.p.ssafy.io/jenkins/`의 `eumi-deploy`에서 본다 (읽기 전용 계정은 인프라 담당에게 요청. Jenkins는 서버 관리자 권한으로 동작하므로 실행 · 설정 권한은 인프라 담당만 가진다). 롤백 · 복구는 서버 접속이 필요하므로 인프라 담당이 진행한다.

### AI 서버 (ai)

- **배포 조건:** `ai/Dockerfile`과 서버 코드 `ai/api.py`가 둘 다 저장소에 있을 때만 Jenkins가 빌드 · 배포한다. `ai/` 바로 아래 `.md`와 `ai/docs/`만 바뀌면 다시 빌드하지 않는다.
- **배포 순서와 실패:** ai → backend → web 순서다. ai가 실패하면 이전 ai로 되돌리고 빌드를 노란색(UNSTABLE)으로 표시한 뒤 backend · web 배포는 계속한다.
- **첫 배포 전 준비:** 서버 `.env.config`에 `EUMI_LLM_API_KEY`(AI 담당 전달)와 `EUMI_AI_TOKEN`(서버에서 `openssl rand -hex 32`)을 넣는다. 값이 없으면 `deploy.sh ai`가 멈춘다. `EUMI_AI_PASSWORD`는 이미 있다.
- **내부 연동 토큰:** backend도 `EUMI_AI_TOKEN`(ai와 같은 값)과 `EUMI_PIPELINE_TOKEN`(서버에서 따로 만든 다른 값)을 받는다. fake인 동안은 없어도 backend가 뜨고, http 모드는 둘 다 있어야 뜬다.
- **연결 방식:** backend는 `EUMI_AI_MODE: fake`인 동안 ai를 부르지 않는다. http로 바꾸는 조건(GMS 주소 · 모델, 시간 값 4개, 토큰 `:?`)은 compose의 backend 주석에 있다.
- **실행 기록:** 컨테이너 메모리(`/app/outputs`, 512MB)에만 남고 ai를 다시 배포하면 지워진다.

배포 뒤 확인 (서버, jenkins 계정):

```bash
cd /srv/eumi
scripts/dc.sh --profile ai ps ai                     # ai: Up … (healthy)
scripts/dc.sh --profile ai logs --tail=50 ai         # "Uvicorn running on http://0.0.0.0:8000", 오류 없음
# backend → ai (내부망): 빈 본문이라 "400 Bad Request"가 나오면 연결된 것이다
scripts/dc.sh exec -T backend wget -S -O /dev/null --header 'Content-Type: application/json' --post-data '{}' http://ai:8000/internal/agent/runs 2>&1 | grep 'HTTP/'
# ai → DB (eumi_ai 계정)
scripts/dc.sh --profile ai exec -T ai /app/.venv/bin/python -c "import os, psycopg; psycopg.connect(os.environ['SETTINGS_DATABASE_URL']).close(); print('db ok')"
# ai → LLM API (바깥 연결): compose의 SETTINGS_BASE_URL(GMS 주소)로 요청한다. 키는 보내지 않는다.
#   200 · 401 · 404가 나오면 나가는 길은 열려 있다 (연결 오류 · 시간 초과면 막힘). 주소가 아직 없으면 OpenAI 주소로 확인한다
scripts/dc.sh --profile ai exec -T ai /app/.venv/bin/python -c "import os, httpx; u = os.environ.get('SETTINGS_BASE_URL', 'https://api.openai.com/v1').rstrip('/'); print(u, httpx.get(u + '/models', timeout=5).status_code)"
```

### 데이터 파이프라인 · Grafana (운영)

compose의 profile `pipeline` 서비스다: `minio`(원본 저장소) · `kafka`(스트리밍 시연용) · `pipeline`(Airflow 스케줄러 + Spark) · `pipeline-web`(Airflow 화면) · `grafana`(대시보드 2개 + 알림 8종), 한 번 돌고 끝나는 `kafka-init` · `pipeline-init`.

- **배포 조건:** `infra/pipeline/`(이미지 정의)이 바뀌었거나 아직 한 번도 배포하지 않았으면 Jenkins가 `eumi-pipeline` 이미지를 빌드해(처음 10~20분) `deploy.sh pipeline`으로 띄운다. 운영 compose만 바뀌면 빌드 없이 지금 태그로 다시 적용한다. `data/`(스크립트 · DAG)만 바뀌면 Sync가 복사할 뿐 컨테이너는 그대로다.
- **실패:** 앱(ai · backend · web)을 먼저 배포하고 pipeline · Grafana는 맨 뒤다. 실패하면 이전 태그로 되돌리고 빌드를 노란색(UNSTABLE)으로 표시한다. 앱과 `eumi` DB에는 영향이 없다.
- **Grafana:** 배포마다 `grafana.sh --skip-if-unconfigured`가 돈다. 비밀값 · DB 계정이 없으면 건너뛰고, `infra/grafana/`가 바뀐 배포에서는 다시 띄운다(알림 설정 반영). 다시 띄운 직후 약 1분은 이전 알림 설정이 쓰인다.
- **자원:** `pipeline` 6 GB(Spark 드라이버 4 GB 포함, 월 배치가 돌 때만 쓴다) · `kafka` 1.5 GB · `minio` 1 GB · `pipeline-web` 1 GB · `grafana` 512 MB. 디스크는 MinIO 원본 약 2 GB + 가상 유동 월 약 1 GB + Kafka 보관 7일.
- **백업:** 매일 · 배포 전 백업은 `eumi` DB만 한다. `airflow` DB(실행 이력)와 MinIO 볼륨은 백업하지 않는다 (원본 파일은 데이터 파트가 따로 보관).

**지킬 것**

- **과거 달 월 배치를 서버에서 다시 돌리지 않는다.** 서버 DB에는 유동 상세(`analysis.flow_detail`)가 없어서, 2025-07~12를 다시 돌리면 행동 지표의 변화 항목이 NULL로 덮이고 격자 이상 점수가 지워진다. Airflow 화면에서 `{"months": [...]}`로 수동 실행하지 않는다. 필요하면 데이터 파트가 먼저 유동 상세를 적재한다.
- 기준 테이블 적재(`load_dim_region.py` · `load_dim_grid100.py`)도 서버에서 돌리지 않는다. 같은 내용이 `db/seed`(R__01 · R__10)로 이미 들어가 있다.
- Grafana · MinIO · Kafka를 `dc.sh up`으로 직접 띄우지 않는다. 비밀값이 비면 Grafana가 기본 비밀번호(admin)로 뜬다. `deploy.sh pipeline` · `grafana.sh`가 값을 확인하고 띄운다.

**처음 한 번 (인프라 담당, 서버에서. 첫 배포 전)**

1. **비밀값:** `/srv/eumi/.env.config`에 `.env.config.example`의 "데이터 파이프라인" 9개(`EUMI_PIPELINE_PASSWORD` 포함)와 "Grafana" 2개(`GRAFANA_ADMIN_PASSWORD` · `EUMI_MONITOR_PASSWORD`)를 넣는다. `MATTERMOST_WEBHOOK_URL`은 없어도 된다(알림만 가지 않는다).
2. **DB 계정 · DB:** 서버 DB 볼륨은 이미 있어서 `postgres-init/`이 돌지 않는다. `.env.config`의 값을 읽어 직접 만든다 (값을 화면에 출력하지 않는다).
   ```bash
   sudo -u jenkins bash <<'EOF'
   set -e
   cd /srv/eumi
   get() { grep -E "^$1=" .env.config | head -1 | cut -d= -f2-; }
   AF=$(get AIRFLOW_DB_PASSWORD); MON=$(get EUMI_MONITOR_PASSWORD)
   [ -n "$AF" ] && [ -n "$MON" ] || { echo "키 값이 없습니다"; exit 1; }
   printf "CREATE ROLE airflow LOGIN PASSWORD '%s';\nCREATE ROLE eumi_monitor LOGIN PASSWORD '%s' CONNECTION LIMIT 10;\nALTER ROLE eumi_monitor SET statement_timeout = '30s';\nGRANT pg_read_all_stats TO eumi_monitor;\n" "$AF" "$MON" \
     | scripts/dc.sh exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -q
   scripts/dc.sh exec -T postgres psql -U postgres -q -c "CREATE DATABASE airflow OWNER airflow" </dev/null
   EOF
   ```
   테이블 권한은 따로 주지 않는다. `eumi` DB는 다음 Flyway 실행의 `afterMigrate.sql`이, `airflow` DB는 `pipeline-init`의 `grant_monitor.py`가 준다. DB 볼륨을 새로 만들었을 때(복구)는 `postgres-init/`이 계정을 기본 비밀번호로 만들므로, `ALTER ROLE airflow PASSWORD …` · `ALTER ROLE eumi_monitor PASSWORD …`로 `.env.config` 값과 맞춘다.
3. **MinIO 볼륨:** `docker volume create eumi-miniodata` (pgdata처럼 external — `down -v`에도 남는다).
4. **Nginx:** `eumi.conf`의 `/airflow/` · `/grafana/` 블록을 반영한다 (`/etc/nginx/sites-available/eumi`에 복사 → `sudo nginx -t` → `sudo systemctl reload nginx`). 컨테이너가 뜨기 전에는 두 경로만 502다.

**배포 뒤 (서버, jenkins 계정)**

```bash
cd /srv/eumi
scripts/dc.sh --profile pipeline ps        # minio · kafka · pipeline · pipeline-web · grafana: Up … (healthy)
scripts/dc.sh --profile pipeline logs --tail=50 pipeline
```

1. **원본 업로드** (약 2 GB. 데이터 파트의 `data/raw` 폴더를 서버 `/srv/eumi/data/raw`에 두고, 컨테이너 계정이 읽을 수 있게 `chmod -R go+rX`):
   ```bash
   scripts/dc.sh --profile pipeline exec -T pipeline python3 pipeline/m1_collect/upload_raw.py     # raw/ → MinIO sgi/raw (DB는 건드리지 않는다)
   ```
2. **Airflow:** `https://k15b201.p.ssafy.io/airflow/`에 `AIRFLOW_ADMIN_*`로 로그인 → **원본 업로드 뒤에** DAG `eumi_monthly`를 unpause 한다. 켜면 가장 최근 스케줄 1건(전월 대상)이 바로 도는데, 그 달 원본이 없으므로 `check_inputs`가 전체를 skip 하고 끝난다 (원본을 올리기 전에 켜면 skip이 아니라 실패한다). 정기 실행은 매월 5일 03:00(전월 대상)이다.
3. **Grafana:** `https://k15b201.p.ssafy.io/grafana/`에 `admin` / `GRAFANA_ADMIN_PASSWORD`로 로그인 →
   - Connections → Data sources의 `eumi` · `airflow`를 각각 Test → 둘 다 OK
   - Dashboards → Eumi 폴더의 "Eumi 파이프라인" · "Eumi 스트리밍"이 열린다
   - Alerting → Alert rules의 Eumi 폴더에 규칙 8개. DAG를 unpause 하기 전에는 "월 배치가 돌지 않음"이 울릴 수 있다
   - 웹훅을 넣었다면 Alerting → Contact points → `eumi-mattermost` → Test로 채널에 "[운영] …"이 오는지 본다
4. **웹훅을 나중에 넣을 때:** `.env.config`에 `MATTERMOST_WEBHOOK_URL`을 넣고 `scripts/grafana.sh`를 실행한다 (컨테이너가 새 값으로 다시 만들어진다).

**서버에서 로컬과 다른 점**

- 유동 상세가 없어 대시보드 "테이블 최신성"의 유동 상세가 비어 보이고, `analysis.pipeline_check`가 비어 "검사 결과"가 "기록 없음"이다. 서버에서 월 배치가 처음 실제로 돌면 채워진다.
- 스트리밍은 시연 때만 수동으로 돌리므로 스트리밍 대시보드는 평소 "멈춤"이 정상이다.
- 월 배치가 끝난 뒤 backend에 알리는 호출(INT-04)은 아직 DAG에 없다. 보고서 생성은 서버에서 INT-04를 직접 호출한다.

**문제가 생기면**

- 파이프라인만 멈추기: `scripts/dc.sh --profile pipeline stop pipeline pipeline-web kafka minio grafana` (앱은 그대로 돈다). 다시 띄울 때는 `scripts/deploy.sh pipeline <태그>` · `scripts/grafana.sh`.
- 이전 버전으로: `docker images eumi-pipeline`에서 태그를 골라 `scripts/deploy.sh pipeline <이전 태그>`.
- 태스크가 실패하면 Airflow 화면의 태스크 로그를 데이터 파트에 전달한다.
