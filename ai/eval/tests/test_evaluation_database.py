"""평가 DB 적재·원본 검사 경계. 실제 DB나 비밀 설정을 읽지 않는다."""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from pydantic import ValidationError

from eval import database
from eval.__main__ import main
from eval.database import (
    TABLES,
    database_identity,
    prepare_database,
    validate_fixture,
    verify_fixture,
)
from src.settings import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        database_url="postgresql://test:private@localhost:5439/eumi_eval_unit",
    )


@pytest.fixture
def fixture():
    timestamp = "2026-11-01T00:00:00.1"
    period = "2026-10-01"
    return {
        "public.dim_region": [
            {
                "adm_cd10": "1111111111",
                "adm_cd8": None,
                "adm_nm": "시험동 ' quoted",
                "sgg_nm": "시험구",
                "geom": None,
                "updated_at": None,
            }
        ],
        "public.region_result": [
            {
                "period_start": period,
                "adm_cd10": "1111111111",
                "bg_score": 10.25,
                "bg_grade": 1,
                "bh_score": 20,
                "bh_grade": 2,
                "risk_grade": 2,
                "updated_at": timestamp,
            }
        ],
        "analysis.dim_grid100": [
            {
                "grid_cd": "grid-1",
                "gx": 12,
                "gy": 34,
                "updated_at": timestamp,
                "adm_cd10": "1111111111",
            }
        ],
        "analysis.bh_region_contribution": [
            {
                "period_start": period,
                "adm_cd10": "1111111111",
                "indicator_cd": "activity_daily",
                "contribution": 0.123456,
                "updated_at": timestamp,
            }
        ],
        "analysis.bh_grid_anomaly": [
            {
                "period_start": period,
                "grid_cd": "grid-1",
                "anomaly_score": None,
                "updated_at": timestamp,
            }
        ],
        "analysis.flow_detail": [
            {
                "period_start": period,
                "dim_type": "hour",
                "dim_value": "10",
                "grid_cd": "grid-1",
                "flow_sum": 123.4567,
                "day_count": None,
                "updated_at": timestamp,
            }
        ],
    }


class Connection:
    """SQL·인자·커밋 경계를 기록하는 메모리 연결."""

    def __init__(self, rows=None, fail_on=None):
        self.rows = {table: deepcopy((rows or {}).get(table, [])) for table in TABLES}
        self.before = deepcopy(self.rows)
        self.info = SimpleNamespace(dbname="eumi_eval_unit")
        self.calls = []
        self.fail_on = fail_on
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, traceback):
        self.committed = kind is None
        self.rolled_back = kind is not None
        if kind:
            self.rows = self.before
        self.close()

    def close(self):
        self.closed = True

    def execute(self, statement, params=None):
        text = statement if isinstance(statement, str) else statement.as_string()
        self.calls.append((text, params))
        if text.startswith("SELECT"):
            table = text.split("FROM ", 1)[1].replace('"', "")
            return SimpleNamespace(fetchall=lambda: deepcopy(self.rows[table]))
        if text.startswith("INSERT"):
            table = text.split("INSERT INTO ", 1)[1].split(" (", 1)[0]
            table = table.replace('"', "")
            if self.fail_on == table:
                raise psycopg.IntegrityError("simulated insert failure")
            columns = text.split(" (", 1)[1].split(")", 1)[0].replace('"', "")
            self.rows[table].append(dict(zip(columns.split(", "), params, strict=True)))
        return SimpleNamespace(fetchall=lambda: [])


def connect(monkeypatch, rows=None, fail_on=None):
    connection = Connection(rows, fail_on)
    mock = Mock(return_value=connection)
    monkeypatch.setattr(database.psycopg, "connect", mock)
    return connection, mock


@pytest.mark.parametrize("name", ["eumi", "production", "eumi_evaluation", ""])
def test_rejects_non_evaluation_database_before_connect(monkeypatch, fixture, name):
    _, mock = connect(monkeypatch)
    settings = Settings(
        _env_file=None, database_url=f"dbname='{name}' password=private"
    )
    with pytest.raises(ValueError, match="database name"):
        prepare_database(settings, fixture)
    mock.assert_not_called()


