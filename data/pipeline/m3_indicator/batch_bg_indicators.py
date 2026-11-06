"""[M3-1 읍면동 배경 지표 | Spark 컨테이너] analysis.bg_region_detail → analysis.bg_region_indicator (비율 6개) 월 배치.

비율 (인수인계 5.1): 남성 = pop_male/pop_total, 1인가구 = hh_size_1/hh_total, 비아파트 = (house_total − house_apt)/house_total,
      65세+ = (pop_total − Σ 0~64세 구간)/pop_total, 공원 = park_area_m2/(area_km2 × 1e6), 정류장 밀도 = bus_stop_cnt/area_km2  (% 또는 개/㎢)
분모 0 또는 항목 결측이면 NULL (0 금지). UPSERT.
실행 (infra/):  docker compose --profile data exec pipeline python3 pipeline/m3_indicator/batch_bg_indicators.py --months 2025-07 ... [--dry-run]
"""
import argparse
import os
from decimal import Decimal

import numpy as np
import pandas as pd
import psycopg

IND = ["male_pct", "one_person_hh_pct", "non_apt_pct", "age65_pct", "park_area_pct", "bus_stop_density"]
BANDS = ["00_04", "05_09", "10_14", "15_19", "20_24", "25_29", "30_34", "35_39", "40_44", "45_49", "50_54", "55_59", "60_64"]


def ratio(n, d):
    return np.where(d > 0, n / np.where(d > 0, d, 1), np.nan)


def indicators(detail: pd.DataFrame) -> pd.DataFrame:
    p = detail.pivot_table(index=["period_start", "adm_cd10"], columns="item_cd", values="value", aggfunc="first")
    for c in ["pop_total", "pop_male", "hh_total", "hh_size_1", "house_total", "house_apt", "park_area_m2", "bus_stop_cnt", "area_km2"] + [f"pop_{s}_{b}" for s in ("M", "F") for b in BANDS]:
        if c not in p.columns:
            p[c] = np.nan
    under65 = sum(p[f"pop_{s}_{b}"] for s in ("M", "F") for b in BANDS)
    out = pd.DataFrame(index=p.index)
    out["male_pct"] = ratio(p.pop_male, p.pop_total) * 100
    out["one_person_hh_pct"] = ratio(p.hh_size_1, p.hh_total) * 100
    out["non_apt_pct"] = ratio(p.house_total - p.house_apt, p.house_total) * 100
    out["age65_pct"] = ratio(p.pop_total - under65, p.pop_total) * 100
    out["park_area_pct"] = ratio(p.park_area_m2, p.area_km2 * 1e6) * 100
    out["bus_stop_density"] = ratio(p.bus_stop_cnt, p.area_km2)
    return out.reset_index()


def dec(v):
    return None if pd.isna(v) else Decimal(f"{v:.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    months = [f"{m}-01" for m in args.months]
    with psycopg.connect(os.environ["PIPELINE_DB_DSN"]) as conn:
        detail = pd.read_sql("SELECT period_start, adm_cd10, item_cd, value FROM analysis.bg_region_detail WHERE period_start = ANY(%s)", conn, params=(months,))
        detail["period_start"] = detail.period_start.astype(str)
        detail["value"] = detail.value.astype(float)
        ind = indicators(detail)
        print(f"[bg_indicators] 원값 {len(detail):,}행 → 지표 {len(ind)}행 (NULL 있는 행 {int(ind[IND].isna().any(axis=1).sum())})", flush=True)
        old = pd.read_sql("SELECT period_start, adm_cd10, " + ", ".join(IND) + " FROM analysis.bg_region_indicator WHERE period_start = ANY(%s)", conn, params=(months,))
        old["period_start"] = old.period_start.astype(str)
        mi = ind.merge(old, on=["period_start", "adm_cd10"], how="inner", suffixes=("_new", "_old"))
        parts = [f"{c}={int(((mi[f'{c}_new'].round(2) - mi[f'{c}_old'].astype(float)).abs() > 0).sum())}건" for c in IND]
        print(f"[bg_indicators] 기존 값 대조({len(mi)}행, 2자리 반올림 후 불일치): " + ", ".join(parts), flush=True)
        if args.dry_run:
            return 0
        with conn.cursor() as cur:
            cur.executemany(f"INSERT INTO analysis.bg_region_indicator (period_start, adm_cd10, {', '.join(IND)}, updated_at) VALUES (%s, %s, {', '.join('%s' for _ in IND)}, now()) "
                            f"ON CONFLICT (period_start, adm_cd10) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in IND)}, updated_at = now()",
                            [(r.period_start, r.adm_cd10, *[dec(getattr(r, c)) for c in IND]) for r in ind.itertuples()])
        conn.commit()
    print(f"[bg_indicators] 적재: bg_region_indicator {len(ind)}행", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
