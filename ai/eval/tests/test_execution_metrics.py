"""실행 평가의 계획 분모·전체 실행 경계·누락 사용량을 검증한다."""

from collections import Counter
from copy import deepcopy

import pytest

from eval.execution.metrics import summarize_executions


def case(case_id="request", *, target="request", checks=None, **conditions):
    return {
        "id": case_id,
        "unit": "workflow" if target == "report" else "agent",
        "target": target,
        "assessment": {
            "required": True,
            "checks": ["EX-1"] if checks is None else checks,
            "expected": {
                "schema_version": "execution-expectations-v1",
                "situation": "normal",
                "entry": "initial",
                "environment": "local",
                "data_size": "one request",
                **conditions,
            },
        },
    }


def assessment(case_id="request", repetition=1, *, verdict="통과", checks=None):
    return {
        "case_id": case_id,
        "run_id": f"{case_id}-{repetition}",
        "repetition": repetition,
        "verdict": verdict,
        "complete": verdict != "미판정",
        "started": True,
        "report_completeness": "complete",
        "checks": [
            {
                "check": name,
                "verdict": verdict,
                "executed": True,
                "complete": verdict != "미판정",
                "reason": "boundary checked",
                "details": [],
            }
            for name in (checks or ["EX-1"])
        ],
    }


def state(status="completed", *, used=0, code=None):
    return {
        "request": {"goal": "review"},
        "results": [],
        "messages": [],
        "response": {"kind": "question" if status == "waiting_input" else "final"},
        "execution": {
            "status": status,
            "error": {"code": code} if code else None,
            "budget": {
                key: {"used": used, "limit": 100}
                for key in ("steps", "retries", "tool_calls", "agent_calls")
            },
        },
    }


def span(identity, kind, name, parent="execution", *, tokens=None, elapsed=2):
    result = {
        "id": identity,
        "parent_id": parent,
        "kind": kind,
        "name": name,
        "started_at": "2026-11-12T00:00:00+00:00",
        "ended_at": "2026-11-12T00:00:02+00:00",
        "elapsed_seconds": elapsed,
        "status": "success",
        "input": {},
        "output": {},
    }
    if kind == "model":
        result["output"] = {
            "sdk_response": {
                "usage_metadata": tokens,
                "response_metadata": {"model_name": "test-model"},
            }
        }
    elif kind in {"agent", "node"}:
        result["input"] = {
            "state" if kind == "node" else "initial_state": state("running")
        }
    return result


def report(
    case_id="request",
    repetition=1,
    *,
    target="request",
    status="completed",
    code=None,
    elapsed=2,
    initial_used=0,
    final_used=2,
    calls=None,
):
    initial = state("queued", used=initial_used)
    final = state(status, used=final_used, code=code)
    root = span("execution", "execution", target, None, elapsed=elapsed)
    root["input"] = {"initial_state": initial}
    root["output"] = {"state": deepcopy(final)}
    spans = [root, *(calls or [])]
    sequences = {}
    for item in spans:
        sequences.setdefault(item["id"], len(sequences) + 1)
        item["sequence"] = sequences[item["id"]]
    unique = list({item["id"]: item for item in spans}.values())
    models = [item for item in unique if item["kind"] == "model"]
    return {
        "run": {
            "id": f"{case_id}-{repetition}",
            "case_id": case_id,
            "repetition": repetition,
            "unit": "workflow" if target == "report" else "agent",
            "target": target,
            "role": "request" if target == "request" else None,
            "status": "returned",
            "dependencies": "real",
            "ended_at": root["ended_at"],
            "elapsed_seconds": elapsed + 5,
        },
        "state": final,
        "failure": None,
        "trace": {
            "spans": spans,
            "counts": dict(Counter(item["kind"] for item in unique)),
            "coverage": {
                "model_attempts": len(models),
                "model_inputs": sum("messages" in item["input"] for item in models),
                "http_requests": sum("http_request" in item for item in models),
                "http_responses": sum("http_response" in item for item in models),
                "sdk_responses": sum("output" in item for item in models),
                "model_errors": sum(item["status"] == "error" for item in models),
                "unfinished_spans": sum(item["ended_at"] is None for item in unique),
            },
        },
    }


