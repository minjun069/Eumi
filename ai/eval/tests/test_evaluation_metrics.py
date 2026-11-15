"""합성 판정·추적 기록으로 계획 분모, 반복 완료, 시간 측정 경계를 확인한다."""

from copy import deepcopy

import pytest

from eval.tools.metrics import summarize_tools


def case(case_id="a", required=True, **assessment):
    prepared = {
        "required": required,
        "checks": ["T-O.1"],
        "expected": {"synthetic": True},
    } | assessment
    if required is None:
        prepared.pop("required")
    return {
        "id": case_id,
        "unit": "tool",
        "target": "query_data",
        "purpose": "집계 단위검사",
        "arguments": {},
        "assessment": prepared,
    }


def assessment(case_id="a", repetition=1, verdict="통과", **changes):
    return {
        "run_id": f"{case_id}-{repetition}",
        "case_id": case_id,
        "target": "query_data",
        "repetition": repetition,
        "executed": True,
        "verdict": verdict,
        "reason": "합성 검사 결과",
        "checks": [
            {
                "check": "T-O.1",
                "target": "output.rows",
                "executed": True,
                "verdict": verdict,
                "reason": "합성 비교",
                "evidence": ["/output/rows"],
            }
        ],
    } | changes


def report(case_id="a", repetition=1, seconds=1.0, status="success", **span_changes):
    return {
        "run": {
            "id": f"{case_id}-{repetition}",
            "case_id": case_id,
            "unit": "tool",
            "target": "query_data",
            "repetition": repetition,
            "ended_at": "2026-11-10T00:00:10+00:00",
            "elapsed_seconds": 9999,
        },
        "trace": {
            "spans": [
                {
                    "id": f"span-{case_id}-{repetition}",
                    "kind": "tool",
                    "name": "query_data",
                    "parent_id": None,
                    "status": status,
                    "started_at": "2026-11-10T00:00:00+00:00",
                    "ended_at": "2026-11-10T00:00:01+00:00",
                    "elapsed_seconds": seconds,
                }
                | span_changes
            ]
        },
    }


def goal(**changes):
    return {
        "target": "query_data",
        "group": "normal",
        "case_ids": ["a"],
        "statistic": "p95",
        "max_seconds": 2.0,
        "environment": "합성 실행 환경",
        "data_size": "준비 자료 3행",
    } | changes


def summarize(cases=None, repeat=1, assessments=None, reports=None, performance=None):
    return summarize_tools(
        [case()] if cases is None else cases,
        repeat,
        [assessment()] if assessments is None else assessments,
        [] if reports is None else reports,
        performance,
    )[0]


def test_all_required_repetitions_pass_once_per_case_and_preserve_inputs():
    cases = [case(), case("optional", required=False)]
    results = [assessment(repetition=rep) for rep in (1, 2)]
    results.append(deepcopy(results[0]))
    results.append(assessment("optional", verdict="실패"))
    before = deepcopy((cases, results))
    functional = summarize(cases, 2, results)["functional"]
    assert functional["verdict"] == "통과"
    assert functional["complete"]
    assert functional["numerator"] == functional["denominator"] == 1
    assert functional["rate"] == 1
    assert functional["completed_cases"] == 1
    assert functional["excluded_cases"] == 1
    assert (cases, results) == before


def test_missing_repeat_stays_in_denominator_and_check_coverage():
    value = summarize(repeat=2)["functional"]
    assert value["verdict"] == "미판정" and not value["complete"]
    assert value["numerator"] == 0 and value["denominator"] == 1
    assert value["rate"] == 0
    assert value["missing_cases"] == value["incomplete_cases"] == 1
    detail = value["cases"][0]
    assert detail["missing_repetitions"] == [2]
    assert detail["checks"][0]["unexecuted"] == 1
    assert detail["checks"][0]["undetermined"] == 1


def test_known_failure_has_priority_without_hiding_unfinished_verification():
    value = summarize(repeat=2, assessments=[assessment(verdict="실패")])["functional"]
    assert value["verdict"] == "실패" and not value["complete"]
    assert value["failed_cases"] == value["incomplete_cases"] == 1
    assert value["completed_failed_cases"] == value["completed_cases"] == 0


def test_failed_and_unknown_items_in_same_run_remain_incomplete():
    result = assessment(verdict="실패")
    result["checks"].append(
        {
            "check": "T-O.1",
            "target": "output.unit",
            "executed": False,
            "verdict": "미판정",
            "reason": "근거 없음",
            "evidence": [],
        }
    )
    value = summarize(assessments=[result])["functional"]
    assert value["verdict"] == "실패" and not value["complete"]
    assert value["cases"][0]["checks"][0]["undetermined"] == 1


def test_zero_denominator_and_unspecified_required_never_pass():
    zero = summarize(cases=[case(required=False)])["functional"]
    assert zero["denominator"] == 0 and zero["rate"] is None
    assert zero["verdict"] == "미판정"
    value = summarize(cases=[case(), case("undecided", required=None)])["functional"]
    assert value["rate"] == 1 and value["denominator"] == 1
    assert value["unspecified_required_cases"] == 1
    assert value["verdict"] == "미판정" and not value["complete"]


@pytest.mark.parametrize("changes", [{"expected": None}, {"checks": []}])
def test_missing_prepared_expectation_or_checks_prevents_vacuous_pass(changes):
    value = summarize(cases=[case(**changes)])["functional"]
    assert value["verdict"] == "미판정" and not value["complete"]


