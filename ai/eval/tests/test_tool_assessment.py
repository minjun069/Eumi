"""합성 결과로 채점기의 오판 경계를 검증한다. 정식 도구 품질 사례가 아니다."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from eval.assessment_store import load_assessment
from eval.schema import suite_adapter
from eval.tools.assessment import assess_run


def case(*items, **assessment):
    return {
        "id": "case",
        "unit": "tool",
        "target": "query_data",
        "purpose": "채점 로직 검증",
        "arguments": {"target": "test"},
        "assessment": {
            "checks": list(dict.fromkeys(item["check"] for item in items)),
            "reference": "테스트에서 독립적으로 지정한 정답",
            "expected": {
                "schema_version": "tool-expectations-v1",
                "items": list(items),
            },
            "required": True,
            **assessment,
        },
    }


def item(path="/output/value", value=1, **extra):
    return {"check": "T-O.1", "path": path, "value": value, **extra}


def report(output=None, status="returned", **extra):
    return {
        "run": {"id": "run", "status": status},
        "output": {"value": 1} if output is None and status == "returned" else output,
        "failure": None,
        "trace": {"spans": []},
        **extra,
    }


@pytest.mark.parametrize(
    ("actual", "expected", "verdict"),
    [
        (1, 1.0, "통과"),
        (True, 1, "실패"),
        ("1", 1, "실패"),
        (None, None, "통과"),
        ([1, 2], [2, 1], "실패"),
        ([1], [1, 1], "실패"),
        ({"a": 1, "b": 2}, {"a": 1}, "실패"),
        (2**54, 2**54 + 1, "실패"),
        (10**400, 10**400, "통과"),
    ],
)
def test_exact_comparison_preserves_json_meaning(actual, expected, verdict):
    result = assess_run(case(item(value=expected)), report({"value": actual}))
    assert result["verdict"] == verdict
    assert result["checks"][0]["executed"]


def test_tolerance_is_explicit_and_item_override_is_local():
    criteria = case(
        item(value=10, tolerance={"absolute": 0.2}),
        item("/output/second", 10),
        tolerance={"relative": 0.01},
    )
    result = assess_run(criteria, report({"value": 10.15, "second": 10.15}))
    assert [check["verdict"] for check in result["checks"]] == ["통과", "실패"]
    assert result["verdict"] == "실패"
    large = case(item(value=2**54 + 1, tolerance={"absolute": 0.2}))
    assert assess_run(large, report({"value": 2**54}))["verdict"] == "실패"


def test_subset_only_relaxes_object_keys_not_array_order_or_multiplicity():
    expected = {"sources": [{"uri": "source-a"}, {"uri": "source-a"}]}
    criteria = case(item(value=expected, match="subset"))
    actual = {"sources": [{"uri": "source-a", "label": "A"}]}
    assert assess_run(criteria, report({"value": actual}))["verdict"] == "실패"
    actual["sources"].append({"uri": "source-a", "label": "A"})
    assert assess_run(criteria, report({"value": actual}))["verdict"] == "통과"


def test_missing_returned_value_fails_but_unavailable_error_output_is_unjudged():
    criteria = case(item())
    assert assess_run(criteria, report({}))["verdict"] == "실패"
    returned_null = report()
    returned_null["output"] = None
    assert assess_run(criteria, returned_null)["verdict"] == "실패"
    result = assess_run(criteria, report(status="error"))
    assert result["verdict"] == "미판정"
    assert not result["checks"][0]["executed"]


def test_expected_rejection_passes_despite_execution_error():
    criteria = case(
        item("/run/status", "error", check="T-I.1"),
        item("/failure/code", "permission_denied", check="T-O.2"),
        item("/output", None),
    )
    actual = report(
        status="error", failure={"type": "ToolFailure", "code": "permission_denied"}
    )
    assert assess_run(criteria, actual)["verdict"] == "통과"
    actual["failure"]["code"] = "read_unavailable"
    assert assess_run(criteria, actual)["verdict"] == "실패"


def test_tableau_invalid_result_can_satisfy_the_expected_behavior():
    criteria = case(
        item("/output/valid", False, check="T-O.2"),
        item("/output/artifact", None),
    )
    criteria["target"] = "validate_visualization"
    actual = report(
        {"valid": False, "artifact": None, "issues": [{"code": "unknown_view"}]}
    )
    assert assess_run(criteria, actual)["verdict"] == "통과"


@pytest.mark.parametrize("mode", ["present", "absent"])
def test_presence_distinguishes_null_from_missing_and_missing_evidence(mode):
    criteria = case({"check": "T-O.5", "path": "/output/source", "match": mode})
    assert assess_run(criteria, report({"source": None}))["verdict"] == (
        "통과" if mode == "present" else "실패"
    )
    assert assess_run(criteria, report({}))["verdict"] == (
        "실패" if mode == "present" else "통과"
    )
    assert assess_run(criteria, report(status="error"))["verdict"] == "미판정"


@pytest.mark.parametrize(
    "change",
    [
        {"reference": None},
        {"reference": {}},
        {"expected": {}},
        {"expected": {"schema_version": "tool-expectations-v1", "items": []}},
    ],
)
def test_absent_criteria_never_pass(change):
    result = assess_run(case(item(), **change), report())
    assert result["verdict"] == "미판정"
    assert not result["executed"]


def test_missing_expected_value_differs_from_explicit_null():
    criteria = case({"check": "T-O.1", "path": "/output/value"})
    assert assess_run(criteria, report({"value": None}))["verdict"] == "미판정"
    criteria["assessment"]["expected"]["items"][0]["value"] = None
    assert assess_run(criteria, report({"value": None}))["verdict"] == "통과"


def test_unknown_check_criteria_and_not_applicable_are_not_vacuous_success():
    criteria = case(item(), checks=["T-O.1", "T-O.5"])
    result = assess_run(criteria, report())
    assert [check["verdict"] for check in result["checks"]] == ["통과", "미판정"]
    assert result["verdict"] == "미판정"
    not_applicable = case(item(applicable=False, reason="이 입력에는 적용하지 않음"))
    result = assess_run(not_applicable, report())
    assert result["checks"][0]["verdict"] == "비적용"
    assert result["verdict"] == "미판정"
    assert assess_run(case(), report())["verdict"] == "미판정"


def test_provider_absence_needs_completed_tool_trace_and_count_is_scoped():
    root_absence = case({"check": "T-I.1", "path": "/observations", "match": "absent"})
    assert assess_run(root_absence, report())["verdict"] == "미판정"
    criteria = case(item("/observations/provider_calls", 0, check="T-I.1"))
    assert assess_run(criteria, report())["verdict"] == "미판정"
    actual = report(
        trace={
            "spans": [
                {
                    "id": "tool",
                    "kind": "tool",
                    "name": "query_data",
                    "ended_at": "end",
                    "status": "success",
                },
                {"id": "unrelated", "kind": "provider", "parent_id": "other"},
            ]
        }
    )
    assert assess_run(criteria, actual)["verdict"] == "통과"
    actual["trace"]["spans"].append(
        {"id": "provider", "kind": "provider", "parent_id": "tool"}
    )
    assert assess_run(criteria, actual)["verdict"] == "실패"


def test_json_pointer_escaping_and_snapshots():
    criteria = case(item("/output/a~1b/~0key/0", {"value": 1}))
    actual = report({"a/b": {"~key": [{"value": 1}]}})
    original = deepcopy((criteria, actual))
    result = assess_run(criteria, actual)
    assert result["verdict"] == "통과"
    result["checks"][0]["actual"]["value"] = 2
    result["checks"][0]["expected"]["value"] = 2
    assert (criteria, actual) == original


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a["expected"].update(schema_version="unknown-v2"),
        lambda a: a["expected"]["items"].append(deepcopy(a["expected"]["items"][0])),
        lambda a: a.update(checks=["T-O.1", "T-O.1"]),
        lambda a: a.update(checks=["T-O.99"]),
        lambda a: a.update(tolerance={"absolute": -1}),
        lambda a: a.update(tolerance={"relative": float("inf")}),
        lambda a: a["expected"]["items"][0].update(path="/output/~bad"),
        lambda a: a["expected"]["items"][0].update(path="/assessment/expected"),
        lambda a: a["expected"]["items"][0].update(applicable=False),
        lambda a: a["expected"]["items"][0].update(applicable="false", reason="비적용"),
        lambda a: a["expected"]["items"][0].update(value=float("nan")),
    ],
)
def test_malformed_criteria_rejected_before_execution(mutate):
    criteria = case(item())
    mutate(criteria["assessment"])
    with pytest.raises((ValueError, ValidationError)):
        suite_adapter.validate_python(
            {
                "schema_version": "evaluation-suite-v1",
                "id": "tests",
                "cases": [criteria],
            }
        )


def test_no_execution_and_unsupported_units_remain_unjudged():
    assert assess_run(case(item()), None)["verdict"] == "미판정"
    criteria = case(item())
    criteria.update(unit="node", target="act")
    assert assess_run(criteria, report())["verdict"] == "미판정"


@pytest.mark.parametrize("spans", [None, "broken", 5, [None], []])
def test_missing_or_broken_trace_does_not_prove_absence(spans):
    criteria = case(
        {"check": "T-I.1", "path": "/trace/spans/0", "match": "absent"},
        item(),
    )
    result = assess_run(criteria, report(trace={"spans": spans}))
    assert [check["verdict"] for check in result["checks"]] == ["미판정", "통과"]


def test_derived_evidence_cannot_be_supplied_in_the_report():
    criteria = case(item("/observations/provider_calls", 0, check="T-I.1"))
    actual = report(observations={"provider_calls": 0})
    assert assess_run(criteria, actual)["verdict"] == "미판정"


def test_unfinished_run_does_not_establish_a_functional_pass():
    assert (
        assess_run(case(item()), report({"value": 1}, status="running"))["verdict"]
        == "미판정"
    )


def test_real_execution_and_score_command_preserve_raw_evidence(
    tmp_path, capsys, monkeypatch
):
    import asyncio
    import json

    from eval.__main__ import main
    from eval.runner import run_suite
    from src.settings import Settings

    def no_model(*args, **kwargs):
        pytest.fail("도구 실행·저장 결과 채점은 모델을 생성하지 않아야 합니다.")

    monkeypatch.setattr("eval.runner.create_model", no_model)
    criteria = case(
        item("/failure/code", "reference_not_found", check="T-I.1"),
        item("/observations/provider_calls", 0, check="T-O.2"),
    )
    suite = {
        "schema_version": "evaluation-suite-v1",
        "id": "logic-integration",
        "cases": [criteria],
    }
    folder = asyncio.run(run_suite(suite, Settings(_env_file=None), tmp_path, repeat=2))
    batch = json.loads((folder / "batch.json").read_text(encoding="utf-8"))
    assert batch["plan"] == {"case_ids": ["case"], "repeat": 2}
    paths = [folder / entry["path"] for entry in batch["runs"]]
    before = [path.read_bytes() for path in paths]
    assert main(["score", str(folder)]) == 0
    output = capsys.readouterr().out.strip()
    from pathlib import Path

    result = load_assessment(Path(output))
    assert [run["verdict"] for run in result["runs"]] == ["통과", "통과"]
    assert result["tools"][0]["functional"]["numerator"] == 1
    assert result["tools"][0]["functional"]["denominator"] == 1
    assert result["tools"][0]["latency"]["error"]["sample_count"] == 2
    assert [path.read_bytes() for path in paths] == before
    assert all(json.loads(raw)["assessment"]["verdict"] == "미판정" for raw in before)
