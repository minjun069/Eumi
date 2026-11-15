"""Agent의 시각화 판단에 필요한 지침과 참조 정보를 제공한다."""

from copy import deepcopy
from pathlib import Path
from typing import NotRequired

from typing_extensions import TypedDict

from src.tools.tableau_catalog import (
    DateOrder,
    ParameterDefinition,
    allowed_views,
    registered_catalog,
)


class Guides(TypedDict):
    selection: str
    tool: str


class ViewSummary(TypedDict):
    title: str
    purpose: str
    limitations: list[str]
    input_profile: str


class FilterGuide(TypedDict):
    depends_on: NotRequired[str]
    allowed: NotRequired[list[str]]


class ProfileGuide(TypedDict):
    parameters: dict[str, ParameterDefinition]
    filters: dict[str, FilterGuide]
    date_orders: list[DateOrder]


class SelectedGuide(TypedDict):
    parameters: dict[str, str]
    filters: dict[str, FilterGuide]


class VisualizationContext(TypedDict):
    views: dict[str, ViewSummary]
    input_profiles: NotRequired[dict[str, ProfileGuide]]
    selected: NotRequired[dict[str, SelectedGuide]]


def load_visualization_instructions() -> Guides:
    directory = Path(__file__).with_name("instructions")
    return {
        "selection": (directory / "visualization-selection.md").read_text(
            encoding="utf-8"
        ),
        "tool": (directory / "visualization-tool.md").read_text(encoding="utf-8"),
    }


def visualization_context(state, *, include_inputs: bool) -> VisualizationContext:
    """선택 목록과 입력 프로필을 공유하고 확인된 매개변수의 필터 값만 상세 제공한다."""
    catalog = registered_catalog()
    allowed = allowed_views(state)
    context: VisualizationContext = {
        "views": {
            key: {
                name: deepcopy(view[name])
                for name in ("title", "purpose", "limitations", "input_profile")
            }
            for key, view in catalog["views"].items()
            if key in allowed
        }
    }
    if not include_inputs:
        return context

    context["input_profiles"] = {}
    for name in sorted({v["input_profile"] for v in context["views"].values()}):
        profile = catalog["input_profiles"][name]
        context["input_profiles"][name] = {
            "parameters": deepcopy(profile["parameters"]),
            "date_orders": deepcopy(profile["date_orders"]),
            "filters": {
                field: {"allowed": list(definition["allowed"])}
                if "allowed" in definition
                else {"depends_on": definition["depends_on"]}
                for field, definition in profile["filters"].items()
            },
        }

    selections = {}

    def collect(current):
        for artifact in (current.get("response") or {}).get("artifacts", []):
            if artifact["type"] == "tableau":
                data = artifact["data"]
                selections[data["view_key"]] = {
                    p["name"]: p["value"] for p in data["parameters"]
                }
        for result in current.get("results", []):
            action = result.get("action") or {}
            if action.get("name") == "validate_visualization":
                args = action["arguments"]
                if isinstance(args.get("view_key"), str):
                    selections[args["view_key"]] = args.get("parameters", {})
            output = result.get("output") or {}
            if "results" in output:
                collect(output)

    collect(state)
    context["selected"] = {}
    for key, requested in selections.items():
        if key not in allowed or not isinstance(requested, dict):
            continue
        profile = catalog["input_profiles"][catalog["views"][key]["input_profile"]]
        parameters = {}
        for name, value in requested.items():
            if name in profile["parameters"]:
                if isinstance(value, str):
                    parameters[name] = value
                else:
                    parameters.pop(name, None)
        filters = deepcopy(
            context["input_profiles"][catalog["views"][key]["input_profile"]]["filters"]
        )
        for field, definition in profile["filters"].items():
            if "depends_on" in definition:
                selected = parameters.get(definition["depends_on"])
                if selected in definition["allowed_by"]:
                    filters[field]["allowed"] = list(definition["allowed_by"][selected])
        context["selected"][key] = {"parameters": parameters, "filters": filters}
    return context
