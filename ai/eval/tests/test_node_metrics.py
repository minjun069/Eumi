"""판정 분모와 실제 노드 호출 경계를 합성 기록으로 확인한다."""

from copy import deepcopy

import pytest

from eval.nodes.criteria import load_criteria
from eval.nodes.evidence import extract_nodes
from eval.nodes.metrics import summarize_nodes


def case(identity="case", **changes):
    return {
        "id": identity,
        "unit": "node",
        "target": "decide",
        "role": "request",
        "assessment": {"required": True, "checks": ["N-F.1"]},
    } | changes


def assessed(identity="case", repetition=1, verdict="통과", **changes):
    return {
        "node_id": f"{identity}-{repetition}",
        "run_id": f"run-{identity}-{repetition}",
        "case_id": identity,
        "repetition": repetition,
        "node": "decide",
        "role": "request",
        "counted": True,
        "verdict": verdict,
        "complete": verdict != "미판정",
        "checks": [
            {
                "check": "N-F.1",
                "axis": "형식 준수",
                "method": "규칙 기반",
                "executed": True,
                "verdict": verdict,
                "reason": "판정",
                "details": [
                    {
                        "id": "field",
                        "executed": True,
                        "verdict": verdict,
                        "reason": "판정",
                        "evidence": ["/raw"],
                    }
                ],
            }
        ],
    } | changes


def evidence(identity="case", repetition=1, **changes):
    return {
        "id": f"{identity}-{repetition}",
        "run_id": f"run-{identity}-{repetition}",
        "case_id": identity,
        "repetition": repetition,
        "node": "decide",
        "role": "request",
        "counted": True,
        "status": "success",
        "complete": True,
        "technical_failure": False,
        "elapsed_seconds": 2.0,
        "usage": {"input_tokens": 3, "output_tokens": 2},
        "model_calls": 1,
        "technical_retries": 0,
    } | changes


def model_span(identity, name="ReportText", **changes):
    return {
        "id": identity,
        "kind": "model",
        "name": name,
        "parent_id": "node",
        "status": "success",
        "ended_at": "now",
        "elapsed_seconds": 2.0,
        "input": {"messages": [{"type": "human", "content": "actual input"}]},
        "output": {
            "sdk_response": {
                "content": "{}",
                "usage_metadata": {"input_tokens": 3, "output_tokens": 2},
            }
        },
    } | changes


def selected_evidence(planned, models, scope=None, **parent_changes):
    parent = {
        "id": "node",
        "kind": "node",
        "name": "compose",
        "parent_id": None,
        "status": "error",
        "ended_at": "now",
        "elapsed_seconds": 100,
        "input": {"role": "report_description", "state": {"results": []}},
        "error": {"type": "RuntimeError", "code": "state_application_failed"},
    } | parent_changes
    report = {
        "run": {"id": "run", "role": "report_description"},
        "trace": {"spans": [parent, *models]},
    }
    return extract_nodes(report, planned, catalog=load_criteria(), scope=scope)


def summarize(cases=None, repeat=1, assessments=None, evidences=None, **kwargs):
    return summarize_nodes(
        cases or [case()],
        repeat,
        [assessed()] if assessments is None else assessments,
        [evidence()] if evidences is None else evidences,
        **kwargs,
    )[0]


def test_repetitions_and_functionally_decided_case_denominator():
    result = summarize(
        [case("pass"), case("fail"), case("missing")],
        2,
        [
            assessed("pass", 1),
            assessed("pass", 2),
            assessed("fail", 1, "실패", complete=False),
        ],
        [],
    )
    cases = result["functional"]["cases"]
    assert (cases["numerator"], cases["denominator"], cases["rate"]) == (1, 2, 0.5)
    assert result["functional"]["verification"] == {
        "required_cases": 3,
        "completed_cases": 1,
        "incomplete_cases": 2,
        "missing_repetitions": 3,
    }
    assert result["verdict"] == "실패" and result["complete"] is False


def test_identical_repeated_records_are_not_counted_twice():
    a, n = assessed(), evidence()
    result = summarize(assessments=[a, deepcopy(a)], evidences=[n, deepcopy(n)])
    assert result["runs"] == 1
    assert result["functional"]["checks"][0]["denominator"] == 1
    assert result["functional"]["details"][0]["denominator"] == 1


