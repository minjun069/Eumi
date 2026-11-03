"""[운영 · 월 배치 실행기 | 호스트] README "월 배치 순서" 13단계를 순서대로 실행한다.

호스트 단계는 이 venv 로, 컨테이너 단계는 `docker compose --profile data exec pipeline …` 로 돌린다.
한 단계가 실패(종료 코드 ≠ 0)하면 거기서 멈추고 요약을 찍는다. 실행 요약은 data/processed/run_log/run_<시각>.json 에도 남긴다.

실행  data/.venv/Scripts/python data/pipeline/ops/run_month.py [--months 2025-12 …]   # 없으면 전월
      --list            단계 목록만
      --from 8 --to 12  8~12단계만,  --only 11 12  지정 단계만,  --skip 3  건너뛰기
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
from common import REPO_ROOT, months_arg, setup

COMPOSE = ["docker", "compose", "-f", str(REPO_ROOT / "infra" / "docker-compose.yml"), "--profile", "data", "exec", "-T", "pipeline"]
LOG_DIR = REPO_ROOT / "data" / "processed" / "run_log"

# (번호, 모듈, 설명, 실행 위치, 스크립트, 월 인자 방식)
#  위치: host | spark-python | spark-submit      월 인자: months(--months …) | none
STEPS = [
    (1, "M1-1", "실거래가 API 수집 → raw/apt_trade · raw/apt_rent", "host", "m1_collect/collect_apt_trade.py", "months"),
    (2, "M1-1", "단지 지오코딩 캐시 갱신", "host", "m1_collect/geocode_apt.py", "months"),
    (3, "M1-2", "가상 유동 anchor → generate → validate", "host", "m1_collect/run_synth.py", "synth"),
    (4, "M2", "Parquet → flow_detail", "spark-submit", "m2_process/batch_flow_detail.py", "months"),
    (5, "M2", "flow_detail 월평균 = anchor 검증", "spark-submit", "m2_process/verify_flow_detail.py", "months"),
    (6, "M2-2", "배경 원본 → bg_region_detail", "spark-python", "m2_process/batch_bg_detail.py", "months"),
    (7, "M2", "실거래가 XML + 좌표 → re_apt_trade", "host", "m2_process/batch_re_apt_trade.py", "months"),
    (8, "M3-1", "bg_region_detail → bg_region_indicator", "spark-python", "m3_indicator/batch_bg_indicators.py", "months"),
    (9, "M3-3", "flow_detail → bh_grid_indicator", "spark-python", "m3_indicator/batch_bh_grid_indicators.py", "months"),
    (10, "M3-2", "flow_detail + bg_region_detail → bh_region_indicator", "spark-python", "m3_indicator/batch_bh_region_indicators.py", "months"),
    (11, "M4", "배경 · 행동 지표 → region_result (점수 · 등급 · 위험단계)", "host", "m4_analysis/batch_region_result.py", "months"),
    (12, "M4-3", "bh_grid_indicator → bh_grid_anomaly", "host", "m4_analysis/batch_grid_anomaly.py", "months"),
    (13, "운영", "결과 테이블 → db/seed/R__*.sql", "host", "ops/make_seed.py", "none"),
]


def commands(step, months: list[str]) -> list[list[str]]:
    no, _, _, where, script, marg = step
    if where == "host":
        base = [sys.executable, "-X", "utf8", str(REPO_ROOT / "data" / "pipeline" / script)]
    else:
        base = COMPOSE + [("spark-submit" if where == "spark-submit" else "python3"), f"pipeline/{script}"]
    if marg == "synth":
        return [base + [stage, "--months", *months] for stage in ("anchor", "generate", "validate")]
    return [base + (["--months", *months] if marg == "months" else [])]


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*", help="기준월 YYYY-MM 목록 (없으면 전월)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--to", dest="end", type=int, default=len(STEPS))
    ap.add_argument("--only", nargs="*", type=int)
    ap.add_argument("--skip", nargs="*", type=int, default=[])
    args = ap.parse_args()
    months = [f"{m[:4]}-{m[4:]}" for m in months_arg(args.months)]
    selected = [s for s in STEPS if (args.only and s[0] in args.only) or (not args.only and args.start <= s[0] <= args.end)]
    selected = [s for s in selected if s[0] not in args.skip]
    if args.list:
        for no, mod, desc, where, script, _ in STEPS:
            print(f"{no:2d}  {mod:5s} {where:13s} {script:48s} {desc}")
        return 0

    print(f"[run_month] 기준월 {months} | 단계 {[s[0] for s in selected]} | 시작 {dt.datetime.now():%H:%M:%S}", flush=True)
    results, ok = [], True
    for step in selected:
        no, mod, desc, where, script, _ = step
        t0 = time.time()
        print(f"\n===== {no:2d}. [{mod}] {desc}  ({where}, {script}) =====", flush=True)
        code = 0
        for cmd in commands(step, months):
            code = subprocess.run(cmd, cwd=REPO_ROOT).returncode
            if code != 0:
                break
        sec = time.time() - t0
        results.append({"step": no, "module": mod, "script": script, "seconds": round(sec), "exit_code": code})
        print(f"----- {no:2d}. {'OK' if code == 0 else f'FAIL (exit {code})'}  {sec:.0f}s", flush=True)
        if code != 0:
            ok = False
            break

    print(f"\n[run_month] 요약 ({'성공' if ok else '실패'}, 총 {sum(r['seconds'] for r in results)}s)", flush=True)
    for r in results:
        print(f"  {r['step']:2d}. {r['script']:48s} {r['seconds']:5d}s  {'OK' if r['exit_code'] == 0 else 'FAIL'}", flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"run_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    log.write_text(json.dumps({"months": months, "started": dt.datetime.now().isoformat(timespec="seconds"), "success": ok, "steps": results},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[run_month] 기록 {log}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
