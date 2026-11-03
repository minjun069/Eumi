-- Flyway 콜백: 마이그레이션이 끝날 때마다 실행한다 (몇 번 실행해도 결과가 같다)
-- 위치: Flyway 마이그레이션 폴더(db/migration/afterMigrate.sql). 계정은 eumi_db_roles.sql로 미리 만든다.
-- 새 테이블을 추가하면 ALL TABLES 줄이 자동으로 권한을 주고, 예외(읽기만 등)만 아래에 추가한다.

GRANT USAGE ON SCHEMA public TO eumi_app, eumi_pipeline, eumi_ai;
GRANT USAGE ON SCHEMA analysis TO eumi_pipeline, eumi_ai;

-- Spring: public 읽기·쓰기. 파이프라인·AI가 쓰는 테이블은 읽기만. Flyway 이력과 analysis는 접근 불가
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO eumi_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO eumi_app;
REVOKE INSERT, UPDATE, DELETE ON dim_region, region_result, region_insight_report FROM eumi_app;
REVOKE ALL ON flyway_schema_history FROM eumi_app;

-- 파이프라인: analysis 읽기·쓰기, public은 dim_region(UPSERT)·region_result만
--   TRUNCATE·DROP·CREATE 권한이 없어 "그 달 삭제 후 append / UPSERT" 외의 적재는 DB가 막는다
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA analysis TO eumi_pipeline;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA analysis TO eumi_pipeline;
GRANT SELECT, INSERT, UPDATE ON dim_region TO eumi_pipeline;
GRANT SELECT, INSERT, UPDATE, DELETE ON region_result TO eumi_pipeline;

-- AI: analysis 읽기, public은 지역·결과·복지자원 조회만, 인사이트 보고서는 저장까지, AI 대화 메시지는 읽기·추가
--   회원·사례자·상담 기록·로그인 세션은 권한 없음 (사례자 정보는 Spring이 가려서 넘긴다)
GRANT SELECT ON ALL TABLES IN SCHEMA analysis TO eumi_ai;
GRANT SELECT ON dim_region, v_sido, v_sigungu, region_result, v_resource_summary TO eumi_ai;
GRANT SELECT, INSERT, UPDATE ON region_insight_report TO eumi_ai;
--   AI 대화: 이전 대화와 이번 질문을 읽고 진행·완료·실패·취소 행을 추가만 한다 (수정·삭제 불가)
--   대화 행(ai_conversation)의 실행 종료 일시·삭제 예정일은 ai_message 트리거가 갱신하므로 권한이 필요 없다
GRANT SELECT, INSERT ON ai_message TO eumi_ai;
