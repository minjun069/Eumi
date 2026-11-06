"""Agent의 업무 판단과 수행을 담당하는 노드를 정의한다."""

import json
from copy import deepcopy
from typing import Annotated, Literal
from uuid import uuid4

from langgraph.graph import END
from langgraph.types import Command
from pydantic import ConfigDict, Field, ValidationError, with_config
from typing_extensions import TypedDict

from src.exceptions import LimitReached, ToolFailure
from src.execution import (
    finalizing,
    invoke_local_tool,
    invoke_model,
    invoke_work,
    record,
)
from src.execution_trace import trace_span
from src.gemini import structured_call
from src.graph import compile_graph
from src.prompting import (
    Role,
    ask_messages,
    compose_messages,
    decide_messages,
    interpret_messages,
    selection_messages,
    verification_messages,
)
from src.prompting import compact as compact
from src.runtime import run_graph
from src.state import Request, create_child_state
from src.tool_specs import selection_tools
from src.tools.interface import create_tools
from src.tools.render import render_visualization
from src.tools.tableau_catalog import registered_catalog


@with_config(ConfigDict(extra="forbid"))
class Interpretation(TypedDict):
    request: Request
    reason: str
    needs_input: bool


@with_config(ConfigDict(extra="forbid"))
class Selection(TypedDict):
    name: Literal[
        "query_data",
        "process_data",
        "validate_visualization",
        "interpretation_agent",
        "visualization_agent",
        "none",
    ]
    arguments_json: Annotated[
        str,
        Field(
            description="선택한 도구 명세에 맞는 인자 객체를 JSON 문자열로 직렬화한다. none이면 {}."
        ),
    ]
    reason: str


@with_config(ConfigDict(extra="forbid"))
class Verification(TypedDict):
    accepted: bool
    reason: str


@with_config(ConfigDict(extra="forbid"))
class Decision(TypedDict):
    next: Literal["act", "compose", "ask"]
    reason: str


@with_config(ConfigDict(extra="forbid"))
class Composition(TypedDict):
    content: str
    artifact_ids: list[str]
    status: Literal["completed", "partial", "failed"]
    reason: str


@with_config(ConfigDict(extra="forbid"))
class Question(TypedDict):
    content: str
    reason: str


def response(state, kind, content, artifacts=None):
    return {
        "id": str(uuid4()),
        "kind": kind,
        "label": kind,
        "content": content,
        "artifacts": deepcopy(
            artifacts
            if artifacts is not None
            else (state["response"] or {}).get("artifacts", [])
        ),
    }


def accepted_outputs(state):
    accepted = {
        r["output"]["call_id"]
        for r in state["results"]
        if r["decision"] == "verification" and r["output"]["accepted"]
    }
    outputs = {
        r["id"]: r["output"]
        for r in state["results"]
        if r["id"] in accepted
        and r["outcome"] == "success"
        and (r["output"] or {}).get("valid") is not False
    }
    # 상위 호출 검증과 하위 호출 검증을 모두 통과한 결과만 참조할 수 있다.
    for output in list(outputs.values()):
        if "results" in output:
            outputs.update(accepted_outputs(output))
    return outputs


