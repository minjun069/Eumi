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

## 운영 (https://k15b201.p.ssafy.io)

`develop` → `master` MR을 병합하면 Jenkins가 바뀐 서비스만 빌드 · 배포한다. 담당: 인프라 (김민재).

```
사용자 ─ https ─> Nginx(443) ─┬─ /api/      → backend   127.0.0.1:8080 ─> postgres (내부망, 포트 없음)
                              ├─ /jenkins/  → Jenkins   127.0.0.1:9090
                              └─ /          → web       127.0.0.1:3000
master 병합 ─> GitLab 웹훅 ─> Jenkins: Plan → Sync → Build → Migrate(백업 → Flyway) → Deploy(헬스체크 · 실패 시 되돌림) → Cleanup
```

| 파일 | 서버 위치 | 용도 |
|---|---|---|
| `deploy/docker-compose.prod.yml` | `/srv/eumi/` | 운영 서비스 (postgres · backend · web · mailpit, flyway는 실행할 때만) |
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
