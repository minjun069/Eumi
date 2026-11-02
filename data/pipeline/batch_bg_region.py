"""2차 5.1 — 배경 원본 → analysis.bg_region_detail(원값) → analysis.bg_region_indicator(비율 6개) 월 배치.

비율 (인수인계 5.1): 남성 = pop_male/pop_total, 1인가구 = hh_size_1/hh_total, 비아파트 = (house_total − house_apt)/house_total,
      65세+ = (pop_total − Σ 0~64세 구간)/pop_total, 공원 = park_area_m2/(area_km2 × 1e6), 정류장 밀도 = bus_stop_cnt/area_km2  (모두 % 또는 개/㎢)
적재: 그 달 행을 지운 뒤 넣는다(detail은 bg_sources 가 만드는 항목만). 분모 0 또는 결측이면 NULL.
실행 (infra/):  docker compose --profile data exec spark spark-submit pipeline/batch_bg_region.py --months 2025-07 ... [--dry-run]
  --dry-run: 적재하지 않고 기존 값(1차 완성본)과의 차이만 출력
"""
import argparse
import os
from decimal import Decimal

import numpy as np
import pandas as pd
import psycopg

from bg_sources import build_detail

IND = ["male_pct", "one_person_hh_pct", "non_apt_pct", "age65_pct", "park_area_pct", "bus_stop_density"]
BANDS = ["00_04", "05_09", "10_14", "15_19", "20_24", "25_29", "30_34", "35_39", "40_44", "45_49", "50_54", "55_59", "60_64"]


def ratio(n, d):
    return np.where(d > 0, n / np.where(d > 0, d, 1), np.nan)


def indicators(detail: pd.DataFrame) -> pd.DataFrame:
    p = detail.pivot_table(index=["period_start", "adm_cd10"], columns="item_cd", values="value", aggfunc="first")
    under65 = sum(p[f"pop_{s}_{b}"] for s in ("M", "F") for b in BANDS)
    out = pd.DataFrame(index=p.index)
    out["male_pct"] = ratio(p.pop_male, p.pop_total) * 100
    out["one_person_hh_pct"] = ratio(p.hh_size_1, p.hh_total) * 100
    out["non_apt_pct"] = ratio(p.house_total - p.house_apt, p.house_total) * 100
    out["age65_pct"] = ratio(p.pop_total - under65, p.pop_total) * 100
    out["park_area_pct"] = ratio(p.park_area_m2, p.area_km2 * 1e6) * 100
    out["bus_stop_density"] = ratio(p.bus_stop_cnt, p.area_km2)
    return out.reset_index()


def dec(v, places):
    return None if pd.isna(v) else Decimal(f"{v:.{places}f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    months = [f"{m}-01" for m in args.months]
    with psycopg.connect(os.environ["PIPELINE_DB_DSN"]) as conn:
        region = pd.read_sql("SELECT adm_cd10, adm_cd8 FROM public.dim_region", conn)
        detail, log = build_detail(region)
        detail = detail[detail.period_start.isin(months)]
        ind = indicators(detail)
        print(f"[bg_region] 원값 {len(detail):,}행 (동 {detail.adm_cd10.nunique()}, 항목 {detail.item_cd.nunique()}), 센서스 복원 {len(log)}셀 | 지표 {len(ind)}행", flush=True)
        # 기존 값(1차)과 비교
        old_d = pd.read_sql("SELECT period_start, adm_cd10, item_cd, value FROM analysis.bg_region_detail WHERE period_start = ANY(%s)", conn, params=(months,))
        old_d["period_start"] = old_d.period_start.astype(str)
        m = detail.merge(old_d, on=["period_start", "adm_cd10", "item_cd"], how="outer", suffixes=("_new", "_old"), indicator=True)
        both = m[m._merge == "both"]
        d2 = (both.value_new.round(2) - both.value_old.astype(float)).abs()
        print(f"[bg_region] 원값 대조: 양쪽 {len(both):,} | 2차에만 {int((m._merge == 'left_only').sum())} | 1차에만 {int((m._merge == 'right_only').sum())} | 2자리 반올림 후 불일치 {int((d2 > 0).sum())} (최대 {d2.max():.2e})", flush=True)
        only_old = m[m._merge == "right_only"]
        if len(only_old):
            print("[bg_region]   1차에만 있는 (동, 항목):", sorted(set(zip(only_old.adm_cd10, only_old.item_cd)))[:20], flush=True)
        old_i = pd.read_sql("SELECT period_start, adm_cd10, " + ", ".join(IND) + " FROM analysis.bg_region_indicator WHERE period_start = ANY(%s)", conn, params=(months,))
        old_i["period_start"] = old_i.period_start.astype(str)
        mi = ind.merge(old_i, on=["period_start", "adm_cd10"], how="inner", suffixes=("_new", "_old"))
        parts = []
        for c in IND:
            dd = (mi[f"{c}_new"].round(2) - mi[f"{c}_old"].astype(float)).abs()
            parts.append(f"{c}={int((dd > 0).sum())}건/최대 {dd.max():.2e}")
        print(f"[bg_region] 지표 대조({len(mi)}행, 2자리 반올림 후 불일치): " + ", ".join(parts), flush=True)
        if args.dry_run:
            return 0
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analysis.bg_region_detail WHERE period_start = ANY(%s) AND item_cd = ANY(%s)", (months, sorted(detail.item_cd.unique())))
            cur.executemany("INSERT INTO analysis.bg_region_detail (period_start, adm_cd10, item_cd, value, updated_at) VALUES (%s, %s, %s, %s, now())",
                            [(r.period_start, r.adm_cd10, r.item_cd, dec(r.value, 2)) for r in detail.itertuples()])
            cur.executemany(f"INSERT INTO analysis.bg_region_indicator (period_start, adm_cd10, {', '.join(IND)}, updated_at) VALUES (%s, %s, {', '.join('%s' for _ in IND)}, now()) "
                            f"ON CONFLICT (period_start, adm_cd10) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in IND)}, updated_at = now()",
                            [(r.period_start, r.adm_cd10, *[dec(getattr(r, c), 2) for c in IND]) for r in ind.itertuples()])
        conn.commit()
    print(f"[bg_region] 적재: bg_region_detail {len(detail):,}행, bg_region_indicator {len(ind)}행", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
