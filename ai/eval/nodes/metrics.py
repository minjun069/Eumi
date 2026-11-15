"""노드 판정과 원본 호출 증거를 역할별로 집계한다. 평가용 호출은 포함하지 않는다."""

from collections import defaultdict
from copy import deepcopy
from math import ceil, isfinite
from statistics import mean, median
from typing import Literal

from typing_extensions import TypedDict

from eval.nodes.criteria import load_criteria, select_rows
from eval.nodes.evidence import CALL_KINDS, NODES, ObservedUsage
from eval.nodes.schema import (
    CaseScopeEvidence,
    case_expectations,
    expectation_matches,
    requested_checks,
)
from eval.nodes.selection import RunCase


class Statistics(TypedDict):
    sample_count: int
    missing_count: int
    unfinished_count: int
    mean: float | None
    median: float | None
    p95: float | None


class RateSummary(TypedDict):
    numerator: int
    denominator: int
    rate: float | None
    passed: int
    failed: int
    undetermined: int
    not_applicable: int
    unexecuted: int
    skipped_after_failure: int


class CheckSummary(RateSummary):
    check: str
    axis: str
    method: str


class DetailSummary(RateSummary):
    check: str
    id: str


class MissingExpectation(TypedDict):
    repetition: int
    id: str


class MissingCheck(TypedDict):
    repetition: int
    check: str


class CaseSummary(TypedDict):
    case_id: str
    required: bool | None
    verdict: str
    complete: bool
    planned_repetitions: int
    recorded_repetitions: int
    missing_repetitions: list[int]
    incomplete_repetitions: list[int]
    excluded_repetitions: list[int]
    missing_expectations: list[MissingExpectation]
    missing_checks: list[MissingCheck]
    reason: str


class CaseTotals(TypedDict):
    numerator: int
    denominator: int
    rate: float | None
    passed: int
    failed: int
    undetermined: int
    excluded: int
    unspecified_required: int
    items: list[CaseSummary]


class VerificationSummary(TypedDict):
    required_cases: int
    completed_cases: int
    incomplete_cases: int
    missing_repetitions: int


class FunctionalSummary(TypedDict):
    verdict: str
    complete: bool
    checks: list[CheckSummary]
    details: list[DetailSummary]
    cases: CaseTotals
    verification: VerificationSummary


class FailureRate(TypedDict):
    numerator: int
    denominator: int
    rate: float | None
    missing_count: int
    unfinished_count: int


class TimingSummary(TypedDict):
    normal: Statistics
    error: Statistics
    unclassified_count: int
    unfinished_count: int


class TokenSummary(TypedDict):
    input_tokens: Statistics
    output_tokens: Statistics


class RetrySummary(TypedDict):
    model: Statistics
    tool: Statistics
    agent: Statistics


class UnfinishedUsage(ObservedUsage):
    node_id: str
    run_id: str | None
    case_id: str
    repetition: int


class OperationalSummary(TypedDict):
    measurement_scope: Literal["selected_model_calls"]
    failure_rate: FailureRate
    response_time: TimingSummary
    tokens: TokenSummary
    model_calls: Statistics
    technical_retries: Statistics
    technical_retries_by_kind: RetrySummary
    unfinished_usage: list[UnfinishedUsage]
    verdict: str
    complete: bool


class PerformanceSummary(TypedDict):
    metric: str
    group: str | None
    statistic: str | None
    case_ids: list[str]
    max_seconds: float | None
    max_rate: float | None
    value_seconds: float | None
    value_rate: float | None
    sample_count: int
    complete: bool
    verdict: str
    reasons: list[str]


class NodeSummary(TypedDict):
    node: str
    role: str | None
    runs: int
    functional: FunctionalSummary
    operational: OperationalSummary
    performance: list[PerformanceSummary]
    complete: bool
    verdict: str
    verdict_scope: str
    conflicting_assessments: list[list[str | None]]
    conflicting_evidence: list[list[str | None]]


def _number(value):
    try:
        return type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError:
        return False


def _statistics(values, *, missing=0, unfinished=0) -> Statistics:
    ordered = sorted(values)
    return {
        "sample_count": len(ordered),
        "missing_count": missing,
        "unfinished_count": unfinished,
        "mean": mean(ordered) if ordered else None,
        "median": median(ordered) if ordered else None,
        "p95": ordered[ceil(0.95 * len(ordered)) - 1] if ordered else None,
    }


