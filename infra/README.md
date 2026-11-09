# infra — 실행 환경

## 로컬 개발 DB

| 파일 | 용도 |
|---|---|
| `docker-compose.yml` | PostgreSQL 17 + Flyway(스키마 · 권한 적용) + Mailpit. profile `ai`: AI 서버(`ai/Dockerfile`). profile `data`: MinIO · Kafka · pipeline(Spark + Airflow) (데이터 파트만, 아래 참고) |
| `.env.example` | 로컬 비밀번호 목록. `.env`로 복사해서 쓴다 (`.env`는 커밋하지 않음) |
| `postgres-init/01-eumi-roles.sh` | DB를 처음 만들 때 계정 4개와 `eumi` DB 생성 (`db/roles/eumi_db_roles.sql` 실행) |
| `pipeline/` | 데이터 파이프라인 실행 이미지 (`Dockerfile`: Python 3.12 + Spark 3.5.9 + Airflow 2.10, `spark-defaults.conf`, `requirements.txt`). profile `data`에서 빌드 |

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
| LLM 키 | `ai/.env`의 `SETTINGS_API_KEY` (각자 발급, 커밋 금지). 없으면 ai가 시작되지 않는다 |
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

backend를 ai에 붙여 보려면 호스트에서 http 모드로 실행한다(Git Bash). 시간 값 4개는 AI 담당이 확정하기 전까지 아래 제안값으로 둔다. 변수는 이 명령에만 적용된다.

```bash
cd backend
EUMI_AI_MODE=http EUMI_AI_EXECUTION_LIMIT=90s EUMI_AI_GRACE_PERIOD=5s \
EUMI_AI_UNRESPONSIVE_AFTER=40s EUMI_AI_CANCEL_WAIT=3s ./gradlew bootRun
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
| pipeline-init | 같은 이미지 | — | — | Airflow 메타 DB 마이그레이션 + 관리자 계정 (한 번 돌고 종료) |

### 켜기 · 끄기

```bash
cd infra
docker compose --profile data up -d --build   # 처음(또는 pipeline/ 변경 후)에는 --build
docker compose --profile data ps -a           # minio · kafka: healthy, flyway · kafka-init: Exited (0)
docker compose --profile data down            # 끌 때도 --profile data (없으면 파이프라인 컨테이너가 남는다)
```

- 데이터까지 지우고 처음부터: `docker compose --profile data down -v` (DB · MinIO · Kafka · Spark 체크포인트 볼륨 모두 삭제)
- Airflow 메타 DB: 새 볼륨이면 `postgres-init/02-airflow-db.sh`가 `airflow` 계정 · DB를 만든다. **이미 있는 로컬 DB**에는 한 번 수동으로: `docker compose exec postgres psql -U postgres -c "CREATE ROLE airflow LOGIN PASSWORD 'airflow_local'" -c "CREATE DATABASE airflow OWNER airflow"`
- 연결 확인: `docker compose --profile data exec pipeline spark-submit pipeline/ops/check_infra.py` → 마지막 줄 `CHECK_INFRA PASS` (s3a 쓰기 · 읽기, 테이블 11개, JDBC, DML 권한, Kafka 메시지 1건 왕복)

### 접속 정보 (로컬 전용, `.env.example`)

| 항목 | 값 |
|---|---|
| MinIO | 루트 계정 `eumi_minio` / `minio_local123` (스크립트 · Spark · s3manager 공통), 버킷 `sgi` |
| Kafka | 호스트 `localhost:9092`, 컨테이너 `kafka:19092`, 토픽 `flow_hourly` |
| PostgreSQL | `eumi_pipeline` / `pipeline_local` (위 표와 같음) |

### Spark 잡 실행

```bash
docker compose --profile data exec pipeline spark-submit pipeline/<잡>.py
```

- 컨테이너 안 환경변수: `MINIO_ENDPOINT` · `MINIO_BUCKET` · `AWS_ACCESS_KEY_ID` · `AWS_SECRET_ACCESS_KEY`(S3A용), `KAFKA_BOOTSTRAP` · `KAFKA_TOPIC_FLOW`, `PIPELINE_DB_URL`(JDBC) · `PIPELINE_DB_DSN`(psycopg) · `PIPELINE_DB_USER` · `PIPELINE_DB_PASSWORD`
- S3A 엔드포인트 등 기본 설정은 `pipeline/spark-defaults.conf`. 드라이버 메모리 기본 4g (`--driver-memory`로 조정)
- 스트리밍 체크포인트 위치: `/opt/eumi/checkpoint` (볼륨)

### MinIO 이미지

MinIO가 2025년에 커뮤니티 에디션 이미지 배포를 중단해 `docker.io/minio/minio`, `quay.io/minio/minio` 모두 받을 수 없다. Bitnami가 마지막으로 빌드한 RELEASE.2025-07-23 이미지(`bitnamilegacy/minio`)를 쓴다. 더 갱신되지 않으므로 운영 반영 때는 RustFS(`rustfs/rustfs`) 같은 대안을 검토한다.

## 운영 (https://k15b201.p.ssafy.io)

`develop` → `master` MR을 병합하면 Jenkins가 바뀐 서비스만 빌드 · 배포한다. 담당: 인프라 (김민재).

```
사용자 ─ https ─> Nginx(443) ─┬─ /api/      → backend   127.0.0.1:8080 ─> postgres (내부망, 포트 없음)
                              │                 └─ http://ai:8000 → ai (내부망, 포트 없음) ─> postgres · LLM API
                              ├─ /jenkins/  → Jenkins   127.0.0.1:9090
                              └─ /          → web       127.0.0.1:3000
