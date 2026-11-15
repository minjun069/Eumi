"""계획한 도구 사례와 저장된 검사·호출 증거에서 기능 및 시간 지표를 계산한다."""

from collections import defaultdict
from datetime import datetime
from math import ceil, isfinite
from statistics import median
from typing import TYPE_CHECKING, Literal

from typing_extensions import TypedDict

from eval.tools.assessment import ToolTarget, Verdict

if TYPE_CHECKING:
    from eval.schema import Case, PerformanceTarget
    from eval.tools.assessment import RunAssessment

TOOLS = ToolTarget.__args__


class CheckCoverage(TypedDict):
    check: str
    unexecuted: int
    undetermined: int
    reasons: list[str]


class CaseSummary(TypedDict):
    case_id: str
    required: bool | None
    verdict: Verdict
    complete: bool
    planned_repetitions: int
    recorded_repetitions: int
    missing_repetitions: list[int]
    undetermined_repetitions: list[int]
    checks: list[CheckCoverage]
    reasons: list[str]


class FunctionalSummary(TypedDict):
    verdict: Verdict
    complete: bool
    numerator: int
    denominator: int
    rate: float | None
    completed_cases: int
    completed_passed_cases: int
    completed_failed_cases: int
    incomplete_cases: int
    passed_cases: int
    failed_cases: int
    missing_cases: int
    undetermined_cases: int
    unspecified_required_cases: int
    excluded_cases: int
    cases: list[CaseSummary]


class TimingStatistics(TypedDict):
    sample_count: int
    median_seconds: float | None
    p95_seconds: float | None


class UnfinishedCall(TypedDict):
    span_id: str
    run_id: str | None
    case_id: str
    repetition: int
    elapsed_seconds: float | None


class LatencySummary(TypedDict):
    normal: TimingStatistics
    error: TimingStatistics
    unfinished_count: int
    unfinished: list[UnfinishedCall]
    conflicting_span_ids: list[str]
    invalid_measurements: int
    execution_limit_exceeded: int
    reasons: list[str]


class PerformanceSummary(TypedDict):
    group: str
    case_ids: list[str]
    statistic: str | None
    max_seconds: float | None
    environment: str | None
    data_size: str | None
    sample_count: int
    value_seconds: float | None
    verdict: Verdict
    complete: bool
    reasons: list[str]


class ToolSummary(TypedDict):
    target: str
    functional: FunctionalSummary
    latency: LatencySummary
    performance: list[PerformanceSummary]


class MeasuredCall(TypedDict):
    span_id: str
    run_id: str | None
    case_id: str
    repetition: int
    group: Literal["normal", "error"]
    elapsed_seconds: float


def _unique(items):
    return list(dict.fromkeys(items))


