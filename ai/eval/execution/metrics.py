"""저장된 실행 경계로 기능 판정과 이번 진입의 운영 사용량을 집계한다."""

from collections import Counter, defaultdict
from datetime import datetime
from math import ceil, isfinite
from statistics import mean, median
from typing import Literal, get_args

from typing_extensions import TypedDict

from eval.execution.schema import supported
from src.prompting import Role


class Statistics(TypedDict):
    sample_count: int
    missing_count: int
    mean: float | None
    median: float | None
    p95: float | None
    minimum: float | None
    maximum: float | None


class Rate(TypedDict):
    numerator: int
    denominator: int
    rate: float | None


class CheckSummary(Rate):
    check: str
    passed: int
    failed: int
    undetermined: int
    unexecuted: int
    not_applicable: int
    reasons: list[str]


class CaseSummary(TypedDict):
    case_id: str
    required: bool | None
    verdict: str
    complete: bool
    planned_repetitions: int
    recorded_repetitions: int
    missing_repetitions: list[int]
    incomplete_repetitions: list[int]
    reasons: list[str]


class CaseTotals(Rate):
    passed: int
    failed: int
    undetermined: int
    excluded: int
    unspecified_required: int
    items: list[CaseSummary]


class Verification(TypedDict):
    required_cases: int
    completed_cases: int
    incomplete_cases: int
    missing_repetitions: int


class FunctionalSummary(TypedDict):
    verdict: str
    complete: bool
    checks: list[CheckSummary]
    cases: CaseTotals
    verification: Verification


class ExecutionMeasurement(TypedDict):
    case_id: str
    run_id: str | None
    repetition: int
    unit: str
    target: str
    role: str | None
    dependencies: str
    situation: str | None
    entry: str | None
    environment: str | None
    data_size: str | None
    dong_code: str | None
    month: str | None
    started: bool
    ended: bool
    returned: bool
    evidence_complete: bool
    outcome: str
    returned_status: str | None
    elapsed_seconds: float | None
    observed_at: str | None
    timing_scope: str | None
    model_calls: int | None
    tool_calls: int | None
    agent_calls: int | None
    node_entries: int | None
    retries: int | None
    budget_delta: dict[str, int | float | None]
    input_tokens: int | None
    output_tokens: int | None
    observed_tokens: dict[str, int | None]
    missing_token_calls: dict[str, int]
    observed_calls: dict[str, int]
    model_cost: float | None
    tool_cost: float | None
    cost: float | None
    currency: str | None
    failed_calls: dict[str, int]
    reasons: list[str]


class FailureRate(Rate):
    unclassified_count: int
    evaluation_failure_count: int
    unfinished_count: int


class OperationalGroup(TypedDict):
    conditions: dict[str, str | None]
    started: int
    ended: int
    unfinished: int
    outcomes: dict[str, Rate]
    failure_rate: FailureRate
    measurements: dict[str, Statistics]
    elapsed_by_outcome: dict[str, Statistics]
    report_completion: Rate
    runs: list[ExecutionMeasurement]


class Repetitions(TypedDict):
    case_id: str
    planned: int
    started: int
    ended: int
    unfinished: int
    missing_repetitions: list[int]
    measurements: dict[str, Statistics]
    runs: list[ExecutionMeasurement]


class GoalSummary(TypedDict):
    target: str
    metric: str
    case_ids: list[str]
    statistic: str | None
    value: float | None
    maximum: float | None
    sample_count: int
    verdict: str
    complete: bool
    reasons: list[str]


class OperationalSummary(TypedDict):
    measurement_scope: Literal["execution"]
    verdict: str
    complete: bool
    groups: list[OperationalGroup]
    repetitions: list[Repetitions]
    goals: list[GoalSummary]
    runs: list[ExecutionMeasurement]
    unfinished_usage: list[ExecutionMeasurement]
    reasons: list[str]


class ExecutionSummary(TypedDict):
    functional: FunctionalSummary
    report_completion: Rate
    operational: OperationalSummary


MEASURES = (
    "elapsed_seconds",
    "model_calls",
    "tool_calls",
    "agent_calls",
    "node_entries",
    "retries",
    "input_tokens",
    "output_tokens",
    "cost",
)
CONDITIONS = (
    "target",
    "role",
    "dependencies",
    "situation",
    "entry",
    "environment",
    "data_size",
)
REPORT_ROLES = {
    "report_selection_agent",
    "report_description_agent",
    "report_insight_agent",
}
NORMAL_OUTCOMES = {"completed", "partial", "question", "refusal", "no_data"}
FUNCTIONAL_EXCLUSION_REASON = (
    "역할 단독 실행은 운영 진단만 집계합니다. "
    "EX 기능 평가는 agent/request 또는 workflow/report에만 적용합니다."
)


