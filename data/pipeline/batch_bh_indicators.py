"""2차 5.2 — flow_detail → bh_grid_indicator(격자, 10개 + activity) → bh_region_indicator(동, 12개 + activity) 월 배치.

산식 (정의서 4.7·4.8, 완성본 컬럼정의)
  activity_daily = Σ 시간대 일평균(24)      h12 = 평균(18~21시)/평균(9~17시)    h13 = 평균(7,8,9,17,18,19시)/평균(10~16시)
  h14·h15·h19 = 비중 엔트로피(자연로그)      h18 = 남60+/(남60++여60+)           h20 = (유동60+/유동전체)/(주민60+/주민전체)
  h21 = (유동 남50++남60+)/유동전체 ÷ 주민 남50+/주민전체                          h26·h29 = 전월 대비 변화율 격차(%p)
  h30·h31 = 전월 대비 JS 거리(밑 2)         분모 0 또는 전월 없음 → NULL (0 금지)
읍면동 값은 격자 값 평균이 아니라 동 안 격자의 유동을 합산한 뒤 다시 계산한다. 주민 인구는 bg_region_detail(그 달).
실행 (infra/):  docker compose --profile data exec spark spark-submit pipeline/batch_bh_indicators.py --months 2025-07 [--dry-run]
  --dry-run: DB 에 쓰지 않고 기존 bh_region_indicator(1차 완성본 값)와의 차이만 출력
  기본 동작: bh_grid_indicator 는 그 달을 지우고 다시 쓰고, bh_region_indicator 는 activity_daily 만 채운다
            (H 지표 12개는 1차 완성본 값을 그대로 둔다 — 2차 산출값과 0.25%~2% 차이가 있어 DA 확인 전까지 덮어쓰지 않음)
  --overwrite-region: bh_region_indicator 의 H 지표 12개까지 2차 산출값으로 덮어쓴다
"""
import argparse
import os
from decimal import Decimal

import numpy as np
import pandas as pd
import psycopg

H = [f"{i:02d}" for i in range(24)]
W = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
A = ["M_10", "M_20", "M_30", "M_40", "M_50", "M_60P", "F_10", "F_20", "F_30", "F_40", "F_50", "F_60P"]
GRID_COLS = ["activity_daily", "h12_evening_day_ratio", "h13_commute_ratio", "h14_hour_entropy", "h15_weekday_entropy",
             "h18_senior_male_share", "h19_age_entropy", "h26_weekend_weekday_change_gap", "h29_senior_gender_change_gap",
             "h30_hour_profile_distance", "h31_weekday_profile_distance"]
REGION_COLS = GRID_COLS[:7] + ["h20_senior_representation", "h21_male50plus_representation"] + GRID_COLS[7:]


def prev_month(m: str) -> str:
    y, mm = (int(x) for x in m.split("-"))
    return f"{y - 1}-12" if mm == 1 else f"{y}-{mm - 1:02d}"


def load_means(conn, m: str):
    """격자 × (hour 24 + weekday 7 + sex_age 12) 일평균. 그 달 자료가 없으면 None."""
    df = pd.read_sql("SELECT grid_cd, dim_type, dim_value, flow_sum / day_count AS mean FROM analysis.flow_detail "
                     "WHERE period_start = %s AND day_count > 0", conn, params=(f"{m}-01",))
    if df.empty:
        return None
    return df.pivot(index="grid_cd", columns="dim_value", values="mean").astype(float).reindex(columns=H + W + A)


def entropy(x):
    tot = x.sum(axis=1, keepdims=True)
    p = np.divide(x, tot, out=np.zeros_like(x), where=tot > 0)
    e = -(np.where(p > 0, p * np.log(np.where(p > 0, p, 1)), 0)).sum(axis=1)
    return np.where(tot[:, 0] > 0, e, np.nan)


