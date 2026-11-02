"""사용법:
  python run.py anchor   [--months 2025-07 2025-08 ...]
  python run.py generate [--months ...]
  python run.py validate [--months ...]
  python run.py all      [--months ...]
입력·출력 경로는 config.py 또는 환경변수(SKT_TIME, SKT_WKDY, SKT_AGE, GRID_FILE, SYNTH_OUT, MINIO_*)로 지정.
"""
import argparse
from config import MONTHS

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["anchor", "generate", "validate", "all"])
    ap.add_argument("--months", nargs="*", default=MONTHS)
    a = ap.parse_args()
    if a.step in ("anchor", "all"):
        import anchor; anchor.run(a.months)
    if a.step in ("generate", "all"):
        import generate; generate.run(a.months)
    if a.step in ("validate", "all"):
        import validate; validate.run(a.months)
