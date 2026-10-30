# infra — 실행 환경

## 로컬 개발 DB

| 파일 | 용도 |
|---|---|
| `docker-compose.yml` | PostgreSQL 17 + Flyway(스키마 · 권한 적용) + Mailpit |
| `.env.example` | 로컬 비밀번호 목록. `.env`로 복사해서 쓴다 (`.env`는 커밋하지 않음) |
| `postgres-init/01-eumi-roles.sh` | DB를 처음 만들 때 계정 4개와 `eumi` DB 생성 (`db/roles/eumi_db_roles.sql` 실행) |

### 처음 실행

```bash
cd infra
cp .env.example .env
docker compose up -d
docker compose ps -a         # postgres: healthy / flyway: Exited (0) / mailpit: running
docker compose logs flyway   # "Successfully applied 6 migrations"
```

- 끌 때: `docker compose down`
- 처음부터 다시 만들기(로컬 DB 삭제): `docker compose down -v` 후 `up -d`
- 새 마이그레이션을 받은 뒤: `docker compose up -d flyway`

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

## 운영

- CI/CD: 서버에 설치된 Jenkins 사용 (인프라 담당 관리)
- 운영 compose · Nginx · 배포 스크립트는 `infra/deploy/`, `infra/scripts/`에 추가 예정
- 운영 DB 계정 비밀번호는 Jenkins credentials로만 넘긴다
