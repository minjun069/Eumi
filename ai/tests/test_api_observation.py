"""Exercise admission, cancellation and queued report evidence locally."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from api import REPORT_PATH, create_app, create_report_states, execute_reports
from src.database import DatabaseUnavailable
from src.state import report_input
from tests.api_fixtures import MemoryDatabase, OfflineModel
from tests.test_api_roundtrip import body, settings, tasks
from tests.test_reports import BODY, ReportModel, setup


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def requests(output):
    return [
        (path, read(path)["trace"]["spans"])
        for path in output.glob("requests/*/request.json")
    ]


def admission(spans):
    return next(span for span in spans if span["name"] == "api.request")


@pytest.mark.asyncio
async def test_invalid_and_missing_requests_preserve_rejection_without_secrets(
    tmp_path,
):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        rejected = await client.post(
            "/internal/agent/runs",
            json=body(db) | {"api_key": "unconfigured-body-secret"},
            headers={
                "Authorization": "Bearer unconfigured-header-secret",
                "Cookie": "session=unconfigured-cookie-secret",
            },
        )
        missing = await client.post(
            "/internal/agent/runs", json=body(db) | {"messageId": 999}
        )
        assert rejected.status_code == missing.status_code == 400
        assert not rejected.content and not app.state.tasks and not db.saved
    recorded = {
        admission(spans)["output"]["outcome"]: spans for _, spans in requests(tmp_path)
    }
    assert set(recorded) == {"invalid_request", "question_not_found"}
    invalid = admission(recorded["invalid_request"])
    assert invalid["output"]["errors"] == [
        {"type": "extra_forbidden", "loc": ["body", "api_key"]}
    ]
    assert invalid["http_request"]["body"]["api_key"] == "[REDACTED]"
    failed_load = next(
        s for s in recorded["question_not_found"] if s["name"] == "load_question"
    )
    assert failed_load["status"] == "error"
    assert failed_load["error"]["type"] == "QuestionNotFound"
    raw = "\n".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.json*"))
    for secret in (
        "private-token",
        "unconfigured-body-secret",
        "unconfigured-header-secret",
        "unconfigured-cookie-secret",
    ):
        assert secret not in raw


@pytest.mark.asyncio
async def test_duplicate_and_conflict_remain_distinct_from_failed_admission(tmp_path):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    entered, release = asyncio.Event(), asyncio.Event()

    async def unavailable(*args):
        entered.set()
        await release.wait()
        raise DatabaseUnavailable from ConnectionError("private-token")

    db.load_question = unavailable
    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        pending = asyncio.create_task(
            client.post("/internal/agent/runs", json=body(db))
        )
        try:
            await asyncio.wait_for(entered.wait(), 2)
            duplicate = await client.post("/internal/agent/runs", json=body(db))
            conflict = await client.post(
                "/internal/agent/runs", json=body(db) | {"messageId": 103}
            )
            assert duplicate.status_code == 202 and conflict.status_code == 409
        finally:
            release.set()
        assert (await pending).status_code == 503
        assert not app.state.tasks and not db.saved
    recorded = {
        admission(spans)["output"]["outcome"]: spans for _, spans in requests(tmp_path)
    }
    assert set(recorded) == {
        "duplicate_active",
        "conversation_conflict",
        "database_unavailable",
    }
    assert (
        sum(s["name"] == "load_question" for spans in recorded.values() for s in spans)
        == 1
    )
    loading = next(
        s for s in recorded["database_unavailable"] if s["name"] == "load_question"
    )
    assert loading["error"]["type"] == "DatabaseUnavailable"
    assert loading["error"]["cause"]["type"] == "ConnectionError"
    assert "private-token" not in json.dumps(recorded)


@pytest.mark.asyncio
async def test_user_execution_manifest_links_original_admission_not_finished_duplicate(
    tmp_path,
):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    app = create_app(config, database=db, model=OfflineModel())
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
        assert (
            await client.post("/internal/agent/runs", json=body(db))
        ).status_code == 202
        await asyncio.gather(*tasks(app))
        saved_count = len(db.saved)
        assert (
            await client.post("/internal/agent/runs", json=body(db))
        ).status_code == 202
        assert len(db.saved) == saved_count and not app.state.tasks
    reports = list(tmp_path.glob("*/*/report.json"))
    assert len(reports) == 1
    manifest = read(reports[0].with_name("manifest.json"))
    linked = Path(manifest["request"]["trace_file"]).with_name("request.json")
    original = admission(read(linked)["trace"]["spans"])
    assert original["output"]["outcome"] == "accepted"
    assert manifest["request"]["span_id"] == original["id"]
    assert manifest["request"]["received_at"] == original["started_at"]
    assert {
        admission(spans)["output"]["outcome"] for _, spans in requests(tmp_path)
    } == {"accepted", "already_finished"}
    assert read(reports[0])["state"]["execution"]["status"] == "completed"


@pytest.mark.asyncio
async def test_cancel_observation_distinguishes_pending_cancel_from_no_target(tmp_path):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    state = await db.load_question(db.conversation_id, db.question)
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def cancellable_work():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            raise

    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        assert (
            await client.post(f"/internal/agent/runs/{uuid4()}/cancel")
        ).status_code == 202
        task = asyncio.create_task(cancellable_work())
        app.state.tasks[str(db.conversation_id)] = (state, task)
        try:
            await asyncio.wait_for(entered.wait(), 2)
            path = f"/internal/agent/runs/{db.conversation_id}/cancel"
            assert (await client.post(path)).status_code == 202
            await asyncio.wait_for(cancelled.wait(), 2)
            assert (await client.post(path)).status_code == 202
            assert task.cancelling() == 1
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            app.state.tasks.clear()
    observed = {
        admission(spans)["output"]["outcome"] for _, spans in requests(tmp_path)
    }
    assert observed == {
        "cancel_no_active_run",
        "cancel_requested",
        "cancel_already_requested",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_body", [False, True])
async def test_report_queue_prepare_and_all_notification_attempts_are_linked(
    tmp_path, invalid_body
):
    config, db = setup(tmp_path)
    config.report_concurrency = 1
    first_code, second_code = "1168066000", "1168064000"
    request = BODY | {"dongCodes": [first_code, second_code]}
    entered, release = asyncio.Event(), asyncio.Event()
    prepare = db.prepare_report
    received = []

    async def prepare_after_wait(state):
        if report_input(state)["dongCode"] == first_code:
            entered.set()
            await release.wait()
        await prepare(state)

    async def receiver(http_request):
        received.append(json.loads(http_request.content))
        assert len(db.saved) == 2
        if invalid_body:
            return httpx.Response(204, content=b"not empty")
        return httpx.Response(500 if len(received) == 1 else 204)

    db.prepare_report = prepare_after_wait
    app = create_app(config, database=db, model=ReportModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as backend,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        app.state.client = backend
        assert (await client.post(REPORT_PATH, json=request)).status_code == 202
        pending = list(app.state.report_tasks)
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.sleep(0.04)
        finally:
            release.set()
        states = (await asyncio.gather(*pending))[0]
    batch_path = next(tmp_path.glob("batches/*/request.json"))
    batch = read(batch_path)["trace"]
    overall = next(s for s in batch["spans"] if s["name"] == "api.report_request")
    assert batch["coverage"]["unfinished_spans"] == 0
    assert {r["run_id"] for r in overall["output"]["reports"]} == {
        s["execution"]["run_id"] for s in states
    }
    assert all(
        r["saved"] and r["status"] == "completed" for r in overall["output"]["reports"]
    )
    assert (
        overall["output"]["request_elapsed_seconds"]
        >= overall["output"]["processing_elapsed_seconds"]
        > 0
    )
    assert overall["output"]["completion_observed_at"] <= overall["ended_at"]
    notifications = [s for s in batch["spans"] if s["name"] == "notification"]
    assert len(notifications) == len(received) == (1 if invalid_body else 2)
    assert [s["http_request"]["attempt"] for s in notifications] == list(
        range(1, len(received) + 1)
    )
    assert all(s["parent_id"] == overall["id"] for s in notifications)
    assert [s["output"]["accepted"] for s in notifications] == (
        [False] if invalid_body else [False, True]
    )
    assert notifications[-1]["output"]["body_empty"] is not invalid_body
    assert notifications[-1]["ended_at"] <= overall["output"]["completion_observed_at"]
    assert all(
        p
        == {
            "requestId": BODY["requestId"],
            "month": BODY["month"],
            "savedCount": 2,
            "failedDongCodes": [],
        }
        for p in received
    )
    ingress = admission(requests(tmp_path)[0][1])
    for state in states:
        folder = tmp_path / state["execution"]["run_id"]
        report = read(folder / "report.json")
        manifest = read(folder / "manifest.json")
        assert manifest["request"]["span_id"] == ingress["id"]
        spans = report["trace"]["spans"]
        waiting = next(s for s in spans if s["name"] == "report_wait")
        prepared = next(s for s in spans if s["name"] == "prepare_report")
        first_node = next(s for s in spans if s["kind"] == "node")
        assert (
            waiting["ended_at"]
            <= prepared["started_at"]
            <= prepared["ended_at"]
            <= first_node["started_at"]
        )
        assert (
            prepared["output"]["source"]["adm_cd10"] == report_input(state)["dongCode"]
        )
        assert (
            first_node["input"]["state"]["execution"]["budget"]["active_seconds"][
                "used"
            ]
            == 0
        )
        if report_input(state)["dongCode"] == second_code:
            assert waiting["elapsed_seconds"] >= 0.03
        else:
            assert prepared["elapsed_seconds"] >= 0.03
    raw = "\n".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.json*"))
    assert "test-token" not in raw


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_sink", ["journal", "snapshot"])
async def test_observation_write_failure_after_commit_does_not_repeat_work(
    tmp_path, monkeypatch, caplog, failed_sink
):
    config, db = setup(tmp_path)
    states = create_report_states(BODY, config)
    received, failed_writes = [], []
    open_path = Path.open

    def unavailable_after_commit(path, mode="r", *args, **kwargs):
        selected = (
            path.name == "trace.jsonl"
            if failed_sink == "journal"
            else path.name != "trace.jsonl"
        )
        if (
            db.saved
            and selected
            and path.is_relative_to(tmp_path)
            and any(flag in mode for flag in "wax")
        ):
            failed_writes.append(path)
            raise OSError("private diagnostic storage location")
        return open_path(path, mode, *args, **kwargs)

    async def receiver(request):
        received.append(json.loads(request.content))
        assert len(db.saved) == 1
        return httpx.Response(204)

    monkeypatch.setattr(Path, "open", unavailable_after_commit)
    async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as client:
        result = await execute_reports(
            states, database=db, model=ReportModel(), client=client
        )
    state = result[0]
    assert failed_writes
    assert len(db.attempts) == len(db.saved) == 1
    assert state["execution"]["status"] == "completed"
    assert state["execution"]["error"] is None
    assert state["execution"]["budget"]["retries"]["used"] == 0
    saves = [item for item in state["results"] if item["decision"] == "report_save"]
    assert len(saves) == 1 and saves[0]["outcome"] == "success"
    assert received == [
        {
            "requestId": BODY["requestId"],
            "month": BODY["month"],
            "savedCount": 1,
            "failedDongCodes": [],
        }
    ]
    assert caplog.records
    assert "private diagnostic storage location" not in caplog.text


@pytest.mark.asyncio
async def test_cancelled_queued_batch_preserves_permit_and_request_context(tmp_path):
    config, db = setup(tmp_path)
    config.report_concurrency = 1
    entered, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()
    prepare = db.prepare_report
    received = []

    class QueueObservedSemaphore(asyncio.Semaphore):
        async def acquire(self):
            if self.locked():
                queued.set()
            return await super().acquire()

    async def held_prepare(state):
        if report_input(state)["requestId"] == "held":
            entered.set()
            await release.wait()
        await prepare(state)

    async def receiver(request):
        received.append(json.loads(request.content))
        return httpx.Response(204)

    db.prepare_report = held_prepare
    app = create_app(config, database=db, model=ReportModel())
    semaphore = QueueObservedSemaphore(1)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as backend,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        app.state.client = backend
        app.state.report_semaphore = semaphore
        held_request = BODY | {"requestId": "held"}
        cancelled_request = BODY | {
            "requestId": "cancelled",
            "dongCodes": ["1168064000"],
        }
        assert (await client.post(REPORT_PATH, json=held_request)).status_code == 202
        held = next(iter(app.state.report_tasks))
        cancelled = None
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert (
                await client.post(REPORT_PATH, json=cancelled_request)
            ).status_code == 202
            cancelled = next(
                task for task in app.state.report_tasks if task is not held
            )
            await asyncio.wait_for(queued.wait(), 2)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(cancelled, 2)
            assert semaphore.locked() and not held.done()
            release.set()
            states = await asyncio.wait_for(held, 5)
            assert states[0]["execution"]["status"] == "completed"
            await asyncio.wait_for(semaphore.acquire(), 1)
            assert semaphore.locked()
            semaphore.release()
        finally:
            release.set()
            pending = [held] + ([cancelled] if cancelled is not None else [])
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    assert len(db.attempts) == len(db.saved) == 1
    assert db.saved[0]["adm_cd10"] == BODY["dongCodes"][0]
    assert {item["requestId"]: item["savedCount"] for item in received} == {
        "held": 1,
        "cancelled": 0,
    }
    batch_spans = {}
    for path in tmp_path.glob("batches/*/request.json"):
        trace = read(path)["trace"]
        overall = next(s for s in trace["spans"] if s["name"] == "api.report_request")
        request_id = overall["input"]["reports"][0]["requestId"]
        batch_spans[request_id] = overall
        assert trace["coverage"]["unfinished_spans"] == 0
        notification = next(s for s in trace["spans"] if s["name"] == "notification")
        assert notification["parent_id"] == overall["id"]
        assert notification["input"]["requestId"] == request_id
        manifest = read(path.with_name("manifest.json"))
        origin = admission(
            read(Path(manifest["request"]["trace_file"]).with_name("request.json"))[
                "trace"
            ]["spans"]
        )
        assert origin["http_request"]["body"]["requestId"] == request_id
        dong_run = overall["input"]["reports"][0]["run_id"]
        child_manifest = read(tmp_path / dong_run / "manifest.json")
        assert child_manifest["request"] == manifest["request"]
        child = read(tmp_path / dong_run / "report.json")["trace"]
        assert child["coverage"]["unfinished_spans"] == 0
        if request_id == "cancelled":
            waiting = next(s for s in child["spans"] if s["name"] == "report_wait")
            assert waiting["error"]["type"] == "CancelledError"
            assert not any(s["name"] == "prepare_report" for s in child["spans"])
    assert set(batch_spans) == {"held", "cancelled"}
    assert batch_spans["held"]["id"] != batch_spans["cancelled"]["id"]
    assert batch_spans["cancelled"]["error"]["type"] == "CancelledError"
