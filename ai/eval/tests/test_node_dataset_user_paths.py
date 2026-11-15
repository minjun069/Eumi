"""Saved user paths preserve structured checks for actual tool arguments."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from eval.nodes.rules import _compare
from eval.scripts.node_dataset_storage import load_scenarios

ROOT = Path(__file__).resolve().parents[2] / "eval/scenarios/nodes"


@pytest.fixture(scope="module")
def selections():
    sidecar = load_scenarios(ROOT / "scenarios.json")
    cases = {
        case["id"]: case
        for case in json.loads((ROOT / "act.json").read_text(encoding="utf-8"))["cases"]
    }
    selected = [
        (cases[step["case_id"]], step["model_outputs"][0])
        for scenario in sidecar["scenarios"]
        if scenario["event"] == "user_request"
        for step in scenario["steps"]
        if step["node"] == "act"
    ]
    assert selected, "The generated dataset must include complete user paths."
    return selected


def compare(case, output):
    assessment = case["assessment"]
    return [
        _compare(
            "N02-O.3",
            item,
            {"node": "act", "role": case["role"]},
            output,
            assessment["reference"]["N02-O.3"],
            {},
        )["verdict"]
        for item in assessment["expected"]["items"]
        if item["check"] == "N02-O.3" and "path" in item
    ]


def test_user_path_arguments_are_read_from_json_subfields(selections):
    for case, output in selections:
        for item in case["assessment"]["expected"]["items"]:
            if item["check"] == "N02-O.3" and "path" in item:
                assert item["path"].startswith("/arguments_json/")
        assert all(verdict == "통과" for verdict in compare(case, output))


def test_equivalent_argument_serialization_passes_but_wrong_source_fails(selections):
    case, original = next(
        (case, output) for case, output in selections if output["name"] == "query_data"
    )
    output = deepcopy(original)
    arguments = json.loads(output["arguments_json"])
    arguments["filters"] = list(reversed(arguments.get("filters", [])))
    output["arguments_json"] = json.dumps(arguments, indent=2, sort_keys=True)
    assert compare(case, output) == ["통과"]
    arguments["target"] = "unregistered.other_source"
    output["arguments_json"] = json.dumps(arguments)
    assert compare(case, output) == ["실패"]
