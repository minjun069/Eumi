"""업무 State와 분리된 노드 평가 기대 항목과 결과 계약."""

import json
import re
from typing import Annotated, Literal, NotRequired

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    with_config,
)
from typing_extensions import TypedDict

from eval.tools.assessment import NumericTolerance, Verdict
from src.prompting import Role

Node = Literal["interpret", "act", "decide", "compose", "ask"]
Text = Annotated[str, Field(min_length=1)]
PositiveInt = Annotated[int, Field(ge=1, strict=True)]
Pointer = Annotated[str, Field(pattern=r"^(?:/(?:[^~]|~[01])*)*$")]


@with_config(ConfigDict(extra="forbid", strict=True))
class InputSelection(TypedDict):
    source: Literal["messages", "state", "output", "reference"]
    path: Pointer
    label: NotRequired[Text]


@with_config(ConfigDict(extra="forbid", strict=True))
class NodeExpectation(TypedDict):
    id: Text
    check: Text
    row_id: NotRequired[Text]
    node: NotRequired[Node]
    role: NotRequired[Role]
    occurrence: NotRequired[PositiveInt]
    call: NotRequired[Text]
    call_index: NotRequired[PositiveInt]
    path: NotRequired[Pointer]
    value: NotRequired[JsonValue]
    match: NotRequired[Literal["equal", "subset", "present", "absent"]]
    pattern: NotRequired[Text]
    extract: NotRequired[Literal["number", "text"]]
    tolerance: NotRequired[NumericTolerance]
    applicable: NotRequired[bool]
    reason: NotRequired[Text]
    inputs: NotRequired[list[InputSelection]]


def _expectation(item: NodeExpectation) -> NodeExpectation:
    if not item["id"].strip() or not item["check"].strip():
        raise ValueError("노드 기대 항목의 ID와 검사 ID는 공백일 수 없습니다")
    if item.get("applicable") is False and not item.get("reason", "").strip():
        raise ValueError("비적용 항목은 사유가 필요합니다")
    if "pattern" in item:
        try:
            pattern = re.compile(item["pattern"])
        except re.error as exc:
            raise ValueError("기대 항목의 정규식이 잘못되었습니다") from exc
        if pattern.groups > 1:
            raise ValueError("추출 정규식은 캡처 그룹을 최대 하나만 사용합니다")
    return item


@with_config(ConfigDict(extra="forbid", strict=True))
class NodeExpectations(TypedDict):
    schema_version: Literal["node-expectations-v1"]
    items: list[Annotated[NodeExpectation, AfterValidator(_expectation)]]


node_expectations_adapter = TypeAdapter(NodeExpectations)


class ScopeCall(TypedDict):
    id: str
    name: str
    index: int
    path: str


class CaseScopeEvidence(TypedDict):
    case_id: str
    repetition: int
    node: Node
    role: Role | None
    occurrence: int
    calls: list[ScopeCall]


def case_model_name(case: dict, nodes=None) -> str | None:
    """단독 실행의 명시한 호출을 우선하고 보고서 기본 호출은 실제 원문에서 읽는다."""
    if case.get("unit") not in {"node", "selection"}:
        return None
    target = case.get("target")
    if target != "compose":
        return {
            "interpret": "Interpretation",
            "act": "Selection",
            "decide": "Decision",
            "ask": "Question",
        }.get(target)
    if not str(case.get("role", "")).startswith("report_"):
        return "Composition"
    stage = case.get("model_call")
    if stage is not None:
        return {
            "selection": "ReportSelection",
            "draft": "ReportText",
            "selection_review": "Verification",
            "draft_review": "Verification",
            "review_retry": "Verification",
        }.get(stage)
    for node in nodes or []:
        if (
            node["node"] == target
            and node.get("role") == case.get("role")
            and node.get("occurrence") == 1
        ):
            return next(
                (
                    call["name"]
                    for index, call in enumerate(node.get("calls", []), 1)
                    if call.get("index", index) == 1
                ),
                None,
            )
    return None


def case_expectations(case: dict, nodes=None, *, row_ids=None) -> list[NodeExpectation]:
    expected = case.get("assessment", {}).get("expected", {})
    if (
        not isinstance(expected, dict)
        or expected.get("schema_version") != "node-expectations-v1"
    ):
        return []
    items = expected["items"]
    if row_ids is not None:
        checks = {row_id.partition("/")[0] for row_id in row_ids}
        items = [
            item
            for item in items
            if item["check"] in checks
            and ("row_id" not in item or item["row_id"] in row_ids)
        ]
    if case.get("unit") not in {"node", "selection"}:
        return items
    scope = {
        "node": case["target"],
        "role": case["role"],
        "occurrence": 1,
        "call_index": 1,
    }
    name = case_model_name(case, nodes)
    if name is not None:
        scope["call"] = name
    return [
        item
        for item in items
        if all(key not in item or item[key] == value for key, value in scope.items())
    ]


