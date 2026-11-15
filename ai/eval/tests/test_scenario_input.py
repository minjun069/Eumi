"""시나리오 진입 입력과 자료원 범위를 보존하고 미래 답변 유입을 막는다."""

import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from eval.execution.schema import COMMON_CHECKS, REPORT_CHECKS
from eval.scenario_input import load_scenario_suite
from eval.schema import suite_adapter
from src.state import state_adapter

DATASET = Path(__file__).parents[2] / "eval/scenarios/nodes"
INDEX = DATASET / "scenarios.json"
REQUEST = "basic-request-revision"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(scope="module")
def agents():
    return load_scenario_suite(INDEX)


@pytest.fixture
def source(tmp_path):
    """작은 실제 경로의 입력을 보존하며 참조 위치만 시험용으로 재배치한다."""
    index = read(INDEX)
    entry = next(item for item in index["scenarios"] if item["id"] == REQUEST)
    body = read(DATASET / entry["file"])
    for step in body["steps"]:
        filename, pointer = step["input_ref"].split("#")
        original = read(DATASET / filename)
        case = original["cases"][int(pointer.split("/")[2])]
        write(tmp_path / filename, {**original, "cases": [case]})
        step["input_ref"] = filename + "#/cases/0/initial"
    write(tmp_path / entry["file"], body)
    snapshot = read(DATASET / index["source_snapshot"])
    snapshot["datasets"] = {
        "public.region_result": snapshot["datasets"]["public.region_result"]
    }
    snapshot["catalog"] = {
        "public.region_result": snapshot["catalog"]["public.region_result"]
    }
    write(tmp_path / index["source_snapshot"], snapshot)
    index["scenarios"] = [entry]
    index["source_snapshot_sha256"] = sha256(
        (tmp_path / index["source_snapshot"]).read_bytes()
    ).hexdigest()
    write(tmp_path / "scenarios.json", index)
    return tmp_path / "scenarios.json"


def test_all_21_agent_inputs_preserve_role_entry_state_and_deployment_sources(agents):
    suite = agents["suite"]
    assert len(suite["cases"]) == 21
    assert Counter(case["target"] for case in suite["cases"]) == {
        "request": 4,
        "interpretation": 4,
        "visualization": 4,
        "report_selection": 3,
        "report_description": 3,
        "report_insight": 3,
    }
    selected = {item["scenario_id"]: item for item in agents["selection"]}
    for case in suite["cases"]:
        body = read(DATASET / selected[case["id"]]["scenario_file"])
        initial = deepcopy(case["initial"])
        assert initial.pop("event") == body["event"]
        assert initial == state_adapter.validate_python(body["start_state"])
        assert case["dependencies"] == "real" and "stubs" not in case
        assert selected[case["id"]]["entry_state"] == "start_state"
        if not case["target"].startswith("report_"):
            assert initial["results"] == [] and initial["response"] is None
            assert case["providers"] == ["public.region_result"]
            expected_steps = 0 if case["target"] == "request" else 3
            assert initial["execution"]["budget"]["steps"]["used"] == expected_steps
        if case["target"] == "request":
            assert case["assessment"] == {
                "required": True,
                "checks": list(COMMON_CHECKS),
                "expected": {
                    "schema_version": "execution-expectations-v1",
                    "situation": "normal",
                    "entry": "initial",
                },
            }
        else:
            assert "assessment" not in case
    for name, digest in agents["source_files_sha256"].items():
        assert not Path(name).is_absolute()
        assert digest == sha256((DATASET / name).read_bytes()).hexdigest()
    assert suite_adapter.validate_python(suite) == suite


def test_workflow_uses_three_pre_stage_inputs_and_only_minimal_execution_checks():
    loaded = load_scenario_suite(INDEX, unit="workflow", target="report")
    assert len(loaded["suite"]["cases"]) == 3
    for case, selected in zip(
        loaded["suite"]["cases"], loaded["selection"], strict=True
    ):
        body = read(DATASET / selected["scenario_file"])
        initial = deepcopy(case["initial"])
        initial.pop("event")
        assert initial == state_adapter.validate_python(
            body["entry_transition"]["before_state"]
        )
        assert [record["decision"] for record in initial["results"]] == [
            "report_input",
            "report_source",
        ]
        assert case["target"] == "report" and case["unit"] == "workflow"
        assert selected["entry_state"] == "entry_transition.before_state"
        assert case["assessment"]["checks"] == list(COMMON_CHECKS + REPORT_CHECKS)
        assert set(case["assessment"]["expected"]) == {
            "schema_version",
            "situation",
            "entry",
        }


def test_explicit_case_selection_does_not_read_unselected_bodies(source):
    index = read(source)
    index["scenarios"].append(
        {"id": "unselected", "title": "unused", "file": "missing.json"}
    )
    write(source, index)
    loaded = load_scenario_suite(source, case_ids=[REQUEST])
    assert [case["id"] for case in loaded["suite"]["cases"]] == [REQUEST]
    assert "missing.json" not in loaded["source_files_sha256"]


def test_target_selection_does_not_validate_unselected_states(source):
    index = read(source)
    index["scenarios"].append(
        {"id": "unselected", "title": "unused", "file": "other.json"}
    )
    write(source, index)
    write(
        source.parent / "other.json",
        {"agent_role": "visualization", "start_state": None},
    )
    loaded = load_scenario_suite(source, target="request")
    assert len(loaded["suite"]["cases"]) == 1
    assert "other.json" not in loaded["source_files_sha256"]


