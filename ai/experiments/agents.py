"""The same graph is used by all three temporary agents."""

import json

from langchain_core.messages import AIMessage, ToolMessage

from experiments import prompts
from experiments.tools import SOURCE, calculate_change, lookup_metrics, render_table
from src.graph import Agent
from src.state import current_call


def observations(messages):
    names = {
        call["id"]: call["name"]
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    return {
        names[m.tool_call_id]: m
        for m in messages
        if isinstance(m, ToolMessage) and m.tool_call_id in names
    }


async def validate_specialist(state, result):
    observed = observations(current_call(state)["messages"])
    lookup = observed.get("lookup_metrics")
    if lookup is None:
        return ["자료를 조회하세요."]
    if lookup.status == "error" or "before" not in json.loads(lookup.content):
        return (
            []
            if result["partial"] and not result["results"]
            else ["자료 없음 또는 실패를 설명하고 부분 완료로 반환하세요."]
        )
    data = json.loads(lookup.content)
    expected = round((data["after"] - data["before"]) / data["before"] * 100, 1)
    if (
        "calculate_change" not in observed
        or json.loads(observed["calculate_change"].content) != expected
    ):
        return ["도구로 변화율을 계산하세요."]
    if not result["results"]:
        return ["실제 산출물이 필요합니다."]
    errors = []
    for item in result["results"]:
        if item["sources"] != [SOURCE]:
            errors.append("출처가 조회 자료와 다릅니다.")
        if item["type"] == "analysis_interpretation":
            target = {
                "region": data["region"],
                "before": data["before"],
                "after": data["after"],
                "change": expected,
            }
            if item["data"] != target:
                errors.append("해석 수치가 원자료·독립 계산 결과와 다릅니다.")
        else:
            rendered = observed.get("render_table")
            if rendered is None or rendered.artifact != item:
                errors.append("렌더링한 산출물을 그대로 사용하세요.")
            if item["data"].get("rows") != [
                [data["region"], data["before"], data["after"], expected]
            ]:
                errors.append("표의 표시값이 원자료·독립 계산 결과와 다릅니다.")
    return errors


async def validate_request(state, result):
    call = current_call(state)
    observed = observations(call["messages"])
    if result["results"] != call["results"]:
        return ["하위 Agent가 검증한 산출물을 변경하지 마세요."]
    if result["partial"]:
        return []
    if not all(
        name in observed and observed[name].status != "error"
        for name in ("analysis", "visualization")
    ):
        return ["해석과 시각화 결과를 모두 확인하세요."]
    if any(
        json.loads(observed[name].content)["partial"]
        for name in ("analysis", "visualization")
    ):
        return ["하위 작업의 미완료 사항을 부분 완료로 보존하세요."]
    if {item["type"] for item in result["results"]} != {
        "analysis_interpretation",
        "visualization",
    }:
        return ["검증된 해석과 표를 함께 반환하세요."]
    return []


def build_agents(models):
    analysis = Agent(
        name="analysis",
        model=models["analysis"],
        prompt=prompts.ANALYSIS,
        tools=[lookup_metrics, calculate_change],
        validate=validate_specialist,
    )
    visualization = Agent(
        name="visualization",
        model=models["visualization"],
        prompt=prompts.VISUALIZATION,
        tools=[lookup_metrics, calculate_change, render_table],
        validate=validate_specialist,
    )
    handler = Agent(
        name="request_handler",
        model=models["request_handler"],
        prompt=prompts.REQUEST_HANDLER,
        tools=[],
        children={"analysis": analysis, "visualization": visualization},
        validate=validate_request,
    )
    return {
        "analysis": analysis,
        "visualization": visualization,
        "request_handler": handler,
    }