def operational_supported(case):
    """실제 역할 실행의 관측량을 집계하되 EX 기능 적용 범위는 확장하지 않는다."""
    return supported(case) or (
        case.get("unit") == "agent" and case.get("target") in get_args(Role)
    )


def _number(value):
    try:
        return type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError:
        return False


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _rate(numerator, denominator) -> Rate:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def _statistics(values) -> Statistics:
    values = list(values)
    ordered = sorted(value for value in values if _number(value))
    return {
        "sample_count": len(ordered),
        "missing_count": len(values) - len(ordered),
        "mean": mean(ordered) if ordered else None,
        "median": median(ordered) if ordered else None,
        "p95": ordered[ceil(len(ordered) * 0.95) - 1] if ordered else None,
        "minimum": ordered[0] if ordered else None,
        "maximum": ordered[-1] if ordered else None,
    }


def _unique(items):
    result = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _expectations(case):
    expected = case.get("assessment", {}).get("expected")
    return expected if isinstance(expected, dict) else {}


def _functional(cases, repeat, assessments) -> FunctionalSummary:
    cases = [case for case in cases if supported(case)]
    indexed = defaultdict(list)
    for item in assessments:
        indexed[item.get("case_id"), item.get("repetition")].append(item)
    checks, case_summaries = {}, []
    for case in cases:
        prepared = case.get("assessment", {})
        requested = _unique(prepared.get("checks", []))
        for name in requested:
            checks.setdefault(
                name,
                {
                    "check": name,
                    **_rate(0, 0),
                    "passed": 0,
                    "failed": 0,
                    "undetermined": 0,
                    "unexecuted": 0,
                    "not_applicable": 0,
                    "reasons": [],
                },
            )
        missing, incomplete, reasons = [], [], []
        failed, recorded = False, 0
        if not requested:
            reasons.append("적용 검사가 지정되지 않았습니다.")
        if _expectations(case).get("schema_version") != ("execution-expectations-v1"):
            reasons.append("실행 기대 조건이 준비되지 않았습니다.")
        for repetition in range(1, repeat + 1):
            records = _unique(indexed[case["id"], repetition])
            known = [r for r in records if r.get("run_id")]
            if not known:
                missing.append(repetition)
            else:
                recorded += 1
            unresolved = bool(reasons) or len(records) != 1 or not known
            applicable = False
            for name in requested:
                summary = checks[name]
                matches = _unique(
                    [
                        check
                        for record in records
                        for check in record.get("checks", [])
                        if check.get("check") == name
                    ]
                )
                failure = any(c.get("verdict") == "실패" for c in matches)
                failed |= failure
                if len(matches) != 1 or len(records) != 1:
                    unresolved = True
                    summary["failed" if failure else "undetermined"] += 1
                    summary["unexecuted"] += not matches
                    summary["reasons"].append(
                        f"{case['id']} 반복 {repetition}: 검사 누락 또는 상충 기록"
                    )
                    continue
                check = matches[0]
                verdict = check.get("verdict")
                executed = check.get("executed", False)
                complete = check.get("complete", verdict in {"통과", "실패", "비적용"})
                if verdict == "비적용" and check.get("reason") and complete:
                    summary["not_applicable"] += 1
                    summary["reasons"].append(check["reason"])
                    continue
                applicable = True
                summary["unexecuted"] += not executed
                if failure:
                    summary["failed"] += 1
                elif verdict == "통과" and executed and complete:
                    summary["passed"] += 1
                else:
                    summary["undetermined"] += 1
                if not executed or not complete or verdict not in {"통과", "실패"}:
                    unresolved = True
                    if check.get("reason"):
                        summary["reasons"].append(check["reason"])
            failed |= any(r.get("verdict") == "실패" for r in records)
            if (
                unresolved
                or not applicable
                or not all(r.get("complete") for r in records)
            ):
                incomplete.append(repetition)
        complete = not incomplete
        case_summaries.append(
            {
                "case_id": case["id"],
                "required": prepared.get("required"),
                "verdict": "실패" if failed else "통과" if complete else "미판정",
                "complete": complete,
                "planned_repetitions": repeat,
                "recorded_repetitions": recorded,
                "missing_repetitions": missing,
                "incomplete_repetitions": incomplete,
                "reasons": reasons,
            }
        )
    required = [item for item in case_summaries if item["required"] is True]
    unspecified = sum(item["required"] is None for item in case_summaries)
    passed = sum(item["verdict"] == "통과" for item in required)
    failed = sum(item["verdict"] == "실패" for item in required)
    completed = sum(item["complete"] for item in required)
    complete = bool(required) and completed == len(required) and not unspecified
    for item in checks.values():
        item.update(_rate(item["passed"], item["passed"] + item["failed"]))
        item["reasons"] = _unique(item["reasons"])
    return {
        "verdict": "실패" if failed else "통과" if complete else "미판정",
        "complete": complete,
        "checks": list(checks.values()),
        "cases": {
            **_rate(passed, passed + failed),
            "passed": passed,
            "failed": failed,
            "undetermined": len(required) - passed - failed,
            "excluded": sum(item["required"] is False for item in case_summaries),
            "unspecified_required": unspecified,
            "items": case_summaries,
        },
        "verification": {
            "required_cases": len(required),
            "completed_cases": completed,
            "incomplete_cases": len(required) - completed,
            "missing_repetitions": sum(len(i["missing_repetitions"]) for i in required),
        },
    }


