"""2차 M3-3 — flow_detail → analysis.bh_grid_indicator (격자, 지표 10개 + activity_daily) 월 배치.

그 달과 전월의 격자별 일평균(시간대 24 · 요일 7 · 성연령 12)을 읽어 산식(bh_indicators.py)대로 계산하고,
그 달 행을 지운 뒤 다시 넣는다. 전월이 없으면 변화 지표 4개(h26·h29·h30·h31)는 NULL.
실행 (infra/):  docker compose --profile data exec spark python3 pipeline/batch_bh_grid_indicators.py --months 2025-07 ... [--dry-run]
  --dry-run: DB 에 쓰지 않고 격자 수와 기존 bh_grid_indicator 와의 최대 차이만 출력
"""
import argparse
import os

import pandas as pd
import psycopg

from bh_indicators import GRID_COLS, indicators, limit_of, load_means, max_diff_text, prev_month, report_overflow, to_dec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with psycopg.connect(os.environ["PIPELINE_DB_DSN"]) as conn:
        for m in args.months:
            cur, prev = load_means(conn, m), load_means(conn, prev_month(m))
            if cur is None:
                print(f"[bh-grid] {m}: flow_detail 없음, 건너뜀", flush=True)
                continue
            grid = indicators(cur, prev)[GRID_COLS]
            old = pd.read_sql("SELECT grid_cd, " + ", ".join(GRID_COLS) + " FROM analysis.bh_grid_indicator WHERE period_start = %s",
                              conn, params=(f"{m}-01",)).set_index("grid_cd").astype(float).reindex(grid.index)
            print(f"[bh-grid] {m}: 격자 {len(grid):,} (전월 {'있음' if prev is not None else '없음'}) | 기존 {int(old['activity_daily'].notna().sum()):,}행과 최대 차이: "
                  + max_diff_text(grid, old, GRID_COLS), flush=True)
            if args.dry_run:
                continue
            report_overflow(f"{m} 격자", grid)
            rows = [(f"{m}-01", g, *[to_dec(v, limit_of(c)) for c, v in zip(GRID_COLS, r)]) for g, r in zip(grid.index, grid.to_numpy())]
            with conn.cursor() as c:
                c.execute("DELETE FROM analysis.bh_grid_indicator WHERE period_start = %s", (f"{m}-01",))
                c.executemany(f"INSERT INTO analysis.bh_grid_indicator (period_start, grid_cd, {', '.join(GRID_COLS)}, updated_at) "
                              f"VALUES (%s, %s, {', '.join('%s' for _ in GRID_COLS)}, now())", rows)
            conn.commit()
            print(f"[bh-grid] {m}: bh_grid_indicator {len(rows):,}행 적재", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
