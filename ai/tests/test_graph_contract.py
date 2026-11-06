"""현재 State 계약을 사용하는 그래프 검증. 모델·외부 도구는 호출하지 않는다."""

from copy import deepcopy
from typing import get_args

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.types import Command

from experiments.fixtures import Scenario, mock_nodes
from src.graph import compile_graph
from src.settings import Settings
from src.state import create_state, state_adapter


def initial(goal="test", event="user_request"):
    return create_state(
        {"goal": goal},
        Settings(_env_file=None),
        messages=[SystemMessage("Test instruction", id="system")],
        version="test",
        event=event,
    )


@pytest.mark.parametrize("scenario", get_args(Scenario))
@pytest.mark.parametrize("event", (False, True))
def test_scenarios_preserve_state_and_resume(scenario, event):
    state = initial(event="analysis_pipeline" if event else "user_request")
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
        for answer in (" ", 42):
            paused = graph.invoke(Command(resume=answer), config)
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
    assert result["execution"]["budget"] == original["execution"]["budget"]
    assert result["execution"]["status"] == {
        "partial": "partial",
        "failure": "failed",
    }.get(scenario, "completed")
    assert result["response"]["kind"] == "final"
    assert result["results"][0]["node"] == ("act" if event else "interpret")
    assert sum(r["action"] is not None for r in result["results"]) == (
        2 if scenario in {"continue", "intermediate"} else 1
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


def test_one_graph_uses_each_states_event_for_entry():
    callbacks, completion = mock_nodes("complete")
    graph = compile_graph(callbacks, finish=completion)
    for event, first_node in (
        ("analysis_pipeline", "act"),
        ("user_request", "interpret"),
        ("analysis_pipeline", "act"),
    ):
        state = initial(event=event)
        result = graph.invoke(state)
        assert result["results"][0]["node"] == first_node
        assert result["execution"]["event"] == event


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
    return {
        "status": "partial" if state["request"]["goal"] == "partial" else "completed",
        "error": None,
    }


@pytest.mark.parametrize(
    "name,command",
    [
        ("act", Command(update={"request": {"goal": "overwrite"}}, goto="decide")),
        (
            "act",
            Command(update={"messages": [HumanMessage("invented")]}, goto="decide"),
        ),
        ("act", Command(update={}, goto=END)),
        ("act", Command(update={"response": response("final")}, goto="decide")),
        ("ask", Command(update={}, goto="wait")),
        ("compose", Command(update={"response": response("intermediate")}, goto=END)),
        ("compose", Command(update={"response": response()}, goto="act")),
    ],
)
def test_rejects_invalid_node_updates(name, command):
    callbacks = nodes()
    callbacks[name] = lambda s: command
    if name == "ask":
        callbacks["decide"] = lambda s: Command(update={}, goto="ask")
    graph = compile_graph(callbacks, finish=finish)
    with pytest.raises(ValueError):
        graph.invoke(initial())


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
    with pytest.raises(ValueError, match="preserve artifacts"):
        graph.invoke(state)


@pytest.mark.asyncio
async def test_async_node_and_completion_use_current_state():
    callbacks = nodes()

    async def interpret(state):
        return Command(update={}, goto="act")

    callbacks["interpret"] = interpret
    graph = compile_graph(callbacks, finish=finish)
    for goal, status in (("test", "completed"), ("partial", "partial")):
        result = await graph.ainvoke(initial(goal))
        assert result["execution"]["status"] == status
