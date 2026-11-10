"""[M2 유동 상세 스트리밍 | Spark 컨테이너] Kafka(flow_hourly) → analysis.flow_detail 스트리밍 누적 (Spark Structured Streaming).

메시지: 키 grid_cd, 값 JSON {"ts": "2025-12-01T08:00:00+09:00", "grid_cd": "다사575465", "m_10": …, "f_60p": …}
처리:   이벤트 시각(ts) 워터마크 1시간 → (grid_cd, ts) 중복 제거 → 하루(KST) 윈도 × 격자 × 시각으로 12칸 합
        → 하루 윈도가 닫히면(append) flow_agg.daily_to_detail 로 증분을 만들어 flow_detail 에 더한다. 날짜 단위라 day_count 가 정확하다.
주의:   하루 윈도는 다음 날 01:00 이후 메시지가 와야 닫힌다. 재생이 끝난 뒤 마지막 날을 닫으려면 send_eos.py 로 종료 신호를 보낸다
        (grid_cd '_EOS', 집계에서 제외). foreachBatch 는 DB 와 exactly-once 가 아니라서 재시작 시 마지막 배치가 두 번 더해질 수 있다
        → 그 달은 batch_flow_detail.py 로 다시 적재한다.
진행 기록: 배치가 끝날 때마다(메시지가 없으면 약 10초마다) analysis.stream_progress 에 한 행을 남긴다
        (읽은 수 · 초당 수신/처리 · 밀린 메시지 · 데이터 시각 · 닫힌 날짜). Grafana "Eumi 스트리밍" 대시보드가 이 표를 읽는다.
        기록이 실패해도 스트림은 멈추지 않는다 (로그에 한 줄만 남긴다).
실행 (infra/):  docker compose --profile data exec pipeline spark-submit pipeline/m2_process/stream_flow_detail.py [--starting earliest|latest] [--trigger 5]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
import json
import os
import threading
import time

from kafka import KafkaConsumer, TopicPartition
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQueryListener
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

from common.flow_agg import AGE_COLS, daily_to_detail, with_day_fields
from common.flow_detail_db import connect, upsert_increments

KAFKA = os.environ["KAFKA_BOOTSTRAP"]
TOPIC = os.environ.get("KAFKA_TOPIC_FLOW", "flow_hourly")
CHECKPOINT = os.environ.get("FLOW_CHECKPOINT", "/opt/eumi/checkpoint/flow_detail")
SCHEMA = StructType([StructField("ts", StringType()), StructField("grid_cd", StringType())]
                    + [StructField(c, DoubleType()) for c in AGE_COLS])

PROGRESS_KEEP_DAYS = 7
PROGRESS_INSERT = """
INSERT INTO analysis.stream_progress
    (run_id, batch_id, input_rows, input_rps, processed_rps, lag_rows, event_time_max, watermark, duration_ms, state_rows, closed_days, loaded_rows)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::date[], %s)
