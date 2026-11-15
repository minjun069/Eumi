"""Snapshot evidence and node projections must stay usable without a live model."""

import json
import shutil
from copy import deepcopy
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

import pytest

from eval.nodes.criteria import load_criteria
from eval.nodes.rules import _compare
from eval.runner import load_suite
from eval.scripts.build_node_dataset import build_dataset
from eval.scripts.node_dataset_coverage import build_coverage
from eval.scripts.node_dataset_paths import identity as case_identity
from eval.scripts.node_dataset_paths import validate_paths
from eval.scripts.node_dataset_storage import load_scenarios
from src.execution import accepted_outputs

ROOT = Path(__file__).resolve().parents[2] / "eval/scenarios/nodes"
ARCHIVE = ROOT.parent / "nodes-extended-v2"
NODES = ("interpret", "act", "decide", "compose", "ask")


@lru_cache
def read(name):
    if name == "scenarios.json":
        return load_scenarios(ROOT / name)
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def has_alias(case, prefix):
    return case["id"].startswith(prefix)


@pytest.fixture(scope="module")
def cases():
    return [case for node in NODES for case in read(f"{node}.json")["cases"]]


@pytest.fixture(scope="module")
def legacy_cases():
    return [
        case
        for node in NODES
        for case in json.loads((ARCHIVE / f"{node}.json").read_text(encoding="utf-8"))[
            "cases"
        ]
    ]


@pytest.mark.parametrize("node", NODES)
def test_existing_runner_can_load_each_node_suite(node):
    suite = load_suite(ROOT / f"{node}.json")
    assert bool(suite["cases"]) == (node != "ask")
    assert all(
        case["unit"] == "node" and case["target"] == node for case in suite["cases"]
    )


def test_source_snapshot_is_unchanged_by_generation(cases, tmp_path):
    snapshot = read("snapshots/data.json")
    before = deepcopy(snapshot)
    shutil.copytree(ROOT / "snapshots", tmp_path / "snapshots")
    build_dataset(tmp_path)
    assert snapshot == before
    assert (
        json.loads((tmp_path / "snapshots/data.json").read_text(encoding="utf-8"))
        == before
    )
    generated = [
        case
        for node in NODES
        for case in json.loads((tmp_path / f"{node}.json").read_text(encoding="utf-8"))[
            "cases"
        ]
    ]
    assert {case["id"]: case for case in generated} == {
        case["id"]: case for case in cases
    }
    for filename in ("scenarios.json", "coverage.json"):
        assert json.loads(
            (tmp_path / filename).read_text(encoding="utf-8")
        ) == json.loads((ROOT / filename).read_text(encoding="utf-8"))
    source_index = json.loads((ROOT / "scenarios.json").read_text(encoding="utf-8"))
    scenario_files = {entry["file"] for entry in source_index["scenarios"]}
    assert len(scenario_files) == len(source_index["scenarios"]) == 21
    for directory in (ROOT, tmp_path):
        assert {
            path.relative_to(directory).as_posix()
            for path in (directory / "scenarios").glob("*.json")
        } == scenario_files
    for filename in sorted(scenario_files):
        assert json.loads(
            (tmp_path / filename).read_text(encoding="utf-8")
        ) == json.loads((ROOT / filename).read_text(encoding="utf-8"))
    assert load_scenarios(tmp_path / "scenarios.json") == read("scenarios.json")


def test_each_checkpoint_resolves_to_its_own_input_and_oracle(cases):
    by_id = {case["id"]: case for case in cases}
    sidecar = read("scenarios.json")
    linked = set()
    expected_usages = {
        identity: {"usages": [], "partial_usages": []} for identity in by_id
    }
    groups = [(group, "usages", "scenario_id") for group in sidecar["scenarios"]] + [
        (group, "partial_usages", "group_id") for group in sidecar["partial_groups"]
    ]
    for scenario, usage_key, group_key in groups:
        for step in scenario["steps"]:
            case = by_id[step["case_id"]]
            linked.add(case["id"])
            expected_usages[case["id"]][usage_key].append(
                {group_key: scenario["id"], "step_id": step["step_id"]}
            )
            assert (step["node"], step["role"]) == (case["target"], case["role"])
            for field, target in [
                ("input_ref", "initial"),
                ("expectation_ref", "assessment"),
            ]:
                filename, pointer = step[field].split("#")
                value = read(filename)
                for part in pointer.strip("/").split("/"):
                    value = value[int(part)] if isinstance(value, list) else value[part]
                assert value == case[target]
            assert "assessment" not in case["initial"]
            assert "axes" not in case["initial"]
    assert linked == set(by_id) == set(sidecar["case_index"])
    for identity, expected in expected_usages.items():
        for key, usages in expected.items():
            assert sidecar["case_index"][identity][key] == usages


