-- 인사이트 보고서 구조 변경 1단계: 그래프 3칸 고정 / PostgreSQL 17
-- 2026-11-06 AI 담당자 회의 결정 ('Eumi ERD 변경 기록' > 위험 탐지 대시보드 > 11/6 인사이트 보고서 구조 변경)
--   * 동·월마다 한 행. 퀵 인사이트 1개와 그래프 3개 · 그래프별 설명 3개를 칸으로 둔다 (그래프 수 3개 고정).
--   * 그래프 칸에는 AI가 고른 Tableau 시트 이름(EmbedDetailV01~EmbedDetailV08)을 그대로 넣는다.
--     화면은 이 이름으로 Tableau 그래프(views/<워크북>/<시트 이름>)를 임베딩한다.
--     DB는 주소에 넣을 수 있는 형식(영문으로 시작, 영문·숫자·밑줄)만 검사하고, 허용 시트 목록은 백엔드가 확인한다.
--     그래프가 늘어도 DB는 그대로다. 저장된 값이 곧 시트 이름이므로 Tableau 시트 이름은 바꾸지 않는다.
--   * 저장 주체가 AI에서 백엔드로 바뀐다. AI는 만든 보고서를 백엔드 API로 보내고, 백엔드가 저장한다.
--     흐름: 월 데이터 적재 → 데이터 분석 파이프라인(검증까지) → 백엔드 확인 → AI에 생성 요청 → AI가 백엔드 API로 전달 → 저장
--   * result_updated_at: 보고서를 만들 때 읽은 결과 행의 region_result.updated_at.
--     파이프라인이 결과 행을 다시 쓰면 updated_at이 바뀌므로, 값이 다른 보고서는 옛 결과로 만든 보고서다.
--     - 조회: 값이 같을 때만 보고서로 보여 준다 (아니면 "보고서 준비 중").
--     - 저장: AI가 보낸 값이 지금 결과 행과 다르면 저장하지 않는다 (늦게 도착한 이전 실행의 보고서).
--     - 데이터 분석 파트 약속: 결과 행을 다시 쓸 때마다 updated_at을 바꾼다 (지금 적재 코드는 now()로 바꾼다).
--
-- 두 단계로 바꾼다
--   1단계 (이 파일): 새 컬럼을 추가하고, 예전 컬럼(summary_lines, report)은 비워 둘 수 있게만 바꾼다.
--                    지금 백엔드 코드가 그대로 동작하므로 백엔드 변경보다 먼저 병합해도 된다.
--   2단계 (다음 파일): 백엔드가 새 컬럼을 쓰도록 바뀐 MR에서 예전 컬럼을 지우고 새 컬럼을 NOT NULL로 바꾼다.
--
-- 규칙
--   * 한 행은 새 형식 8칸이 모두 있거나, 8칸이 모두 비고 예전 형식(summary_lines · report)이 있어야 한다.
--   * 퀵 인사이트와 설명은 공백만으로 채울 수 없다. 그래프 칸은 시트 이름 형식, 3개가 서로 달라야 한다.
--   * 같은 동·월은 덮어쓴다. 결과(region_result)를 지우면 보고서도 함께 지워진다 (V5 FK 그대로).
--
-- 저장 (Spring). 결과 행의 updated_at이 AI가 보낸 값과 같을 때만 넣고, 같은 동·월은 덮어쓴다.
--   INSERT INTO region_insight_report
--       (period_start, adm_cd10, quick_insight, graph_1, desc_1, graph_2, desc_2, graph_3, desc_3,
--        result_updated_at, generated_at)
--   SELECT r.period_start, r.adm_cd10, :quick, :g1, :d1, :g2, :d2, :g3, :d3, r.updated_at, :generated_at
--   FROM region_result r
--   WHERE r.period_start = :month AND r.adm_cd10 = :dong AND r.updated_at = :result_updated_at
--   ON CONFLICT (period_start, adm_cd10) DO UPDATE
--     SET quick_insight = EXCLUDED.quick_insight,
--         graph_1 = EXCLUDED.graph_1, desc_1 = EXCLUDED.desc_1,
--         graph_2 = EXCLUDED.graph_2, desc_2 = EXCLUDED.desc_2,
--         graph_3 = EXCLUDED.graph_3, desc_3 = EXCLUDED.desc_3,
--         result_updated_at = EXCLUDED.result_updated_at,
--         generated_at = EXCLUDED.generated_at;
--   0행이면: 결과 행이 없으면 404, 있으면 옛 결과로 만든 보고서라 409.
--   예전 컬럼은 쓰지 않는다 (2단계에서 지워지므로 이 문장은 2단계 뒤에도 그대로 쓴다).
--
-- 조회 (Spring)
--   * 퀵 인사이트 : v_region_insight.quick_insight (최신 보고서가 없으면 NULL)
--   * 보고서      : region_result r LEFT JOIN region_insight_report i
--                     ON i.period_start = r.period_start AND i.adm_cd10 = r.adm_cd10
--                    AND i.result_updated_at = r.updated_at


