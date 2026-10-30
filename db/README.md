# db — PostgreSQL 스키마

백엔드(Spring Boot), AI 서버(FastAPI), 데이터 파이프라인이 같은 DB를 쓰므로 스키마를 이 폴더 한 곳에서 관리합니다.

| 폴더 | 용도 |
|---|---|
| `migration/` | 스키마 변경 SQL. 번호 순서대로 적용 |
| `seed/` | 지역·기관 기준 정보, 테스트 데이터 |

## 규칙

- 파일 이름: `V{번호}__{설명}.sql` (예: `V1__init.sql`, `V2__add_client_index.sql`)
- 이미 `develop`에 병합된 migration 파일은 고치지 않고, 새 번호의 파일로 변경합니다.
- 스키마를 바꾸는 MR은 백엔드 담당자 리뷰를 받습니다.
- 적용 도구: Flyway 13.11.1. 로컬은 `infra/docker-compose.yml`의 flyway 서비스가 `eumi_owner` 계정으로 적용합니다.
- `migration/afterMigrate.sql`: 마이그레이션이 끝날 때마다 계정별 권한을 다시 적용합니다. 새 테이블은 자동으로 기본 권한을 받으므로, 예외(읽기만 등)만 이 파일에 추가합니다.
- `roles/eumi_db_roles.sql`: 계정 4개(eumi_owner · eumi_app · eumi_pipeline · eumi_ai)와 `eumi` DB를 만듭니다. Flyway 밖에서 환경마다 한 번 실행합니다 (로컬은 compose가 처음 실행할 때 자동).

## 담당과 번호 규칙

| 범위 | 스키마 | 작성 · 관리 |
|---|---|---|
| V1~V5 | public (화면 API가 쓰는 테이블) | DB 담당. 변경은 백엔드와 함께 정함 |
| V6 | analysis (파이프라인 · AI만 쓰는 테이블) | 데이터 분석 |
| V6 이후 전부 | public · analysis | 날짜 형식 버전: `V20261101_01__설명.sql` (두 팀 번호가 겹치지 않게) |

- develop에 병합된 V 파일은 주석 한 글자도 고치지 않습니다. 바꿀 것은 새 버전 파일로 추가합니다.
- 테이블 · 컬럼 변경은 'Eumi ERD 변경 기록' 문서에 먼저 적고 팀별 전달 사항을 갱신합니다.
