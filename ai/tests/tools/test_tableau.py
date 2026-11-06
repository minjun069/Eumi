"""등록 조건 검사와 오류 설명·Tableau 산출물의 실제 경계 동작."""

import json
from copy import deepcopy
from functools import partial

import pytest
from pydantic import TypeAdapter

from src.settings import Settings
from src.state import Artifact, create_state
from src.tools.tableau import (
    VisualizationResult,
    validate_visualization,
)
from src.tools.tableau_catalog import visualization_catalog

TOOL_STATE = create_state(
    {"goal": "Tableau 조건 검증"},
    Settings(_env_file=None),
    messages=[],
    version="test",
    event="user_request",
)
validate_visualization = partial(validate_visualization, state=TOOL_STATE)


pytestmark = pytest.mark.usefixtures("all_tableau_views")


def request(**overrides):
    return {
        "view_key": "Embed01VulnerabilityMap",
        "parameters": {
            "p_city": "51110",
            "p_start": "2025-07-01",
            "p_end": "2025-12-01",
        },
        "filters": {"읍면동": ["후평3동"]},
    } | overrides


def test_valid_artifact_preserves_conditions_and_public_contract():
    original = request()
    before = deepcopy(original)
    result = validate_visualization(original)
    TypeAdapter(VisualizationResult).validate_python(result)
    TypeAdapter(Artifact).validate_python(result["artifact"])
    assert original == before
    assert result["valid"] and not result["issues"]
    data = result["artifact"]["data"]
    assert data["src"] == (
        "https://public.tableau.com/views/"
        "eumi_tableau_main_dashboard_v2_0_6_connection_map_fixed/"
        "Embed01VulnerabilityMap"
    )
    assert {p["name"]: p["value"] for p in data["parameters"]} == original["parameters"]
    assert data["filters"] == [
        {
            "worksheet": "① 지도 · 배경 취약성",
            "field": "읍면동",
            "operation": "replace",
            "values": ["후평3동"],
        }
    ]
    assert data["validation_scope"] == "registered_configuration"
    assert "data_version" not in data
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "view_key",
    [
        "Embed01RiskMap",
        "Embed01VulnerabilityMap",
        "Embed01BehaviorMap",
        "Embed02RiskDistribution",
        "Embed03Vulnerability",
        "Embed05BehaviorChange",
    ],
)
def test_all_registered_views_and_defaults(view_key):
    result = validate_visualization({"view_key": view_key})
    assert result["valid"]
    data = result["artifact"]["data"]
    assert data["filters"][0]["operation"] == "all"
    assert data["filters"][0]["values"] == []
    assert len(data["parameters"]) == 3


@pytest.mark.parametrize(
    "overrides,code,path",
    [
        ({"view_key": "https://example.com/arbitrary"}, "view_not_allowed", "view_key"),
        ({"parameters": {"month": "2025-12"}}, "unknown_parameter", "parameters.month"),
        (
            {"parameters": {"p_city": "99999"}},
            "invalid_parameter_value",
            "parameters.p_city",
        ),
        (
            {"parameters": {"p_end": "not-a-date"}},
            "invalid_parameter_value",
            "parameters.p_end",
        ),
        (
            {"parameters": {"p_end": "2099-01-01"}},
            "invalid_parameter_value",
            "parameters.p_end",
        ),
        (
            {"parameters": {"p_start": "2025-12-01", "p_end": "2025-07-01"}},
            "invalid_period",
            "parameters",
        ),
        (
            {"filters": {"missing": ["후평3동"]}},
            "unsupported_filter",
            "filters.missing",
        ),
        (
            {"filters": {"읍면동": ["없는지역"]}},
            "invalid_filter_value",
            "filters.읍면동",
        ),
        (
            {"filters": {"읍면동": ["후평3동", "없는지역"]}},
            "invalid_filter_value",
            "filters.읍면동",
        ),
        ({"parameters": {"p_city": "11680"}}, "invalid_filter_value", "filters.읍면동"),
        (
            {"filters": {"읍면동": ["후평3동", "후평3동"]}},
            "duplicate_filter_value",
            "filters.읍면동",
        ),
    ],
)
def test_invalid_requests_return_actionable_issues_without_artifact(
    overrides, code, path
):
    result = validate_visualization(request(**overrides))
    assert not result["valid"] and result["artifact"] is None
    issue = next(i for i in result["issues"] if i["code"] == code)
    assert issue["path"] == path and issue["message"] and not issue["retryable"]
    if code not in {"duplicate_filter_value", "invalid_period"}:
        assert issue["allowed"]
    TypeAdapter(VisualizationResult).validate_python(result)


@pytest.mark.parametrize(
    "overrides",
    [
        {"parameters": {"p_city": 51110}},
        {"parameters": {"p_city": True}},
        {"filters": {"읍면동": "후평3동"}},
        {"filters": {"읍면동": []}},
        {"filters": {"읍면동": [None]}},
        {"filters": {"읍면동": [" "]}},
        {"src": "https://example.com"},
        {"data": {"rows": []}},
    ],
)
def test_strict_input_rejects_coercion_and_unknown_fields(overrides):
    result = validate_visualization(request(**overrides))
    assert not result["valid"] and result["artifact"] is None
    assert result["issues"][0]["code"] == "invalid_input"


def test_hash_is_stable_for_equivalent_selections_but_changes_for_conditions():
    a = request(filters={"읍면동": ["후평3동", "퇴계동"]})
    b = request(filters={"읍면동": ["퇴계동", "후평3동"]})
    assert (
        validate_visualization(a)["artifact"] == validate_visualization(b)["artifact"]
    )
    assert (
        validate_visualization(a)["artifact"]
        != validate_visualization(request())["artifact"]
    )


def test_result_and_catalog_are_isolated():
    result = validate_visualization(request())
    result["artifact"]["data"]["filters"][0]["values"].clear()
    catalog = visualization_catalog()
    catalog["input_profiles"]["monthly_city"]["filters"]["읍면동"]["allowed_by"][
        "51110"
    ].clear()
    assert validate_visualization(request())["valid"]
    assert validate_visualization(request())["artifact"]["data"]["filters"][0][
        "values"
    ] == ["후평3동"]


def test_region_error_explains_rejected_subset_without_silent_partial_success():
    result = validate_visualization(request(filters={"읍면동": ["후평3동", "역삼1동"]}))
    issue = result["issues"][0]
    assert issue["requested"] == ["역삼1동"]
    assert "후평3동" in issue["allowed"] and "역삼1동" not in issue["allowed"]
    assert result["artifact"] is None


def test_distribution_subset_has_scope_warning():
    result = validate_visualization(request(view_key="Embed02RiskDistribution"))
    data = result["artifact"]["data"]
    assert data["period_mode"] == "period"
    assert any("도시 전체" in w for w in data["warnings"])