def js_distance(x, y):
    def shares(v):
        tot = v.sum(axis=1, keepdims=True)
        return np.divide(v, tot, out=np.full_like(v, np.nan), where=tot > 0)
    p, q = shares(x), shares(y)
    mm = (p + q) / 2
    def kl(a, b):
        return (np.where(a > 0, a * np.log2(np.where(a > 0, a, 1) / np.where(b > 0, b, 1)), 0)).sum(axis=1)
    return np.sqrt(np.clip((kl(p, mm) + kl(q, mm)) / 2, 0, None))


def ratio(num, den):
    return np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)


def indicators(cur, prev):
    h, w, a = cur[H].to_numpy(), cur[W].to_numpy(), cur[A].to_numpy()
    out = pd.DataFrame(index=cur.index)
    out["activity_daily"] = h.sum(axis=1)
    out["h12_evening_day_ratio"] = ratio(h[:, 18:22].mean(axis=1), h[:, 9:18].mean(axis=1))
    out["h13_commute_ratio"] = ratio(h[:, [7, 8, 9, 17, 18, 19]].mean(axis=1), h[:, 10:17].mean(axis=1))
    out["h14_hour_entropy"] = entropy(h)
    out["h15_weekday_entropy"] = entropy(w)
    out["h18_senior_male_share"] = ratio(a[:, 5], a[:, 5] + a[:, 11])
    out["h19_age_entropy"] = entropy(a[:, :6] + a[:, 6:])
    for c in GRID_COLS[7:]:
        out[c] = np.nan
    if prev is not None:
        pv = prev.reindex(cur.index)
        ph, pw, pa = pv[H].to_numpy(), pv[W].to_numpy(), pv[A].to_numpy()
        wk_t, wd_t = w[:, 5:7].mean(axis=1), w[:, :5].mean(axis=1)
        wk_p, wd_p = pw[:, 5:7].mean(axis=1), pw[:, :5].mean(axis=1)
        out["h26_weekend_weekday_change_gap"] = 100 * ((ratio(wk_t, wk_p) - 1) - (ratio(wd_t, wd_p) - 1))
        out["h29_senior_gender_change_gap"] = 100 * ((ratio(a[:, 5], pa[:, 5]) - 1) - (ratio(a[:, 11], pa[:, 11]) - 1))
        out["h30_hour_profile_distance"] = js_distance(h, ph)
        out["h31_weekday_profile_distance"] = js_distance(w, pw)
    return out


def region_means(conn, means):
    if means is None:
        return None
    g2r = pd.read_sql("SELECT grid_cd, adm_cd10 FROM analysis.dim_grid100", conn).set_index("grid_cd")["adm_cd10"]
    return means.groupby(g2r.reindex(means.index)).sum(min_count=1)


def resident(conn, m):
    d = pd.read_sql("SELECT adm_cd10, item_cd, value FROM analysis.bg_region_detail WHERE period_start = %s", conn, params=(f"{m}-01",))
    p = d.pivot(index="adm_cd10", columns="item_cd", values="value").astype(float)
    bands = ["00_04", "05_09", "10_14", "15_19", "20_24", "25_29", "30_34", "35_39", "40_44", "45_49", "50_54", "55_59", "60_64"]
    under60 = sum(p[f"pop_{s}_{b}"] for s in ("M", "F") for b in bands[:-1])
    male_under50 = sum(p[f"pop_M_{b}"] for b in bands[:-3])
    return pd.DataFrame({"total": p["pop_total"], "senior60": p["pop_total"] - under60, "male50": p["pop_male"] - male_under50})


# 저장 가능 범위: H 지표 DECIMAL(10,6) → |값| < 10^4 (유동이 극히 적은 격자의 변화율 %p 가 넘길 수 있다 → 저장 불가라 NULL),
#                activity_daily 는 격자 DECIMAL(12,2) · 읍면동 DECIMAL(14,2)
def limit_of(col):
    return 1e10 if col == "activity_daily" else 1e4


def to_dec(v, limit=1e4):
    return None if pd.isna(v) or abs(v) >= limit else Decimal(f"{v:.6f}")


