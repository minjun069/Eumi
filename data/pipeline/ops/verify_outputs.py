"""[운영 · 결과 검증 | pipeline 컨테이너] 월 배치가 끝난 뒤 결과 테이블이 계약대로 채워졌는지 검사한다 (DAG 마지막 태스크).

달마다 보는 것
  - 배경: bg_region_detail 47개 동 · 값 ≥ 0, bg_region_indicator 47행 · 6개 지표 모두 있음 · 비율 0~100
  - 유동: flow_detail 격자마다 구분 43칸(시간 24 · 요일 7 · 성연령 12) · day_count = 그 달 일수(요일은 4~5) · 값 ≥ 0
  - 행동 지표: bh_grid_indicator 격자 수 = flow_detail 격자 수, 엔트로피 · 비율 · JS 거리 범위,
              bh_region_indicator 47행 · 전월이 있으면 12개 전부, 없으면 변화 지표 4개는 NULL
  - 결과: region_result 는 전월이 있으면 47행 · 없으면 0행, 등급 1~3 · 위험단계 = 두 등급 합 − 1,
          도시마다 행동 등급 3 비율 10~30%, 점수가 지금 지표로 다시 계산한 값과 같음(0.005 이내, 오래된 결과 탐지)
  - 격자 점수: bh_grid_anomaly 는 지표 10개가 모두 있는 격자만 · 다시 계산한 값과 같음
  - 실거래가: re_apt_trade 그 달 계약 행 > 0 · 거래 유형 · 금액(매매 · 전세 > 0, 월세는 월세 > 0 · 보증금 0 허용) · 좌표 범위 · 강남구/춘천시 동
하나라도 실패하면 종료 코드 1 (Airflow 태스크 실패).
실행  python3 pipeline/ops/verify_outputs.py --months 2025-12 …   |   --all (결과가 있는 모든 달)
"""
import argparse
import calendar
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
from common import check, db_connect, months_arg, setup

CITY_PREFIX = ("11680", "51110")
N_DONG = 47


def one(cur, sql, *params):
    cur.execute(sql, params)
    return cur.fetchone()


def prev_month(m: str) -> str:
    y, mm = int(m[:4]), int(m[5:])
    return f"{y - 1}-12" if mm == 1 else f"{y}-{mm - 1:02d}"


def check_background(cur, m):
    p = f"{m}-01"
    dongs, rows, items, vmin = one(cur, "SELECT count(DISTINCT adm_cd10), count(*), count(DISTINCT item_cd), min(value) FROM analysis.bg_region_detail WHERE period_start = %s", p)
    ok = check(f"{m} 배경 상세", dongs == N_DONG and items >= 40 and (vmin or 0) >= 0, f"동 {dongs} · 행 {rows:,} · 항목 {items} · 최솟값 {vmin}")
    n, full, bad = one(cur, """SELECT count(*),
        count(*) FILTER (WHERE male_pct IS NOT NULL AND one_person_hh_pct IS NOT NULL AND non_apt_pct IS NOT NULL
                          AND age65_pct IS NOT NULL AND park_area_pct IS NOT NULL AND bus_stop_density IS NOT NULL),
        count(*) FILTER (WHERE greatest(male_pct, one_person_hh_pct, non_apt_pct, age65_pct, park_area_pct) > 100
                            OR least(male_pct, one_person_hh_pct, non_apt_pct, age65_pct, park_area_pct, bus_stop_density) < 0)
        FROM analysis.bg_region_indicator WHERE period_start = %s""", p)
    ok &= check(f"{m} 배경 지표", n == N_DONG and full == N_DONG and bad == 0, f"행 {n} · 6개 모두 {full} · 범위 밖 {bad}")
    return ok


def check_flow(cur, m):
    p = f"{m}-01"
    days = calendar.monthrange(int(m[:4]), int(m[5:]))[1]
    cur.execute("""SELECT dim_type, count(*), count(DISTINCT grid_cd), min(day_count), max(day_count), min(flow_sum)
                   FROM analysis.flow_detail WHERE period_start = %s GROUP BY dim_type""", (p,))
    d = {r[0]: r[1:] for r in cur.fetchall()}
    if not d:
        return check(f"{m} 유동 상세", False, "행 없음"), 0
    grids = d.get("hour", (0, 0))[1]
    want = {"hour": 24, "weekday": 7, "sex_age": 12}
    shape = all(t in d and d[t][1] == grids and d[t][0] == grids * k for t, k in want.items())
    dc = d["hour"][2] == d["hour"][3] == days and d["sex_age"][2] == d["sex_age"][3] == days and 4 <= d["weekday"][2] <= d["weekday"][3] <= 5
    neg = min(v[4] for v in d.values()) < 0
    return check(f"{m} 유동 상세", shape and dc and not neg,
                 f"격자 {grids:,} · 행 {sum(v[0] for v in d.values()):,} · 일수 {days} · day_count {[(t, v[2], v[3]) for t, v in d.items()]}"), grids