def test_conflicting_record_does_not_choose_favorable_measurement():
    result = summarize(evidences=[evidence(), evidence(usage={"input_tokens": 999})])
    assert result["conflicting_evidence"]
    assert result["operational"]["tokens"]["input_tokens"]["sample_count"] == 0


def test_failure_gate_skip_is_not_pass_or_undetermined_check():
    a = assessed(verdict="실패")
    a["checks"].append(
        {
            "check": "N03-O.2",
            "axis": "내용 정확성",
            "method": "LLM 기반",
            "executed": False,
            "verdict": "미판정",
            "reason": "선행 단계 실패로 미실행",
            "details": [],
        }
    )
    result = summarize(
        [case(assessment={"required": True, "checks": ["N-F.1", "N03-O.2"]})],
        assessments=[a],
    )
    skipped = next(c for c in result["functional"]["checks"] if c["check"] == "N03-O.2")
    assert skipped["unexecuted"] == skipped["skipped_after_failure"] == 1
    assert skipped["denominator"] == skipped["undetermined"] == 0
    assert result["functional"]["verification"]["completed_cases"] == 1


def test_missing_tokens_and_retries_are_not_zero_measurements():
    result = summarize(
        evidences=[
            evidence(
                usage={"input_tokens": 0, "output_tokens": None}, technical_retries=None
            )
        ]
    )
    ops = result["operational"]
    assert ops["tokens"]["input_tokens"]["mean"] == 0
    assert ops["tokens"]["output_tokens"]["mean"] is None
    assert ops["tokens"]["output_tokens"]["missing_count"] == 1
    assert ops["technical_retries"]["missing_count"] == 1


def test_selection_and_evaluator_usage_do_not_enter_node_metrics():
    result = summarize(
        assessments=[assessed(), assessed(counted=False, node_id="selection")],
        evidences=[evidence(), evidence(counted=False, id="selection", model_calls=50)],
    )
    assert result["runs"] == 1
    assert result["operational"]["model_calls"]["mean"] == 1


def test_unknown_and_unfinished_failures_are_separate_from_normal():
    result = summarize(
        [case("a"), case("b"), case("c")],
        evidences=[
            evidence("a", status="success", technical_failure=True, elapsed_seconds=4),
            evidence("b", technical_failure=None),
            evidence("c", status="running", technical_failure=None),
        ],
    )
    ops = result["operational"]
    assert ops["failure_rate"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1,
        "missing_count": 1,
        "unfinished_count": 1,
    }
    assert ops["response_time"]["error"]["median"] == 4
    assert ops["response_time"]["normal"]["sample_count"] == 0


def test_missing_planned_node_produces_unfinished_case_not_pass():
    result = summarize(assessments=[], evidences=[])
    assert result["verdict"] == "미판정"
    assert result["functional"]["cases"]["denominator"] == 0
    assert result["functional"]["verification"]["incomplete_cases"] == 1


def test_performance_requires_all_planned_repetitions():
    goal = {
        "target": "decide",
        "role": "request",
        "group": "normal",
        "case_ids": ["case"],
        "statistic": "p95",
        "max_seconds": 3,
        "environment": "unit",
        "data_size": "small",
    }
    result = summarize(repeat=2, performance=[goal])
    assert result["performance"][0]["verdict"] == "미판정"
    result = summarize(performance=[goal])
    assert result["performance"][0]["verdict"] == "통과"


def test_failure_rate_target_does_not_pass_with_missing_classification():
    goal = {
        "target": "decide",
        "role": "request",
        "metric": "failure_rate",
        "case_ids": ["case"],
        "max_rate": 0.5,
        "environment": "unit",
        "data_size": "small",
    }
    result = summarize(evidences=[evidence(technical_failure=None)], performance=[goal])
    assert result["performance"][0]["verdict"] == "미판정"
    result = summarize(performance=[goal])
    assert result["performance"][0]["value_rate"] == 0
    assert result["operational"]["verdict"] == "통과"
    result = summarize(evidences=[evidence(technical_failure=True)], performance=[goal])
    assert result["operational"]["verdict"] == "실패"


def test_no_operational_target_keeps_operational_judgment_undetermined():
    result = summarize()
    assert result["functional"]["verdict"] == "통과"
    assert result["operational"]["verdict"] == "미판정"
    assert result["operational"]["complete"] is False


