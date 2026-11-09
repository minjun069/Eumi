-- Flyway 콜백: 마이그레이션이 끝날 때마다 실행한다 (몇 번 실행해도 결과가 같다)
-- 위치: Flyway 마이그레이션 폴더(db/migration/afterMigrate.sql). 계정은 eumi_db_roles.sql로 미리 만든다.
-- 새 테이블을 추가하면 ALL TABLES 줄이 자동으로 권한을 주고, 예외(읽기만 등)만 아래에 추가한다.

GRANT USAGE ON SCHEMA public TO eumi_app, eumi_pipeline, eumi_ai;
GRANT USAGE ON SCHEMA analysis TO eumi_pipeline, eumi_ai;

-- Spring: public 읽기·쓰기. 파이프라인·AI가 쓰는 테이블은 읽기만. Flyway 이력과 analysis는 접근 불가
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO eumi_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO eumi_app;
REVOKE INSERT, UPDATE, DELETE ON dim_region, region_result FROM eumi_app;
--   인사이트 보고서: AI가 직접 저장하므로 Spring은 읽기만 한다 (2026-11-06 결정). 삭제는 결과를 지울 때 FK가 함께 한다
REVOKE INSERT, UPDATE, DELETE ON region_insight_report FROM eumi_app;
REVOKE ALL ON flyway_schema_history FROM eumi_app;

-- 파이프라인: analysis 읽기·쓰기, public은 dim_region(UPSERT)·region_result만
--   TRUNCATE·DROP·CREATE 권한이 없어 "그 달 삭제 후 append / UPSERT" 외의 적재는 DB가 막는다
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA analysis TO eumi_pipeline;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA analysis TO eumi_pipeline;
GRANT SELECT, INSERT, UPDATE ON dim_region TO eumi_pipeline;
GRANT SELECT, INSERT, UPDATE, DELETE ON region_result TO eumi_pipeline;

-- AI: analysis 읽기, public은 지역·결과·복지자원 조회, 인사이트 보고서는 조회·저장·덮어쓰기, AI 대화 메시지는 읽기·추가
--   회원·사례자·상담 기록·로그인 세션은 권한 없음 (사례자 정보는 Spring이 가려서 넘긴다)
GRANT SELECT ON ALL TABLES IN SCHEMA analysis TO eumi_ai;
GRANT SELECT ON dim_region, v_sido, v_sigungu, region_result, v_resource_summary, region_insight_report TO eumi_ai;
--   인사이트 보고서: AI가 동·월마다 직접 저장·덮어쓴다 (2026-11-06 결정). 결과 행 updated_at이 같을 때만 저장하는 문장을 쓴다
--   (docs/work-ref/내부_연동_변경_계획.md 3절). 삭제는 하지 않는다
GRANT INSERT, UPDATE ON region_insight_report TO eumi_ai;
REVOKE DELETE ON region_insight_report FROM eumi_ai;
--   AI 대화: 이전 대화와 이번 질문을 읽고 진행·완료·실패·취소 행을 추가만 한다 (수정·삭제 불가)
--   대화 행(ai_conversation)의 실행 종료 일시·삭제 예정일은 ai_message 트리거가 갱신하므로 권한이 필요 없다
GRANT SELECT, INSERT ON ai_message TO eumi_ai;

-- 모니터링(Grafana, eumi_monitor): 읽기만. analysis 전체와 public의 지역·결과. 회원·사례자·상담·복지자원·AI 대화는 권한 없음
--   계정은 eumi_db_roles.sql이 만든다. 계정이 없는 환경(모니터링을 켜지 않은 DB)에서도 마이그레이션이 멈추지 않도록 있을 때만 준다
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eumi_monitor') THEN
        GRANT USAGE ON SCHEMA public, analysis TO eumi_monitor;
        GRANT SELECT ON ALL TABLES IN SCHEMA analysis TO eumi_monitor;
        GRANT SELECT ON dim_region, region_result TO eumi_monitor;
    END IF;
END $$;
