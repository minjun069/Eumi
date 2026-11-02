"""Tableau 등록 명세와 등록 시 일관성 검사. 모델 입력과 검증의 공통 원본."""

from copy import deepcopy
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated, Literal, NotRequired

from pydantic import ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Values = Annotated[list[Text], Field(min_length=1)]


@with_config(ConfigDict(extra="forbid", strict=True))
class ParameterDefinition(TypedDict):
    data_type: Literal["date", "string"]
    allowed: Values
    default: NotRequired[Text]
    labels: NotRequired[dict[Text, Text]]


@with_config(ConfigDict(extra="forbid", strict=True))
class FixedFilter(TypedDict):
    allowed: Values


@with_config(ConfigDict(extra="forbid", strict=True))
class DependentFilter(TypedDict):
    depends_on: Text
    allowed_by: dict[Text, Values]


FilterDefinition = FixedFilter | DependentFilter


@with_config(ConfigDict(extra="forbid", strict=True))
class DateOrder(TypedDict):
    start: Text
    end: Text


@with_config(ConfigDict(extra="forbid", strict=True))
class InputProfile(TypedDict):
    parameters: dict[Text, ParameterDefinition]
    filters: dict[Text, FilterDefinition]
    date_orders: list[DateOrder]


@with_config(ConfigDict(extra="forbid", strict=True))
class ViewDefinition(TypedDict):
    title: Text
    purpose: Text
    limitations: list[Text]
    workbook: Text
    view_name: Text
    input_profile: Text
    filter_targets: dict[Text, Values]
    period_mode: Literal["end_month", "period", "independent"]
    subset_warnings: list[Text]


class RegistrationVerification(TypedDict):
    scope: Literal["registration_snapshot"]
    filter_checked_at: str
    checks: list[str]
    limitations: list[str]


@with_config(ConfigDict(extra="forbid", strict=True))
class TableauCatalog(TypedDict):
    revision: Text
    registered_at: Text
    base_url: Literal["https://public.tableau.com/views"]
    input_profiles: dict[Text, InputProfile]
    views: dict[Text, ViewDefinition]
    verification: RegistrationVerification


def validate_catalog(value: object) -> TableauCatalog:
    """등록 오류는 배포 구성 오류로 즉시 거부한다. 사용자 입력 오류와 구분한다."""
    catalog = TypeAdapter(TableauCatalog).validate_python(value)

    def require(condition, path, message):
        if not condition:
            raise ValueError(f"{path}: {message}")

    def unique(values, path):
        require(len(set(values)) == len(values), path, "중복 허용값")

    require(bool(catalog["views"]), "views", "등록 뷰가 필요합니다")
    for name, profile in catalog["input_profiles"].items():
        path = f"input_profiles.{name}"
        params = profile["parameters"]
        for field, definition in params.items():
            field_path = f"{path}.parameters.{field}"
            allowed = definition["allowed"]
            unique(allowed, field_path)
            if "default" in definition:
                require(
                    definition["default"] in allowed, field_path, "허용되지 않은 기본값"
                )
            require(
                set(definition.get("labels", {})) <= set(allowed),
                field_path,
                "허용값에 없는 표시 이름",
            )
            if definition["data_type"] == "date":
                for item in allowed:
                    try:
                        valid = date.fromisoformat(item).isoformat() == item
                    except ValueError:
                        valid = False
                    require(valid, field_path, "날짜는 YYYY-MM-DD여야 합니다")
        for field, definition in profile["filters"].items():
            field_path = f"{path}.filters.{field}"
            if "allowed" in definition:
                unique(definition["allowed"], field_path)
            else:
                dependency = definition["depends_on"]
                require(dependency in params, field_path, "참조 매개변수가 없습니다")
                require(
                    set(definition["allowed_by"]) == set(params[dependency]["allowed"]),
                    field_path,
                    "매개변수의 모든 허용값에 대한 필터 목록이 필요합니다",
                )
                for values in definition["allowed_by"].values():
                    unique(values, field_path)
        for rule in profile["date_orders"]:
            start, end = rule["start"], rule["end"]
            require(
                start != end
                and all(
                    p in params and params[p]["data_type"] == "date"
                    for p in (start, end)
                ),
                path,
                "날짜 순서는 서로 다른 날짜 매개변수를 참조해야 합니다",
            )
            if all("default" in params[p] for p in (start, end)):
                require(
                    params[start]["default"] <= params[end]["default"],
                    path,
                    "기본 시작 날짜가 종료 날짜보다 늦습니다",
                )
    for key, view in catalog["views"].items():
        path = f"views.{key}"
        require(
            view["input_profile"] in catalog["input_profiles"],
            path,
            "참조 입력 프로필이 없습니다",
        )
        profile = catalog["input_profiles"][view["input_profile"]]
        require(
            set(view["filter_targets"]) == set(profile["filters"]),
            path,
            "각 필터의 대상 시트를 정확히 등록해야 합니다",
        )
        for targets in view["filter_targets"].values():
            unique(targets, path)
    return catalog


@cache
def registered_catalog() -> TableauCatalog:
    import json

    return validate_catalog(
        json.loads(
            Path(__file__).with_name("tableau_catalog.json").read_text(encoding="utf-8")
        )
    )


def visualization_catalog() -> TableauCatalog:
    """등록 설정을 외부에 제공할 때 캐시 원본을 보호한다."""
    return deepcopy(registered_catalog())