def test_identity_contains_no_credentials(settings):
    assert database_identity(settings) == {
        "host": "localhost",
        "port": "5439",
        "dbname": "eumi_eval_unit",
    }


@pytest.mark.parametrize("dsn", [None, "not-a-dsn password=private"])
def test_missing_invalid_connection_never_exposes_credentials(dsn):
    settings = Settings(_env_file=None, database_url=dsn)
    with pytest.raises(ValueError) as raised:
        database_identity(settings)
    assert "private" not in str(raised.value)


def test_connected_database_must_match_configured_name(monkeypatch, settings):
    connection, _ = connect(monkeypatch)
    connection.info.dbname = "eumi"
    with pytest.raises(ValueError, match="connected database differs"):
        verify_fixture(settings, {})
    assert connection.closed
    assert connection.calls == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f.update({"public.dim_region; DROP TABLE x": []}),
        lambda f: f["public.dim_region"][0].pop("geom"),
        lambda f: f["public.dim_region"][0].update(extra="unexpected"),
        lambda f: f["public.region_result"][0].update(bg_grade=True),
        lambda f: f["public.region_result"][0].update(bg_score="10.25"),
        lambda f: f["public.region_result"][0].update(bg_score=1.001),
        lambda f: f["public.region_result"][0].update(bg_score=float("nan")),
        lambda f: f["public.region_result"][0].update(period_start="2026-02-30"),
        lambda f: f["public.region_result"][0].update(updated_at="2026-11-01"),
        lambda f: f["public.region_result"][0].update(
            updated_at="2026-11-01T00:00:00+09:00"
        ),
        lambda f: f["public.region_result"][0].update(
            updated_at="2026-11-01T00:00:00.1234567"
        ),
    ],
)
def test_invalid_fixture_rejected_without_database(
    monkeypatch, settings, fixture, mutate
):
    _, mock = connect(monkeypatch)
    mutate(fixture)
    with pytest.raises((ValueError, ValidationError)):
        prepare_database(settings, fixture)
    mock.assert_not_called()


def test_prepares_all_tables_in_one_transaction_with_parameters(
    monkeypatch,
    settings,
    fixture,
):
    connection, mock = connect(monkeypatch)
    original = deepcopy(fixture)
    result = prepare_database(settings, fixture)
    assert result == {"status": "prepared", "rows": dict.fromkeys(TABLES, 1)}
    assert connection.committed and connection.closed
    assert mock.call_count == 1
    assert connection.calls[0][0].startswith("LOCK TABLE")
    inserts = [
        (text, params) for text, params in connection.calls if text.startswith("INSERT")
    ]
    assert len(inserts) == 6
    for table, (statement, _) in zip(TABLES, inserts, strict=True):
        schema, name = table.split(".")
        assert statement.startswith(f'INSERT INTO "{schema}"."{name}" ')
    assert "시험동" not in inserts[0][0]
    assert "시험동 ' quoted" in inserts[0][1]
    assert inserts[1][1][0] == date(2026, 10, 1)
    assert Decimal("10.25") in inserts[1][1]
    assert datetime(2026, 11, 1, microsecond=100000) in inserts[1][1]
    assert fixture == original
    assert not any(
        text.startswith(("DELETE", "UPDATE", "TRUNCATE", "CREATE"))
        for text, _ in connection.calls
    )


def test_insert_failure_rolls_back_all_prior_inserts(monkeypatch, settings, fixture):
    connection, _ = connect(monkeypatch, fail_on="analysis.dim_grid100")
    with pytest.raises(psycopg.IntegrityError):
        prepare_database(settings, fixture)
    assert connection.rolled_back and connection.closed
    assert not any(connection.rows.values())


