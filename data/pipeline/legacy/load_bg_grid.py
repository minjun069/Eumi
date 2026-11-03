"""[legacy · 1차 완성본 적재 | 호스트] grid100_sgis2024_강남춘천.csv (40,942행) → analysis.bg_grid_indicator (ref_year 2024, INT 7개).

- 정제 없이 값을 옮긴다. 기록 없는 격자는 완성본대로 0 (인수인계 5.1 규칙). 비율 등 나머지 컬럼은 넣지 않는다.
- grid_cd 는 모두 analysis.dim_grid100 에 있어야 한다 (먼저 load_dim_grid100.py).
실행  data/.venv/Scripts/python data/pipeline/legacy/load_bg_grid.py
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import random

import pandas as pd

from common import RAW_DIR, check, db_connect, setup

CSV = RAW_DIR / "final_sets" / "grid100_sgis2024_강남춘천.csv"
REF_YEAR = 2024
COLS = ["pop_total", "pop_male", "pop_female", "households", "housing", "businesses", "employees"]
EXPECTED_ROWS = 40_942
SQL = f"""
INSERT INTO analysis.bg_grid_indicator (ref_year, grid_cd, {', '.join(COLS)}, updated_at)
VALUES (%(ref_year)s, %(grid_cd)s, {', '.join(f'%({c})s' for c in COLS)}, now())
ON CONFLICT (ref_year, grid_cd) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in COLS)}, updated_at = now()
"""


def main() -> int:
    setup()
    argparse.ArgumentParser(description="1차 완성본 격자 배경 데이터셋 적재 (지금은 m2_process/batch_bg_grid.py 가 대체)").parse_args()  # 인자는 없지만 --help 가 실행으로 이어지지 않게
    df = pd.read_csv(CSV, encoding="utf-8-sig", dtype={"grid_cd": str, "adm_cd10": str, "adm_cd8": str, "sgg_cd": str})
    ok = check("행 수", len(df) == EXPECTED_ROWS, f"{len(df)}")
    ok &= check("grid_cd 유일", df["grid_cd"].is_unique, "")
    missing_cols = [c for c in COLS if c not in df.columns]
    ok &= check("INT 7개 컬럼 존재", not missing_cols, f"missing={missing_cols}" if missing_cols else "")
    if missing_cols:
        return 1
    nulls = {c: int(df[c].isna().sum()) for c in COLS if df[c].isna().any()}
    ok &= check("빈 값 없음", not nulls, str(nulls) if nulls else "")
    neg = {c: int((df[c] < 0).sum()) for c in COLS if (df[c] < 0).any()}
    ok &= check("음수 없음", not neg, str(neg) if neg else "")
    ok &= check("정수 값", all(pd.api.types.is_integer_dtype(df[c]) for c in COLS), str({c: str(df[c].dtype) for c in COLS}))

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT grid_cd FROM analysis.dim_grid100")
            known = {r[0] for r in cur.fetchall()}
            unknown = sorted(set(df["grid_cd"]) - known)
            ok &= check("grid_cd 가 dim_grid100 에 있음", not unknown, f"unknown={unknown[:5]}" if unknown else f"{len(known)}개 격자")
            if not ok:
                conn.rollback()
                print("적재하지 않음 (위 FAIL 확인)")
                return 1
            rows = [{"ref_year": REF_YEAR, "grid_cd": r.grid_cd, **{c: int(getattr(r, c)) for c in COLS}} for r in df.itertuples()]
            cur.executemany(SQL, rows)
            cur.execute(f"SELECT count(*), {', '.join(f'sum({c})' for c in COLS)} FROM analysis.bg_grid_indicator WHERE ref_year = %s", (REF_YEAR,))
            res = cur.fetchone()
            n, db_sums = res[0], dict(zip(COLS, (int(v) for v in res[1:])))
            random.seed(45)
            pick = df.iloc[random.randrange(len(df))]
            cur.execute(f"SELECT {', '.join(COLS)} FROM analysis.bg_grid_indicator WHERE ref_year = %s AND grid_cd = %s", (REF_YEAR, pick.grid_cd))
            db_row = cur.fetchone()
        conn.commit()

    src_sums = {c: int(df[c].sum()) for c in COLS}
    ok &= check("bg_grid_indicator 행 수", n == EXPECTED_ROWS, f"{n} (ref_year {REF_YEAR})")
    ok &= check("컬럼별 합계 = 원본 합계", db_sums == src_sums, str(db_sums))
    exp = tuple(int(pick[c]) for c in COLS)
    ok &= check(f"대조 격자 {pick.grid_cd} ({pick.dong_name})", db_row == exp, f"db={db_row}")
    zero = int((df[COLS].sum(axis=1) == 0).sum())
    print(f"참고: 7개 값이 모두 0인 격자 {zero:,}개 (SGIS 기록 없는 격자, 완성본대로 0)")
    print("LOAD_BG_GRID", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
