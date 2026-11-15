"""업무 모델의 실제 입력과 원본 응답만 수집하는 독립 호출 경계."""

import asyncio

from typing_extensions import TypedDict

from eval.schema import Case
from src.agent_nodes import prepare_model_call
from src.execution_trace import trace_output, trace_span
from src.gemini import raw_call
from src.state import State
from src.tools.interface import create_tools


class ModelOutput(TypedDict):
    model_call: str
    raw: str


async def run_model_output(
    case: Case,
    state: State,
    model,
    providers,
    catalog,
    config,
    *,
    timeout_seconds: float,
) -> ModelOutput:
    """모델 결과를 업무 State에 적용하거나 후속 호출을 실행하지 않는다."""
    with trace_span(
        "node",
        case["target"],
        {
            "role": case["role"],
            "initial_state": state,
            "evaluation_scope": "model_output",
            "model_call": case.get("model_call"),
        },
    ):
        tools = (
            {tool.name: tool for tool in create_tools(providers, state=state)}
            if case["target"] == "act"
            else None
        )
        prepared = prepare_model_call(
            case["target"],
            state,
            role=case["role"],
            catalog=catalog,
            tools=tools,
            report_stage=case.get("model_call"),
        )
        async with asyncio.timeout(timeout_seconds):
            response, usage = await raw_call(
                model,
                prepared["schema"],
                prepared["messages"],
                config,
                strict=prepared["strict"],
            )
        output = ModelOutput(model_call=prepared["schema"].__name__, raw=response.text)
        trace_output({"output": output, "model_usage": usage})
        return output
