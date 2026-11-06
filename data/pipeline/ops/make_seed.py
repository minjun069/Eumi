"""[운영 · 서버 seed 생성 | 호스트] 로컬 DB 의 데이터 파트 테이블을 Flyway seed(db/seed/R__NN_<table>.sql)로 내보낸다.

- pg_dump 의 COPY 블록을 임시 테이블에 넣고 INSERT ... ON CONFLICT DO NOTHING 으로 옮기는 형태라, R 파일이 다시 실행돼도 안전하다.
- flow_detail(760만 행, 500 MB)은 git · Flyway 로 옮기기엔 커서 제외한다. 필요하면 덤프로 따로 옮긴다 (data/README.md 서버 반영 절).
- FK 순서: dim_region(R__01) → dim_grid100(R__10) → 나머지. R__02 · 03 은 인프라 담당의 기관 · 회원 seed.
실행  data/.venv/Scripts/python data/pipeline/ops/make_seed.py            (로컬 Docker postgres 컨테이너에서 pg_dump)
      … make_seed.py --tables bh_region_contribution region_result      값이 바뀐 테이블만 다시 만든다 (다른 파일은 그대로)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # data/pipeline (common 패키지)
import argparse
import datetime as dt
import subprocess
from pathlib import Path

from common import REPO_ROOT, setup

SEED_DIR = REPO_ROOT / "db" / "seed"
COMPOSE = ["docker", "compose", "-f", str(REPO_ROOT / "infra" / "docker-compose.yml"), "exec", "-T", "postgres"]
TABLES = [  # (파일 순번, 스키마.테이블)
    ("01", "public.dim_region"),
    ("10", "analysis.dim_grid100"),
    ("11", "analysis.bg_region_detail"),
    ("12", "analysis.bg_region_indicator"),
    ("13", "analysis.bg_grid_indicator"),
    ("14", "analysis.bh_region_indicator"),
    ("15", "analysis.bh_grid_indicator"),
    ("16", "public.region_result"),
    ("17", "analysis.bh_grid_anomaly"),
    ("18", "analysis.re_apt_trade"),
    ("19", "analysis.bh_region_contribution"),   # region_result(R__16) 를 참조하므로 그 뒤
]
IDENTITY = {"analysis.re_apt_trade": "trade_id"}  # 시퀀스를 seed 최대값 뒤로 맞춰야 하는 테이블
COPY_END = chr(92) + "."  # COPY 블록 끝 표시 (백슬래시 + 점)


def dump_copy_block(table: str) -> tuple[str, list[str]]:
    out = subprocess.run(COMPOSE + ["pg_dump", "-U", "postgres", "-d", "eumi", "--data-only", "--no-owner", "-t", table],
                         capture_output=True, check=True).stdout.decode("utf-8")
    lines = out.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("COPY "))
    end = next(i for i in range(start, len(lines)) if lines[i] == COPY_END)
    cols = lines[start][lines[start].index("(") + 1: lines[start].index(")")]
    return cols, lines[start + 1: end]


def main() -> int:
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", nargs="*", help="테이블 이름(스키마 없이)만 골라 내보낸다. 없으면 전부")
    args = ap.parse_args()
    names = {t.split('.')[1] for _, t in TABLES}
    if args.tables and not set(args.tables) <= names:
        raise SystemExit(f"모르는 테이블: {sorted(set(args.tables) - names)} (가능: {sorted(names)})")
    today = dt.date.today().isoformat()
    for num, table in TABLES:
        if args.tables and table.split('.')[1] not in args.tables:
            continue
        schema, name = table.split(".")
        cols, rows = dump_copy_block(table)
        path = SEED_DIR / f"R__{num}_{name}.sql"
        tail = ""
        if table in IDENTITY:
            col = IDENTITY[table]
            tail = (f"-- seed 가 PK 값을 가지고 들어오므로 IDENTITY 시퀀스를 그 뒤로 맞춘다\n"
                    f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'), (SELECT max({col}) FROM {table}));\n")
        body = (f"-- 데이터 파트 seed: {table} ({len(rows):,}행, {today} 로컬 파이프라인 산출값). 생성 스크립트 data/pipeline/ops/make_seed.py\n"
                f"-- R 파일은 내용이 바뀌면 다시 실행되므로 임시 테이블에 COPY 한 뒤 ON CONFLICT DO NOTHING 으로 넣는다 (있는 행은 그대로 둠).\n"
                f"CREATE TEMP TABLE seed_{name} (LIKE {table}) ON COMMIT DROP;\n"
                f"COPY seed_{name} ({cols}) FROM stdin;\n" + "\n".join(rows) + "\n" + COPY_END + "\n"
                f"INSERT INTO {table} ({cols}) SELECT {cols} FROM seed_{name} ON CONFLICT DO NOTHING;\n" + tail)
        path.write_text(body, encoding="utf-8", newline="\n")
        print(f"{path.name:40s} {len(rows):>9,}행 {path.stat().st_size / 1048576:6.1f} MB", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