def test_one_measured_occurrence_does_not_hide_another_missing_duration():
    goal = {
        "target": "decide",
        "role": "request",
        "group": "normal",
        "case_ids": ["case"],
        "statistic": "p95",
        "max_seconds": 3,
        "environment": "unit",
        "data_size": "small",
    }
    result = summarize(
        evidences=[evidence(), evidence(id="second", elapsed_seconds=None)],
        performance=[goal],
    )
    assert result["performance"][0]["verdict"] == "미판정"


def test_unexecuted_explicit_workflow_scope_remains_in_planned_metrics():
    planned = case(
        unit="workflow",
        target="report",
        role=None,
        assessment={
            "required": True,
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {
                        "id": "planned",
                        "check": "N04-O.1",
                        "node": "compose",
                        "role": "report_description",
                        "occurrence": 1,
                    },
                ],
            },
        },
    )
    (result,) = summarize_nodes([planned], 2, [], [])
    assert (result["node"], result["role"]) == ("compose", "report_description")
    assert result["functional"]["verification"]["missing_repetitions"] == 2
    assert result["verdict"] == "미판정"


def test_passing_one_occurrence_does_not_hide_a_missing_expected_occurrence():
    planned = case(
        unit="agent",
        target="request",
        role=None,
        assessment={
            "required": True,
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {
                        "id": "second",
                        "check": "N03-O.3",
                        "node": "decide",
                        "occurrence": 2,
                    },
                ],
            },
        },
    )
    result = summarize([planned], evidences=[evidence(occurrence=1)])
    item = result["functional"]["cases"]["items"][0]
    assert item["missing_expectations"] == [{"repetition": 1, "id": "second"}]
    assert result["verdict"] == "미판정"


def test_retry_statistics_keep_kinds_and_missing_measurements_separate():
    result = summarize(
        [case("a"), case("b"), case("c")],
        evidences=[
            evidence(
                "a", technical_retries_by_kind={"model": 0, "tool": 2, "agent": 1}
            ),
            evidence(
                "b", technical_retries_by_kind={"model": 4, "tool": None, "agent": 3}
            ),
            evidence("c"),
        ],
    )
    kinds = result["operational"]["technical_retries_by_kind"]
    assert kinds["model"]["mean"] == 2
    assert kinds["model"]["p95"] == 4
    assert kinds["model"]["missing_count"] == 1
    assert kinds["tool"]["mean"] == kinds["tool"]["p95"] == 2
    assert kinds["tool"]["missing_count"] == 2
    assert kinds["agent"]["mean"] == 2 and kinds["agent"]["p95"] == 3


def test_unfinished_observations_preserve_values_without_entering_finished_statistics():
    observed = {
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "usage_missing_calls": {"input_tokens": 1, "output_tokens": 0},
        "model_calls": 9,
        "technical_retries": 2,
        "technical_retries_by_kind": {"model": 1, "tool": 1, "agent": 0},
    }
    result = summarize(
        [case("done"), case("pending")],
        evidences=[
            evidence(
                "done", technical_retries_by_kind={"model": 0, "tool": 0, "agent": 0}
            ),
            evidence(
                "pending",
                status="running",
                complete=False,
                observed_usage=observed,
                usage={"input_tokens": 100, "output_tokens": 50},
                model_calls=9,
                technical_retries=2,
                technical_retries_by_kind={"model": 1, "tool": 1, "agent": 0},
            ),
        ],
    )
    ops = result["operational"]
    assert ops["tokens"]["input_tokens"]["mean"] == 3
    assert ops["tokens"]["input_tokens"]["unfinished_count"] == 1
    assert ops["model_calls"]["mean"] == 1
    assert ops["technical_retries_by_kind"]["model"]["mean"] == 0
    assert ops["technical_retries_by_kind"]["tool"]["unfinished_count"] == 1
    assert ops["unfinished_usage"] == [
        {
            "node_id": "pending-1",
            "run_id": "run-pending-1",
            "case_id": "pending",
            "repetition": 1,
            **observed,
        }
    ]
    ops["unfinished_usage"][0]["usage"]["input_tokens"] = 999
    assert observed["usage"]["input_tokens"] == 100