def _error_codes(error):
    while isinstance(error, dict):
        yield error.get("code") or error.get("type")
        error = error.get("cause")


def _outcome(report, final, ended):
    failure = set(_error_codes(report.get("failure")))
    if failure & {"unexpected_stub_call", "UnexpectedStubCall"}:
        return "evaluation_failure"
    if not ended:
        return "unfinished"
    run = report.get("run", {})
    execution = _mapping(final.get("execution"))
    status = execution.get("status")
    if run.get("status") == "cancelled" or status == "cancelled":
        return "cancelled"
    # 보고서 조립은 부분 상태로 반환해도 실행 오류 원인은 보존한다.
    error = _mapping(execution.get("error"))
    code = error.get("code")
    if (status is not None and not isinstance(status, str)) or (
        code is not None and not isinstance(code, str)
    ):
        return "unclassified"
    if code and code not in {"incomplete", "insufficient_data", "no_data", "refused"}:
        return "technical_failure"
    if run.get("status") == "error":
        return "technical_failure"
    if status == "failed":
        return "unclassified"
    if status == "waiting_input":
        return "question"
    if status in {"completed", "partial"}:
        return {"refused": "refusal", "no_data": "no_data"}.get(code, status)
    return "unclassified"


def _span_records(report):
    records, conflicting, issues = {}, set(), []
    trace = _mapping(report.get("trace"))
    raw = trace.get("spans")
    if not isinstance(raw, list):
        return [], ["호출 목록이 누락되었거나 배열이 아닙니다."]
    for span in raw:
        if (
            not isinstance(span, dict)
            or not isinstance(span.get("id"), str)
            or not span["id"]
        ):
            issues.append("호출 식별자가 누락되었거나 유효하지 않습니다.")
            continue
        if span.get("evidence_conflict"):
            issues.append(f"호출 {span['id']}: 복구 증거가 상충합니다.")
        identity = span["id"]
        if identity in records and records[identity] != span:
            conflicting.add(identity)
        else:
            records[identity] = span
    if conflicting:
        issues.append("같은 호출 ID의 기록이 상충합니다.")
    records = {key: span for key, span in records.items() if key not in conflicting}
    sequences = []
    for span in records.values():
        identity, status = span["id"], span.get("status")
        ended = span.get("ended_at") is not None
        if (
            not isinstance(status, str)
            or status not in {"running", "success", "error", "interrupted"}
            or ((status == "running") == ended)
        ):
            issues.append(f"호출 {identity}: 종료 상태와 종료 기록이 불명확합니다.")
        kind = span.get("kind")
        if not isinstance(kind, str) or not kind:
            issues.append(f"호출 {identity}: 호출 종류가 없습니다.")
        if not isinstance(span.get("name"), str):
            issues.append(f"호출 {identity}: 호출 이름이 유효하지 않습니다.")
        if (
            isinstance(kind, str)
            and kind
            in {
                "execution",
                "evaluation",
                "agent",
                "node",
                "model",
            }
            and (
                not isinstance(span.get("input"), dict)
                or ("output" in span and not isinstance(span["output"], dict))
            )
        ):
            issues.append(f"호출 {identity}: 경계 입출력이 객체가 아닙니다.")
        if isinstance(kind, str) and kind in {
            "execution",
            "evaluation",
            "agent",
            "node",
        }:
            state_key = "state" if kind == "node" else "initial_state"
            if not isinstance(_mapping(span.get("input")).get(state_key), dict):
                issues.append(
                    f"호출 {identity}: 진입 상태가 누락되었거나 객체가 아닙니다."
                )
        output = _mapping(span.get("output"))
        for key in ("state", "observed_state", "applied_update", "sdk_response"):
            if (
                key in output
                and output[key] is not None
                and not isinstance(output[key], dict)
            ):
                issues.append(f"호출 {identity}: {key} 증거가 객체가 아닙니다.")
        sequence = span.get("sequence")
        if type(sequence) is not int or sequence < 1:
            issues.append(f"호출 {identity}: 시작 순번이 없습니다.")
        else:
            sequences.append(sequence)
        parent, visited = span.get("parent_id"), {identity}
        while parent is not None:
            if (
                not isinstance(parent, str)
                or parent not in records
                or parent in visited
            ):
                issues.append(f"호출 {identity}: 부모 호출이 누락되었거나 순환합니다.")
                break
            visited.add(parent)
            ancestor = records[parent]
            if (
                type(sequence) is int
                and type(ancestor.get("sequence")) is int
                and (ancestor["sequence"] >= sequence)
            ):
                issues.append(
                    f"호출 {identity}: 부모보다 먼저 시작한 것으로 기록됐습니다."
                )
            parent = ancestor.get("parent_id")
    if sorted(sequences) != list(range(1, len(records) + 1)):
        issues.append("호출 시작 순번이 누락되었거나 중복됩니다.")
    roots = [span for span in records.values() if span.get("parent_id") is None]
    if (
        len(roots) != 1
        or not isinstance(roots[0].get("kind"), str)
        or (roots[0]["kind"] not in {"execution", "evaluation"})
    ):
        issues.append("하나의 실행 시작 경계에 모든 호출이 연결되지 않았습니다.")
    counts = Counter(
        span["kind"] for span in records.values() if isinstance(span.get("kind"), str)
    )
    declared = trace.get("counts")
    if (
        not isinstance(declared, dict)
        or any(type(count) is not int or count < 0 for count in declared.values())
        or dict(counts) != declared
    ):
        issues.append("기록된 종류별 호출 수와 실제 호출 목록이 일치하지 않습니다.")
    models = [span for span in records.values() if span.get("kind") == "model"]
    coverage = {
        "model_attempts": len(models),
        "model_inputs": sum(
            isinstance(s.get("input"), dict) and "messages" in s["input"]
            for s in models
        ),
        "http_requests": sum("http_request" in s for s in models),
        "http_responses": sum("http_response" in s for s in models),
        "sdk_responses": sum("output" in s for s in models),
        "model_errors": sum(s.get("status") == "error" for s in models),
        "unfinished_spans": sum(s.get("ended_at") is None for s in records.values()),
    }
    declared_coverage = trace.get("coverage")
    if not isinstance(declared_coverage, dict) or any(
        type(declared_coverage.get(key)) is not int or declared_coverage[key] != count
        for key, count in coverage.items()
    ):
        issues.append("호출·응답 수집 현황과 실제 호출 목록이 일치하지 않습니다.")
    return list(records.values()), _unique(issues)


