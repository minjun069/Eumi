"""선택 단계의 입력량을 줄이면서 필요한 조건·후속 작업 정보를 보존한다."""

from functools import partial

import pytest

from src.settings import Settings
from src.state import create_state
from src.tools.tableau import validate_visualization
from src.visualization_instructions import visualization_context

TOOL_STATE = create_state(
    {"goal": "Tableau 조건 검증"},
    Settings(_env_file=None),
    messages=[],
    version="test",
    event="user_request",
)
validate_visualization = partial(validate_visualization, state=TOOL_STATE)


pytestmark = pytest.mark.usefixtures("all_tableau_views")


def test_interpretation_receives_only_selection_descriptions(all_tableau_views):
    context = visualization_context(TOOL_STATE, include_inputs=False)
    assert set(context) == {"views"}
    assert set(context["views"]) == set(all_tableau_views["views"])
    assert all(
        set(view) == {"title", "purpose", "limitations", "input_profile"}
        for view in context["views"].values()
    )


def test_selection_shares_profiles_and_omits_unselected_domains():
    context = visualization_context(TOOL_STATE, include_inputs=True)
    assert set(context["input_profiles"]) == {"monthly_city", "monthly_detail"}
    assert context["input_profiles"]["monthly_city"]["filters"]["읍면동"] == {
        "depends_on": "p_city"
    }
    assert context["selected"] == {}


def test_followup_receives_selected_city_only_and_is_isolated():
    artifact = validate_visualization(
        {"view_key": "Embed01RiskMap", "parameters": {"p_city": "11680"}}
    )["artifact"]
    state = {"response": {"artifacts": [artifact]}}
    state["execution"] = TOOL_STATE["execution"]
    context = visualization_context(state, include_inputs=True)
    selected = context["selected"]["Embed01RiskMap"]["filters"]["읍면동"]["allowed"]
    assert "역삼1동" in selected and "후평3동" not in selected
    selected.clear()
    assert visualization_context(state, include_inputs=True)["selected"][
        "Embed01RiskMap"
    ]["filters"]["읍면동"]["allowed"]


def test_invalid_dependency_does_not_expose_default_domain_as_selected():
    state = {
        "results": [
            {
                "action": {
                    "name": "validate_visualization",
                    "arguments": {
                        "view_key": "Embed01RiskMap",
                        "parameters": {"p_city": 51110},
                    },
                }
            }
        ]
    }
    state["execution"] = TOOL_STATE["execution"]
    context = visualization_context(state, include_inputs=True)
    assert "allowed" not in context["selected"]["Embed01RiskMap"]["filters"]["읍면동"]


def test_latest_attempt_supersedes_previous_view_conditions():
    artifact = validate_visualization(
        {"view_key": "Embed01RiskMap", "parameters": {"p_city": "11680"}}
    )["artifact"]
    state = {
        "response": {"artifacts": [artifact]},
        "results": [
            {
                "action": {
                    "name": "validate_visualization",
                    "arguments": {
                        "view_key": "Embed01RiskMap",
                        "parameters": {"p_city": "51110"},
                    },
                }
            }
        ],
    }
    state["execution"] = TOOL_STATE["execution"]
    context = visualization_context(state, include_inputs=True)
    selected = context["selected"]["Embed01RiskMap"]["filters"]["읍면동"]["allowed"]
    assert "후평3동" in selected and "역삼1동" not in selected
