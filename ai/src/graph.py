"""업무 노드 연결, State 갱신 검사, 질문 저장·재개.

노드는 Command(update=부분 갱신, goto=다음 노드)를 반환한다.
finish는 최종 State에서 종료 상태·오류를 결정하는 실행 계층 함수다.
모델·도구·업무 판단은 호출자가 제공한다.
"""

from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ConfigDict, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.state import Error, State, StateUpdate, state_adapter

Node = Callable[[State], Command | Awaitable[Command]]


class Nodes(TypedDict):
    interpret: Node
    act: Node
    decide: Node
    compose: Node
    ask: Node


@with_config(ConfigDict(extra="forbid"))
class Completion(TypedDict):
    status: Literal["completed", "partial", "failed"]
    error: Error | None


# 허용 전이와 공개 응답 종류. 질문 대기는 실행 계층에서 처리한다.
DESTINATIONS = {
    "interpret": ("act", "decide"),
    "act": ("decide",),
    "decide": ("act", "compose", "ask"),
    "compose": ("act", "ask", END),
    "ask": ("wait",),
}
RESPONSE_KINDS = {
    "act": ("progress",),
    "decide": ("progress",),
    "ask": ("question",),
    "compose": ("intermediate", "final"),
}
update_adapter = TypeAdapter(StateUpdate)
completion_adapter = TypeAdapter(Completion)


def _wrap_node(name: str, fn: Node, finish: Callable[[State], Completion]):
    node = RunnableLambda(fn)

    def prepare(state: State):
        if state["execution"]["status"] == "queued":
            state = state_adapter.validate_python(state)
        return deepcopy(state)

    def apply(state: State, command: Command):
        if command.graph is not None or command.goto not in DESTINATIONS[name]:
            raise ValueError(f"Disallowed transition: {name}")
        update = update_adapter.validate_python(command.update)
        allowed = (
            {"results", "request"} if name == "interpret" else {"results", "response"}
        )
        if update.keys() - allowed:
            raise ValueError(f"Disallowed State update: {name}")
        records = update.get("results", [])
        if any(record["node"] != name for record in records):
            raise ValueError("A node may only append its own records")
        update["results"] = [*state["results"], *records]
        response = update.get("response")
        if name in {"ask", "compose"} and not response:
            raise ValueError(f"Response is required: {name}")
        status = "running"
        if response:
            kind = response["kind"]
            if kind not in RESPONSE_KINDS[name]:
                raise ValueError(f"Disallowed response kind: {name}")
            if (kind == "final") != (command.goto == END):
                raise ValueError("A final response must end the graph")
            if kind in {"progress", "question"}:
                artifacts = (state["response"] or {}).get("artifacts", [])
                if response["artifacts"] != artifacts:
                    raise ValueError("Progress and questions must preserve artifacts")
            if kind == "question":
                status = "waiting_input"
            update["messages"] = [AIMessage(response["content"], id=response["id"])]
        execution = state["execution"] | {"status": status}
        if command.goto == END:
            completion = completion_adapter.validate_python(
                finish(deepcopy(state | update))
            )
            execution.update(completion)
        update["execution"] = execution
        return Command(update=update, goto=command.goto)

    def run(state: State, config):
        return apply(state, node.invoke(prepare(state), config))

    async def arun(state: State, config):
        return apply(state, await node.ainvoke(prepare(state), config))

    return RunnableLambda(run, afunc=arun)


def _wait_for_input(state: State):
    """질문 노드의 갱신이 저장된 뒤 대기하고, 실제 답변만 대화에 추가한다."""
    if state["execution"]["status"] != "waiting_input":
        raise ValueError("Run is not waiting for input")
    answer = interrupt(state["response"])
    while not isinstance(answer, str) or not answer.strip():
        answer = interrupt(state["response"])
    return Command(
        update={
            "messages": [HumanMessage(answer, id=str(uuid4()))],
            "execution": state["execution"] | {"status": "running"},
        },
        goto="interpret",
    )


def compile_graph(
    nodes: Nodes,
    *,
    finish: Callable[[State], Completion],
    analysis_event: bool = False,
    checkpointer=None,
):
    """노드와 종료 판단을 연결한다. 질문 재개에는 checkpointer가 필요하다."""
    if nodes.keys() != DESTINATIONS.keys():
        raise ValueError(f"Provide exactly these nodes: {tuple(DESTINATIONS)}")
    graph = StateGraph(State)
    for name, fn in nodes.items():
        graph.add_node(
            name, _wrap_node(name, fn, finish), destinations=DESTINATIONS[name]
        )
    graph.add_node("wait", _wait_for_input, destinations=("interpret",))
    graph.add_edge(START, "act" if analysis_event else "interpret")
    return graph.compile(checkpointer=checkpointer)
