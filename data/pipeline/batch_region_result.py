"""2차 M4 (읍면동) — bg_region_indicator + bh_region_indicator → public.region_result 월 배치.

  M4-2 배경 취약성 점수: 배경 지표 6개 → 고정 PCA 계수 → bg_score, 고정 임계값(도시별 P20·P80) → bg_grade 1~3
  M4-3 행동 이상 점수:   행동 지표 12개 → 도시별 IsolationForest → bh_score (지표가 하나라도 NULL 이면 점수 없음)
  M4-4 위험단계 판정:   그 달 · 도시 안 bh_score 의 P20·P80 → bh_grade 1~3, risk_grade = bg_grade + bh_grade − 1 (1~5)
행동 점수가 없는 동(첫 달처럼 변화 지표 4개가 NULL)은 행을 넣지 않는다 (region_result 의 bh_score · risk_grade 가 NOT NULL, DA 와 같은 방침).
UPSERT 만 한다 — DELETE 는 region_insight_report · bh_region_contribution 이 CASCADE 로 지워지므로 하지 않는다.
모델·계수는 m4_models.py (MinIO raw/model/<MODEL_VERSION>/).

실행  data/.venv/Scripts/python data/pipeline/batch_region_result.py [--months 2025-08 …] [--dry-run]
  --dry-run: DB 에 쓰지 않고 기존 region_result 와 점수 · 등급 차이만 출력
"""
import argparse
import datetime as dt
from decimal import Decimal

import numpy as np
import pandas as pd

from common import check, db_connect, setup
from m4_models import BAND_RANK, BG_COLS, ModelAssets, behavior_bands
from apt_api import months_arg


def score_month(conn, assets: ModelAssets, m: str) -> pd.DataFrame:
    feats = assets.dong_features
    sql = ("SELECT r.adm_cd10, r.sgg_nm AS city, " + ", ".join(f"b.{c}" for c in BG_COLS) + ", " + ", ".join(f"h.{c}" for c in feats) +
           " FROM public.dim_region r JOIN analysis.bg_region_indicator b ON b.adm_cd10 = r.adm_cd10 AND b.period_start = %s"
           " LEFT JOIN analysis.bh_region_indicator h ON h.adm_cd10 = r.adm_cd10 AND h.period_start = %s ORDER BY r.adm_cd10")
    df = pd.read_sql(sql, conn, params=(f"{m}-01", f"{m}-01"))
    if df.empty:
        return df
    for c in list(BG_COLS) + feats:
        df[c] = df[c].astype(float)
    # M4-2
    df["bg_score"], _ = assets.background_score(df)
    df["bg_band"] = [assets.background_band(c, s) for c, s in zip(df.city, df.bg_score)]
    # M4-3
    df["bh_score"] = np.nan
    for city in df.city.unique():
        mask = df.city.eq(city)
        df.loc[mask, "bh_score"] = assets.anomaly_score("dong", city, df.loc[mask])
    # M4-4
    df["bh_band"], df["bh_p20"], df["bh_p80"] = None, np.nan, np.nan
    for city in df.city.unique():
        mask = df.city.eq(city) & df.bh_score.notna()
        if mask.any():
            bands, p20, p80 = behavior_bands(df.loc[mask, "bh_score"])
            df.loc[mask, "bh_band"], df.loc[mask, "bh_p20"], df.loc[mask, "bh_p80"] = bands, p20, p80
    df["bg_grade"] = df.bg_band.map(BAND_RANK)
    df["bh_grade"] = df.bh_band.map(BAND_RANK)
    df["risk_grade"] = df.bg_grade + df.bh_grade - 1
    return df


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", help="기준월 YYYY-MM 목록 (없으면 전월)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    assets = ModelAssets()
    print(f"[m4-region] 모델 자산 {assets.version} (읍면동 지표 {len(assets.dong_features)}개)", flush=True)
    ok = True
    with db_connect() as conn:
        for ym in months_arg(args.months):
            m = f"{ym[:4]}-{ym[4:]}"
            df = score_month(conn, assets, m)
            if df.empty:
                print(f"[m4-region] {m}: bg_region_indicator 없음, 건너뜀", flush=True)
                continue
            scored = df[df.bh_score.notna()].copy()
            unscored = df[df.bh_score.isna()]
            old = pd.read_sql("SELECT adm_cd10, bg_score, bg_grade, bh_score, bh_grade, risk_grade FROM public.region_result WHERE period_start = %s",
                              conn, params=(f"{m}-01",)).set_index("adm_cd10").astype(float).reindex(scored.adm_cd10)
            cmp = ""
            if old.bg_score.notna().any():
                cmp = (f" | 기존 대비: bg_score 최대차 {np.nanmax(np.abs(old.bg_score.to_numpy() - scored.bg_score.to_numpy())):.2f}, "
                       f"bh_score 최대차 {np.nanmax(np.abs(old.bh_score.to_numpy() - scored.bh_score.to_numpy())):.2f}, "
                       f"bg_grade 변경 {int((old.bg_grade.to_numpy() != scored.bg_grade.to_numpy()).sum())}, "
                       f"bh_grade 변경 {int((old.bh_grade.to_numpy() != scored.bh_grade.to_numpy()).sum())}, "
                       f"risk_grade 변경 {int((old.risk_grade.to_numpy() != scored.risk_grade.to_numpy()).sum())}")
            stages = scored.groupby(["city", "risk_grade"]).size().unstack(fill_value=0).to_dict("index")
            print(f"[m4-region] {m}: 동 {len(df)} (점수 {len(scored)}, 행동 지표 NULL 로 제외 {len(unscored)}) | 단계 분포 {stages}{cmp}", flush=True)
            ok &= check(f"{m} 등급 범위", scored.bg_grade.between(1, 3).all() and scored.bh_grade.between(1, 3).all() and scored.risk_grade.between(1, 5).all(), "")
            if args.dry_run or scored.empty:
                continue
            rows = [{"period_start": f"{m}-01", "adm_cd10": r.adm_cd10, "bg_score": Decimal(f"{r.bg_score:.2f}"), "bg_grade": int(r.bg_grade),
                     "bh_score": Decimal(f"{r.bh_score:.2f}"), "bh_grade": int(r.bh_grade), "risk_grade": int(r.risk_grade)} for r in scored.itertuples()]
            with conn.cursor() as cur:
                cur.executemany("""INSERT INTO public.region_result (period_start, adm_cd10, bg_score, bg_grade, bh_score, bh_grade, risk_grade, updated_at)
                    VALUES (%(period_start)s, %(adm_cd10)s, %(bg_score)s, %(bg_grade)s, %(bh_score)s, %(bh_grade)s, %(risk_grade)s, now())
                    ON CONFLICT (period_start, adm_cd10) DO UPDATE SET bg_score = EXCLUDED.bg_score, bg_grade = EXCLUDED.bg_grade,
                    bh_score = EXCLUDED.bh_score, bh_grade = EXCLUDED.bh_grade, risk_grade = EXCLUDED.risk_grade, updated_at = now()""", rows)
            conn.commit()
            print(f"[m4-region] {m}: region_result {len(rows)}행 UPSERT", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