def goal(metric="latency", **options):
    return {
        "target": "request",
        "case_ids": ["request"],
        "metric": metric,
        "statistic": "p95",
        "max_seconds": 4,
        "environment": "local",
        "data_size": "one request",
        **options,
    }


def test_failure_precedes_incomplete_and_rates_exclude_unknown_repetitions():
    results = summarize_executions(
        [case(), case("unrun")],
        2,
        [assessment(verdict="실패")],
        [report()],
    )["functional"]
    assert results["verdict"] == "실패"
    assert results["complete"] is False
    assert results["cases"]["denominator"] == 1
    assert results["cases"]["failed"] == 1
    assert results["cases"]["undetermined"] == 1
    assert results["verification"] == {
        "required_cases": 2,
        "completed_cases": 0,
        "incomplete_cases": 2,
        "missing_repetitions": 3,
    }
    check = results["checks"][0]
    assert (check["denominator"], check["failed"], check["undetermined"]) == (1, 1, 3)


def test_all_planned_checks_required_even_if_run_claims_complete():
    result = summarize_executions(
        [case(checks=["EX-1", "EX-2"])],
        1,
        [assessment()],
        [report()],
    )["functional"]
    assert result["verdict"] == "미판정"
    assert result["cases"]["denominator"] == 0
    assert result["cases"]["rate"] is None
    assert result["checks"][1]["unexecuted"] == 1


def test_nonapplicable_check_keeps_reason_outside_rate():
    judged = assessment(checks=["EX-1", "EX-4"])
    judged["checks"][1].update(
        verdict="비적용", executed=False, reason="No interruption"
    )
    result = summarize_executions(
        [case(checks=["EX-1", "EX-4"])],
        1,
        [judged],
        [report()],
    )["functional"]
    assert result["verdict"] == "통과"
    assert result["checks"][1]["denominator"] == 0
    assert result["checks"][1]["not_applicable"] == 1
    assert result["checks"][1]["reasons"] == ["No interruption"]


def test_conflicting_assessments_preserve_failure_and_incomplete():
    result = summarize_executions(
        [case()],
        1,
        [assessment(), assessment(verdict="실패")],
        [report()],
    )["functional"]
    assert result["verdict"] == "실패"
    assert result["complete"] is False
    assert result["checks"][0]["failed"] == 1


def test_report_completion_requires_return_and_three_passed_checks():
    names = ["EX-R4", "EX-R5", "EX-5"]
    cases = [
        case(name, target="report", checks=names)
        for name in ("full", "partial", "error")
    ]
    judgments = [
        assessment(name, checks=names) for name in ("full", "partial", "error")
    ]
    judgments[1]["report_completeness"] = "partial"
    reports = [report(name, target="report") for name in ("full", "partial", "error")]
    reports[2]["run"]["status"] = "error"
    reports[2]["failure"] = {"type": "RuntimeError"}
    summary = summarize_executions(cases, 1, judgments, reports)
    assert summary["report_completion"] == {
        "numerator": 1,
        "denominator": 3,
        "rate": 1 / 3,
    }
    assert summary["functional"]["verdict"] == "통과"


def test_whole_execution_time_and_calls_do_not_sum_parent_or_role_totals():
    calls = [
        span("outer-node", "node", "act"),
        span("role", "agent", "report_selection_agent", "outer-node"),
        span("child", "agent", "interpretation_agent", "role"),
        span("child-node", "node", "act", "child"),
        span(
            "model",
            "model",
            "model",
            "child-node",
            tokens={"input_tokens": 11, "output_tokens": 7},
        ),
        span("tool", "tool", "query_data", "child-node"),
        span("nested-tool", "tool", "query_data", "tool"),
    ]
    calls.append(deepcopy(calls[4]))
    data = report(calls=calls, elapsed=6, initial_used=10, final_used=12)
    result = summarize_executions([case(entry="reentry")], 1, [], [data])
    run = result["operational"]["runs"][0]
    assert (run["elapsed_seconds"], run["model_calls"], run["tool_calls"]) == (6, 1, 1)
    assert (run["agent_calls"], run["node_entries"], run["retries"]) == (1, 2, 2)
    assert run["input_tokens"] == 11
    assert run["output_tokens"] == 7
    assert run["budget_delta"]["steps"] == 2
    assert result["operational"]["verdict"] == "미판정"


