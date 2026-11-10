"""[운영 · 스트리밍 시연 실행기 | 호스트] README "스트리밍 시연" 절차를 명령 하나로 돌린다.

  체크포인트 삭제 → 스트리밍 시작(백그라운드) → 재생 → 종료 신호 → 재생한 날짜가 모두 적재될 때까지 대기
  → 스트리밍 종료 → 그 달 flow_detail 을 월 배치로 되돌리고 검증
진행은 Grafana "Eumi 스트리밍"(http://localhost:3000/d/eumi-streaming)에서 본다.
중간에 실패하거나 Ctrl+C 로 끊어도 스트리밍을 끝내고 그 달을 되돌린다. 이미 도는 스트리밍이 있으면 건드리지 않고 멈춘다.

실행  data/.venv/Scripts/python data/pipeline/ops/run_stream_demo.py [--month 2025-12] [--days 01 02] [--speed 2]
      --days   재생할 날짜 DD 목록 (없으면 그 달 전부)
      --speed  1시간치 발행 간격(초). 기본 2, 0 이면 쉬지 않고 보낸다
      --keep   끝난 뒤 되돌리지 않는다. 시작할 때 그 달 flow_detail 을 비워 스트리밍한 값만 남긴다
               (이어서 M3 · M4 를 돌려 지표 · 단계가 바뀌는 것을 보일 때. 원래 값은 Airflow 에서 그 달을 수동 실행해 되돌린다)
"""
import argparse
import calendar
import collections
import datetime as dt
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
from common import REPO_ROOT, db_connect, setup
from common.flow_detail_db import delete_months

COMPOSE = ["docker", "compose", "-f", str(REPO_ROOT / "infra" / "docker-compose.yml"), "--profile", "data", "exec", "-T", "pipeline"]
CHECKPOINT = "/opt/eumi/checkpoint/flow_detail"
STREAM_SCRIPT = "pipeline/m2_process/stream_flow_detail.py"
STREAM_PROCESS = "SparkSubmit.*stream_flow_detail"   # Java 프로세스까지 끝내야 한다
DASHBOARD = "http://localhost:3000/d/eumi-streaming"
SPARK_LOG = re.compile(r"^\d\d/\d\d/\d\d \d\d:\d\d:\d\d (INFO|WARN) ")
LOADED = """
SELECT coalesce(sum(cardinality(closed_days)) FILTER (WHERE loaded_rows IS NOT NULL), 0), coalesce(sum(loaded_rows), 0), coalesce(sum(input_rows), 0)
FROM analysis.stream_progress WHERE recorded_at >= %s
"""


def say(msg: str) -> None:
    print(f"[stream_demo] {msg}", flush=True)


