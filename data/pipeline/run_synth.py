"""1차 4.6 — 제공 생성기(synth_flow/)를 MinIO 경로로 실행하는 래퍼.

infra/.env 의 MINIO_* 를 읽고, 입력은 4.4에서 올린 raw/ (SKT는 변환한 csv), 출력은 s3://<버킷>/synth 로 지정한 뒤
synth_flow/run.py 또는 replay.py 를 그대로 실행한다. 인자는 그대로 넘긴다.

  data/.venv/Scripts/python data/pipeline/run_synth.py all
  data/.venv/Scripts/python data/pipeline/run_synth.py generate --months 2025-12
  data/.venv/Scripts/python data/pipeline/run_synth.py replay --months 2025-12 --speed 10   # 2차
"""
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parents[1] / "infra" / ".env", override=False)
bucket = os.environ["MINIO_BUCKET"]
env = {
    **os.environ,
    "SKT_TIME": f"s3://{bucket}/raw/skt_flow_time/flow_time_pop_202507_202512.csv",
    "SKT_WKDY": f"s3://{bucket}/raw/skt_flow_wkdy/flow_wkdy_pop_202507_202512.csv",
    "SKT_AGE": f"s3://{bucket}/raw/skt_flow_age/flow_age_pop_202507_202512.csv",
    "GRID_FILE": f"s3://{bucket}/raw/dim_grid100.csv",
    "SYNTH_OUT": f"s3://{bucket}/synth",
    "PYTHONUTF8": "1",
}
args = sys.argv[1:]
script = "replay.py" if args and args[0] == "replay" else "run.py"
if script == "replay.py":
    args = args[1:]
    if "--bootstrap" not in args and os.environ.get("KAFKA_BOOTSTRAP"):   # 호스트용 Kafka 주소는 infra/.env 의 값
        args = ["--bootstrap", os.environ["KAFKA_BOOTSTRAP"], *args]
sys.exit(subprocess.call([sys.executable, script, *args], cwd=HERE / "synth_flow", env=env))
