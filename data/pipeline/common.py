"""적재 스크립트 공통: 경로, 환경변수(infra/.env), DB 연결, 출력 인코딩."""
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
ENV_FILE = REPO_ROOT / "infra" / ".env"


def setup() -> None:
    """stdout을 UTF-8로 맞추고 infra/.env를 읽는다 (이미 있는 환경변수는 유지)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    load_dotenv(ENV_FILE, override=False)


def db_connect() -> psycopg.Connection:
    dsn = os.environ.get("PIPELINE_DB_DSN")
    if not dsn:
        raise SystemExit(f"PIPELINE_DB_DSN 이 없습니다. {ENV_FILE} 를 확인하세요 (.env.example 참고)")
    return psycopg.connect(dsn, autocommit=False)


def check(name: str, passed: bool, detail: str = "") -> bool:
    print(f"[{'OK' if passed else 'FAIL'}] {name}: {detail}", flush=True)
    return passed