def _identity(value):
    return value.get("run_id"), value.get("node_id", value.get("id"))


def _deduplicate(values):
    groups = defaultdict(list)
    for value in values:
        group = groups[_identity(value)]
        if value not in group:
            group.append(value)
    unique, conflicts = [], []
    for key, group in groups.items():
        if len(group) == 1:
            unique.append(group[0])
        else:
            conflicts.append(key)
            item = dict(group[0])
            item.update(
                complete=False,
                status="unknown",
                technical_failure=None,
                elapsed_seconds=None,
                usage={},
                model_calls=None,
                technical_retries=None,
                technical_retries_by_kind=dict.fromkeys(CALL_KINDS),
                observed_usage=None,
            )
            if "verdict" in item:
                item["verdict"] = (
                    "실패"
                    if any(g.get("verdict") == "실패" for g in group)
                    else "미판정"
                )
                item["checks"] = []
            item["issues"] = ["동일 노드 실행의 기록이 충돌합니다."]
            unique.append(item)
    return unique, conflicts


def _rate(items) -> RateSummary:
    counts = {"통과": 0, "실패": 0, "미판정": 0, "비적용": 0}
    unexecuted = skipped = 0
    for item in items:
        if not item.get("executed", False):
            unexecuted += 1
            skipped += "선행 단계 실패" in item.get("reason", "")
            continue
        verdict = item.get("verdict", "미판정")
        counts[verdict if verdict in counts else "미판정"] += 1
    denominator = counts["통과"] + counts["실패"]
    return {
        "numerator": counts["통과"],
        "denominator": denominator,
        "rate": counts["통과"] / denominator if denominator else None,
        "passed": counts["통과"],
        "failed": counts["실패"],
        "undetermined": counts["미판정"],
        "not_applicable": counts["비적용"],
        "unexecuted": unexecuted,
        "skipped_after_failure": skipped,
    }


def _scope_context(case, evidences, scope_evidence, repetition=None):
    def matches(node):
        return node["case_id"] == case["id"] and (
            repetition is None or node["repetition"] == repetition
        )

    scoped = [n for n in scope_evidence or [] if matches(n)]
    return scoped or [n for n in evidences or [] if matches(n)]


def _group_requested(case, node, role, context, catalog, row_ids):
    """명시한 다른 노드·역할만 제외하며 범위가 없는 검사는 임의로 배제하지 않는다."""
    items = case_expectations(case, context, row_ids=row_ids)
    selected = set()
    for identifier in requested_checks(case, context, row_ids=row_ids):
        definition = catalog["checks"].get(identifier)
        if definition is not None and node not in definition["nodes"]:
            continue
        expected = [item for item in items if item["check"] == identifier]
        if not expected or any(
            item.get("node", node) == node and item.get("role", role) == role
            for item in expected
        ):
            selected.add(identifier)
    return selected


def _check_summaries(cases, assessments, evidences, scope_evidence, plan, row_ids):
    checks, details = defaultdict(list), defaultdict(list)
    case_by_id = {case["id"]: case for case in cases}
    for assessment in assessments:
        repetition = assessment["repetition"]
        case = plan.get(
            (assessment["case_id"], repetition), case_by_id[assessment["case_id"]]
        )
        requested = requested_checks(
            case,
            _scope_context(case, evidences, scope_evidence, repetition),
            row_ids=row_ids,
        )
        seen_checks, seen_details = set(), set()
        for check in assessment.get("checks", []):
            check_id = check.get("check")
            if check_id not in requested:
                continue
            key = (check_id, check.get("axis"), check.get("method"))
            if check_id in seen_checks:
                continue
            seen_checks.add(check_id)
            checks[key].append(check)
            for detail in check.get("details", []):
                detail_id = detail.get("id")
                if (check_id, detail_id) in seen_details:
                    continue
                seen_details.add((check_id, detail_id))
                details[(check_id, detail_id)].append(detail)
    return (
        [
            {"check": key[0], "axis": key[1], "method": key[2], **_rate(items)}
            for key, items in sorted(checks.items(), key=lambda pair: str(pair[0]))
        ],
        [
            {"check": key[0], "id": key[1], **_rate(items)}
            for key, items in sorted(details.items(), key=lambda pair: str(pair[0]))
        ],
    )


