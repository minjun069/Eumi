"""새 뷰가 기존 뷰의 도시·기간 규칙에 묶이지 않는지 확인한다."""

import pytest
from pydantic import ValidationError

from src.settings import Settings
from src.state import create_state
from src.tools import tableau, tableau_catalog
from src.tools.tableau_catalog import validate_catalog, visualization_catalog

pytestmark = pytest.mark.usefixtures("all_tableau_views")


@pytest.fixture
def catalog():
    value = visualization_catalog()
    value["input_profiles"]["groups"] = {
        "parameters": {
            "measure": {"data_type": "string", "allowed": ["count", "ratio"]}
        },
        "filters": {"연령대": {"allowed": ["청년", "중년", "노년"]}},
        "date_orders": [],
    }
    value["views"]["AgeGroups"] = {
        "title": "테스트 연령대 비교",
        "purpose": "테스트용 집단 비교",
        "limitations": ["합성 등록 명세"],
        "workbook": "another_workbook",
        "view_name": "PublishedAgeGroups",
        "input_profile": "groups",
        "filter_targets": {"연령대": ["연령별 수", "연령별 비율"]},
        "period_mode": "independent",
        "subset_warnings": [],
    }
    value["event_views"]["user_request"].append("AgeGroups")
    return value


def install(monkeypatch, catalog):
    validated = validate_catalog(catalog)
    monkeypatch.setattr(tableau, "registered_catalog", lambda: validated)
    monkeypatch.setattr(tableau_catalog, "registered_catalog", lambda: validated)


def validate_visualization(request):
    state = create_state(
        {"goal": "등록 명세 검증"},
        Settings(_env_file=None),
        messages=[],
        version="test",
        event="user_request",
    )
    return tableau.validate_visualization(request, state=state)


def test_different_workbook_and_filter_types_share_one_validator(monkeypatch, catalog):
    install(monkeypatch, catalog)
    result = validate_visualization(
        {
            "view_key": "AgeGroups",
            "parameters": {"measure": "ratio"},
            "filters": {"연령대": ["노년"]},
        }
    )
    assert result["valid"]
    data = result["artifact"]["data"]
    assert data["src"].endswith("/another_workbook/PublishedAgeGroups")
    assert data["parameters"] == [
        {"name": "measure", "data_type": "string", "value": "ratio"}
    ]
    assert {f["worksheet"] for f in data["filters"]} == {"연령별 수", "연령별 비율"}
    assert all(f["values"] == ["노년"] for f in data["filters"])
    assert validate_visualization({"view_key": "Embed01RiskMap"})["valid"]


@pytest.mark.parametrize(
    "arguments,code",
    [
        ({}, "missing_parameter"),
        ({"parameters": {"measure": "ratio", "p_city": "51110"}}, "unknown_parameter"),
    ],
)
def test_selected_view_exclusively_owns_inputs(monkeypatch, catalog, arguments, code):
    install(monkeypatch, catalog)
    result = validate_visualization({"view_key": "AgeGroups"} | arguments)
    assert not result["valid"] and result["artifact"] is None
    assert result["issues"][0]["code"] == code


def test_only_declared_date_order_is_checked(monkeypatch, catalog):
    profile = catalog["input_profiles"]["groups"]
    profile["parameters"] = {
        name: {"data_type": "date", "allowed": ["2025-01-01", "2025-06-01"]}
        for name in ("from_date", "to_date")
    }
    request = {
        "view_key": "AgeGroups",
        "parameters": {"from_date": "2025-06-01", "to_date": "2025-01-01"},
    }
    install(monkeypatch, catalog)
    assert validate_visualization(request)["valid"]
    profile["date_orders"] = [{"start": "from_date", "end": "to_date"}]
    install(monkeypatch, catalog)
    result = validate_visualization(request)
    assert result["issues"][0]["code"] == "invalid_period"
    assert result["issues"][0]["requested"] == request["parameters"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c["views"]["AgeGroups"].update(input_profile="missing"),
        lambda c: c["input_profiles"]["groups"]["parameters"]["measure"].update(
            default="missing"
        ),
    ],
)
def test_registration_rejects_inconsistent_configuration(catalog, mutation):
    mutation(catalog)
    with pytest.raises((ValueError, ValidationError)):
        validate_catalog(catalog)