def _calls(spans):
    by_id = {span["id"]: span for span in spans}
    result = []
    for span in spans:
        kind = span.get("kind")
        if not isinstance(kind, str) or kind not in {"model", "tool", "agent", "node"}:
            continue
        if (
            kind == "agent"
            and isinstance(span.get("name"), str)
            and span["name"] in REPORT_ROLES
        ):
            continue
        parent, visited, duplicate = span.get("parent_id"), set(), False
        while isinstance(parent, str) and parent in by_id and parent not in visited:
            visited.add(parent)
            ancestor = by_id[parent]
            if kind == "tool" and (ancestor.get("kind"), ancestor.get("name")) == (
                kind,
                span.get("name"),
            ):
                duplicate = True
                break
            parent = ancestor.get("parent_id")
        if not duplicate:
            result.append(span)
    return result


def _token_values(models):
    tokens = {key: [] for key in ("input_tokens", "output_tokens")}
    for model in models:
        response = _mapping(_mapping(model.get("output")).get("sdk_response"))
        usage = _mapping(response.get("usage_metadata"))
        for key in tokens:
            value = usage.get(key)
            tokens[key].append(value if type(value) is int and value >= 0 else None)
    return tokens


def _costs(models, tools, pricing, intact):
    reasons, model_cost, tool_cost = [], 0.0, 0.0
    if not pricing or not intact:
        return (
            None,
            None,
            ["단가 또는 완전한 호출 증거가 없어 비용을 산출하지 않습니다."],
        )
    for call in models:
        response = _mapping(_mapping(call.get("output")).get("sdk_response"))
        name = _mapping(response.get("response_metadata")).get("model_name")
        if not isinstance(name, str):
            name = None
        price = pricing.get("models", {}).get(name, {})
        tokens = _token_values([call])
        missing = False
        for key, rate in (
            ("input_tokens", "input_per_million"),
            ("output_tokens", "output_per_million"),
        ):
            if not _number(price.get(rate)) or tokens[key][0] is None:
                missing = True
            elif model_cost is not None:
                model_cost += tokens[key][0] * price[rate] / 1_000_000
        if missing:
            model_cost = None
            reasons.append(f"모델 {name or '미확인'}: 사용량 또는 입력·출력 단가 누락")
    for call in tools:
        name = call.get("name") if isinstance(call.get("name"), str) else None
        rate = pricing.get("tools", {}).get(name, {}).get("per_call")
        if not _number(rate):
            tool_cost = None
            reasons.append(f"도구 {name}: 호출 단가 누락")
        elif tool_cost is not None:
            tool_cost += rate
    return model_cost, tool_cost, _unique(reasons)


