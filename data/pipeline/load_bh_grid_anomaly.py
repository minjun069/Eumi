"""모델 결과 적재 — 분석 재현 패키지의 grid_scores_monthly.csv.gz → analysis.bh_grid_anomaly.

패키지 격자(G100_ix_iy)의 중심 좌표에서 좌하단 좌표(gx = center_x − 50, gy = center_y − 50)를 구해 dim_grid100 의 grid_cd 를 붙인다.
좌하단 좌표가 100의 배수가 아니면 SGIS 격자와 어긋난 것이므로 적재하지 않는다 (DA 가 격자 원점을 SGIS 에 맞춰 재계산해야 함).
점수가 있는 행(8~12월)만 넣고, 결측(7월·부적격 격자)은 행을 넣지 않는다. UPSERT.
실행  data/.venv/Scripts/python data/pipeline/load_bh_grid_anomaly.py [--csv 경로] [--check-only]
"""
import argparse
from decimal import Decimal

import numpy as np
import pandas as pd

from common import RAW_DIR, check, db_connect, setup

DEFAULT_CSV = RAW_DIR / "model_package" / "dual_analysis_reproducible_20261102" / "data" / "grid_scores_monthly.csv.gz"
SQL = """
INSERT INTO analysis.bh_grid_anomaly (period_start, grid_cd, anomaly_score, updated_at)
VALUES (%(period_start)s, %(grid_cd)s, %(anomaly_score)s, now())
ON CONFLICT (period_start, grid_cd) DO UPDATE SET anomaly_score = EXCLUDED.anomaly_score, updated_at = now()
"""


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    df = pd.read_csv(args.csv, dtype={"region_code": str, "grid_id": str, "month": str},
                     usecols=["city", "region_code", "grid_id", "month", "center_x", "center_y", "behavior_anomaly_score", "anomaly_score_status"])
    print(f"패키지 격자 점수: {len(df):,}행, 격자 {df.grid_id.nunique():,}개, 점수 있는 행 {int(df.behavior_anomaly_score.notna().sum()):,}")
    gx, gy = df.center_x - 50, df.center_y - 50
    off_x, off_y = float(np.abs(gx % 100).max()), float(np.abs(gy % 100).max())
    aligned = off_x < 1e-6 and off_y < 1e-6
    ok = check("SGIS 격자 정렬 (좌하단 좌표가 100의 배수)", aligned,
               "정렬됨" if aligned else f"어긋남: x 나머지 최대 {off_x:.2f} m, y {off_y:.2f} m → DA 가 격자 원점을 SGIS 에 맞춰 재계산해야 함")
    if not aligned:
        print("LOAD_BH_GRID_ANOMALY FAIL (정렬 전 파일)")
        return 1
    df["gx"], df["gy"] = gx.round().astype(int), gy.round().astype(int)
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT grid_cd, gx, gy, adm_cd10 FROM analysis.dim_grid100")
            dim = pd.DataFrame(cur.fetchall(), columns=["grid_cd", "gx", "gy", "adm_cd10"])
        m = df.merge(dim, on=["gx", "gy"], how="left")
        unmapped = m[m.grid_cd.isna()]
        ok &= check("모든 격자가 dim_grid100 에 있음", unmapped.empty, f"없음 {unmapped.grid_id.nunique():,}개" if not unmapped.empty else f"{m.grid_cd.nunique():,}개 매핑")
        dong_mismatch = int((m.region_code != m.adm_cd10).sum())
        ok &= check("소속 동이 dim_grid100 과 일치", dong_mismatch == 0, f"불일치 {dong_mismatch:,}행")
        scored = m[m.behavior_anomaly_score.notna()]
        if args.check_only or not ok:
            conn.rollback()
            print("LOAD_BH_GRID_ANOMALY", "CHECK_ONLY" if ok else "FAIL")
            return 0 if ok else 1
        rows = [{"period_start": f"{r.month}-01", "grid_cd": r.grid_cd, "anomaly_score": Decimal(f"{r.behavior_anomaly_score:.2f}")} for r in scored.itertuples()]
        with conn.cursor() as cur:
            cur.executemany(SQL, rows)
            cur.execute("SELECT period_start, count(*) FROM analysis.bh_grid_anomaly GROUP BY 1 ORDER BY 1")
            by_month = cur.fetchall()
        conn.commit()
    ok &= check("bh_grid_anomaly 행 수", sum(n for _, n in by_month) == len(rows), str([(str(m)[:7], n) for m, n in by_month]))
    print("LOAD_BH_GRID_ANOMALY", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