def test_unfinished_child_trace_is_preserved_despite_parent_success_status():
    report = {
        "run": {"id": "run", "role": "request"},
        "trace": {
            "spans": [
                {
                    "id": "n",
                    "kind": "node",
                    "name": "decide",
                    "parent_id": None,
                    "status": "success",
                    "ended_at": "now",
                    "input": {"state": {"results": []}},
                    "output": {"applied_update": {"results": []}},
                },
                {
                    "id": "m",
                    "kind": "model",
                    "name": "Decision",
                    "parent_id": "n",
                    "status": "running",
                    "ended_at": None,
                    "input": {"messages": []},
                    "output": {
                        "sdk_response": {
                            "content": "{}",
                            "usage_metadata": {"input_tokens": 7},
                        }
                    },
                },
            ]
        },
    }
    nodes = extract_nodes(report, case())
    result = summarize(evidences=nodes)
    ops = result["operational"]
    assert ops["tokens"]["input_tokens"]["sample_count"] == 0
    assert ops["failure_rate"]["denominator"] == 0
    assert ops["model_calls"]["unfinished_count"] == 1
    observation = ops["unfinished_usage"][0]
    assert (observation["node_id"], observation["run_id"]) == ("n", "run")
    assert observation["usage"] == {"input_tokens": 7, "output_tokens": None}
    assert observation["usage_missing_calls"] == {"input_tokens": 0, "output_tokens": 1}
    assert observation["model_calls"] == 1


def test_node_case_excludes_other_nodes_and_roles_from_all_metrics():
    results = summarize_nodes(
        [case()],
        1,
        [
            assessed(),
            assessed(node_id="other-node", node="act", verdict="실패"),
            assessed(node_id="other-role", role="interpretation", verdict="실패"),
        ],
        [
            evidence(),
            evidence(id="other-node", node="act", model_calls=99),
            evidence(id="other-role", role="interpretation", model_calls=99),
        ],
    )
    assert len(results) == 1
    result = results[0]
    assert (result["node"], result["role"], result["runs"]) == ("decide", "request", 1)
    assert result["functional"]["verdict"] == "통과"
    assert result["operational"]["model_calls"]["mean"] == 1


def test_metrics_do_not_add_unrequested_checks_or_their_planned_scopes():
    planned = case(
        assessment={
            "required": True,
            "checks": ["N-F.1"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {"id": "format", "check": "N-F.1"},
                    {"id": "other", "check": "N04-O.1", "node": "compose"},
                ],
            },
        }
    )
    a = assessed()
    extra = deepcopy(a["checks"][0])
    extra.update(check="N03-O.1", verdict="실패")
    a["checks"].append(extra)
    (result,) = summarize_nodes([planned], 1, [a], [evidence()])
    assert [check["check"] for check in result["functional"]["checks"]] == ["N-F.1"]
    assert result["functional"]["verdict"] == "통과"


def test_requested_call_scope_keeps_original_index_after_other_calls_are_filtered():
    planned = case(
        unit="agent",
        target="report_description",
        role=None,
        assessment={
            "required": True,
            "checks": ["N-F.1"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {
                        "id": "review",
                        "check": "N-F.1",
                        "call": "Verification",
                        "call_index": 2,
                    }
                ],
            },
        },
    )
    result = summarize(
        [planned],
        assessments=[assessed(node="compose", role="report_description")],
        evidences=[
            evidence(
                node="compose",
                role="report_description",
                calls=[{"name": "Verification", "index": 2}],
            )
        ],
    )
    assert result["functional"]["cases"]["items"][0]["missing_expectations"] == []
    assert result["functional"]["verdict"] == "통과"


def test_model_quality_pass_does_not_require_successful_state_application():
    planned = case(target="compose", role="report_description")
    nodes = selected_evidence(planned, [model_span("model", "ReportText")])
    result = summarize(
        [planned],
        assessments=[assessed(node="compose", role="report_description")],
        evidences=nodes,
        performance=[
            {
                "target": "compose",
                "role": "report_description",
                "metric": "response_time",
                "group": "normal",
                "case_ids": ["case"],
                "statistic": "p95",
                "max_seconds": 3,
                "environment": "unit",
                "data_size": "small",
            }
        ],
    )
    assert result["functional"]["verdict"] == result["verdict"] == "통과"
    assert result["functional"]["verification"]["completed_cases"] == 1
    ops = result["operational"]
    assert ops["measurement_scope"] == "selected_model_calls"
    assert ops["failure_rate"]["rate"] == 0
    assert ops["response_time"]["normal"]["mean"] == 2
    assert result["performance"][0]["verdict"] == "통과"
    assert nodes[0]["spans"][0]["error"]["code"] == "state_application_failed"