def check_behavior(cur, m, flow_grids, has_prev):
    p = f"{m}-01"
    n, act, chg, bad = one(cur, f"""SELECT count(*), count(activity_daily),
        count(*) FILTER (WHERE h26_weekend_weekday_change_gap IS NOT NULL OR h30_hour_profile_distance IS NOT NULL),
        count(*) FILTER (WHERE h14_hour_entropy > {math.log(24) + 1e-6} OR h15_weekday_entropy > {math.log(7) + 1e-6}
                            OR h19_age_entropy > {math.log(6) + 1e-6} OR h18_senior_male_share NOT BETWEEN 0 AND 1
                            OR h30_hour_profile_distance NOT BETWEEN 0 AND 1 OR h31_weekday_profile_distance NOT BETWEEN 0 AND 1
                            OR h12_evening_day_ratio < 0 OR h13_commute_ratio < 0)
        FROM analysis.bh_grid_indicator WHERE period_start = %s""", p)
    ok = check(f"{m} 격자 행동 지표", n == flow_grids and act == n and bad == 0 and ((chg > 0) == has_prev),
               f"격자 {n:,} (유동 {flow_grids:,}) · activity {act:,} · 변화 지표 있음 {chg:,} · 범위 밖 {bad}")
    n, full, lag_null = one(cur, """SELECT count(*),
        count(*) FILTER (WHERE activity_daily IS NOT NULL AND h12_evening_day_ratio IS NOT NULL AND h13_commute_ratio IS NOT NULL
             AND h14_hour_entropy IS NOT NULL AND h15_weekday_entropy IS NOT NULL AND h18_senior_male_share IS NOT NULL
             AND h19_age_entropy IS NOT NULL AND h20_senior_representation IS NOT NULL AND h21_male50plus_representation IS NOT NULL
             AND h26_weekend_weekday_change_gap IS NOT NULL AND h29_senior_gender_change_gap IS NOT NULL
             AND h30_hour_profile_distance IS NOT NULL AND h31_weekday_profile_distance IS NOT NULL),
        count(*) FILTER (WHERE h26_weekend_weekday_change_gap IS NULL AND h29_senior_gender_change_gap IS NULL
             AND h30_hour_profile_distance IS NULL AND h31_weekday_profile_distance IS NULL)
        FROM analysis.bh_region_indicator WHERE period_start = %s""", p)
    want = (full == N_DONG) if has_prev else (lag_null == N_DONG)
    ok &= check(f"{m} 읍면동 행동 지표", n == N_DONG and want, f"행 {n} · 13개 모두 {full} · 변화 지표 NULL {lag_null} (전월 {'있음' if has_prev else '없음'})")
    return ok


def check_result(cur, conn, assets, m, has_prev):
    from m4_analysis.batch_region_result import score_month  # 같은 산식으로 다시 계산해 저장값과 대조
    p = f"{m}-01"
    db = pd.read_sql("SELECT r.adm_cd10, d.sgg_nm AS city, r.bg_score, r.bg_grade, r.bh_score, r.bh_grade, r.risk_grade "
                     "FROM public.region_result r JOIN public.dim_region d USING (adm_cd10) WHERE r.period_start = %s", conn, params=(p,))
    if not has_prev:
        return check(f"{m} 읍면동 결과", len(db) == 0, f"전월 없음 → 행 0 이어야 함 (실제 {len(db)})")
    for c in ("bg_score", "bh_score"):
        db[c] = db[c].astype(float)
    grade_ok = db.bg_grade.between(1, 3).all() and db.bh_grade.between(1, 3).all() and (db.risk_grade == db.bg_grade + db.bh_grade - 1).all()
    share = db.groupby("city").bh_grade.apply(lambda s: float((s == 3).mean())).to_dict()
    ok = check(f"{m} 읍면동 결과", len(db) == N_DONG and grade_ok and all(0.10 <= v <= 0.30 for v in share.values()),
               f"행 {len(db)} · 등급 규칙 {grade_ok} · 행동 등급 3 비율 {({k: round(v, 2) for k, v in share.items()})}")
    re = score_month(conn, assets, m).set_index("adm_cd10").reindex(db.adm_cd10)
    d_bg = float(np.nanmax(np.abs(re.bg_score.to_numpy() - db.bg_score.to_numpy())))
    d_bh = float(np.nanmax(np.abs(re.bh_score.to_numpy() - db.bh_score.to_numpy())))
    same_grade = int((re.risk_grade.to_numpy() == db.risk_grade.to_numpy()).sum())
    ok &= check(f"{m} 결과 = 지금 지표로 재계산", d_bg <= 0.0051 and d_bh <= 0.0051 and same_grade == len(db),
                f"bg_score 최대차 {d_bg:.4f} · bh_score 최대차 {d_bh:.4f} · 위험단계 일치 {same_grade}/{len(db)}")
    return ok


