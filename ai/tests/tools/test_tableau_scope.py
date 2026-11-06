"""호출 측에서 주입한 허용 범위가 안내·호출 경계에서 일치하는지 확인한다."""

import pytest

from src.tools.interface import create_tools
from src.tools.tableau import validate_visualization
from src.tools.tableau_catalog import (
    resolve_allowed_views,
    validate_catalog,
    visualization_catalog,
)
from src.visualization_instructions import visualization_context

MAP = "Embed01RiskMap"
OTHER = "Embed03Vulnerability"


def tool(keys):
    return next(
        t
        for t in create_tools({}, allowed_view_keys=keys)
        if t.name == "validate_visualization"
    )


def test_default_and_empty_scope_deny_all():
    assert not validate_visualization({"view_key": MAP})["valid"]
    for keys in ([], (), set(), frozenset()):
        output = tool(keys).invoke({"view_key": MAP})
        assert output["artifact"] is None
        assert output["issues"][0]["code"] == "view_not_allowed"
        assert output["issues"][0]["allowed"] == []
        assert visualization_context(
            {}, include_inputs=True, allowed_view_keys=keys
        ) == {"views": {}, "input_profiles": {}, "selected": {}}


@pytest.mark.parametrize(
    "keys", [None, MAP, [None], [123], [" "], ["unknown"], {MAP: True}]
)
def test_bad_scope_is_configuration_error(keys):
    with pytest.raises(ValueError, match="allowed_view_keys"):
        create_tools({}, allowed_view_keys=keys)
    with pytest.raises(ValueError, match="allowed_view_keys"):
        visualization_context({}, include_inputs=True, allowed_view_keys=keys)


def test_only_allowed_view_is_executable_and_advertised():
    configured = tool([MAP])
    assert configured.invoke({"view_key": MAP})["valid"]
    for key in (OTHER, "unknown"):
        result = configured.invoke({"view_key": key})
        assert not result["valid"] and result["artifact"] is None
        assert result["issues"][0]["code"] == "view_not_allowed"
        assert result["issues"][0]["allowed"] == [MAP]
    context = visualization_context({}, include_inputs=True, allowed_view_keys=[MAP])
    assert list(context["views"]) == [MAP]
    assert list(context["input_profiles"]) == ["monthly_city"]


def test_tool_schema_does_not_let_model_modify_scope():
    configured = tool([MAP])
    assert "allowed_view_keys" not in configured.args_schema["properties"]
    assert configured.args_schema["properties"]["view_key"]["enum"] == [MAP]
    result = configured.invoke({"view_key": OTHER, "allowed_view_keys": [OTHER]})
    assert not result["valid"]
    assert result["issues"][0]["code"] == "invalid_input"
    assert not configured.invoke({"view_key": OTHER})["valid"]


def test_scopes_are_snapshots_and_do_not_change_other_executions():
    keys = [MAP]
    first, second = tool(keys), tool([OTHER])
    keys.append(OTHER)
    assert first.invoke({"view_key": MAP})["valid"]
    assert not first.invoke({"view_key": OTHER})["valid"]
    assert second.invoke({"view_key": OTHER})["valid"]
    assert not second.invoke({"view_key": MAP})["valid"]
    assert resolve_allowed_views([MAP, MAP]) == frozenset([MAP])


def test_previous_forbidden_view_does_not_load_its_details():
    artifact = validate_visualization({"view_key": OTHER}, allowed_view_keys=[OTHER])[
        "artifact"
    ]
    state = {"response": {"artifacts": [artifact]}}
    context = visualization_context(state, include_inputs=True, allowed_view_keys=[MAP])
    assert OTHER not in context["views"] and OTHER not in context["selected"]


def test_unrelated_input_profile_is_not_loaded(monkeypatch):
    from src import visualization_instructions
    from src.tools import tableau_catalog

    catalog = visualization_catalog()
    catalog["input_profiles"]["other_profile"] = {
        "parameters": {},
        "filters": {},
        "date_orders": [],
    }
    catalog["views"][OTHER].update(input_profile="other_profile", filter_targets={})
    validated = validate_catalog(catalog)
    monkeypatch.setattr(tableau_catalog, "registered_catalog", lambda: validated)
    monkeypatch.setattr(
        visualization_instructions, "registered_catalog", lambda: validated
    )
    context = visualization_context({}, include_inputs=True, allowed_view_keys=[MAP])
    assert "other_profile" not in context["input_profiles"]
