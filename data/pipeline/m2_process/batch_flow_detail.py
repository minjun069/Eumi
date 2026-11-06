"""[M2 유동 상세 월 배치 | Spark 컨테이너] 가상 유동 Parquet(synth/flow_hourly) → analysis.flow_detail 월 배치 적재 (Kafka 를 거치지 않는 과거분 적재용).

그 달 행을 지운 뒤 월 전체를 집계해 넣는다 (한 달이 통째로 들어오므로 day_count 가 정확하다).
실행 (infra/):  docker compose --profile data exec pipeline spark-submit pipeline/m2_process/batch_flow_detail.py --months 2025-07 2025-08
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
import os
import time

from pyspark.sql import SparkSession

from common.flow_agg import daily_to_detail, with_day_fields
from common.flow_detail_db import connect, delete_months, upsert_increments

BUCKET = os.environ["MINIO_BUCKET"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="+", required=True)
    args = ap.parse_args()
    spark = SparkSession.builder.appName("batch_flow_detail").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    assert spark.conf.get("spark.sql.session.timeZone") == "Asia/Seoul"

    for m in args.months:
        t0 = time.time()
        src = f"s3a://{BUCKET}/synth/flow_hourly/period={m}"
        df = with_day_fields(spark.read.parquet(src))
        detail = daily_to_detail(df).filter(f"period_start = date '{m}-01'")
        rows = detail.toLocalIterator()
        with connect() as conn:
            deleted = delete_months(conn, [f"{m}-01"])
            n = upsert_increments(conn, ((r.period_start, r.grid_cd, r.dim_type, r.dim_value, round(float(r.flow_sum), 4), int(r.day_count)) for r in rows))
            conn.commit()
        print(f"[batch_flow_detail] {m}: 기존 {deleted:,}행 삭제 → {n:,}행 적재 ({time.time() - t0:.0f}s)", flush=True)
    spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
