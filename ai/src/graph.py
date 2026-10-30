"""Sequential agent calls in one LangGraph state and checkpoint namespace."""

import json
from copy import deepcopy
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool, tool
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, ToolRuntime
from langgraph.types import Command, interrupt

from src.exceptions import LimitReached, ToolFailure
from src.state import (
    Artifact,
    Reference,
    Result,
    State,
    consume,
    current_call,
    merge_results,
    new_call,
    request_adapter,
    result_adapter,
    update_call,
)


@dataclass
class Agent:
    """Static components only; changing execution data belongs to State."""

    name: str
    model: object
    prompt: str
    tools: list
    validate: object
    children: dict = field(default_factory=dict)


@tool
def submit_result(
    content: str,
    results: list[Artifact],
    references: list[Reference],
    runtime: ToolRuntime,
    partial: bool = False,
) -> Command:
    """Submit a grounded result for verification; this does not mean completion."""
    result = result_adapter.validate_python(
        Result(content=content, results=results, references=references, partial=partial)
    )
    update = update_call(runtime.state, candidate=result)
    update["messages"] = [
        ToolMessage(
            "Result submitted for verification.", tool_call_id=runtime.tool_call_id
        )
    ]
    return Command(update=update)


@tool
def ask_user(question: str, runtime: ToolRuntime) -> str:
    """Ask for missing essential information and wait for the user's answer."""
    if not question.strip():
        raise ValueError("A non-empty question is required")
    return interrupt({"id": runtime.tool_call_id, "question": question})


async def call_tool(request, execute):
    """ToolNode handles dispatch; a retry is scheduled through the graph."""
    try:
        return await execute(request)
    except (GraphBubbleUp, LimitReached):
        raise
    except ToolFailure as exc:
        safe = bool(request.tool and (request.tool.metadata or {}).get("retry_safe"))
        return ToolMessage(
            str(exc),
            tool_call_id=request.tool_call["id"],
            status="error",
            additional_kwargs={"retry_tool": safe and exc.retryable},
        )
    except Exception as exc:
        return ToolMessage(
            f"{type(exc).__name__}: tool input or execution failed",
            tool_call_id=request.tool_call["id"],
            status="error",
        )


def return_to_parent(state, *, result=None, error=None):
    call = current_call(state)
    calls = state["calls"] | {
        state["active_call"]: call
        | {"candidate": None, "result": result, "error": error}
    }
    if call["parent"] is None:
        return {"calls": calls, "result": result, "error": error}
    parent_state = state | {"calls": calls, "active_call": call["parent"]}
    parent = current_call(parent_state)
    message = ToolMessage(
        error["cause"] if error else json.dumps(result, ensure_ascii=False),
        tool_call_id=call["tool_call_id"],
        status="error" if error else "success",
    )
    update = update_call(
        parent_state,
        messages=[message],
        results=merge_results(parent["results"], result["results"] if result else []),
    )
    return update | {"active_call": call["parent"]}


