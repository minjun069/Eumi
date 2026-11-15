import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from api import create_app, notify
from src.database import DatabaseUnavailable, response_row
from src.settings import Settings
from tests.api_fixtures import MemoryDatabase, OfflineModel


def settings(tmp_path):
    return Settings(
        _env_file=None,
        output_dir=tmp_path,
        backend_url="http://backend.test",
        backend_token="private-token",
        langfuse_enabled=False,
    )


def body(db):
    return {"conversationId": str(db.conversation_id), "messageId": db.question}


def tasks(app):
    return [task for _, task in app.state.tasks.values()]


@pytest.mark.asyncio
async def test_progress_commit_then_notification_and_terminal_row(tmp_path):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    sent = []

    async def receiver(request):
        payload = json.loads(request.content)
        assert request.url.path == "/api/internal/agent/notifications"
        assert request.headers["Authorization"] == "Bearer private-token"
        assert set(payload) == {"conversationId", "messageId"}
        assert payload["messageId"] == 101 + len(db.saved)
        sent.append(payload)
        return httpx.Response(204)

    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as receiver_client,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        app.state.client = receiver_client
        request = body(db) | {"context": {"dongCode": "1168066000", "month": "2025-12"}}
        result = await client.post("/internal/agent/runs", json=request)
        assert result.status_code == 202 and not result.content
        await asyncio.gather(*tasks(app))
        assert (await client.get("/health")).json() == {"status": "UP"}
        # Completed duplicates are acknowledged without another execution.
        assert (
            await client.post("/internal/agent/runs", json=request)
        ).status_code == 202
    rows = [response_row(s) for s in db.saved]
    assert [r["content"] for r in rows[:-1]] == [
        "질문 이해",
        "진행 판단",
        "자료 조회·작업 실행",
        "진행 판단",
        "답변 작성",
    ]
    assert all(r["status"] == "진행" for r in rows[:-1])
    assert rows[-1]["status"] == "완료"
    assert len(sent) == len(rows)
    report_text = next(tmp_path.rglob("report.json")).read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["failure"] is None and "private-token" not in report_text
    request = next(
        r for r in report["state"]["results"] if r["decision"] == "run_request"
    )
    assert request["action"]["arguments"]["context"]["month"] == "2025-12"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure, expected_attempts", [(500, 2), (404, 1), ("body", 1), ("timeout", 2)]
)
async def test_notification_failure_only_retries_delivery(
    tmp_path, failure, expected_attempts
):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    state = await db.load_question(db.conversation_id, db.question)
    attempts = []

    async def receiver(request):
        attempts.append(json.loads(request.content))
        if failure == "timeout":
            raise httpx.ReadTimeout("private-token")
        return httpx.Response(
            204 if failure == "body" else failure,
            content=b"wrong" if failure == "body" else b"",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as client:
        assert not await notify(
            client,
            config,
            state,
            "/api/internal/agent/notifications",
            {"conversationId": str(db.conversation_id), "messageId": 102},
        )
    assert len(attempts) == expected_attempts
    assert not db.saved
    assert (
        len([r for r in state["results"] if r["decision"] == "notification"])
        == expected_attempts
    )


@pytest.mark.asyncio
async def test_notification_outage_preserves_saved_completion(tmp_path):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500))
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
    assert sum(response_row(s)["status"] == "완료" for s in db.saved) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"conversationId": "bad", "messageId": 1},
        {"conversationId": str(uuid4()), "messageId": "1"},
        {"conversationId": str(uuid4()), "messageId": 0},
        {"conversationId": str(uuid4()), "messageId": True},
        {"conversation_id": str(uuid4()), "question_id": 1},
        {
            "conversationId": str(uuid4()),
            "messageId": 1,
            "context": {"month": "2025-13"},
        },
    ],
)
async def test_invalid_request_never_executes(tmp_path, payload):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        result = await client.post("/internal/agent/runs", json=payload)
        assert result.status_code == 400 and not result.content
        assert not app.state.tasks and not db.saved


@pytest.mark.asyncio
async def test_duplicate_admission_is_reserved_and_load_failure_releases(tmp_path):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    entered, release = asyncio.Event(), asyncio.Event()

    async def unavailable(*args):
        entered.set()
        await release.wait()
        raise DatabaseUnavailable

    db.load_question = unavailable
    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        first = asyncio.create_task(client.post("/internal/agent/runs", json=body(db)))
        await asyncio.wait_for(entered.wait(), 2)
        assert (
            await client.post("/internal/agent/runs", json=body(db))
        ).status_code == 202
        assert (
            await client.post(
                "/internal/agent/runs", json=body(db) | {"messageId": 103}
            )
        ).status_code == 409
        release.set()
        assert (await first).status_code == 503
        assert not app.state.tasks


