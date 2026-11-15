"""Reject omitted execution frames even when their membership counts are repaired."""

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from eval.scripts.node_dataset_paths import validate_paths
from eval.scripts.node_dataset_storage import load_scenarios

ROOT = Path(__file__).resolve().parents[2] / "eval/scenarios/nodes"
NODES = ("interpret", "act", "decide", "compose", "ask")


@pytest.fixture(scope="module")
def dataset():
    sidecar = load_scenarios(ROOT / "scenarios.json")
    cases = [
        case
        for node in NODES
        for case in json.loads((ROOT / f"{node}.json").read_text(encoding="utf-8"))[
            "cases"
        ]
    ]
    assert not validate_paths(sidecar, cases)
    return sidecar, cases


def repair_membership_and_counts(sidecar, cases):
    """Keep bookkeeping valid so a broken execution boundary causes rejection."""
    paths = sidecar["scenarios"]
    index = sidecar["case_index"]
    for key, entry in index.items():
        uses = [
            (path, step)
            for path in paths
            for step in path["steps"]
            if step["case_id"] == key
        ]
        entry["usages"] = [
            {"scenario_id": path["id"], "step_id": step["step_id"]}
            for path, step in uses
        ]
        counts = sorted({len(step["model_outputs"]) for _, step in uses})
        if counts:
            entry["model_call_counts"] = counts
            entry["model_call_count"] = counts[0] if len(counts) == 1 else None
        else:
            entry.pop("model_call_counts", None)
            entry.pop("model_call_count", None)
    sidecar["summary"].update(
        complete_scenario_count=len(paths),
        path_node_execution_count=sum(len(path["steps"]) for path in paths),
        preparation_node_execution_count=sum(
            len(path.get("entry_transition", {}).get("parent_steps", []))
            for path in paths
        ),
        partial_only_node_case_count=sum(
            not value["usages"] for value in index.values()
        ),
        shared_node_case_count=sum(
            len(value["usages"]) > 1 for value in index.values()
        ),
        runtime_only_node_case_count=sum(
            value.get("model_call_counts") == [0] for value in index.values()
        ),
        path_runtime_only_execution_count=sum(
            not step["model_outputs"] for path in paths for step in path["steps"]
        ),
        by_role=dict(Counter(case["role"] for case in cases)),
        scenarios_by_event=dict(Counter(path["event"] for path in paths)),
    )


def failures(sidecar, cases):
    repair_membership_and_counts(sidecar, cases)
    checks = {error["check"] for error in validate_paths(sidecar, cases)}
    assert not any(check.startswith("summary_") for check in checks)
    assert "reverse_path_usage" not in checks
    assert "reverse_partial_usage" not in checks
    return checks


def test_parent_delegation_requires_recorded_child_path(dataset):
    sidecar, cases = deepcopy(dataset)
    path = next(
        path for path in sidecar["scenarios"] if path["agent_role"] == "request"
    )
    removed = [step for step in path["steps"] if step["frame"] != "root"]
    assert removed
    path["steps"] = [step for step in path["steps"] if step["frame"] == "root"]
    assert "delegated_child_path_present" in failures(sidecar, cases)


def test_report_handoff_cannot_supply_omitted_description_results(dataset):
    sidecar, cases = deepcopy(dataset)
    path = next(
        path for path in sidecar["scenarios"] if path["agent_role"] == "report_insight"
    )
    description_id = path["upstream_scenario_id"]
    selection = next(
        p
        for p in sidecar["scenarios"]
        if p["agent_role"] == "report_selection"
        and p["region_code"] == path["region_code"]
    )
    sidecar["scenarios"] = [
        p for p in sidecar["scenarios"] if p["id"] != description_id
    ]
    path["entry_transition"]["before_state"] = deepcopy(selection["terminal"]["state"])
    checks = failures(sidecar, cases)
    assert {"report_upstream_present", "report_agent_entry_transition"} <= checks


def test_role_cannot_change_inside_an_existing_child_frame(dataset):
    sidecar, cases = deepcopy(dataset)
    path = next(
        path for path in sidecar["scenarios"] if path["agent_role"] == "request"
    )
    step = next(
        step
        for step in path["steps"]
        if step["frame"] != "root" and step["node"] == "decide"
    )
    case = next(case for case in cases if case["id"] == step["case_id"])
    assert step["role"] == "interpretation"
    step["role"] = case["role"] = "visualization"
    sidecar["case_index"][case["id"]]["role"] = "visualization"
    assert "frame_role_preserved" in failures(sidecar, cases)


def test_duplicate_scenario_id_is_rejected_after_recounting(dataset):
    sidecar, cases = deepcopy(dataset)
    sidecar["scenarios"].append(deepcopy(sidecar["scenarios"][0]))
    assert "unique_scenarios_ids" in failures(sidecar, cases)


def test_case_family_tags_match_actual_path_membership(dataset):
    sidecar, cases = deepcopy(dataset)
    case = next(
        case
        for case in cases
        if sidecar["case_index"][case["id"]]["usages"]
        and not sidecar["case_index"][case["id"]]["partial_usages"]
    )
    case["tags"].append("family:unrelated-prototype")
    assert "case_family_membership" in failures(sidecar, cases)


def test_cumulative_budget_must_match_actual_node_and_child_execution(dataset):
    sidecar, cases = deepcopy(dataset)
    step = sidecar["scenarios"][0]["steps"][0]
    step["after_state"]["execution"]["budget"]["steps"]["used"] += 1
    assert "budget_execution_count" in failures(sidecar, cases)


