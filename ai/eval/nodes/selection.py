"""저장 사례의 선언과 JSON 적용 조건을 교차해 채점할 범위를 정한다."""

from copy import deepcopy
from typing import Literal

from typing_extensions import TypedDict

from eval.nodes.criteria import CriteriaCatalog, select_rows
from eval.nodes.schema import (
    case_expectations,
    case_matches,
    case_model_name,
    expectation_matches,
    requested_checks,
)
from eval.schema import Case


class EvaluationFilter(TypedDict):
    case_ids: list[str] | None
    check_ids: list[str] | None
    row_ids: list[str] | None


class SelectionDecision(TypedDict):
    case_id: str
    repetition: int | None
    check: str | None
    expectation_id: str | None
    status: Literal["selected", "undetermined", "excluded"]
    reason: str
    row_ids: list[str]


class RunCase(TypedDict):
    case: Case
    repetition: int


def evaluation_filter(cases, catalog, *, case_ids=None, check_ids=None, row_ids=None):
    """선택 ID를 전체 정의와 대조한다. 사례 선언에 없는 검사를 추가하지 않는다."""
    available_cases = {case["id"] for case in cases}
    rows = {
        row["row_id"]: definition["id"]
        for definition in catalog["checks"].values()
        for row in definition["rows"]
    }
    result: EvaluationFilter = {}
    for name, values, available in (
        ("case_ids", case_ids, available_cases),
        ("check_ids", check_ids, catalog["checks"]),
        ("row_ids", row_ids, rows),
    ):
        selected = None if values is None else sorted(set(values))
        if selected is not None:
            if not selected:
                raise ValueError(f"{name}: 선택 ID를 하나 이상 지정해야 합니다")
            unknown = set(selected) - set(available)
            if unknown:
                raise ValueError(
                    f"{name}: 정의 또는 실행 계획에 없는 ID: {sorted(unknown)}"
                )
        result[name] = selected
    if check_ids is not None and row_ids is not None:
        if any(rows[identity] not in check_ids for identity in row_ids):
            raise ValueError("선택한 행은 --check로 지정한 검사에 속해야 합니다")
    return result


def _copy_case(case, checks, items):
    value = deepcopy(case)
    assessment = value.setdefault("assessment", {})
    assessment["checks"] = sorted(checks)
    expected = assessment.get("expected")
    if (
        isinstance(expected, dict)
        and expected.get("schema_version") == "node-expectations-v1"
    ):
        expected["items"] = deepcopy(items)
    return value


def candidate_cases(cases, catalog, filters):
    """요청한 ID와 사례의 적용 검사 선언을 교차한다. 원본 입력은 유지한다."""
    row_checks = {
        definition["id"]
        for definition in catalog["checks"].values()
        if any(
            row["row_id"] in (filters["row_ids"] or []) for row in definition["rows"]
        )
    }
    selected, decisions = [], []
    for case in cases:
        checks = requested_checks(case)
        if filters["check_ids"] is not None:
            checks &= set(filters["check_ids"])
        if filters["row_ids"] is not None:
            checks &= row_checks
        items = [
            item
            for item in case_expectations(case)
            if item["check"] in checks
            and (
                filters["row_ids"] is None
                or "row_id" not in item
                or item["row_id"] in filters["row_ids"]
            )
        ]
        original_items = case_expectations(case)
        checks -= {
            check
            for check in checks
            if any(item["check"] == check for item in original_items)
            and not any(item["check"] == check for item in items)
        }
        reason = None
        if filters["case_ids"] is not None and case["id"] not in filters["case_ids"]:
            reason = "지정한 사례 범위 밖입니다."
        elif not checks:
            reason = (
                "사례에 선언한 검사·기대 항목과 지정한 평가 범위의 교집합이 없습니다."
            )
        if reason:
            decisions.append(
                SelectionDecision(
                    case_id=case["id"],
                    repetition=None,
                    check=None,
                    expectation_id=None,
                    status="excluded",
                    reason=reason,
                    row_ids=[],
                )
            )
        else:
            if unknown := checks - catalog["checks"].keys():
                raise ValueError(
                    f"{case['id']}: 평가 정의에 없는 요청 검사: {sorted(unknown)}"
                )
            selected.append(_copy_case(case, checks, items))
    return selected, decisions


