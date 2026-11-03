"""[M2 유동 상세 스트리밍 | Spark 컨테이너] Kafka(flow_hourly) → analysis.flow_detail 스트리밍 누적 (Spark Structured Streaming).

메시지: 키 grid_cd, 값 JSON {"ts": "2025-12-01T08:00:00+09:00", "grid_cd": "다사575465", "m_10": …, "f_60p": …}
처리:   이벤트 시각(ts) 워터마크 1시간 → (grid_cd, ts) 중복 제거 → 하루(KST) 윈도 × 격자 × 시각으로 12칸 합
        → 하루 윈도가 닫히면(append) flow_agg.daily_to_detail 로 증분을 만들어 flow_detail 에 더한다. 날짜 단위라 day_count 가 정확하다.
주의:   하루 윈도는 다음 날 01:00 이후 메시지가 와야 닫힌다. 재생이 끝난 뒤 마지막 날을 닫으려면 send_eos.py 로 종료 신호를 보낸다
        (grid_cd '_EOS', 집계에서 제외). foreachBatch 는 DB 와 exactly-once 가 아니라서 재시작 시 마지막 배치가 두 번 더해질 수 있다
        → 그 달은 batch_flow_detail.py 로 다시 적재한다.
실행 (infra/):  docker compose --profile data exec spark spark-submit pipeline/m2_process/stream_flow_detail.py [--starting earliest|latest] [--trigger 5]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
import os
import time

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

from common.flow_agg import AGE_COLS, daily_to_detail, with_day_fields
from common.flow_detail_db import connect, upsert_increments

KAFKA = os.environ["KAFKA_BOOTSTRAP"]
TOPIC = os.environ.get("KAFKA_TOPIC_FLOW", "flow_hourly")
CHECKPOINT = os.environ.get("FLOW_CHECKPOINT", "/opt/eumi/checkpoint/flow_detail")
SCHEMA = StructType([StructField("ts", StringType()), StructField("grid_cd", StringType())]
                    + [StructField(c, DoubleType()) for c in AGE_COLS])


def sink(batch_df, batch_id: int) -> None:
    t0 = time.time()
    # 종료 신호(_EOS)는 여기서 뺀다. 집계 앞에서 거르면 옵티마이저가 필터를 워터마크 아래로 내려 워터마크가 올라가지 않는다
    rows_df = (batch_df.filter(F.col("grid_cd") != "_EOS")
                       .withColumn("ts", F.timestamp_seconds(F.unix_timestamp(F.col("window.start")) + F.col("h") * 3600)))
    detail = daily_to_detail(with_day_fields(rows_df)).cache()
    days = sorted(r[0].isoformat() for r in rows_df.select(F.to_date("window.start")).distinct().collect())
    if not days:
        return
    with connect() as conn:
        n = upsert_increments(conn, ((r.period_start, r.grid_cd, r.dim_type, r.dim_value, round(float(r.flow_sum), 4), int(r.day_count))
                                     for r in detail.toLocalIterator()))
        conn.commit()
    detail.unpersist()
    print(f"[stream] batch {batch_id}: 닫힌 날짜 {days} → flow_detail {n:,}행 누적 ({time.time() - t0:.1f}s)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--starting", default="earliest", choices=["earliest", "latest"])
    ap.add_argument("--trigger", type=int, default=5, help="마이크로배치 간격(초)")
    args = ap.parse_args()
    spark = SparkSession.builder.appName("stream_flow_detail").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    assert spark.conf.get("spark.sql.session.timeZone") == "Asia/Seoul"

    raw = (spark.readStream.format("kafka")
           .option("kafka.bootstrap.servers", KAFKA).option("subscribe", TOPIC)
           .option("startingOffsets", args.starting).option("maxOffsetsPerTrigger", 2_000_000)
           .load())
    msgs = (raw.select(F.from_json(F.col("value").cast("string"), SCHEMA).alias("m")).select("m.*")
               .withColumn("ts", F.col("ts").cast("timestamp"))
               .withWatermark("ts", "1 hour"))
    clean = msgs.dropDuplicates(["grid_cd", "ts"])
    # 하루 윈도를 KST 자정에 맞춘다 (window 는 UTC 기준이라 startTime 15시간 보정)
    hourly = (clean.groupBy(F.window("ts", "1 day", "1 day", "15 hours"), "grid_cd", F.hour("ts").alias("h"))
                   .agg(*[F.sum(c).alias(c) for c in AGE_COLS]))
    query = (hourly.writeStream.outputMode("append").foreachBatch(sink)
                   .option("checkpointLocation", CHECKPOINT)
                   .trigger(processingTime=f"{args.trigger} seconds").start())
    print(f"[stream] 시작: topic={TOPIC} starting={args.starting} checkpoint={CHECKPOINT}", flush=True)
    query.awaitTermination()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