def test_nonapplicable_checks_need_an_applicable_result_to_pass():
    value = summarize(assessments=[assessment(verdict="비적용")])["functional"]
    assert value["verdict"] == "미판정" and not value["complete"]
    result = assessment()
    result["checks"].append(
        {
            "check": "T-O.5",
            "target": "source",
            "executed": False,
            "verdict": "비적용",
            "reason": "거부 결과에는 출처가 없음",
            "evidence": [],
        }
    )
    value = summarize(cases=[case(checks=["T-O.1", "T-O.5"])], assessments=[result])[
        "functional"
    ]
    assert value["verdict"] == "통과" and value["complete"]


def test_conflicting_assessments_do_not_choose_the_successful_record():
    value = summarize(assessments=[assessment(), assessment(verdict="실패")])[
        "functional"
    ]
    assert value["verdict"] == "실패" and not value["complete"]
    assert value["cases"][0]["checks"][0]["undetermined"] == 1


def test_timing_groups_use_tool_spans_not_run_duration_or_functional_verdict():
    reports = [report(), report("b", seconds=3, status="error")]
    value = summarize(
        cases=[case(), case("b")],
        assessments=[assessment(), assessment("b")],
        reports=reports,
    )
    assert value["functional"]["verdict"] == "통과"
    assert value["latency"]["normal"]["median_seconds"] == 1
    assert value["latency"]["error"]["median_seconds"] == 3


def test_nearest_rank_p95_and_median_preserve_uneven_samples():
    value = summarize(
        repeat=20, reports=[report(repetition=i, seconds=i) for i in range(1, 21)]
    )["latency"]["normal"]
    assert value == {"sample_count": 20, "median_seconds": 10.5, "p95_seconds": 19}


def test_duplicate_spans_and_nested_tool_time_are_not_counted_twice():
    original = report(seconds=3)
    child = deepcopy(original["trace"]["spans"][0])
    child.update(id="nested", parent_id="span-a-1", elapsed_seconds=2)
    original["trace"]["spans"].extend(
        [
            deepcopy(original["trace"]["spans"][0]),
            child,
            {
                "id": "provider",
                "kind": "provider",
                "name": "query_data",
                "elapsed_seconds": 50,
            },
        ]
    )
    value = summarize(reports=[original, deepcopy(original)])["latency"]
    assert value["normal"]["sample_count"] == 1
    assert value["normal"]["median_seconds"] == 3


def test_conflicting_duplicate_span_is_excluded_and_blocks_performance():
    original, conflicting = report(), report(seconds=2)
    value = summarize(reports=[original, conflicting], performance=[goal()])
    assert value["latency"]["conflicting_span_ids"] == ["span-a-1"]
    assert value["latency"]["normal"]["sample_count"] == 0
    assert value["performance"][0]["verdict"] == "미판정"


def test_unfinished_call_is_excluded_and_its_elapsed_time_is_retained():
    value = summarize(
        reports=[report(seconds=None, status="running", ended_at=None)],
        performance=[goal()],
    )
    assert value["latency"]["normal"]["sample_count"] == 0
    assert value["latency"]["unfinished_count"] == 1
    assert value["latency"]["unfinished"][0]["elapsed_seconds"] == 10
    assert value["performance"][0]["verdict"] == "미판정"


@pytest.mark.parametrize(
    "seconds", [float("nan"), float("inf"), -1, True, None, 10**400]
)
def test_invalid_timing_is_not_a_sample(seconds):
    value = summarize(reports=[report(seconds=seconds)])["latency"]
    assert value["normal"]["sample_count"] == 0
    assert value["invalid_measurements"] == 1


@pytest.mark.parametrize(
    "spans", ["invalid", [None], [{"kind": "tool", "name": "query_data", "id": []}]]
)
def test_malformed_trace_records_do_not_become_timing_measurements(spans):
    value = report()
    value["trace"]["spans"] = spans
    result = summarize(reports=[value], performance=[goal()])
    assert result["latency"]["normal"]["sample_count"] == 0
    assert result["latency"]["invalid_measurements"] == 1
    assert result["performance"][0]["verdict"] == "미판정"


def test_performance_uses_only_selected_cases_and_complete_planned_repetitions():
    cases = [case(), case("other")]
    reports = [report(seconds=1), report("other", seconds=500)]
    passed = summarize(cases=cases, reports=reports, performance=[goal()])
    assert passed["performance"][0]["verdict"] == "통과"
    failed = summarize(reports=[report(seconds=3)], performance=[goal()])
    assert failed["performance"][0]["verdict"] == "실패"
    incomplete = summarize(repeat=2, reports=reports, performance=[goal()])
    assert incomplete["performance"][0]["verdict"] == "미판정"


@pytest.mark.parametrize(
    "field", ["statistic", "max_seconds", "environment", "data_size"]
)
def test_unconfirmed_performance_condition_blocks_verdict(field):
    target = goal()
    target.pop(field)
    value = summarize(reports=[report()], performance=[target])["performance"][0]
    assert value["verdict"] == "미판정" and not value["complete"]


def test_execution_limit_failure_is_preserved_without_completed_measurement():
    value = report(seconds=None, ended_at=None, status="error")
    value["failure"] = {"code": "execution_limit_exceeded"}
    result = summarize(reports=[value], performance=[goal()])
    assert result["latency"]["execution_limit_exceeded"] == 1
    assert result["performance"][0]["verdict"] == "실패"
    assert not result["performance"][0]["complete"]


def test_unplanned_reports_and_unsupported_tool_do_not_expand_scope():
    cases = [case(), case("render") | {"target": "render_visualization"}]
    value = summarize(
        cases=cases, reports=[report(), report(repetition=2, seconds=50), report("b")]
    )
    assert value["latency"]["normal"]["sample_count"] == 1
    assert len(summarize_tools(cases, 1, [], [])) == 1


@pytest.mark.parametrize("repeat", [0, -1, True, 1.5])
def test_invalid_repetition_is_rejected(repeat):
    with pytest.raises(ValueError, match="positive integer"):
        summarize(repeat=repeat)
