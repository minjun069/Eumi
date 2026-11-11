-- 인사이트 보고서 일부 저장 허용 / PostgreSQL 17
-- 2026-11-11 결정: AI가 만든 보고서는 검토를 통과한 칸만 저장한다 (11/10의 "8칸이 모두 있을 때만 저장"을 바꿈).
--   AI 생성 품질 · 시간 문제로 일부 칸을 만들지 못해도, 만든 칸은 화면에 보여 준다.
--   계약: docs/api/insight-report.md 4 · 8절, openapi 2.6.0 API-12 (찬 칸만 칸 순서대로 0~3개, 설명 · 퀵 인사이트는 null 가능)
--
-- 바꾸는 것
--   1. quick_insight, graph_1~3, desc_1~3 의 NOT NULL을 푼다. result_updated_at(기준 결과 수정 시각)은 그대로 필수다.
--   2. 검사 2개를 더한다.
--      - 퀵 인사이트와 그래프 3개가 모두 비면 받지 않는다 (빈 보고서는 저장하지 않고 실패한 동으로 센다)
--      - 그래프 없이 설명만 있는 칸은 받지 않는다 (그래프만 있고 설명이 없는 칸은 받는다)
--   기존 검사(공백만 있는 글, 시트 이름 형식, 같은 그래프 중복)는 그대로 둔다. 빈 칸은 통과하고 값이 있는 칸끼리만 검사한다.
--   뷰 v_region_insight는 바꾸지 않는다 (quick_insight가 NULL이면 원래도 NULL로 보인다).

ALTER TABLE region_insight_report
    ALTER COLUMN quick_insight DROP NOT NULL,
    ALTER COLUMN graph_1       DROP NOT NULL,
    ALTER COLUMN desc_1        DROP NOT NULL,
    ALTER COLUMN graph_2       DROP NOT NULL,
    ALTER COLUMN desc_2        DROP NOT NULL,
    ALTER COLUMN graph_3       DROP NOT NULL,
    ALTER COLUMN desc_3        DROP NOT NULL,
    -- 퀵 인사이트와 그래프 중 하나는 있어야 한다
    ADD CONSTRAINT ck_region_insight_report_filled CHECK (
        num_nonnulls(quick_insight, graph_1, graph_2, graph_3) >= 1
    ),
    -- 설명은 그 칸의 그래프가 있을 때만 쓴다
    ADD CONSTRAINT ck_region_insight_report_desc CHECK (
        (desc_1 IS NULL OR graph_1 IS NOT NULL)
        AND (desc_2 IS NULL OR graph_2 IS NOT NULL)
        AND (desc_3 IS NULL OR graph_3 IS NOT NULL)
    );

COMMENT ON COLUMN region_insight_report.quick_insight IS '퀵 인사이트 (읍면동 화면 위쪽 위험 설명 2~3줄). AI 검토를 통과하지 못하면 NULL';
COMMENT ON COLUMN region_insight_report.graph_1 IS '그래프 1 (AI가 고른 Tableau 시트 이름, 예: EmbedDetailV01). 만들지 못하면 NULL';
COMMENT ON COLUMN region_insight_report.desc_1 IS '그래프 1 설명. 그래프 1이 있을 때만 쓰고, AI 검토를 통과하지 못하면 NULL';
COMMENT ON COLUMN region_insight_report.graph_2 IS '그래프 2 (AI가 고른 Tableau 시트 이름, 예: EmbedDetailV01). 만들지 못하면 NULL';
COMMENT ON COLUMN region_insight_report.desc_2 IS '그래프 2 설명. 그래프 2가 있을 때만 쓰고, AI 검토를 통과하지 못하면 NULL';
COMMENT ON COLUMN region_insight_report.graph_3 IS '그래프 3 (AI가 고른 Tableau 시트 이름, 예: EmbedDetailV01). 만들지 못하면 NULL';
COMMENT ON COLUMN region_insight_report.desc_3 IS '그래프 3 설명. 그래프 3이 있을 때만 쓰고, AI 검토를 통과하지 못하면 NULL';
