"""
State 계약
자료형과 초기 상태만 제공하며 실행·재개·쓰기 제어는 수행하지 않는다.
세부사항은 docs/ieumi-agent-state.md를 따른다.
"""

from copy import deepcopy
from typing import Annotated, Literal, NotRequired
from uuid import uuid4

from langchain_core.messages import AnyMessage
from langgraph.graph import MessagesState
from pydantic import ConfigDict, Field, JsonValue, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.settings import Settings



# Request - Constraints
@with_config(ConfigDict(extra="forbid"))
class Constraints(TypedDict):
    required: NotRequired[Annotated[list[str], Field(default_factory=list)]]
    preferred: NotRequired[Annotated[list[str], Field(default_factory=list)]]
    excluded: NotRequired[Annotated[list[str], Field(default_factory=list)]]

# Request
@with_config(ConfigDict(extra="forbid"))
class Request(TypedDict):
    goal: Annotated[str, Field(min_length=1, pattern=r"\S")]
    constraints: NotRequired[
        Annotated[Constraints, Field(default_factory=dict, validate_default=True)]
    ]



# result - ResultItem - Action
@with_config(ConfigDict(extra="forbid"))
class Action(TypedDict):
    name: Annotated[str, Field(min_length=1, pattern=r"\S")]
    arguments: dict[str, JsonValue]

# result - ResultItem
@with_config(ConfigDict(extra="forbid"))
class ResultItem(TypedDict):
    id: Annotated[str, Field(min_length=1)]
    node: Annotated[str, Field(min_length=1, pattern=r"\S")]
    decision: Annotated[str, Field(min_length=1, pattern=r"\S")]
    reason: str
    action: Action | None
    output: dict[str, JsonValue] | None
    description: str
    outcome: Literal["success", "failure"]



# Response - Artifact
@with_config(ConfigDict(extra="forbid"))
class Artifact(TypedDict):
    type: Annotated[str, Field(min_length=1, pattern=r"\S")]
    data: dict[str, JsonValue]

# Response
@with_config(ConfigDict(extra="forbid"))
class Response(TypedDict):
    id: Annotated[str, Field(min_length=1)]
    kind: Literal["progress", "intermediate", "final", "question"]
    label: str
    content: str
    artifacts: list[Artifact]



# Execution - Budget - Usage
@with_config(ConfigDict(extra="forbid"))
class Usage(TypedDict):
    used: int | float
    limit: int | float

# Execution - Budget
@with_config(ConfigDict(extra="forbid"))
class Budget(TypedDict):
    steps: Usage
    tool_calls: Usage
    agent_calls: Usage
    retries: Usage
    active_seconds: Usage

# Execution - Error
@with_config(ConfigDict(extra="forbid"))
class Error(TypedDict):
    code: str
    cause: str

# Execution
@with_config(ConfigDict(extra="forbid"))
class Execution(TypedDict):
    run_id: str
    status: Literal[
        "queued",
        "running",
        "waiting_input",
        "completed",
        "partial",
        "failed",
        "cancelled",
    ]
    version: Annotated[str, Field(min_length=1, pattern=r"\S")]
    budget: Budget
    error: Error | None

# State
@with_config(ConfigDict(extra="forbid"))
class State(MessagesState):
    request: Request
    # messages: 시스템 지침·실제 대화. MessagesState의 타입·병합을 상속한다.
    results: list[ResultItem]
    response: Response | None
    execution: Execution


@with_config(ConfigDict(extra="forbid"))
class StateUpdate(TypedDict, total=False):
    """실행 계층을 포함한 부분 갱신. 노드 쓰기 권한을 강제하는 타입은 아니다."""

    request: Request
    messages: list[AnyMessage]
    results: list[ResultItem]
    response: Response | None
    execution: Execution


request_adapter = TypeAdapter(Request)
result_item_adapter = TypeAdapter(ResultItem)
response_adapter = TypeAdapter(Response)
state_adapter = TypeAdapter(State)


def create_state(
    request: Request,
    settings: Settings,
    *,
    messages: list[AnyMessage],
    version: str,
) -> State:
    """호출자가 구성한 메시지와 배포 버전으로 새 실행을 초기화한다.

    이벤트 실행의 시스템 지침도 호출자가 messages에 제공한다.
    goal을 사용자 발화로 복제하지 않으며 저장된 실행 재개에는 사용하지 않는다.
    """
    limits = {
        "steps": settings.max_steps,
        "tool_calls": settings.max_tool_calls,
        "agent_calls": settings.max_agent_calls,
        "retries": settings.max_tool_retries,
        "active_seconds": settings.runtime_timeout,
    }
    return state_adapter.validate_python(
        {
            "request": deepcopy(request),
            "messages": deepcopy(messages),
            "results": [],
            "response": None,
            "execution": {
                "run_id": str(uuid4()),
                "status": "queued",
                "version": version,
                "budget": {
                    key: {"used": 0, "limit": limit} for key, limit in limits.items()
                },
                "error": None,
            },
        }
    )
