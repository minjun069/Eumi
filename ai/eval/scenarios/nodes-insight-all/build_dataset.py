"""Build all current scenarios in an isolated copy using the real node runtime."""

from __future__ import annotations

# ruff: noqa: E402 -- standalone builder imports the existing project.
import asyncio
import json
import re
import sys
from collections import Counter
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
from eval.scripts.node_dataset_coverage import build_coverage
from eval.scripts.node_dataset_paths import PathRecorder, assemble_paths, validate_paths
from eval.scripts.node_dataset_storage import load_scenarios, write_scenarios
from eval.scripts.validate_node_dataset import _validate_cases

NODES = ("interpret", "decide", "act", "compose", "ask")
USER_ROLES = ("request", "interpretation", "visualization")
REPORT_ROLES = ("report_selection", "report_description", "report_insight")
CONDITIONS = ("none", "new_topic", "revision", "clarification_complete")
REGIONS = ("1168065500", "1168063000", "5111062000")


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def protected_integrity():
    baseline = json.loads((HERE / "protected-sources.json").read_text(encoding="utf-8"))
    changed = [
        name
        for name, expected in baseline.items()
        if sha256((ROOT / name).read_bytes()).hexdigest() != expected
    ]
    assert not changed, f"Protected original, pilot or runtime changed: {changed}"
    return len(baseline)


async def generate(snapshot):
    recorder = PathRecorder(snapshot)
    await build_user_candidate(snapshot, recorder)
    print("User scenarios generated", flush=True)
    await build_report_candidate(snapshot, recorder)
    print("Report scenarios generated", flush=True)
    return recorder


def check_scope(scenarios):
    users = [s for s in scenarios if s["agent_role"] in USER_ROLES]
    reports = [s for s in scenarios if s["agent_role"] in REPORT_ROLES]
    assert len(scenarios) == 21 and len(users) == 12 and len(reports) == 9
    assert Counter(
        (s["agent_role"], s["conversation_condition"]) for s in users
    ) == Counter((role, condition) for role in USER_ROLES for condition in CONDITIONS)
    assert Counter((s["agent_role"], s["region_code"]) for s in reports) == Counter(
        (role, region) for role in REPORT_ROLES for region in REGIONS
    )
    assert all(s["terminal"]["status"] == "completed" for s in scenarios)


def check_pilot_preserved(scenarios):
    pilot = load_scenarios(HERE.parent / "nodes-insight-review/scenarios.json")[
        "scenarios"
    ]
    for previous in pilot:
        matches = [
            s
            for s in scenarios
            if s["agent_role"] == previous["agent_role"]
            and s["region_code"] == previous["region_code"]
            and s["conversation_condition"] == previous["conversation_condition"]
        ]
        assert len(matches) == 1
        current = matches[0]
        if previous["agent_role"] == "request":
            assert (
                current["start_state"]["request"] == previous["start_state"]["request"]
            )
            assert (
                current["terminal"]["state"]["response"]["content"]
                == previous["terminal"]["state"]["response"]["content"]
            )
        else:
            # Match approved wording, preserving prose while allowing source IDs
            # to change when the immutable evidence catalog gains two regions.
            for before, after in zip(
                [s for s in previous["steps"] if s["node"] == "compose"],
                [s for s in current["steps"] if s["node"] == "compose"],
                strict=True,
            ):
                before_text = [
                    o["content"] for o in before["model_outputs"] if "content" in o
                ]
                after_text = [
                    o["content"] for o in after["model_outputs"] if "content" in o
                ]
                assert before_text == after_text, previous["id"]


def check_authored_numbers(cases, recorder):
    outputs = {
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
                outputs[case["id"]],
                assessment["reference"]["N-O.1"],
                {},
            )
            assert result["verdict"] == "통과", (case["id"], result)
            checked += 1
    return checked


def check_report_lengths(scenarios):
    records = []
    for scenario in scenarios:
        role = scenario["agent_role"]
        if role not in {"report_description", "report_insight"}:
            continue
        step = next(s for s in scenario["steps"] if s["node"] == "compose")
        for output in step["model_outputs"]:
            if "content" not in output:
                continue
            text = output["content"].strip()
            lines = text.splitlines() if role == "report_insight" else [text]
            if role == "report_insight":
                assert 3 <= len(lines) <= 4
            counts = [len(re.findall(r"[.!?](?:\s|$)", line)) for line in lines]
            assert all(
                1 <= count <= (1 if role == "report_insight" else 3) for count in counts
            ), (scenario["id"], counts)
            records.append({"scenario_id": scenario["id"], "sentence_counts": counts})
    assert len(records) == 12
    return records


