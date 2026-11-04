"""[M4-3 읍면동 행동 지표 기여도 | 호스트] bh_region_indicator + region_result → analysis.bh_region_contribution 월 배치.

정의  지표 j 의 기여도 = B(동의 지표 12개) − B(지표 j 만 같은 도시 · 같은 달 동들의 중앙값으로 바꾼 12개)
      B 는 행동 이상 점수 (region_result.bh_score 와 같은 모델 · 산식, −score_samples × 100). 단위는 점수.
      + 면 그 지표가 보통 동보다 튀어서 점수를 올렸다는 뜻, − 면 오히려 낮췄다는 뜻. 지표 간 상호작용은 반영하지 않아
      12개의 합이 점수 차와 정확히 같지는 않다 (상위 요인을 고르는 용도).
대상  region_result 가 있는 동 · 달만 (첫 달은 결과가 없어 기여도도 없다). 한 달에 동 47 × 지표 12 = 564행.
적재  그 달 행을 지운 뒤 넣는다. indicator_cd = bh_region_indicator 컬럼명 (V6 정의), 한글 이름은 common.bh_indicators.LABELS.
실행  python3 pipeline/m4_analysis/batch_bh_contribution.py [--months 2025-12 …] [--dry-run]
      --dry-run: DB 에 쓰지 않고 위험단계 4~5 동의 상위 요인 3개를 출력
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
from decimal import Decimal

import numpy as np
import pandas as pd

from common import check, db_connect, months_arg, setup
from common.bh_indicators import LABELS
from common.m4_models import ModelAssets


def contributions(conn, assets: ModelAssets, m: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(동별 정보, 기여도 long 표). 그 달 결과가 없으면 빈 표."""
    feats = assets.dong_features
    df = pd.read_sql("SELECT r.adm_cd10, d.sgg_nm AS city, d.adm_nm, r.bh_score, r.risk_grade, " + ", ".join(f"h.{c}" for c in feats) +
                     " FROM public.region_result r JOIN analysis.bh_region_indicator h ON h.adm_cd10 = r.adm_cd10 AND h.period_start = r.period_start"
                     " JOIN public.dim_region d ON d.adm_cd10 = r.adm_cd10 WHERE r.period_start = %s ORDER BY r.adm_cd10",
                     conn, params=(f"{m}-01",))
    if df.empty:
        return df, pd.DataFrame(columns=["adm_cd10", "indicator_cd", "contribution"])
    for c in feats + ["bh_score"]:
        df[c] = df[c].astype(float)
    df["bh_calc"] = np.nan
    rows = []
    for city, g in df.groupby("city"):
        base = assets.anomaly_score("dong", city, g)
        df.loc[g.index, "bh_calc"] = base
        median = g[feats].median()
        for c in feats:
            alt = g.copy()
            alt[c] = median[c]
            delta = base - assets.anomaly_score("dong", city, alt)
            rows += [(a, c, float(v)) for a, v in zip(g.adm_cd10, delta)]
    return df, pd.DataFrame(rows, columns=["adm_cd10", "indicator_cd", "contribution"])


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", help="기준월 YYYY-MM 목록 (없으면 전월)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    assets = ModelAssets()
    n_feat = len(assets.dong_features)
    ok = True
    with db_connect() as conn:
        for ym in months_arg(args.months):
            m = f"{ym[:4]}-{ym[4:]}"
            info, long = contributions(conn, assets, m)
            if info.empty:
                print(f"[bh-contrib] {m}: region_result 없음, 건너뜀", flush=True)
                continue
            diff = float(np.max(np.abs(info.bh_calc - info.bh_score)))
            ok &= check(f"{m} 기준 점수 = region_result.bh_score", diff <= 0.0051, f"최대차 {diff:.4f}")
            ok &= check(f"{m} 기여도 행 수", len(long) == len(info) * n_feat and np.isfinite(long.contribution).all(),
                        f"동 {len(info)} × 지표 {n_feat} = {len(long)}")
            pos = long.groupby("adm_cd10").contribution.max()
            print(f"[bh-contrib] {m}: 기여도 범위 {long.contribution.min():.2f} ~ {long.contribution.max():.2f}, "
                  f"양(+) 요인이 하나도 없는 동 {int((pos <= 0).sum())}", flush=True)
            if args.dry_run:
                top = info[info.risk_grade >= 4].sort_values(["city", "bh_score"], ascending=[True, False])
                for r in top.itertuples():
                    t = long[long.adm_cd10 == r.adm_cd10].nlargest(3, "contribution")
                    desc = ", ".join(f"{LABELS[x.indicator_cd][0]} {x.contribution:+.2f}" for x in t.itertuples())
                    print(f"   {r.city} {r.adm_nm} (단계 {r.risk_grade}, 행동 {r.bh_score:.2f}): {desc}", flush=True)
                continue
            rows = [(f"{m}-01", a, c, Decimal(f"{v:.6f}")) for a, c, v in long.itertuples(index=False)]
            with conn.cursor() as cur:
                cur.execute("DELETE FROM analysis.bh_region_contribution WHERE period_start = %s", (f"{m}-01",))
                cur.executemany("INSERT INTO analysis.bh_region_contribution (period_start, adm_cd10, indicator_cd, contribution, updated_at) "
                                "VALUES (%s, %s, %s, %s, now())", rows)
            conn.commit()
            print(f"[bh-contrib] {m}: bh_region_contribution {len(rows)}행 적재", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
