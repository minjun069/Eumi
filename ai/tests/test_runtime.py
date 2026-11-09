"""현재 실행·재개 경계의 상태 보존, 한도와 취소를 검증한다."""

import asyncio
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from experiments.fixtures import initial_state, mock_nodes
from src.exceptions import LimitReached
from src.execution import consume, merge_child_budget
from src.graph import compile_graph
from src.runtime import resume_graph, run_graph
from src.state import create_child_state


@pytest.mark.asyncio
async def test_resume_rejects_wrong_question_and_reuses_saved_state():
    nodes, finish = mock_nodes("question")
    saver = InMemorySaver()
    graph = compile_graph(nodes, finish=finish, checkpointer=saver)
    state = initial_state()
    waiting = await run_graph(graph, state)
    run_id, question_id = waiting["execution"]["run_id"], waiting["response"]["id"]
    original = deepcopy(waiting)
    for pending, answer in (("wrong", "답변"), (question_id, " "), (question_id, 42)):
        with pytest.raises(ValueError):
            await resume_graph(graph, run_id, pending, answer)
    saved = await graph.aget_state({"configurable": {"thread_id": run_id}})
    assert saved.values["results"] == original["results"]
    assert saved.values["execution"] == original["execution"]
    with pytest.raises(ValueError):
        await run_graph(graph, waiting)
    rebuilt = compile_graph(nodes, finish=finish, checkpointer=saver)
    result = await resume_graph(rebuilt, run_id, question_id, "답변")
    assert result["execution"]["run_id"] == run_id
    assert result["execution"]["status"] == "completed"
    assert result["results"][: len(original["results"])] == original["results"]
    assert (
        result["execution"]["budget"]["steps"]["used"]
        > original["execution"]["budget"]["steps"]["used"]
    )
    assert [m.content for m in result["messages"] if m.type == "human"] == ["답변"]
    with pytest.raises(ValueError):
        await resume_graph(rebuilt, run_id, question_id, "중복 답변")


def test_child_budget_is_cumulative_and_isolated():
    parent = initial_state()
    consume(parent, "tool_calls")
    child = create_child_state({"goal": "하위 작업"}, parent)
    assert child["execution"]["event"] == parent["execution"]["event"]
    assert child["execution"]["run_id"] != parent["execution"]["run_id"]
    consume(child, "tool_calls")
    assert parent["execution"]["budget"]["tool_calls"]["used"] == 1
    merge_child_budget(parent, child)
    assert parent["execution"]["budget"]["tool_calls"]["used"] == 2
    parent["execution"]["budget"]["tool_calls"]["limit"] = 2
    with pytest.raises(LimitReached):
        consume(parent, "tool_calls")
    child["execution"]["budget"]["tool_calls"]["limit"] += 1
    with pytest.raises(ValueError):
        merge_child_budget(parent, child)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancellation_stop_running_work(cancel):
    state = initial_state()
    state["execution"]["budget"]["active_seconds"]["limit"] = 1
    entered, stopped = asyncio.Event(), asyncio.Event()

    async def slow(current):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    nodes, finish = mock_nodes()
    nodes["interpret"] = slow
    graph = compile_graph(nodes, finish=finish)
    task = asyncio.create_task(run_graph(graph, state))
    await asyncio.wait_for(entered.wait(), 2)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert result["execution"]["error"]["code"] == "execution_limit_exceeded"
        assert result["execution"]["status"] in {"partial", "failed"}
        assert result["execution"]["budget"]["active_seconds"]["used"] > 0
    assert stopped.is_set()
