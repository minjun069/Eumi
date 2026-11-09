"""외부 모델만 대체하고 실제 노드·결정론적 도구·산출물 선택을 실행한다."""

import json
from copy import deepcopy
from functools import partial
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent_nodes import build_nodes, finish, select_artifacts
from src.exceptions import ToolFailure
from src.graph import compile_graph
from src.settings import Settings
from src.state import create_state, state_adapter
from src.tools.interface import create_tools
from src.tools.tableau import validate_visualization

TOOL_STATE = create_state(
    {"goal": "Tableau 조건 검증"},
    Settings(_env_file=None),
    messages=[],
    version="test",
    event="user_request",
)
validate_visualization = partial(validate_visualization, state=TOOL_STATE)
create_tools = partial(create_tools, state=TOOL_STATE)

VALID = {
    "view_key": "Embed01VulnerabilityMap",
    "parameters": {"p_city": "51110"},
    "filters": {"읍면동": ["후평3동"]},
}


pytestmark = pytest.mark.usefixtures("all_tableau_views")

def choose(name, args):
    return {
        "name": name,
        "arguments_json": json.dumps(args, ensure_ascii=False),
        "reason": "요청 조건",
    }


def last_call(context):
    return next(
        r["id"] for r in reversed(context["results"]) if r["decision"] == "call"
    )


def compose(context):
    return {
        "content": "춘천시 후평3동의 배경 취약성 표시 설정입니다.",
        "artifact_ids": [last_call(context)],
        "status": "completed",
        "reason": "설정 검사 통과",
    }


class Model:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    async def ainvoke(self, messages, config):
        context = json.loads(messages[1].content.split("\n", 1)[1])
        self.calls.append((messages[0].content, context))
        value = next(self.replies)
        if callable(value):
            value = value(context)
        return AIMessage(json.dumps(value, ensure_ascii=False))


async def run(
    model,
    *,
    role="visualization",
    settings=None,
    previous=None,
):
    settings = settings or Settings(_env_file=None)
    state = create_state(
        {"goal": "춘천시 후평3동 배경 취약성 지도"},
        settings,
        messages=[HumanMessage("춘천시 후평3동 배경 취약성 지도")],
        version="test",
        event="analysis_pipeline",
    )
    if previous:
        state["response"] = deepcopy(previous)
    graph = compile_graph(
        build_nodes(model, {}, [], settings, role=role),
        finish=finish,
    )
    return await graph.ainvoke(state, {"recursion_limit": 35})


@pytest.mark.asyncio
async def test_guides_catalog_and_real_tool_reach_model_and_public_response():
    model = Model(
        [
            choose("validate_visualization", VALID),
            {"accepted": True, "reason": "요청과 설정 일치"},
            {"next": "compose", "reason": "준비 완료"},
            compose,
        ]
    )
    state = await run(model)
    state_adapter.validate_python(state)
    assert state["execution"]["status"] == "completed"
    assert state["response"]["artifacts"] == [validate_visualization(VALID)["artifact"]]
    instructions = Path(__file__).parents[1] / "src" / "instructions"
    selection = (instructions / "visualization-selection.md").read_text(
        encoding="utf-8"
    )
    tool = (instructions / "visualization-tool.md").read_text(encoding="utf-8")
    first_prompt, first_context = model.calls[0]
    assert selection in first_prompt and tool in first_prompt
    assert first_context["visualization_catalog"]["views"][VALID["view_key"]]
    assert "allowed_by" not in json.dumps(first_context["visualization_catalog"])
    for prompt, context in model.calls[1:]:
        assert selection not in prompt and tool not in prompt
        assert "visualization_catalog" not in context
    assert not any(
        r["action"] and r["action"]["name"] == "query_data" for r in state["results"]
    )


@pytest.mark.asyncio
async def test_invalid_conditions_are_visible_for_repair_and_cannot_be_published():
    invalid = VALID | {"filters": {"읍면동": ["역삼1동"]}}

    def repair(context):
        selected = context["visualization_catalog"]["selected"][VALID["view_key"]]
        assert "후평3동" in selected["filters"]["읍면동"]["allowed"]
        assert "역삼1동" not in selected["filters"]["읍면동"]["allowed"]
        output = next(
            r["output"] for r in reversed(context["results"]) if r["decision"] == "call"
        )
        assert output["valid"] is False and output["artifact"] is None
        assert output["issues"][0]["requested"] == ["역삼1동"]
        assert "후평3동" in output["issues"][0]["allowed"]
        return choose("validate_visualization", VALID)

    model = Model(
        [
            choose("validate_visualization", invalid),
            {"next": "act", "reason": "지역 수정"},
            repair,
            {"accepted": True, "reason": "수정 조건 확인"},
            {"next": "compose", "reason": "충분"},
            compose,
        ]
    )
    state = await run(model)
    calls = [r for r in state["results"] if r["decision"] == "call"]
    assert len(calls) == 2 and calls[0]["outcome"] == "success"
    rejected = next(r for r in state["results"] if r["decision"] == "verification")
    assert rejected["outcome"] == "success" and not rejected["output"]["accepted"]
    # 모델이 뒤늦게 유효하다고 주장해도 부적합 도구 결과는 공개할 수 없다.
    forged = deepcopy(state)
    next(r for r in forged["results"] if r["decision"] == "verification")["output"][
        "accepted"
    ] = True
    with pytest.raises(ToolFailure):
        select_artifacts(forged, [calls[0]["id"]])
    assert len(state["response"]["artifacts"]) == 1


