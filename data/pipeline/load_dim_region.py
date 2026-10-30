"""1차 4.3 — 행정동 기준(public.dim_region) 적재.

입력  data/raw/adm_boundary/2025-07-01/HangJeongDong_ver20250701.geojson (vuski/admdongkor, 경위도 CRS84)
      data/raw/dim_grid100.csv (대상 동 47개와 adm_cd10 ↔ adm_cd8 대응을 여기서 얻는다)
처리  geojson의 adm_cd2(행안부 10자리)가 csv의 adm_cd10 에 있는 동만 고른다 → 강남구 22 + 춘천시 25.
      adm_cd8 은 geojson의 adm_cd(통계청 8자리)를 쓰되 csv 값과 같은지 검사한다.
      경계는 EPSG:4326 → EPSG:5179 로 변환해 GeoJSON MultiPolygon 문자열로 넣는다 (PostGIS 없음 → TEXT).
적재  UPSERT (INSERT ... ON CONFLICT (adm_cd10) DO UPDATE). eumi_pipeline 은 dim_region DELETE 권한이 없다.
실행  data/.venv/Scripts/python data/pipeline/load_dim_region.py [--srid 5179|4326]
"""
import argparse
import csv
import io
import json
import re
from collections import Counter

from pyproj import Transformer

from common import RAW_DIR, check, db_connect, setup

GEOJSON = RAW_DIR / "adm_boundary" / "2025-07-01" / "HangJeongDong_ver20250701.geojson"
GRID_CSV = RAW_DIR / "dim_grid100.csv"
UPSERT = """
INSERT INTO public.dim_region (adm_cd10, adm_cd8, adm_nm, sgg_nm, geom, updated_at)
VALUES (%(adm_cd10)s, %(adm_cd8)s, %(adm_nm)s, %(sgg_nm)s, %(geom)s, now())
ON CONFLICT (adm_cd10) DO UPDATE SET
    adm_cd8 = EXCLUDED.adm_cd8, adm_nm = EXCLUDED.adm_nm, sgg_nm = EXCLUDED.sgg_nm,
    geom = EXCLUDED.geom, updated_at = now()
"""


def read_code_map() -> dict:
    """csv → {adm_cd10: (adm_cd8, city)}"""
    with io.open(GRID_CSV, encoding="utf-8-sig", newline="") as f:
        pairs = {(r["adm_cd10"], r["adm_cd8"], r["city"]) for r in csv.DictReader(f)}
    out = {}
    for a10, a8, city in pairs:
        if a10 in out and out[a10] != (a8, city):
            raise SystemExit(f"dim_grid100.csv 에서 {a10} 의 adm_cd8/city 가 둘 이상입니다")
        out[a10] = (a8, city)
    return out


def to_multipolygon(geometry: dict, transform) -> dict:
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    out = []
    for poly in polys:
        rings = []
        for ring in poly:
            xs, ys = transform([p[0] for p in ring], [p[1] for p in ring])
            rings.append([[round(x, 2), round(y, 2)] for x, y in zip(xs, ys)])
        out.append(rings)
    return {"type": "MultiPolygon", "coordinates": out}


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--srid", type=int, default=5179, help="geom 좌표계 (기본 5179, 웹 지도용이면 4326)")
    args = ap.parse_args()

    code_map = read_code_map()
    features = json.load(io.open(GEOJSON, encoding="utf-8"))["features"]
    picked = [f for f in features if f["properties"].get("adm_cd2") in code_map]
    ok = check("대상 동 47개 선택", len(picked) == 47 and len(code_map) == 47, f"geojson {len(picked)} / csv {len(code_map)}")

    if args.srid == 4326:
        transform = lambda xs, ys: (xs, ys)  # noqa: E731
    else:
        transform = Transformer.from_crs("EPSG:4326", f"EPSG:{args.srid}", always_xy=True).transform

    rows, mismatch = [], []
    for f in picked:
        pr = f["properties"]
        a10, a8_geo, sgg = pr["adm_cd2"], pr["adm_cd"], pr["sggnm"]
        a8_csv, city = code_map[a10]
        if a8_geo != a8_csv or sgg != city:
            mismatch.append((a10, a8_geo, a8_csv, sgg, city))
        adm_nm = re.sub(rf"^{re.escape(pr['sidonm'])}\s+{re.escape(sgg)}\s+", "", pr["adm_nm"])
        geom = json.dumps(to_multipolygon(f["geometry"], transform), separators=(",", ":"))
        rows.append({"adm_cd10": a10, "adm_cd8": a8_geo, "adm_nm": adm_nm, "sgg_nm": sgg, "geom": geom})
    ok &= check("코드·시군구명이 csv 와 일치", not mismatch, f"mismatch={mismatch}" if mismatch else "47개 모두 일치")
    counts = Counter(r["sgg_nm"] for r in rows)
    ok &= check("시군구별 동 수", counts == Counter({"강남구": 22, "춘천시": 25}), str(dict(counts)))
    if not ok:
        print("적재하지 않음 (위 FAIL 확인)")
        return 1

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT, rows)
            cur.execute("SELECT sgg_nm, count(*), count(geom), count(adm_cd8) FROM public.dim_region GROUP BY 1 ORDER BY 1")
            by_sgg = cur.fetchall()
            cur.execute("SELECT count(*) FROM public.dim_region")
            total = cur.fetchone()[0]
            cur.execute("SELECT adm_cd10, adm_cd8, adm_nm, sgg_nm, length(geom) FROM public.dim_region ORDER BY adm_cd10 LIMIT 3")
            sample = cur.fetchall()
        conn.commit()

    ok &= check("dim_region 행 수", total == 47, f"{total} (시군구, 행, geom, adm_cd8: {by_sgg})")
    print("sample:", sample)
    print(f"geom: EPSG:{args.srid} GeoJSON MultiPolygon, 좌표 소수점 2자리")
    print("LOAD_DIM_REGION", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
