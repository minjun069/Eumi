"""원본을 보존하며 사용자 요청 1개와 한 동의 보고서 검토용 사본을 만든다."""

from __future__ import annotations

# ruff: noqa: E402 -- standalone review builder locates the existing AI package.
import asyncio
import json
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from activity_evidence import ACTIVITY, enrich_activity_snapshot
from reference_evidence import enrich_snapshot
from report_calls import build_report_calls
from report_candidate import build_report_candidate
from user_candidate import build_user_candidate

from eval.nodes.rules import _compare
from eval.schema import suite_adapter
from eval.scripts.node_dataset_paths import PathRecorder, assemble_paths, validate_paths
from eval.scripts.node_dataset_storage import write_scenarios


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def original_integrity():
    baseline = json.loads(
        (HERE / "original-hashes-action-revision.json").read_text(encoding="utf-8")
    )
    changed = [
        name
        for name, expected in baseline.items()
        if sha256((ROOT / name).read_bytes()).hexdigest() != expected
    ]
    if changed:
        raise AssertionError(f"Original files changed: {changed}")
    return len(baseline)


def criteria_hashes():
    return {
        f"eval/docs/nodes/{name}.json": sha256(
            (ROOT / f"eval/docs/nodes/{name}.json").read_bytes()
        ).hexdigest()
        for name in ("common", "interpret", "decide", "act", "compose", "ask")
    }


def review_input_integrity():
    baseline = json.loads(
        (HERE / "before-action-revision/input-hashes.json").read_text(encoding="utf-8")
    )
    changed = [
        name
        for name, expected in baseline.items()
        if sha256((HERE / name).read_bytes()).hexdigest() != expected
    ]
    if changed:
        raise AssertionError(f"Review input files changed: {changed}")
    return len(baseline)


async def generate(snapshot):
    recorder = PathRecorder(snapshot)
    await build_user_candidate(snapshot, recorder)
    await build_report_candidate(snapshot, recorder)
    return recorder


def check_authored_numbers(cases, recorder):
    """Exercise existing numeric checks; semantic quality is reviewed separately."""
    first_outputs = {
        step["case_id"]: step["model_outputs"][0]
        for scenario in recorder.scenarios
        for step in scenario["steps"]
        if step["node"] == "compose"
    }
    checked = 0
    for case in cases:
        if case["target"] != "compose":
            continue
        assessment = case["assessment"]
        for item in assessment["expected"]["items"]:
            if item["check"] != "N-O.1" or item.get("applicable") is False:
                continue
            result = _compare(
                "N-O.1",
                item,
                {"call": {"path": case["id"]}},
                first_outputs[case["id"]],
                assessment["reference"]["N-O.1"],
                {},
            )
            assert result["verdict"] == "통과", (case["id"], result)
            checked += 1
    return checked


