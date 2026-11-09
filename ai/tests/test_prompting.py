"""제목형 입력, State 보존 및 실제 노드의 호출·검증 경계를 확인한다."""

from copy import deepcopy

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from experiments.scenario_fixtures import CATALOG, PROVIDERS
from src.agent_nodes import (
    build_nodes,
    record,
)
from src.execution import accepted_outputs
from src.prompting import (
    ask_messages,
    compose_messages,
    decide_messages,
    interpret_messages,
    selection_messages,
)
from tests.helpers import ScriptedModel, initial, section, selection

pytestmark = pytest.mark.usefixtures("all_tableau_views")


def test_each_node_selects_materials_without_mutating_state():
    role = "request"
    state = initial()
    state["results"] = [
        record(
            "act", "selection", "조회", output=selection("query_data", {"target": "D3"})
        ),
        record(
            "act",
            "call",
            "조회",
            action={"name": "query_data", "arguments": {"target": "D3"}},
            output={"data": {"rows": [{"n": 11}]}},
        ),
    ]
    before = deepcopy(state)
    catalog = {"data_catalog_sentinel": {"title": "조회 목록"}}
    builders = [
        interpret_messages,
        decide_messages,
        compose_messages,
        ask_messages,
    ]
    for builder in builders:
        messages = builder(state, role)
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)
        assert state["messages"][0].content in messages[1].content
        assert "data_catalog_sentinel" not in messages[1].content
        assert "[시각화 목록과 입력 조건]" not in messages[1].content
    messages = selection_messages(state, role, catalog)
    assert "data_catalog_sentinel" in messages[1].content
    assert state == before


def test_decision_keeps_nested_call_results_without_model_verification():
    state = initial()
    child = record("act", "call", "원본", output={"data": {"rows": [{"n": 1}]}})
    parent = record("act", "call", "하위 결과", output={"results": [child]})
    state["results"] = [parent]
    before = deepcopy(state)
    messages = decide_messages(state, "request")
    records = section(messages, "작업 결과와 검증 이력")
    assert records[0]["output"]["results"][0]["id"] == child["id"]
    assert state == before


@pytest.mark.parametrize(
    "role,expected",
    [
        ("report", {"query_data", "process_data"}),
        ("visualization", {"query_data", "process_data", "validate_visualization"}),
        (
            "request",
            {
                "query_data",
                "process_data",
                "validate_visualization",
                "interpretation_agent",
                "visualization_agent",
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_selection_response_choices_match_provided_tools(role, expected):
    model = ScriptedModel([selection("none", {})])
    command = await build_nodes(model, PROVIDERS, CATALOG, role=role)["act"](
        initial(), {}
    )
    provided = {item["function"]["name"] for item in model.tool_definitions[0]}
    schema = model.response_schemas[0]
    assert provided == expected
    assert set(schema["properties"]["name"]["enum"]) == provided | {"none"}
    assert set(schema["properties"]) == {"name", "arguments_json", "reason"}
    assert command.goto == "decide"
    assert [r["decision"] for r in command.update["results"]] == ["selection"]


@pytest.mark.parametrize(
    "condition",
    [
        "rejected",
        "failed_child",
    ],
)
def test_unusable_results_remain_excluded_without_model_verification(condition):
    state = initial()
    child = record("act", "call", "하위 자료", output={"data": {"rows": []}})
    called = record("act", "call", "호출", output={"results": [child]})
    state["results"] = [called]
    if condition == "failed_child":
        called["output"]["execution"] = {"status": "failed"}
    else:
        state["results"].append(
            record(
                "act",
                "verification",
                "부적합",
                output={"call_id": called["id"], "accepted": False},
            )
        )
    assert accepted_outputs(state) == {}


def test_report_draft_still_requires_separate_review():
    state = initial()
    draft = record("compose", "report_draft", "작성", output={"content": "설명"})
    state["results"] = [draft]
    assert accepted_outputs(state) == {}
    state["results"].append(
        record(
            "compose",
            "verification",
            "보고서 검토",
            output={"call_id": draft["id"], "accepted": True},
        )
    )
    assert accepted_outputs(state) == {draft["id"]: draft["output"]}