def case_matches(case, node, call=None, index=None, *, nodes=None):
    if case.get("unit") not in {"node", "selection"}:
        return True
    if (
        node["node"] != case.get("target")
        or node.get("role") != case.get("role")
        or node.get("occurrence") != 1
    ):
        return False
    if call is None:
        return True
    name = case_model_name(case, [node] if nodes is None else nodes)
    return call.get("index", index) == 1 and (name is None or call["name"] == name)


def requested_checks(case: dict, nodes=None, *, row_ids=None) -> set[str]:
    """명시한 검사 목록을 우선하고, 없으면 기대 항목의 검사만 선택한다."""
    assessment = case.get("assessment", {})
    expected = assessment.get("expected", {})
    original = set()
    if (
        isinstance(expected, dict)
        and expected.get("schema_version") == "node-expectations-v1"
    ):
        original = {item["check"] for item in expected["items"]}
    selected = {
        item["check"] for item in case_expectations(case, nodes, row_ids=row_ids)
    }
    if "checks" in assessment:
        selected = set(assessment["checks"]) - (original - selected)
    if row_ids is not None:
        selected &= {row_id.partition("/")[0] for row_id in row_ids}
    return selected


def expectation_matches(item, node, call=None, index=None, *, row_id=None):
    """원본 노드 발생 순서와 모델 호출 순서로 명시한 평가 범위를 비교한다."""
    if any(
        key in item and item[key] != node.get(key)
        for key in ("node", "role", "occurrence")
    ):
        return False
    if row_id is not None and item.get("row_id", row_id) != row_id:
        return False
    if call is not None:
        return ("call" not in item or item["call"] == call["name"]) and (
            "call_index" not in item or item["call_index"] == call.get("index", index)
        )
    return True


def validate_node_assessment(assessment: dict) -> None:
    """기존 자유 형식은 보존하되 명시한 노드 기대값은 잘못된 채점을 막는다."""
    expected = assessment.get("expected")
    if (
        not isinstance(expected, dict)
        or expected.get("schema_version") != "node-expectations-v1"
    ):
        return
    from eval.nodes.criteria import load_criteria

    expectations = node_expectations_adapter.validate_python(expected)
    json.dumps(expectations, allow_nan=False)
    ids = [item["id"] for item in expectations["items"]]
    if len(ids) != len(set(ids)):
        raise ValueError("노드 기대 항목 ID가 중복되었습니다")
    checks = assessment.get("checks", [])
    if len(checks) != len(set(checks)):
        raise ValueError("노드 검사 ID가 중복되었습니다")
    catalog = load_criteria()["checks"]
    if set(checks) - catalog.keys():
        raise ValueError("평가 문서에 없는 노드 검사 ID입니다")
    for item in expectations["items"]:
        if item["check"] not in catalog:
            raise ValueError("기대 항목은 평가 정의의 검사 ID에 연결되어야 합니다")
        if "row_id" in item and item["row_id"] not in {
            row["row_id"] for row in catalog[item["check"]]["rows"]
        }:
            raise ValueError("기대 항목의 row_id는 해당 검사의 평가 행이어야 합니다")
        if "node" in item and item["node"] not in catalog[item["check"]]["nodes"]:
            raise ValueError("기대 항목의 검사와 노드 범위가 다릅니다")


class DetailResult(TypedDict):
    id: str
    verdict: Verdict
    reason: str
    evidence: list[str]
    executed: bool
    actual: NotRequired[JsonValue]
    expected: NotRequired[JsonValue]


class CallAssessment(TypedDict):
    id: str
    name: str
    index: int
    row_id: NotRequired[str]
    details: list[DetailResult]
    judge: NotRequired[dict[str, JsonValue]]
    format_contract: NotRequired[dict[str, JsonValue]]


class NodeCheckResult(TypedDict):
    check: str
    axis: str
    method: str
    executed: bool
    verdict: Verdict
    reason: str
    details: list[DetailResult]
    calls: list[CallAssessment]
    related_checks: list[str]  # 저장 결과·뷰어 형식 유지용. 현재는 빈 목록이다.


class NodeAssessment(TypedDict):
    node_id: str
    run_id: str | None
    case_id: str
    repetition: int
    node: Node
    role: Role | None
    counted: bool
    verdict: Verdict
    complete: bool
    checks: list[NodeCheckResult]
    reason: str


@with_config(ConfigDict(extra="forbid", strict=True))
class NodePerformanceTarget(TypedDict):
    target: Node
    role: Role
    metric: Literal["response_time", "failure_rate"]
    case_ids: Annotated[list[Text], Field(min_length=1)]
    group: NotRequired[Literal["normal", "error"]]
    statistic: NotRequired[Literal["median", "p95"]]
    max_seconds: NotRequired[Annotated[float, Field(ge=0, allow_inf_nan=False)]]
    max_rate: NotRequired[Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]]
    environment: NotRequired[Text]
    data_size: NotRequired[Text]