def _expectations(
    case, evidences=None, scope_evidence=None, *, repetition=None, row_ids=None
):
    nodes = _scope_context(case, evidences, scope_evidence, repetition)
    requested = requested_checks(case, nodes, row_ids=row_ids)
    return [
        item
        for item in case_expectations(case, nodes, row_ids=row_ids)
        if item.get("check") in requested
    ]


def _planned_groups(case, known, evidences=None, scope_evidence=None, *, row_ids=None):
    groups = set()
    for item in _expectations(case, evidences, scope_evidence, row_ids=row_ids):
        node = item.get(
            "node", case.get("target") if case.get("unit") == "node" else None
        )
        role = item.get(
            "role",
            case.get(
                "role", case.get("target") if case.get("unit") == "agent" else None
            ),
        )
        if node not in NODES:
            continue
        if case.get("unit") == "node" and (node, role) != (
            case["target"],
            case.get("role"),
        ):
            continue
        if role is None:
            groups.update({g for g in known if g[0] == node} or {(node, None)})
        else:
            groups.add((node, role))
    return groups


def _matches(item, evidence, catalog, row_ids):
    if not expectation_matches(item, evidence):
        return False
    if "row_id" in item or row_ids is not None:
        definition = catalog["checks"].get(item["check"])
        return definition is not None and any(
            expectation_matches(item, evidence, call, index, row_id=row["row_id"])
            for index, call in enumerate(evidence.get("calls", []), 1)
            for row in select_rows(definition, evidence, call, row_ids=row_ids)["rows"]
        )
    if "call" in item or "call_index" in item:
        return any(
            expectation_matches(item, evidence, call, index)
            for index, call in enumerate(evidence.get("calls", []), 1)
        )
    return True


def _case_summary(
    case,
    repeat,
    assessments,
    evidences,
    node,
    role,
    scope_evidence,
    plan,
    catalog,
    row_ids,
    all_assessments,
) -> CaseSummary:
    selected = [a for a in assessments if a.get("case_id") == case["id"]]
    required = case.get("assessment", {}).get("required")
    missing, incomplete, excluded = [], [], []
    missing_expectations = []
    missing_checks = []
    failed = False
    all_passed = True
    for repetition in range(1, repeat + 1):
        current_case = plan.get((case["id"], repetition), case)
        context = _scope_context(current_case, evidences, scope_evidence, repetition)
        requested = requested_checks(current_case, context, row_ids=row_ids)
        if not _group_requested(current_case, node, role, context, catalog, row_ids):
            excluded.append(repetition)
            continue
        recorded_checks = {
            check["check"]
            for assessment in all_assessments
            if assessment["case_id"] == case["id"]
            and assessment["repetition"] == repetition
            for check in assessment.get("checks", [])
        }
        missing_checks.extend(
            {"repetition": repetition, "check": identifier}
            for identifier in sorted(requested - recorded_checks)
        )
        if requested - recorded_checks:
            incomplete.append(repetition)
            all_passed = False
        scopes = [
            item
            for item in _expectations(
                current_case,
                evidences,
                scope_evidence,
                repetition=repetition,
                row_ids=row_ids,
            )
            if item.get("node", node) == node and item.get("role", role) == role
        ]
        current = [a for a in selected if a.get("repetition") == repetition]
        failed |= any(a.get("verdict") == "실패" for a in current)
        if not current:
            missing.append(repetition)
            if repetition not in incomplete:
                incomplete.append(repetition)
            all_passed = False
            continue
        current_evidence = [
            e
            for e in evidences
            if e.get("case_id") == case["id"] and e.get("repetition") == repetition
        ]
        for item in scopes:
            if not any(
                _matches(item, evidence, catalog, row_ids)
                for evidence in current_evidence
            ):
                missing_expectations.append(
                    {"repetition": repetition, "id": item["id"]}
                )
                if repetition not in incomplete:
                    incomplete.append(repetition)
                all_passed = False
        if any(not a.get("complete", False) for a in current):
            if repetition not in incomplete:
                incomplete.append(repetition)
        all_passed &= all(a.get("verdict") == "통과" for a in current)
        if any(a.get("verdict") in {"미판정", "비적용", None} for a in current):
            if repetition not in incomplete:
                incomplete.append(repetition)
    active = repeat - len(excluded)
    complete = bool(active) and not incomplete
    verdict = "실패" if failed else "통과" if complete and all_passed else "미판정"
    return {
        "case_id": case["id"],
        "required": required,
        "verdict": verdict,
        "complete": complete,
        "planned_repetitions": repeat,
        "recorded_repetitions": active - len(missing),
        "missing_repetitions": missing,
        "incomplete_repetitions": incomplete,
        "excluded_repetitions": excluded,
        "missing_expectations": missing_expectations,
        "missing_checks": missing_checks,
        "reason": "요청한 대상에 적용할 검사가 없습니다."
        if not active
        else "예정한 반복의 평가가 완료되지 않았습니다."
        if not complete
        else "예정한 반복의 판정을 완료했습니다.",
    }


