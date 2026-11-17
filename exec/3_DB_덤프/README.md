# 3. DB 덤프 — 이음이 (Eumi)

운영 서버 DB(`eumi`)를 시연 상태로 떠 둔 덤프와 복원 방법입니다. 포팅 매뉴얼 4-7의 Flyway 대신 이 덤프를 복원하면, AI가 만든 보고서와 대화 기록까지 운영과 같은 상태가 됩니다.

| 항목 | 내용 |
|---|---|
| 파일 | [`eumi-db-20261117.sql.gz`](eumi-db-20261117.sql.gz) — gzip으로 압축한 SQL (약 9MB, 풀면 약 42MB) |
| 뜬 때 | 2026-11-17 13:13 (한국 시간), 운영 서버 |
| DB | PostgreSQL 17.11, 데이터베이스 `eumi` (스키마 `public` · `analysis`) |
| 구조 | 테이블 27 · 뷰 6, Flyway 이력 29건 (마지막 V20261111.01) |
| SHA-256 | `5b94fb23f956d94718c87bb6aeae4bf936b4167e6517e31f0a942ac7671af452` |

## 목차

1. [담긴 것과 뺀 것](#1-담긴-것과-뺀-것)
2. [만든 방법](#2-만든-방법)
3. [새 서버에 복원하기](#3-새-서버에-복원하기)
4. [운영 DB를 건드리지 않고 확인만 하기](#4-운영-db를-건드리지-않고-확인만-하기)

---

## 1. 담긴 것과 뺀 것

**담긴 것**

- 구조: 테이블 · 뷰 · 함수 · 인덱스와 소유자(`eumi_owner`) · 권한(GRANT)
- 데이터 24개 테이블
  - 기관 · 회원 · 사례자 · 담당자 · 상담 기록 · 복지자원. 시연 데이터를 기준 상태로 되돌린 직후 떴습니다 (시연 기관 "싸피 복지기관": 회원 3 · 사례자 6 · 담당자 13 · 상담 15 · 복지자원 3)
  - 분석 결과: `analysis` 스키마의 동 · 격자 지표, 행동 이상 점수, 아파트 실거래, 처리 기록과 `public.region_result`
  - AI가 만든 인사이트 보고서(`region_insight_report`)와 AI 대화 기록(`ai_conversation` · `ai_message`)
  - Flyway 이력(`flyway_schema_history`)
- 운영 DB에는 시연용 가상 데이터만 있습니다. 회원 비밀번호는 해시로만 저장되어 있습니다.

**뺀 것**

| 대상 | 이유 |
|---|---|
| `spring_session` · `spring_session_attributes` 데이터 | 로그인 세션. 구조만 남김 |
| `email_verification` 데이터 | 이메일 인증 코드. 구조만 남김 |
| DB 계정(역할)과 비밀번호 | `pg_dump`는 계정을 담지 않습니다. 복원할 서버의 postgres가 처음 뜰 때 `infra/postgres-init/`이 만듭니다 (포팅 매뉴얼 4-7) |
| `airflow` DB | Airflow 실행 기록. 파이프라인을 처음 배포할 때 다시 만들어집니다 |

---

## 2. 만든 방법

운영 서버에서 시연 데이터를 기준 상태로 되돌린 뒤 아래처럼 떴습니다. 매일 백업(`infra/scripts/backup.sh`)과 같은 방식에서 세션 · 인증 코드 데이터만 뺐습니다.

```bash
sudo -u jenkins /srv/eumi/scripts/dc.sh exec -T postgres pg_dump -U postgres -d eumi --exclude-table-data='public.spring_session*' --exclude-table-data=public.email_verification </dev/null | gzip -9 > /tmp/eumi-db-20261117.sql.gz
```

뜬 뒤 `infra/scripts/restore-test.sh`로 임시 DB에 복원해 운영 DB와 테이블 · 뷰 · Flyway 이력 수가 같은 것을 확인했습니다 ([4장](#4-운영-db를-건드리지-않고-확인만-하기)).

---

## 3. 새 서버에 복원하기

포팅 매뉴얼을 따라 서버를 준비하고, **4-7에서 `migrate.sh` 대신 아래 순서로** 진행합니다. 명령은 서버의 `ubuntu` 계정 기준입니다.

1. 포팅 매뉴얼 4-1 ~ 4-6을 마칩니다 (서버 설정, 비밀값 `.env.config`, 소스, 이미지 빌드).

2. 덤프 파일을 서버로 옮깁니다. PC의 저장소 폴더에서:

   ```bash
   scp -i <키 파일> exec/3_DB_덤프/eumi-db-20261117.sql.gz ubuntu@<서버 주소>:/tmp/
   ```

3. postgres만 먼저 띄웁니다. 빈 볼륨으로 처음 뜨면서 계정과 빈 `eumi` DB(소유자 `eumi_owner`)가 만들어집니다.

   ```bash
   sudo -u jenkins /srv/eumi/scripts/dc.sh up -d --wait --wait-timeout 180 postgres
   ```

4. 덤프를 복원합니다. 오류가 나면 바로 멈춥니다.

   ```bash
   gunzip -c /tmp/eumi-db-20261117.sql.gz | sudo -u jenkins /srv/eumi/scripts/dc.sh exec -T postgres psql -U postgres -d eumi -v ON_ERROR_STOP=1 -q
   ```

   덤프 첫머리에 `\restrict` 명령이 있어 psql 17.6 이상이 필요합니다. 위처럼 운영 compose의 postgres 컨테이너(17.x) 안의 psql을 쓰면 됩니다.

5. 포팅 매뉴얼 4-7 아래의 **"처음 만든 볼륨에서는 아래를 한 번 더 실행합니다"** 명령(`airflow` · `eumi_monitor` 비밀번호 맞추기)을 실행합니다.

6. `migrate.sh`를 실행합니다. 배포 전 백업을 뜬 뒤 Flyway가 이력을 확인합니다. 덤프와 같은 버전의 소스라면 적용할 마이그레이션이 없고, 권한(`afterMigrate.sql`)만 다시 맞춥니다.

   ```bash
   sudo -u jenkins /srv/eumi/scripts/migrate.sh
   ```

7. 포팅 매뉴얼 4-8부터 이어서 서비스를 배포합니다.

**확인**: 4-9의 확인에 더해, 아래 결과가 `members 3 · cases 6 · consultations 15 · reports 235`이면 시연 데이터와 보고서가 그대로 들어온 것입니다.

```bash
sudo -u jenkins /srv/eumi/scripts/dc.sh exec -T postgres psql -U postgres -d eumi -At -F ' · ' -c "SELECT 'members ' || count(*) FROM member WHERE org_id = 3 UNION ALL SELECT 'cases ' || count(*) FROM case_record c JOIN member m ON m.member_id = c.created_by WHERE m.org_id = 3 UNION ALL SELECT 'consultations ' || count(*) FROM consultation UNION ALL SELECT 'reports ' || count(*) FROM region_insight_report" </dev/null
```

복원이 끝나면 서버의 `/tmp/eumi-db-20261117.sql.gz`는 지워도 됩니다.

---

## 4. 운영 DB를 건드리지 않고 확인만 하기

이미 서비스가 도는 서버에서는 운영 DB에 덮어쓰지 않습니다. 대신 `restore-test.sh`가 임시 DB(`eumi_restore_test`)에 복원해 운영 DB와 비교한 뒤 임시 DB를 지웁니다.

```bash
sudo -u jenkins /srv/eumi/scripts/restore-test.sh /tmp/eumi-db-20261117.sql.gz
```

2026-11-17 결과:

```text
운영 eumi       : tables=27 views=6 migrations=29 (last V20261111.01)
복원 eumi_restore_test : tables=27 views=6 migrations=29 (last V20261111.01)
[restore-test] 성공 — 임시 DB는 지웁니다
```
