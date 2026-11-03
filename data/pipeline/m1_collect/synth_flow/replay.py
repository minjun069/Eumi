"""시연용 재생기: flow_hourly Parquet를 시각 순서대로 Kafka에 발행한다.

  python replay.py --months 2025-12 --topic flow_hourly --bootstrap localhost:9092 --speed 60
  --speed 60 : 데이터 1시간치를 60초마다 발행 (실시간의 60배). 0이면 쉬지 않고 전부 밀어 넣음.
메시지 키 = grid_cd, 값 = JSON {"ts": ..., "grid_cd": ..., "m_10": ..., ..., "f_60p": ...}
"""
import argparse, json, time
import pandas as pd
from config import HOURLY_DIR, AGE_COLS, MONTHS
from io_util import read_parquet, list_files

def iter_hours(months, days=None):
    for p in months:
        for f in list_files(f"{HOURLY_DIR}/period={p}"):
            if days and f.rsplit("day=", 1)[-1].split(".")[0] not in days:   # --days 로 날짜를 고를 때
                continue
            df = read_parquet(f)
            for ts, g in df.groupby("ts", sort=True):
                yield ts, g

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", default=MONTHS)
    ap.add_argument("--topic", default="flow_hourly")
    ap.add_argument("--bootstrap", default="localhost:9092")
    ap.add_argument("--speed", type=float, default=0, help="1시간치 발행 간격(초). 0 = 대기 없음")
    ap.add_argument("--days", nargs="*", help="재생할 날짜 DD 목록 (없으면 그 달 전부). 예: --days 01 02")
    a = ap.parse_args()
    from kafka import KafkaProducer   # pip install kafka-python
    prod = KafkaProducer(bootstrap_servers=a.bootstrap, key_serializer=lambda k: k.encode(),
                         value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode(), linger_ms=20, batch_size=256 * 1024)
    n = 0
    for ts, g in iter_hours(a.months, a.days):
        t0 = time.time()
        ts_str = pd.Timestamp(ts).isoformat()
        for row in g.itertuples(index=False):
            msg = {"ts": ts_str, "grid_cd": row.grid_cd, **{c: round(float(getattr(row, c)), 4) for c in AGE_COLS}}
            prod.send(a.topic, key=row.grid_cd, value=msg)
        prod.flush(); n += len(g)
        print(f"{ts_str}  {len(g):,}건 발행 (누적 {n:,})", flush=True)
        if a.speed > 0:
            time.sleep(max(0, a.speed - (time.time() - t0)))

if __name__ == "__main__":
    main()
