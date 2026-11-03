"""[운영 · 월 배치 입력 확인 | pipeline 컨테이너] 그 달 원본이 MinIO 에 있는지 본다. 없으면 종료 코드 99 (Airflow 가 그 달을 skip).

확인하는 것
  - SKT 시간대 월평균 csv(raw/skt_flow_time/) 에 그 달(STD_YM) 행이 있는가  → 가상 유동 · 행동 지표의 원천
  - 주민등록 월간 파일(raw/resident_pop/, 이름의 YYYYMM_YYYYMM 구간)이 그 달을 덮는가 → 배경 상세의 원천
실거래가 API 는 확인하지 않는다 (원본이 없는 달에 API 를 부르지 않으려는 것이 이 검사의 목적).
실행  python3 pipeline/ops/check_month_inputs.py --months 2025-12 …   (종료 코드 0 있음 / 99 없음 / 1 오류)
"""
import argparse
import io
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
from common import check, minio_connect, months_arg, setup

SKT_TIME = "raw/skt_flow_time/flow_time_pop_202507_202512.csv"
NO_INPUT = 99


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", help="기준월 YYYY-MM 목록 (없으면 전월)")
    args = ap.parse_args()
    months = months_arg(args.months)
    fs, bucket = minio_connect()

    with fs.open(f"{bucket}/{SKT_TIME}", "rb") as f:
        skt_months = set(pd.read_csv(io.BytesIO(f.read()), usecols=["STD_YM"], dtype=str, encoding="utf-8-sig")["STD_YM"].unique())
    ranges = []
    for key in fs.glob(f"{bucket}/raw/resident_pop/*/*.csv"):
        m = re.search(r"(\d{6})[_~](\d{6})", key.rsplit("/", 1)[-1])
        if m:
            ranges.append((m.group(1), m.group(2)))

    ok = True
    for ym in months:
        has_skt = ym in skt_months
        has_res = any(a <= ym <= b for a, b in ranges)
        ok &= check(f"{ym[:4]}-{ym[4:]} SKT 월평균", has_skt, f"STD_YM {sorted(skt_months)[0]}~{sorted(skt_months)[-1]}")
        ok &= check(f"{ym[:4]}-{ym[4:]} 주민등록 월간", has_res, f"파일 구간 {sorted(set(ranges))}")
    if not ok:
        print(f"[check_inputs] 원본이 없는 달이 있어 이 실행을 건너뜁니다 (exit {NO_INPUT})", flush=True)
        return NO_INPUT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