def select_artifacts(state):
    ids = next(
        item["output"]["artifact_ids"]
        for item in reversed(state["results"])
        if item["decision"] == "composition"
    )
    available = accepted_outputs(state)
    artifacts = deepcopy((state["response"] or {}).get("artifacts", [])) if finalizing(state) else []
    for selected in ids:
        if selected == "previous":
            items = (state["response"] or {}).get("artifacts", [])
        else:
            if selected not in available:
                raise ToolFailure("unverified_artifact")
            output = available[selected]
            if "response" in output:
                items = output["response"]["artifacts"]
            elif "artifact" in output:
                if output["artifact"] is None or output.get("valid") is False:
                    raise ToolFailure("unverified_artifact")
                items = [output["artifact"]]
                if "data" in output:
                    items.append(
                        {
                            "type": "data",
                            "data": {
                                "dataset": output["data"],
                                "spec": output["applied"],
                                "warnings": output["warnings"],
                            },
                        }
                    )
            elif "data" in output:
                table_input = {
                    "data": output["data"],
                    "spec": {
                        "type": "table",
                        "title": "비교 근거·사용 데이터",
                    },
                }
                items = [{"type": "data", "data": {"dataset": output["data"]}}]
                if not finalizing(state):
                    with trace_span(
                        "artifact", "render_comparison_table", table_input
                    ) as span:
                        table = invoke_local_tool(
                            state,
                            "compose",
                            "render_visualization",
                            table_input,
                            lambda table_input=table_input: render_visualization(
                                table_input
                            ),
                        )
                        if span:
                            span.update(output=table)
                    items[0]["data"]["spec"] = table["applied"]
                    items.insert(0, table["artifact"])
            else:
                raise ToolFailure("artifact_not_found")
        for item in items:
            if (
                item["type"] == "tableau"
                and item["data"].get("view_key") not in registered_catalog()["views"]
            ):
                raise ToolFailure("unknown_view")
            if item not in artifacts:
                artifacts.append(deepcopy(item))
    return artifacts


def finish(state):
    last = next(r for r in reversed(state["results"]) if r["decision"] == "composition")
    status = last["output"]["status"]
    return {
        "status": status,
        "error": None
        if status == "completed"
        else {
            "code": "incomplete",
            "cause": last["reason"],
        },
    }


