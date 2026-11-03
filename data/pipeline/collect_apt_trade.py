"""2차 5.3 (M1-1) — 아파트 실거래가 API 수집: 응답 XML 을 손대지 않고 MinIO 에 보관한다.

시군구(강남구 11680 · 춘천시 51110) × 계약월 × 종류(매매 trade · 전월세 rent)마다 페이지 끝까지 받아
  s3://<버킷>/raw/apt_trade/<YYYYMM>/<LAWD>_p<NN>.xml      (매매 상세)
  s3://<버킷>/raw/apt_rent/<YYYYMM>/<LAWD>_p<NN>.xml       (전월세)
  …/<LAWD>_manifest.json                                  (totalCount · 페이지 수 · 받은 건수 · 수집 시각)
으로 저장한다. 이미 manifest 가 있고 --force 가 없으면 건너뛴다 (월 배치에서 재실행해도 안전).
받은 건수 = totalCount 인지 확인하고, 다르면 FAIL 로 끝낸다.

실행  data/.venv/Scripts/python data/pipeline/collect_apt_trade.py                      # 전월 한 달
      data/.venv/Scripts/python data/pipeline/collect_apt_trade.py --months 2025-07 2025-08 … 2025-12
      옵션 --lawd 11680 51110  --kinds trade rent  --force
"""
import argparse
import datetime as dt
import json
import math
import time

from apt_api import KINDS, LAWD, PAGE_SIZE, fetch_page, minio, months_arg, parse_items, raw_prefix
from common import check, setup


def collect(fs, bucket: str, kind: str, lawd: str, ym: str, force: bool) -> tuple[int, int]:
    """한 (종류, 시군구, 월)을 수집한다. (totalCount, 받은 건수)"""
    prefix = raw_prefix(bucket, kind, ym)
    manifest_key = f"{prefix}/{lawd}_manifest.json"
    if not force and fs.exists(manifest_key):
        with fs.open(manifest_key, "r", encoding="utf-8") as f:
            m = json.load(f)
        print(f"  {kind} {lawd} {ym}: 있음 (건너뜀) total={m['total_count']} rows={m['rows']}", flush=True)
        return m["total_count"], m["rows"]

    for old in fs.glob(f"{prefix}/{lawd}_p*.xml"):  # 다시 받을 때 지난 페이지가 남지 않게
        fs.rm(old)

    total, rows, page = None, 0, 1
    while True:
        body = fetch_page(kind, lawd, ym, page)
        page_total, items = parse_items(body)
        total = page_total if total is None else total
        with fs.open(f"{prefix}/{lawd}_p{page:02d}.xml", "wb") as f:
            f.write(body)
        rows += len(items)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        if page >= pages or not items:
            break
        page += 1
        time.sleep(0.2)

    manifest = {
        "kind": kind, "lawd": lawd, "ym": ym, "total_count": total, "pages": page, "rows": rows,
        "page_size": PAGE_SIZE, "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    with fs.open(manifest_key, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"  {kind} {lawd} {ym}: total={total} rows={rows} pages={page}", flush=True)
    return total, rows


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", help="계약월 YYYY-MM 목록 (없으면 전월)")
    ap.add_argument("--lawd", nargs="*", default=list(LAWD), help="법정동 시군구 코드")
    ap.add_argument("--kinds", nargs="*", default=list(KINDS), choices=list(KINDS))
    ap.add_argument("--force", action="store_true", help="이미 받은 달도 다시 받는다")
    args = ap.parse_args()
    months = months_arg(args.months)
    fs, bucket = minio()

    ok = True
    summary: dict[str, int] = {}
    for ym in months:
        print(f"[{ym}]", flush=True)
        for kind in args.kinds:
            for lawd in args.lawd:
                total, rows = collect(fs, bucket, kind, lawd, ym, args.force)
                summary[f"{kind}/{lawd}/{ym}"] = rows
                ok &= check(f"{kind} {lawd} {ym} 받은 건수 = totalCount", rows == total, f"{rows} / {total}")
    print(f"합계 {sum(summary.values()):,}건 → s3://{bucket}/raw/apt_trade, raw/apt_rent")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