def build():
    protected = protected_integrity()
    source = HERE.parent / "nodes"
    original_path = source / "snapshots/data.json"
    original = json.loads(original_path.read_text(encoding="utf-8"))
    snapshot = enrich_activity_snapshot(enrich_snapshot(original))
    assert all(
        snapshot["datasets"][key] == value
        for key, value in original["datasets"].items()
    )
    snapshot_path = HERE / "snapshots/data.json"
    write_json(snapshot_path, snapshot)
    write_json(
        HERE / "snapshots/definitions.json",
        snapshot["datasets"]["reference.behavior_definitions"],
    )
    write_json(HERE / "snapshots/activity-dataset.json", snapshot["datasets"][ACTIVITY])
    (HERE / "snapshots/raw-query-results.json").write_bytes(
        (source / "snapshots/raw-query-results.json").read_bytes()
    )
    snapshot_before = deepcopy(snapshot)
    recorder = asyncio.run(generate(snapshot))
    assert snapshot == snapshot_before
    check_scope(recorder.scenarios)
    check_pilot_preserved(recorder.scenarios)
    lengths = check_report_lengths(recorder.scenarios)
    cases, sidecar = assemble_paths([], [], recorder)
    sidecar.update(
        dataset_scope="all-current-insight-copy",
        source_dataset="../nodes/scenarios.json",
        approved_pilot="../nodes-insight-review/scenarios.json",
        source_snapshot="snapshots/data.json",
        source_snapshot_sha256=sha256(snapshot_path.read_bytes()).hexdigest(),
        measurement_snapshot_sha256=sha256(original_path.read_bytes()).hexdigest(),
        supplemental_evidence=[
            "snapshots/definitions.json",
            "snapshots/activity-evidence.json",
        ],
        input_contract=(
            "evaluation-suite-v1: independent initial input, separate assessment"
        ),
        history_contract=(
            "Authored example model responses executed through current production "
            "nodes and prepared-data tools. No external model evaluation."
        ),
        flow_contract=(
            "12 complete user paths and 9 report role paths, with actual specialist "
            "boundaries and sequential approved report handoffs."
        ),
        model_output_contract=(
            "Examples are not exact-string answers. Assess supported interpretations, "
            "permitted alternatives and case-specific failure conditions."
        ),
    )
    suites = []
    for node in NODES:
        selected = [case for case in cases if case["target"] == node]
        providers = {name for case in selected for name in case.get("providers", [])}
        suite = {
            "schema_version": "evaluation-suite-v1",
            "id": f"node-insight-all-{node}",
            "data_source": "prepared",
            "datasets": {
                name: deepcopy(snapshot["datasets"][name]) for name in sorted(providers)
            },
            "catalog": {name: snapshot["catalog"][name] for name in sorted(providers)},
            "cases": selected,
        }
        suite_adapter.validate_python(suite)
        suites.append(suite)
        for index, case in enumerate(selected):
            sidecar["case_index"][case["id"]].update(
                input_ref=f"{node}.json#/cases/{index}/initial",
                expectation_ref=f"{node}.json#/cases/{index}/assessment",
            )
        write_json(HERE / f"{node}.json", suite)
    for scenario in sidecar["scenarios"]:
        for step in scenario["steps"]:
            entry = sidecar["case_index"][step["case_id"]]
            step.update(
                {
                    key: entry[key]
                    for key in ("input_ref", "expectation_ref", "node", "role")
                }
            )
    errors = validate_paths(sidecar, cases)
    assert not errors, errors
    write_scenarios(HERE / "scenarios.json", sidecar)
    assert load_scenarios(HERE / "scenarios.json")["scenarios"] == sidecar["scenarios"]
    coverage = build_coverage(cases, sidecar)
    assert not coverage["gaps"], coverage["gaps"]
    write_json(HERE / "coverage.json", coverage)
    numeric_checks = check_authored_numbers(cases, recorder)
    report_suite, report_coverage = build_report_calls(snapshot, recorder)
    write_json(HERE / "report-calls.json", report_suite)
    write_json(HERE / "report-call-coverage.json", report_coverage)
    print(
        "Checking input boundaries and replaying recorded data operations", flush=True
    )
    validation = {"errors": [], "checks": {}, "prompt_boundaries": [], "summary": {}}
    counts = Counter()

    def check(condition, name, identity, detail=""):
        counts[name] += 1
        if not condition:
            validation["errors"].append(
                {"check": name, "id": identity, "detail": detail}
            )

    asyncio.run(_validate_cases(suites, sidecar, snapshot, validation, check))
    validation["checks"] = dict(counts)
    write_json(HERE / "input-validation.json", validation)
    assert not validation["errors"], validation["errors"][:10]
    assert protected_integrity() == protected
    result = {
        "valid": True,
        "protected_original_pilot_and_runtime_files": protected,
        "approved_pilot_wording_preserved": True,
        "original_measurement_datasets_unchanged": True,
        "supplemental_activity_rows": len(snapshot["datasets"][ACTIVITY]["rows"]),
        "activity_detail_rows": len(
            snapshot["datasets"]["analysis.flow_detail"]["rows"]
        ),
        "suite_schema_errors": 0,
        "path_errors": errors,
        "summary": sidecar["summary"],
        "authored_numeric_checks_passed": numeric_checks,
        "report_sentence_checks": lengths,
        "input_boundary_and_data_replay_errors": len(validation["errors"]),
        "report_model_calls": {
            key: value for key, value in report_coverage.items() if key != "cases"
        },
        "external_model_evaluation": "not_run",
        "quality_scope": (
            "Case-specific observations, interpretations and conditional field checks "
            "are authored evaluation requirements; numeric and structural checks are "
            "not an autonomous model quality result."
        ),
    }
    write_json(HERE / "validation.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