def independent_child(sidecar):
    return next(
        path for path in sidecar["scenarios"] if path["agent_role"] == "interpretation"
    )


def test_parent_preparation_is_counted_outside_evaluation_steps(dataset):
    sidecar, cases = dataset
    children = [
        path
        for path in sidecar["scenarios"]
        if path["agent_role"] in {"interpretation", "visualization"}
    ]
    assert len(children) == 8
    assert sidecar["summary"]["preparation_node_execution_count"] == 24
    assert sidecar["summary"]["path_node_execution_count"] == sum(
        len(path["steps"]) for path in sidecar["scenarios"]
    )
    assert sidecar["summary"]["unique_node_case_count"] == len(cases)
    for path in children:
        entry = path["entry_transition"]
        assert entry["after_state"] == path["start_state"]
        assert all(
            not {"case_id", "input_ref", "expectation_ref"}.intersection(step)
            for step in entry["parent_steps"]
        )


def test_nonzero_budget_cannot_replace_actual_parent_preparation(dataset):
    sidecar, cases = deepcopy(dataset)
    path = independent_child(sidecar)
    assert path["start_state"]["execution"]["budget"]["agent_calls"]["used"] == 1
    del path["entry_transition"]
    assert {"agent_call_entry", "parent_preparation_present"} <= failures(
        sidecar, cases
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("status", "running", "child_queued_entry"),
        ("event", "analysis_pipeline", "child_inherited_event"),
        ("version", "unrelated-deployment", "child_inherited_version"),
        (
            "error",
            {"code": "invented", "cause": "not inherited"},
            "child_inherited_error",
        ),
    ],
)
def test_independent_child_preserves_parent_execution_contract(
    dataset, field, value, expected
):
    sidecar, cases = deepcopy(dataset)
    path = independent_child(sidecar)
    path["start_state"]["execution"][field] = value
    assert expected in failures(sidecar, cases)


def test_independent_child_requires_new_run_id_and_consumed_parent_budget(dataset):
    sidecar, cases = deepcopy(dataset)
    path = independent_child(sidecar)
    parent = path["entry_transition"]["parent_steps"][-1]["before_state"]
    path["start_state"]["execution"]["run_id"] = parent["execution"]["run_id"]
    path["start_state"]["execution"]["budget"] = deepcopy(parent["execution"]["budget"])
    assert {"child_new_run_id", "child_inherited_budget"} <= failures(sidecar, cases)


def test_independent_child_inherits_messages_and_constraints(dataset):
    sidecar, cases = deepcopy(dataset)
    path = independent_child(sidecar)
    path["start_state"]["messages"] = []
    path["start_state"]["request"]["constraints"]["required"].append(
        "invented requirement"
    )
    assert {"child_initial_state", "child_constraints"} <= failures(sidecar, cases)


def test_parent_preparation_requires_continuous_actual_node_usage(dataset):
    sidecar, cases = deepcopy(dataset)
    path = independent_child(sidecar)
    steps = path["entry_transition"]["parent_steps"]
    steps[0]["after_state"]["execution"]["budget"]["steps"]["used"] += 1
    assert {"parent_preparation_budget", "parent_preparation_continuity"} <= failures(
        sidecar, cases
    )


def test_parent_preparation_selection_must_match_child_goal(dataset):
    sidecar, cases = deepcopy(dataset)
    path = independent_child(sidecar)
    step = path["entry_transition"]["parent_steps"][-1]
    step["model_outputs"][0]["arguments_json"] = json.dumps({"goal": "different task"})
    assert {"child_target_goal", "child_return_arguments"} <= failures(sidecar, cases)


def test_parent_return_preserves_actual_child_output_and_cumulative_budget(dataset):
    sidecar, cases = deepcopy(dataset)
    path = independent_child(sidecar)
    entry = path["entry_transition"]
    parent_after = entry["parent_steps"][-1]["after_state"]
    call = next(
        r
        for r in parent_after["results"]
        if r["id"] == entry["parent_return_record_id"]
    )
    call["output"]["response"]["content"] = "changed child response"
    parent_after["execution"]["budget"]["steps"]["used"] += 1
    assert {"child_return_state", "child_return_budget"} <= failures(sidecar, cases)


def test_preparation_records_cannot_be_declared_evaluation_cases(dataset):
    sidecar, cases = deepcopy(dataset)
    path = independent_child(sidecar)
    path["entry_transition"]["parent_steps"][0]["case_id"] = cases[0]["id"]
    assert "parent_preparation_excludes_evaluation" in failures(sidecar, cases)


def test_parent_call_requires_its_actual_selection_record(dataset):
    sidecar, cases = deepcopy(dataset)
    path = independent_child(sidecar)
    state = path["entry_transition"]["parent_steps"][-1]["after_state"]
    state["results"] = [r for r in state["results"] if r["decision"] != "selection"]
    assert "child_parent_selection_record" in failures(sidecar, cases)


def test_nested_child_also_requires_new_queued_inherited_execution(dataset):
    sidecar, cases = deepcopy(dataset)
    path = next(p for p in sidecar["scenarios"] if p["agent_role"] == "request")
    child = next(s for s in path["steps"] if s["boundary_before"]["kind"] == "call")
    parent = next(
        s
        for s in path["steps"]
        if s["step_id"] == child["boundary_before"]["from_step"]
    )
    execution = child["before_state"]["execution"]
    execution["run_id"] = parent["before_state"]["execution"]["run_id"]
    execution["status"] = "running"
    execution["event"] = "analysis_pipeline"
    assert {
        "child_new_run_id",
        "child_queued_entry",
        "child_inherited_event",
    } <= failures(sidecar, cases)
