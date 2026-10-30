"""One execution-wide state, including each agent call's request and history."""

from copy import deepcopy
from typing import Annotated, Literal, NotRequired
from uuid import uuid4

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph import MessagesState
from pydantic import ConfigDict, Field, JsonValue, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.exceptions import LimitReached
from src.settings import Settings


@with_config(ConfigDict(extra="forbid"))
class Constraints(TypedDict):
    required: NotRequired[Annotated[list[str], Field(default_factory=list)]]
    preferred: NotRequired[Annotated[list[str], Field(default_factory=list)]]
    excluded: NotRequired[Annotated[list[str], Field(default_factory=list)]]


@with_config(ConfigDict(extra="forbid"))
class Request(TypedDict):
    goal: Annotated[str, Field(min_length=1, pattern=r"\S")]
    subject: NotRequired[Annotated[dict[str, JsonValue], Field(default_factory=dict)]]
    constraints: NotRequired[
        Annotated[Constraints, Field(default_factory=dict, validate_default=True)]
    ]


@with_config(ConfigDict(extra="forbid"))
class Reference(TypedDict):
    label: Annotated[str, Field(min_length=1)]
    uri: Annotated[str, Field(min_length=1)]


@with_config(ConfigDict(extra="forbid"))
class Artifact(TypedDict):
    type: Literal["analysis_interpretation", "visualization"]
    data: dict[str, JsonValue]
    sources: NotRequired[Annotated[list[Reference], Field(default_factory=list)]]
    issues: NotRequired[Annotated[list[str], Field(default_factory=list)]]


@with_config(ConfigDict(extra="forbid"))
class Result(TypedDict):
    content: Annotated[str, Field(min_length=1, pattern=r"\S")]
    results: NotRequired[Annotated[list[Artifact], Field(default_factory=list)]]
    references: NotRequired[Annotated[list[Reference], Field(default_factory=list)]]
    partial: NotRequired[Annotated[bool, Field(default=False)]]


@with_config(ConfigDict(extra="forbid"))
class Call(TypedDict):
    agent_path: list[str]
    parent: str | None
    tool_call_id: str | None
    request: Request
    messages: list[AnyMessage]
    results: list[Artifact]
    candidate: Result | None
    result: Result | None
    error: dict[str, JsonValue] | None
    retry_tool: bool


@with_config(ConfigDict(extra="forbid"))
class Initial(TypedDict):
    request: Request
    info: dict[str, JsonValue]
    messages: list[AnyMessage]
    results: list[Artifact]
    candidate: Result | None
    result: Result | None


@with_config(ConfigDict(extra="forbid"))
class State(MessagesState):
    request: Request
    info: dict[str, JsonValue]
    results: list[Artifact]
    result: Result | None
    calls: dict[str, Call]
    active_call: str
    settings: dict[str, JsonValue]
    run_id: str
    agent: str
    data_versions: dict[str, str]
    input_version: int
    usage: dict[str, int | float]
    initial: Initial
    instruction_version: str
    public_messages: list[dict[str, str]]
    status: str
    error: dict[str, JsonValue] | None
    pending: dict[str, str] | None
    cancel_requested: bool


request_adapter = TypeAdapter(Request)
artifact_adapter = TypeAdapter(Artifact)
result_adapter = TypeAdapter(Result)
state_adapter = TypeAdapter(State)


def merge_results(*groups: list[Artifact]) -> list[Artifact]:
    merged = []
    for group in groups:
        for item in group:
            if item not in merged:
                merged.append(deepcopy(item))
    return merged


def new_call(request: Request, path: list[str], parent=None, tool_call_id=None) -> Call:
    return {
        "agent_path": path,
        "parent": parent,
        "tool_call_id": tool_call_id,
        "request": request,
        "messages": [HumanMessage(request["goal"], id=str(uuid4()))],
        "results": [],
        "candidate": None,
        "result": None,
        "error": None,
        "retry_tool": False,
    }


def create_state(
    request,
    settings: Settings,
    *,
    agent="test",
    instruction_version="test",
    info=None,
    data_versions=None,
) -> State:
    request = request_adapter.validate_python(request)
    call = new_call(request, [])
    initial = {
        "request": request,
        "info": info if info is not None else {},
        "messages": call["messages"],
        "results": [],
        "candidate": None,
        "result": None,
    }
    return state_adapter.validate_python(
        {
            "request": request,
            "info": initial["info"],
            "messages": call["messages"],
            "results": [],
            "result": None,
            "calls": {"root": call},
            "active_call": "root",
            "settings": settings.model_dump(mode="json", exclude={"api_key"}),
            "run_id": str(uuid4()),
            "agent": agent,
            "data_versions": data_versions if data_versions is not None else {},
            "input_version": 1,
            "usage": {
                "steps": 0,
                "tool_calls": 0,
                "agent_calls": 0,
                "retries": 0,
                "active_seconds": 0.0,
            },
            "initial": deepcopy(initial),
            "instruction_version": instruction_version,
            "public_messages": [{"role": "user", "content": request["goal"]}],
            "status": "queued",
            "error": None,
            "pending": None,
            "cancel_requested": False,
        }
    )


def consume(state: State, kind: str) -> None:
    limit = "max_tool_retries" if kind == "retries" else f"max_{kind}"
    if state["usage"][kind] >= state["settings"][limit]:
        raise LimitReached(kind)
    state["usage"][kind] += 1


def current_call(state: State) -> Call:
    return state["calls"][state["active_call"]]


def update_call(state: State, *, messages=(), **changes) -> dict:
    messages = [
        m if m.id else m.model_copy(update={"id": str(uuid4())}) for m in messages
    ]
    call = current_call(state) | changes
    call["messages"] = [*call["messages"], *messages]
    return {
        "calls": state["calls"] | {state["active_call"]: call},
        "messages": messages,
    }
