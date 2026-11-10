-- 인사이트 보고서 구조 변경 2단계: 예전 형식 칸 삭제 · 새 칸 NOT NULL + 시연용 보고서 / PostgreSQL 17
-- 1단계: V20261106_01__insight_report_slots.sql (새 칸 추가, 예전 칸은 비워 둘 수 있게만)
-- 2026-11-10 AI-b 보고서 연결 ('Eumi ERD 변경 기록' > 위험 탐지 대시보드 > 11/9 · 11/10 변경)
--   * 저장 주체는 AI다 (11/9 결정, 권한은 afterMigrate.sql). AI가 eumi_ai 계정으로 직접 저장하고 백엔드는 조회만 한다.
--   * 백엔드(AI-b, dedee75)는 새 칸과 v_region_insight의 quick_insight · insight_generated_at만 읽는다.
--   * AI의 저장 문장(ai/src/database.py)에서 예전 칸 이름(summary_lines · report)을 빼야 저장된다.
--     운영은 fake 모드라 AI가 보고서를 저장하지 않으므로, http로 바꾸기 전까지만 고치면 된다.
--
-- 순서
--   1. 시연용 보고서: region_result의 모든 동 · 월에 '[시연용 예시]' 보고서를 넣는다.
--      AI가 만든 최신 보고서(새 형식, result_updated_at = 결과 행 updated_at)는 건드리지 않고,
--      예전 형식 행과 옛 보고서(결과가 다시 쓰여 꼬리표가 다름)만 이 예시로 바꾼다.
--      수치는 그 동 결과 행의 점수 · 단계만 쓴다. AI가 그 동 보고서를 저장하면 덮어쓴다.
--   2. 예전 형식만 있는 행이 남아 있으면 멈춘다 (1에서 모두 바꾸므로 보통은 없다).
--   3. v_region_insight를 지운다 (예전 칸 summary_lines를 쓰고 있어 칸보다 먼저 지워야 한다).
--   4. 예전 형식 CHECK 3개와 summary_lines · report를 지우고, 새 8칸을 NOT NULL로 바꾼다.
--   5. v_region_insight를 다시 만든다. 최신 보고서만 붙이므로 옛 보고서는 퀵 인사이트 · 생성 일시가 NULL이다.
--   6. 표 설명의 저장 주체를 고친다. 권한은 afterMigrate.sql이 마이그레이션마다 다시 준다.


-- 1. 시연용 보고서 (그래프는 V01 행동 이상 추이 · V06 취약성 요인 · V03 시간대 활동)
INSERT INTO region_insight_report
    (period_start, adm_cd10, quick_insight, graph_1, desc_1, graph_2, desc_2, graph_3, desc_3,
     result_updated_at, generated_at)
SELECT r.period_start, r.adm_cd10,
       format(E'[시연용 예시] %s %s의 %s 종합 위험은 %s단계(5단계가 가장 높음)입니다.\n'
              '배경 취약성 %s단계, 행동 이상 %s단계입니다. 실제 해석은 AI 보고서가 만들어지면 바뀝니다.',
              d.sgg_nm, d.adm_nm, to_char(r.period_start, 'YYYY-MM'), r.risk_grade, r.bg_grade, r.bh_grade),
       'EmbedDetailV01',
       format('[시연용 예시] %s의 행동 이상 점수 월별 추이입니다. 기준 월 행동 이상 점수는 %s(%s단계)입니다.',
              d.adm_nm, r.bh_score, r.bh_grade),
       'EmbedDetailV06',
       format('[시연용 예시] 배경 취약성을 이루는 요인입니다. 기준 월 배경 취약성 점수는 %s(%s단계)입니다.',
              r.bg_score, r.bg_grade),
       'EmbedDetailV03',
       '[시연용 예시] 시간대별 활동입니다. 어느 시간대에 활동이 달라졌는지 함께 확인해 보세요.',
       r.updated_at, now()
FROM region_result r
JOIN dim_region d ON d.adm_cd10 = r.adm_cd10
ON CONFLICT (period_start, adm_cd10) DO UPDATE
   SET quick_insight = EXCLUDED.quick_insight,
       graph_1 = EXCLUDED.graph_1, desc_1 = EXCLUDED.desc_1,
       graph_2 = EXCLUDED.graph_2, desc_2 = EXCLUDED.desc_2,
       graph_3 = EXCLUDED.graph_3, desc_3 = EXCLUDED.desc_3,
       result_updated_at = EXCLUDED.result_updated_at,
       generated_at = EXCLUDED.generated_at
 WHERE region_insight_report.quick_insight IS NULL
    OR region_insight_report.result_updated_at IS DISTINCT FROM EXCLUDED.result_updated_at;


-- 2. 예전 형식만 있는 행은 새 칸으로 옮길 수 없다 (JSON 보고서 → 그래프 3칸 변환 규칙 없음)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM region_insight_report WHERE quick_insight IS NULL) THEN
        RAISE EXCEPTION '예전 형식(summary_lines · report)만 있는 인사이트 보고서가 있어 컬럼을 지울 수 없습니다. 그 동·월 보고서를 새 형식으로 다시 만들거나 지운 뒤 다시 실행하세요.';
    END IF;
END $$;


-- 3. 뷰를 먼저 지운다
DROP VIEW v_region_insight;


-- 4. 예전 형식 칸 · CHECK 삭제, 새 8칸 NOT NULL
ALTER TABLE region_insight_report
    DROP CONSTRAINT ck_region_insight_report_format,
    DROP CONSTRAINT ck_region_insight_report_summary,
    DROP CONSTRAINT ck_region_insight_report_report,
    DROP COLUMN summary_lines,
    DROP COLUMN report,
    ALTER COLUMN quick_insight     SET NOT NULL,
    ALTER COLUMN graph_1           SET NOT NULL,
    ALTER COLUMN desc_1            SET NOT NULL,
    ALTER COLUMN graph_2           SET NOT NULL,
    ALTER COLUMN desc_2            SET NOT NULL,
    ALTER COLUMN graph_3           SET NOT NULL,
    ALTER COLUMN desc_3            SET NOT NULL,
    ALTER COLUMN result_updated_at SET NOT NULL;


-- 5. 읍면동 화면 위쪽 (지역 이름, 점수·단계, 퀵 인사이트). 최신 보고서가 없으면 quick_insight · insight_generated_at이 NULL
CREATE VIEW v_region_insight AS
SELECT
    r.period_start,
    r.adm_cd10,
    d.adm_nm AS dong_name,
    left(r.adm_cd10, 5) AS sigungu_code,
    d.sgg_nm AS sigungu_name,
    r.bg_score,
    r.bg_grade,
    r.bh_score,
    r.bh_grade,
    r.risk_grade,
    i.quick_insight,
    i.generated_at AS insight_generated_at
FROM region_result r
JOIN dim_region d ON d.adm_cd10 = r.adm_cd10
LEFT JOIN region_insight_report i
       ON i.period_start = r.period_start AND i.adm_cd10 = r.adm_cd10
      AND i.result_updated_at = r.updated_at;


-- 6. 저장 주체 설명 (1단계 COMMENT는 '백엔드가 저장'으로 남아 있음)
COMMENT ON TABLE region_insight_report IS '읍면동 인사이트 보고서 (동·월마다 하나, AI가 만들어 eumi_ai 계정으로 직접 저장)';