def check_grid_anomaly(conn, assets, m, has_prev):
    p = f"{m}-01"
    feats = assets.grid_features
    df = pd.read_sql("SELECT i.grid_cd, r.sgg_nm AS city, " + ", ".join(f"i.{c}" for c in feats) + ", a.anomaly_score "
                     "FROM analysis.bh_grid_indicator i JOIN analysis.dim_grid100 g ON g.grid_cd = i.grid_cd "
                     "JOIN public.dim_region r ON r.adm_cd10 = g.adm_cd10 "
                     "LEFT JOIN analysis.bh_grid_anomaly a ON a.grid_cd = i.grid_cd AND a.period_start = i.period_start "
                     "WHERE i.period_start = %s", conn, params=(p,))
    for c in feats + ["anomaly_score"]:
        df[c] = df[c].astype(float)
    full = np.isfinite(df[feats].to_numpy()).all(axis=1)
    stored = df.anomaly_score.notna().to_numpy()
    if not has_prev:
        return check(f"{m} 격자 이상 점수", stored.sum() == 0, f"전월 없음 → 행 0 이어야 함 (실제 {int(stored.sum())})")
    re = np.full(len(df), np.nan)
    for city in df.city.unique():
        mask = df.city.eq(city).to_numpy()
        re[mask] = assets.anomaly_score("grid", city, df.loc[mask])
    diff = float(np.nanmax(np.abs(re[stored] - df.anomaly_score.to_numpy()[stored]))) if stored.any() else float("nan")
    return check(f"{m} 격자 이상 점수", (stored == full).all() and stored.sum() > 0 and diff <= 0.0051,
                 f"점수 {int(stored.sum()):,} = 지표 10개 모두 있는 격자 {int(full.sum()):,} · 재계산 최대차 {diff:.4f}")


def check_apt(cur, m):
    y, mm = int(m[:4]), int(m[5:])
    first = f"{m}-01"
    nxt = f"{y + 1}-01-01" if mm == 12 else f"{y}-{mm + 1:02d}-01"
    n, by_type, bad = one(cur, f"""SELECT count(*),
        string_agg(DISTINCT deal_type, ','),
        count(*) FILTER (WHERE deal_type NOT IN ('매매', '전세', '월세') OR price_10k < 0
             OR (deal_type IN ('매매', '전세') AND price_10k <= 0)
             OR (deal_type = '월세' AND coalesce(monthly_rent_10k, 0) <= 0)
             OR lat NOT BETWEEN 33 AND 39 OR lon NOT BETWEEN 124 AND 132
             OR left(adm_cd10, 5) NOT IN {CITY_PREFIX})
        FROM analysis.re_apt_trade WHERE contract_date >= %s AND contract_date < %s""", first, nxt)
    return check(f"{m} 실거래가", n > 0 and bad == 0, f"행 {n:,} · 유형 {by_type} · 규칙 위반 {bad}")


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", help="기준월 YYYY-MM 목록 (없으면 전월)")
    ap.add_argument("--all", action="store_true", help="bg_region_indicator 에 있는 모든 달")
    args = ap.parse_args()
    from common.m4_models import ModelAssets
    assets = ModelAssets()
    ok = True
    with db_connect() as conn, conn.cursor() as cur:
        if args.all:
            cur.execute("SELECT DISTINCT to_char(period_start, 'YYYY-MM') FROM analysis.bg_region_indicator ORDER BY 1")
            months = [r[0] for r in cur.fetchall()]
        else:
            months = [f"{m[:4]}-{m[4:]}" for m in months_arg(args.months)]
        n_dim = one(cur, "SELECT (SELECT count(*) FROM public.dim_region), (SELECT count(*) FROM analysis.dim_grid100)")
        ok &= check("기준 테이블", n_dim[0] == N_DONG and n_dim[1] > 0, f"행정동 {n_dim[0]} · 100m 격자 {n_dim[1]:,}")
        for m in months:
            has_prev = one(cur, "SELECT EXISTS (SELECT 1 FROM analysis.flow_detail WHERE period_start = %s)", f"{prev_month(m)}-01")[0]
            print(f"--- {m} (전월 유동 {'있음' if has_prev else '없음'})", flush=True)
            ok &= check_background(cur, m)
            flow_ok, grids = check_flow(cur, m)
            ok &= flow_ok
            ok &= check_behavior(cur, m, grids, has_prev)
            ok &= check_result(cur, conn, assets, m, has_prev)
            ok &= check_grid_anomaly(conn, assets, m, has_prev)
            ok &= check_apt(cur, m)
    print(f"VERIFY {'PASS' if ok else 'FAIL'} ({', '.join(months)})", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
