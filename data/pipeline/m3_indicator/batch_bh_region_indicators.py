"""[M3-2 읍면동 행동 지표 | Spark 컨테이너] flow_detail + bg_region_detail → analysis.bh_region_indicator (읍면동, 지표 12개 + activity_daily) 월 배치.

읍면동 값은 격자 지표의 평균이 아니라, 동 안 격자(dim_grid100.adm_cd10)의 일평균 유동을 합산한 뒤 산식(bh_indicators.py)을 다시 적용한다.
h20·h21 의 분모(주민 60세+ · 남 50세+ 비율)는 그 달 bg_region_detail 의 주민등록 인구.
실행 (infra/):  docker compose --profile data exec spark python3 pipeline/m3_indicator/batch_bh_region_indicators.py --months 2025-07 ... [--dry-run]
  --dry-run: DB 에 쓰지 않고 기존 bh_region_indicator 와의 최대 차이만 출력
  기본 동작: 지표 12개 + activity_daily 를 UPSERT 한다. 유동 상세가 DA 와 같은 50m 코호트 셀로 생성되므로(synth_flow COHORT_FILE)
  DA 읍면동 값과 셀 집합·산식이 같고, 동 배정 단위(100m 격자 vs 50m 점)만 달라 최대 2% 안에서 차이가 난다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
import os

import pandas as pd
import psycopg

from common.bh_indicators import A, REGION_COLS, indicators, limit_of, load_means, max_diff_text, prev_month, ratio, report_overflow, to_dec

BANDS = ["00_04", "05_09", "10_14", "15_19", "20_24", "25_29", "30_34", "35_39", "40_44", "45_49", "50_54", "55_59", "60_64"]


def region_means(conn, means):
    """격자 일평균 → 동별 합산 (dim_grid100 의 소속 동 기준)."""
    if means is None:
        return None
    g2r = pd.read_sql("SELECT grid_cd, adm_cd10 FROM analysis.dim_grid100", conn).set_index("grid_cd")["adm_cd10"]
    return means.groupby(g2r.reindex(means.index)).sum(min_count=1)


def resident(conn, m):
    """그 달 주민등록 인구: 전체, 60세+, 남 50세+."""
    d = pd.read_sql("SELECT adm_cd10, item_cd, value FROM analysis.bg_region_detail WHERE period_start = %s", conn, params=(f"{m}-01",))
    p = d.pivot(index="adm_cd10", columns="item_cd", values="value").astype(float)
    under60 = sum(p[f"pop_{s}_{b}"] for s in ("M", "F") for b in BANDS[:-1])
    male_under50 = sum(p[f"pop_M_{b}"] for b in BANDS[:-3])
    return pd.DataFrame({"total": p["pop_total"], "senior60": p["pop_total"] - under60, "male50": p["pop_male"] - male_under50})


def region_indicators(conn, m):
    """(동별 지표 DataFrame, 전월 있음 여부). 그 달 flow_detail 이 없으면 (None, False)."""
    cur, prev = load_means(conn, m), load_means(conn, prev_month(m))
    if cur is None:
        return None, False
    rc, rp = region_means(conn, cur), region_means(conn, prev)
    reg = indicators(rc, rp)
    res = resident(conn, m).reindex(reg.index)
    a = rc[A].to_numpy()
    tot = a.sum(axis=1)
    reg["h20_senior_representation"] = ratio(ratio(a[:, 5] + a[:, 11], tot), ratio(res["senior60"].to_numpy(), res["total"].to_numpy()))
    reg["h21_male50plus_representation"] = ratio(ratio(a[:, 4] + a[:, 5], tot), ratio(res["male50"].to_numpy(), res["total"].to_numpy()))
    return reg[REGION_COLS], prev is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with psycopg.connect(os.environ["PIPELINE_DB_DSN"]) as conn:
        for m in args.months:
            reg, has_prev = region_indicators(conn, m)
            if reg is None:
                print(f"[bh-region] {m}: flow_detail 없음, 건너뜀", flush=True)
                continue
            old = pd.read_sql("SELECT adm_cd10, " + ", ".join(REGION_COLS) + " FROM analysis.bh_region_indicator WHERE period_start = %s",
                              conn, params=(f"{m}-01",)).set_index("adm_cd10").astype(float).reindex(reg.index)
            print(f"[bh-region] {m}: 동 {len(reg)} (전월 {'있음' if has_prev else '없음'}) | 기존 값과 최대 차이: " + max_diff_text(reg, old, REGION_COLS), flush=True)
            if args.dry_run:
                continue
            report_overflow(f"{m} 읍면동", reg)
            wcols = REGION_COLS
            rows = [(f"{m}-01", d, *[to_dec(v, limit_of(c)) for c, v in zip(wcols, r)]) for d, r in zip(reg.index, reg[wcols].to_numpy())]
            with conn.cursor() as c:
                c.executemany(f"INSERT INTO analysis.bh_region_indicator (period_start, adm_cd10, {', '.join(wcols)}, updated_at) "
                              f"VALUES (%s, %s, {', '.join('%s' for _ in wcols)}, now()) "
                              f"ON CONFLICT (period_start, adm_cd10) DO UPDATE SET {', '.join(f'{x} = EXCLUDED.{x}' for x in wcols)}, updated_at = now()", rows)
            conn.commit()
            print(f"[bh-region] {m}: bh_region_indicator {len(rows)}행 적재", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