ALTER TABLE region_insight_report
    ADD COLUMN quick_insight      TEXT,
    ADD COLUMN graph_1            VARCHAR(100),
    ADD COLUMN desc_1             TEXT,
    ADD COLUMN graph_2            VARCHAR(100),
    ADD COLUMN desc_2             TEXT,
    ADD COLUMN graph_3            VARCHAR(100),
    ADD COLUMN desc_3             TEXT,
    ADD COLUMN result_updated_at  TIMESTAMP,
    ALTER COLUMN summary_lines DROP NOT NULL,
    ALTER COLUMN report        DROP NOT NULL,
    -- 새 형식 8칸은 함께 채운다. 비어 있으면 예전 형식이 있어야 한다 (2단계에서 삭제)
    ADD CONSTRAINT ck_region_insight_report_format CHECK (
        num_nonnulls(quick_insight, graph_1, desc_1, graph_2, desc_2, graph_3, desc_3, result_updated_at) = 8
        OR (num_nonnulls(quick_insight, graph_1, desc_1, graph_2, desc_2, graph_3, desc_3, result_updated_at) = 0
            AND summary_lines IS NOT NULL AND report IS NOT NULL)
    ),
    -- 공백만 있는 퀵 인사이트 · 설명은 받지 않는다
    ADD CONSTRAINT ck_region_insight_report_text CHECK (
        quick_insight ~ '\S' AND desc_1 ~ '\S' AND desc_2 ~ '\S' AND desc_3 ~ '\S'
    ),
    -- 그래프 칸 형식: Tableau 시트 이름 (영문으로 시작, 영문·숫자·밑줄. 허용 목록은 백엔드)
    ADD CONSTRAINT ck_region_insight_report_sheets CHECK (
        graph_1 ~ '^[A-Za-z][A-Za-z0-9_]*$'
        AND graph_2 ~ '^[A-Za-z][A-Za-z0-9_]*$'
        AND graph_3 ~ '^[A-Za-z][A-Za-z0-9_]*$'
    ),
    -- 같은 그래프를 두 칸에 넣지 않는다
    ADD CONSTRAINT ck_region_insight_report_graphs CHECK (
        graph_1 <> graph_2 AND graph_1 <> graph_3 AND graph_2 <> graph_3
    );


-- 읍면동 화면 위쪽: 퀵 인사이트를 맨 뒤 컬럼으로 추가한다 (기존 컬럼은 그대로)
--   결과 행과 같은 updated_at으로 만든 보고서일 때만 값이 있고, 없거나 옛 보고서면 NULL
CREATE OR REPLACE VIEW v_region_insight AS
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
    i.summary_lines,
    i.generated_at AS insight_generated_at,
    CASE WHEN i.result_updated_at = r.updated_at THEN i.quick_insight END AS quick_insight
FROM region_result r
JOIN dim_region d ON d.adm_cd10 = r.adm_cd10
LEFT JOIN region_insight_report i
       ON i.period_start = r.period_start AND i.adm_cd10 = r.adm_cd10;


-- 논리명 · 규칙
COMMENT ON TABLE  region_insight_report IS '읍면동 인사이트 보고서 (동·월마다 하나, AI가 만들고 백엔드가 저장)';
COMMENT ON COLUMN region_insight_report.quick_insight IS '퀵 인사이트 (읍면동 화면 위쪽 위험 설명 2~3줄)';
COMMENT ON COLUMN region_insight_report.graph_1 IS '그래프 1 (AI가 고른 Tableau 시트 이름, 예: EmbedDetailV01)';
COMMENT ON COLUMN region_insight_report.desc_1 IS '그래프 1 설명';
COMMENT ON COLUMN region_insight_report.graph_2 IS '그래프 2 (AI가 고른 Tableau 시트 이름, 예: EmbedDetailV01)';
COMMENT ON COLUMN region_insight_report.desc_2 IS '그래프 2 설명';
COMMENT ON COLUMN region_insight_report.graph_3 IS '그래프 3 (AI가 고른 Tableau 시트 이름, 예: EmbedDetailV01)';
COMMENT ON COLUMN region_insight_report.desc_3 IS '그래프 3 설명';
COMMENT ON COLUMN region_insight_report.result_updated_at IS '기준 결과 수정 시각 (보고서를 만들 때 읽은 region_result.updated_at, 다르면 옛 보고서)';
COMMENT ON COLUMN region_insight_report.summary_lines IS '퀵 인사이트 문장 목록 (예전 형식, 2단계에서 삭제)';
COMMENT ON COLUMN region_insight_report.report IS '인사이트 보고서 JSON (예전 형식, 2단계에서 삭제)';