"""
_SINK: dict = {}  # batch_id → (닫힌 날짜들, flow_detail 에 더한 행 수). sink 가 채우고 진행 기록이 가져간다


def _offsets(v) -> dict:
    """진행 정보의 오프셋 {토픽: {파티션: 위치}}. 버전에 따라 JSON 문자열로 오기도 한다."""
    return json.loads(v) if isinstance(v, str) else (v or {})


def progress_row(p: dict, lag_now=None) -> tuple:
    """Spark 진행 정보 한 건 → analysis.stream_progress 한 행. lag_now: 지금 Kafka 에 물어본 밀린 메시지 수 (없으면 Spark 가 준 값으로)."""
    src = (p.get("sources") or [{}])[0]
    end, latest = _offsets(src.get("endOffset")), _offsets(src.get("latestOffset"))
    lag = lag_now
    if lag is None and end and latest:
        # Spark 가 준 값: 배치를 계획할 때의 최신 위치 − 그 배치가 읽은 끝. 배치가 도는 동안 들어온 메시지는 빠져 있어 거의 항상 0 이다
        lag = sum(max(off - end.get(topic, {}).get(part, off), 0) for topic, parts in latest.items() for part, off in parts.items())
    event = p.get("eventTime") or {}
    watermark = event.get("watermark")
    if watermark and watermark.startswith("1970"):  # 첫 메시지를 보기 전의 초기값
        watermark = None
    days, loaded = _SINK.pop(p["batchId"], (None, None))
    return (p["runId"], p["batchId"], p.get("numInputRows", 0), p.get("inputRowsPerSecond"), p.get("processedRowsPerSecond"), lag,
            event.get("max"), watermark, (p.get("durationMs") or {}).get("triggerExecution"),
            sum(s.get("numRowsTotal", 0) for s in p.get("stateOperators") or []), days, loaded)


class ProgressRecorder(StreamingQueryListener):
    """배치가 끝날 때마다 진행 정보를 DB 에 남긴다. 메시지가 없어 쉬는 동안에는 Spark 가 약 10초마다 알려 주는 것을 0건 행으로 남긴다.
    하루 윈도를 flow_detail 에 더하는 배치는 오래 걸리므로 sink 가 시작할 때 '적재 중' 표시 행을 하나 더 남긴다 (mark_loading)."""

    def __init__(self) -> None:
        self.run_id = None    # 이번 실행 (스트림을 시작할 때마다 Spark 가 새로 준다)
        self.last = None      # 마지막으로 남긴 행 (쉬는 동안의 행이 배치 번호 · 워터마크 · 상태 행 수를 이어 쓴다)
        self.read_to = {}     # 파티션 → Spark 가 읽은 위치 (마지막 배치의 끝)
        self.consumer = None  # 최신 위치만 물어보는 Kafka 연결 (메시지는 읽지 않는다)
        self.lock = threading.Lock()  # 진행 알림과 sink 가 다른 스레드에서 온다. Kafka 연결은 한 번에 한 스레드만 쓴다

    def _lag_now(self):
        """지금 Kafka 최신 위치 − Spark 가 읽은 위치 (파티션 합). 배치가 도는 동안 쌓인 메시지까지 센다. 물어볼 수 없으면 None."""
        read_to = self.read_to
        if not read_to:
            return None
        try:
            with self.lock:
                if self.consumer is None:
                    self.consumer = KafkaConsumer(bootstrap_servers=KAFKA, group_id=None, enable_auto_commit=False)
                ends = self.consumer.end_offsets([TopicPartition(TOPIC, part) for part in read_to])
            return sum(max(off - read_to[tp.partition], 0) for tp, off in ends.items())
        except Exception as e:
            print(f"[stream] Kafka 최신 위치 조회 실패 (Spark 가 준 값으로 기록): {e}", flush=True)
            self.consumer = None
            return None

    def mark_loading(self, batch_id: int, days: list) -> None:
        """하루 윈도를 flow_detail 에 더하기 직전에 남기는 표시: 닫힌 날짜만 있고 더한 행 수는 없는 행.
        더하는 데 1분 가까이 걸리고 그동안은 진행 알림이 없어서, 화면이 '멈춤' 대신 '적재 중'으로 보이게 한다."""
        last = self.last
        self._save((self.run_id or (last[0] if last else "unknown"), batch_id, 0, None, None, self._lag_now(), None,
                    last[7] if last else None, None, last[9] if last else None, days, None))

    def _save(self, row: tuple) -> None:
        try:  # 기록 실패가 스트림을 멈추면 안 된다
            with connect() as conn:
                conn.execute(PROGRESS_INSERT, row)
            self.last = row
        except Exception as e:
            print(f"[stream] 진행 기록 실패: {e}", flush=True)

    def onQueryStarted(self, event) -> None:
        self.run_id = str(event.runId)

    def onQueryProgress(self, event) -> None:
        p = json.loads(event.progress.json)
        self.run_id = p["runId"]
        end = _offsets((p.get("sources") or [{}])[0].get("endOffset")).get(TOPIC) or {}
        if end:
            self.read_to = {int(part): off for part, off in end.items()}
        self._save(progress_row(p, self._lag_now()))

    def onQueryIdle(self, event) -> None:
        last = self.last
        # 쉬는 중 = 읽을 메시지가 없었다 → 수신 · 처리 0. 밀린 메시지는 지금 다시 물어본다 (방금 들어온 것이 있으면 다음 배치가 읽는다)
        self._save((str(event.runId), last[1] if last else -1, 0, 0, 0, self._lag_now() or 0, None, last[7] if last else None, None,
                    last[9] if last else None, None, None))

    def onQueryTerminated(self, event) -> None:
        pass


RECORDER = ProgressRecorder()


def prune_progress() -> None:
    try:
        with connect() as conn:
            n = conn.execute("DELETE FROM analysis.stream_progress WHERE recorded_at < now() - make_interval(days => %s)",
                             (PROGRESS_KEEP_DAYS,)).rowcount
        print(f"[stream] 진행 기록: {PROGRESS_KEEP_DAYS}일 지난 {n:,}행 삭제", flush=True)
    except Exception as e:
        print(f"[stream] 진행 기록 정리 실패 (스트림은 계속): {e}", flush=True)


def sink(batch_df, batch_id: int) -> None:
    t0 = time.time()
    # 종료 신호(_EOS)는 여기서 뺀다. 집계 앞에서 거르면 옵티마이저가 필터를 워터마크 아래로 내려 워터마크가 올라가지 않는다
    rows_df = (batch_df.filter(F.col("grid_cd") != "_EOS")
                       .withColumn("ts", F.timestamp_seconds(F.unix_timestamp(F.col("window.start")) + F.col("h") * 3600)))
    detail = daily_to_detail(with_day_fields(rows_df)).cache()
    days = sorted(r[0].isoformat() for r in rows_df.select(F.to_date("window.start")).distinct().collect())
    if not days:
        return
    RECORDER.mark_loading(batch_id, days)
    with connect() as conn:
        n = upsert_increments(conn, ((r.period_start, r.grid_cd, r.dim_type, r.dim_value, round(float(r.flow_sum), 4), int(r.day_count))
                                     for r in detail.toLocalIterator()))
        conn.commit()
    detail.unpersist()
    _SINK[batch_id] = (days, n)
    print(f"[stream] batch {batch_id}: 닫힌 날짜 {days} → flow_detail {n:,}행 누적 ({time.time() - t0:.1f}s)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--starting", default="earliest", choices=["earliest", "latest"])
    ap.add_argument("--trigger", type=int, default=5, help="마이크로배치 간격(초)")
    args = ap.parse_args()
    spark = SparkSession.builder.appName("stream_flow_detail").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    assert spark.conf.get("spark.sql.session.timeZone") == "Asia/Seoul"
    prune_progress()
    spark.streams.addListener(RECORDER)

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
