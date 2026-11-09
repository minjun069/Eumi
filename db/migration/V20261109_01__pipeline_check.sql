-- 파이프라인 검사 결과 기록: 월 배치 마지막 단계(ops/verify_outputs.py)가 검사마다 한 행을 남긴다 / PostgreSQL 17
-- 2026-11-09 파이프라인 모니터링(Grafana) 작업 ('Eumi ERD 변경 기록' > 데이터 파이프라인 > 11/9 검사 결과 기록)
--   * 지금까지 검사 결과는 Airflow 로그에만 남아 "이번 달 검사를 통과했나"를 DB에서 볼 수 없었다.
--     Grafana 대시보드 · 알림이 이 표를 읽는다 (Airflow 실행 이력은 "돌았나", 이 표는 "결과가 계약대로인가").
--   * 기준월 · 검사 이름마다 한 행 (달마다 11개). 같은 달을 다시 돌리면 그 달 행을 지우고 다시 넣어 마지막 실행 결과만 남긴다.
--   * seq: 검사 순서 (화면에서 파이프라인 순서대로 보이게). detail: 로그의 [OK]/[FAIL] 뒤에 찍던 수치 그대로.
--   * 화면 · AI는 쓰지 않는다. 권한은 afterMigrate의 analysis 전체 규칙을 그대로 따른다 (파이프라인 읽기·쓰기, AI · Grafana 읽기).
CREATE TABLE analysis.pipeline_check (
    period_start  DATE          NOT NULL,
    check_name    VARCHAR(60)   NOT NULL,
    seq           SMALLINT      NOT NULL,
    passed        BOOLEAN       NOT NULL,
    detail        TEXT,
    checked_at    TIMESTAMP     NOT NULL DEFAULT now(),
    CONSTRAINT pk_pipeline_check PRIMARY KEY (period_start, check_name),
    CONSTRAINT ck_pipeline_check_month CHECK (period_start = date_trunc('month', period_start)::date)
);
