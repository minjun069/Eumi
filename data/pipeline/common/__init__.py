"""파이프라인 공통 패키지: 경로 · 환경변수(infra/.env) · DB · MinIO 연결 · 월 인자 · 검사 출력.

하위 모듈: apt_api(실거래가 API) · bg_sources(배경 원본) · bh_indicators(행동 지표 산식) · flow_agg · flow_detail_db(유동 상세) · m4_models(모델 자산).
실행 스크립트는 자기 폴더(m1_collect …)에서 돌므로 맨 위에서 data/pipeline 을 sys.path 에 넣고 `from common import …` 한다.
"""
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]  # data/pipeline/common/__init__.py → 저장소 루트
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


def minio_connect():
    """infra/.env 의 MINIO_* 로 MinIO 에 연결한다. 반환 (s3fs 파일시스템, 버킷). Spark 컨테이너에는 s3fs 가 없어 여기서 import 한다."""
    import s3fs
    fs = s3fs.S3FileSystem(
        key=os.environ["MINIO_ACCESS_KEY"], secret=os.environ["MINIO_SECRET_KEY"],
        client_kwargs={"endpoint_url": os.environ["MINIO_ENDPOINT"]},
        config_kwargs={"s3": {"addressing_style": "path"}},
    )
    return fs, os.environ["MINIO_BUCKET"]


def months_arg(values: list[str] | None) -> list[str]:
    """--months 값(YYYY-MM 또는 YYYYMM)을 YYYYMM 목록으로. 없으면 전월 한 달 (월 배치 기본값)."""
    if values:
        return [v.replace("-", "") for v in values]
    import datetime as dt
    prev = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    return [prev.strftime("%Y%m")]