def _contexts(case, nodes, item):
    return [
        (node, call)
        for node in nodes
        if case_matches(case, node) and expectation_matches(item, node)
        for index, call in enumerate(node.get("calls", []), 1)
        if case_matches(case, node, call, index, nodes=nodes)
        and expectation_matches(item, node, call, index)
    ]


def _missing_context(case, item):
    """실행 증거가 없으면 선언으로 배제할 수 있는 범위만 확인한다."""
    node = {
        "node": item.get(
            "node",
            case.get("target") if case["unit"] in {"node", "selection"} else None,
        ),
        "role": item.get(
            "role",
            case.get("role", case.get("target") if case["unit"] == "agent" else None),
        ),
    }
    return node, {"name": item.get("call", case_model_name(case))}


def plan_case(
    case: Case, nodes, catalog: CriteriaCatalog, repetition: int, *, row_ids=None
):
    """한 반복의 실제 맥락으로 행을 고른다. 증거 부족은 제외하지 않고 보류한다."""
    checks = requested_checks(case, nodes)
    items = case_expectations(case, nodes)
    included_checks, included_items, decisions = set(), [], []
    if not checks:
        decisions.append(
            SelectionDecision(
                case_id=case["id"],
                repetition=repetition,
                check=None,
                expectation_id=None,
                status="excluded",
                reason="현재 독립 호출 범위에 적용할 요청 검사·기대 항목이 없습니다.",
                row_ids=[],
            )
        )
    for identifier in sorted(checks):
        definition = catalog["checks"][identifier]
        expectations = [item for item in items if item["check"] == identifier]
        for item in expectations or [{}]:
            contexts = [
                (node, call)
                for node, call in _contexts(case, nodes, item)
                if node.get("node") in definition["nodes"]
            ]
            missing_call = not contexts
            contexts = contexts or [_missing_context(case, item)]
            selected_rows, missing = set(), []
            for node, call in contexts:
                selection = select_rows(definition, node, call, row_ids=row_ids)
                missing.extend(selection["missing_context"])
                selected_rows.update(
                    row["row_id"]
                    for row in selection["rows"]
                    if "row_id" not in item or row["row_id"] == item["row_id"]
                )
            if missing or (missing_call and selected_rows):
                status, reason = (
                    "undetermined",
                    "적용 조건을 확인할 실행 증거가 부족하거나 모호합니다.",
                )
                if missing:
                    reason += " " + "; ".join(sorted(set(missing)))
            elif selected_rows:
                status, reason = (
                    "selected",
                    "사례의 범위와 JSON 적용 조건이 일치합니다.",
                )
            else:
                status, reason = (
                    "excluded",
                    "현재 노드·역할·호출·도구에 지정한 평가 행이 적용되지 않습니다.",
                )
            if status != "excluded":
                included_checks.add(identifier)
                if item:
                    included_items.append(item)
            decisions.append(
                SelectionDecision(
                    case_id=case["id"],
                    repetition=repetition,
                    check=identifier,
                    expectation_id=item.get("id"),
                    status=status,
                    reason=reason,
                    row_ids=sorted(selected_rows),
                )
            )
    return _copy_case(case, included_checks, included_items), decisions


def aggregate_cases(candidates, run_cases):
    """집계 대상 사례에는 선택된 반복들의 검사·기대 항목만 남긴다."""
    result = []
    for case in candidates:
        runs = [run["case"] for run in run_cases if run["case"]["id"] == case["id"]]
        checks = set().union(*(requested_checks(run) for run in runs))
        if not checks:
            continue
        items = {item["id"]: item for run in runs for item in case_expectations(run)}
        result.append(_copy_case(case, checks, list(items.values())))
    return result