def test_case_sharing_preserves_inputs_and_judging_criteria(cases):
    source = deepcopy(cases[0])
    renamed = deepcopy(source)
    renamed.update(
        id="another-path", purpose="다른 경로의 설명", tags=["scenario:other"]
    )
    assert case_identity(source) == case_identity(renamed)
    changed_input = deepcopy(source)
    changed_input["initial"]["request"]["goal"] += " 다른 기간도 비교한다."
    assert case_identity(source) != case_identity(changed_input)
    changed_oracle = deepcopy(source)
    changed_oracle["assessment"]["reference"]["test_only_difference"] = True
    assert case_identity(source) != case_identity(changed_oracle)


def test_complete_paths_have_consistent_states_and_returns(cases):
    assert not validate_paths(read("scenarios.json"), cases)


@pytest.mark.parametrize(
    "change", ["before_state", "missing_middle", "child_return", "summary"]
)
def test_complete_paths_reject_broken_continuity_and_counts(cases, change):
    sidecar = deepcopy(read("scenarios.json"))
    if change == "summary":
        sidecar["summary"]["path_node_execution_count"] += 1
    elif change == "child_return":
        path = next(
            path
            for path in sidecar["scenarios"]
            if any(step["boundary_before"]["kind"] == "call" for step in path["steps"])
        )
        child = next(
            step for step in path["steps"] if step["boundary_before"]["kind"] == "call"
        )
        parent = next(
            step
            for step in path["steps"]
            if step["step_id"] == child["boundary_before"]["from_step"]
        )
        parent["after_state"]["results"] = [
            record
            for record in parent["after_state"]["results"]
            if (record.get("action") or {}).get("name") != child["role"] + "_agent"
        ]
    else:
        path = next(
            path
            for path in sidecar["scenarios"]
            if any(
                step["boundary_before"]["kind"] == "next"
                for step in path["steps"][1:-1]
            )
        )
        index = next(
            index
            for index, step in enumerate(path["steps"][1:-1], 1)
            if step["boundary_before"]["kind"] == "next"
        )
        if change == "before_state":
            path["steps"][index]["before_state"]["request"]["goal"] += (
                " 잘못 전달된 목표"
            )
        else:
            path["steps"].pop(index)
    assert validate_paths(sidecar, cases)


def test_clarification_starts_at_current_answer_without_restored_tools(cases):
    by_id = {case["id"]: case for case in cases}
    paths = [
        p
        for p in read("scenarios.json")["scenarios"]
        if p["conversation_condition"] == "clarification_complete"
    ]
    assert {p["agent_role"] for p in paths} == {
        "request",
        "interpretation",
        "visualization",
    }
    for path in paths:
        case = by_id[path["steps"][0]["case_id"]]
        assert case["initial"]["results"] == []
        assert case["initial"]["response"] is None
        assert [message["type"] for message in case["initial"]["messages"]] == [
            "human",
            "ai",
            "human",
        ]
        assert path["steps"][0]["expected_next_nodes"] == ["decide"]
        assert path["terminal"]["status"] == "completed"


def test_score_oracle_uses_decimal_source_values(legacy_cases):
    cases = legacy_cases
    snapshot = read("snapshots/data.json")
    selection = snapshot["selection"]
    rows = {
        row["period_start"]: row
        for row in snapshot["datasets"]["public.region_result"]["rows"]
        if row["adm_cd10"] == selection["dong_code"]
    }
    current = Decimal(str(rows[selection["month"] + "-01"]["bh_score"]))
    previous = Decimal(str(rows[selection["previous_month"] + "-01"]["bh_score"]))
    case = next(
        case
        for case in cases
        if has_alias(case, "U1-score-change") and case["target"] == "compose"
    )
    item = next(
        item
        for item in case["assessment"]["expected"]["items"]
        if item["check"] == "N-O.1"
    )
    assert Decimal(str(item["value"])) == current - previous
    process = next(
        record for record in case["initial"]["results"] if record["id"] == "p-change"
    )
    assert Decimal(str(process["output"]["data"]["rows"][0]["bh_change"])) == (
        current - previous
    )


def test_artifact_expectations_use_call_ids_or_previous(cases):
    for case in cases:
        if case["target"] != "compose" or case["role"].startswith("report_"):
            continue
        expected = next(
            item
            for item in case["assessment"]["expected"]["items"]
            if item["check"] == "N04-O.2"
        )["value"]
        outputs = accepted_outputs(case["initial"])
        for identity in expected:
            if identity == "previous":
                assert case["initial"]["response"]["artifacts"]
            else:
                assert identity in outputs
                output = outputs[identity]
                assert (
                    output.get("artifact")
                    or output.get("data")
                    or (output.get("response") or {}).get("artifacts")
                )


