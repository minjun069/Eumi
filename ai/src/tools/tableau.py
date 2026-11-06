"""Tableau 시각화 요청을 검증하고 화면 연동용 산출물을 구성한다."""

import json
from datetime import date
from hashlib import sha256
from typing import Annotated, Literal, NotRequired
from urllib.parse import quote

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    with_config,
)
from typing_extensions import TypedDict

from src.state import State
from src.tools.tableau_catalog import Text, allowed_views, registered_catalog


@with_config(ConfigDict(extra="forbid", strict=True))
class VisualizationRequest(TypedDict):
    view_key: Text
    parameters: NotRequired[dict[Text, Text]]
    filters: NotRequired[dict[Text, Annotated[list[Text], Field(min_length=1)]]]


class ValidationIssue(TypedDict):
    code: str
    path: str
    message: str
    requested: JsonValue
    allowed: list[str]
    retryable: Literal[False]


class TableauParameter(TypedDict):
    name: str
    data_type: Literal["date", "string"]
    value: str


class TableauFilter(TypedDict):
    worksheet: str
    field: str
    operation: Literal["replace", "all"]
    values: list[str]


class TableauSource(TypedDict):
    label: str
    uri: str


class TableauData(TypedDict):
    schema_version: Literal[1]
    artifact_id: str
    catalog_revision: str
    view_key: str
    src: str
    title: str
    period_mode: Literal["end_month", "period", "independent"]
    parameters: list[TableauParameter]
    filters: list[TableauFilter]
    source: TableauSource
    validation_scope: Literal["registered_configuration"]
    warnings: list[str]


class TableauArtifact(TypedDict):
    type: Literal["tableau"]
    data: TableauData


class VisualizationResult(TypedDict):
    valid: bool
    validation_scope: Literal["registered_configuration"]
    catalog_revision: str
    issues: list[ValidationIssue]
    artifact: TableauArtifact | None


visualization_adapter = TypeAdapter(VisualizationRequest)


def _issue(code, path, message, requested, allowed=()) -> ValidationIssue:
    # 형식이 잘못된 Python 입력도 JSON으로 진단할 수 있게 한다.
    try:
        requested = json.loads(json.dumps(requested, allow_nan=False))
    except (ValueError, TypeError):
        requested = f"<{type(requested).__name__}>"
    return {
        "code": code,
        "path": path,
        "message": message,
        "requested": requested,
        "allowed": list(allowed),
        "retryable": False,
    }


