"""설정된 서비스 DB를 읽기 전용으로 조회해 노드 평가 근거를 보존한다."""

import argparse
import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

AI_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AI_ROOT))

from src.database import Database  # noqa: E402
from src.settings import Settings  # noqa: E402
from src.tools.data import Dataset, read_dataset  # noqa: E402


def primitive(value, *, exact=False):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value) if exact else float(value)
    if isinstance(value, dict):
        return {key: primitive(item, exact=exact) for key, item in value.items()}
    if isinstance(value, list):
        return [primitive(item, exact=exact) for item in value]
    return value


def digest(value):
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


class SnapshotDatabase(Database):
    """기존 공급자의 SQL·열 정의를 같은 읽기 전용 트랜잭션에서 사용한다."""

    def __init__(self, settings, connection, periods, grid_regions):
        super().__init__(settings)
        self.connection = connection
        self.periods = periods
        self.grid_regions = grid_regions
        self.queries = {}
        self.raw = {}

    def _read_dataset(self, name, sql, description, columns, spatial="행정동"):
        scoped = f"SELECT * FROM ({sql}) AS source WHERE period_start = ANY(%s)"
        parameters = [self.periods]
        if name == "analysis.bh_grid_anomaly":
            scoped += " AND adm_cd10 = ANY(%s)"
            parameters.append(self.grid_regions)
        scoped += " ORDER BY " + ", ".join(
            key for key, _, _ in columns if key != "updated_at"
        )
        rows = self.connection.execute(scoped, parameters).fetchall()
        self.raw[name] = primitive(rows, exact=True)
        converted = primitive(rows)
        self.queries[name] = {
            "sql": scoped,
            "parameters": primitive(parameters),
            "row_count": len(rows),
            "query_result_sha256": digest(self.raw[name]),
            "decimal_encoding": "exact decimal strings in raw-query-results.json",
        }
        # Dataset의 행·수치·참조 버전 변환은 서비스 공급자와 같은 규칙이다.
        return read_dataset(
            {
                "reference": {
                    "id": name,
                    "version": sha256(
                        json.dumps(converted, sort_keys=True).encode()
                    ).hexdigest(),
                },
                "as_of": max((row["updated_at"] for row in converted), default="empty"),
                "sources": [
                    {"label": description, "uri": "db://" + name.replace(".", "/")}
                ],
                "columns": [
                    {
                        "name": key,
                        "kind": kind,
                        "unit": unit,
                        "spatial_unit": spatial,
                        "temporal_unit": "월",
                        "denominator": "해당 없음",
                    }
                    for key, kind, unit in columns
                ],
                "rows": converted,
            }
        )