def _elapsed(start, end):
    try:
        value = (
            datetime.fromisoformat(end) - datetime.fromisoformat(start)
        ).total_seconds()
        return value if _number(value) else None
    except (TypeError, ValueError):
        return None


def _measurement(case, report, pricing) -> ExecutionMeasurement:
    run = report.get("run", {})
    expected = _expectations(case)
    evidence = _mapping(report.get("evidence"))
    spans, conflicting = _span_records(report)
    roots = [s for s in spans if s.get("kind") == "execution"]
    legacy = False
    if not roots:
        roots = [s for s in spans if s.get("kind") == "evaluation"]
        legacy = bool(roots)
    root = roots[0] if len(roots) == 1 else {}
    initial = _mapping(_mapping(root.get("input")).get("initial_state"))
    final = _mapping(report.get("state")) or _mapping(
        _mapping(root.get("output")).get("state")
    )
    started = evidence.get(
        "entry_observed",
        bool(
            root
            or any(s.get("kind") == "node" or s.get("kind") == "agent" for s in spans)
        ),
    )
    ended = bool(root.get("ended_at"))
    reasons = []
    if conflicting or len(roots) != 1:
        reasons.append("실행 경계 또는 호출 식별자가 누락되거나 상충합니다.")
    reasons.extend(conflicting)
    if legacy:
        reasons.append(
            "기존 evaluation 경계 시간은 실행 준비를 포함하므로 진단용입니다."
        )
    intact = (
        bool(root)
        and not conflicting
        and evidence.get("complete", True)
        and not (_mapping(report.get("trace")).get("recovery_issues"))
    )
    if not intact:
        reasons.append("추적 증거가 불완전하여 관측량과 최종 사용량을 구분합니다.")
    observed_at = evidence.get("observed_at") or evidence.get("last_observed_at")
    elapsed = root.get("elapsed_seconds")
    if not _number(elapsed):
        elapsed = _elapsed(root.get("started_at"), root.get("ended_at") or observed_at)
    calls = _calls(spans)
    counts = Counter(span.get("kind") for span in calls)
    models = [span for span in calls if span.get("kind") == "model"]
    tools = [span for span in calls if span.get("kind") == "tool"]
    tokens = _token_values(models)
    missing = {
        key: sum(value is None for value in values) for key, values in tokens.items()
    }
    measured = {
        key: sum(value for value in values if value is not None)
        for key, values in tokens.items()
    }
    totals = {
        key: measured[key] if intact and not missing[key] else None for key in tokens
    }
    before = _mapping(_mapping(initial.get("execution")).get("budget"))
    observed_state = next(
        (
            s["output"]["observed_state"]
            for s in reversed(spans)
            if isinstance(s.get("output"), dict)
            and isinstance(s["output"].get("observed_state"), dict)
        ),
        None,
    )
    after = _mapping(_mapping((observed_state or final).get("execution")).get("budget"))
    budget_delta = {}
    for key in before.keys() | after.keys():
        previous, current = (
            _mapping(before.get(key)).get("used"),
            _mapping(after.get(key)).get("used"),
        )
        budget_delta[key] = (
            current - previous
            if _number(previous) and _number(current) and current >= previous
            else None
        )
    retries = budget_delta.get("retries") if ended and intact else None
    reasons.append(
        "재시도 수는 이번 진입의 명시적 예산 증가분입니다. "
        "여러 호출에 걸친 보완과 독립적인 새 작업을 기록만으로 모두 구분할 수 없으며, "
        "같은 작업·인자만으로 추가 재시도를 추정하지 않습니다."
    )
    model_cost, tool_cost, price_reasons = _costs(models, tools, pricing, intact)
    reasons.extend(price_reasons)
    input_records = initial.get("results")
    report_input = next(
        (
            _mapping(r.get("output"))
            for r in (input_records if isinstance(input_records, list) else [])
            if isinstance(r, dict) and r.get("decision") == "report_input"
        ),
        {},
    )
    return {
        "case_id": case["id"],
        "run_id": run.get("id"),
        "repetition": run.get("repetition"),
        "unit": case["unit"],
        "target": case["target"],
        "role": run.get("role"),
        "dependencies": run.get("dependencies", "unknown"),
        "situation": expected.get("situation"),
        "entry": expected.get("entry"),
        "environment": expected.get("environment"),
        "data_size": expected.get("data_size"),
        "dong_code": report_input.get("dongCode")
        if isinstance(report_input.get("dongCode"), str)
        else None,
        "month": report_input.get("month")
        if isinstance(report_input.get("month"), str)
        else None,
        "started": started,
        "ended": ended,
        "returned": run.get("status") == "returned",
        "evidence_complete": intact,
        "outcome": _outcome(report, final, ended),
        "returned_status": _mapping(final.get("execution")).get("status"),
        "elapsed_seconds": elapsed,
        "observed_at": observed_at,
        "timing_scope": "evaluation_with_preparation"
        if legacy
        else ("execution" if root else None),
        "model_calls": counts["model"] if intact else None,
        "tool_calls": counts["tool"] if intact else None,
        "agent_calls": counts["agent"] if intact else None,
        "node_entries": counts["node"] if intact else None,
        "retries": retries,
        "budget_delta": budget_delta,
        **totals,
        "observed_tokens": {
            key: measured[key]
            if any(value is not None for value in tokens[key])
            or (intact and not models)
            else None
            for key in tokens
        },
        "missing_token_calls": missing,
        "observed_calls": {
            key: counts[key] for key in ("model", "tool", "agent", "node")
        },
        "model_cost": model_cost,
        "tool_cost": tool_cost,
        "cost": model_cost + tool_cost
        if model_cost is not None and tool_cost is not None
        else None,
        "currency": pricing.get("currency") if pricing else None,
        "failed_calls": dict(
            Counter(s.get("kind") for s in calls if s.get("status") == "error")
        ),
        "reasons": _unique(reasons),
    }


