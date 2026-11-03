"""2차 5.1 — SGIS 100m 격자 csv 15개 (raw/sgis_grid/<연도>/, CP949, 머리글 없음: 연도,격자코드,항목코드,값) → analysis.bg_grid_indicator.

항목: to_in_001 총인구 · to_in_007 남 · to_in_008 여 · to_ga_001 가구 · to_ho_001 주택 · to_fa_010 사업체 · to_em_020 종사자
dim_grid100 에 있는 격자만 넣고, 기록 없는 격자·항목은 0 (인수인계 5.1). 그 연도를 지우고 다시 넣는다.
실행 (infra/):  docker compose --profile data exec spark spark-submit pipeline/batch_bg_grid.py --year 2024 [--dry-run]
"""
import argparse
import os
import time

import pandas as pd
import psycopg
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, LongType, StringType, StructField, StructType

BUCKET = os.environ["MINIO_BUCKET"]
ITEMS = {"to_in_001": "pop_total", "to_in_007": "pop_male", "to_in_008": "pop_female", "to_ga_001": "households", "to_ho_001": "housing", "to_fa_010": "businesses", "to_em_020": "employees"}
COLS = list(ITEMS.values())
SCHEMA = StructType([StructField("year", IntegerType()), StructField("grid_cd", StringType()), StructField("item", StringType()), StructField("value", LongType())])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    spark = SparkSession.builder.appName("batch_bg_grid").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    raw = spark.read.schema(SCHEMA).option("encoding", "cp949").csv(f"s3a://{BUCKET}/raw/sgis_grid/{args.year}/")
    n_raw = raw.count()
    with psycopg.connect(os.environ["PIPELINE_DB_DSN"]) as conn:
        dim = pd.read_sql("SELECT grid_cd FROM analysis.dim_grid100", conn)
        grids = spark.createDataFrame(dim)
        agg = (raw.filter(F.col("year") == args.year).join(grids, "grid_cd")
                  .groupBy("grid_cd").pivot("item", list(ITEMS)).agg(F.sum("value")))
        pdf = agg.toPandas().rename(columns=ITEMS).set_index("grid_cd").reindex(dim.grid_cd).fillna(0).astype(int)
        print(f"[bg_grid] {args.year}: 원본 {n_raw:,}행 → dim_grid100 격자 {len(pdf):,} (기록 있음 {int((pdf.sum(axis=1) > 0).sum()):,}) | 합계 {pdf.sum().to_dict()} ({time.time() - t0:.0f}s)", flush=True)
        old = pd.read_sql(f"SELECT grid_cd, {', '.join(COLS)} FROM analysis.bg_grid_indicator WHERE ref_year = {args.year}", conn).set_index("grid_cd").reindex(dim.grid_cd)
        if len(old.dropna()):
            diff = {c: int((pdf[c] != old[c].astype(float)).sum()) for c in COLS}
            print(f"[bg_grid] 기존 적재값과 다른 격자 수: {diff}", flush=True)
        if args.dry_run:
            return 0
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analysis.bg_grid_indicator WHERE ref_year = %s", (args.year,))
            cur.executemany(f"INSERT INTO analysis.bg_grid_indicator (ref_year, grid_cd, {', '.join(COLS)}, updated_at) VALUES (%s, %s, {', '.join('%s' for _ in COLS)}, now())",
                            [(args.year, g, *[int(v) for v in r]) for g, r in zip(pdf.index, pdf[COLS].to_numpy())])
            cur.execute("SELECT count(*) FROM analysis.bg_grid_indicator WHERE ref_year = %s", (args.year,))
            n = cur.fetchone()[0]
        conn.commit()
    print(f"[bg_grid] bg_grid_indicator {n:,}행 적재", flush=True)
    spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