class WaitingModel(OfflineModel):
    def with_structured_output(self, schema, **kwargs):
        async def invoke(messages, config):
            values = {
                "Interpretation": {
                    "request": {"goal": "지역 확인"},
                    "reason": "지역 필요",
                },
                "Decision": {"next": "ask", "reason": "지역 필요"},
                "Question": {"content": "어느 지역인가요?", "reason": "지역 필요"},
            }
            return {
                "raw": AIMessage(
                    json.dumps(values[schema["title"]], ensure_ascii=False)
                )
            }

        return RunnableLambda(invoke)


@pytest.mark.asyncio
async def test_waiting_input_is_committed_as_completed(tmp_path):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    app = create_app(config, database=db, model=WaitingModel())
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
    assert db.saved[-1]["execution"]["status"] == "waiting_input"
    assert response_row(db.saved[-1])["status"] == "완료"
    assert response_row(db.saved[-1])["content"] == "어느 지역인가요?"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [True, False])
async def test_cancellation_and_wall_deadline_commit_terminal(
    tmp_path, monkeypatch, cancel
):
    import api

    config = settings(tmp_path)
    db = MemoryDatabase(config)
    entered = asyncio.Event()

    async def blocked(state, config):
        entered.set()
        await asyncio.Event().wait()

    if not cancel:
        load = db.load_question

        async def short_budget(*args):
            state = await load(*args)
            state["execution"]["budget"]["active_seconds"]["limit"] = 0.15
            state["execution"]["budget"]["final_active_seconds"]["limit"] = 3
            return state

        db.load_question = short_budget
    monkeypatch.setattr(
        api,
        "build_nodes",
        lambda *a, **k: {
            name: blocked for name in ("interpret", "act", "decide", "compose", "ask")
        },
    )
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
        await asyncio.wait_for(entered.wait(), 2)
        pending = tasks(app)
        if cancel:
            path = f"/internal/agent/runs/{db.conversation_id}/cancel"
            assert (await client.post(path)).status_code == 202
            assert (await client.post(path)).status_code == 202
        await asyncio.wait_for(asyncio.gather(*pending), 3)
    assert response_row(db.saved[-1])["status"] == ("취소" if cancel else "실패")
    assert len([s for s in db.saved if response_row(s)["status"] != "진행"]) == 1


@pytest.mark.asyncio
async def test_terminal_save_failure_does_not_notify_unsaved_row(tmp_path):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    save = db.save_response
    failed = []
    sent = []

    async def fail_terminal(state):
        if state["execution"]["status"] == "completed":
            failed.append(True)
            raise DatabaseUnavailable
        return await save(state)

    db.save_response = fail_terminal

    async def receive(request):
        sent.append(json.loads(request.content))
        return httpx.Response(204)

    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.MockTransport(receive)) as backend,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        app.state.client = backend
        assert (
            await client.post("/internal/agent/runs", json=body(db))
        ).status_code == 202
        await asyncio.gather(*tasks(app))
    assert len(failed) == 1 and len(sent) == len(db.saved)
    assert all(response_row(s)["status"] == "진행" for s in db.saved)
    report = json.loads(next(tmp_path.rglob("report.json")).read_text(encoding="utf-8"))
    assert report["failure"]["error_type"] == "DatabaseUnavailable"


@pytest.mark.asyncio
async def test_cancel_before_background_coroutine_starts_still_commits(tmp_path):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    state = await db.load_question(db.conversation_id, db.question)
    app = create_app(config, database=db, model=OfflineModel())
    entered = []

    async def not_started():
        entered.append(True)
        await asyncio.Event().wait()

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(204))
        ) as backend,
    ):
        app.state.client = backend
        pending = asyncio.create_task(not_started())
        app.state.tasks[str(db.conversation_id)] = (state, pending)
        cancel = next(r.endpoint for r in app.routes if r.path.endswith("/cancel"))
        assert (await cancel(db.conversation_id)).status_code == 202
        await asyncio.gather(*tasks(app))
    assert not entered and pending.cancelled()
    assert response_row(db.saved[-1])["status"] == "취소"


def test_backend_settings_and_token_redaction(monkeypatch):
    from src.execution_trace import safe_settings

    monkeypatch.setenv("SETTINGS_BACKEND_URL", "http://backend:8080")
    monkeypatch.setenv("SETTINGS_BACKEND_TOKEN", "secret-test-token")
    monkeypatch.setenv("SETTINGS_BASE_URL", "https://gateway.test/v1")
    config = Settings(_env_file=None)
    assert str(config.backend_url) == "http://backend:8080/"
    assert str(config.base_url) == "https://gateway.test/v1"
    assert "secret-test-token" not in json.dumps(safe_settings(config))