def test_input_and_output_token_missingness_are_independent():
    data = report(calls=[span("m", "model", "model", tokens={"input_tokens": 15})])
    result = summarize_executions([case()], 1, [], [data])
    run = result["operational"]["runs"][0]
    assert run["input_tokens"] == 15
    assert run["output_tokens"] is None
    assert run["missing_token_calls"] == {"input_tokens": 0, "output_tokens": 1}
    stats = result["operational"]["groups"][0]["measurements"]
    assert stats["output_tokens"]["sample_count"] == 0
    assert stats["output_tokens"]["missing_count"] == 1


def test_cost_requires_each_model_direction_and_each_tool_rate():
    data = report(
        calls=[
            span(
                "m", "model", "model", tokens={"input_tokens": 100, "output_tokens": 20}
            ),
            span("t", "tool", "query_data"),
        ]
    )
    prices = {
        "version": "test",
        "currency": "USD",
        "models": {"test-model": {"input_per_million": 2, "output_per_million": 10}},
        "tools": {"query_data": {"per_call": 0}},
    }
    run = summarize_executions([case()], 1, [], [data], pricing=prices)["operational"][
        "runs"
    ][0]
    assert run["cost"] == pytest.approx(0.0004)
    prices["tools"].clear()
    run = summarize_executions([case()], 1, [], [data], pricing=prices)["operational"][
        "runs"
    ][0]
    assert run["model_cost"] == pytest.approx(0.0004)
    assert run["tool_cost"] is None
    assert run["cost"] is None


def test_six_agent_roles_keep_usage_and_only_request_functional_denominator():
    roles = (
        "request",
        "interpretation",
        "visualization",
        "report_selection",
        "report_description",
        "report_insight",
    )
    cases = [case(role, target=role) for role in roles]
    for item in cases[1:]:
        item.pop("assessment")
    reports = [
        report(
            role,
            target=role,
            calls=[
                span(
                    "model",
                    "model",
                    "model",
                    tokens={"input_tokens": 100, "output_tokens": 20},
                ),
                span("tool", "tool", "query_data"),
            ],
        )
        for role in roles
    ]
    prices = {
        "version": "test",
        "currency": "USD",
        "models": {"test-model": {"input_per_million": 2, "output_per_million": 10}},
        "tools": {"query_data": {"per_call": 0}},
    }
    # 역할 단독 실행에 잘못 붙은 판정도 EX 기능 분모를 늘리지 않는다.
    assessments = [assessment(role) for role in roles]
    result = summarize_executions(cases, 1, assessments, reports, pricing=prices)
    assert result["functional"]["verdict"] == "통과"
    assert result["functional"]["verification"]["required_cases"] == 1
    assert [item["case_id"] for item in result["functional"]["cases"]["items"]] == [
        "request"
    ]
    assert result["report_completion"] == {
        "numerator": 0,
        "denominator": 0,
        "rate": None,
    }
    runs = result["operational"]["runs"]
    assert {item["target"] for item in runs} == set(roles)
    assert len(result["operational"]["groups"]) == len(roles)
    assert all(item["model_calls"] == item["tool_calls"] == 1 for item in runs)
    assert all(item["elapsed_seconds"] == 2 for item in runs)
    assert all(
        item["input_tokens"] == 100 and item["output_tokens"] == 20 for item in runs
    )
    assert all(item["cost"] == pytest.approx(0.0004) for item in runs)


def test_role_diagnostics_keep_planned_repetitions_without_functional_or_goal_pass():
    selected = {"id": "specialist", "unit": "agent", "target": "interpretation"}
    result = summarize_executions(
        [selected],
        2,
        [],
        [report("specialist", target="interpretation")],
    )
    assert result["functional"]["verdict"] == "미판정"
    assert result["functional"]["complete"] is False
    assert result["functional"]["cases"]["denominator"] == 0
    assert result["functional"]["checks"] == []
    assert result["operational"]["verdict"] == "미판정"
    assert result["operational"]["repetitions"][0]["missing_repetitions"] == [2]
    assert result["operational"]["repetitions"][0]["planned"] == 2

    # 입력 스키마를 우회한 직접 집계에서도 역할 진단에 운영 합격을 부여하지 않는다.
    invalid = goal(target="interpretation", case_ids=["specialist"])
    selected["assessment"] = case()["assessment"]
    result = summarize_executions(
        [selected],
        1,
        [],
        [report("specialist", target="interpretation")],
        goals=[invalid],
    )
    measured = result["operational"]["goals"][0]
    assert measured["verdict"] == "미판정"
    assert measured["sample_count"] == 0
    assert any("운영 합격 대상" in reason for reason in measured["reasons"])