def _functional(
    cases,
    repeat,
    assessments,
    evidences,
    node,
    role,
    scope_evidence,
    plan,
    catalog,
    row_ids,
    all_assessments,
) -> FunctionalSummary:
    case_summaries = [
        _case_summary(
            case,
            repeat,
            assessments,
            evidences,
            node,
            role,
            scope_evidence,
            plan,
            catalog,
            row_ids,
            all_assessments,
        )
        for case in cases
    ]
    required = [c for c in case_summaries if c["required"] is True]
    passed = sum(c["verdict"] == "통과" for c in required)
    failed = sum(c["verdict"] == "실패" for c in required)
    # 실패가 확인된 사례는 기능 판정 완료다. 검증 완료 여부는 별도로 보존한다.
    denominator = passed + failed
    complete_count = sum(c["complete"] for c in required)
    unspecified = sum(c["required"] is None for c in case_summaries)
    complete = bool(required) and complete_count == len(required) and not unspecified
    checks, details = _check_summaries(
        cases, assessments, evidences, scope_evidence, plan, row_ids
    )
    return {
        "verdict": "실패"
        if failed
        else "통과"
        if complete and passed == len(required)
        else "미판정",
        "complete": complete,
        "checks": checks,
        "details": details,
        "cases": {
            "numerator": passed,
            "denominator": denominator,
            "rate": passed / denominator if denominator else None,
            "passed": passed,
            "failed": failed,
            "undetermined": len(required) - denominator,
            "excluded": sum(c["required"] is False for c in case_summaries),
            "unspecified_required": unspecified,
            "items": case_summaries,
        },
        "verification": {
            "required_cases": len(required),
            "completed_cases": complete_count,
            "incomplete_cases": len(required) - complete_count,
            "missing_repetitions": sum(len(c["missing_repetitions"]) for c in required),
        },
    }


def _operational(evidences) -> OperationalSummary:
    finished, pending = [], []
    for node in evidences:
        unfinished = node.get(
            "unfinished", node.get("status") not in {"success", "error"}
        )
        (pending if unfinished else finished).append(node)
    unfinished = len(pending)
    known = [n for n in finished if type(n.get("technical_failure")) is bool]
    failed = sum(n["technical_failure"] for n in known)
    timing = {}
    for group, failure in (("normal", False), ("error", True)):
        nodes = [n for n in known if n["technical_failure"] is failure]
        values = [
            n["elapsed_seconds"] for n in nodes if _number(n.get("elapsed_seconds"))
        ]
        timing[group] = _statistics(values, missing=len(nodes) - len(values))
    timing["unclassified_count"] = len(finished) - len(known)
    timing["unfinished_count"] = unfinished
    usage = {}
    for field in ("input_tokens", "output_tokens", "model_calls", "technical_retries"):
        values = [
            (n.get("usage") or {}).get(field)
            if field.endswith("_tokens")
            else n.get(field)
            for n in finished
        ]
        measured = [v for v in values if type(v) is int and v >= 0]
        usage[field] = _statistics(
            measured, missing=len(values) - len(measured), unfinished=unfinished
        )
    retry_kinds = {}
    for kind in CALL_KINDS:
        values = [
            (n.get("technical_retries_by_kind") or {}).get(kind) for n in finished
        ]
        measured = [value for value in values if type(value) is int and value >= 0]
        retry_kinds[kind] = _statistics(
            measured, missing=len(values) - len(measured), unfinished=unfinished
        )
    observations = []
    for node in pending:
        observed = node.get("observed_usage") or {
            "usage": {
                key: (node.get("usage") or {}).get(key)
                for key in ("input_tokens", "output_tokens")
            },
            "usage_missing_calls": dict.fromkeys(("input_tokens", "output_tokens")),
            "model_calls": node.get("model_calls"),
            "technical_retries": node.get("technical_retries"),
            "technical_retries_by_kind": {
                key: (node.get("technical_retries_by_kind") or {}).get(key)
                for key in CALL_KINDS
            },
        }
        observations.append(
            {
                "node_id": node["id"],
                "run_id": node.get("run_id"),
                "case_id": node["case_id"],
                "repetition": node["repetition"],
                **deepcopy(observed),
            }
        )
    return {
        "measurement_scope": "selected_model_calls",
        "verdict": "미판정",
        "complete": False,
        "failure_rate": {
            "numerator": failed,
            "denominator": len(known),
            "rate": failed / len(known) if known else None,
            "missing_count": len(finished) - len(known),
            "unfinished_count": unfinished,
        },
        "response_time": timing,
        "tokens": {key: usage[key] for key in ("input_tokens", "output_tokens")},
        "model_calls": usage["model_calls"],
        "technical_retries": usage["technical_retries"],
        "technical_retries_by_kind": retry_kinds,
        "unfinished_usage": observations,
    }


