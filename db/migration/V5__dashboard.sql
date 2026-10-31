-- Eumi 위험 탐지 대시보드 (고립 위험 탐색) — public 스키마 / PostgreSQL 17
-- 2026-10-30 ERD 점검 결과
--   데이터 분석 정의: region_result (파이프라인이 적재)
--   직접 설계: region_insight_report (AI가 작성)
--   뷰: v_region_insight
--   V2(dim_region) 다음에 실행한다. analysis 스키마 테이블은 V6.
--
-- 스키마 규칙
--   * public  : 화면 API가 기대는 테이블. 구조 변경은 백엔드와 함께 정한다.
--   * analysis: 파이프라인·AI만 쓰는 테이블. 마이그레이션 파일은 데이터 분석 파트가 작성한다 (V6~).
--   * 스키마가 달라도 FK는 그대로 건다. 이후 추가 마이그레이션은 날짜 형식 버전(V20261101_01__...)으로 두 팀 번호가 겹치지 않게 한다.
--
-- 화면에서 고르는 지표 (시군구 지도 · Tableau ①②의 지표 매개변수)
--   * 배경 점수 = bg_score·bg_grade, 행동 점수 = bh_score·bh_grade, 종합 위험 단계 = risk_grade
--   * 읍면동 격자 지도(Tableau ⑥)는 analysis.bh_grid_anomaly.anomaly_score로 색을 칠한다 (수준 컬럼 없음)
--
-- 적재 규칙 (파이프라인)
--   * 결과가 없는 동은 행을 넣지 않는다 (점수·단계는 모두 NOT NULL).
--   * DROP·전체 TRUNCATE 금지 (Spark overwrite 기본 동작 포함). 그 달 행을 지운 뒤 append, 또는 UPSERT.
--   * 한 달을 지우면 그 달의 지표 기여도(analysis.bh_region_contribution)와 인사이트 보고서도 함께 지워진다.
--   * 적재를 마치면 FastAPI의 인사이트 보고서 생성을 내부 호출한다. 다시 적재한 달은 보고서도 다시 생성한다.
--   * updated_at은 데이터 분석 파트 규칙대로 TIMESTAMP(한국 시간).
--
-- 조회 (Spring)
--   * 적재된 월 목록  : SELECT DISTINCT period_start FROM region_result WHERE left(adm_cd10, 5) = :sigungu ORDER BY period_start
--   * 읍면동 인사이트 : SELECT * FROM v_region_insight WHERE adm_cd10 = :dong AND period_start = :month
--   * 인사이트 보고서 : SELECT report, generated_at FROM region_insight_report WHERE adm_cd10 = :dong AND period_start = :month
--   * 보고서가 없으면(결과 적재 직후, 생성 실패) 화면은 "보고서 준비 중"을 보여준다.
--
-- 저장 (AI, 같은 동·월은 덮어씀)
--   INSERT INTO region_insight_report (period_start, adm_cd10, summary_lines, report, generated_at)
--   VALUES (:month, :dong, :summary_lines, :report, now())
--   ON CONFLICT (period_start, adm_cd10) DO UPDATE
--     SET summary_lines = EXCLUDED.summary_lines, report = EXCLUDED.report, generated_at = EXCLUDED.generated_at;


-- 읍면동 월별 결과 (데이터 분석 정의, 파이프라인이 적재)
CREATE TABLE region_result (
    period_start  DATE          NOT NULL,
    adm_cd10      VARCHAR(10)   NOT NULL,
    bg_score      DECIMAL(7,2)  NOT NULL,
    bg_grade      SMALLINT      NOT NULL,
    bh_score      DECIMAL(7,2)  NOT NULL,
    bh_grade      SMALLINT      NOT NULL,
    risk_grade    SMALLINT      NOT NULL,
    updated_at    TIMESTAMP     NOT NULL DEFAULT now(),
    CONSTRAINT pk_region_result PRIMARY KEY (period_start, adm_cd10),
    CONSTRAINT fk_region_result_region FOREIGN KEY (adm_cd10) REFERENCES dim_region (adm_cd10),
    -- 기준월은 그 달 1일
    CONSTRAINT ck_region_result_month CHECK (period_start = date_trunc('month', period_start)::date),
    -- 단계는 1~5, 5가 가장 위험
    CONSTRAINT ck_region_result_grades CHECK (
        bg_grade BETWEEN 1 AND 5 AND bh_grade BETWEEN 1 AND 5 AND risk_grade BETWEEN 1 AND 5
    )
);


