# db — PostgreSQL 스키마

Spring Boot · FastAPI · 데이터 파이프라인이 같은 DB(`eumi`)를 쓰므로 스키마를 이 폴더 한 곳에서 관리합니다. PostgreSQL 17, Flyway 13.11.1을 씁니다.

| 경로 | 용도 |
|---|---|
| `migration/V*__*.sql` | 스키마 변경. Flyway가 버전 순서대로 한 번씩 적용 |
| `migration/afterMigrate.sql` | Flyway 콜백. 마이그레이션이 끝날 때마다 계정별 권한을 다시 적용 |
| `roles/eumi_db_roles.sql` | 계정 4개와 `eumi` DB 생성. Flyway 밖에서 환경마다 한 번 실행 (로컬은 compose가 처음 실행할 때 자동) |
| `seed/` | 개발 · 시연용 초기 데이터 |

로컬 DB 실행 방법은 [infra/README.md](../infra/README.md)에 있습니다.

## 스키마와 담당

| 스키마 | 담는 것 | 마이그레이션 작성 |
|---|---|---|
| public | 화면 API가 쓰는 테이블 | 김민재 (DB · BE) |
| analysis | 파이프라인 · AI만 쓰는 테이블 | 강병민 (DE) |

스키마가 달라도 FK는 그대로 겁니다.

## 계정과 권한

| 계정 | 쓰는 곳 | 권한 요약 |
|---|---|---|
| `eumi_owner` | Flyway | 모든 테이블 소유. 앱 코드에서는 쓰지 않음 |
| `eumi_app` | Spring Boot | public 읽기 · 쓰기 (`dim_region` · `region_result` · `region_insight_report`는 읽기만). analysis와 Flyway 이력은 접근 불가 |
| `eumi_pipeline` | 데이터 파이프라인 | analysis 읽기 · 쓰기 · 삭제. public은 `dim_region` 넣기 · 수정, `region_result` 읽기 · 쓰기 · 삭제 |
| `eumi_ai` | FastAPI | analysis 읽기. public은 지역 · 결과 · 복지자원 조회와 `region_insight_report` 저장. 회원 · 사례자 · 상담 기록은 접근 불가 |

- 권한은 `migration/afterMigrate.sql`이 마이그레이션마다 다시 적용합니다. 새 테이블은 자동으로 기본 권한을 받으므로, 예외(읽기만 등)만 이 파일에 추가합니다.
- `afterMigrate.sql`은 버전 파일이 아니어서 병합 후에도 고칠 수 있고, 다음 `migrate` 때 다시 적용됩니다.
- 파이프라인 · AI 계정의 기본 스키마는 `analysis, public`입니다. DB 시간대는 `Asia/Seoul`입니다.

## 바꾸는 순서

1. 'Eumi ERD 변경 기록'에 변경 내용과 팀별 전달 사항을 먼저 적습니다 (DB 담당과 상의).
2. 새 파일을 만듭니다: `V{날짜}_{순번}__{설명}.sql` (예: `V20261031_01__add_resource_category.sql`). 같은 날 두 번째 파일은 `_02`.
3. 로컬에서 확인합니다.
   ```bash
   cd infra
   docker compose up -d flyway
   docker compose logs flyway      # "Successfully applied"
   ```
4. MR을 올립니다. public은 강병민, analysis는 김민재가 **승인한 뒤** 병합합니다 ([CONTRIBUTING 3.3](../CONTRIBUTING.md#33-누가-무엇을-리뷰하나)).
5. 병합 후 팀 채널에 알립니다. 팀원은 pull 후 `docker compose up -d flyway`로 반영합니다.

## 지킬 것

- **develop에 병합된 V 파일은 주석 한 글자도 고치지 않습니다.** Flyway가 파일이 바뀐 것을 감지해 멈춥니다. 되돌릴 것도 새 파일로 추가합니다.
- V1~V6는 숫자 버전이고, 그 뒤로는 두 파트의 번호가 겹치지 않게 날짜 버전을 씁니다.
- 파이프라인 적재: DROP · 전체 TRUNCATE · Spark overwrite 기본 동작은 쓰지 않습니다(권한으로도 막혀 있음). 그 달 행을 지운 뒤 append하거나 UPSERT합니다. `dim_region` · `analysis.dim_grid100`은 다른 테이블이 참조하므로 UPSERT로만 갱신합니다.
- 로컬 DB가 꼬였으면 `docker compose down -v` 후 `up -d`로 처음부터 다시 만듭니다 (로컬 데이터 전부 삭제).

## 초기 데이터 (seed)

- 위치는 `seed/`, 이름은 `R__{순번}_{설명}.sql`입니다 (예: `R__01_dim_region.sql`). R 파일은 내용이 바뀔 때마다 다시 실행되므로 `INSERT ... ON CONFLICT DO NOTHING`으로 씁니다.
- 넣는 순서: 행정동(`dim_region`) → 기관 · 회원 → 사례자. FK 때문에 순서가 바뀌면 실패합니다.
- **가짜 데이터만** 넣습니다. 실제 개인정보는 넣지 않습니다.
- seed 경로는 로컬(`infra/docker-compose.yml`)과 운영(`infra/deploy/docker-compose.prod.yml`) Flyway에 모두 켜져 있습니다. 파일을 넣으면 다음 `docker compose up -d flyway`와 배포 때 적용됩니다.
- 운영에도 들어가므로 시연 계정의 평문 비밀번호는 넣지 않고 해시만 넣습니다.
- 데이터 파트 seed(R__01, R__10~18)는 `data/pipeline/ops/make_seed.py`가 로컬 DB에서 만든다(임시 테이블에 COPY 후 `ON CONFLICT DO NOTHING`). 값이 바뀌면 다시 생성해 커밋하고, 로컬은 `docker compose up -d flyway`로 적용한다.

| 파일 (예정) | 내용 | 담당 |
|---|---|---|
| `R__01_dim_region.sql` | 강남구 · 춘천시 행정동 | 강병민 |
| `R__02_organization.sql` | 기관 | 김민재 |
| `R__03_demo_member.sql` | 개발 · 시연용 회원 (PBKDF2 해시, OPEN-04) | 김민재 |
| `R__04_welfare_resource.sql` | 시연용 복지자원 39건 (실제 복지서비스 26 + 동 단위 가상 자원 13). `data/demo_seed/make_demo_seed.py` 로 생성 | 강병민 |
| `R__05_demo_case.sql` | 시연용 사례자 52명 · 담당자 · 상담 기록 186건 (가상 인물). 같은 스크립트로 생성 | 강병민 |
| `R__10_dim_grid100.sql` ~ `R__19_bh_region_contribution.sql` | 데이터 파이프라인 결과 11개 테이블(격자 기준, 배경 상세 · 지표, 행동 지표, 읍면동 월별 결과, 격자 이상 점수, 실거래가, 지표별 기여도). 2025-07~12, 약 41 MB. `flow_detail`(760만 행)은 제외 | 강병민 |
