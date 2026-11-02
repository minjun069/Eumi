"""모델 결과 적재 — 분석 재현 패키지의 dong_priority_monthly.csv → public.region_result.

열 대응: vulnerability_score → bg_score, background_band(낮음·중간·높음) → bg_grade 1·2·3, behavior_anomaly_score → bh_score,
         behavior_band → bh_grade 1·2·3, priority_stage(1~5) → risk_grade. 등급 방향은 인수인계 기준(3 = 높음, 5 = 최우선)과 같다.
7월은 전월이 없어 B·단계가 결측이라 넣지 않는다 (region_result 의 bh_score·risk_grade 는 NOT NULL). 8~12월 235행.
UPSERT 라 다시 실행해도 안전하다. 행을 지우면 인사이트 보고서·기여도가 CASCADE 로 지워지므로 DELETE 는 하지 않는다.
실행  data/.venv/Scripts/python data/pipeline/load_region_result.py [--csv 경로]
"""
import argparse
from decimal import Decimal

import pandas as pd

from common import RAW_DIR, check, db_connect, setup

DEFAULT_CSV = RAW_DIR / "model_package" / "dual_analysis_reproducible_20261102" / "data" / "dong_priority_monthly.csv"
BAND = {"낮음": 1, "중간": 2, "높음": 3}
SQL = """
INSERT INTO public.region_result (period_start, adm_cd10, bg_score, bg_grade, bh_score, bh_grade, risk_grade, updated_at)
VALUES (%(period_start)s, %(adm_cd10)s, %(bg_score)s, %(bg_grade)s, %(bh_score)s, %(bh_grade)s, %(risk_grade)s, now())
ON CONFLICT (period_start, adm_cd10) DO UPDATE SET
    bg_score = EXCLUDED.bg_score, bg_grade = EXCLUDED.bg_grade, bh_score = EXCLUDED.bh_score,
    bh_grade = EXCLUDED.bh_grade, risk_grade = EXCLUDED.risk_grade, updated_at = now()
"""


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    args = ap.parse_args()
    df = pd.read_csv(args.csv, encoding="utf-8-sig", dtype={"region_code": str, "month": str})
    ok = check("패키지 결과 행 수", len(df) == 282 and df.region_code.nunique() == 47, f"{len(df)}행, 동 {df.region_code.nunique()}")
    scored = df[df.priority_stage.notna()].copy()
    skipped = df[df.priority_stage.isna()]
    ok &= check("단계 있는 행 = 8~12월 235", len(scored) == 235 and set(scored.month) == {"2025-08", "2025-09", "2025-10", "2025-11", "2025-12"},
                f"{len(scored)}행 / 제외 {len(skipped)}행 ({', '.join(sorted(skipped.month.unique()))}: {skipped.priority_status.unique().tolist()})")
    ok &= check("밴드 값", set(scored.background_band) | set(scored.behavior_band) <= set(BAND), str(set(scored.background_band) | set(scored.behavior_band)))
    ok &= check("단계 = S등급 + B등급 − 1", (scored.priority_stage == scored.background_band.map(BAND) + scored.behavior_band.map(BAND) - 1).all(), "")
    ok &= check("점수 결측 없음", scored[["vulnerability_score", "behavior_anomaly_score"]].notna().all().all(), "")
    if not ok:
        return 1
    rows = [{"period_start": f"{r.month}-01", "adm_cd10": r.region_code, "bg_score": Decimal(f"{r.vulnerability_score:.2f}"),
             "bg_grade": BAND[r.background_band], "bh_score": Decimal(f"{r.behavior_anomaly_score:.2f}"),
             "bh_grade": BAND[r.behavior_band], "risk_grade": int(r.priority_stage)} for r in scored.itertuples()]
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT adm_cd10 FROM public.dim_region")
            known = {r[0] for r in cur.fetchall()}
            missing = sorted(set(scored.region_code) - known)
            ok &= check("adm_cd10 이 dim_region 에 있음", not missing, f"missing={missing}" if missing else "47개")
            if not ok:
                conn.rollback()
                return 1
            cur.executemany(SQL, rows)
            cur.execute("SELECT period_start, count(*), count(*) FILTER (WHERE risk_grade >= 4) FROM public.region_result GROUP BY 1 ORDER BY 1")
            by_month = cur.fetchall()
            cur.execute("SELECT count(*) FROM public.region_result")
            total = cur.fetchone()[0]
            cur.execute("SELECT r.adm_nm, x.period_start, x.bg_score, x.bg_grade, x.bh_score, x.bh_grade, x.risk_grade FROM public.region_result x JOIN public.dim_region r USING (adm_cd10) WHERE r.adm_nm = '개포1동' ORDER BY 2")
            sample = cur.fetchall()
        conn.commit()
    ok &= check("region_result 행 수", total == 235, f"{total} (월별 행 수, 4·5단계 수: {[(str(m), n, p) for m, n, p in by_month]})")
    exp_priority = scored.groupby("month").apply(lambda d: int((d.priority_stage >= 4).sum())).to_dict()
    ok &= check("월별 4·5단계 수 = 패키지", {str(m)[:7]: p for m, _, p in by_month} == exp_priority, str(exp_priority))
    print("개포1동:", sample)
    print("LOAD_REGION_RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