def _report_completion(runs, assessments):
    reports = [
        run
        for run in runs
        if run["unit"] == "workflow" and run["target"] == "report" and run["started"]
    ]
    count = 0
    for run in reports:
        matching = _unique(
            [
                item
                for item in assessments
                if (item.get("case_id"), item.get("repetition"), item.get("run_id"))
                == (run["case_id"], run["repetition"], run["run_id"])
            ]
        )
        if len(matching) != 1 or not run["ended"]:
            continue
        result = matching[0]
        passed = {
            c["check"]
            for c in result.get("checks", [])
            if c.get("verdict") == "통과" and c.get("complete")
        }
        if (
            result.get("report_completeness") == "complete"
            and ({"EX-R4", "EX-R5", "EX-5"} <= passed)
            and run["returned"]
        ):
            count += 1
    return _rate(count, len(reports))


def _group(runs, assessments) -> OperationalGroup:
    started = [run for run in runs if run["started"]]
    ended = [run for run in started if run["ended"]]
    measured = [run for run in ended if run["outcome"] != "evaluation_failure"]
    outcomes = Counter(run["outcome"] for run in started)
    failure_rate = _rate(outcomes["technical_failure"], len(measured))
    if outcomes["unclassified"]:
        failure_rate["rate"] = None
    return {
        "conditions": {key: runs[0][key] for key in CONDITIONS},
        "started": len(started),
        "ended": len(ended),
        "unfinished": len(started) - len(ended),
        "outcomes": {
            key: _rate(count, len(started)) for key, count in outcomes.items()
        },
        "failure_rate": {
            **failure_rate,
            "unclassified_count": outcomes["unclassified"],
            "evaluation_failure_count": outcomes["evaluation_failure"],
            "unfinished_count": outcomes["unfinished"],
        },
        "measurements": {
            key: _statistics(run[key] for run in measured) for key in MEASURES
        },
        "elapsed_by_outcome": {
            outcome: _statistics(
                run["elapsed_seconds"] for run in measured if run["outcome"] == outcome
            )
            for outcome in sorted({r["outcome"] for r in measured})
        },
        "report_completion": _report_completion(started, assessments),
        "runs": runs,
    }


