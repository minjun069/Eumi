"""Agent 실행을 시작하고 사용자 답변에 따라 저장된 실행을 재개한다."""

from langgraph.types import Command

from src.state import State, state_adapter


def execution_config(run_id: str, config=None):
    # 호출자가 전달하는 것은 관측 설정뿐이다. 실행 식별자는 State에서 온다.
    tracing = {
        key: value for key, value in (config or {}).items()
        if key in {"callbacks", "tags", "metadata", "run_name"}
    }
    return tracing | {
        "configurable": {"thread_id": run_id, "checkpoint_ns": ""},
    }


def _state(value):
    return state_adapter.validate_python({k: v for k, v in value.items() if k != "__interrupt__"})


async def run_graph(graph, state: State, config=None) -> State:
    state = state_adapter.validate_python(state)
    if state["execution"]["status"] != "queued":
        raise ValueError("Start requires a queued State; resume a saved question separately")
    return _state(await graph.ainvoke(
        state, execution_config(state["execution"]["run_id"], config)
    ))


async def resume_graph(graph, run_id: str, question_id: str, answer: str, config=None) -> State:
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("A non-empty answer is required")
    config = execution_config(run_id, config)
    saved = await graph.aget_state(config)
    state = _state(saved.values)
    response = state["response"]
    if (
        state["execution"]["run_id"] != run_id
        or state["execution"]["status"] != "waiting_input"
        or not saved.interrupts
        or not response
        or response["kind"] != "question"
        or response["id"] != question_id
    ):
        raise ValueError("Run is not waiting for this question")
    return _state(await graph.ainvoke(Command(resume=answer), config))