def build_nodes(
    model,
    providers,
    catalog,
    *,
    role: Role,
):
    async def call(state, schema, messages, config, *, tools=None):
        return await invoke_model(
            state,
            lambda: structured_call(model, schema, messages(), config, tools=tools),
        )

    async def interpret(state, config):
        value, usage = await call(
            state,
            Interpretation,
            lambda: interpret_messages(state, role),
            config,
        )
        return Command(
            update={
                "request": value["request"],
                "results": [
                    record(
                        "interpret",
                        "interpretation",
                        value["reason"],
                        output=value | {"model_usage": usage},
                    )
                ],
            },
            goto="decide" if value["needs_input"] else "act",
        )

    async def act(state, config):
        tools = {t.name: t for t in create_tools(providers, state=state)}
        # 노드 내부 판단도 같은 State 이력을 읽고, 반환할 때 새 기록만 전달한다.
        first_record = len(state["results"])
        choice, usage = await call(
            state,
            Selection,
            lambda: selection_messages(state, role, catalog),
            config,
            tools=selection_tools(tools, role),
        )
        records = state["results"]
        records.append(
            record(
                "act",
                "selection",
                choice["reason"],
                output=choice | {"model_usage": usage},
            )
        )
        name = choice["name"]
        if name == "none":
            return Command(update={"results": records[first_record:]}, goto="decide")
        arguments = {}
        try:
            arguments = json.loads(choice["arguments_json"])
            if not isinstance(arguments, dict):
                arguments = {}
                raise ToolFailure("invalid_input")

            async def execute():
                # invoke_work가 호출 수를 소비한 뒤 이 State에서 하위 실행을 만든다.
                if name.endswith("_agent"):
                    if role != "request" or set(arguments) != {"goal"}:
                        raise ToolFailure("invalid_agent_call")
                    child_role = name.removesuffix("_agent")
                    child = create_child_state(
                        {
                            "goal": arguments["goal"],
                            "constraints": state["request"]["constraints"],
                        },
                        state,
                    )
                    graph = compile_graph(
                        build_nodes(model, providers, catalog, role=child_role),
                        finish=finish,
                    )
                    with trace_span(
                        "agent",
                        name,
                        {
                            "initial_state": child,
                            "catalog": catalog,
                            "role": child_role,
                        },
                    ) as span:
                        result = await run_graph(graph, child, config)
                        if span:
                            span.update(output=result)
                    return {k: result[k] for k in ("response", "results", "execution")}
                if role == "interpretation" and name == "validate_visualization":
                    raise ToolFailure("tool_not_allowed")
                actual = deepcopy(arguments)
                if name == "process_data":
                    source_id = actual.pop("input_result_id", None)
                    source = accepted_outputs(state).get(source_id, {})
                    if "data" not in source or "data" in actual:
                        raise ToolFailure("invalid_data_reference")
                    actual["data"] = source["data"]
                with trace_span(
                    "tool",
                    name,
                    {
                        "selected_arguments": arguments,
                        "resolved_arguments": actual,
                        "input_schema": tools[name].args_schema,
                    },
                ) as span:
                    output = await tools[name].ainvoke(actual, config)
                    if span:
                        span.update(output=output)
                return output

            invoked = await invoke_work(
                state, "act", name, arguments, choice["reason"], execute
            )
            output = invoked["output"]
            if name.endswith("_agent"):
                if finalizing(output):
                    limit_record = next(
                        r
                        for r in reversed(output["results"])
                        if r["decision"] == "limit_reached"
                    )["output"]
                    raise LimitReached(
                        limit_record["resource"],
                        used=limit_record["used"],
                        limit=limit_record["limit"],
                    )
            if name == "validate_visualization" and not output["valid"]:
                records.append(
                    record(
                        "act",
                        "verification",
                        "등록된 시각화 조건에 부적합",
                        output={
                            "accepted": False,
                            "call_id": invoked["id"],
                            "issues": output["issues"],
                        },
                    )
                )
                return Command(
                    update={"results": records[first_record:]}, goto="decide"
                )
            verification, usage = await call(
                state,
                Verification,
                lambda: verification_messages(state, role),
                config,
            )
            records.append(
                record(
                    "act",
                    "verification",
                    verification["reason"],
                    output=verification
                    | {"call_id": invoked["id"], "model_usage": usage},
                    success=True,
                )
            )
        except (ToolFailure, ValidationError, json.JSONDecodeError) as exc:
            if any(
                r["decision"] == "call" and r["outcome"] == "failure"
                for r in records[first_record:]
            ):
                return Command(
                    update={"results": records[first_record:]}, goto="decide"
                )
            records.append(
                record(
                    "act",
                    "call_failed",
                    "호출 입력·결과 검증 실패",
                    action={"name": name, "arguments": arguments},
                    success=False,
                    output={
                        "code": getattr(exc, "code", "invalid_input"),
                        "details": getattr(exc, "details", {}),
                        "retryable": getattr(exc, "retryable", False),
                    },
                )
            )
        return Command(update={"results": records[first_record:]}, goto="decide")

    async def decide(state, config):
        value, usage = await call(
            state, Decision, lambda: decide_messages(state, role), config
        )
        target = value["next"]
        if role != "request" and target == "ask":
            target = "compose"
        return Command(
            update={
                "results": [
                    record(
                        "decide",
                        "decision",
                        value["reason"],
                        output=value | {"model_usage": usage},
                    )
                ]
            },
            goto=target,
        )

    async def compose(state, config):
        first_record = len(state["results"])
        value, usage = await call(
            state,
            Composition,
            lambda: compose_messages(state, role),
            config,
        )
        state["results"].append(
            record(
                "compose",
                "composition",
                value["reason"],
                output=value | {"model_usage": usage},
            )
        )
        with trace_span(
            "artifact",
            "select_artifacts",
            {
                "selected_ids": value["artifact_ids"],
                "available_results": accepted_outputs(state),
                "previous_response": state["response"],
            },
        ) as span:
            artifacts = select_artifacts(state)
            if span:
                span.update(output=artifacts)
        return Command(
            update={
                "results": state["results"][first_record:],
                "response": response(state, "final", value["content"], artifacts),
            },
            goto=END,
        )

    async def ask(state, config):
        value, usage = await call(
            state, Question, lambda: ask_messages(state, role), config
        )
        return Command(
            update={
                "results": [
                    record(
                        "ask",
                        "question",
                        value["reason"],
                        output=value | {"model_usage": usage},
                    )
                ],
                "response": response(state, "question", value["content"]),
            },
            goto="wait",
        )

    return {
        "interpret": interpret,
        "act": act,
        "decide": decide,
        "compose": compose,
        "ask": ask,
    }
