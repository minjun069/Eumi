"""현재 State 계약을 사용하는 그래프 검증. 모델·외부 도구는 호출하지 않는다."""

from copy import deepcopy

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.types import Command

from experiments.fixtures import mock_nodes
from src.execution import record
from src.execution_trace import TraceRecorder, recording
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


@pytest.mark.asyncio
async def test_wait_trace_preserves_interrupt_then_resume_boundary():
    state = initial()
    nodes, finish = mock_nodes("question")
    graph = compile_graph(nodes, finish=finish, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": state["execution"]["run_id"]}}
    recorder = TraceRecorder()
    with recording(recorder):
        waiting = await graph.ainvoke(state, config)
        assert waiting["execution"]["status"] == "waiting_input"
        completed = await graph.ainvoke(Command(resume="answer"), config)
    spans = [s for s in recorder.spans if s["name"] == "wait"]
    assert len(spans) == 2
    assert spans[0]["status"] == "interrupted"
    assert spans[0]["error"]["type"] == "GraphInterrupt"
    assert "output" not in spans[0]
    assert spans[1]["status"] == "success"
    assert spans[1]["output"]["goto"] == "interpret"
    assert spans[1]["output"]["node_update"]["messages"][0]["content"] == "answer"
    assert completed["execution"]["status"] == "completed"
    assert recorder.export()["coverage"]["unfinished_spans"] == 0


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
        # 중간 작성 이후의 추가 작업도 진행 판단을 반드시 거친다.
        assert [item["node"] for item in result["results"]] == [
            "interpret",
            "decide",
            "act",
            "act",
            "act",
            "decide",
            "compose",
            "decide",
            "act",
            "act",
            "act",
            "decide",
            "compose",
        ]


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
        "interpret": lambda s: Command(update={}, goto="decide"),
        "act": lambda s: Command(
            update={"results": [record("act", "call", "자료 확보")]}, goto="decide"
        ),
        "decide": lambda s: Command(
            update={},
            goto="compose" if any(r["node"] == "act" for r in s["results"]) else "act",
        ),
        "compose": lambda s: Command(update={"response": response()}, goto=END),
        "ask": lambda s: Command(
            update={"response": response("question")}, goto="wait"
        ),
    }


def finish(state):
    return {"status": "completed", "error": None}


@pytest.mark.parametrize("event", ["user_request", "analysis_pipeline"])
@pytest.mark.parametrize("next_node", ["act", "compose", "ask"])
def test_first_decision_precedes_work_or_routes_directly_to_response(event, next_node):
    state = initial()
    state["execution"]["event"] = event
    visited = []
    callbacks = nodes()

    def decide(current):
        visited.append("decide")
        return Command(
            update={},
            goto=next_node if visited.count("decide") == 1 else "compose",
        )

    for name in ("interpret", "act", "compose", "ask"):
        callback = callbacks[name]

        def observe(current, name=name, callback=callback):
            visited.append(name)
            return callback(current)

        callbacks[name] = observe
    callbacks["decide"] = decide
    graph = compile_graph(callbacks, finish=finish, checkpointer=InMemorySaver())
    result = graph.invoke(
        state, {"configurable": {"thread_id": f"{event}-{next_node}"}}
    )
    expected = (["interpret"] if event == "user_request" else []) + ["decide"]
    expected += ["act", "decide", "compose"] if next_node == "act" else [next_node]
    assert visited == expected
    assert result["execution"]["status"] == (
        "waiting_input" if next_node == "ask" else "completed"
    )
    assert result["execution"]["budget"]["steps"]["used"] == len(expected)


@pytest.mark.parametrize(
    "name,command",
    [
        ("interpret", Command(update={}, goto="act")),
        ("act", Command(update={"request": {"goal": "overwrite"}}, goto="decide")),
        ("act", Command(update={}, goto=END)),
        ("ask", Command(update={}, goto="wait")),
        ("compose", Command(update={"response": response("intermediate")}, goto=END)),
        ("compose", Command(update={"response": response("intermediate")}, goto="act")),
        ("compose", Command(update={"response": response("intermediate")}, goto="ask")),
        ("compose", Command(update={"response": response("final")}, goto="decide")),
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


@pytest.mark.parametrize("next_node", ["act", "compose", "ask"])
def test_intermediate_response_returns_to_decision_before_continuing(next_node):
    visited = []
    callbacks = nodes()

    def decide(state):
        visited.append("decide")
        after_draft = (state["response"] or {}).get("kind") == "intermediate"
        target = (
            next_node if after_draft and visited.count("decide") == 2 else "compose"
        )
        return Command(update={}, goto=target)

    def compose(state):
        visited.append("compose")
        intermediate = visited.count("compose") == 1
        return Command(
            update={"response": response("intermediate" if intermediate else "final")},
            goto="decide" if intermediate else END,
        )

    def act(state):
        visited.append("act")
        return Command(update={}, goto="decide")

    callbacks.update(decide=decide, compose=compose, act=act)
    graph = compile_graph(callbacks, finish=finish, checkpointer=InMemorySaver())
    result = graph.invoke(initial(), {"configurable": {"thread_id": next_node}})
    assert visited[:3] == ["decide", "compose", "decide"]
    if next_node == "ask":
        assert result["execution"]["status"] == "waiting_input"
        assert result["response"]["kind"] == "question"
    else:
        assert visited[3:] == (
            ["act", "decide", "compose"] if next_node == "act" else ["compose"]
        )
        assert result["execution"]["status"] == "completed"


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
