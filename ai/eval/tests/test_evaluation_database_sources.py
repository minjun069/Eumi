"""평가 자료원 선택이 실제 서비스 조회와 저장·재채점 경계까지 전달되는지 확인한다."""

import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256

import psycopg
import pytest
from pydantic import ValidationError

from eval import runner
from eval.assessment_store import load_assessment
from eval.runner import load_suite, run_suite
from eval.schema import suite_adapter
from eval.tests.batch_fixtures import read_document
from eval.tools.scoring import score_batch
from src.database import REPORT_SOURCES, Database
from src.settings import Settings

DATABASE_URL = "postgresql://evaluation:secret-password@localhost:5432/eumi_eval_test"


def _case(name="public.region_result", **changes):
    return {
        "id": name.replace(".", "-"),
        "unit": "tool",
        "target": "query_data",
        "purpose": "서비스에 등록한 조회 공급자를 실행한다.",
        "arguments": {"target": name},
    } | changes


def _suite(*cases, **changes):
    return {
        "schema_version": "evaluation-suite-v1",
        "id": "database-source-tests",
        "data_source": "database",
        "database_fixture": {"public.region_result": []},
        "cases": list(cases) or [_case()],
    } | changes


def _settings():
    return Settings(_env_file=None, database_url=DATABASE_URL)


def _read(path):
    return load_assessment(path) if path.is_dir() else read_document(path)


def _reports(folder):
    batch = _read(folder / "batch.json")
    return [_read(folder / item["path"]) for item in batch["runs"]]


@pytest.mark.parametrize("mode", [None, "prepared"])
async def test_prepared_mode_does_not_check_or_open_database(
    tmp_path, monkeypatch, mode
):
    def forbidden(*args, **kwargs):
        pytest.fail("Prepared suites must not access a database")

    monkeypatch.setattr(runner, "verify_fixture", forbidden)
    monkeypatch.setattr(runner, "database_identity", forbidden)
    monkeypatch.setattr(Database, "report_sources", forbidden)
    value = {
        "schema_version": "evaluation-suite-v1",
        "id": "prepared-default",
        "cases": [_case()],
    }
    if mode is not None:
        value["data_source"] = mode
    folder = await run_suite(value, _settings(), tmp_path)
    (report,) = _reports(folder)
    assert report["failure"]["code"] == "reference_not_found"
    manifest = _read(folder / "runs" / report["run"]["id"] / "manifest.json")
    assert manifest["evaluation"]["data_source"] == "prepared"
    assert manifest["evaluation"]["database_fixture_sha256"] is None
    assert manifest["evaluation"]["database"] is None
    assert _read(score_batch(folder))["criteria"]["data_source"] == "prepared"


@pytest.mark.parametrize(
    "changes",
    [
        {"datasets": {}},
        {"catalog": {}},
        {"data_source": "prepared"},
        {"data_source": "unknown"},
        {"database_fixture": {"public.not_registered": []}},
        {"database_fixture": {"public.region_result": [{}]}},
        {"cases": [_case(provider_failures={})]},
        {"cases": [_case(providers=["analysis.dim_grid100"])]},
        {"cases": [_case(providers=["prepared-only"])]},
    ],
)
def test_database_suite_rejects_ambiguous_or_unsupported_input(changes):
    with pytest.raises((ValidationError, ValueError)):
        suite_adapter.validate_python(_suite(**changes))


def test_database_fixture_is_required_and_legacy_suite_cannot_use_it():
    value = _suite()
    del value["database_fixture"]
    with pytest.raises(ValidationError, match="require database_fixture"):
        suite_adapter.validate_python(value)
    value = _suite()
    del value["data_source"]
    with pytest.raises(ValidationError, match="requires data_source=database"):
        suite_adapter.validate_python(value)