def compile_graph(root: Agent, *, checkpointer=None):
    agents, models, tools = {}, {}, {}

    def register(agent, path):
        delegates = [
            StructuredTool.from_function(
                func=lambda **kwargs: None,
                name=name,
                description=f"Delegate a task to {name}.",
                args_schema=request_adapter.json_schema(),
            )
            for name in agent.children
        ]
        exposed = [*agent.tools, *delegates, ask_user, submit_result]
        if len({item.name for item in exposed}) != len(exposed):
            raise ValueError("Tool and child names must be unique")
        agents[path] = agent
        models[path] = agent.model.bind_tools(exposed, parallel_tool_calls=False)
        tools[path] = ToolNode(
            [*agent.tools, ask_user, submit_result],
            handle_tool_errors=False,
            awrap_tool_call=call_tool,
        )
        for name, child in agent.children.items():
            register(child, (*path, name))

    register(root, ())

    def guard(fn):
        async def invoke(state: State, config):
            work = state | {"usage": state["usage"].copy()}
            try:
                update = await fn(work, config)
            except GraphBubbleUp:
                raise
            except LimitReached as exc:
                update = {
                    "error": {
                        "code": f"{exc}_limit",
                        "cause": f"Execution limit reached: {exc}.",
                        "retryable": False,
                    }
                }
            except Exception as exc:
                update = return_to_parent(
                    work,
                    error={
                        "code": "runtime_error",
                        "retryable": False,
                        "cause": f"Execution failed ({type(exc).__name__}).",
                    },
                )
            return {"usage": work["usage"]} | update

        return invoke

    async def reserve_model(state, config):
        consume(state, "steps")
        return {}

    async def call_model(state, config):
        call = current_call(state)
        path = tuple(call["agent_path"])
        context = json.dumps(
            {
                "request": call["request"],
                "info": state["info"],
                "results": merge_results(state["results"], call["results"]),
                "data_versions": state["data_versions"],
            },
            ensure_ascii=False,
        )
        message = await models[path].ainvoke(
            [
                SystemMessage(
                    agents[path].prompt
                    + "\nUse one tool per turn. Use submit_result to finish.\n"
                    + context
                ),
                *call["messages"],
            ]
        )
        if not isinstance(message, AIMessage):
            raise TypeError("Model must return AIMessage")
        calls = message.tool_calls
        if len(calls) != 1:
            replies = [
                ToolMessage(
                    "Use exactly one tool per turn.",
                    tool_call_id=c["id"],
                    status="error",
                )
                for c in calls
            ]
            return update_call(
                state,
                messages=[
                    message,
                    *replies,
                    SystemMessage("Use one tool, or submit_result to finish."),
                ],
            )
        if calls[0]["name"] in agents[path].children:
            try:
                request_adapter.validate_python(calls[0]["args"])
            except ValueError:
                return update_call(
                    state,
                    messages=[
                        message,
                        ToolMessage(
                            "Invalid child request.",
                            tool_call_id=calls[0]["id"],
                            status="error",
                        ),
                    ],
                )
            consume(state, "agent_calls")
        return update_call(state, messages=[message])

    async def delegate(state, config):
        parent = current_call(state)
        action = parent["messages"][-1].tool_calls[0]
        call_id = f"call-{len(state['calls'])}"
        child = new_call(
            request_adapter.validate_python(action["args"]),
            [*parent["agent_path"], action["name"]],
            state["active_call"],
            action["id"],
        )
        return {
            "calls": state["calls"] | {call_id: child},
            "active_call": call_id,
            "messages": child["messages"],
        }

    async def reserve_tool(state, config):
        call = current_call(state)
        action = next(
            m for m in reversed(call["messages"]) if isinstance(m, AIMessage)
        ).tool_calls[0]
        if action["name"] not in {"ask_user", "submit_result"}:
            if call["retry_tool"]:
                consume(state, "retries")
            consume(state, "tool_calls")
        return {}

    async def execute_tool(state, config):
        path = tuple(current_call(state)["agent_path"])
        output = await tools[path].ainvoke(state, config)
        parts = output if isinstance(output, list) else [output]
        changes, messages = {}, []
        for part in parts:
            update = part.update if isinstance(part, Command) else part
            messages.extend(update.get("messages", []))
            changes.update({k: v for k, v in update.items() if k != "messages"})
        if any(m.additional_kwargs.get("retry_tool") for m in messages):
            return update_call(state, retry_tool=True)
        updated = state | changes
        return changes | update_call(updated, messages=messages, retry_tool=False)

    async def verify(state, config):
        call = current_call(state)
        result = result_adapter.validate_python(
            call["candidate"]
            | {"results": merge_results(call["results"], call["candidate"]["results"])}
        )
        agent = agents[tuple(call["agent_path"])]
        feedback = await agent.validate(deepcopy(state), deepcopy(result))
        if not isinstance(feedback, list) or not all(
            isinstance(x, str) for x in feedback
        ):
            raise TypeError("Validator must return a list of problems")
        if feedback:
            return update_call(
                state,
                candidate=None,
                messages=[SystemMessage("Validation failed: " + "; ".join(feedback))],
            )
        update = return_to_parent(state, result=result)
        return update | {"results": merge_results(state["results"], result["results"])}

    def route_model(state):
        if state["error"]:
            return END
        call = current_call(state)
        message = call["messages"][-1]
        if not isinstance(message, AIMessage) or not message.tool_calls:
            return "reserve_model"
        children = agents[tuple(call["agent_path"])].children
        return (
            "delegate" if message.tool_calls[0]["name"] in children else "reserve_tool"
        )

    def route_tools(state):
        if state["error"]:
            return END
        call = current_call(state)
        if call["retry_tool"]:
            return "reserve_tool"
        return "verify" if call["candidate"] else "reserve_model"

    graph = StateGraph(State)
    for name, fn in {
        "reserve_model": reserve_model,
        "model": call_model,
        "delegate": delegate,
        "reserve_tool": reserve_tool,
        "tools": execute_tool,
        "verify": verify,
    }.items():
        graph.add_node(name, guard(fn))
    graph.add_edge(START, "reserve_model")
    graph.add_conditional_edges(
        "reserve_model", lambda s: END if s["error"] else "model", [END, "model"]
    )
    graph.add_conditional_edges(
        "model", route_model, [END, "delegate", "reserve_model", "reserve_tool"]
    )
    graph.add_conditional_edges(
        "delegate",
        lambda s: END if s["error"] else "reserve_model",
        [END, "reserve_model"],
    )
    graph.add_conditional_edges(
        "reserve_tool", lambda s: END if s["error"] else "tools", [END, "tools"]
    )
    graph.add_conditional_edges(
        "tools", route_tools, [END, "reserve_tool", "verify", "reserve_model"]
    )
    graph.add_conditional_edges(
        "verify",
        lambda s: END if s["error"] or s["result"] else "reserve_model",
        [END, "reserve_model"],
    )
    return graph.compile(checkpointer=checkpointer, name=root.name)