def test_agent_calls_still_keep_their_actual_node_groups():
    planned = case(unit="agent", target="request")
    results = summarize_nodes(
        [planned],
        1,
        [assessed(), assessed(node_id="child", node="compose", role="interpretation")],
        [evidence(), evidence(id="child", node="compose", role="interpretation")],
    )
    assert {(item["node"], item["role"], item["runs"]) for item in results} == {
        ("decide", "request", 1),
        ("compose", "interpretation", 1),
    }


def test_unfinished_observation_is_not_a_performance_goal_sample():
    goal = {
        "target": "decide",
        "role": "request",
        "metric": "response_time",
        "group": "normal",
        "case_ids": ["case"],
        "statistic": "p95",
        "max_seconds": 3,
        "environment": "unit",
        "data_size": "small",
    }
    result = summarize(evidences=[evidence(unfinished=True)], performance=[goal])
    performance = result["performance"][0]
    assert performance["sample_count"] == 0
    assert performance["value_seconds"] is None
    assert performance["verdict"] == "미판정"


def test_operational_statistics_use_only_requested_report_model_calls():
    planned = case(
        unit="agent",
        target="report_description",
        role=None,
        assessment={
            "required": True,
            "checks": ["N-F.1"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {
                        "id": "review",
                        "check": "N-F.1",
                        "call": "Verification",
                        "call_index": 2,
                    }
                ],
            },
        },
    )
    nodes = selected_evidence(
        planned,
        [
            model_span(
                "draft",
                "ReportText",
                status="error",
                elapsed_seconds=80,
                error={"type": "ConnectionError"},
                output={},
            ),
            model_span("review", "Verification", elapsed_seconds=4),
        ],
    )
    result = summarize(
        [planned],
        assessments=[assessed(node="compose", role="report_description")],
        evidences=nodes,
    )
    ops = result["operational"]
    assert result["runs"] == 1
    assert ops["failure_rate"]["rate"] == 0
    assert ops["response_time"]["normal"]["mean"] == 4
    assert ops["tokens"]["input_tokens"]["mean"] == 3
    assert ops["tokens"]["output_tokens"]["mean"] == 2
    assert ops["model_calls"]["mean"] == 1
    assert ops["technical_retries"]["mean"] is None
    assert ops["technical_retries_by_kind"]["tool"]["mean"] is None
    assert ops["technical_retries_by_kind"]["agent"]["mean"] is None


def test_selected_model_failure_and_unfinished_call_have_separate_statistics():
    planned = [
        case("failed", target="compose", role="report_description"),
        case("unfinished", target="compose", role="report_description"),
        case("missing", target="compose", role="report_description"),
    ]
    nodes = [
        *selected_evidence(
            planned[0],
            [
                model_span(
                    "failed-model",
                    status="error",
                    error={"type": "ConnectionError"},
                    output={},
                )
            ],
        ),
        *selected_evidence(
            planned[1],
            [model_span("pending-model", status="running", ended_at=None)],
        ),
        *selected_evidence(planned[2], [model_span("missing-model", output={})]),
    ]
    for node in nodes:
        node["id"] = node["case_id"]
    result = summarize(planned, assessments=[], evidences=nodes)
    ops = result["operational"]
    assert ops["failure_rate"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1,
        "missing_count": 1,
        "unfinished_count": 1,
    }
    assert ops["response_time"]["error"]["mean"] == 2
    assert ops["response_time"]["normal"]["sample_count"] == 0
    assert ops["tokens"]["input_tokens"]["sample_count"] == 0
    assert any(item["case_id"] == "unfinished" for item in ops["unfinished_usage"])