def test_invalid_history_is_excluded_from_processing_oracles(legacy_cases):
    cases = legacy_cases
    references = [case for case in cases if has_alias(case, "U1-reference-")]
    assert len(references) == 3
    for case in references:
        outputs = accepted_outputs(case["initial"])
        assert "q-current" in outputs
        assert not {"q-failure", "q-cancelled", "q-rejected"} & outputs.keys()
        item = next(
            item
            for item in case["assessment"]["expected"]["items"]
            if item["check"] == "N02-O.3"
        )
        assert item["path"] == "/arguments_json/input_result_id"
        assert item["value"] == "q-current"


@pytest.mark.parametrize(
    "content,verdict",
    [
        ("점수 차이는 5.24점이다.", "통과"),
        ("점수 차이는 +5.24점이다. 다시 적으면 5.24점이다.", "통과"),
        ("점수 차이는 15.24점이다.", "실패"),
        ("점수 차이는 -5.24점이다.", "실패"),
    ],
)
def test_numeric_oracle_rejects_substrings_and_wrong_sign(
    legacy_cases, content, verdict
):
    cases = legacy_cases
    case = next(
        case
        for case in cases
        if has_alias(case, "U1-score-change") and case["target"] == "compose"
    )
    item = next(
        item
        for item in case["assessment"]["expected"]["items"]
        if item["check"] == "N-O.1"
    )
    assert (
        _compare(
            "N-O.1",
            item,
            {},
            {"content": content},
            case["assessment"]["reference"]["N-O.1"],
            {},
        )["verdict"]
        == verdict
    )


def test_unknown_or_changed_request_does_not_inherit_score_oracle(cases):
    for case in cases:
        if case["target"] in {"interpret", "ask"}:
            for reference in case["assessment"]["reference"].values():
                assert "observations" not in reference
                assert "independent_calculation" not in reference


def test_argument_oracles_parse_the_serialized_arguments(legacy_cases):
    cases = legacy_cases
    for case in cases:
        if case["target"] != "act" or not has_alias(case, "U"):
            continue
        reference = case["assessment"]["reference"]["N02-O.3"]
        arguments = reference.get("expected_arguments")
        if not arguments:
            continue
        output = {"arguments_json": json.dumps(arguments, ensure_ascii=False)}
        for item in case["assessment"]["expected"]["items"]:
            if item["check"] != "N02-O.3" or item.get("path", "").startswith(
                "/arguments_json/operations"
            ):
                continue
            assert (
                _compare("N02-O.3", item, {}, output, reference, {})["verdict"]
                == "통과"
            )


def test_coverage_has_current_sources_and_explicit_gaps(cases):
    coverage = build_coverage(cases, read("scenarios.json"))
    assert coverage == read("coverage.json")
    assert coverage["summary"]["criterion_row_count"] == 57
    assert not coverage["gaps"]
    assert all(
        row["status"] in {"mapped", "out_of_scope"}
        for row in coverage["criterion_rows"]
    )
    catalog = load_criteria()
    assert all(
        not row["not_applicable"]
        for row in coverage["criterion_rows"]
        if catalog["checks"][row["check"]]["method"] == "LLM 기반"
    )
    assert all(
        row["status"] == "out_of_scope"
        for row in coverage["criterion_rows"]
        if "ask" in row["when"].get("nodes", [])
    )
    sidecar = read("scenarios.json")
    for key in (
        "complete_scenario_count",
        "unique_node_case_count",
        "path_node_execution_count",
    ):
        assert coverage["summary"][key] == sidecar["summary"][key]
    for identity, entry in coverage["node_cases"].items():
        assert entry["usages"] == [
            {"case_id": identity, **usage}
            for usage in sorted(
                sidecar["case_index"][identity]["usages"],
                key=lambda item: (item["scenario_id"], item["step_id"]),
            )
        ]


def test_saved_prompt_validation_matches_current_generated_inputs():
    validation = read("validation.json")
    assert validation["valid"], validation["errors"]
    for filename, digest in validation["files_sha256"].items():
        assert sha256((ROOT / filename).read_bytes()).hexdigest() == digest
    assert all(
        not boundary["model_called"]
        and (
            boundary["prepared"]
            or (
                boundary["model_call_count"] == 0
                and boundary["terminal_without_model"] is not None
            )
        )
        for boundary in validation["prompt_boundaries"]
    )