def validate_visualization(
    request: VisualizationRequest, *, state: State
) -> VisualizationResult:
    """부적합도 검사 결과로 반환한다. 허용값 자동 보정·부분 적용은 하지 않는다."""
    catalog = registered_catalog()
    allowed = allowed_views(state)
    result: VisualizationResult = {
        "valid": False,
        "validation_scope": "registered_configuration",
        "catalog_revision": catalog["revision"],
        "issues": [],
        "artifact": None,
    }
    issues = result["issues"]
    try:
        request = visualization_adapter.validate_python(request)
    except ValidationError as exc:
        for error in exc.errors(include_url=False, include_context=False):
            issues.append(
                _issue(
                    "invalid_input",
                    ".".join(map(str, error["loc"])),
                    error["msg"],
                    error.get("input"),
                )
            )
        return result

    key = request["view_key"]
    if key not in allowed:
        issues.append(
            _issue(
                "view_not_allowed",
                "view_key",
                "이 실행 이벤트에 허용된 뷰를 선택하세요.",
                key,
                sorted(allowed),
            )
        )
        return result

    view = catalog["views"][key]
    profile = catalog["input_profiles"][view["input_profile"]]
    definitions = profile["parameters"]
    parameters = {
        name: item["default"] for name, item in definitions.items() if "default" in item
    }
    for name, value in request.get("parameters", {}).items():
        definition = definitions.get(name)
        if definition is None:
            issues.append(
                _issue(
                    "unknown_parameter",
                    f"parameters.{name}",
                    "이 뷰에 등록되지 않은 매개변수입니다.",
                    value,
                    definitions,
                )
            )
            continue
        parameters[name] = value
        if value not in definition["allowed"]:
            issues.append(
                _issue(
                    "invalid_parameter_value",
                    f"parameters.{name}",
                    "등록된 허용값과 정확히 일치해야 합니다.",
                    value,
                    definition["allowed"],
                )
            )
    for name, definition in definitions.items():
        if name not in parameters:
            issues.append(
                _issue(
                    "missing_parameter",
                    f"parameters.{name}",
                    "기본값이 없는 필수 매개변수입니다.",
                    None,
                    definition["allowed"],
                )
            )

    for rule in profile["date_orders"]:
        start, end = rule["start"], rule["end"]
        if all(parameters.get(n) in definitions[n]["allowed"] for n in (start, end)):
            if date.fromisoformat(parameters[start]) > date.fromisoformat(
                parameters[end]
            ):
                issues.append(
                    _issue(
                        "invalid_period",
                        "parameters",
                        f"{start}는 {end}보다 늦을 수 없습니다.",
                        {start: parameters[start], end: parameters[end]},
                    )
                )

    for field, values in request.get("filters", {}).items():
        definition = profile["filters"].get(field)
        if definition is None:
            issues.append(
                _issue(
                    "unsupported_filter",
                    f"filters.{field}",
                    "이 뷰에 등록되지 않은 필터입니다.",
                    values,
                    profile["filters"],
                )
            )
            continue
        if len(values) != len(set(values)):
            issues.append(
                _issue(
                    "duplicate_filter_value",
                    f"filters.{field}",
                    "같은 값을 중복 지정할 수 없습니다.",
                    values,
                )
            )
        if "allowed" in definition:
            allowed = definition["allowed"]
            message = "이 필터의 등록 허용값에 없는 값입니다."
        else:
            dependency = definition["depends_on"]
            selected = parameters.get(dependency)
            if selected not in definition["allowed_by"]:
                continue  # 매개변수 오류의 부차적인 필터 오류는 만들지 않는다.
            allowed = definition["allowed_by"][selected]
            message = f"{dependency}={selected} 조건에서 허용되지 않는 값입니다."
        invalid = [value for value in values if value not in allowed]
        if invalid:
            issues.append(
                _issue(
                    "invalid_filter_value",
                    f"filters.{field}",
                    message + " 값을 자동 제외하지 않습니다.",
                    invalid,
                    allowed,
                )
            )
    if issues:
        return result

    src = (
        f"{catalog['base_url']}/{quote(view['workbook'], safe='')}/"
        f"{quote(view['view_name'], safe='')}"
    )
    data: TableauData = {
        "schema_version": 1,
        "artifact_id": "",
        "catalog_revision": catalog["revision"],
        "view_key": key,
        "src": src,
        "title": view["title"],
        "period_mode": view["period_mode"],
        "parameters": [
            {
                "name": name,
                "data_type": definitions[name]["data_type"],
                "value": value,
            }
            for name, value in sorted(parameters.items())
        ],
        "filters": [
            {
                "worksheet": worksheet,
                "field": field,
                "operation": "replace"
                if field in request.get("filters", {})
                else "all",
                "values": sorted(request.get("filters", {}).get(field, [])),
            }
            for field, worksheets in view["filter_targets"].items()
            for worksheet in worksheets
        ],
        "source": {"label": "Tableau Public · " + view["title"], "uri": src},
        "validation_scope": "registered_configuration",
        "warnings": [
            "등록 설정 검사 결과입니다. 실제 데이터 유무·최신성·"
            "브라우저 표시 성공은 확인하지 않았습니다.",
            "설정 등록 버전은 원자료 버전이 아닙니다.",
        ],
    }
    data["warnings"].extend(view["limitations"])
    if request.get("filters"):
        data["warnings"].extend(view["subset_warnings"])
    encoded = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    data["artifact_id"] = "tableau-" + sha256(encoded.encode()).hexdigest()[:24]
    result["valid"] = True
    result["artifact"] = {"type": "tableau", "data": data}
    return result