def _performance(goals, cases, repeat, evidences) -> list[PerformanceSummary]:
    summaries = []
    known_ids = {c["id"] for c in cases}
    for goal in goals:
        reasons = []
        ids = goal.get("case_ids", [])
        metric = goal.get("metric", "response_time")
        group, statistic = goal.get("group"), goal.get("statistic")
        selected = [n for n in evidences if n.get("case_id") in ids]
        if not ids or not set(ids) <= known_ids:
            reasons.append("성능 대상 사례가 평가 계획에 없습니다.")
        if metric == "response_time":
            if group not in {"normal", "error"} or statistic not in {"median", "p95"}:
                reasons.append("성능 판정의 종료 종류·통계값이 미확정입니다.")
            if not _number(goal.get("max_seconds")):
                reasons.append("성능 목표가 미확정입니다.")
        elif metric == "failure_rate":
            if not _number(goal.get("max_rate")) or goal["max_rate"] > 1:
                reasons.append("기술적 실패율 목표가 미확정입니다.")
        else:
            reasons.append("지원하지 않는 운영 지표입니다.")
        for key in ("environment", "data_size"):
            if not isinstance(goal.get(key), str) or not goal[key].strip():
                reasons.append(f"시험 조건 미확정: {key}")
        eligible = [
            n
            for n in selected
            if n.get("status") in {"success", "error"}
            and not n.get("unfinished", False)
            and type(n.get("technical_failure")) is bool
            and (
                metric == "failure_rate"
                or (
                    n["technical_failure"] is (group == "error")
                    and _number(n.get("elapsed_seconds"))
                )
            )
        ]
        observed = {(n["case_id"], n["repetition"]) for n in eligible}
        if {(cid, rep) for cid in ids for rep in range(1, repeat + 1)} - observed:
            reasons.append("예정한 사례·반복의 해당 상태 측정이 없습니다.")
        if any(not n.get("complete") for n in selected):
            reasons.append("완료되지 않은 실행 증거가 있습니다.")
        if metric == "failure_rate" and len(eligible) != len(selected):
            reasons.append("기술적 실패 여부를 판정할 측정이 누락되었습니다.")
        if metric == "response_time" and any(
            type(n.get("technical_failure")) is not bool
            or (
                n["technical_failure"] is (group == "error")
                and not _number(n.get("elapsed_seconds"))
            )
            for n in selected
        ):
            reasons.append("종료 종류 또는 해당 종류의 응답시간 측정이 누락되었습니다.")
        if metric == "failure_rate":
            value = (
                sum(n["technical_failure"] for n in eligible) / len(eligible)
                if eligible
                else None
            )
            limit = goal.get("max_rate")
        else:
            stats = _statistics(n["elapsed_seconds"] for n in eligible)
            value = stats.get(statistic)
            limit = goal.get("max_seconds")
        complete = not reasons and value is not None
        summaries.append(
            {
                "metric": metric,
                "group": group,
                "statistic": statistic,
                "case_ids": ids,
                "max_seconds": goal.get("max_seconds"),
                "max_rate": goal.get("max_rate"),
                "value_seconds": value if metric == "response_time" else None,
                "value_rate": value if metric == "failure_rate" else None,
                "sample_count": len(eligible),
                "complete": complete,
                "verdict": ("통과" if value <= limit else "실패")
                if complete
                else "미판정",
                "reasons": reasons,
            }
        )
    return summaries