def run(cmd: list[str], quiet: bool = False) -> int:
    """pipeline 컨테이너 안에서 실행. quiet 이면 Spark 의 INFO · WARN 줄은 빼고 찍는다."""
    if not quiet:
        return subprocess.run(COMPOSE + cmd, cwd=REPO_ROOT).returncode
    proc = subprocess.Popen(COMPOSE + cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        if line.strip() and not SPARK_LOG.match(line):
            print("  " + line.rstrip(), flush=True)
    return proc.wait()


def stream_running() -> bool:
    return subprocess.run(COMPOSE + ["pgrep", "-f", STREAM_PROCESS], cwd=REPO_ROOT, capture_output=True).returncode == 0


def start_stream(conn, since) -> subprocess.Popen:
    """스트리밍을 띄우고, 첫 진행 기록이 남을 때까지 기다린다 (그 뒤에 보낸 메시지부터 읽는다)."""
    proc = subprocess.Popen(COMPOSE + ["spark-submit", STREAM_SCRIPT, "--starting", "latest"], cwd=REPO_ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    tail = collections.deque(maxlen=30)

    def pump() -> None:
        for line in proc.stdout:
            tail.append(line.rstrip())
            if "[stream]" in line:
                print("  " + line.rstrip(), flush=True)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("스트리밍이 시작하다 끝났습니다:\n" + "\n".join(tail))
        if conn.execute("SELECT count(*) FROM analysis.stream_progress WHERE recorded_at >= %s", (since,)).fetchone()[0] > 0:
            return proc
        time.sleep(2)
    raise RuntimeError("스트리밍이 3분 안에 준비되지 않았습니다:\n" + "\n".join(tail))


def stop_stream(proc: subprocess.Popen) -> None:
    subprocess.run(COMPOSE + ["pkill", "-f", STREAM_PROCESS], cwd=REPO_ROOT, capture_output=True)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    say("스트리밍 종료")


def wait_loaded(conn, since, expected: int, proc: subprocess.Popen, timeout: float) -> int:
    """재생한 날짜가 모두 flow_detail 에 더해질 때까지 진행 기록을 본다. 반환: 적재된 날짜 수."""
    done, deadline = -1, time.time() + timeout
    while time.time() < deadline:
        n, rows, _ = conn.execute(LOADED, (since,)).fetchone()
        if n != done:
            done = n
            say(f"적재 완료 {n}/{expected}일 (flow_detail +{rows:,}행)")
        if n >= expected:
            break
        if proc.poll() is not None:
            raise RuntimeError("적재를 기다리는 중에 스트리밍이 끝났습니다")
        time.sleep(3)
    return done


def month_total(conn, period_start: dt.date) -> tuple:
    return conn.execute("SELECT count(*), coalesce(sum(flow_sum), 0) FROM analysis.flow_detail WHERE period_start = %s", (period_start,)).fetchone()


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default="2025-12", help="재생할 달 YYYY-MM")
    ap.add_argument("--days", nargs="*", help="재생할 날짜 DD 목록 (없으면 그 달 전부)")
    ap.add_argument("--speed", type=float, default=2, help="1시간치 발행 간격(초). 0 = 대기 없음")
    ap.add_argument("--keep", action="store_true", help="끝난 뒤 되돌리지 않고 스트리밍한 값만 남긴다")
    args = ap.parse_args()
    year, mon = (int(x) for x in args.month.split("-"))
    period_start = dt.date(year, mon, 1)
    days = sorted({int(d) for d in args.days}) if args.days else list(range(1, calendar.monthrange(year, mon)[1] + 1))
    eos = f"{dt.date(year, mon, days[-1]) + dt.timedelta(days=1):%Y-%m-%d}T02:00:00+09:00"   # 마지막 날의 다음 날 02:00 → 마지막 하루 윈도를 닫는다

    if stream_running():
        say("이미 도는 스트리밍이 있습니다. 먼저 끝내세요: docker compose --profile data exec pipeline pkill -f \"SparkSubmit.*stream_flow_detail\"")
        return 1
    conn = db_connect()
    conn.autocommit = True
    since = conn.execute("SELECT now()").fetchone()[0]
    before = month_total(conn, period_start)
    say(f"{args.month} {len(days)}일치 · 1시간치마다 {args.speed:g}초 · 예상 약 {(len(days) * 24 * (args.speed + 1.4) + 90) / 60:.0f}분"
        f"{'' if args.keep else ' + 되돌리기 2분'} | 화면 {DASHBOARD}")

    t0, proc, touched, code = time.time(), None, False, 0
    try:
        run(["rm", "-rf", CHECKPOINT])   # 예전 체크포인트가 남으면 그 마감 시각 때문에 같은 날짜를 다시 받아도 버려진다
        if args.keep:
            touched = True
            n = delete_months(conn, [period_start])
            say(f"--keep: {args.month} flow_detail {n:,}행을 비웠습니다 (스트리밍한 값만 남깁니다)")
        say("스트리밍 시작 중 …")
        proc = start_stream(conn, since)
        say("스트리밍 준비됨 → 재생 시작")
        touched = True
        replay = ["python3", "pipeline/m1_collect/run_synth.py", "replay", "--months", args.month, "--speed", f"{args.speed:g}"]
        if args.days:
            replay += ["--days", *[f"{d:02d}" for d in days]]
        if run(replay) != 0:
            raise RuntimeError("재생이 실패했습니다")
        if run(["python3", "pipeline/m1_collect/send_eos.py", "--ts", eos]) != 0:
            raise RuntimeError("종료 신호를 보내지 못했습니다")
        loaded = wait_loaded(conn, since, len(days), proc, timeout=180 + 120 * len(days))
        if loaded < len(days):
            raise RuntimeError(f"{len(days)}일 중 {loaded}일만 적재됐습니다 (스트리밍 대시보드 · 위 로그 확인)")
        _, rows, received = conn.execute(LOADED, (since,)).fetchone()
        say(f"스트리밍 끝: 수신 {received:,}건 → {loaded}일 적재, flow_detail +{rows:,}행 ({time.time() - t0:.0f}초)")
    except KeyboardInterrupt:
        say("중단 요청 → 정리합니다")
        code = 130
    except Exception as e:
        say(f"실패: {e}")
        code = 1
    finally:
        if proc is not None:
            stop_stream(proc)
        if touched and not args.keep:
            say(f"{args.month} flow_detail 을 월 배치로 되돌리는 중 (약 2분) …")
            ok = (run(["spark-submit", "pipeline/m2_process/batch_flow_detail.py", "--months", args.month], quiet=True) == 0
                  and run(["spark-submit", "pipeline/m2_process/verify_flow_detail.py", "--months", args.month], quiet=True) == 0)
            after = month_total(conn, period_start)
            if ok:   # 검증(verify_flow_detail)이 기준이다. 시작 전 값과의 비교는 참고로 찍는다
                same = after[0] == before[0] and abs(after[1] - before[1]) < 1
                say(f"되돌림 완료 · 검증 통과: {after[0]:,}행 · 합계 {after[1]:,.2f} "
                    + ("(시작 전과 같음)" if same else f"(시작 전에는 {before[0]:,}행 · {before[1]:,.2f} 이었음)"))
            else:
                say(f"되돌리지 못했습니다 (지금 {after[0]:,}행 · 합계 {after[1]:,.2f}). Airflow 에서 {args.month} 을 수동 실행해 되돌리세요")
                code = code or 1
        elif args.keep:
            say(f"--keep: 되돌리지 않았습니다. 원래 값은 Airflow 에서 {args.month} 을 수동 실행해 되돌립니다")
        conn.close()
    say(f"{'완료' if code == 0 else '끝 (문제 있음)'} · 총 {time.time() - t0:.0f}초")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
