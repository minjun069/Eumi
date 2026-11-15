"""특정 데이터셋 이름 없이 선언·실제 호출·JSON 조건을 교차한다."""

import json
from copy import deepcopy

import pytest

from eval.nodes.criteria import load_criteria
from eval.nodes.selection import (
    aggregate_cases,
    candidate_cases,
    evaluation_filter,
    plan_case,
)


@pytest.fixture
def catalog():
    return load_criteria()


def case(identity="arbitrary-case"):
    return {
        "id": identity,
        "unit": "node",
        "target": "act",
        "role": "interpretation",
        "assessment": {
            "required": True,
            "checks": ["N-F.1", "N02-O.3"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {"id": "query", "check": "N02-O.3", "row_id": "N02-O.3/query"},
                    {"id": "process", "check": "N02-O.3", "row_id": "N02-O.3/process"},
                ],
            },
        },
    }


def node(tool, *, raw=True):
    output = {"name": tool, "arguments_json": "{}", "reason": "작업 선택"}
    return {
        "node": "act",
        "role": "interpretation",
        "occurrence": 1,
        "calls": [
            {
                "name": "Selection",
                "index": 1,
                "raw": json.dumps(output) if raw else None,
                "output": output if raw else None,
            }
        ],
    }


@pytest.mark.parametrize(
    "options",
    [
        {"case_ids": ["missing"]},
        {"check_ids": ["N99-O.9"]},
        {"row_ids": ["N02-O.3/missing"]},
        {"row_ids": []},
        {"check_ids": ["N-F.1"], "row_ids": ["N02-O.3/query"]},
    ],
)
def test_invalid_selection_fails_before_evaluation(catalog, options):
    with pytest.raises(ValueError):
        evaluation_filter([case()], catalog, **options)


def test_filters_intersect_declarations_without_mutating_cases(catalog):
    cases = [case(), case("unselected")]
    original = deepcopy(cases)
    filters = evaluation_filter(
        cases, catalog, case_ids=[cases[0]["id"]], row_ids=["N02-O.3/query"]
    )
    selected, decisions = candidate_cases(cases, catalog, filters)
    assert cases == original
    assert len(selected) == 1
    assert selected[0]["assessment"]["checks"] == ["N02-O.3"]
    assert [i["id"] for i in selected[0]["assessment"]["expected"]["items"]] == [
        "query"
    ]
    assert decisions[0]["case_id"] == "unselected"
    assert decisions[0]["status"] == "excluded"


def test_check_not_declared_by_case_is_not_implicitly_added(catalog):
    filters = evaluation_filter([case()], catalog, check_ids=["N01-O.2"])
    selected, decisions = candidate_cases([case()], catalog, filters)
    assert selected == []
    assert decisions[0]["status"] == "excluded"


def test_unknown_check_in_unstructured_case_has_clear_input_error(catalog):
    value = case()
    value["assessment"] = {"checks": ["N99-O.9"]}
    filters = evaluation_filter([value], catalog)
    with pytest.raises(ValueError, match="없는 요청 검사"):
        candidate_cases([value], catalog, filters)


def test_actual_tool_selects_only_corresponding_row_expectation(catalog):
    effective, decisions = plan_case(case(), [node("query_data")], catalog, 1)
    assert [i["id"] for i in effective["assessment"]["expected"]["items"]] == ["query"]
    assert (
        next(d for d in decisions if d["expectation_id"] == "process")["status"]
        == "excluded"
    )


def test_nonmatching_tool_row_is_excluded_but_missing_evidence_stays_unknown(catalog):
    filters = evaluation_filter([case()], catalog, row_ids=["N02-O.3/process"])
    (candidate,), _ = candidate_cases([case()], catalog, filters)
    mismatch, decisions = plan_case(
        candidate, [node("query_data")], catalog, 1, row_ids=filters["row_ids"]
    )
    assert mismatch["assessment"]["checks"] == []
    assert decisions[0]["status"] == "excluded"
    missing, decisions = plan_case(
        candidate,
        [node("process_data", raw=False)],
        catalog,
        2,
        row_ids=filters["row_ids"],
    )
    assert missing["assessment"]["checks"] == ["N02-O.3"]
    assert decisions[0]["status"] == "undetermined"


def test_missing_requested_occurrence_is_kept_in_plan(catalog):
    value = case()
    value.update(unit="agent", target="interpretation")
    value["assessment"]["checks"] = ["N02-O.3"]
    value["assessment"]["expected"]["items"] = [
        {
            "id": "later",
            "check": "N02-O.3",
            "node": "act",
            "occurrence": 2,
            "call": "Selection",
            "row_id": "N02-O.3/process",
        }
    ]
    effective, decisions = plan_case(value, [node("query_data")], catalog, 1)
    assert effective["assessment"]["checks"] == ["N02-O.3"]
    assert decisions[0]["status"] == "undetermined"


def test_repetition_plan_keeps_only_selected_conditions_and_case_union(catalog):
    filters = evaluation_filter([case()], catalog, row_ids=["N02-O.3/query"])
    candidates, _ = candidate_cases([case()], catalog, filters)
    plans = [
        {
            "case": plan_case(
                candidates[0], [node(tool)], catalog, rep, row_ids=filters["row_ids"]
            )[0],
            "repetition": rep,
        }
        for rep, tool in enumerate(("query_data", "process_data"), 1)
    ]
    assert plans[1]["case"]["assessment"]["checks"] == []
    (effective,) = aggregate_cases(candidates, plans)
    assert effective["assessment"]["checks"] == ["N02-O.3"]
    assert [i["id"] for i in effective["assessment"]["expected"]["items"]] == ["query"]


def test_original_raw_output_overrides_stale_parsed_tool_for_plan(catalog):
    evidence = node("query_data")
    evidence["calls"][0]["output"]["name"] = "process_data"
    effective, _ = plan_case(case(), [evidence], catalog, 1)
    assert [i["id"] for i in effective["assessment"]["expected"]["items"]] == ["query"]
