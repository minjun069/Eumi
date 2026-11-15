"""노드 평가 문서의 형식을 모델 원본에 적용한다. 업무 스키마 검증과 분리한다."""

import json
import re
from copy import deepcopy
from datetime import date
from math import isfinite
from typing import Annotated, Literal, NotRequired

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    with_config,
)
from typing_extensions import TypedDict

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Scalar = str | int | Finite | bool | None
Texts = Annotated[list[Text], Field(min_length=1)]
STRICT = ConfigDict(extra="forbid", strict=True)


@with_config(STRICT)
class Constraints(TypedDict, total=False):
    required: list[str]
    preferred: list[str]
    excluded: list[str]


@with_config(STRICT)
class Request(TypedDict):
    goal: Text
    constraints: NotRequired[Constraints]


@with_config(STRICT)
class Interpretation(TypedDict):
    request: Request
    reason: str


@with_config(STRICT)
class Selection(TypedDict):
    name: Literal[
        "query_data",
        "process_data",
        "validate_visualization",
        "interpretation_agent",
        "visualization_agent",
    ]
    arguments_json: str
    reason: str


@with_config(STRICT)
class Decision(TypedDict):
    next: Literal["act", "compose", "ask"]
    reason: str


@with_config(STRICT)
class Composition(TypedDict):
    content: str
    artifact_ids: list[str]
    status: Literal["completed", "partial", "failed"]
    reason: str


@with_config(STRICT)
class Question(TypedDict):
    content: str
    reason: str


@with_config(STRICT)
class SelectedView(TypedDict):
    view_key: Literal[
        "EmbedDetailV01",
        "EmbedDetailV02",
        "EmbedDetailV03",
        "EmbedDetailV04",
        "EmbedDetailV05",
        "EmbedDetailV06",
        "EmbedDetailV07",
        "EmbedDetailV08",
    ]
    reason: Text
    evidence_ids: Texts


@with_config(STRICT)
class ReportSelection(TypedDict):
    views: Annotated[list[SelectedView], Field(max_length=3)]


@with_config(STRICT)
class ReportText(TypedDict):
    content: Text


@with_config(STRICT)
class Verification(TypedDict):
    accepted: bool
    reason: str


@with_config(STRICT)
class Condition(TypedDict):
    field: Text
    operator: Literal["eq", "ne", "lt", "le", "gt", "ge", "contains", "is_null"]
    value: Scalar


@with_config(STRICT)
class SortKey(TypedDict):
    field: Text
    descending: bool


@with_config(STRICT)
class QueryArguments(TypedDict):
    target: Text
    version: NotRequired[Text]
    as_of: NotRequired[Text]
    filters: NotRequired[list[Condition]]
    fields: NotRequired[Texts]
    sort: NotRequired[list[SortKey]]
    offset: NotRequired[Annotated[int, Field(ge=0)]]
    limit: NotRequired[Annotated[int, Field(ge=1, le=10_000)]]


@with_config(STRICT)
class Calculate(TypedDict):
    operation: Literal["calculate"]
    method: Literal["difference", "ratio", "percentage", "percent_change"]
    before: Text
    after: Text
    output: Text


@with_config(STRICT)
class Aggregate(TypedDict):
    operation: Literal["aggregate"]
    method: Literal["sum", "mean", "min", "max", "count"]
    field: Text
    output: Text
    group_by: list[Text]


@with_config(STRICT)
class Join(TypedDict):
    operation: Literal["join"]
    right_result_id: str
    keys: Texts
    how: Literal["inner", "left"]
    fields: Annotated[dict[Text, Text], Field(min_length=1)]


@with_config(STRICT)
class Filter(TypedDict):
    operation: Literal["filter"]
    conditions: list[Condition]


@with_config(STRICT)
class Cast(TypedDict):
    operation: Literal["cast"]
    field: Text
    kind: Literal["string", "integer", "number"]


@with_config(STRICT)
class Sort(TypedDict):
    operation: Literal["sort"]
    by: Annotated[list[SortKey], Field(min_length=1)]


Operation = Annotated[
    Calculate | Aggregate | Join | Filter | Cast | Sort,
    Field(discriminator="operation"),
]


@with_config(STRICT)
class ProcessArguments(TypedDict):
    input_result_id: str
    operations: Annotated[list[Operation], Field(min_length=1)]
    missing: NotRequired[Literal["error", "drop", "preserve"]]
    fields: NotRequired[Texts]
    decimals: NotRequired[Annotated[int, Field(ge=0, le=12)]]