def report_overflow(name, df):
    over = {c: int((df[c].abs() >= limit_of(c)).sum()) for c in df.columns if (df[c].abs() >= limit_of(c)).any()}
    if over:
        print(f"[bh]   {name}: 저장 범위를 넘어 NULL 처리한 값 {over}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite-region", action="store_true")
    args = ap.parse_args()
    with psycopg.connect(os.environ["PIPELINE_DB_DSN"]) as conn:
        for m in args.months:
            cur, prev = load_means(conn, m), load_means(conn, prev_month(m))
            if cur is None:
                print(f"[bh] {m}: flow_detail 없음, 건너뜀", flush=True)
                continue
            grid = indicators(cur, prev)
            rc, rp = region_means(conn, cur), region_means(conn, prev)
            reg = indicators(rc, rp)
            res = resident(conn, m).reindex(reg.index)
            a = rc[A].to_numpy()
            tot = a.sum(axis=1)
            reg["h20_senior_representation"] = ratio(ratio(a[:, 5] + a[:, 11], tot), ratio(res["senior60"].to_numpy(), res["total"].to_numpy()))
            reg["h21_male50plus_representation"] = ratio(ratio(a[:, 4] + a[:, 5], tot), ratio(res["male50"].to_numpy(), res["total"].to_numpy()))
            reg = reg[REGION_COLS]
            old = pd.read_sql("SELECT adm_cd10, " + ", ".join(REGION_COLS) + " FROM analysis.bh_region_indicator WHERE period_start = %s",
                              conn, params=(f"{m}-01",)).set_index("adm_cd10").astype(float).reindex(reg.index)
            parts = []
            for c in REGION_COLS:
                if old[c].notna().any():
                    parts.append(f"{c.split('_')[0]}={float(np.nanmax(np.abs(reg[c].to_numpy(float) - old[c].to_numpy(float)))):.1e}")
                else:
                    parts.append(f"{c.split('_')[0]}=기존NULL")
            print(f"[bh] {m}: 격자 {len(grid):,} (전월 {'있음' if prev is not None else '없음'}) | 동 {len(reg)} | 기존 값과 최대 차이: " + ", ".join(parts), flush=True)
            if args.dry_run:
                continue
            report_overflow(f"{m} 격자", grid[GRID_COLS])
            report_overflow(f"{m} 읍면동", reg)
            with conn.cursor() as c:
                c.execute("DELETE FROM analysis.bh_grid_indicator WHERE period_start = %s", (f"{m}-01",))
                rows = [(f"{m}-01", g, *[to_dec(v, limit_of(c)) for c, v in zip(GRID_COLS, r)]) for g, r in zip(grid.index, grid[GRID_COLS].to_numpy())]
                c.executemany(f"INSERT INTO analysis.bh_grid_indicator (period_start, grid_cd, {', '.join(GRID_COLS)}, updated_at) "
                              f"VALUES (%s, %s, {', '.join('%s' for _ in GRID_COLS)}, now())", rows)
                wcols = REGION_COLS if args.overwrite_region else ["activity_daily"]
                rrows = [(f"{m}-01", d, *[to_dec(v, limit_of(c)) for c, v in zip(wcols, r)]) for d, r in zip(reg.index, reg[wcols].to_numpy())]
                c.executemany(f"INSERT INTO analysis.bh_region_indicator (period_start, adm_cd10, {', '.join(wcols)}, updated_at) "
                              f"VALUES (%s, %s, {', '.join('%s' for _ in wcols)}, now()) "
                              f"ON CONFLICT (period_start, adm_cd10) DO UPDATE SET {', '.join(f'{x} = EXCLUDED.{x}' for x in wcols)}, updated_at = now()", rrows)
            conn.commit()
            print(f"[bh] {m}: bh_grid_indicator {len(rows):,}행, bh_region_indicator {len(rrows)}행 ({'전체 컬럼' if args.overwrite_region else 'activity_daily 만'}) 적재", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