def _case_summary(case: "Case", repeat: int, assessments) -> CaseSummary:
    prepared = case.get("assessment", {})
    check_ids = _unique(prepared.get("checks", []))
    reasons = []
    missing, unknown = [], []
    failed = False
    recorded = 0
    coverage = {
        check: CheckCoverage(check=check, unexecuted=0, undetermined=0, reasons=[])
        for check in check_ids
    }
    if not check_ids:
        reasons.append("적용 검사가 지정되지 않았습니다.")
    if prepared.get("expected") is None:
        reasons.append("기대 결과가 준비되지 않았습니다.")
    for repetition in range(1, repeat + 1):
        matches = assessments.get((case["id"], case["target"], repetition), [])
        distinct = []
        for item in matches:
            if item not in distinct:
                distinct.append(item)
        if not distinct:
            missing.append(repetition)
            unknown.append(repetition)
            for item in coverage.values():
                item["unexecuted"] += 1
                item["undetermined"] += 1
                item["reasons"].append(f"반복 {repetition}: 평가 기록 없음")
            continue
        recorded += 1
        if len(distinct) != 1:
            unknown.append(repetition)
            reasons.append(f"반복 {repetition}: 서로 다른 평가 기록이 중복됩니다.")
            # 확인된 실패는 보존하되 상충 기록 중 하나를 선택하지 않는다.
            failed |= any(item["verdict"] == "실패" for item in distinct)
            for item in coverage.values():
                item["undetermined"] += 1
                item["reasons"].append(f"반복 {repetition}: 평가 기록 중복")
            continue
        result = distinct[0]
        failed |= result["verdict"] == "실패"
        unresolved = not result["executed"] or result["verdict"] in {"미판정", "비적용"}
        if result.get("run_id") is None:
            missing.append(repetition)
            unresolved = True
        applicable = False
        for check_id in check_ids:
            details = [c for c in result["checks"] if c["check"] == check_id]
            item = coverage[check_id]
            if not details:
                item["unexecuted"] += 1
                item["undetermined"] += 1
                item["reasons"].append(f"반복 {repetition}: 검사 기록 없음")
                unresolved = True
                continue
            # 같은 검사·대상의 같은 판정은 완료 현황에 한 번만 반영한다.
            seen = set()
            for detail in details:
                key = (detail["target"], detail["verdict"], detail["executed"])
                if key in seen:
                    continue
                seen.add(key)
                if detail["verdict"] == "비적용":
                    if not detail.get("reason", "").strip():
                        item["undetermined"] += 1
                        unresolved = True
                    continue
                applicable = True
                failed |= detail["verdict"] == "실패"
                if not detail["executed"]:
                    item["unexecuted"] += 1
                if not detail["executed"] or detail["verdict"] == "미판정":
                    item["undetermined"] += 1
                    item["reasons"].append(f"반복 {repetition}: {detail['reason']}")
                    unresolved = True
        if not applicable:
            unresolved = True
            reasons.append(f"반복 {repetition}: 판정한 적용 검사가 없습니다.")
        if unresolved:
            unknown.append(repetition)
            if result.get("reason"):
                reasons.append(f"반복 {repetition}: {result['reason']}")
    if reasons and (not check_ids or prepared.get("expected") is None):
        unknown = list(range(1, repeat + 1))
    complete = not unknown
    if missing:
        reasons.append(f"실행 또는 평가 기록이 없는 반복: {missing}")
    return {
        "case_id": case["id"],
        "required": prepared.get("required"),
        "verdict": "실패" if failed else "통과" if complete else "미판정",
        "complete": complete,
        "planned_repetitions": repeat,
        "recorded_repetitions": recorded,
        "missing_repetitions": missing,
        "undetermined_repetitions": unknown,
        "checks": list(coverage.values()),
        "reasons": _unique(reasons),
    }


def _functional(cases, repeat, assessments) -> FunctionalSummary:
    summaries = [_case_summary(case, repeat, assessments) for case in cases]
    required = [item for item in summaries if item["required"] is True]
    unspecified = sum(item["required"] is None for item in summaries)
    passed = sum(item["verdict"] == "통과" for item in required)
    failed = sum(item["verdict"] == "실패" for item in required)
    completed = sum(item["complete"] for item in required)
    complete = bool(required) and completed == len(required) and not unspecified
    return {
        "verdict": "실패" if failed else "통과" if complete else "미판정",
        "complete": complete,
        "numerator": passed,
        "denominator": len(required),
        "rate": passed / len(required) if required else None,
        "completed_cases": completed,
        "completed_passed_cases": passed,
        "completed_failed_cases": sum(
            item["complete"] and item["verdict"] == "실패" for item in required
        ),
        "incomplete_cases": len(required) - completed,
        "passed_cases": passed,
        "failed_cases": failed,
        "missing_cases": sum(bool(item["missing_repetitions"]) for item in required),
        "undetermined_cases": sum(not item["complete"] for item in required),
        "unspecified_required_cases": unspecified,
        "excluded_cases": sum(item["required"] is False for item in summaries),
        "cases": summaries,
    }


def _seconds(value):
    try:
        return type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError:
        return False


