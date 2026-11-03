"""2차 5.1 공통 — MinIO raw/ 의 배경 원본을 읽어 동 × 월 × 항목 원값(bg_region_detail 형태)으로 만든다.

소스와 규칙 (1차 완성본 배경데이터셋_최종.xlsm 과 같은 결과가 나오도록):
  주민등록 (raw/resident_pop, 행정동 10자리, 월간)  → pop_total · pop_male · 남녀 5세 구간(0~64) 26개
  등록센서스 (raw/census, 통계청 8자리, 2025 연간)   → 가구원수별 가구 7개 · 주택 유형 9개. 비공개 'X' 는 행 합계식·시군구 합계식으로
                                                      역산한다(미확정 1개면 나머지 값, 나머지가 0이면 전부 0). 못 풀면 NULL (행 생략)
  공원 · 정류장 (패키지 매핑표 park_allocations · bus_stops, 스냅샷) → park_area_m2 · bus_stop_cnt, 매달 반복
  동 면적 (raw/adm_boundary geojson, EPSG:5179 면적)  → area_km2, 매달 반복
"""
import csv
import io
import json
import os
import re

import numpy as np
import pandas as pd
import pyarrow.fs as pafs

BUCKET = os.environ["MINIO_BUCKET"]
PKG = "raw/model_package/dual_analysis_reproducible_20261102/analysis/background_checks/data/environment"
MONTHS = ["2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
BANDS = ["0~4세", "5~9세", "10~14세", "15~19세", "20~24세", "25~29세", "30~34세", "35~39세", "40~44세", "45~49세", "50~54세", "55~59세", "60~64세"]
HH = {"일반가구_계 (가구)": "hh_total", "1인 (가구)": "hh_size_1", "2인 (가구)": "hh_size_2", "3인 (가구)": "hh_size_3",
      "4인 (가구)": "hh_size_4", "5인 (가구)": "hh_size_5", "6인 이상 (가구)": "hh_size_6P"}
HO = {"주택_계": "house_total", "단독주택_계": "house_detached_total", "단독주택_일반": "house_detached_general",
      "단독주택_다가구": "house_detached_multi", "단독주택_영업겸용": "house_detached_mixed", "아파트": "house_apt",
      "연립주택": "house_row", "다세대주택": "house_multi", "비주거용 건물 내 주택": "house_nonres"}
IDENTITIES = {  # 총계 항목: 구성 항목 (행 합계식)
    "hh_total": ["hh_size_1", "hh_size_2", "hh_size_3", "hh_size_4", "hh_size_5", "hh_size_6P"],
    "house_total": ["house_detached_total", "house_apt", "house_row", "house_multi", "house_nonres"],
    "house_detached_total": ["house_detached_general", "house_detached_multi", "house_detached_mixed"],
}


def s3():
    ep = os.environ["MINIO_ENDPOINT"].replace("http://", "").replace("https://", "")
    key = os.environ.get("MINIO_ACCESS_KEY") or os.environ["AWS_ACCESS_KEY_ID"]        # Spark 컨테이너는 AWS_* 이름으로 받는다
    secret = os.environ.get("MINIO_SECRET_KEY") or os.environ["AWS_SECRET_ACCESS_KEY"]
    return pafs.S3FileSystem(access_key=key, secret_key=secret, endpoint_override=ep, scheme="http", region="us-east-1")


def read_text(fs, key, encoding):
    with fs.open_input_stream(f"{BUCKET}/{key}") as f:
        return f.read().decode(encoding)


def list_keys(fs, prefix):
    sel = pafs.FileSelector(f"{BUCKET}/{prefix}", recursive=True)
    return [i.path[len(BUCKET) + 1:] for i in fs.get_file_info(sel) if i.is_file]


def resident(fs, dongs):
    """주민등록 → {(adm_cd10, month, item_cd): value}"""
    out = {}
    for key in list_keys(fs, "raw/resident_pop"):
        if "연령별인구현황_월간" not in key:
            continue
        rows = list(csv.reader(io.StringIO(read_text(fs, key, "cp949"))))
        hdr = rows[0]
        for r in rows[1:]:
            m = re.search(r"\((\d{10})\)", r[0])
            if not m or m.group(1) not in dongs:
                continue
            for h, v in zip(hdr[1:], r[1:]):
                ym, grp, band = h.split("_", 2)
                month = f"{ym[:4]}-{ym[5:7]}"
                val = float(v.replace(",", ""))
                if grp == "계" and band == "총인구수":
                    out[(m.group(1), month, "pop_total")] = val
                elif grp == "남" and band == "총인구수":
                    out[(m.group(1), month, "pop_male")] = val
                elif grp in ("남", "여") and band in BANDS:
                    lo, hi = band.replace("세", "").split("~")
                    out[(m.group(1), month, f"pop_{'M' if grp == '남' else 'F'}_{int(lo):02d}_{int(hi):02d}")] = val
    return out


def kosis(fs, key, colmap, a8to10):
    rows = list(csv.reader(io.StringIO(read_text(fs, key, "cp949"))))
    i = next(k for k, r in enumerate(rows) if r and r[0].startswith("C행정구역별"))
    df = pd.DataFrame(rows[i + 1:], columns=rows[i])
    df["code"] = df.iloc[:, 0].str.strip("'")
    df = df.rename(columns=colmap)[["code"] + list(colmap.values())]
    for c in colmap.values():
        df[c] = pd.to_numeric(df[c], errors="coerce")   # 'X' → NaN
    dong = df[df.code.isin(a8to10)].copy()
    dong["adm_cd10"] = dong.code.map(a8to10)
    sgg = df[df.code.isin({c[:5] for c in a8to10})].copy()   # 시군구 합계 행 (5자리)
    return dong.set_index("adm_cd10")[list(colmap.values())], sgg.set_index("code")[list(colmap.values())]


def restore(dong: pd.DataFrame, sgg: pd.DataFrame, identities: dict, sgg_map: dict):
    """비공개 셀 역산. 행 합계식(총계 = Σ구성)과 열 합계식(시군구 = Σ동)을 더 풀 수 없을 때까지 반복한다.
    sgg_map: {KOSIS 시군구 5자리: 행안부 코드 앞 5자리} (예: '11230' → '11680')."""
    d = dong.copy()
    log = []
    changed = True
    while changed:
        changed = False
        for total, parts in identities.items():
            cols = [total] + parts
            for a, row in d[cols].iterrows():
                miss = [c for c in cols if pd.isna(row[c])]
                if not miss:
                    continue
                if total in miss:
                    if len(miss) == 1:
                        d.at[a, total] = row[parts].sum(); changed = True; log.append((a, total, "row"))
                    continue
                rem = row[total] - row[[c for c in parts if c not in miss]].sum()
                if len(miss) == 1 or rem == 0:
                    for c in miss:
                        d.at[a, c] = rem if len(miss) == 1 else 0.0
                        log.append((a, c, "row"))
                    changed = True
        for c in d.columns:   # 열 합계식: 시군구 합계 = Σ 그 시군구 동
            for sg, pre in sgg_map.items():
                if sg not in sgg.index:
                    continue
                sub = d[d.index.str.startswith(pre)][c]
                miss = sub[sub.isna()].index.tolist()
                if not miss or pd.isna(sgg.at[sg, c]):
                    continue
                rem = sgg.at[sg, c] - sub.dropna().sum()
                if len(miss) == 1 or rem == 0:
                    for a in miss:
                        d.at[a, c] = rem if len(miss) == 1 else 0.0
                        log.append((a, c, "sgg"))
                    changed = True
    return d, log


def census(fs, a8to10):
    hh, hh_s = kosis(fs, "raw/census/2025/가구형태_읍면동별_2025.csv", HH, a8to10)
    ho, ho_s = kosis(fs, "raw/census/2025/읍면동별 주거형태.csv", HO, a8to10)
    sgg_map = {a8[:5]: a10[:5] for a8, a10 in a8to10.items()}
    hh, log1 = restore(hh, hh_s, {"hh_total": IDENTITIES["hh_total"]}, sgg_map)
    ho, log2 = restore(ho, ho_s, {k: IDENTITIES[k] for k in ("house_total", "house_detached_total")}, sgg_map)
    return pd.concat([hh, ho], axis=1), log1 + log2


def environment(fs, dongs):
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform
    pa = pd.read_csv(io.StringIO(read_text(fs, f"{PKG}/park_allocations.csv", "utf-8-sig")), dtype={"adm_cd": str})
    park = pa.groupby("adm_cd").allocated_area_m2.sum()
    bs = pd.read_csv(io.StringIO(read_text(fs, f"{PKG}/bus_stops.csv", "utf-8-sig")), dtype={"adm_cd": str})
    bus = bs[bs.status == "included"].groupby("adm_cd").canonical_stop_id.nunique()
    gj = json.loads(read_text(fs, "raw/adm_boundary/2025-07-01/HangJeongDong_ver20250701.geojson", "utf-8"))
    tr = Transformer.from_crs(4326, 5179, always_xy=True).transform
    area = {f["properties"]["adm_cd2"]: transform(tr, shape(f["geometry"])).area / 1e6
            for f in gj["features"] if f["properties"]["adm_cd2"] in dongs}
    return pd.DataFrame({"park_area_m2": pd.Series({a: float(park.get(a, 0.0)) for a in dongs}),
                         "bus_stop_cnt": pd.Series({a: float(bus.get(a, 0)) for a in dongs}),
                         "area_km2": pd.Series(area)})


def build_detail(region: pd.DataFrame):
    """region: dim_region (adm_cd10, adm_cd8) → (DataFrame[period_start, adm_cd10, item_cd, value], 복원 로그)"""
    fs = s3()
    dongs = set(region.adm_cd10)
    a8to10 = dict(zip(region.adm_cd8, region.adm_cd10))
    rec = resident(fs, dongs)
    annual, log = census(fs, a8to10)
    env = environment(fs, dongs)
    rows = [{"period_start": f"{m}-01", "adm_cd10": a, "item_cd": i, "value": v} for (a, m, i), v in rec.items()]
    for a in sorted(dongs):
        for m in MONTHS:
            for c in annual.columns:
                v = annual.at[a, c] if a in annual.index else np.nan
                if not pd.isna(v):
                    rows.append({"period_start": f"{m}-01", "adm_cd10": a, "item_cd": c, "value": float(v)})
            for c in env.columns:
                rows.append({"period_start": f"{m}-01", "adm_cd10": a, "item_cd": c, "value": float(env.at[a, c])})
    return pd.DataFrame(rows), log