@with_config(STRICT)
class VisualizationArguments(TypedDict):
    view_key: Text
    parameters: NotRequired[dict[Text, Text]]
    filters: NotRequired[dict[Text, Texts]]


@with_config(STRICT)
class AgentArguments(TypedDict):
    goal: str


ADAPTERS = {
    name: TypeAdapter(schema)
    for name, schema in {
        "interpret": Interpretation,
        "act": Selection,
        "decide": Decision,
        "compose": Composition,
        "ask": Question,
        "report_selection": ReportSelection,
        "report_text": ReportText,
        "verification": Verification,
        "query_data": QueryArguments,
        "process_data": ProcessArguments,
        "validate_visualization": VisualizationArguments,
        "interpretation_agent": AgentArguments,
        "visualization_agent": AgentArguments,
    }.items()
}


class FormatContract(TypedDict):
    actual_response_schema: JsonValue
    evaluation_response_schema: dict[str, JsonValue] | None
    structural_equal: bool | None
    differences: list[str]


SCHEMA_ANNOTATIONS = {
    "title",
    "description",
    "$comment",
    "default",
    "examples",
    "deprecated",
    "readOnly",
    "writeOnly",
}
SCHEMA_MAPS = {"properties", "patternProperties", "dependentSchemas"}
SCHEMA_VALUES = {
    "additionalProperties",
    "unevaluatedProperties",
    "propertyNames",
    "contains",
    "if",
    "then",
    "else",
    "not",
    "additionalItems",
    "unevaluatedItems",
    "contentSchema",
}
SCHEMA_ARRAYS = {"allOf", "anyOf", "oneOf", "prefixItems"}
SCHEMA_TYPES = {"null", "boolean", "object", "array", "number", "integer", "string"}
SCHEMA_COUNTS = {
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minProperties",
    "maxProperties",
    "minContains",
    "maxContains",
}


def _schema_pointer(path, token):
    return path + "/" + str(token).replace("~", "~0").replace("/", "~1")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _normalized_schema(schema):
    """로컬 참조를 펼치되 주석을 필드 이름·const 값에서 지우지 않는다."""

    def visit(value, path="", refs=()):
        if isinstance(value, bool):
            return value
        if not isinstance(value, dict):
            raise ValueError(path)
        result = {}
        for key, child in value.items():
            location = _schema_pointer(path, key)
            if key in SCHEMA_ANNOTATIONS or key in {"$defs", "definitions", "$ref"}:
                continue
            if key in {"$dynamicRef", "$recursiveRef"}:
                raise ValueError(location)
            if key == "type":
                types = child if isinstance(child, list) else [child]
                if not types or any(
                    not isinstance(t, str) or t not in SCHEMA_TYPES for t in types
                ):
                    raise ValueError(location)
            if key == "required" and (
                not isinstance(child, list)
                or any(not isinstance(item, str) for item in child)
            ):
                raise ValueError(location)
            if key == "enum" and (not isinstance(child, list) or not child):
                raise ValueError(location)
            if key in SCHEMA_COUNTS and (type(child) is not int or child < 0):
                raise ValueError(location)
            if key == "uniqueItems" and type(child) is not bool:
                raise ValueError(location)
            if key in {"pattern", "format", "$id", "$schema"} and not isinstance(
                child, str
            ):
                raise ValueError(location)
            if key in SCHEMA_MAPS:
                if not isinstance(child, dict):
                    raise ValueError(location)
                result[key] = {
                    name: visit(item, _schema_pointer(location, name), refs)
                    for name, item in child.items()
                }
            elif key in SCHEMA_VALUES or key == "items" and not isinstance(child, list):
                result[key] = visit(child, location, refs)
            elif key in SCHEMA_ARRAYS or key == "items":
                if not isinstance(child, list) or key in SCHEMA_ARRAYS and not child:
                    raise ValueError(location)
                items = [
                    visit(item, _schema_pointer(location, i), refs)
                    for i, item in enumerate(child)
                ]
                result[key] = (
                    sorted(items, key=_canonical)
                    if key in {"allOf", "anyOf", "oneOf"}
                    else items
                )
            elif key in {"required", "enum", "type"} and isinstance(child, list):
                result[key] = sorted(deepcopy(child), key=_canonical)
            else:
                result[key] = deepcopy(child)
        if "$ref" not in value:
            return result
        ref = value["$ref"]
        location = _schema_pointer(path, "$ref")
        if not isinstance(ref, str) or not ref.startswith("#/") or ref in refs:
            raise ValueError(location)
        target = schema
        for raw in ref[2:].split("/"):
            if re.search(r"~(?![01])", raw):
                raise ValueError(location)
            token = raw.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or token not in target:
                raise ValueError(location)
            target = target[token]
        expanded = visit(target, path, (*refs, ref))
        if not result:
            return expanded
        if isinstance(expanded, dict) and all(
            key not in expanded or expanded[key] == child
            for key, child in result.items()
        ):
            return {**expanded, **result}
        return {"allOf": sorted([expanded, result], key=_canonical)}

    return visit(schema)


