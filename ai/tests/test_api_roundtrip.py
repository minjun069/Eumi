import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from api import create_app
from src.database import Database, DatabaseUnavailable, UnmappedResponse
from src.settings import Settings
from tests.api_fixtures import MemoryDatabase, OfflineModel


def settings(tmp_path):
    return Settings(
        _env_file=None,
        output_dir=tmp_path,
        notification_url="http://receiver.test/completed",
        langfuse_enabled=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "save", "notify", "ack_body", "timeout"])
async def test_commit_before_notification_and_independent_delivery_failure(
    tmp_path, failure
):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    if failure == "save":

        async def broken_save(state):
            raise DatabaseUnavailable

        db.save_response = broken_save
    sent = []

    async def receiver(request):
        assert db.saved
        sent.append(json.loads(request.content))
        if failure == "timeout":
            raise httpx.ReadTimeout("private transport details")
        return httpx.Response(
            500 if failure == "notify" else 204,
            content=b"unexpected" if failure == "ack_body" else b"",
        )

    app = create_app(config, database=db, model=OfflineModel())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(receiver)
        ) as receiver_client:
            app.state.client = receiver_client
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://ai.test",
            ) as client:
                response = await client.post(
                    "/internal/agent/runs",
                    json={
                        "conversation_id": str(db.conversation_id),
                        "question_id": db.question,
                    },
                )
                assert response.status_code == 202 and response.content == b""
                await asyncio.gather(*list(app.state.tasks.values()))
    report = json.loads(next(tmp_path.rglob("report.json")).read_text(encoding="utf-8"))
    assert report["state"]["execution"]["status"] == "completed"
    assert bool(report["failure"]) == bool(failure)
    assert len(db.saved) == (0 if failure == "save" else 1)
    assert len(sent) == (0 if failure == "save" else 1)
    if sent:
        assert sent == [
            {
                "conversation_id": str(db.conversation_id),
                "question_id": 101,
                "message_id": 102,
            }
        ]
    assert "private transport details" not in json.dumps(report)
    assert next(tmp_path.rglob("trace.jsonl")).exists()
    assert next(tmp_path.rglob("report.html")).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"conversation_id": "bad", "question_id": 1},
        {"conversation_id": str(uuid4()), "question_id": "1"},
        {"conversation_id": str(uuid4()), "question_id": 0},
        {"conversation_id": str(uuid4()), "question_id": True},
        {"conversation_id": str(uuid4()), "message_id": 1},
    ],
)
async def test_invalid_request_never_executes(tmp_path, body):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://ai.test",
        ) as client,
    ):
        assert (await client.post("/internal/agent/runs", json=body)).status_code == 422
        assert not app.state.tasks and not db.saved


@pytest.mark.asyncio
async def test_concurrent_acceptance_is_reserved_and_released_on_load_error(tmp_path):
    config = settings(tmp_path)
    db = MemoryDatabase(config)
    entered, release = asyncio.Event(), asyncio.Event()

    async def unavailable(*args):
        entered.set()
        await release.wait()
        raise DatabaseUnavailable

    db.load_question = unavailable
    app = create_app(config, database=db, model=OfflineModel())
    body = {"conversation_id": str(db.conversation_id), "question_id": 101}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://ai.test",
        ) as client,
    ):
        first = asyncio.create_task(client.post("/internal/agent/runs", json=body))
        await asyncio.wait_for(entered.wait(), 2)
        assert (await client.post("/internal/agent/runs", json=body)).status_code == 409
        release.set()
        assert (await first).status_code == 503
        assert not app.state.tasks


@pytest.mark.asyncio
async def test_missing_configuration_is_explicit(tmp_path):
    config = settings(tmp_path)
    db = Database(config)
    with pytest.raises(DatabaseUnavailable):
        await db.connect()
    config.notification_url = None
    app = create_app(config, database=db, model=OfflineModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://ai.test",
        ) as client,
    ):
        response = await client.post(
            "/internal/agent/runs",
            json={
                "conversation_id": str(uuid4()),
                "question_id": 1,
            },
        )
        assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["waiting_input", "partial"])
async def test_unconfirmed_db_mapping_is_not_silently_converted(tmp_path, status):
    config = settings(tmp_path)
    fixture = MemoryDatabase(config)
    state = await fixture.load_question(fixture.conversation_id, fixture.question)
    state["execution"]["status"] = status
    with pytest.raises(UnmappedResponse):
        await Database(config).save_response(state)