def test_database_providers_are_actual_registered_service_callables():
    settings = _settings()
    value = suite_adapter.validate_python(_suite())
    providers, catalog = runner._sources(value["cases"][0], value, settings)
    assert set(providers) == {"public.region_result", *REPORT_SOURCES}
    region = providers["public.region_result"]
    assert region.__func__ is Database.region_results
    assert region.__self__.settings is settings
    for name in REPORT_SOURCES:
        assert providers[name].func.__func__ is Database.report_dataset
        assert providers[name].func.__self__ is region.__self__
        assert providers[name].args == (name,)
    assert catalog == region.__self__.report_sources()[1]

    selected_case = _case(providers=["analysis.flow_detail"])
    selected, selected_catalog = runner._sources(selected_case, value, settings)
    assert list(selected) == list(selected_catalog) == ["analysis.flow_detail"]
    empty, empty_catalog = runner._sources(_case(providers=[]), value, settings)
    assert empty == empty_catalog == {}


async def test_database_settings_required_before_any_output(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Missing settings must be rejected before fixture verification")

    monkeypatch.setattr(runner, "verify_fixture", forbidden)
    with pytest.raises(ValueError, match="SETTINGS_DATABASE_URL"):
        await run_suite(_suite(), Settings(_env_file=None, database_url=None), tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "error", [ValueError("fixture differs"), psycopg.OperationalError()]
)
async def test_fixture_verification_failure_never_falls_back_or_creates_output(
    tmp_path, monkeypatch, error
):
    called = []

    def verify(settings, fixture):
        called.append(deepcopy(fixture))
        assert list(tmp_path.iterdir()) == []
        raise error

    def forbidden(*args, **kwargs):
        pytest.fail("No provider or model should run after fixture verification fails")

    monkeypatch.setattr(runner, "verify_fixture", verify)
    monkeypatch.setattr(Database, "report_sources", forbidden)
    monkeypatch.setattr(runner, "create_model", forbidden)
    with pytest.raises(type(error)) as caught:
        await run_suite(_suite(), _settings(), tmp_path)
    assert caught.value is error
    assert called == [{"public.region_result": []}]
    assert list(tmp_path.iterdir()) == []


async def test_database_execution_uses_service_sql_and_preserves_original_evidence(
    tmp_path, monkeypatch
):
    # DB 연결만 대체한다. 서비스의 공급자·SQL 선택·Dataset 변환·도구는 실제 실행한다.
    rows = {
        "public.region_result": {
            "bg_score": Decimal("1.5"),
            "bg_grade": 1,
            "bh_score": Decimal("2.5"),
            "bh_grade": 2,
            "risk_grade": 3,
        },
        "analysis.bh_region_contribution": {
            "indicator_cd": "I1",
            "contribution": Decimal("3.5"),
        },
        "analysis.flow_detail": {
            "dim_type": "hour",
            "dim_value": "00",
            "activity_daily": Decimal("4.5"),
        },
        "analysis.bh_grid_anomaly": {
            "grid_cd": "GRID1",
            "anomaly_score": Decimal("5.5"),
        },
    }
    for row in rows.values():
        row.update(
            period_start=date(2026, 10, 1),
            adm_cd10="1111111111",
            updated_at=datetime(2026, 11, 1),
        )
    calls = []
    verified = []

    def verify(settings, fixture):
        assert list(tmp_path.iterdir()) == []
        verified.append(deepcopy(fixture))

    class Connection:
        def execute(self, sql):
            assert len(verified) == 1
            name = next(name for name in rows if f"FROM {name}" in sql)
            calls.append((name, sql))
            self.name = name
            return self

        def fetchall(self):
            return [deepcopy(rows[self.name])]

    @contextmanager
    def connect(url, **kwargs):
        assert url == DATABASE_URL
        assert kwargs["connect_timeout"] == 10
        yield Connection()

    monkeypatch.setattr(runner, "verify_fixture", verify)
    monkeypatch.setattr("src.database.psycopg.connect", connect)
    cases = []
    for name in rows:
        expected = {
            key: value.isoformat()
            if isinstance(value, (date, datetime))
            else float(value)
            if isinstance(value, Decimal)
            else value
            for key, value in rows[name].items()
        }
        cases.append(
            _case(
                name,
                assessment={
                    "required": True,
                    "checks": ["T-O.1"],
                    "reference": {"id": "independent-expected-database-rows"},
                    "expected": {
                        "schema_version": "tool-expectations-v1",
                        "items": [
                            {
                                "check": "T-O.1",
                                "path": "/output/data/rows",
                                "value": [expected],
                            }
                        ],
                    },
                },
            )
        )
    value = _suite(*cases)
    original = deepcopy(value)
    folder = await run_suite(value, _settings(), tmp_path, repeat=2)
    assert value == original
    assert verified == [original["database_fixture"]]
    assert [name for name, _ in calls] == [name for name in rows for _ in range(2)]
    for name, sql in calls:
        if name in REPORT_SOURCES:
            assert sql == REPORT_SOURCES[name][0]
        else:
            assert "ORDER BY period_start, adm_cd10" in sql

    saved = _read(folder / "suite.json")
    assert saved == original
    for report in _reports(folder):
        assert report["run"]["status"] == "returned"
        provider = next(s for s in report["trace"]["spans"] if s["kind"] == "provider")
        assert provider["output"]["rows"] == report["output"]["data"]["rows"]
        assert provider["output"]["sources"][0]["uri"].startswith("db://")
        manifest_path = folder / "runs" / report["run"]["id"] / "manifest.json"
        manifest = _read(manifest_path)
        conditions = manifest["evaluation"]
        assert conditions["data_source"] == "database"
        assert conditions["database"] == {
            "host": "localhost",
            "port": "5432",
            "dbname": "eumi_eval_test",
        }
        assert (
            conditions["database_fixture_sha256"]
            == sha256(
                json.dumps(
                    original["database_fixture"], sort_keys=True, ensure_ascii=False
                ).encode()
            ).hexdigest()
        )
        assert "database.py" in conditions["runner_sha256"]
        assert "src/database.py" in manifest["files_sha256"]
        assert "secret-password" not in manifest_path.read_text(encoding="utf-8")

    # 채점은 저장된 파일만 읽으며 DB 연결 및 fixture 대조를 다시 수행하지 않는다.
    def forbidden(*args, **kwargs):
        pytest.fail("Scoring must not connect to a database")

    monkeypatch.setattr(runner, "verify_fixture", forbidden)
    monkeypatch.setattr("src.database.psycopg.connect", forbidden)
    first_path = score_batch(folder)
    first_bytes = {
        path: path.read_bytes() for path in first_path.rglob("*") if path.is_file()
    }
    first = _read(first_path)
    assert all(run["verdict"] == "통과" for run in first["runs"])
    assert first["criteria"]["data_source"] == "database"
    assert first["criteria"]["database_fixture"] == original["database_fixture"]
    assert "database.py" in first["evaluator_sha256"]
    saved["database_fixture"] = {}
    (folder / "suite.json").write_text(json.dumps(saved), encoding="utf-8")
    second = _read(score_batch(folder))
    assert second["criteria_sha256"] != first["criteria_sha256"]
    assert {
        path: path.read_bytes() for path in first_path.rglob("*") if path.is_file()
    } == first_bytes
    assert (
        _read(first_path)["criteria"]["database_fixture"]
        == original["database_fixture"]
    )


async def test_provider_database_error_is_saved_without_prepared_fallback(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "verify_fixture", lambda settings, fixture: None)

    def failed_connect(*args, **kwargs):
        raise psycopg.OperationalError("unavailable")

    monkeypatch.setattr("src.database.psycopg.connect", failed_connect)
    folder = await run_suite(_suite(), _settings(), tmp_path)
    (report,) = _reports(folder)
    assert report["run"]["status"] == "error"
    assert report["output"] is None
    assert report["failure"]["type"] == "OperationalError"
    (provider,) = [s for s in report["trace"]["spans"] if s["kind"] == "provider"]
    assert provider["status"] == "error"
    assert provider["error"]["type"] == "OperationalError"


def test_loading_database_suite_keeps_mode_and_fixture(tmp_path):
    value = _suite()
    path = tmp_path / "source.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert load_suite(path) == value
