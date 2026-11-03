"""[M2 유동 상세 검증 | Spark 컨테이너] 검증 — flow_detail 의 일평균(flow_sum/day_count) 이 anchor(h · w×k_wkdy · a×k_age) 와 같은지 (상대오차 1e-5, 인수인계 5.2).

실행 (infra/):  docker compose --profile data exec pipeline spark-submit pipeline/m2_process/verify_flow_detail.py --months 2025-07
"""
import argparse
import os

import numpy as np
import pandas as pd
import psycopg
from pyspark.sql import SparkSession

BUCKET = os.environ["MINIO_BUCKET"]
RTOL, ATOL = 1e-5, 1e-4
H = [f"h_{i:02d}" for i in range(24)]
W = ["w_mon", "w_tue", "w_wed", "w_thu", "w_fri", "w_sat", "w_sun"]
A = ["a_m_10", "a_m_20", "a_m_30", "a_m_40", "a_m_50", "a_m_60p", "a_f_10", "a_f_20", "a_f_30", "a_f_40", "a_f_50", "a_f_60p"]
DIM = {"hour": [f"{i:02d}" for i in range(24)], "weekday": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
       "sex_age": ["M_10", "M_20", "M_30", "M_40", "M_50", "M_60P", "F_10", "F_20", "F_30", "F_40", "F_50", "F_60P"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="+", required=True)
    args = ap.parse_args()
    spark = SparkSession.builder.appName("verify_flow_detail").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    allok = True
    for m in args.months:
        anc = spark.read.parquet(f"s3a://{BUCKET}/synth/anchor/period={m}.parquet").toPandas().set_index("grid_cd")
        with psycopg.connect(os.environ["PIPELINE_DB_DSN"]) as conn:
            fd = pd.read_sql("SELECT grid_cd, dim_type, dim_value, flow_sum, day_count FROM analysis.flow_detail WHERE period_start = %s", conn, params=(f"{m}-01",))
        fd["mean"] = fd["flow_sum"].astype(float) / fd["day_count"]
        ok = True
        print(f"[verify] {m}: anchor 격자 {len(anc):,} | flow_detail 행 {len(fd):,} (격자 {fd.grid_cd.nunique():,})")
        for dim, cols, factor in (("hour", H, None), ("weekday", W, "k_wkdy"), ("sex_age", A, "k_age")):
            got = fd[fd.dim_type == dim].pivot(index="grid_cd", columns="dim_value", values="mean").reindex(index=anc.index, columns=DIM[dim])
            want = anc[cols].to_numpy(float) * (anc[factor].to_numpy(float)[:, None] if factor else 1.0)
            g = got.to_numpy(float)
            missing = int(np.isnan(g).sum())
            d = np.abs(np.nan_to_num(g) - want)
            big = want >= 0.01
            rel = np.where(big, d / np.maximum(want, 1e-12), 0).max()
            ab = np.where(~big, d, 0).max()
            dc = fd[fd.dim_type == dim].groupby("dim_value")["day_count"].agg(["min", "max"])
            # flow_sum 은 DECIMAL(16,4) 라 합계가 소수 4자리로 반올림된다 → 일평균 오차 한계 0.00005 / day_count 를 허용에 더한다
            round_tol = 0.5e-4 / max(int(dc["min"].min()), 1)
            within = (d <= RTOL * want + round_tol + np.where(big, 0, ATOL)).all()
            passed = missing == 0 and within
            ok &= passed
            print(f"  {dim:8s}: 빈 칸 {missing} | 최대 상대오차 {rel:.1e} (허용 {RTOL} + 반올림 한계 {round_tol:.1e}/값) | 최대 절대오차(입력<0.01) {ab:.1e} | day_count {dc['min'].min()}~{dc['max'].max()} → {'OK' if passed else 'FAIL'}")
        allok &= ok
    print("VERIFY_FLOW_DETAIL", "PASS" if allok else "FAIL")
    spark.stop()
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
