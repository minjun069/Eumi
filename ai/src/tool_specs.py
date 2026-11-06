"""기존 도구의 명세를 모델이 선택하는 입력 형태로 구성한다."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Annotated

from langchain_core.tools import BaseTool
from pydantic import ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.prompting import Role
from src.visualization_instructions import load_visualization_instructions


@with_config(ConfigDict(extra="forbid"))
class AgentTask(TypedDict):
    goal: Annotated[str, Field(description="구체적 대상·요구·완료조건")]


def selection_tools(tools: Mapping[str, BaseTool], role: Role) -> list[dict]:
    """실행 도구·State를 보관하지 않고 이번 선택 호출의 명세만 반환한다."""
    names = ["query_data", "process_data"]
    if role in {"request", "visualization"}:
        names.append("validate_visualization")
    definitions = []
    for name in names:
        tool = tools[name]
        parameters = deepcopy(tool.args_schema)
        description = tool.description
        if name == "process_data":
            # 실행 인자의 data는 노드가 검증된 State 결과에서 찾는다.
            # 모델에는 이미 사용하던 input_result_id 계약을 그대로 제공한다.
            del parameters["properties"]["data"]
            parameters["properties"]["input_result_id"] = {
                "type": "string",
                "description": "현재 results에 있는 검증된 data 호출의 id",
            }
            parameters["required"] = [
                "input_result_id" if key == "data" else key
                for key in parameters["required"]
            ]
            description += (
                " 자료 전체를 재작성하지 말고 input_result_id를 사용한다. "
                "calculate의 before는 분모열, after는 분자열이다. "
                "percentage=after/before*100, "
                "percent_change=(after-before)/before*100."
            )
        elif name == "validate_visualization":
            description += "\n\n" + load_visualization_instructions()["tool"]
        definitions.append((name, description, parameters))
    if role == "request":
        for name in ("interpretation_agent", "visualization_agent"):
            definitions.append(
                (
                    name,
                    "전문 Agent가 목표에 필요한 자료 조회·계산·표현·검증을 수행한다. "
                    "request 역할만 호출할 수 있다.",
                    TypeAdapter(AgentTask).json_schema(),
                )
            )
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
                "strict": False,
            },
        }
        for name, description, parameters in definitions
    ]
