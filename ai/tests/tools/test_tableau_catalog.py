"""새 뷰가 기존 뷰의 도시·기간 규칙에 묶이지 않는지 확인한다."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.tools import tableau
from src.tools.tableau_catalog import validate_catalog, visualization_catalog


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
    return value


def install(monkeypatch, catalog):
    validated = validate_catalog(catalog)
    monkeypatch.setattr(tableau, "registered_catalog", lambda: validated)


def test_different_workbook_and_filter_types_share_one_validator(monkeypatch, catalog):
    install(monkeypatch, catalog)
    result = tableau.validate_visualization(
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
    assert tableau.validate_visualization({"view_key": "Embed01RiskMap"})["valid"]


@pytest.mark.parametrize(
    "arguments,code",
    [
        ({}, "missing_parameter"),
        ({"parameters": {"measure": "ratio", "p_city": "51110"}}, "unknown_parameter"),
        (
            {"parameters": {"measure": "ratio"}, "filters": {"읍면동": ["후평3동"]}},
            "unsupported_filter",
        ),
        (
            {"parameters": {"measure": "ratio"}, "filters": {"연령대": ["후평3동"]}},
            "invalid_filter_value",
        ),
    ],
)
def test_selected_view_exclusively_owns_inputs(monkeypatch, catalog, arguments, code):
    install(monkeypatch, catalog)
    result = tableau.validate_visualization({"view_key": "AgeGroups"} | arguments)
    assert not result["valid"] and result["artifact"] is None
    assert result["issues"][0]["code"] == code


def test_view_without_any_parameters_or_filters(monkeypatch, catalog):
    catalog["input_profiles"]["groups"] = {
        "parameters": {},
        "filters": {},
        "date_orders": [],
    }
    catalog["views"]["AgeGroups"]["filter_targets"] = {}
    install(monkeypatch, catalog)
    result = tableau.validate_visualization({"view_key": "AgeGroups"})
    assert result["valid"]
    assert result["artifact"]["data"]["parameters"] == []
    assert result["artifact"]["data"]["filters"] == []


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
    assert tableau.validate_visualization(request)["valid"]
    profile["date_orders"] = [{"start": "from_date", "end": "to_date"}]
    install(monkeypatch, catalog)
    result = tableau.validate_visualization(request)
    assert result["issues"][0]["code"] == "invalid_period"
    assert result["issues"][0]["requested"] == request["parameters"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c["views"]["AgeGroups"].update(input_profile="missing"),
        lambda c: c["views"]["AgeGroups"]["filter_targets"].clear(),
        lambda c: c["views"]["AgeGroups"]["filter_targets"].update(연령대=[]),
        lambda c: c["views"]["AgeGroups"]["filter_targets"].update(
            연령대=["same", "same"]
        ),
        lambda c: c["input_profiles"]["groups"]["parameters"]["measure"].update(
            default="missing"
        ),
        lambda c: c["input_profiles"]["groups"]["parameters"]["measure"].update(
            allowed=["count", "count"]
        ),
        lambda c: c["input_profiles"]["groups"]["parameters"]["measure"].update(
            labels={"missing": "name"}
        ),
        lambda c: c["input_profiles"]["groups"].update(
            date_orders=[{"start": "measure", "end": "missing"}]
        ),
        lambda c: c["input_profiles"]["monthly_city"]["filters"]["읍면동"].update(
            depends_on="missing"
        ),
        lambda c: c["input_profiles"]["monthly_city"]["filters"]["읍면동"][
            "allowed_by"
        ].pop("51110"),
        lambda c: c["input_profiles"]["monthly_city"]["parameters"]["p_start"].update(
            allowed=["invalid-date"]
        ),
        lambda c: c["input_profiles"]["monthly_city"]["parameters"]["p_start"].update(
            default="2025-12-01"
        ),
    ],
)
def test_registration_rejects_inconsistent_configuration(catalog, mutation):
    # 마지막 사례가 기본 날짜 역순을 만들도록 종료 기본값을 먼저 설정한다.
    catalog["input_profiles"]["monthly_city"]["parameters"]["p_end"]["default"] = (
        "2025-07-01"
    )
    mutation(catalog)
    with pytest.raises((ValueError, ValidationError)):
        validate_catalog(catalog)


def test_registration_does_not_mutate_input(catalog):
    before = deepcopy(catalog)
    validate_catalog(catalog)
    assert catalog == before