@pytest.mark.parametrize("model_call", ["draft_review", None])
def test_standalone_report_scope_excludes_other_call_expectations(model_call):
    planned = case(
        target="compose",
        role="report_description",
        assessment={
            "required": True,
            "checks": ["N-F.1", "N04-O.1"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {"id": "draft", "check": "N-F.1", "call": "ReportText"},
                    {"id": "review", "check": "N-F.1", "call": "Verification"},
                    {"id": "body", "check": "N04-O.1", "call": "ReportText"},
                ],
            },
        },
    )
    if model_call is not None:
        planned["model_call"] = model_call
    nodes = selected_evidence(planned, [model_span("review", "Verification")])
    result = summarize(
        [planned],
        assessments=[assessed(node="compose", role="report_description")],
        evidences=nodes,
    )
    assert result["functional"]["verdict"] == "통과"
    assert result["functional"]["cases"]["items"][0]["missing_expectations"] == []
    assert [item["check"] for item in result["functional"]["checks"]] == ["N-F.1"]


def test_default_report_scope_without_requested_checks_has_no_metric_samples():
    planned = case(
        target="compose",
        role="report_description",
        assessment={
            "required": True,
            "checks": ["N04-O.1"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [{"id": "draft", "check": "N04-O.1", "call": "ReportText"}],
            },
        },
    )
    scope = []
    nodes = selected_evidence(
        planned, [model_span("review", "Verification")], scope=scope
    )
    assert nodes == []
    assert scope[0]["calls"][0]["name"] == "Verification"
    (result,) = summarize_nodes([planned], 1, [], nodes, scope_evidence=scope)
    functional = result["functional"]
    assert functional["cases"]["denominator"] == 0
    assert functional["cases"]["items"][0]["missing_expectations"] == []
    assert functional["cases"]["items"][0]["reason"] == (
        "요청한 대상에 적용할 검사가 없습니다."
    )
    assert functional["checks"] == functional["details"] == []
    assert functional["verdict"] == "미판정"
    assert result["runs"] == 0
    assert result["operational"]["model_calls"]["sample_count"] == 0
    assert result["operational"]["failure_rate"]["denominator"] == 0


def test_excluded_repetition_is_not_missing_or_an_operational_sample():
    planned = case()
    excluded = case(assessment={"required": True, "checks": []})
    result = summarize(
        [planned],
        2,
        [assessed(), assessed(repetition=2, verdict="실패")],
        [evidence(), evidence(repetition=2, model_calls=99)],
        run_cases=[
            {"case": planned, "repetition": 1},
            {"case": excluded, "repetition": 2},
        ],
    )
    summary = result["functional"]["cases"]["items"][0]
    assert summary["excluded_repetitions"] == [2]
    assert summary["missing_repetitions"] == summary["incomplete_repetitions"] == []
    assert summary["recorded_repetitions"] == 1
    assert summary["verdict"] == "통과"
    assert result["functional"]["checks"][0]["denominator"] == 1
    assert result["runs"] == 1
    assert result["operational"]["model_calls"]["mean"] == 1


def test_each_repetition_uses_only_its_own_expected_call_scope():
    def planned(index):
        return case(
            unit="agent",
            target="request",
            assessment={
                "required": True,
                "checks": ["N-F.1"],
                "expected": {
                    "schema_version": "node-expectations-v1",
                    "items": [
                        {
                            "id": f"call-{index}",
                            "check": "N-F.1",
                            "call": "Decision",
                            "call_index": index,
                        }
                    ],
                },
            },
        )

    first, second = planned(1), planned(2)
    combined = deepcopy(first)
    combined["assessment"]["expected"]["items"] += second["assessment"]["expected"][
        "items"
    ]
    result = summarize(
        [combined],
        2,
        [assessed(), assessed(repetition=2)],
        [
            evidence(calls=[{"name": "Decision", "index": 1}]),
            evidence(repetition=2, calls=[{"name": "Decision", "index": 2}]),
        ],
        run_cases=[
            {"case": first, "repetition": 1},
            {"case": second, "repetition": 2},
        ],
    )
    assert result["functional"]["cases"]["items"][0]["missing_expectations"] == []
    assert result["functional"]["verdict"] == "통과"


def test_row_bound_expectation_requires_that_actual_row():
    planned = case(
        target="act",
        assessment={
            "required": True,
            "checks": ["N-F.1"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {
                        "id": "visualization",
                        "check": "N-F.1",
                        "row_id": "N-F.1/act-visualization",
                    }
                ],
            },
        },
    )
    result = summarize(
        [planned],
        assessments=[assessed(node="act")],
        evidences=[
            evidence(
                node="act",
                calls=[
                    {
                        "name": "Selection",
                        "index": 1,
                        "raw": '{"name":"none"}',
                        "output": {"name": "none"},
                    }
                ],
            )
        ],
        row_ids=["N-F.1/act-visualization"],
    )
    assert result["functional"]["cases"]["items"][0]["missing_expectations"] == [
        {"id": "visualization", "repetition": 1}
    ]
    assert result["functional"]["verdict"] == "미판정"


