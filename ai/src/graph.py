"""Agent의 실행 흐름과 상태 전이를 관리한다."""

import asyncio

from collections.abc import Awaitable, Callable
from copy import deepcopy
from sys import maxsize
from typing import Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ConfigDict, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.exceptions import LimitReached
from src.execution import consume, exhausted, finalizing, record, remaining, require, timed
from src.execution_trace import trace_span
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


def _stop(state: State, *, cause: str, code: str):
    previous = state["response"] or {}
    content = cause
    if previous.get("content"):
        content = previous["content"] + "\n\n" + cause
    reply = {
        "id": str(uuid4()), "kind": "final", "label": "실행 종료",
        "content": content, "artifacts": deepcopy(previous.get("artifacts", [])),
    }
    useful = (
        bool(previous.get("artifacts"))
        or (previous.get("kind") in {"intermediate", "final"} and bool(previous.get("content")))
    ) or any(
        item["decision"] == "verification"
        and (item["output"] or {}).get("accepted") is True
        for item in state["results"]
    )
    execution = state["execution"] | {
        "status": "partial" if useful else "failed",
        "error": state["execution"]["error"] or {"code": code, "cause": cause},
    }
    return Command(update={
        "results": state["results"], "execution": execution, "response": reply,
        "messages": [AIMessage(content, id=reply["id"])],
    }, goto=END)


def _limited(state: State, name: str, exc: LimitReached):
    was_finalizing = finalizing(state)
    usage = state["execution"]["budget"][exc.resource]
    state["results"].append(record(
        name, "limit_reached", str(exc), success=False,
        output={"code": exc.code, "resource": exc.resource, **usage},
    ))
    state["execution"]["error"] = state["execution"]["error"] or {
        "code": exc.code, "cause": str(exc),
    }
    if (
        not was_finalizing
        and remaining(state, "final_model_calls") > 0
        and remaining(state, "final_active_seconds") > 0
    ):
        state["execution"]["status"] = "running"
        return Command(update={
            "results": state["results"], "execution": state["execution"],
        }, goto="compose")
    return _stop(
        state, code=exc.code,
        cause="실행 한도에 도달했습니다. 기존 공개 결과를 보존하며, "
        "검증을 마치지 못한 결과는 새 근거로 공개하지 않습니다.",
    )


def _wrap_node(name: str, fn: Node, finish: Callable[[State], Completion]):
    node = RunnableLambda(fn)

    def apply(original: State, state: State, command: Command):
        if command.graph is not None or command.goto not in DESTINATIONS[name]:
            raise ValueError(f"Disallowed transition: {name}")
        update = update_adapter.validate_python(command.update)
        allowed = {"results", "request"} if name == "interpret" else {"results", "response"}
        if update.keys() - allowed:
            raise ValueError(f"Disallowed State update: {name}")
        records = update.get("results", [])
        if any(item["node"] != name for item in records):
            raise ValueError("A node may only append its own records")
        update["results"] = [*original["results"], *records]
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
                artifacts = (original["response"] or {}).get("artifacts", [])
                if response["artifacts"] != artifacts:
                    raise ValueError("Progress and questions must preserve artifacts")
            if kind == "question":
                status = "waiting_input"
            update["messages"] = [AIMessage(response["content"], id=response["id"])]
        execution = state["execution"] | {"status": status}
        if command.goto == END:
            completion = completion_adapter.validate_python(finish(deepcopy(state | update)))
            if finalizing(state):
                completion = {
                    "status": "failed" if completion["status"] == "failed" else "partial",
                    "error": state["execution"]["error"],
                }
            execution.update(completion)
        elif finalizing(state):
            raise ValueError("The final response budget must end the graph")
        update["execution"] = execution
        return Command(update=update, goto=command.goto)

    async def arun(state: State, config):
        prepared = deepcopy(state_adapter.validate_python(state))
        with trace_span("node", name, {"state": prepared}) as span:
            command = None
            try:
                if finalizing(prepared):
                    if name != "compose":
                        raise exhausted(prepared, "steps")
                    require(prepared, "final_model_calls")
                    require(prepared, "final_active_seconds")
                else:
                    require(prepared, "active_seconds")
                    consume(prepared, "steps")
                command = await timed(
                    prepared, lambda: node.ainvoke(prepared, config),
                    contains_child=name == "act",
                )
                # 동기 처리까지 포함한 실측을 반영한 뒤 다음 업무로 진행한다.
                resource = "final_active_seconds" if finalizing(prepared) else "active_seconds"
                if remaining(prepared, resource) <= 0:
                    # 노드가 반환한 새 기록은 한도 종료에서도 보존한다.
                    pending = update_adapter.validate_python(command.update).get("results", [])
                    known = {item["id"] for item in prepared["results"]}
                    prepared["results"].extend(item for item in pending if item["id"] not in known)
                    raise exhausted(prepared, resource)
                result = apply(state, prepared, command)
            except LimitReached as exc:
                result = _limited(prepared, name, exc)
            except Exception as exc:
                prepared["results"].append(record(
                    name, "execution_failed", "노드 실행 실패", success=False,
                    output={"code": getattr(exc, "code", "runtime_error"),
                            "error_type": type(exc).__name__},
                ))
                result = _stop(
                    prepared, code=getattr(exc, "code", "runtime_error"),
                    cause="실행 오류로 요청을 완료하지 못했습니다. 기존 공개 결과를 보존합니다.",
                )
            if span:
                span.update(output={
                    "node_update": command.update if command is not None else None,
                    "applied_update": result.update, "goto": result.goto,
                })
            return result

    def run(state: State, config):
        return asyncio.run(arun(state, config))

    return RunnableLambda(run, afunc=arun)


def _wait_for_input(state: State):
    with trace_span("node", "wait", {"state": state}) as span:
        command = _receive_input(state)
        if span:
            span.update(output={"node_update": command.update, "goto": command.goto})
        return command


def _receive_input(state: State):
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
    checkpointer=None,
):
    """State의 시작 이벤트로 진입한다. 질문 재개에는 checkpointer가 필요하다."""
    if nodes.keys() != DESTINATIONS.keys():
        raise ValueError(f"Provide exactly these nodes: {tuple(DESTINATIONS)}")
    graph = StateGraph(State)
    for name, fn in nodes.items():
        graph.add_node(
            name, _wrap_node(name, fn, finish),
            destinations=tuple(dict.fromkeys((*DESTINATIONS[name], "compose", END)))
        )
    graph.add_node("wait", _wait_for_input, destinations=("interpret",))
    graph.add_conditional_edges(
        START,
        lambda state: (
            "act" if state["execution"]["event"] == "analysis_pipeline" else "interpret"
        ),
        ["act", "interpret"],
    )
    # LangGraph superstep 수는 업무 단계가 아니다. State의 steps를 유일한 실행 한도로 쓴다.
    return graph.compile(checkpointer=checkpointer).with_config(recursion_limit=maxsize)
