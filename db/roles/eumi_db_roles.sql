-- Eumi DB 계정 초기화 (인프라, Flyway 밖) / PostgreSQL 17
-- 환경(로컬·운영)마다 한 번, 슈퍼유저로 실행한다. 비밀번호는 git에 두지 않고 실행할 때 넘긴다.
--   psql -U postgres -v owner_pw="$OWNER_PW" -v app_pw="$APP_PW" -v pipeline_pw="$PIPELINE_PW" -v ai_pw="$AI_PW" -v monitor_pw="$MONITOR_PW" -f eumi_db_roles.sql
--   (Docker 이미지의 초기화 폴더에서는 .sql이 변수를 받지 못하므로 위 명령을 담은 .sh로 실행)
--
-- 계정
--   eumi_owner    : Flyway 실행, 모든 테이블 소유 (Flyway 컨테이너)
--   eumi_app      : Spring Boot (spring.datasource.username)
--   eumi_pipeline : 데이터 분석 파이프라인 (Spark)
--   eumi_ai       : FastAPI
--   eumi_monitor  : Grafana (읽기만. eumi DB 의 결과 테이블 + airflow DB 의 실행 이력 + 세션 통계)
-- 테이블별 권한은 Flyway 콜백 afterMigrate.sql이 마이그레이션마다 다시 적용한다 (airflow DB 는 data/airflow/grant_monitor.py).
-- 이미 있는 DB 에 eumi_monitor 만 더하려면 아래 "모니터링 계정" 블록을 슈퍼유저로 실행한다 (infra/README.md 참고).

CREATE ROLE eumi_owner    LOGIN PASSWORD :'owner_pw';
CREATE ROLE eumi_app      LOGIN PASSWORD :'app_pw';
CREATE ROLE eumi_pipeline LOGIN PASSWORD :'pipeline_pw';
CREATE ROLE eumi_ai       LOGIN PASSWORD :'ai_pw';

-- 모니터링 계정: 대시보드 쿼리가 DB 를 붙들지 않도록 동시 접속 · 실행 시간을 제한하고, 다른 세션의 상태를 볼 수 있게 한다
CREATE ROLE eumi_monitor  LOGIN PASSWORD :'monitor_pw' CONNECTION LIMIT 10;
ALTER ROLE eumi_monitor SET statement_timeout = '30s';
GRANT pg_read_all_stats TO eumi_monitor;

CREATE DATABASE eumi OWNER eumi_owner;

-- TIMESTAMP 컬럼(데이터 분석 테이블)과 now() 기본값을 한국 시간으로 맞춘다
ALTER DATABASE eumi SET timezone TO 'Asia/Seoul';

-- 파이프라인·AI는 analysis를 먼저 찾는다 (스키마 없이 테이블 이름만 써도 됨)
ALTER ROLE eumi_pipeline IN DATABASE eumi SET search_path = analysis, public;
ALTER ROLE eumi_ai       IN DATABASE eumi SET search_path = analysis, public;

\connect eumi
-- 테이블은 eumi_owner(Flyway)만 만든다
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
