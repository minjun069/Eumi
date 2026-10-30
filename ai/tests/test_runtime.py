import asyncio
from copy import deepcopy

import pytest
from langchain_core.tools import tool
from pydantic import ValidationError

from src.runtime import AgentRuntime
from src.settings import Settings
from src.state import Request
from tests.helpers import ScriptedModel, finish
from tests.test_graph import graph


def runtime(model, **settings):
    return AgentRuntime({"test": graph(model)}, Settings(_env_file=None, **settings))


async def start(app, **kwargs):
    return await app.start(
        "test",
        Request(goal="Synthetic experiment"),
        instruction_version="test-v1",
        **kwargs,
    )


def answer(state, content="A"):
    execution = state["execution"]
    return {
        "run_id": execution["run_id"],
        "pending_id": execution["pending"]["id"],
        "expected_input_version": execution["input_version"],
        "content": content,
        "data_versions": execution["data_versions"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"goal": " "},
        {"goal": "Explain", "unexpected": True},
        {"goal": "Explain", "constraints": {"required": [123]}},
    ],
)
async def test_invalid_request_is_rejected_before_starting_a_run(payload):
    model = ScriptedModel(finish())
    app = runtime(model)
    with pytest.raises(ValidationError):
        await app.start("test", payload, instruction_version="test-v1")
    assert app.runs == {}
    assert model.invocations == 0


@pytest.mark.asyncio
async def test_question_versions_and_late_answer(monkeypatch):
    app = runtime(
        ScriptedModel(
            ("ask_user", {"question": "Region?"}),
            ("ask_user", {"question": "Period?"}),
            finish(),
        )
    )
    waiting = await start(app, data_versions={"analysis": "v1"})
    old = answer(waiting)
    for change in (
        {"pending_id": "wrong"},
        {"expected_input_version": 0},
        {"data_versions": {"analysis": "v2"}},
        {"content": " "},
    ):
        with pytest.raises(ValueError):
            await app.resume(**(old | change))
    assert app.get(old["run_id"])["execution"]["attempts"]["steps"] == 1
    # Move wall time forward by a day: waiting has no expiry or active-time cost.
    from src import runtime as module

    now = module.monotonic
    monkeypatch.setattr(module, "monotonic", lambda: now() + 86400)
    second = await app.resume(**old)
    assert second["execution"]["input_version"] == 2
    assert second["execution"]["pending"]["id"] != old["pending_id"]
    with pytest.raises(ValueError):
        await app.resume(**old)
    done = await app.resume(**answer(second, "2026-09"))
    assert done["execution"]["status"] == "completed"
    assert done["execution"]["attempts"]["active_seconds"] < 10
    with pytest.raises(ValueError):
        await app.resume(**answer(second))


@pytest.mark.asyncio
async def test_isolated_requests_results_and_validator_inputs():
    async def validate(state, result):
        state["info"]["nested"].append(9)
        state["request"]["goal"] = "changed"
        return []

    model = ScriptedModel(("ask_user", {"question": "Region?"}), finish())
    app = AgentRuntime(
        {"test": graph(model, validate=validate)}, Settings(_env_file=None)
    )
    info = {"nested": [1]}
    first = await start(app, info=info)
    saved = deepcopy(first)
    second = await start(app, info={"nested": [2]})
    info["nested"].append(3)
    first["info"]["nested"].append(4)
    first["execution"]["attempts"]["steps"] = 100
    done = await app.resume(**answer(saved))
    assert done["info"] == {"nested": [1]}
    assert done["request"]["goal"] == "Synthetic experiment"
    assert (
        app.get(second["execution"]["run_id"])["execution"]["status"] == "waiting_input"
    )


@pytest.mark.asyncio
async def test_child_budget_preserves_completed_results():
    artifact = {"type": "analysis_interpretation", "data": {"value": 12}}
    child = graph(ScriptedModel(finish(results=[artifact])))
    parent = graph(
        ScriptedModel(("child", {"goal": "Read"}), finish()), children={"child": child}
    )
    app = AgentRuntime({"test": parent}, Settings(max_steps=2, _env_file=None))
    result = await start(app)
    assert result["execution"]["status"] == "partial"
    assert result["execution"]["attempts"]["steps"] == 2
    assert result["results"][0]["data"]["value"] == 12


@pytest.mark.asyncio
async def test_cancel_waiting_and_finished_runs():
    app = runtime(ScriptedModel(("ask_user", {"question": "Region?"}), finish()))
    waiting = await start(app)
    run_id = waiting["execution"]["run_id"]
    cancelled = await app.cancel(run_id)
    assert cancelled["execution"]["status"] == "cancelled"
    assert cancelled["execution"]["pending"] is None
    assert await app.cancel(run_id) == cancelled
    with pytest.raises(ValueError):
        await app.resume(**answer(waiting))
    finished_app = runtime(ScriptedModel(finish()))
    finished = await start(finished_app)
    assert await finished_app.cancel(finished["execution"]["run_id"]) == finished


@pytest.mark.asyncio
async def test_running_cancel_and_concurrent_resume():
    entered = asyncio.Event()
    release = asyncio.Event()

    @tool
    async def slow() -> str:
        """Read data with a simulated delay."""
        entered.set()
        await release.wait()
        return "ready"

    model = ScriptedModel(("ask_user", {"question": "Region?"}), ("slow", {}), finish())
    app = AgentRuntime({"test": graph(model, tools=[slow])}, Settings(_env_file=None))
    waiting = await start(app)
    running = asyncio.create_task(app.resume(**answer(waiting)))
    await asyncio.wait_for(entered.wait(), timeout=3)
    with pytest.raises(ValueError):
        await app.resume(**answer(waiting))
    first, second = await asyncio.gather(
        app.cancel(waiting["execution"]["run_id"]),
        app.cancel(waiting["execution"]["run_id"]),
    )
    assert first["execution"]["status"] == second["execution"]["status"] == "cancelled"
    assert (await running)["execution"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_active_timeout_stops_tool():
    stopped = asyncio.Event()

    @tool
    async def slow() -> str:
        """A cancellable slow read."""
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    app = AgentRuntime(
        {"test": graph(ScriptedModel(("slow", {})), tools=[slow])},
        Settings(runtime_timeout=0.15, _env_file=None),
    )
    result = await start(app)
    assert result["execution"]["error"]["code"] == "time_limit"
    assert stopped.is_set()
