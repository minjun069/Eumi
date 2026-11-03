"""2차 5.2 공통 — flow_detail 증분 적재 (psycopg). eumi_pipeline 은 TRUNCATE·CREATE 권한이 없어 임시 테이블 + UPSERT 로 쓴다."""
import os
from io import StringIO

import psycopg

COLS = ["period_start", "grid_cd", "dim_type", "dim_value", "flow_sum", "day_count"]
UPSERT = """
INSERT INTO analysis.flow_detail (period_start, grid_cd, dim_type, dim_value, flow_sum, day_count, updated_at)
SELECT period_start, grid_cd, dim_type, dim_value, flow_sum, day_count, now() FROM _flow_in
ON CONFLICT (period_start, grid_cd, dim_type, dim_value) DO UPDATE SET
    flow_sum = analysis.flow_detail.flow_sum + EXCLUDED.flow_sum,
    day_count = analysis.flow_detail.day_count + EXCLUDED.day_count,
    updated_at = now()
"""


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["PIPELINE_DB_DSN"], autocommit=False)


def delete_months(conn: psycopg.Connection, months) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM analysis.flow_detail WHERE period_start = ANY(%s)", (list(months),))
        return cur.rowcount


def upsert_increments(conn: psycopg.Connection, rows) -> int:
    """rows: (period_start, grid_cd, dim_type, dim_value, flow_sum, day_count) 반복자. 같은 키는 더해진다."""
    buf = StringIO()
    n = 0
    for r in rows:
        buf.write("\t".join(str(v) for v in r) + "\n")
        n += 1
    buf.seek(0)
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS _flow_in (period_start date, grid_cd varchar(10), dim_type varchar(10), dim_value varchar(10), flow_sum numeric(16,4), day_count smallint) ON COMMIT DELETE ROWS")
        with cur.copy("COPY _flow_in (period_start, grid_cd, dim_type, dim_value, flow_sum, day_count) FROM STDIN") as cp:
            cp.write(buf.read())
        cur.execute(UPSERT)
    return n