def _schema_differences(actual, expected, path=""):
    if isinstance(actual, dict) and isinstance(expected, dict):
        differences = []
        for key in sorted(actual.keys() | expected.keys()):
            location = _schema_pointer(path, key)
            if key not in actual or key not in expected:
                differences.append(location)
            else:
                differences.extend(
                    _schema_differences(actual[key], expected[key], location)
                )
        return differences
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            return [path]
        return [
            location
            for index, (left, right) in enumerate(zip(actual, expected, strict=True))
            for location in _schema_differences(
                left, right, _schema_pointer(path, index)
            )
        ]
    return [] if type(actual) is type(expected) and actual == expected else [path]


def format_contract(context) -> FormatContract:
    """실제 응답 계약과 평가 계약의 구조 차이만 기록하며 출력 판정에 관여하지 않는다."""
    actual = context.get("call", {}).get("response_schema")
    adapter = ADAPTERS.get(_schema_key(context))
    expected = adapter.json_schema() if adapter is not None else None
    result: FormatContract = {
        "actual_response_schema": deepcopy(actual),
        "evaluation_response_schema": expected,
        "structural_equal": None,
        "differences": [],
    }
    for name, schema in (
        ("actual_response_schema", actual),
        ("evaluation_response_schema", expected),
    ):
        if not isinstance(schema, dict) or not schema:
            result["differences"].append("/" + name)
    if result["differences"]:
        return result
    normalized = []
    for name, schema in (
        ("actual_response_schema", actual),
        ("evaluation_response_schema", expected),
    ):
        try:
            normalized.append(_normalized_schema(schema))
        except (TypeError, ValueError, RecursionError) as exc:
            location = str(exc) if isinstance(exc, ValueError) else ""
            result["differences"].append("/" + name + location)
    if len(normalized) != 2:
        return result
    result["differences"] = _schema_differences(*normalized)
    result["structural_equal"] = not result["differences"]
    return result