master 병합 ─> GitLab 웹훅 ─> Jenkins: Plan → Sync → Build → Migrate(백업 → Flyway) → Deploy(헬스체크 · 실패 시 되돌림) → Cleanup
```

| 파일 | 서버 위치 | 용도 |
|---|---|---|
| `deploy/docker-compose.prod.yml` | `/srv/eumi/` | 운영 서비스 (postgres · ai · backend · web · mailpit, flyway는 실행할 때만) |
| `deploy/.env.config.example` | `/srv/eumi/.env.config` | 운영 비밀값 키 목록. 값은 서버에서 무작위로 만들고 git에 두지 않는다 |
| `deploy/nginx/eumi.conf` | `/etc/nginx/sites-available/eumi` | HTTPS · 경로 연결. 인프라 담당이 손으로 반영 (Jenkins는 다르면 경고만) |
| `deploy/nginx/eumi-bootstrap.conf` | (인증서 첫 발급 때만) | |
| `deploy/jenkins/override.conf` | `/etc/systemd/system/jenkins.service.d/` | Jenkins를 127.0.0.1:9090, `/jenkins` 경로로 |
| `deploy/cron/eumi-backup` | `/etc/cron.d/` | 매일 04:30 DB 백업 |
| `scripts/sync.sh` | `/srv/eumi/scripts/` | 저장소 → `/srv/eumi` 복사 (비밀값 · 태그 · 백업은 건드리지 않음) |
| `scripts/migrate.sh` | 〃 | DB 기동 → 백업 → Flyway |
| `scripts/deploy.sh` | 〃 | 서비스 하나 교체 + 헬스체크, 실패하면 이전 태그로 |
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
- **연결 방식:** backend는 `EUMI_AI_MODE: fake`인 동안 ai를 부르지 않는다. http로 바꾸는 조건은 compose의 backend 주석에 있다.
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
# ai → LLM API (바깥 연결): 401 또는 200이면 나가는 길은 열려 있다
scripts/dc.sh --profile ai exec -T ai /app/.venv/bin/python -c "import httpx; print(httpx.get('https://api.openai.com/v1/models', timeout=5).status_code)"
```
