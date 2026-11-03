"""[M2 실거래가 적재 | 호스트] 실거래가 원본 XML + 단지 좌표 캐시 → analysis.re_apt_trade 적재.

- 입력: s3://<버킷>/raw/apt_trade, raw/apt_rent 의 원본 (collect_apt_trade.py), raw/apt_geocode/apt_geocode.csv (geocode_apt.py).
- 변환: 매매 → deal_type '매매', 거래금액 → price_10k. 전월세 → 월세 0 이면 '전세' 아니면 '월세', 보증금 → price_10k, 월세 → monthly_rent_10k.
  해제 거래(매매 cdealType='O') 제외. 전월세 API 에는 해제 항목이 없다. 전용면적은 소수 2자리로 반올림(DECIMAL(7,2)).
- 적재: V6 규칙대로 같은 계약월 행을 DELETE 한 뒤 INSERT (trade_id 는 DB 발급). 좌표가 없는 단지의 거래는 넣지 않고 건수를 남긴다.
- 검증: 넣은 행 수 = 원본 − 해제 − 좌표 없음, 월별 DB 행 수, 시군구별 건수.

실행  data/.venv/Scripts/python data/pipeline/m2_process/batch_re_apt_trade.py [--months 2025-07 …] [--dry-run]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
import datetime as dt
import io

import pandas as pd

from common.apt_api import KINDS, LAWD, minio, months_arg, read_raw_items
from common import check, db_connect, setup
from common.apt_api import GEOCODE_CACHE_KEY as CACHE_KEY, GEOCODE_GOOD as GOOD, read_csv

COLS = ["deal_type", "contract_date", "apt_name", "exclusive_area_m2", "floor", "build_year",
        "price_10k", "monthly_rent_10k", "lat", "lon", "adm_cd10"]


def to_int(s: str) -> int | None:
    s = s.replace(",", "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def to_row(it: dict, geo: dict) -> dict | None:
    """item → 테이블 행. 해제 거래나 좌표 없는 단지는 None."""
    if it["_kind"] == "trade" and it.get("cdealType", "").upper() == "O":
        return None
    g = geo.get(it.get("aptSeq", ""))
    if g is None:
        return None
    if it["_kind"] == "trade":
        deal_type, price, monthly = "매매", to_int(it.get("dealAmount", "")), None
    else:
        monthly = to_int(it.get("monthlyRent", "")) or 0
        deal_type, price = ("전세" if monthly == 0 else "월세"), to_int(it.get("deposit", ""))
    area = it.get("excluUseAr", "").strip()
    return {
        "deal_type": deal_type,
        "contract_date": dt.date(int(it["dealYear"]), int(it["dealMonth"]), int(it["dealDay"])),
        "apt_name": it.get("aptNm", "")[:100] or None,
        "exclusive_area_m2": round(float(area), 2) if area else None,
        "floor": to_int(it.get("floor", "")),
        "build_year": to_int(it.get("buildYear", "")),
        "price_10k": price,
        "monthly_rent_10k": monthly,
        "lat": g["lat"], "lon": g["lon"], "adm_cd10": g["adm_cd10"],
    }


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", help="계약월 YYYY-MM 목록 (없으면 전월)")
    ap.add_argument("--dry-run", action="store_true", help="DB 에 쓰지 않고 변환 · 검증만")
    args = ap.parse_args()
    months = months_arg(args.months)
    fs, bucket = minio()

    cache = read_csv(fs, f"{bucket}/{CACHE_KEY}")
    if cache is None:
        raise SystemExit("단지 좌표 캐시가 없습니다. geocode_apt.py 를 먼저 실행하세요")
    good = cache[cache["status"].isin(GOOD)]
    geo = {r.apt_seq: {"lat": float(r.lat), "lon": float(r.lon), "adm_cd10": r.adm_cd10} for r in good.itertuples()}

    ok = True
    with db_connect() as conn:
        for ym in months:
            first = dt.date(int(ym[:4]), int(ym[4:]), 1)
            nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            items, rows, cancelled, no_geo = [], [], 0, 0
            for kind in KINDS:
                for lawd in LAWD:
                    items += read_raw_items(fs, bucket, kind, ym, lawd)
            for it in items:
                row = to_row(it, geo)
                if row is None:
                    if it["_kind"] == "trade" and it.get("cdealType", "").upper() == "O":
                        cancelled += 1
                    else:
                        no_geo += 1
                    continue
                rows.append(row)
            df = pd.DataFrame(rows, columns=COLS)
            in_month = df["contract_date"].between(first, nxt - dt.timedelta(days=1)).all() if len(df) else True
            ok &= check(f"{ym} 변환", len(df) == len(items) - cancelled - no_geo and in_month,
                        f"원본 {len(items):,} − 해제 {cancelled} − 좌표없음 {no_geo} = {len(df):,} (계약일 모두 {ym} 안: {in_month})")
            by = df.groupby([df["adm_cd10"].str[:5].map({"11680": "강남구", "51110": "춘천시"}), "deal_type"]).size()
            print("  " + ", ".join(f"{a} {t} {n:,}" for (a, t), n in by.items()), flush=True)
            if args.dry_run:
                continue

            with conn.cursor() as cur:
                cur.execute("DELETE FROM analysis.re_apt_trade WHERE contract_date >= %s AND contract_date < %s", (first, nxt))
                deleted = cur.rowcount
                with cur.copy(f"COPY analysis.re_apt_trade ({', '.join(COLS)}) FROM STDIN") as cp:
                    for r in rows:  # DataFrame 을 거치면 NULL 섞인 정수 열이 실수로 바뀌므로 dict 그대로 쓴다
                        cp.write_row(tuple(r[c] for c in COLS))
                cur.execute("SELECT count(*) FROM analysis.re_apt_trade WHERE contract_date >= %s AND contract_date < %s", (first, nxt))
                n_db = cur.fetchone()[0]
            conn.commit()
            ok &= check(f"{ym} 적재", n_db == len(df), f"삭제 {deleted:,} → DB {n_db:,} 행")

        if not args.dry_run:
            with conn.cursor() as cur:
                cur.execute("""SELECT to_char(contract_date, 'YYYY-MM') ym, deal_type, count(*), round(avg(price_10k))
                               FROM analysis.re_apt_trade GROUP BY 1, 2 ORDER BY 1, 2""")
                print(pd.DataFrame(cur.fetchall(), columns=["월", "유형", "건수", "평균 금액(만원)"]).to_string(index=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