def summarize_nodes(
    cases,
    repeat,
    assessments,
    node_evidences,
    performance=None,
    *,
    scope_evidence: list[CaseScopeEvidence] | None = None,
    row_ids=None,
    catalog=None,
    run_cases: list[RunCase] | None = None,
) -> list[NodeSummary]:
    """같은 노드·역할 안에서 검사 전체, 세부 항목, 필수 사례를 각각 집계한다."""
    if type(repeat) is not int or repeat < 1:
        raise ValueError("repeat must be a positive integer")
    case_by_id = {c["id"]: c for c in cases}
    plan = {
        (run["case"]["id"], run["repetition"]): run["case"] for run in run_cases or []
    }
    catalog = load_criteria() if catalog is None else catalog

    def selected(value, *, scope_only=False):
        case = case_by_id.get(value.get("case_id"))
        if case is None:
            return False
        if not scope_only:
            case = plan.get((case["id"], value.get("repetition")), case)
            context = _scope_context(
                case, node_evidences, scope_evidence, value.get("repetition")
            )
            if not _group_requested(
                case, value.get("node"), value.get("role"), context, catalog, row_ids
            ):
                return False
        if case.get("unit") == "node":
            return (value.get("node"), value.get("role")) == (
                case["target"],
                case.get("role"),
            )
        return True

    assessments = [
        a
        for a in assessments
        if a.get("counted", True)
        and selected(a)
        and type(a.get("repetition")) is int
        and 1 <= a["repetition"] <= repeat
    ]
    evidences = [
        n
        for n in node_evidences
        if n.get("counted", True)
        and selected(n)
        and type(n.get("repetition")) is int
        and 1 <= n["repetition"] <= repeat
    ]
    scope_evidence = [
        n
        for n in scope_evidence or []
        if selected(n, scope_only=True)
        and type(n.get("repetition")) is int
        and 1 <= n["repetition"] <= repeat
    ]
    assessments, assessment_conflicts = _deduplicate(assessments)
    evidences, evidence_conflicts = _deduplicate(evidences)
    groups = {(n.get("node"), n.get("role")) for n in [*assessments, *evidences]}
    groups |= {(c["target"], c.get("role")) for c in cases if c.get("unit") == "node"}
    for case in cases:
        groups |= _planned_groups(
            case, groups, evidences, scope_evidence, row_ids=row_ids
        )
    summaries = []
    for node, role in sorted(groups, key=str):
        if node not in NODES:
            continue
        scored = [
            a for a in assessments if (a.get("node"), a.get("role")) == (node, role)
        ]
        observed = [
            n for n in evidences if (n.get("node"), n.get("role")) == (node, role)
        ]
        relevant_ids = {a["case_id"] for a in [*scored, *observed]}
        selected = [
            c
            for c in cases
            if c["id"] in relevant_ids
            or (node, role)
            in _planned_groups(c, groups, evidences, scope_evidence, row_ids=row_ids)
            or (
                c.get("unit") == "node"
                and c["target"] == node
                and c.get("role") == role
            )
        ]
        functional = _functional(
            selected,
            repeat,
            scored,
            observed,
            node,
            role,
            scope_evidence,
            plan,
            catalog,
            row_ids,
            assessments,
        )
        operational = _operational(observed)
        goals = [
            g
            for g in performance or []
            if g.get("target", g.get("node")) == node and g.get("role", role) == role
        ]
        performance_results = _performance(goals, selected, repeat, observed)
        if performance_results:
            operational["complete"] = all(r["complete"] for r in performance_results)
            operational["verdict"] = (
                "실패"
                if any(r["verdict"] == "실패" for r in performance_results)
                else "통과"
                if operational["complete"]
                else "미판정"
            )
        all_results = [functional, *performance_results]
        complete = all(r["complete"] for r in all_results)
        summaries.append(
            {
                "node": node,
                "role": role,
                "runs": len(observed),
                "functional": functional,
                "operational": operational,
                "performance": performance_results,
                "complete": complete,
                "verdict": "실패"
                if any(r["verdict"] == "실패" for r in all_results)
                else "통과"
                if complete
                else "미판정",
                "verdict_scope": "기능과 지정된 운영 목표",
                "conflicting_assessments": [list(k) for k in assessment_conflicts],
                "conflicting_evidence": [list(k) for k in evidence_conflicts],
            }
        )
    return summaries
