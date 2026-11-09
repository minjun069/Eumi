"""임시 보고서 DB를 실제 API에 연결하고 기록·저장·재접수를 검증한다."""

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from api import REPORT_PATH, create_app, create_report_states, execute_reports
from experiments import report_roundtrip
from experiments.report_roundtrip import FileReportDatabase
from src.state import report_artifact, report_input
from tests.test_reports import BODY, ReportModel, setup


@pytest.mark.asyncio
async def test_local_http_report_runner(monkeypatch, tmp_path):
    settings, _ = setup(tmp_path / "runs")
    db = FileReportDatabase(settings, tmp_path / "db")
    db.seed(BODY)
    model = ReportModel()
    monkeypatch.setattr(
        report_roundtrip,
        "create_app",
        lambda settings, *, database: create_app(
            settings, database=database, model=model
        ),
    )
    assert await report_roundtrip.run(settings, db, BODY)
    assert db.read_reports()[0]["quick_insight"]
    # 같은 파일 DB라도 다시 접수해 생성한다.
    assert await report_roundtrip.run(settings, db, BODY)
    assert len(list(settings.output_dir.glob("*/report.json"))) == 2


@pytest.mark.asyncio
async def test_file_reports_api_trace_and_regenerate(tmp_path):
    settings, _ = setup(tmp_path / "runs")
    settings.api_key = SecretStr("test-secret-marker")
    body = BODY | {"dongCodes": ["1168066000", "1168064000"]}
    db = FileReportDatabase(settings, tmp_path / "db")
    db.seed(body)
    model = ReportModel(fail_once="EmbedDetailV01")
    entered, release = asyncio.Event(), asyncio.Event()
    model.entered, model.release = entered, release
    app = create_app(settings, database=db, model=model)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(204))
        ) as backend,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        app.state.client = backend
        response = await client.post(REPORT_PATH, json=body)
        assert response.status_code == 202 and not response.content
        await asyncio.wait_for(entered.wait(), 2)
        task = next(iter(app.state.report_tasks))
        release.set()
        states = await task
        persisted = FileReportDatabase(settings, db.folder).read_reports()
        assert sorted(persisted, key=lambda r: r["adm_cd10"]) == sorted(
            [report_artifact(s) for s in states], key=lambda r: r["adm_cd10"]
        )
        assert all(s["execution"]["status"] == "completed" for s in states)
        for state in states:
            path = settings.output_dir / state["execution"]["run_id"] / "report.json"
            raw = path.read_text(encoding="utf-8")
            assert "test-secret-marker" not in raw
            report = json.loads(raw)
            assert report["state"]["results"] == state["results"]
            assert report["trace"]["coverage"]["unfinished_spans"] == 0
            spans = report["trace"]["spans"]
            attempts = [s for s in spans if s["name"] == "api.report"]
            retried = any(r["decision"] == "report_retry" for r in state["results"])
            assert len(attempts) == 1 + retried
            assert all(
                report_input(s["input"]["initial_state"])["dongCode"]
                == report_input(state)["dongCode"]
                for s in attempts
            )
            assert any(s["kind"] == "model" and s["input"]["messages"] for s in spans)

        await asyncio.sleep(0)
        calls = len(model.calls)
        response = await client.post(REPORT_PATH, json=body)
        assert response.status_code == 202 and not response.content
        await asyncio.gather(*list(app.state.report_tasks))
        assert len(model.calls) > calls
    with pytest.raises(FileExistsError):
        db.seed(body)


@pytest.mark.asyncio
async def test_file_reports_null_upsert_and_missing_source(monkeypatch, tmp_path):
    settings, _ = setup(tmp_path / "runs")
    db = FileReportDatabase(settings, tmp_path / "db")
    db.seed(BODY)
    states = create_report_states(BODY, settings)
    with monkeypatch.context() as patch:
        patch.setattr(
            db, "read_reports", lambda: pytest.fail("기존 보고서를 조회하면 안 됨")
        )
        await db.prepare_report(states[0])
    assert states[0]["results"][-1]["output"] == {
        "period_start": "2025-12-01",
        "adm_cd10": "1168066000",
        "updated_at": "2025-12-15T00:00:00",
    }
    model = ReportModel()
    model.empty_selection = True
    await execute_reports(states, database=db, model=model)
    row = report_artifact(states[0])
    assert row["quick_insight"] is None and row["graph_1"] is None
    await db.save_report(states[0])
    assert db.read_reports() == [row]
    missing = create_report_states(BODY | {"month": "2024-01"}, settings)
    await db.prepare_report(missing[0])
    await execute_reports(missing, database=db, model=ReportModel())
    assert missing[0]["execution"]["error"]["code"] == "result_not_found"
    assert db.read_reports() == [row]
