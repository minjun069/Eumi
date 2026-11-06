"""[legacy · 1차 완성본 적재 | 호스트] 배경데이터셋_최종.xlsm 읍면동_월_통합표(282행) → analysis.bg_region_indicator(비율 6개) + analysis.bg_region_detail(원값).

- 정제 없이 값을 옮긴다. 지표는 DECIMAL(5,2)·(7,2) 자리수로 반올림되고, 원값은 NUMERIC(18,6)(V20261102_01)에 그대로 들어간다.
- bg_region_detail 에는 정의서 5.1 항목 사전에 있는 항목만 넣는다 (46개). 통합표에 없는 pop_female · pop_M_65P · pop_F_65P 는 넣지 않는다.
- 비어 있는 셀(NaN)은 행을 넣지 않는다 (0 금지). 같은 달 · 같은 항목은 지우고 다시 넣는다.
실행  data/.venv/Scripts/python data/pipeline/legacy/load_bg_region.py
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import random
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from common import RAW_DIR, check, db_connect, setup

XLSM = RAW_DIR / "final_sets" / "배경데이터셋_최종.xlsm"
SHEET = "읍면동_월_통합표"
IND_MAP = {
    "male_population_pct": "male_pct",
    "single_person_household_pct_annual": "one_person_hh_pct",
    "non_apartment_housing_pct_annual": "non_apt_pct",
    "population_65plus_pct": "age65_pct",
    "park_registered_area_pct_snapshot": "park_area_pct",
    "bus_stop_density_per_km2_snapshot": "bus_stop_density",
}
DETAIL_MAP = {"pop_total_all": "pop_total", "pop_male_all": "pop_male"}
for band in ["0_4", "5_9", "10_14", "15_19", "20_24", "25_29", "30_34", "35_39", "40_44", "45_49", "50_54", "55_59", "60_64"]:
    lo, hi = (int(x) for x in band.split("_"))
    DETAIL_MAP[f"pop_male_{band}"] = f"pop_M_{lo:02d}_{hi:02d}"
    DETAIL_MAP[f"pop_female_{band}"] = f"pop_F_{lo:02d}_{hi:02d}"
DETAIL_MAP.update({
    "households_total_annual": "hh_total", "households_1person_annual": "hh_size_1", "households_2person_annual": "hh_size_2",
    "households_3person_annual": "hh_size_3", "households_4person_annual": "hh_size_4", "households_5person_annual": "hh_size_5",
    "households_6plus_annual": "hh_size_6P",
    "housing_total_annual": "house_total", "housing_detached_total_annual": "house_detached_total",
    "housing_detached_general_annual": "house_detached_general", "housing_detached_multihousehold_annual": "house_detached_multi",
    "housing_detached_mixeduse_annual": "house_detached_mixed", "housing_apartment_annual": "house_apt",
    "housing_rowhouse_annual": "house_row", "housing_multifamily_annual": "house_multi", "housing_in_nonresidential_annual": "house_nonres",
    "park_registered_area_m2_snapshot": "park_area_m2", "bus_stop_count_snapshot": "bus_stop_cnt", "admin_boundary_area_km2": "area_km2",
})
IND_SQL = """
INSERT INTO analysis.bg_region_indicator (period_start, adm_cd10, male_pct, one_person_hh_pct, non_apt_pct, age65_pct, park_area_pct, bus_stop_density, updated_at)
VALUES (%(period_start)s, %(adm_cd10)s, %(male_pct)s, %(one_person_hh_pct)s, %(non_apt_pct)s, %(age65_pct)s, %(park_area_pct)s, %(bus_stop_density)s, now())
ON CONFLICT (period_start, adm_cd10) DO UPDATE SET
    male_pct = EXCLUDED.male_pct, one_person_hh_pct = EXCLUDED.one_person_hh_pct, non_apt_pct = EXCLUDED.non_apt_pct,
    age65_pct = EXCLUDED.age65_pct, park_area_pct = EXCLUDED.park_area_pct, bus_stop_density = EXCLUDED.bus_stop_density, updated_at = now()