def test_excluding_all_repetitions_cannot_pass_a_required_case():
    planned = case()
    excluded = case(assessment={"required": True, "checks": []})
    result = summarize([planned], run_cases=[{"case": excluded, "repetition": 1}])
    summary = result["functional"]["cases"]["items"][0]
    assert summary["excluded_repetitions"] == [1]
    assert summary["missing_repetitions"] == []
    assert summary["reason"] == "요청한 대상에 적용할 검사가 없습니다."
    assert result["functional"]["cases"]["denominator"] == 0
    assert result["functional"]["verdict"] == "미판정"
    assert result["runs"] == 0


def test_group_repetitions_use_their_explicit_node_and_role_expectations():
    def planned(node_name, role):
        return case(
            unit="workflow",
            target="report",
            role=None,
            assessment={
                "required": True,
                "checks": ["N-F.1"],
                "expected": {
                    "schema_version": "node-expectations-v1",
                    "items": [
                        {
                            "id": node_name,
                            "check": "N-F.1",
                            "node": node_name,
                            "role": role,
                        }
                    ],
                },
            },
        )

    first = planned("decide", "report_description")
    second = planned("compose", "report_insight")
    combined = deepcopy(first)
    combined["assessment"]["expected"]["items"] += second["assessment"]["expected"][
        "items"
    ]
    results = summarize_nodes(
        [combined],
        2,
        [
            assessed(role="report_description"),
            assessed(repetition=2, node="compose", role="report_insight"),
        ],
        [
            evidence(role="report_description"),
            evidence(repetition=2, node="compose", role="report_insight"),
        ],
        run_cases=[
            {"case": first, "repetition": 1},
            {"case": second, "repetition": 2},
        ],
    )
    assert len(results) == 2
    for result in results:
        item = result["functional"]["cases"]["items"][0]
        assert item["excluded_repetitions"] == (
            [2] if result["node"] == "decide" else [1]
        )
        assert item["missing_repetitions"] == item["missing_checks"] == []
        assert result["functional"]["verdict"] == "통과"


def test_other_group_request_without_any_assessment_keeps_case_unjudged():
    planned = case(
        unit="agent",
        target="request",
        assessment={"required": True, "checks": ["N-F.1", "N04-O.1"]},
    )
    result = summarize([planned])
    item = result["functional"]["cases"]["items"][0]
    assert item["missing_checks"] == [{"repetition": 1, "check": "N04-O.1"}]
    assert item["incomplete_repetitions"] == [1]
    assert result["functional"]["verdict"] == "미판정"


def test_assessment_in_another_group_satisfies_its_declared_check_presence():
    planned = case(
        unit="agent",
        target="request",
        assessment={"required": True, "checks": ["N-F.1", "N04-O.1"]},
    )
    other = assessed(node_id="compose", node="compose")
    other["checks"][0]["check"] = "N04-O.1"
    results = summarize_nodes(
        [planned],
        1,
        [assessed(), other],
        [evidence(), evidence(id="compose", node="compose")],
    )
    assert len(results) == 2
    for result in results:
        item = result["functional"]["cases"]["items"][0]
        assert item["missing_checks"] == []
        assert result["functional"]["verdict"] == "통과"


def test_unobserved_nonapplicable_expectation_stays_incomplete():
    planned = case(
        unit="agent",
        target="request",
        assessment={
            "required": True,
            "checks": ["N-F.1"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {"id": "seen", "check": "N-F.1", "occurrence": 1},
                    {
                        "id": "missing-na",
                        "check": "N-F.1",
                        "occurrence": 2,
                        "applicable": False,
                        "reason": "사전 비적용 선언",
                    },
                ],
            },
        },
    )
    result = summarize([planned], evidences=[evidence(occurrence=1)])
    item = result["functional"]["cases"]["items"][0]
    assert item["missing_expectations"] == [{"id": "missing-na", "repetition": 1}]
    assert item["incomplete_repetitions"] == [1]
    assert result["functional"]["verdict"] == "미판정"