def build():
    protected = original_integrity()
    protected_inputs = review_input_integrity()
    criteria_before = criteria_hashes()
    source = HERE.parent / "nodes"
    (HERE / "snapshots").mkdir(exist_ok=True)
    raw_name = "raw-query-results.json"
    (HERE / "snapshots" / raw_name).write_bytes(
        (source / "snapshots" / raw_name).read_bytes()
    )
    original_snapshot_path = source / "snapshots/data.json"
    original_snapshot = json.loads(original_snapshot_path.read_text(encoding="utf-8"))
    snapshot = enrich_activity_snapshot(enrich_snapshot(original_snapshot))
    for name, dataset in original_snapshot["datasets"].items():
        assert snapshot["datasets"][name] == dataset
    snapshot_path = HERE / "snapshots/data.json"
    write_json(snapshot_path, snapshot)
    write_json(
        HERE / "snapshots/definitions.json",
        snapshot["datasets"]["reference.behavior_definitions"],
    )
    write_json(HERE / "snapshots/activity-dataset.json", snapshot["datasets"][ACTIVITY])
    snapshot_before = deepcopy(snapshot)
    recorder = asyncio.run(generate(snapshot))
    assert snapshot == snapshot_before, "Fixture execution mutated source data"
    previous = json.loads(
        (HERE / "before-action-revision/comparison.json").read_text(encoding="utf-8")
    )
    user_before = next(item["after"] for item in previous if item["role"] == "request")
    user_after = next(p for p in recorder.scenarios if p["agent_role"] == "request")
    assert user_after["start_state"]["request"] == user_before["request"]
    assert (
        user_after["terminal"]["state"]["response"]["content"]
        == user_before["response"]
    ), "This revision must preserve the user-response copy"
    cases, sidecar = assemble_paths([], [], recorder)
    assert len(sidecar["scenarios"]) == 4
    assert sorted(p["agent_role"] for p in sidecar["scenarios"]) == [
        "report_description",
        "report_insight",
        "report_selection",
        "request",
    ]
    sidecar.update(
        dataset_scope="insight-review-copy",
        revision="user-final-report",
        source_snapshot="snapshots/data.json",
        source_snapshot_sha256=sha256(snapshot_path.read_bytes()).hexdigest(),
        measurement_snapshot_sha256=sha256(
            original_snapshot_path.read_bytes()
        ).hexdigest(),
        supplemental_evidence=[
            "snapshots/definitions.json",
            "snapshots/activity-evidence.json",
        ],
        input_contract=(
            "evaluation-suite-v1: independent initial input, separate assessment"
        ),
        history_contract=(
            "Review copy: authored model replies executed through current production "
            "nodes and real prepared-data tools; no external model evaluation."
        ),
        flow_contract=(
            "One user request with its delegated interpretation; one Dong report "
            "represented by three existing sequential agent boundaries."
        ),
        model_output_contract=(
            "Authored candidate responses are examples, not exact-string answers. "
            "Assessment specifies required meanings, allowed alternatives and failures."
        ),
    )
    for node in ("interpret", "decide", "act", "compose", "ask"):
        selected = [case for case in cases if case["target"] == node]
        providers = {name for case in selected for name in case.get("providers", [])}
        suite = {
            "schema_version": "evaluation-suite-v1",
            "id": f"node-insight-review-{node}",
            "data_source": "prepared",
            "datasets": {
                name: deepcopy(snapshot["datasets"][name]) for name in sorted(providers)
            },
            "catalog": {name: snapshot["catalog"][name] for name in sorted(providers)},
            "cases": selected,
        }
        suite_adapter.validate_python(suite)
        for index, case in enumerate(selected):
            sidecar["case_index"][case["id"]].update(
                input_ref=f"{node}.json#/cases/{index}/initial",
                expectation_ref=f"{node}.json#/cases/{index}/assessment",
            )
        write_json(HERE / f"{node}.json", suite)
    for path in sidecar["scenarios"]:
        for step in path["steps"]:
            entry = sidecar["case_index"][step["case_id"]]
            for key in ("input_ref", "expectation_ref", "node", "role"):
                step[key] = entry[key]
    errors = validate_paths(sidecar, cases)
    if errors:
        raise AssertionError(errors)
    write_scenarios(HERE / "scenarios.json", sidecar)
    numeric_checks = check_authored_numbers(cases, recorder)
    report_suite, report_coverage = build_report_calls(snapshot, recorder)
    write_json(HERE / "report-calls.json", report_suite)
    write_json(HERE / "report-call-coverage.json", report_coverage)
    original_integrity()
    review_input_integrity()
    assert criteria_hashes() == criteria_before, "Criteria changed during generation"
    result = {
        "valid": True,
        "original_files_unchanged": protected,
        "original_integrity_reference": "original-hashes-action-revision.json",
        "review_input_files_unchanged": protected_inputs,
        "review_input_integrity_reference": "before-action-revision/input-hashes.json",
        "original_measurement_datasets_unchanged": True,
        "previous_user_request_and_response_unchanged": True,
        "supplemental_activity_rows": len(snapshot["datasets"][ACTIVITY]["rows"]),
        "activity_detail_rows": len(
            snapshot["datasets"]["analysis.flow_detail"]["rows"]
        ),
        "supplemental_definition_rows": len(
            snapshot["datasets"]["reference.behavior_definitions"]["rows"]
        ),
        "criteria_sha256": criteria_before,
        "suite_schema_errors": 0,
        "authored_response_numeric_checks_passed": numeric_checks,
        "report_model_calls": {
            key: value for key, value in report_coverage.items() if key != "cases"
        },
        "path_errors": errors,
        "summary": sidecar["summary"],
        "external_model_evaluation": "not_run",
        "semantic_quality": (
            "The user-provided final wording is preserved. V07 explains the six-month "
            "context; V02 distinguishes conditional interpretations of relative gender "
            "change; V08 supplements the current distribution with August-December "
            "history for the same grids and November-December score changes. Ranks use "
            "one plus the number of strictly higher scores, including ties. Selection "
            "and reviews distinguish persistent high levels from the largest recent "
            "increase and retain the residence condition for field checks. Each view "
            "is not forced to add an operational action. Numeric and structural checks "
            "do not establish autonomous model quality. "
            "External model evaluation not run."
        ),
    }
    write_json(HERE / "validation.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
