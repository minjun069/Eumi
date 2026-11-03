"""2차 M4-3 (격자) — bh_grid_indicator → analysis.bh_grid_anomaly 월 배치.

격자 행동 지표 10개 → 격자의 소속 동(dim_grid100 → dim_region.sgg_nm)으로 도시를 정해 도시별 격자 IsolationForest → anomaly_score (= -score_samples × 100).
지표가 하나라도 NULL 인 격자(첫 달, 분모 0, 저장 범위 초과)는 점수를 내지 않고 행도 넣지 않는다. 그 달 행을 지운 뒤 다시 넣는다.
모델은 m4_models.py (MinIO raw/model/<MODEL_VERSION>/). 등급은 없고 점수만 둔다(DA 와 같음).

실행  data/.venv/Scripts/python data/pipeline/batch_grid_anomaly.py [--months 2025-08 …] [--dry-run]
"""
import argparse
from decimal import Decimal

import numpy as np
import pandas as pd

from apt_api import months_arg
from common import check, db_connect, setup
from m4_models import ModelAssets


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", help="기준월 YYYY-MM 목록 (없으면 전월)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    assets = ModelAssets()
    feats = assets.grid_features
    print(f"[m4-grid] 모델 자산 {assets.version} (격자 지표 {len(feats)}개)", flush=True)
    ok = True
    with db_connect() as conn:
        for ym in months_arg(args.months):
            m = f"{ym[:4]}-{ym[4:]}"
            df = pd.read_sql("SELECT g.grid_cd, r.sgg_nm AS city, " + ", ".join(f"i.{c}" for c in feats) +
                             " FROM analysis.bh_grid_indicator i JOIN analysis.dim_grid100 g ON g.grid_cd = i.grid_cd"
                             " JOIN public.dim_region r ON r.adm_cd10 = g.adm_cd10 WHERE i.period_start = %s", conn, params=(f"{m}-01",))
            if df.empty:
                print(f"[m4-grid] {m}: bh_grid_indicator 없음, 건너뜀", flush=True)
                continue
            for c in feats:
                df[c] = df[c].astype(float)
            df["score"] = np.nan
            for city in df.city.unique():
                mask = df.city.eq(city)
                df.loc[mask, "score"] = assets.anomaly_score("grid", city, df.loc[mask])
            scored = df[df.score.notna()]
            old = pd.read_sql("SELECT grid_cd, anomaly_score FROM analysis.bh_grid_anomaly WHERE period_start = %s", conn, params=(f"{m}-01",)).set_index("grid_cd").anomaly_score.astype(float)
            cmp = ""
            if len(old):
                both = scored.set_index("grid_cd").score.to_frame("new").join(old.rename("old"), how="inner")
                cmp = f" | 기존 {len(old):,}행과 공통 {len(both):,}: 점수 상관 {both.new.corr(both.old):.4f}, 최대차 {np.abs(both.new - both.old).max():.2f}"
            by_city = scored.groupby("city").score.agg(["size", "mean"]).round(2).to_dict("index")
            print(f"[m4-grid] {m}: 격자 {len(df):,} (점수 {len(scored):,}, 지표 NULL 제외 {len(df) - len(scored):,}) | 도시별 {by_city}{cmp}", flush=True)
            ok &= check(f"{m} 점수 범위 (DECIMAL(7,2))", scored.score.abs().lt(1e5).all(), f"{scored.score.min():.2f} ~ {scored.score.max():.2f}")
            if args.dry_run or scored.empty:
                continue
            rows = [(f"{m}-01", g, Decimal(f"{s:.2f}")) for g, s in zip(scored.grid_cd, scored.score)]
            with conn.cursor() as cur:
                cur.execute("DELETE FROM analysis.bh_grid_anomaly WHERE period_start = %s", (f"{m}-01",))
                cur.executemany("INSERT INTO analysis.bh_grid_anomaly (period_start, grid_cd, anomaly_score, updated_at) VALUES (%s, %s, %s, now())", rows)
            conn.commit()
            print(f"[m4-grid] {m}: bh_grid_anomaly {len(rows):,}행 적재", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
