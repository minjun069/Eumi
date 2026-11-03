"""[M1-1 지오코딩 | 호스트] 단지(aptSeq)별 지오코딩: Kakao 주소 검색 → WGS84 좌표 → dim_region 경계로 소속 행정동.

- 입력: MinIO 의 실거래가 원본 XML (collect_apt_trade.py 결과). 거래 건이 아니라 단지 일련번호(aptSeq) 단위로 한 번만 조회한다.
- 주소: 도로명(매매는 roadNm + 건물번호, 전월세는 roadnm 에 번호 포함) → 실패하면 지번(법정동 + jibun).
- 행정동: 좌표를 EPSG:5179 로 바꿔 dim_region.geom(GeoJSON) 포함 판정. 경계 밖이면 200m 안 가장 가까운 동(status=nearest).
- 결과 캐시: s3://<버킷>/raw/apt_geocode/apt_geocode.csv (있는 단지는 건너뜀).
  수동 보정: raw/apt_geocode/manual.csv (apt_seq, lon, lat) 가 있으면 그 좌표를 우선 쓴다 (status=manual).
- 키: infra/.env 의 KAKAO_REST_KEY. 쿼터는 일 10만 건, 여기서는 단지 수(수백) 만큼만 쓴다.

실행  data/.venv/Scripts/python data/pipeline/m1_collect/geocode_apt.py [--months 2025-07 …] [--retry-failed]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, shape

from common.apt_api import (GEOCODE_CACHE_KEY as CACHE_KEY, GEOCODE_GOOD as GOOD, GEOCODE_MANUAL_KEY as MANUAL_KEY,
                            LAWD, minio, months_arg, read_csv, read_raw_items)
from common import check, db_connect, setup

COLS = ["apt_seq", "lawd", "apt_nm", "query_used", "address_name", "lon", "lat", "adm_cd10", "adm_nm", "status", "geocoded_at"]
NEAREST_M = 200
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/address.json"


def addresses(item: dict) -> list[tuple[str, str]]:
    """item 에서 시도할 주소를 (종류, 주소) 순서대로. 도로명 먼저, 그다음 지번."""
    sido, sgg = LAWD[item["_lawd"]]
    out = []
    if item["_kind"] == "trade":
        road, bon, bu = item.get("roadNm", ""), item.get("roadNmBonbun", ""), item.get("roadNmBubun", "")
        if road and bon.strip("0"):
            num = str(int(bon)) + (f"-{int(bu)}" if bu and int(bu) else "")
            out.append(("road", f"{sido} {sgg} {road} {num}"))
    else:
        road = item.get("roadnm", "")
        if road:
            out.append(("road", f"{sido} {sgg} {road}"))
    umd, jibun = item.get("umdNm", ""), item.get("jibun", "")
    if umd and jibun:
        out.append(("jibun", f"{sido} {sgg} {umd} {jibun}"))
    return out


def kakao(query: str, key: str) -> dict | None:
    req = urllib.request.Request(
        KAKAO_URL + "?" + urllib.parse.urlencode({"query": query, "analyze_type": "exact", "size": 1}),
        headers={"Authorization": "KakaoAK " + key},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                docs = json.loads(r.read().decode("utf-8"))["documents"]
            return docs[0] if docs else None
        except urllib.error.HTTPError as e:
            if e.code in (400, 401):
                raise SystemExit(f"Kakao 응답 {e.code}: {e.read().decode('utf-8')[:200]} (KAKAO_REST_KEY 확인)")
            time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt)
    return None


def load_regions() -> list[tuple[str, str, str, object]]:
    """(adm_cd10, adm_nm, sgg_nm, shapely geometry in EPSG:5179)"""
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT adm_cd10, adm_nm, sgg_nm, geom FROM public.dim_region")
        return [(a, n, s, shape(json.loads(g))) for a, n, s, g in cur.fetchall()]


def locate(regions, to5179, lon: float, lat: float, sgg_expected: str) -> tuple[str, str, str]:
    """(adm_cd10, adm_nm, status). status: ok | nearest | outside | sgg_mismatch"""
    pt = Point(*to5179(lon, lat))
    for a, n, s, g in regions:
        if g.contains(pt):
            return (a, n, "ok") if s == sgg_expected else (a, n, "sgg_mismatch")
    a, n, s, d = min(((a, n, s, g.distance(pt)) for a, n, s, g in regions), key=lambda t: t[3])
    if d <= NEAREST_M and s == sgg_expected:
        return a, n, "nearest"
    return "", "", "outside"


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", help="원본을 읽을 계약월 (없으면 전월)")
    ap.add_argument("--retry-failed", action="store_true", help="이전에 실패한 단지도 다시 조회")
    args = ap.parse_args()
    key = os.environ.get("KAKAO_REST_KEY")
    if not key:
        raise SystemExit("KAKAO_REST_KEY 가 없습니다. infra/.env 를 확인하세요")
    fs, bucket = minio()

    # 1) 원본에서 단지별 대표 item (매매 item 을 우선: 도로명 구성요소가 완전)
    apts: dict[str, dict] = {}
    for ym in months_arg(args.months):
        for kind in ("trade", "rent"):
            for lawd in LAWD:
                for it in read_raw_items(fs, bucket, kind, ym, lawd):
                    seq = it.get("aptSeq", "")
                    if seq and (seq not in apts or (kind == "trade" and apts[seq]["_kind"] == "rent")):
                        apts[seq] = it
    print(f"단지 {len(apts):,}개 (원본 기준)", flush=True)

    # 2) 캐시 · 수동 보정
    cache = read_csv(fs, f"{bucket}/{CACHE_KEY}")
    cache = cache if cache is not None else pd.DataFrame(columns=COLS)
    done = set(cache.loc[cache["status"].isin(GOOD), "apt_seq"])
    if not args.retry_failed:
        done |= set(cache["apt_seq"])
    manual = read_csv(fs, f"{bucket}/{MANUAL_KEY}")
    manual = {r.apt_seq: (float(r.lon), float(r.lat)) for r in manual.itertuples()} if manual is not None else {}

    regions = load_regions()
    to5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True).transform
    now = dt.datetime.now().isoformat(timespec="seconds")
    new_rows, calls = [], 0
    for seq, it in sorted(apts.items()):
        if seq in done and seq not in manual:
            continue
        sgg = LAWD[it["_lawd"]][1]
        row = {"apt_seq": seq, "lawd": it["_lawd"], "apt_nm": it.get("aptNm", ""), "query_used": "", "address_name": "",
               "lon": "", "lat": "", "adm_cd10": "", "adm_nm": "", "status": "fail", "geocoded_at": now}
        if seq in manual:
            lon, lat = manual[seq]
            a, n, st = locate(regions, to5179, lon, lat, sgg)
            row.update(query_used="manual", lon=f"{lon:.7f}", lat=f"{lat:.7f}", adm_cd10=a, adm_nm=n,
                       status="manual" if st in ("ok", "nearest") else st)
        else:
            for how, q in addresses(it):
                doc = kakao(q, key)
                calls += 1
                time.sleep(0.05)
                if doc is None:
                    continue
                lon, lat = float(doc["x"]), float(doc["y"])
                a, n, st = locate(regions, to5179, lon, lat, sgg)
                row.update(query_used=f"{how}:{q}", address_name=doc["address_name"], lon=f"{lon:.7f}", lat=f"{lat:.7f}",
                           adm_cd10=a, adm_nm=n, status=st)
                if st in ("ok", "nearest"):
                    break
        new_rows.append(row)

    # 3) 캐시 갱신 (새 결과가 기존 행을 덮는다)
    if new_rows:
        new = pd.DataFrame(new_rows, columns=COLS)
        cache = pd.concat([cache[~cache["apt_seq"].isin(new["apt_seq"])], new], ignore_index=True)
        cache = cache.sort_values("apt_seq").reset_index(drop=True)
        with fs.open(f"{bucket}/{CACHE_KEY}", "wb") as f:
            f.write(cache.to_csv(index=False, lineterminator="\n").encode("utf-8-sig"))
    print(f"Kakao 호출 {calls}회, 새로 처리 {len(new_rows)}개 → s3://{bucket}/{CACHE_KEY}", flush=True)

    # 4) 검증: 원본에 나온 단지가 모두 캐시에 있고, 실패율을 기록
    sub = cache[cache["apt_seq"].isin(apts)]
    counts = sub["status"].value_counts().to_dict()
    good = int(sub["status"].isin(GOOD).sum())
    ok = check("원본 단지 모두 캐시에 있음", len(sub) == len(apts), f"{len(sub)} / {len(apts)}")
    ok &= check("좌표 · 행정동 확보율 ≥ 99%", good >= 0.99 * len(apts),
                f"{good}/{len(apts)} = {good / max(len(apts), 1):.2%} ({counts})")
    bad = sub[~sub["status"].isin(GOOD)]
    if len(bad):
        print("실패 단지 (manual.csv 로 보정 가능):")
        print(bad[["apt_seq", "lawd", "apt_nm", "query_used", "status"]].to_string(index=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