-- 읍면동 인사이트 보고서 (동·월마다 하나, AI가 결과 적재 후 생성)
--   summary_lines: 동 화면 퀵 인사이트 문장 목록
--   report       : {headline, sections:[{question, blocks:[{kind: paragraph | bullets | chart, ...}]}]}
--                  그래프 값까지 담은 스냅샷. 섹션·블록·그래프 개수와 종류가 바뀌어도 DB는 그대로다.
CREATE TABLE region_insight_report (
    period_start   DATE         NOT NULL,
    adm_cd10       VARCHAR(10)  NOT NULL,
    summary_lines  TEXT[]       NOT NULL,
    report         JSONB        NOT NULL,
    generated_at   TIMESTAMPTZ  NOT NULL,
    CONSTRAINT pk_region_insight_report PRIMARY KEY (period_start, adm_cd10),
    -- 결과가 적재된 동·월에만 보고서를 쓸 수 있다
    CONSTRAINT fk_region_insight_report_result FOREIGN KEY (period_start, adm_cd10)
        REFERENCES region_result (period_start, adm_cd10) ON DELETE CASCADE,
    CONSTRAINT ck_region_insight_report_summary CHECK (cardinality(summary_lines) >= 1),
    CONSTRAINT ck_region_insight_report_report CHECK (jsonb_typeof(report) = 'object')
);


-- 읍면동 화면 위쪽 (지역 이름, 점수·단계, 퀵 인사이트). 보고서가 없으면 summary_lines가 NULL
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
    i.summary_lines,
    i.generated_at AS insight_generated_at
FROM region_result r
JOIN dim_region d ON d.adm_cd10 = r.adm_cd10
LEFT JOIN region_insight_report i
       ON i.period_start = r.period_start AND i.adm_cd10 = r.adm_cd10;


-- 논리명 · 규칙
COMMENT ON TABLE  region_result IS '읍면동 월별 결과 (데이터 분석 정의, 파이프라인 적재)';
COMMENT ON COLUMN region_result.period_start IS '기준월 (그 달 1일)';
COMMENT ON COLUMN region_result.adm_cd10 IS '행정동코드';
COMMENT ON COLUMN region_result.bg_score IS '배경 취약성 점수';
COMMENT ON COLUMN region_result.bg_grade IS '배경 도시 내 등급 (시군구 안 1~5, 5가 가장 위험)';
COMMENT ON COLUMN region_result.bh_score IS '행동 이상 점수';
COMMENT ON COLUMN region_result.bh_grade IS '행동 도시 내 등급 (시군구 안 1~5, 5가 가장 위험)';
COMMENT ON COLUMN region_result.risk_grade IS '위험단계 등급 (종합 위험 단계 1~5, 산정 규칙은 데이터 분석 파트 문서)';
COMMENT ON COLUMN region_result.updated_at IS '수정 시각';

COMMENT ON TABLE  region_insight_report IS '읍면동 인사이트 보고서 (AI 생성, 동·월마다 하나)';
COMMENT ON COLUMN region_insight_report.period_start IS '기준월';
COMMENT ON COLUMN region_insight_report.adm_cd10 IS '행정동코드';
COMMENT ON COLUMN region_insight_report.summary_lines IS '퀵 인사이트 문장 목록';
COMMENT ON COLUMN region_insight_report.report IS '인사이트 보고서 (제목 문장, 질문별 내용 블록, 그래프 값 포함)';
COMMENT ON COLUMN region_insight_report.generated_at IS 'AI 생성 일시';
