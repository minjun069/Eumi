"""1차 4.5 — 행동_데이터셋_최종.xlsx 행동_최종본(282행) → analysis.bh_region_indicator (H 지표 12개).

- 정제 없이 값을 옮긴다. 7월의 h26 · h29 · h30 · h31 은 전월이 없어 원본대로 NULL (0 금지).
- activity_daily(24시간 유동 합)는 완성본에 없어 NULL 로 둔다 (2차에서 flow_detail 로 산출). 점수 · 등급 컬럼은 넣지 않는다.
실행  data/.venv/Scripts/python data/pipeline/load_bh_region.py
"""
import random
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from common import RAW_DIR, check, db_connect, setup

XLSX = RAW_DIR / "final_sets" / "행동_데이터셋_최종.xlsx"
SHEET = "행동_최종본"
H_COLS = ["h12_evening_day_ratio", "h13_commute_ratio", "h14_hour_entropy", "h15_weekday_entropy", "h18_senior_male_share",
          "h19_age_entropy", "h20_senior_representation", "h21_male50plus_representation", "h26_weekend_weekday_change_gap",
          "h29_senior_gender_change_gap", "h30_hour_profile_distance", "h31_weekday_profile_distance"]
PREV_MONTH_COLS = H_COLS[8:]
SQL = f"""
INSERT INTO analysis.bh_region_indicator (period_start, adm_cd10, activity_daily, {', '.join(H_COLS)}, updated_at)
VALUES (%(period_start)s, %(adm_cd10)s, NULL, {', '.join(f'%({c})s' for c in H_COLS)}, now())
ON CONFLICT (period_start, adm_cd10) DO UPDATE SET activity_daily = NULL, {', '.join(f'{c} = EXCLUDED.{c}' for c in H_COLS)}, updated_at = now()
"""


def dec(v):
    return None if pd.isna(v) else Decimal(str(v))


def q6(v):
    return None if pd.isna(v) else Decimal(str(v)).quantize(Decimal("0.000001"), ROUND_HALF_UP)


def main() -> int:
    setup()
    df = pd.read_excel(XLSX, sheet_name=SHEET, dtype={"region_code": str, "month": str})
    df["period_start"] = pd.to_datetime(df["month"] + "-01").dt.date
    ok = check("행동_최종본 행 수", len(df) == 282, f"{len(df)} (47동 × 6개월)")
    ok &= check("동 × 월 유일", not df.duplicated(["region_code", "month"]).any(), f"동 {df['region_code'].nunique()}, 도시 {df['city'].value_counts().to_dict()}")
    missing_cols = [c for c in H_COLS if c not in df.columns]
    ok &= check("H 지표 12개 컬럼 존재", not missing_cols, f"missing={missing_cols}" if missing_cols else "")
    src_null = {c: int(df[c].isna().sum()) for c in H_COLS if df[c].isna().any()}
    july_only = all(df.loc[df[c].isna(), "month"].eq("2025-07").all() and df[c].isna().sum() == 47 for c in PREV_MONTH_COLS)
    ok &= check("원본 결측은 7월 h26·h29·h30·h31 뿐", july_only and set(src_null) == set(PREV_MONTH_COLS), str(src_null))
    if not ok:
        return 1

    rows = [{"period_start": r.period_start, "adm_cd10": r.region_code, **{c: dec(getattr(r, c)) for c in H_COLS}} for r in df.itertuples()]
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(SQL, rows)
            cur.execute("SELECT count(*), " + ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in H_COLS) + ", count(*) FILTER (WHERE activity_daily IS NULL) FROM analysis.bh_region_indicator")
            res = cur.fetchone()
            n, db_null, n_act_null = res[0], dict(zip(H_COLS, res[1:-1])), res[-1]
            random.seed(45)
            pick = df.iloc[random.randrange(len(df))]
            cur.execute(f"SELECT {', '.join(H_COLS)} FROM analysis.bh_region_indicator WHERE period_start = %s AND adm_cd10 = %s", (pick.period_start, pick.region_code))
            db_row = cur.fetchone()
        conn.commit()

    ok &= check("bh_region_indicator 행 수", n == 282, f"{n}")
    ok &= check("DB NULL 수 = 원본 결측 수 (0으로 안 바뀜)", {c: v for c, v in db_null.items() if v} == src_null, f"{ {c: v for c, v in db_null.items() if v} }")
    exp = tuple(q6(pick[c]) for c in H_COLS)
    ok &= check(f"대조 {pick.region_name} {pick.month} 지표 12개", db_row == exp, "모두 일치" if db_row == exp else f"db={db_row} exp={exp}")
    print(f"참고: activity_daily 는 완성본에 없어 NULL ({n_act_null}행). 2차에서 flow_detail 로 산출")
    print("LOAD_BH_REGION", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