def test_technical_failure_uses_preserved_cause_even_for_partial_return():
    data = report(status="partial", code="execution_limit_exceeded")
    run = summarize_executions([case()], 1, [], [data])["operational"]["runs"][0]
    assert run["outcome"] == "technical_failure"
    assert run["returned_status"] == "partial"


@pytest.mark.parametrize(
    "status,outcome",
    [
        ("completed", "completed"),
        ("partial", "partial"),
        ("waiting_input", "question"),
        ("cancelled", "cancelled"),
    ],
)
def test_handled_child_error_does_not_change_normal_parent_result(status, outcome):
    child = span("tool", "tool", "query_data")
    child.update(status="error", error={"type": "TimeoutError"})
    data = report(status=status, calls=[child])
    result = summarize_executions([case()], 1, [], [data])["operational"]
    assert result["runs"][0]["outcome"] == outcome
    assert result["groups"][0]["failure_rate"]["numerator"] == 0
    assert result["runs"][0]["failed_calls"] == {"tool": 1}


def test_evaluation_failure_is_outside_business_failure_rate():
    data = report()
    data["run"]["status"] = "error"
    data["failure"] = {"code": "unexpected_stub_call"}
    operational = summarize_executions([case()], 1, [], [data])["operational"]
    failure = operational["groups"][0]["failure_rate"]
    assert failure["evaluation_failure_count"] == 1
    assert failure["denominator"] == 0
    assert failure["rate"] is None


def test_unfinished_measurement_preserves_observed_usage_outside_finished_statistics():
    data = report(calls=[span("m", "model", "model", tokens={"input_tokens": 8})])
    data["trace"]["spans"][0].update(
        ended_at=None, elapsed_seconds=None, status="running"
    )
    data["run"].update(status="running", ended_at=None)
    data["evidence"] = {"complete": False, "observed_at": "2026-11-12T00:00:05+00:00"}
    operational = summarize_executions([case()], 1, [], [data])["operational"]
    run = operational["unfinished_usage"][0]
    assert run["outcome"] == "unfinished"
    assert run["elapsed_seconds"] == 5
    assert run["observed_tokens"]["input_tokens"] == 8
    assert run["observed_calls"]["model"] == 1
    assert run["input_tokens"] is None
    assert operational["groups"][0]["measurements"]["input_tokens"]["sample_count"] == 0
    assert operational["groups"][0]["failure_rate"]["denominator"] == 0


def test_cancelled_node_snapshot_preserves_usage_since_last_completed_node():
    node = span("n", "node", "act")
    node["output"] = {"observed_state": state("running", used=14)}
    data = report(status="cancelled", initial_used=10, final_used=12, calls=[node])
    data["run"]["status"] = "cancelled"
    run = summarize_executions([case()], 1, [], [data])["operational"]["runs"][0]
    assert run["budget_delta"]["steps"] == 4
    assert data["state"]["execution"]["budget"]["steps"]["used"] == 12


def test_real_and_mock_fault_conditions_are_separate_groups():
    cases = [case("normal"), case("fault", situation="fault")]
    reports = [report("normal"), report("fault")]
    reports[1]["run"]["dependencies"] = "stub"
    groups = summarize_executions(cases, 1, [], reports)["operational"]["groups"]
    assert len(groups) == 2
    assert [
        (g["conditions"]["dependencies"], g["conditions"]["situation"]) for g in groups
    ] == [("real", "normal"), ("stub", "fault")]


