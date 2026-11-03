"""[기준 · 100m 격자 초기 적재 | 호스트] 100m 격자 기준(analysis.dim_grid100) 적재.

입력  data/raw/dim_grid100.csv  (grid_cd, adm_cd10, adm_cd8, gx, gy, city — adm_cd8·city 는 검증에만 쓰고 넣지 않는다)
검사  40,942행 · grid_cd 유일 · gx/gy 100의 배수 · adm_cd10 이 모두 public.dim_region 에 있음 (먼저 load_dim_region.py)
적재  UPSERT (INSERT ... ON CONFLICT (grid_cd) DO UPDATE). dim_grid100 은 다른 테이블이 참조하므로 UPSERT 로만 갱신한다.
실행  data/.venv/Scripts/python data/pipeline/ops/load_dim_grid100.py
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import csv
import io
import re
from collections import Counter

from common import RAW_DIR, check, db_connect, setup

GRID_CSV = RAW_DIR / "dim_grid100.csv"
EXPECTED_ROWS = 40_942
UPSERT = """
INSERT INTO analysis.dim_grid100 (grid_cd, adm_cd10, gx, gy, updated_at)
VALUES (%(grid_cd)s, %(adm_cd10)s, %(gx)s, %(gy)s, now())
ON CONFLICT (grid_cd) DO UPDATE SET
    adm_cd10 = EXCLUDED.adm_cd10, gx = EXCLUDED.gx, gy = EXCLUDED.gy, updated_at = now()
"""


def main() -> int:
    setup()
    argparse.ArgumentParser(description="100m 격자 기준 테이블 초기 적재 (raw/dim_grid100.csv → analysis.dim_grid100, UPSERT)").parse_args()  # 인자는 없지만 --help 가 실행으로 이어지지 않게
    with io.open(GRID_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["gx"], r["gy"] = int(r["gx"]), int(r["gy"])

    ok = check("행 수", len(rows) == EXPECTED_ROWS, f"{len(rows)} (기대 {EXPECTED_ROWS})")
    ok &= check("grid_cd 유일", len({r["grid_cd"] for r in rows}) == len(rows), "")
    bad_cd = [r["grid_cd"] for r in rows if not re.fullmatch(r"[가-힣]{2}\d{6}", r["grid_cd"])]
    ok &= check("grid_cd 형식 (문자2+숫자6)", not bad_cd, f"bad={bad_cd[:5]}" if bad_cd else "")
    bad_xy = [r["grid_cd"] for r in rows if r["gx"] % 100 or r["gy"] % 100]
    ok &= check("gx·gy 100의 배수", not bad_xy, f"bad={bad_xy[:5]}" if bad_xy else "")

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT adm_cd10, adm_cd8, sgg_nm FROM public.dim_region")
            region = {a10: (a8, sgg) for a10, a8, sgg in cur.fetchall()}
            missing = sorted({r["adm_cd10"] for r in rows} - set(region))
            ok &= check("adm_cd10 이 dim_region 에 있음", not missing, f"missing={missing}" if missing else f"{len(region)}개 동")
            mism = [r["grid_cd"] for r in rows if r["adm_cd10"] in region
                    and (region[r["adm_cd10"]][0] != r["adm_cd8"] or region[r["adm_cd10"]][1] != r["city"])]
            ok &= check("adm_cd8·city 가 dim_region 과 일치", not mism, f"mismatch={mism[:5]}" if mism else "")
            if not ok:
                conn.rollback()
                print("적재하지 않음 (위 FAIL 확인)")
                return 1

            cur.executemany(UPSERT, [{k: r[k] for k in ("grid_cd", "adm_cd10", "gx", "gy")} for r in rows])
            cur.execute("SELECT count(*) FROM analysis.dim_grid100")
            total = cur.fetchone()[0]
            cur.execute("""
                SELECT count(*) FROM analysis.dim_grid100 g
                LEFT JOIN public.dim_region r ON r.adm_cd10 = g.adm_cd10 WHERE r.adm_cd10 IS NULL""")
            orphans = cur.fetchone()[0]
            cur.execute("""
                SELECT r.sgg_nm, count(*) FROM analysis.dim_grid100 g
                JOIN public.dim_region r ON r.adm_cd10 = g.adm_cd10 GROUP BY 1 ORDER BY 1""")
            by_sgg = cur.fetchall()
        conn.commit()

    ok &= check("dim_grid100 행 수", total == EXPECTED_ROWS, f"{total}")
    ok &= check("dim_region 에 없는 격자", orphans == 0, f"{orphans}")
    expected_city = Counter(r["city"] for r in rows)
    ok &= check("시군구별 격자 수", dict(by_sgg) == dict(expected_city), f"{by_sgg}")
    print("LOAD_DIM_GRID100", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
