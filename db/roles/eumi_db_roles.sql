-- Eumi DB 계정 초기화 (인프라, Flyway 밖) / PostgreSQL 17
-- 환경(로컬·운영)마다 한 번, 슈퍼유저로 실행한다. 비밀번호는 git에 두지 않고 실행할 때 넘긴다.
--   psql -U postgres -v owner_pw="$OWNER_PW" -v app_pw="$APP_PW" -v pipeline_pw="$PIPELINE_PW" -v ai_pw="$AI_PW" -f eumi_db_roles.sql
--   (Docker 이미지의 초기화 폴더에서는 .sql이 변수를 받지 못하므로 위 명령을 담은 .sh로 실행)
--
-- 계정
--   eumi_owner    : Flyway 실행, 모든 테이블 소유 (Flyway 컨테이너)
--   eumi_app      : Spring Boot (spring.datasource.username)
--   eumi_pipeline : 데이터 분석 파이프라인 (Spark)
--   eumi_ai       : FastAPI
-- 테이블별 권한은 Flyway 콜백 afterMigrate.sql이 마이그레이션마다 다시 적용한다.

CREATE ROLE eumi_owner    LOGIN PASSWORD :'owner_pw';
CREATE ROLE eumi_app      LOGIN PASSWORD :'app_pw';
CREATE ROLE eumi_pipeline LOGIN PASSWORD :'pipeline_pw';
CREATE ROLE eumi_ai       LOGIN PASSWORD :'ai_pw';

CREATE DATABASE eumi OWNER eumi_owner;

-- TIMESTAMP 컬럼(데이터 분석 테이블)과 now() 기본값을 한국 시간으로 맞춘다
ALTER DATABASE eumi SET timezone TO 'Asia/Seoul';

-- 파이프라인·AI는 analysis를 먼저 찾는다 (스키마 없이 테이블 이름만 써도 됨)
ALTER ROLE eumi_pipeline IN DATABASE eumi SET search_path = analysis, public;
ALTER ROLE eumi_ai       IN DATABASE eumi SET search_path = analysis, public;

\connect eumi
-- 테이블은 eumi_owner(Flyway)만 만든다
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
