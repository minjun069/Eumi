"""현재 State 계약을 사용하는 그래프 검증. 모델·외부 도구는 호출하지 않는다."""

from copy import deepcopy

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.types import Command

from experiments.fixtures import mock_nodes
from src.graph import compile_graph
from src.settings import Settings
from src.state import create_state, state_adapter


def initial():
    return create_state(
        {"goal": "test"},
        Settings(_env_file=None),
        messages=[SystemMessage("Test instruction", id="system")],
        version="test",
        event="user_request",
    )


@pytest.mark.parametrize("scenario", ["intermediate", "question", "partial", "failure"])
def test_scenarios_preserve_state_and_resume(scenario):
    state = initial()
    original = deepcopy(state)
    saver = InMemorySaver()
    callbacks, completion = mock_nodes(scenario)
    graph = compile_graph(callbacks, finish=completion, checkpointer=saver)
    config = {"configurable": {"thread_id": state["execution"]["run_id"]}}
    snapshots = list(graph.stream(state, config, stream_mode="values"))
    if scenario == "question":
        saved = graph.get_state(config)
        assert saved.next == ("wait",)
        question = saved.values["response"]
        records = deepcopy(saved.values["results"])
        paused = graph.invoke(Command(resume=" "), config)
        assert paused["execution"]["status"] == "waiting_input"
        assert paused["response"] == question
        assert paused["results"] == records
        graph = compile_graph(callbacks, finish=completion, checkpointer=saver)
        snapshots.extend(
            graph.stream(Command(resume="answer"), config, stream_mode="values")
        )
    result = graph.get_state(config).values
    state_adapter.validate_python(result)
    assert state == original
    assert result["execution"]["budget"]["steps"]["used"] > 0
    assert {k: v["limit"] for k, v in result["execution"]["budget"].items()} == {
        k: v["limit"] for k, v in original["execution"]["budget"].items()
    }
    assert result["execution"]["status"] == {
        "partial": "partial",
        "failure": "failed",
    }.get(scenario, "completed")
    assert result["response"]["kind"] == "final"
    assert result["results"][0]["node"] == "interpret"
    assert sum(r["action"] is not None for r in result["results"]) == (
        2 if scenario == "intermediate" else 1
    )
    assert sum(isinstance(m, HumanMessage) for m in result["messages"]) == (
        scenario == "question"
    )
    if scenario == "intermediate":
        assert any(
            (s.get("response") or {}).get("kind") == "intermediate"
            and s["execution"]["status"] == "running"
            for s in snapshots
        )


def response(kind="final", artifacts=None):
    return {
        "id": "response",
        "kind": kind,
        "label": "test",
        "content": "result",
        "artifacts": artifacts or [],
    }


def nodes():
    return {
        "interpret": lambda s: Command(update={}, goto="act"),
        "act": lambda s: Command(update={}, goto="decide"),
        "decide": lambda s: Command(update={}, goto="compose"),
        "compose": lambda s: Command(update={"response": response()}, goto=END),
        "ask": lambda s: Command(
            update={"response": response("question")}, goto="wait"
        ),
    }


def finish(state):
    return {"status": "completed", "error": None}


@pytest.mark.parametrize(
    "name,command",
    [
        ("act", Command(update={"request": {"goal": "overwrite"}}, goto="decide")),
        ("act", Command(update={}, goto=END)),
        ("ask", Command(update={}, goto="wait")),
        ("compose", Command(update={"response": response("intermediate")}, goto=END)),
    ],
)
def test_rejects_invalid_node_updates(name, command):
    callbacks = nodes()
    callbacks[name] = lambda s: command
    if name == "ask":
        callbacks["decide"] = lambda s: Command(update={}, goto="ask")
    graph = compile_graph(callbacks, finish=finish)
    result = graph.invoke(initial())
    assert result["execution"]["status"] == "failed"
    assert result["execution"]["error"]["code"] == "runtime_error"
    assert result["request"] == initial()["request"]


def test_progress_preserves_published_artifacts():
    state = initial()
    state["response"] = response(
        "intermediate", [{"type": "table", "data": {"value": 1}}]
    )
    callbacks = nodes()
    callbacks["act"] = lambda s: Command(
        update={"response": response("progress")}, goto="decide"
    )
    graph = compile_graph(callbacks, finish=finish)
    result = graph.invoke(state)
    assert result["execution"]["status"] == "partial"
    assert result["execution"]["error"]["code"] == "runtime_error"
    assert result["response"]["artifacts"] == state["response"]["artifacts"]