def test_regions_and_months_share_statistics_from_individual_execution_values():
    locations = [
        ("1111051500", "2026-09"),
        ("1111051500", "2026-09"),
        ("1111051500", "2026-10"),
        ("1111053000", "2026-09"),
    ]
    reports = []
    for repetition, ((dong_code, month), elapsed) in enumerate(
        zip(locations, [1, 3, 20, 100], strict=True), start=1
    ):
        data = report(repetition=repetition, target="report", elapsed=elapsed)
        initial = data["trace"]["spans"][0]["input"]["initial_state"]
        initial["results"] = [
            {
                "decision": "report_input",
                "output": {"dongCode": dong_code, "month": month},
            }
        ]
        reports.append(data)
    originals = deepcopy(reports)

    operational = summarize_executions(
        [case(target="report", data_size="one report")], 4, [], reports
    )["operational"]

    assert len(operational["groups"]) == 1
    group = operational["groups"][0]
    assert "dong_code" not in group["conditions"]
    assert "month" not in group["conditions"]
    assert group["started"] == group["ended"] == 4
    assert group["measurements"]["elapsed_seconds"] == {
        "sample_count": 4,
        "missing_count": 0,
        "mean": 31,
        "median": 11.5,
        "p95": 100,
        "minimum": 1,
        "maximum": 100,
    }
    assert group["runs"] == operational["runs"]
    assert [(run["dong_code"], run["month"]) for run in group["runs"]] == locations
    assert reports == originals


def test_operating_goal_uses_execution_time_and_all_planned_repetitions():
    reports = [report(repetition=1, elapsed=2), report(repetition=2, elapsed=3)]
    operational = summarize_executions([case()], 2, [], reports, [goal()])[
        "operational"
    ]
    assert operational["verdict"] == "통과"
    assert operational["goals"][0]["value"] == 3
    incomplete = summarize_executions([case()], 3, [], reports, [goal(max_seconds=1)])
    assert incomplete["operational"]["verdict"] == "미판정"


def test_stub_and_legacy_timing_cannot_pass_actual_operation_goal():
    data = report()
    data["run"]["dependencies"] = "stub"
    data["trace"]["spans"][0]["kind"] = "evaluation"
    data["trace"]["counts"] = {"evaluation": 1}
    operational = summarize_executions([case()], 1, [], [data], [goal()])["operational"]
    assert operational["verdict"] == "미판정"
    assert len(operational["goals"][0]["reasons"]) == 2


def test_failure_rate_and_repeat_spread_goals():
    reports = [
        report(repetition=1),
        report(repetition=2, elapsed=10, code="runtime_error"),
    ]
    failure_goal = goal("failure_rate", max_rate=0.2)
    spread_goal = goal("repeat_spread", measure="elapsed_seconds", max_spread=3)
    result = summarize_executions([case()], 2, [], reports, [failure_goal, spread_goal])
    goals = result["operational"]["goals"]
    assert [(g["value"], g["verdict"]) for g in goals] == [(0.5, "실패"), (8, "실패")]


def test_excluded_goal_case_and_corrupt_trace_remain_unmeasured():
    data = report(calls=[span("m", "model", "model", tokens={"input_tokens": 8})])
    data["trace"]["recovery_issues"] = ["truncated record"]
    operational = summarize_executions(
        [case()],
        1,
        [],
        [data],
        [goal(case_ids=["request", "excluded"])],
    )["operational"]
    assert operational["verdict"] == "미판정"
    assert operational["runs"][0]["input_tokens"] is None
    assert operational["runs"][0]["model_calls"] is None


def test_execution_not_entered_is_outside_report_completion_denominator():
    data = report(target="report")
    data["trace"]["spans"].clear()
    data["evidence"] = {"complete": False, "entry_observed": False}
    result = summarize_executions([case(target="report")], 1, [], [data])
    assert result["report_completion"]["denominator"] == 0
    assert result["operational"]["groups"][0]["started"] == 0


def test_empty_plan_and_invalid_repeat_do_not_create_pass():
    result = summarize_executions([], 1, [], [])
    assert result["functional"]["verdict"] == "미판정"
    assert result["functional"]["cases"]["rate"] is None
    with pytest.raises(ValueError):
        summarize_executions([], 0, [], [])