def _statistics(values) -> TimingStatistics:
    ordered = sorted(values)
    return {
        "sample_count": len(ordered),
        "median_seconds": median(ordered) if ordered else None,
        "p95_seconds": ordered[ceil(0.95 * len(ordered)) - 1] if ordered else None,
    }


def _unfinished_elapsed(span, report):
    if _seconds(span.get("elapsed_seconds")):
        return span["elapsed_seconds"]
    try:
        elapsed = (
            datetime.fromisoformat(report["run"]["ended_at"])
            - datetime.fromisoformat(span["started_at"])
        ).total_seconds()
    except (KeyError, TypeError, ValueError):
        return None
    return elapsed if _seconds(elapsed) else None


def _limit_exceeded(error):
    while isinstance(error, dict):
        if error.get("code") == "execution_limit_exceeded":
            return True
        error = error.get("cause")
    return False


def _timings(target, cases, repeat, reports):
    case_ids = {case["id"] for case in cases}
    records = {}
    conflicts = set()
    limits = set()
    invalid = 0
    reasons = []
    for report in reports:
        run = report.get("run", {})
        if (
            run.get("unit") != "tool"
            or run.get("target") != target
            or run.get("case_id") not in case_ids
            or type(run.get("repetition")) is not int
            or not 1 <= run["repetition"] <= repeat
        ):
            continue
        identity = (run["case_id"], run["repetition"], run.get("id"))
        if _limit_exceeded(report.get("failure")):
            limits.add(identity)
        raw_spans = report.get("trace", {}).get("spans", [])
        if not isinstance(raw_spans, list):
            invalid += 1
            continue
        spans = [span for span in raw_spans if isinstance(span, dict)]
        invalid += len(raw_spans) - len(spans)
        by_id = {span["id"]: span for span in spans if isinstance(span.get("id"), str)}
        for span in spans:
            if span.get("kind") != "tool" or span.get("name") != target:
                continue
            # 재진입으로 같은 도구의 하위 span이 생겨도 호출시간을 더하지 않는다.
            parent, visited = span.get("parent_id"), set()
            nested = False
            while isinstance(parent, str) and parent in by_id and parent not in visited:
                visited.add(parent)
                ancestor = by_id[parent]
                if ancestor.get("kind") == "tool" and ancestor.get("name") == target:
                    nested = True
                    break
                parent = ancestor.get("parent_id")
            if nested:
                continue
            span_id = span.get("id")
            if not isinstance(span_id, str) or not span_id:
                invalid += 1
                continue
            if span_id in records:
                previous, previous_report = records[span_id]
                previous_run = previous_report["run"]
                previous_identity = (
                    previous_run["case_id"],
                    previous_run["repetition"],
                    previous_run.get("id"),
                )
                if previous != span or previous_identity != identity:
                    conflicts.add(span_id)
                continue
            records[span_id] = (span, report)
    calls: list[MeasuredCall] = []
    unfinished: list[UnfinishedCall] = []
    for span_id, (span, report) in records.items():
        if span_id in conflicts:
            continue
        run = report["run"]
        common = {
            "span_id": span_id,
            "run_id": run.get("id"),
            "case_id": run["case_id"],
            "repetition": run["repetition"],
        }
        if span.get("ended_at") is None:
            unfinished.append(
                common | {"elapsed_seconds": _unfinished_elapsed(span, report)}
            )
            continue
        elapsed = span.get("elapsed_seconds")
        if (
            span.get("status") not in ("success", "error")
            or not isinstance(span["ended_at"], str)
            or not span["ended_at"]
            or not _seconds(elapsed)
        ):
            invalid += 1
            continue
        calls.append(
            common
            | {
                "group": "normal" if span["status"] == "success" else "error",
                "elapsed_seconds": elapsed,
            }
        )
    if conflicts:
        reasons.append("동일한 span ID의 기록이 서로 일치하지 않습니다.")
    if invalid:
        reasons.append("종료 상태·경과 시간·식별자가 유효하지 않은 호출이 있습니다.")
    summary: LatencySummary = {
        "normal": _statistics(
            c["elapsed_seconds"] for c in calls if c["group"] == "normal"
        ),
        "error": _statistics(
            c["elapsed_seconds"] for c in calls if c["group"] == "error"
        ),
        "unfinished_count": len(unfinished),
        "unfinished": unfinished,
        "conflicting_span_ids": sorted(conflicts),
        "invalid_measurements": invalid,
        "execution_limit_exceeded": len(limits),
        "reasons": reasons,
    }
    return summary, calls, limits


