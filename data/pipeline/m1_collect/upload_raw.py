"""[M1 수동 업로드 | 호스트] 원본 파일을 손대지 않고 MinIO 에 올린다.

- data/raw/ 아래 파일을 버킷 raw/<같은 경로> 로 미러링한다 (*.md 제외). 같은 크기로 이미 있으면 건너뛴다.
- SKT xlsx 2개(시간대별 · 요일별)는 csv 로도 변환해(data/processed/skt_csv/, utf-8-sig) 같은 폴더에 올린다. 값은 바꾸지 않는다.
- 끝나면 버킷 raw/ 목록을 받아 로컬과 파일 수 · 크기를 대조한다.
실행  data/.venv/Scripts/python data/pipeline/m1_collect/upload_raw.py [--no-convert]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
import os
from pathlib import Path

import pandas as pd

from common import REPO_ROOT, RAW_DIR, check, minio_connect as connect, setup

PROCESSED_DIR = REPO_ROOT / "data" / "processed" / "skt_csv"
SKT_XLSX = {  # 원본 상대경로 → csv 이름 (같은 폴더에 올린다)
    "skt_flow_time/flow_time_pop_202507_202512.xlsx": "flow_time_pop_202507_202512.csv",
    "skt_flow_wkdy/flow_wkdy_pop_202507_202512.xlsx": "flow_wkdy_pop_202507_202512.csv",
}
TEXT_COLS = {"STD_YM": str, "BLOCK_CD": str}  # 20자리 코드가 숫자로 바뀌지 않게


def convert_skt(rel: str, csv_name: str) -> Path:
    src = RAW_DIR / rel
    dst = PROCESSED_DIR / csv_name
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        print(f"  csv 있음 (건너뜀): {dst.name}", flush=True)
        return dst
    print(f"  xlsx → csv 변환 중: {src.name} (몇 분 걸림)", flush=True)
    df = pd.read_excel(src, sheet_name=0, dtype=TEXT_COLS)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(dst, index=False, encoding="utf-8-sig", lineterminator="\n")
    print(f"  {dst.name}: {len(df):,}행 × {df.shape[1]}열", flush=True)
    return dst


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-convert", action="store_true", help="SKT xlsx → csv 변환 생략")
    args = ap.parse_args()
    fs, bucket = connect()

    # 올릴 목록: (로컬 경로, 버킷 키)
    plan: list[tuple[Path, str]] = []
    for p in sorted(RAW_DIR.rglob("*")):
        if p.is_file() and p.suffix.lower() != ".md":
            plan.append((p, f"{bucket}/raw/{p.relative_to(RAW_DIR).as_posix()}"))
    if not args.no_convert:
        print("[SKT xlsx → csv]")
    for rel, csv_name in SKT_XLSX.items():
        csv_path = convert_skt(rel, csv_name) if not args.no_convert else PROCESSED_DIR / csv_name
        if csv_path.exists():   # --no-convert 라도 이미 변환해 둔 csv 는 대조 목록에 포함한다
            plan.append((csv_path, f"{bucket}/raw/{Path(rel).parent.as_posix()}/{csv_name}"))

    print(f"[업로드] {len(plan)}개 → s3://{bucket}/raw/")
    uploaded = skipped = 0
    for local, key in plan:
        size = local.stat().st_size
        if fs.exists(key) and fs.info(key)["size"] == size:
            skipped += 1
            continue
        fs.put(str(local), key)
        uploaded += 1
        print(f"  올림: {key.split('/', 1)[1]} ({size:,} B)", flush=True)
    print(f"  올림 {uploaded}, 이미 있어 건너뜀 {skipped}")

    # 대조: 버킷 raw/ 전체 목록 vs 계획한 목록
    fs.invalidate_cache()
    remote = {k: v["size"] for k, v in fs.find(f"{bucket}/raw", detail=True).items()}
    expected = {key: local.stat().st_size for local, key in plan}
    missing = sorted(set(expected) - set(remote))
    extra = sorted(set(remote) - set(expected))
    wrong = sorted(k for k in expected if k in remote and remote[k] != expected[k])
    ok = check("버킷 파일 수", len(remote) == len(expected), f"버킷 {len(remote)} / 로컬 {len(expected)}")
    ok &= check("빠진 파일", not missing, str(missing) if missing else "없음")
    ok &= check("크기 다른 파일", not wrong, str(wrong) if wrong else "없음")
    ok &= check("계획에 없는 파일", not extra, str(extra) if extra else "없음")
    total_mb = sum(expected.values()) / 1e6
    print(f"총 {len(expected)}개, {total_mb:,.1f} MB")
    print("UPLOAD_RAW", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
