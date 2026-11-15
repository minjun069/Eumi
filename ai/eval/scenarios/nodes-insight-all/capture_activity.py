"""Capture three regions' aggregate indicators in a read-only transaction."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from src.settings import Settings  # noqa: E402

REGIONS = {
    "1168065500": "도곡1동",
    "1168063000": "대치4동",
    "5111062000": "효자1동",
}


def encode(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def digest(rows):
    return sha256(
        json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def capture():
    prior = json.loads(
        (
            HERE.parent / "nodes-insight-review/snapshots/activity-evidence.json"
        ).read_text(encoding="utf-8")
    )
    settings = Settings(LANGFUSE_ENABLED=False)
    if settings.database_url is None:
        raise RuntimeError("Configured database is unavailable")
    queries = {}
    with psycopg.connect(
        settings.database_url.get_secret_value(),
        connect_timeout=10,
        row_factory=dict_row,
        options="-c statement_timeout=20000",
    ) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        transaction = connection.execute(
            "SELECT current_database() AS database, "
            "current_setting('transaction_read_only') AS read_only, "
            "current_setting('transaction_isolation') AS isolation, "
            "transaction_timestamp() AS transaction_at"
        ).fetchone()
        transaction = json.loads(json.dumps(transaction, default=encode))
        assert transaction["read_only"] == "on"
        for key in ("region_indicators", "activity_hourly_mean"):
            sql = (
                prior["queries"][key]["sql"]
                .replace("adm_cd10=%s", "adm_cd10=ANY(%s)")
                .replace("ORDER BY period_start", "ORDER BY adm_cd10,period_start")
            )
            parameters = [list(REGIONS), "2025-07-01", "2025-12-01"]
            rows = connection.execute(sql, parameters).fetchall()
            rows = json.loads(json.dumps(rows, default=encode))
            expected = {
                (code, f"2025-{month:02d}-01")
                for code in REGIONS
                for month in range(7, 13)
            }
            assert {(row["adm_cd10"], row["period_start"]) for row in rows} == expected
            assert len(rows) == len(expected)
            queries[key] = {
                "sql": sql,
                "parameters": parameters,
                "row_count": len(rows),
                "rows": rows,
                "query_result_sha256": digest(rows),
                "transaction": transaction,
            }
        connection.rollback()
    # Preserve the already approved region's observations exactly.
    for key in queries:
        dogok = [r for r in queries[key]["rows"] if r["adm_cd10"] == "1168065500"]
        assert dogok == prior["queries"][key]["rows"], "Approved observations changed"
    payload = {
        "origin": "configured_service_database_read_only_query",
        "captured_at": datetime.now(UTC).isoformat(),
        "transaction": transaction,
        "target": {
            "regions": REGIONS,
            "period_from": "2025-07-01",
            "period_to": "2025-12-01",
        },
        "decimal_encoding": prior["decimal_encoding"],
        "source_files": prior["source_files"],
        "table_definitions": {
            key: prior["table_definitions"][key]
            for key in (
                "analysis.bh_region_indicator",
                "activity_daily",
                "flow_detail",
                "h18_senior_male_share",
                "h29_senior_gender_change_gap",
                "h26_weekend_weekday_change_gap",
                "activity_hourly_mean",
            )
        },
        "queries": queries,
    }
    destination = HERE / "snapshots/activity-evidence.json"
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "regions": REGIONS,
                "rows_per_query": len(rows),
                "read_only": transaction["read_only"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    capture()