def _goal(goal, cases, repeat, runs) -> GoalSummary:
    eligible = {
        case["id"]
        for case in cases
        if supported(case) and case["target"] == goal["target"]
    }
    selected = [
        run
        for run in runs
        if run["case_id"] in goal["case_ids"]
        and run["case_id"] in eligible
        and run["target"] == goal["target"]
    ]
    planned = {
        (case_id, i) for case_id in goal["case_ids"] for i in range(1, repeat + 1)
    }
    observed = {(run["case_id"], run["repetition"]) for run in selected if run["ended"]}
    reasons = []
    if not planned or planned - observed:
        reasons.append("예정한 사례·반복의 종료 측정이 완료되지 않았습니다.")
    if not set(goal["case_ids"]) <= {case["id"] for case in cases}:
        reasons.append("운영 목표의 사례가 선택한 실행 계획에 없습니다.")
    if any(
        case["id"] in goal["case_ids"]
        and (not supported(case) or case["target"] != goal["target"])
        for case in cases
    ):
        reasons.append(
            "역할 단독 운영 진단은 요청·보고서 전체의 운영 합격 대상이 아닙니다."
        )
    for key in ("environment", "data_size"):
        if not goal.get(key):
            reasons.append(f"시험 조건 미확정: {key}")
        if any(not run[key] for run in selected):
            reasons.append(f"실행의 시험 조건이 기록되지 않았습니다: {key}")
        if any(run[key] is not None and run[key] != goal.get(key) for run in selected):
            reasons.append(f"운영 목표와 실행의 {key} 조건이 다릅니다.")
    if any(run["dependencies"] != "real" for run in selected):
        reasons.append("모의 연결 측정은 실제 환경의 운영 합격에 사용하지 않습니다.")
    if any(not run["evidence_complete"] for run in selected):
        reasons.append("필수 실행 증거의 무결성과 전체 호출 수를 확인하지 못했습니다.")
    if len({(r["situation"], r["entry"]) for r in selected}) > 1:
        reasons.append("시험 상황·최초 진입과 재진입을 구분해 목표를 지정해야 합니다.")
    if any(r["outcome"] in {"unclassified", "evaluation_failure"} for r in selected):
        reasons.append("분류하지 못한 종료 또는 평가 과정 실패가 있습니다.")
    metric, statistic = goal["metric"], goal.get("statistic")
    ended = [
        run
        for run in selected
        if run["ended"] and run["outcome"] not in {"unclassified", "evaluation_failure"}
    ]
    group = goal.get("group")
    samples = [
        r
        for r in ended
        if not group
        or (
            r["outcome"] in NORMAL_OUTCOMES
            if group == "normal"
            else r["outcome"] == group
        )
    ]
    value, maximum = None, None
    if metric == "failure_rate":
        all_ended = [
            run
            for run in selected
            if run["ended"] and run["outcome"] != "evaluation_failure"
        ]
        value = (
            None
            if any(r["outcome"] == "unclassified" for r in all_ended)
            else _rate(
                sum(r["outcome"] == "technical_failure" for r in all_ended),
                len(all_ended),
            )["rate"]
        )
        maximum = goal.get("max_rate")
        samples = all_ended
    else:
        measure = {"latency": "elapsed_seconds", "cost": "cost"}.get(
            metric, goal.get("measure")
        )
        if measure == "elapsed_seconds" and any(
            r["timing_scope"] != "execution" for r in samples
        ):
            reasons.append("준비 시간을 분리한 실제 실행 경계 측정이 필요합니다.")
        values = [r.get(measure) for r in samples]
        if any(not _number(v) for v in values):
            reasons.append("필수 운영 지표의 측정값이 누락되었습니다.")
        stats = _statistics(values)
        if metric == "repeat_spread":
            maximum = goal.get("max_spread")
            spreads = []
            for case_id in goal["case_ids"]:
                same = [r.get(measure) for r in samples if r["case_id"] == case_id]
                if (
                    len(same) != repeat
                    or repeat < 2
                    or any(not _number(v) for v in same)
                ):
                    reasons.append(
                        "반복 편차는 같은 사례의 2회 이상 전체 반복 측정이 필요합니다."
                    )
                elif same:
                    spreads.append(max(same) - min(same))
            value = max(spreads) if spreads else None
        else:
            value = stats.get(statistic)
            maximum = goal.get("max_seconds" if metric == "latency" else "max_cost")
            if statistic not in {"median", "p95", "mean"}:
                reasons.append("판정 통계값을 확정해야 합니다.")
    if not _number(maximum):
        reasons.append("운영 지표의 허용 상한이 지정되지 않았습니다.")
    if not samples or value is None:
        reasons.append("지정한 조건의 측정 표본이 없습니다.")
    complete = not reasons
    # 일부 표본의 p95·실패율은 미실행 반복을 포함한 목표값을 확정하지 않는다.
    failed = complete and value > maximum
    return {
        "target": goal["target"],
        "metric": metric,
        "case_ids": goal["case_ids"],
        "statistic": statistic,
        "value": value,
        "maximum": maximum,
        "sample_count": len(samples),
        "verdict": "실패" if failed else ("통과" if complete else "미판정"),
        "complete": complete,
        "reasons": _unique(reasons),
    }