def test_future_fixed_outputs_and_node_oracles_never_enter_agent_input(source):
    before = load_scenario_suite(source)
    entry = read(source)["scenarios"][0]
    body_path = source.parent / entry["file"]
    body = read(body_path)
    body["terminal"] = {"arbitrary_future": "changed"}
    for index, step in enumerate(body["steps"]):
        step["model_outputs"] = ["not a model response"]
        step["after_state"] = {"answer": "do not copy"}
        if index:
            step["before_state"] = {"future": "not validated as initial"}
        node_path = source.parent / step["input_ref"].split("#")[0]
        node = read(node_path)
        node["cases"][0].update(
            initial={"future": "not copied"},
            assessment={"answer": "not copied"},
            dependencies="stub",
            stubs=[{"output": {"answer": "not copied"}}],
        )
        write(node_path, node)
    write(body_path, body)
    after = load_scenario_suite(source)
    assert after["suite"] == before["suite"]
    assert after["selection"] == before["selection"]
    assert after["source_files_sha256"] != before["source_files_sha256"]


@pytest.mark.parametrize(
    "options",
    [
        {"unit": "node"},
        {"target": "unknown"},
        {"unit": "workflow", "target": "request"},
        {"case_ids": ["unknown"]},
        {"case_ids": []},
        {"case_ids": [REQUEST, REQUEST]},
        {"case_ids": [REQUEST], "target": "visualization"},
        {"unit": "workflow", "case_ids": [REQUEST]},
    ],
)
def test_invalid_or_incompatible_selection_is_rejected(source, options):
    with pytest.raises(ValueError):
        load_scenario_suite(source, **options)


@pytest.mark.parametrize("change", ["id", "event", "role", "first_state"])
def test_start_identity_event_and_first_node_must_agree(source, change):
    index = read(source)
    body_path = source.parent / index["scenarios"][0]["file"]
    body = read(body_path)
    if change == "id":
        body["id"] = "different"
    elif change == "event":
        body["event"] = "analysis_pipeline"
    elif change == "role":
        body["steps"][0]["role"] = "visualization"
    else:
        body["steps"][0]["before_state"]["request"]["goal"] = "different"
    write(body_path, body)
    with pytest.raises(ValueError):
        load_scenario_suite(source)


@pytest.mark.parametrize("location", ["scenario", "snapshot", "node"])
def test_references_cannot_escape_dataset_root(source, location):
    index = read(source)
    if location == "scenario":
        index["scenarios"][0]["file"] = "../outside.json"
    elif location == "snapshot":
        index["source_snapshot"] = "../outside.json"
    else:
        body_path = source.parent / index["scenarios"][0]["file"]
        body = read(body_path)
        body["steps"][0]["input_ref"] = "../outside.json#/cases/0/initial"
        write(body_path, body)
    write(source, index)
    with pytest.raises(ValueError, match="outside the dataset"):
        load_scenario_suite(source)


def test_modified_snapshot_requires_matching_declared_hash(source):
    index = read(source)
    snapshot_path = source.parent / index["source_snapshot"]
    snapshot_path.write_text(
        snapshot_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="SHA256"):
        load_scenario_suite(source)


@pytest.mark.parametrize(
    "change", ["missing_provider", "missing_registration", "missing_case", "wrong_id"]
)
def test_referenced_node_provider_and_identity_are_required(source, change):
    node_path = source.parent / "interpret.json"
    node = read(node_path)
    if change == "missing_provider":
        node["cases"][0]["providers"] = ["absent.dataset"]
    elif change == "missing_registration":
        node["datasets"] = {}
    elif change == "missing_case":
        node["cases"] = []
    else:
        node["cases"][0]["id"] = "different"
    write(node_path, node)
    with pytest.raises(ValueError):
        load_scenario_suite(source)


def test_omitted_providers_keep_the_original_node_suite_default_scope(source):
    before = load_scenario_suite(source)
    for filename in ("interpret.json", "decide.json", "compose.json"):
        node_path = source.parent / filename
        node = read(node_path)
        node["cases"][0].pop("providers")
        node["datasets"] = {
            "public.region_result": node["datasets"]["public.region_result"]
        }
        write(node_path, node)
    assert load_scenario_suite(source)["suite"] == before["suite"]


@pytest.mark.parametrize("change", ["step", "reference", "role"])
def test_malformed_selected_metadata_is_an_input_error(source, change):
    body_path = source.parent / read(source)["scenarios"][0]["file"]
    body = read(body_path)
    if change == "step":
        body["steps"][1] = None
    elif change == "reference":
        body["steps"][1]["input_ref"] = None
    else:
        body["agent_role"] = []
    write(body_path, body)
    with pytest.raises(ValueError):
        load_scenario_suite(source)


def test_selected_source_scope_matches_original_provider_declarations(agents):
    used = {name for case in agents["suite"]["cases"] for name in case["providers"]}
    assert set(agents["suite"]["datasets"]) == used
    assert set(agents["suite"]["catalog"]) == used
    assert "analysis.flow_detail" not in used
    one = load_scenario_suite(INDEX, case_ids=[REQUEST])
    assert set(one["suite"]["datasets"]) == {"public.region_result"}
    assert set(one["suite"]["catalog"]) == {"public.region_result"}