def _performance(goal, cases, repeat, reports, target) -> PerformanceSummary:
    ids = goal["case_ids"]
    selected = [case for case in cases if case["id"] in ids]
    latency, calls, limits = _timings(target, selected, repeat, reports)
    group = goal["group"]
    samples = [call for call in calls if call["group"] == group]
    statistics = _statistics(call["elapsed_seconds"] for call in samples)
    statistic = goal.get("statistic")
    value = statistics.get(f"{statistic}_seconds")
    reasons = []
    if not ids or set(ids) != {case["id"] for case in selected}:
        reasons.append("성능 대상 사례가 현재 평가 계획에 모두 포함되지 않았습니다.")
    if statistic not in {"median", "p95"} or not _seconds(goal.get("max_seconds")):
        reasons.append("판정 통계값과 최대 허용 시간을 확정해야 합니다.")
    for key in ("environment", "data_size"):
        if not isinstance(goal.get(key), str) or not goal[key].strip():
            reasons.append(f"시험 조건 미확정: {key}")
    observed = {(call["case_id"], call["repetition"]) for call in samples}
    planned = {(case_id, rep) for case_id in ids for rep in range(1, repeat + 1)}
    if planned - observed:
        reasons.append("예정한 사례·반복의 해당 상태 측정이 완료되지 않았습니다.")
    if latency["unfinished_count"]:
        reasons.append("종료되지 않은 호출은 응답시간 통계에서 제외했습니다.")
    reasons.extend(latency["reasons"])
    complete = not reasons and value is not None
    verdict: Verdict = "미판정"
    if limits:
        verdict = "실패"
        reasons.append("실행 한도 초과가 기록되었습니다.")
    elif complete:
        verdict = "통과" if value <= goal["max_seconds"] else "실패"
    return {
        "group": group,
        "case_ids": list(ids),
        "statistic": statistic,
        "max_seconds": goal.get("max_seconds"),
        "environment": goal.get("environment"),
        "data_size": goal.get("data_size"),
        "sample_count": len(samples),
        "value_seconds": value,
        "verdict": verdict,
        "complete": complete,
        "reasons": _unique(reasons),
    }


def summarize_tools(
    cases: list["Case"],
    repeat: int,
    assessments: list["RunAssessment"],
    reports: list[dict],
    performance: list["PerformanceTarget"] | None = None,
) -> list[ToolSummary]:
    """선택한 계획의 사례 분모를 보존하며 도구별 판정과 측정값을 반환한다."""
    if type(repeat) is not int or repeat < 1:
        raise ValueError("repeat must be a positive integer")
    indexed = defaultdict(list)
    for assessment in assessments:
        indexed[
            (assessment["case_id"], assessment["target"], assessment["repetition"])
        ].append(assessment)
    summaries = []
    for target in TOOLS:
        selected = [
            case
            for case in cases
            if case["unit"] == "tool" and case["target"] == target
        ]
        goals = [goal for goal in performance or [] if goal["target"] == target]
        if not selected and not goals:
            continue
        latency, _, _ = _timings(target, selected, repeat, reports)
        summaries.append(
            {
                "target": target,
                "functional": _functional(selected, repeat, indexed),
                "latency": latency,
                "performance": [
                    _performance(goal, selected, repeat, reports, target)
                    for goal in goals
                ],
            }
        )
    return summaries