def summarize_executions(
    cases,
    repeat,
    assessments,
    reports,
    goals=None,
    pricing=None,
) -> ExecutionSummary:
    """업무 State를 변경하지 않고 계획 분모와 기능·운영 판정을 각각 보존한다."""
    if type(repeat) is not int or repeat < 1:
        raise ValueError("repeat must be a positive integer")
    selected = [case for case in cases if operational_supported(case)]
    by_id = {case["id"]: case for case in selected}
    indexed = defaultdict(list)
    for report in reports:
        run = report.get("run", {})
        if (
            run.get("case_id") in by_id
            and type(run.get("repetition")) is int
            and (1 <= run["repetition"] <= repeat)
        ):
            indexed[run["case_id"], run["repetition"]].append(report)
    runs, reasons = [], []
    for (case_id, _), records in indexed.items():
        distinct = _unique(records)
        if len(distinct) != 1:
            reasons.append(f"{case_id}: 같은 예정 반복의 실행 증거가 상충합니다.")
            # 시작이 확인된 작성 실행은 증거 충돌 때문에 완성률 분모에서 빼지 않는다.
            observed = [
                _measurement(by_id[case_id], item, pricing) for item in distinct
            ]
            run_info = distinct[0]["run"]
            conflicting = _measurement(
                by_id[case_id],
                {
                    "run": {
                        "case_id": case_id,
                        "repetition": run_info["repetition"],
                        "id": run_info.get("id")
                        if len({item["run_id"] for item in observed}) == 1
                        else None,
                        "status": "running",
                    },
                    "trace": {"spans": []},
                    "evidence": {
                        "complete": False,
                        "entry_observed": any(item["started"] for item in observed),
                    },
                },
                pricing,
            )
            conflicting["ended"] = all(item["ended"] for item in observed)
            conflicting["outcome"] = (
                "unclassified" if conflicting["ended"] else "unfinished"
            )
            conflicting["reasons"].append(reasons[-1])
            runs.append(conflicting)
            continue
        runs.append(_measurement(by_id[case_id], distinct[0], pricing))
    return summarize_measurements(selected, repeat, assessments, runs, goals, reasons)


def summarize_measurements(
    cases, repeat, assessments, runs, goals=None, reasons=None
) -> ExecutionSummary:
    """저장된 실행별 측정·판정을 재사용해 선택 범위의 집계만 만든다."""
    selected = [case for case in cases if operational_supported(case)]
    reasons = list(reasons or [])
    grouped = defaultdict(list)
    for run in runs:
        grouped[tuple(run[key] for key in CONDITIONS)].append(run)
    repetitions = []
    for case in selected:
        matching = [run for run in runs if run["case_id"] == case["id"]]
        finished = [
            run
            for run in matching
            if run["ended"] and run["outcome"] != "evaluation_failure"
        ]
        repetitions.append(
            {
                "case_id": case["id"],
                "planned": repeat,
                "started": sum(run["started"] for run in matching),
                "ended": sum(run["ended"] for run in matching),
                "unfinished": sum(
                    run["started"] and not run["ended"] for run in matching
                ),
                "missing_repetitions": sorted(
                    set(range(1, repeat + 1))
                    - {run["repetition"] for run in matching if run["started"]}
                ),
                "measurements": {
                    key: _statistics(run[key] for run in finished) for key in MEASURES
                },
                "runs": matching,
            }
        )
    performance = [_goal(goal, selected, repeat, runs) for goal in goals or []]
    complete = (
        bool(performance)
        and all(item["complete"] for item in performance)
        and not reasons
    )
    failed = any(item["verdict"] == "실패" for item in performance)
    if not performance:
        reasons.append("사전에 지정한 필수 운영 목표가 없어 운영 합격은 미판정입니다.")
    return {
        "functional": _functional(selected, repeat, assessments),
        "report_completion": _report_completion(runs, assessments),
        "operational": {
            "measurement_scope": "execution",
            "verdict": "실패" if failed else ("통과" if complete else "미판정"),
            "complete": complete,
            "groups": [_group(group, assessments) for group in grouped.values()],
            "repetitions": repetitions,
            "goals": performance,
            "runs": runs,
            "unfinished_usage": [
                run for run in runs if run["started"] and not run["ended"]
            ],
            "reasons": reasons,
        },
    }
