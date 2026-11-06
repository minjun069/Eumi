-- 배경 상세(analysis.bg_region_detail) 값 자릿수 확대 / PostgreSQL 17
-- 2026-11-02 데이터 파이프라인 파트 (analysis 스키마)
--   value 가 DECIMAL(14,2) 라 동 면적(area_km2, 예 1.740451 ㎢)이 1.74 로 잘려 저장됐고,
--   2차 배치가 이 값으로 공원 면적 비율·정류장 밀도를 다시 계산하면 1차 완성본과 둘째 자리에서 어긋난다.
--   정수 항목(인구·가구·주택·공원 ㎡·정류장 수)은 영향 없음. 기존 행은 값 그대로 유지되고 소수 4자리가 0으로 채워진다.
--   적용 후 batch_bg_detail.py 를 다시 돌려 면적을 6자리로 적재한다.

ALTER TABLE analysis.bg_region_detail
    ALTER COLUMN value TYPE NUMERIC(18, 6);

COMMENT ON COLUMN analysis.bg_region_detail.value IS '값 (명 · 가구 · 호 · ㎡ · 개 · ㎢, 소수 6자리)';