def test_database_side_change_during_insert_rolls_back(monkeypatch, settings, fixture):
    connection, _ = connect(monkeypatch)
    execute = connection.execute

    def change_score(statement, params=None):
        result = execute(statement, params)
        if connection.rows["public.region_result"]:
            connection.rows["public.region_result"][0]["bh_score"] = Decimal("999")
        return result

    monkeypatch.setattr(connection, "execute", change_score)
    with pytest.raises(ValueError, match="inserted evaluation data differs"):
        prepare_database(settings, fixture)
    assert connection.rolled_back
    assert not any(connection.rows.values())


def test_identical_data_is_noop_after_temporal_numeric_normalization(
    monkeypatch,
    settings,
    fixture,
):
    actual = deepcopy(fixture)
    actual["public.region_result"][0].update(
        period_start=date(2026, 10, 1),
        bg_score=Decimal("10.2500"),
        updated_at=datetime(2026, 11, 1, microsecond=100000),
    )
    connection, _ = connect(monkeypatch, actual)
    assert prepare_database(settings, fixture)["status"] == "unchanged"
    assert connection.committed
    assert not any(text.startswith("INSERT") for text, _ in connection.calls)


def test_nonempty_different_database_is_unchanged(monkeypatch, settings, fixture):
    actual = deepcopy(fixture)
    actual["analysis.flow_detail"][0]["flow_sum"] = 999
    connection, _ = connect(monkeypatch, actual)
    with pytest.raises(ValueError, match="must be empty or match"):
        prepare_database(settings, fixture)
    assert connection.rows == actual
    assert not any(text.startswith("INSERT") for text, _ in connection.calls)


def test_verify_uses_readonly_snapshot_and_checks_omitted_tables(
    monkeypatch,
    settings,
    fixture,
):
    connection, _ = connect(monkeypatch, fixture)
    with pytest.raises(ValueError, match="differs"):
        verify_fixture(settings, {"public.dim_region": fixture["public.dim_region"]})
    assert connection.calls[0][0] == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    )
    assert sum(text.startswith("SELECT") for text, _ in connection.calls) == 6
    assert all(
        text.startswith(("SET TRANSACTION", "SELECT")) for text, _ in connection.calls
    )


def test_verify_ignores_row_order_but_not_duplicates(monkeypatch, settings, fixture):
    second = dict(fixture["public.dim_region"][0], adm_cd10="2222222222")
    fixture["public.dim_region"].append(second)
    actual = deepcopy(fixture)
    actual["public.dim_region"].reverse()
    connect(monkeypatch, actual)
    verify_fixture(settings, fixture)
    actual["public.dim_region"].append(second)
    connect(monkeypatch, actual)
    with pytest.raises(ValueError, match="differs"):
        verify_fixture(settings, fixture)


def test_empty_fixture_requires_all_six_tables_empty(monkeypatch, settings):
    connection, _ = connect(monkeypatch)
    validate_fixture({})
    verify_fixture(settings, {})
    assert connection.committed


def test_prepare_cli_uses_seed_settings_without_running_evaluation(monkeypatch, capsys):
    suite = {"id": "db", "data_source": "database", "database_fixture": {}, "cases": []}
    monkeypatch.setattr("eval.__main__.load_suite", Mock(return_value=suite))
    factory = Mock(return_value=object())
    monkeypatch.setattr("eval.__main__.Settings", factory)
    prepare = Mock(return_value={"status": "unchanged", "rows": {}})
    monkeypatch.setattr(database, "prepare_database", prepare)
    run = Mock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr("eval.__main__.run_suite", run)
    assert main(["prepare-db", "suite.json", "--env-file", "seed.env"]) == 0
    assert str(factory.call_args.kwargs["_env_file"]) == "seed.env"
    prepare.assert_called_once_with(factory.return_value, {})
    assert "unchanged" in capsys.readouterr().out


def test_prepare_cli_rejects_prepared_data_source(monkeypatch):
    monkeypatch.setattr(
        "eval.__main__.load_suite",
        Mock(return_value={"id": "prepared", "cases": []}),
    )
    prepare = Mock()
    monkeypatch.setattr(database, "prepare_database", prepare)
    assert main(["prepare-db", "suite.json"]) == 2
    prepare.assert_not_called()
