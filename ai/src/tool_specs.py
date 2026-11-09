"""기존 도구의 명세를 모델이 선택하는 입력 형태로 구성한다."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Annotated

from langchain_core.tools import BaseTool
from pydantic import ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.execution import accepted_outputs
from src.prompting import Role
from src.state import State
from src.visualization_instructions import load_visualization_instructions


@with_config(ConfigDict(extra="forbid"))
class AgentTask(TypedDict):
    goal: Annotated[str, Field(description="구체적 대상·요구·완료조건")]


def selection_tools(
    tools: Mapping[str, BaseTool], role: Role, *, state: State
) -> list[dict]:
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
                "description": "가공할 자료가 들어 있는 results 항목의 id. "
                "output.data.reference.id나 조회 대상 target이 아니다.",
            }
            available = [
                key
                for key, output in accepted_outputs(state).items()
                if "data" in output
            ]
            if available:
                parameters["properties"]["input_result_id"]["enum"] = available
            else:
                parameters["properties"]["input_result_id"]["description"] += (
                    " 현재 사용 가능한 자료가 없으므로 먼저 query_data로 조회한다."
                )
            parameters["required"] = [
                "input_result_id" if key == "data" else key
                for key in parameters["required"]
            ]
            join = parameters["$defs"]["Join"]
            del join["properties"]["right"]
            join["properties"]["right_result_id"] = deepcopy(
                parameters["properties"]["input_result_id"]
            )
            join["required"] = [
                "right_result_id" if key == "right" else key for key in join["required"]
            ]
            # 선택 인자에는 자료 본문이 없으므로 사용하지 않는 자료 정의도 제외한다.
            for definition in ("Dataset", "Column", "Source", "DataReference"):
                del parameters["$defs"][definition]
            description += (
                " 자료 전체를 재작성하지 말고 input_result_id를 사용한다. "
                "calculate의 before는 분모열, after는 분자열이다. "
                "percentage=after/before*100, "
                "percent_change=(after-before)/before*100."
                " operations는 직전 연산 결과를 순서대로 처리한다. "
                "aggregate 후에는 group_by 열과 output 열만 남는다. "
                "원본 열로 별도 집계할 때는 같은 원본 input_result_id로 따로 호출한다. "
                "fields는 모든 연산이 끝난 뒤 남아 있는 열만 지정한다. "
                "join.fields는 {오른쪽 원본 열: 새 결과 열} 방향이다. "
                "join.right_result_id도 가공 가능한 State 결과 ID를 사용한다. "
                "right 자료를 직접 작성하지 않는다. 오른쪽 자료의 필터·가공이 필요하면 "
                "먼저 별도로 처리하고 그 호출 결과 ID를 지정한다. "
                "최대-최소는 범위이며 시작월-종료월 변화와 같지 않다."
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