def strict_json(raw: str):
    """중복 키·비유한 수·JSON 외부 문구를 허용하지 않는 원본 해석."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"중복 JSON 키: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"JSON에 허용되지 않는 수: {value}")

    def floating(value):
        number = float(value)
        if not isfinite(number):
            raise ValueError("JSON 수가 유한하지 않습니다.")
        return number

    if not isinstance(raw, str):
        raise ValueError("모델 원본 문자열이 없습니다.")
    return json.loads(
        raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating
    )


def message_texts(context):
    for message in context.get("call", {}).get("messages") or []:
        data = message.get("data", message) if isinstance(message, dict) else None
        content = data.get("content") if isinstance(data, dict) else None
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    yield block["text"]


def prompt_sections(context):
    """저장된 실제 프롬프트의 제목별 JSON과 보고서 입력을 읽는다."""
    sections = {}
    for text in message_texts(context):
        headers = list(re.finditer(r"(?m)^\[([^\]\r\n]+)\]\r?\n", text))
        if not headers:
            try:
                value = strict_json(text)
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict):
                sections.setdefault("보고서 입력", value)
            continue
        for index, header in enumerate(headers):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
            body = text[header.end() : end].strip()
            try:
                sections[header[1]] = strict_json(body)
            except (ValueError, TypeError):
                sections[header[1]] = body
    return sections


def visual_context(context, reference=None):
    """실행 당시 스냅샷만 사용하며 현재 등록 카탈로그를 조회하지 않는다."""
    sections = prompt_sections(context)
    for name in ("시각화 목록과 입력 조건", "시각화 선택 목록", "상세 뷰의 표현 범위"):
        value = sections.get(name)
        if isinstance(value, dict) and isinstance(value.get("views"), dict):
            return value, f"messages#[{name}]"
    if isinstance(reference, dict):
        value = reference.get("visualization")
        if isinstance(value, dict) and isinstance(value.get("views"), dict):
            return value, "reference#/visualization"
    return None, None


def detail(identity, verdict, reason, evidence=(), **values):
    return {
        "id": identity,
        "verdict": verdict,
        "reason": reason,
        "evidence": list(evidence),
        "executed": verdict in {"통과", "실패", "비적용"},
        **values,
    }


def sentence_count(text: str) -> int:
    """문장 종결 부호를 세며 소수·URL·목록 번호의 마침표는 제외한다."""
    text = re.sub(r"(?m)^\s*(?:[-*•]\s+|\d+[.)]\s+)", "", text).strip()
    text = re.sub(r"`[^`]*`", lambda m: m[0].replace(".", "·"), text)
    text = re.sub(
        r"https?://[^\s<>]+",
        lambda m: (
            re.sub(r"[.!?]", "·", m[0].rstrip(".!?")) + m[0][len(m[0].rstrip(".!?")) :]
        ),
        text,
    )
    text = re.sub(r"(?<=\d)\.(?=\d)", "·", text)
    text = re.sub(
        r"\b(?:e\.g|i\.e|Mr|Mrs|Ms|Dr|Prof)\.",
        lambda m: m[0].replace(".", "·"),
        text,
        flags=re.IGNORECASE,
    )
    count, start = 0, 0
    for match in re.finditer(r"[.!?。！？]+(?:[\"'”’」』])?", text):
        if match[0][-1:] in {'"', "'", "”", "’", "」", "』"} and re.match(
            r"(?:라고|라는|라며|라니|하고|하며|하는)", text[match.end() :]
        ):
            continue
        if re.search(r"\w", text[start : match.start()]):
            count += 1
        start = match.end()
    if re.search(r"\w", text[start:]):
        count += 1
    return count


def _schema_key(context):
    node, role = context.get("node"), context.get("role")
    call = context.get("call", {})
    if node != "compose":
        return node
    schema = call.get("response_schema") or {}
    title = schema.get("title", "") if isinstance(schema, dict) else ""
    names = {call.get("name"), title}
    if names & {
        "Verification",
        "verification",
        "selection_review",
        "draft_review",
        "review_retry",
    }:
        return "verification"
    if role == "report_selection" or "ReportSelection" in names:
        return "report_selection"
    if role in {"report_description", "report_insight"} or "ReportText" in names:
        return "report_text"
    return "compose"


def _validation(identity, adapter, value, evidence):
    try:
        adapter.validate_python(value, strict=True)
    except ValidationError as exc:
        errors = [
            {"path": "/" + "/".join(map(str, error["loc"])), "type": error["type"]}
            for error in exc.errors(include_input=False, include_url=False)
        ]
        return detail(
            identity,
            "실패",
            "필수 필드·자료형·허용값·추가 필드 기준 위반입니다.",
            evidence,
            actual=errors,
        )
    return detail(identity, "통과", "문서의 필드·자료형·허용값을 충족합니다.", evidence)


def _profile_format(arguments, context, reference):
    identity = "visualization-profile"
    catalog, source = visual_context(context, reference)
    if catalog is None:
        return detail(identity, "미판정", "실행 당시 뷰·입력 프로필 근거가 없습니다.")
    view = catalog["views"].get(arguments["view_key"])
    if not isinstance(view, dict):
        return detail(
            identity,
            "미판정",
            "선택한 뷰의 입력 프로필을 확인할 수 없습니다.",
            [source],
        )
    name = view.get("input_profile")
    profiles = catalog.get("input_profiles", {})
    profile = profiles.get(name) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        # 문서의 두 프로필은 스냅샷이 뷰와 프로필의 연결을 확인한 경우에만 적용한다.
        if name == "monthly_city":
            profile = {
                "parameters": {
                    "p_city": {"data_type": "string"},
                    "p_start": {"data_type": "date"},
                    "p_end": {"data_type": "date"},
                },
                "filters": {"읍면동": {}},
            }
        elif name == "monthly_detail":
            profile = {
                "parameters": {
                    "p_detail_adm": {"data_type": "string"},
                    "p_start": {"data_type": "date"},
                    "p_end": {"data_type": "date"},
                },
                "filters": {},
            }
        else:
            return detail(
                identity,
                "미판정",
                "해당 프로필의 필수 이름·자료형이 없습니다.",
                [source],
            )
    definitions, filters = profile.get("parameters"), profile.get("filters")
    if not isinstance(definitions, dict) or not isinstance(filters, dict):
        return detail(
            identity, "미판정", "프로필의 매개변수·필터 정의가 부족합니다.", [source]
        )
    values = arguments.get("parameters", {})
    failures = []
    if set(values) != set(definitions):
        failures.append("매개변수 이름·필수 항목 불일치")
    if set(arguments.get("filters", {})) - set(filters):
        failures.append("프로필에 없는 필터")
    for key, definition in definitions.items():
        if key not in values:
            continue
        kind = definition.get("data_type") if isinstance(definition, dict) else None
        if kind == "date":
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[key]):
                    raise ValueError
                date.fromisoformat(values[key])
            except (ValueError, TypeError):
                failures.append(f"{key}: 유효한 YYYY-MM-DD 날짜가 아님")
        elif kind != "string":
            return detail(
                identity, "미판정", f"{key}의 지원 자료형 근거가 없습니다.", [source]
            )
    return detail(
        identity,
        "실패" if failures else "통과",
        "; ".join(failures) if failures else "프로필의 이름·자료형을 충족합니다.",
        [source],
    )


def evaluate_format(context, reference=None):
    call = context.get("call", {})
    evidence = [call.get("path") or "model-response#raw"]
    raw = call.get("raw")
    if not isinstance(raw, str):
        return [
            detail(
                "raw-json",
                "미판정",
                "형식을 확인할 모델 원본 본문이 없습니다.",
                evidence,
            )
        ]
    try:
        value = strict_json(raw)
        if not isinstance(value, dict):
            raise ValueError("반환값은 JSON 객체 하나여야 합니다.")
    except (ValueError, TypeError) as exc:
        return [detail("raw-json", "실패", str(exc), evidence)]
    result = [
        detail("raw-json", "통과", "원본은 해석 가능한 JSON 객체 하나입니다.", evidence)
    ]
    key = _schema_key(context)
    if key not in ADAPTERS:
        return result + [
            detail("structure", "미판정", "노드·역할의 출력 형식을 특정할 수 없습니다.")
        ]
    structure = _validation("structure", ADAPTERS[key], value, evidence)
    result.append(structure)
    if structure["verdict"] != "통과":
        return result
    if key == "act":
        try:
            args = strict_json(value["arguments_json"])
            if not isinstance(args, dict):
                raise ValueError("호출 인자는 JSON 객체여야 합니다.")
        except (ValueError, TypeError) as exc:
            return result + [detail("arguments", "실패", str(exc), evidence)]
        item = _validation("arguments", ADAPTERS[value["name"]], args, evidence)
        result.append(item)
        if item["verdict"] == "통과" and value["name"] == "validate_visualization":
            result.append(_profile_format(args, context, reference))
    elif key == "report_text":
        if context.get("role") not in {"report_description", "report_insight"}:
            return result + [
                detail(
                    "length",
                    "미판정",
                    "설명·인사이트 역할을 확인할 수 없어 분량 기준을 고를 수 없습니다.",
                )
            ]
        format_reference = (
            reference.get("format", {}) if isinstance(reference, dict) else {}
        )
        completed = (
            format_reference.get("completed")
            if isinstance(format_reference, dict)
            else None
        )
        if type(completed) is not bool:
            result.append(
                detail(
                    "length",
                    "미판정",
                    "완성본·미완성 안내의 분량 적용 여부가 평가 기준에 없습니다.",
                )
            )
        elif not completed:
            result.append(
                detail(
                    "length",
                    "비적용",
                    "미완성 안내에는 완성본 분량을 적용하지 않습니다.",
                    ["reference#/format/completed"],
                )
            )
        else:
            content = value["content"].strip()
            if context.get("role") == "report_description":
                paragraphs = len(re.split(r"\n\s*\n", content))
                sentences = sentence_count(content)
                valid = paragraphs == 1 and 1 <= sentences <= 3
                actual = {"paragraphs": paragraphs, "sentences": sentences}
                reason = "설명은 한 단락·최대 3문장이어야 합니다."
            else:
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                counts = [sentence_count(line) for line in lines]
                valid = 3 <= len(lines) <= 4 and all(count == 1 for count in counts)
                actual = {"items": len(lines), "sentences": counts}
                reason = "인사이트는 줄바꿈한 3~4항목이며 항목당 한 문장이어야 합니다."
            result.append(
                detail(
                    "length",
                    "통과" if valid else "실패",
                    reason,
                    evidence + ["reference#/format/completed"],
                    actual=actual,
                )
            )
    return result
