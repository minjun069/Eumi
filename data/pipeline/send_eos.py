"""2차 5.2 — 스트리밍의 마지막 하루 윈도를 닫는 종료 신호를 Kafka 에 보낸다 (호스트에서 실행).

  data/.venv/Scripts/python data/pipeline/send_eos.py --month 2025-12      # 다음 달 1일 02:00 KST 시각의 '_EOS' 메시지 1건
stream_flow_detail.py 는 이 메시지로 워터마크만 올리고 집계에는 넣지 않는다.
"""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from kafka import KafkaProducer

load_dotenv(Path(__file__).resolve().parents[2] / "infra" / ".env", override=False)
AGE_COLS = ["m_10", "m_20", "m_30", "m_40", "m_50", "m_60p", "f_10", "f_20", "f_30", "f_40", "f_50", "f_60p"]

ap = argparse.ArgumentParser()
ap.add_argument("--month", help="재생을 마친 달 (YYYY-MM) → 다음 달 1일 02:00")
ap.add_argument("--ts", help="직접 지정 (예: 2025-12-03T02:00:00+09:00, 마지막으로 재생한 날짜의 다음 날 02:00)")
a = ap.parse_args()
if a.ts:
    ts = a.ts
else:
    y, m = (int(x) for x in a.month.split("-"))
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    ts = f"{y:04d}-{m:02d}-01T02:00:00+09:00"
msg = {"ts": ts, "grid_cd": "_EOS", **{c: 0.0 for c in AGE_COLS}}
prod = KafkaProducer(bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092"),
                     key_serializer=lambda k: k.encode(), value_serializer=lambda v: json.dumps(v).encode())
prod.send(os.environ.get("KAFKA_TOPIC_FLOW", "flow_hourly"), key="_EOS", value=msg)
prod.flush()
print(f"EOS 발행: ts={ts}")