"""
DET_SQL = "INSERT INTO analysis.bg_region_detail (period_start, adm_cd10, item_cd, value, updated_at) VALUES (%s, %s, %s, %s, now())"


def dec(v):
    return None if pd.isna(v) else Decimal(str(v))


def q(v, places):
    return None if v is None else Decimal(str(v)).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)


def main() -> int:
    setup()
    argparse.ArgumentParser(description="1차 완성본 배경 데이터셋 적재 (지금은 m2_process/batch_bg_detail.py · m3_indicator/batch_bg_indicators.py 가 대체)").parse_args()  # 인자는 없지만 --help 가 실행으로 이어지지 않게
    df = pd.read_excel(XLSM, sheet_name=SHEET, dtype={"adm_cd": str})
    df["period_start"] = pd.to_datetime(df["base_month"] + "-01").dt.date
    ok = check("통합표 행 수", len(df) == 282, f"{len(df)} (47동 × 6개월)")
    ok &= check("동 × 월 유일", not df.duplicated(["adm_cd", "base_month"]).any(), f"동 {df['adm_cd'].nunique()}, 월 {sorted(df['base_month'].unique())}")
    missing_cols = [c for c in list(IND_MAP) + list(DETAIL_MAP) if c not in df.columns]
    ok &= check("필요 컬럼 존재", not missing_cols, f"missing={missing_cols}" if missing_cols else f"지표 6 + 원값 {len(DETAIL_MAP)}")
    if not ok:
        return 1

    ind_rows = [{"period_start": r.period_start, "adm_cd10": r.adm_cd, **{IND_MAP[c]: dec(getattr(r, c)) for c in IND_MAP}} for r in df.itertuples()]
    det_rows = [(r.period_start, r.adm_cd, DETAIL_MAP[c], dec(getattr(r, c))) for r in df.itertuples() for c in DETAIL_MAP if not pd.isna(getattr(r, c))]
    skipped = len(df) * len(DETAIL_MAP) - len(det_rows)
    months = sorted(df["period_start"].unique())

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(IND_SQL, ind_rows)
            cur.execute("DELETE FROM analysis.bg_region_detail WHERE period_start = ANY(%s) AND item_cd = ANY(%s)", (months, list(DETAIL_MAP.values())))
            cur.executemany(DET_SQL, det_rows)
            cur.execute("SELECT count(*), count(*) FILTER (WHERE male_pct IS NULL OR one_person_hh_pct IS NULL OR non_apt_pct IS NULL OR age65_pct IS NULL OR park_area_pct IS NULL OR bus_stop_density IS NULL) FROM analysis.bg_region_indicator")
            n_ind, n_ind_null = cur.fetchone()
            cur.execute("SELECT count(*), count(DISTINCT item_cd), count(*) FILTER (WHERE value IS NULL) FROM analysis.bg_region_detail")
            n_det, n_items, n_det_null = cur.fetchone()
            # 임의 동 · 월 하나를 골라 원본과 대조 (DB 자리수로 반올림한 값과 같아야 한다)
            random.seed(45)
            pick = df.iloc[random.randrange(len(df))]
            cur.execute("SELECT male_pct, one_person_hh_pct, non_apt_pct, age65_pct, park_area_pct, bus_stop_density FROM analysis.bg_region_indicator WHERE period_start = %s AND adm_cd10 = %s", (pick.period_start, pick.adm_cd))
            db_ind = cur.fetchone()
            exp_ind = tuple(q(pick[c], 2) for c in IND_MAP)
            cur.execute("SELECT item_cd, value FROM analysis.bg_region_detail WHERE period_start = %s AND adm_cd10 = %s", (pick.period_start, pick.adm_cd))
            db_det = dict(cur.fetchall())
            exp_det = {DETAIL_MAP[c]: q(pick[c], 6) for c in DETAIL_MAP if not pd.isna(pick[c])}
        conn.commit()

    ok &= check("bg_region_indicator 행 수", n_ind == 282, f"{n_ind}, NULL 있는 행 {n_ind_null}")
    ok &= check("bg_region_detail 행 수", n_det == len(det_rows), f"{n_det} (항목 {n_items}개, 빈 셀로 건너뛴 {skipped}개, NULL 값 {n_det_null})")
    ok &= check(f"대조 {pick.dong_name} {pick.base_month} 지표 6개", db_ind == exp_ind, f"db={db_ind}")
    diff = {k: (db_det.get(k), v) for k, v in exp_det.items() if db_det.get(k) != v}
    ok &= check(f"대조 {pick.dong_name} {pick.base_month} 원값 {len(exp_det)}개", not diff, str(diff) if diff else "모두 일치")
    lost = sum(1 for r in df.itertuples() for c in IND_MAP if q(getattr(r, c), 2) != Decimal(str(getattr(r, c))))
    print(f"참고: 지표 셀 {len(df) * 6}개 중 {lost}개가 소수점 2자리로 반올림됨 (DECIMAL(5,2)·(7,2) 스키마)")
    print("LOAD_BG_REGION", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
