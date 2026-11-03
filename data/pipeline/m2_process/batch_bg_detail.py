"""[M2-2 배경 정제 | Spark 컨테이너] 배경 원본 → analysis.bg_region_detail (동 × 월 × 항목 원값) 월 배치.

원본 읽기·센서스 비공개 셀 역산·공원/정류장 귀속·동 면적은 bg_sources.py. 지표(비율 6개)는 batch_bg_indicators.py 가 따로 만든다.
적재: 그 달의 해당 항목 행을 지운 뒤 넣는다. 값이 없는 셀(못 푼 비공개)은 행을 넣지 않는다.
실행 (infra/):  docker compose --profile data exec spark python3 pipeline/m2_process/batch_bg_detail.py --months 2025-07 ... [--dry-run]
  --dry-run: 적재하지 않고 기존 값(1차 완성본)과의 차이만 출력
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
import os
from decimal import Decimal

import pandas as pd
import psycopg

from common.bg_sources import build_detail


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
        print(f"[bg_detail] 원값 {len(detail):,}행 (동 {detail.adm_cd10.nunique()}, 항목 {detail.item_cd.nunique()}), 센서스 복원 {len(log)}셀", flush=True)
        old = pd.read_sql("SELECT period_start, adm_cd10, item_cd, value FROM analysis.bg_region_detail WHERE period_start = ANY(%s)", conn, params=(months,))
        old["period_start"] = old.period_start.astype(str)
        m = detail.merge(old, on=["period_start", "adm_cd10", "item_cd"], how="outer", suffixes=("_new", "_old"), indicator=True)
        both = m[m._merge == "both"]
        d2 = (both.value_new.round(6) - both.value_old.astype(float)).abs()
        print(f"[bg_detail] 기존 값 대조: 양쪽 {len(both):,} | 새로만 {int((m._merge == 'left_only').sum())} | 기존에만 {int((m._merge == 'right_only').sum())} | 6자리 반올림 후 불일치 {int((d2 > 0).sum())} (최대 {d2.max() if len(d2) else 0:.2e})", flush=True)
        only_old = m[m._merge == "right_only"]
        if len(only_old):
            print("[bg_detail]   기존에만 있는 (동, 항목):", sorted(set(zip(only_old.adm_cd10, only_old.item_cd)))[:20], flush=True)
        if args.dry_run:
            return 0
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analysis.bg_region_detail WHERE period_start = ANY(%s) AND item_cd = ANY(%s)", (months, sorted(detail.item_cd.unique())))
            cur.executemany("INSERT INTO analysis.bg_region_detail (period_start, adm_cd10, item_cd, value, updated_at) VALUES (%s, %s, %s, %s, now())",
                            [(r.period_start, r.adm_cd10, r.item_cd, Decimal(f"{r.value:.6f}")) for r in detail.itertuples()])
        conn.commit()
    print(f"[bg_detail] 적재: bg_region_detail {len(detail):,}행", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