@pytest.mark.asyncio
async def test_invalid_validation_consumes_existing_repair_limit():
    invalid = VALID | {"parameters": {"p_city": "99999"}}
    model = Model(
        [
            choose("validate_visualization", invalid),
            {"next": "act", "reason": "다시 시도"},
            {"next": "act", "reason": "한도 무시 시도"},
            {
                "content": "지원 도시 확인 필요",
                "artifact_ids": [],
                "status": "partial",
                "reason": "한도",
            },
        ]
    )
    state = await run(model, settings=Settings(_env_file=None, max_tool_retries=0))
    assert any(r["decision"] == "limit_reached" for r in state["results"])
    assert state["execution"]["status"] == "partial"
    assert state["response"]["artifacts"] == []


@pytest.mark.asyncio
async def test_request_agent_preserves_child_tableau_artifact():
    from tableau_demo import run_visualization

    valid = {"accepted": True, "reason": "조건 일치"}
    done = {"next": "compose", "reason": "충분"}
    model = Model(
        [
            {
                "request": {"goal": "춘천시 후평3동 배경 취약성 지도"},
                "reason": "요청 확인",
                "needs_input": False,
            },
            choose("visualization_agent", {"goal": "춘천시 후평3동 배경 취약성 지도"}),
            {
                "request": {"goal": "춘천시 후평3동 배경 취약성 지도"},
                "reason": "확인",
                "needs_input": False,
            },
            choose("validate_visualization", VALID),
            valid,
            done,
            compose,
            valid,
            done,
            compose,
        ]
    )
    state = await run_visualization(
        "춘천시 후평3동 배경 취약성 지도",
        model,
        Settings(_env_file=None),
    )
    child = next(
        r["output"]
        for r in state["results"]
        if r["action"] and r["action"]["name"] == "visualization_agent"
    )
    assert state["response"]["artifacts"] == child["response"]["artifacts"]
    assert state["response"]["artifacts"][0]["type"] == "tableau"


@pytest.mark.asyncio
async def test_followup_preserves_existing_tableau_without_revalidation():
    previous = {
        "id": "old",
        "kind": "final",
        "label": "지도",
        "content": "지도",
        "artifacts": [validate_visualization(VALID)["artifact"]],
    }
    model = Model(
        [
            choose("none", {}),
            {"next": "compose", "reason": "조건 설명"},
            {
                "content": "선택된 조건 설명",
                "artifact_ids": ["previous"],
                "status": "completed",
                "reason": "유지",
            },
        ]
    )
    state = await run(model, previous=previous)
    assert state["response"]["artifacts"] == previous["artifacts"]


@pytest.mark.asyncio
async def test_interpretation_role_cannot_invoke_visualization_tool():
    model = Model(
        [
            choose("validate_visualization", VALID),
            {"next": "compose", "reason": "허용 작업 아님"},
            {
                "content": "시각화 역할 필요",
                "artifact_ids": [],
                "status": "partial",
                "reason": "역할",
            },
        ]
    )
    state = await run(model, role="interpretation")
    assert (
        next(r["output"] for r in state["results"] if r["decision"] == "call_failed")[
            "code"
        ]
        == "tool_not_allowed"
    )
    assert all("visualization_catalog" not in c for _, c in model.calls)


@pytest.mark.asyncio
async def test_native_tool_call_keeps_structured_validation_errors():
    tool = next(t for t in create_tools({}) if t.name == "validate_visualization")
    message = await tool.ainvoke(
        {
            "type": "tool_call",
            "id": "v1",
            "name": tool.name,
            "args": VALID | {"parameters": {"p_city": "99999"}},
        }
    )
    output = json.loads(message.content)
    assert not output["valid"] and output["issues"][0]["allowed"] == ["11680", "51110"]