def capture(settings: Settings):
    if not settings.database_url:
        raise ValueError("database_url_missing")
    dsn = settings.database_url.get_secret_value()
    config = conninfo_to_dict(dsn)
    with psycopg.connect(
        dsn,
        row_factory=dict_row,
        connect_timeout=settings.database_timeout,
        options="-c default_transaction_read_only=on -c statement_timeout=30000",
    ) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        identity = connection.execute(
            "SELECT current_database() AS database, "
            "current_setting('transaction_read_only') AS read_only, "
            "current_setting('transaction_isolation') AS isolation, "
            "transaction_timestamp() AS transaction_at"
        ).fetchone()
        if identity["database"].startswith("eumi_eval"):
            raise ValueError("evaluation_database_is_not_a_service_snapshot")
        period_sql = (
            "SELECT period_start, count(*) AS row_count, "
            "count(DISTINCT adm_cd10) AS region_count FROM public.region_result "
            "GROUP BY period_start ORDER BY period_start DESC LIMIT 5"
        )
        periods = connection.execute(period_sql).fetchall()
        if len(periods) < 2:
            raise ValueError("two_actual_periods_required")
        latest = periods[0]["period_start"]
        region_sql = (
            "SELECT r.adm_cd10, d.adm_nm, d.sgg_nm, "
            "r.bh_score, r.bg_score, r.risk_grade, "
            "r.bh_score-p.bh_score AS previous_delta "
            "FROM public.region_result r JOIN public.dim_region d USING(adm_cd10) "
            "LEFT JOIN public.region_result p ON p.adm_cd10=r.adm_cd10 "
            "AND p.period_start=r.period_start-INTERVAL '1 month' "
            "WHERE r.period_start=%s ORDER BY d.sgg_nm,r.adm_cd10"
        )
        regions = connection.execute(region_sql, (latest,)).fetchall()
        selected = []
        for city in sorted({row["sgg_nm"] for row in regions}):
            comparable = [
                row
                for row in regions
                if row["sgg_nm"] == city and row["previous_delta"] is not None
            ]
            if not comparable:
                continue
            for chooser in (max, min):
                row = chooser(comparable, key=lambda item: item["previous_delta"])
                if row not in selected:
                    selected.append(row)
        if not selected:
            raise ValueError("comparable_actual_regions_required")
        db = SnapshotDatabase(
            settings,
            connection,
            [row["period_start"] for row in periods],
            [row["adm_cd10"] for row in selected],
        )
        providers, catalog = db.report_sources()
        datasets: dict[str, Dataset] = {
            name: provider() for name, provider in providers.items()
        }
        grid_scope = ", ".join(
            f"{row['adm_nm']}({row['adm_cd10']})" for row in selected
        )
        for name in catalog:
            catalog[name] += (
                " 평가용 실제 DB 조회 스냅샷. 제공 기간은 "
                + ", ".join(row["period_start"].isoformat()[:7] for row in periods)
                + "."
            )
        catalog["analysis.bh_grid_anomaly"] += " 제공 지역은 " + grid_scope + "."
        primary = selected[0]
        comparison = selected[1] if len(selected) > 1 else selected[0]
        provenance = {
            "origin": "configured_service_database_read_only_snapshot",
            "database": identity["database"],
            "connection_endpoint": (
                "local"
                if config.get("host") in (None, "localhost", "127.0.0.1", "::1")
                else "remote"
            ),
            "endpoint_sha256": digest(
                {key: config.get(key) for key in ("host", "port", "dbname")}
            ),
            "transaction": primitive(identity),
            "captured_at": datetime.now(UTC).isoformat(),
            "period_query": {"sql": period_sql, "results": primitive(periods)},
            "region_query": {
                "sql": region_sql,
                "parameters": [latest.isoformat()],
                "query_result_sha256": digest(primitive(regions, exact=True)),
            },
            "sources": db.queries,
            "service_provider_sha256": sha256(
                (AI_ROOT / "src/database.py").read_bytes()
            ).hexdigest(),
            "capture_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "dataset_sha256": {name: digest(data) for name, data in datasets.items()},
            "limitations": [
                "설정된 서비스 DB의 조회 결과. 원자료의 수집 경로는 미검증",
                "격자 자료는 각 시군구의 최신월 전월차 최댓값·최솟값 지역만 포함",
                "정상 0행인 자료원을 합성 값으로 채우지 않음",
                "DB 연결 정보의 계정·비밀번호·주소 원문은 저장하지 않음",
            ],
        }
        snapshot = {
            "datasets": datasets,
            "catalog": catalog,
            "selection": {
                "dong_code": primary["adm_cd10"],
                "dong_name": primary["adm_nm"],
                "city_name": primary["sgg_nm"],
                "month": latest.isoformat()[:7],
                "previous_month": periods[1]["period_start"].isoformat()[:7],
                "comparison_dong_code": comparison["adm_cd10"],
                "comparison_dong_name": comparison["adm_nm"],
                "periods": [row["period_start"].isoformat()[:7] for row in periods],
                "grid_regions": primitive(selected),
            },
            "regions": primitive(regions),
            "provenance": provenance,
        }
        raw = {
            "sources": db.raw,
            "regions": primitive(regions, exact=True),
        }
    return snapshot, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=AI_ROOT / ".env")
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).parent / "snapshots"
    )
    args = parser.parse_args()
    paths = [args.output / name for name in ("data.json", "raw-query-results.json")]
    if any(path.exists() for path in paths):
        parser.error("snapshot exists; choose a new output directory")
    try:
        snapshot, raw = capture(Settings(_env_file=args.env_file))
    except Exception as exc:
        # DB 예외 본문은 접속 정보가 포함될 수 있어 기록하지 않는다.
        print(
            json.dumps(
                {
                    "error_type": type(exc).__name__,
                    "sqlstate": getattr(exc, "sqlstate", None),
                }
            ),
            file=sys.stderr,
        )
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    for path, data in zip(paths, (snapshot, raw), strict=True):
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "row_counts": {
                    name: len(data["rows"])
                    for name, data in snapshot["datasets"].items()
                },
                "selection": snapshot["selection"],
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