def test_conflicting_started_reports_remain_in_completion_denominator():
    original = report(target="report")
    conflicting = deepcopy(original)
    conflicting["state"]["execution"]["status"] = "partial"
    result = summarize_executions(
        [case(target="report")],
        1,
        [],
        [original, conflicting],
    )
    assert result["report_completion"] == {
        "numerator": 0,
        "denominator": 1,
        "rate": 0,
    }
    run = result["operational"]["runs"][0]
    assert run["outcome"] == "unclassified"
    assert run["input_tokens"] is None
    assert run["observed_tokens"]["input_tokens"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_status",
        "missing_parent",
        "cycle",
        "missing_model",
        "coverage_mismatch",
        "missing_counts",
        "missing_coverage",
        "sequence_gap",
    ],
)
def test_incomplete_call_evidence_cannot_understate_usage_or_pass_goals(mutation):
    data = report(
        calls=[
            span(
                "m",
                "model",
                "model",
                tokens={"input_tokens": 100, "output_tokens": 50},
            )
        ]
    )
    model = data["trace"]["spans"][1]
    if mutation == "unknown_status":
        model["status"] = "unknown"
    elif mutation == "missing_parent":
        model["parent_id"] = "missing-node"
    elif mutation == "cycle":
        model["parent_id"] = model["id"]
    elif mutation == "missing_model":
        data["trace"]["spans"].pop()
    elif mutation == "coverage_mismatch":
        data["trace"]["coverage"]["model_attempts"] += 1
    elif mutation == "missing_counts":
        data["trace"].pop("counts")
    elif mutation == "missing_coverage":
        data["trace"].pop("coverage")
    else:
        model["sequence"] = 3
    prices = {
        "version": "test",
        "currency": "USD",
        "tools": {},
        "models": {"test-model": {"input_per_million": 1, "output_per_million": 1}},
    }
    result = summarize_executions([case()], 1, [], [data], [goal()], prices)[
        "operational"
    ]
    run = result["runs"][0]
    assert run["model_calls"] is None
    assert run["input_tokens"] is None
    assert run["cost"] is None
    assert run["evidence_complete"] is False
    assert result["verdict"] == "미판정"
    assert run["observed_calls"]["model"] == (0 if mutation == "missing_model" else 1)


def test_unclassified_ended_execution_keeps_failure_denominator_but_rate_unknown():
    reports = [
        report(repetition=1, code="runtime_error"),
        report(repetition=2, status="failed"),
    ]
    result = summarize_executions(
        [case()],
        2,
        [],
        reports,
        [
            goal("failure_rate", max_rate=0.5),
        ],
    )["operational"]
    rate = result["groups"][0]["failure_rate"]
    assert rate["numerator"] == 1
    assert rate["denominator"] == 2
    assert rate["unclassified_count"] == 1
    assert rate["rate"] is None
    assert result["goals"][0]["value"] is None
    assert result["goals"][0]["sample_count"] == 2
    assert result["verdict"] == "미판정"


@pytest.mark.parametrize("condition", ["environment", "data_size"])
def test_goal_condition_does_not_replace_missing_run_condition(condition):
    prepared = case()
    del prepared["assessment"]["expected"][condition]
    result = summarize_executions([prepared], 1, [], [report()], [goal()])[
        "operational"
    ]
    assert result["verdict"] == "미판정"
    assert result["goals"][0]["complete"] is False
    assert any(condition in reason for reason in result["goals"][0]["reasons"])


@pytest.mark.parametrize(
    "location",
    [
        "root_input",
        "root_output",
        "initial_state",
        "model_output",
        "sdk_response",
        "parent",
        "kind",
        "status",
    ],
)
def test_malformed_boundary_json_becomes_incomplete_instead_of_crashing(location):
    data = report(
        calls=[
            span(
                "m",
                "model",
                "model",
                tokens={"input_tokens": 100, "output_tokens": 50},
            )
        ]
    )
    root, model = data["trace"]["spans"]
    if location == "root_input":
        root["input"] = ["invalid"]
    elif location == "root_output":
        root["output"] = ["invalid"]
    elif location == "initial_state":
        root["input"]["initial_state"] = ["invalid"]
    elif location == "model_output":
        model["output"] = ["invalid"]
    elif location == "sdk_response":
        model["output"]["sdk_response"] = ["invalid"]
    elif location == "parent":
        model["parent_id"] = ["invalid"]
    else:
        model[location] = ["invalid"]
    result = summarize_executions([case()], 1, [], [data], [goal()])["operational"]
    assert result["verdict"] == "미판정"
    assert result["runs"][0]["evidence_complete"] is False
    assert result["runs"][0]["input_tokens"] is None
