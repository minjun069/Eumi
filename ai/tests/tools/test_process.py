from copy import deepcopy

import pytest

from src.exceptions import ToolFailure
from src.tools.process import process_data


def calculation(**changes):
    return {
        "operation": "calculate",
        "method": "percent_change",
        "before": "before",
        "after": "after",
        "output": "change",
    } | changes


def test_calculate_actual_values_units_counts_and_isolation(dataset):
    original = deepcopy(dataset)
    request = {
        "data": dataset,
        "operations": [calculation()],
        "missing": "drop",
        "fields": ["region", "change"],
        "decimals": 1,
    }
    result = process_data(request)
    assert result["data"]["rows"] == [
        {"region": "A", "change": -10.0},
        {"region": "B", "change": -8.0},
    ]
    assert result["data"]["columns"][-1]["unit"] == "%"
    assert (result["input_rows"], result["output_rows"], result["excluded_rows"]) == (
        3,
        2,
        1,
    )
    assert result["data"]["inputs"] == [dataset["reference"]]
    assert dataset == original


@pytest.mark.parametrize(
    "method,value,unit",
    [
        ("difference", -12.0, "index"),
        ("ratio", 0.9, "ratio"),
    ],
)
def test_calculation_methods_and_preserved_missing(dataset, method, value, unit):
    result = process_data(
        {
            "data": dataset,
            "operations": [calculation(method=method)],
            "missing": "preserve",
        }
    )
    assert result["data"]["rows"][0]["change"] == value
    assert result["data"]["rows"][-1]["change"] is None
    assert result["data"]["columns"][-1]["unit"] == unit


@pytest.mark.parametrize("metadata", ["unit", "denominator"])
def test_incompatible_comparisons_stop(dataset, metadata):
    dataset["columns"][2][metadata] = "different"
    with pytest.raises(ToolFailure):
        process_data(
            {"data": dataset, "operations": [calculation()], "missing": "drop"}
        )


def test_zero_missing_overflow_and_overwrite_fail_without_mutation(dataset):
    for data, op in [
        (dataset, calculation()),
        (dataset | {"rows": [{"region": "A", "before": 0, "after": 3}]}, calculation()),
        (
            dataset | {"rows": [{"region": "A", "before": 1e-308, "after": 1e308}]},
            calculation(),
        ),
        (dataset, calculation(output="before")),
    ]:
        original = deepcopy(data)
        with pytest.raises(ToolFailure):
            process_data({"data": data, "operations": [op]})
        assert data == original


@pytest.mark.parametrize(
    "method,expected",
    [
        ("sum", 300),
        ("count", 3),
    ],
)
def test_aggregation(dataset, method, expected):
    result = process_data(
        {
            "data": dataset,
            "operations": [
                {
                    "operation": "aggregate",
                    "method": method,
                    "field": "before",
                    "group_by": [],
                    "output": "value",
                }
            ],
        }
    )
    assert result["data"]["rows"] == [{"value": expected}]
    assert result["excluded_rows"] == 0  # 집계로 합쳐진 행은 제외 행이 아니다.


def test_ordered_filter_calculate_group_and_missing(dataset):
    dataset["rows"][1]["region"] = "A"
    result = process_data(
        {
            "data": dataset,
            "missing": "preserve",
            "operations": [
                calculation(),
                {
                    "operation": "aggregate",
                    "method": "mean",
                    "field": "change",
                    "group_by": ["region"],
                    "output": "average",
                },
            ],
        }
    )
    assert result["data"]["rows"] == [
        {"region": "A", "average": -9.0},
        {"region": "C", "average": None},
    ]
    result = process_data(
        {
            "data": dataset,
            "operations": [
                {
                    "operation": "filter",
                    "conditions": [{"field": "region", "operator": "ne", "value": "C"}],
                },
                calculation(),
            ],
        }
    )
    assert result["excluded_rows"] == 1
    assert len(result["counts"]) == 2


def join(right, how="left"):
    return {
        "operation": "join",
        "right": right,
        "keys": ["region"],
        "how": how,
        "fields": {"after": "joined_after"},
    }


def test_join_modes_metadata_lineage_and_isolation(dataset):
    right = deepcopy(dataset)
    right["reference"] = {"id": "other", "version": "v2"}
    right["sources"] = [{"label": "other source", "uri": "fixture://other"}]
    right["rows"] = right["rows"][:1]
    original = deepcopy(right)
    for how, size in (("inner", 1), ("left", 3)):
        result = process_data({"data": dataset, "operations": [join(right, how)]})
        assert len(result["data"]["rows"]) == size
        assert result["data"]["rows"][0]["joined_after"] == 108
        assert result["data"]["inputs"] == [dataset["reference"], right["reference"]]
        assert result["data"]["sources"] == dataset["sources"] + right["sources"]
        if how == "left":
            assert result["data"]["rows"][1]["joined_after"] is None
    assert right == original


@pytest.mark.parametrize("failure", ["duplicate", "period"])
def test_invalid_join_is_rejected(dataset, failure):
    right = deepcopy(dataset)
    op = join(right)
    if failure == "duplicate":
        right["rows"].append(right["rows"][0])
    if failure == "period":
        right["as_of"] = "2026-08"
    with pytest.raises(ToolFailure):
        process_data({"data": dataset, "operations": [op]})


def test_explicit_cast_preserves_large_integer_and_rejects_loss(dataset):
    data = deepcopy(dataset)
    data["rows"] = [{"region": "9007199254740993", "before": 120, "after": 108}]
    result = process_data(
        {
            "data": data,
            "operations": [{"operation": "cast", "field": "region", "kind": "integer"}],
        }
    )
    assert result["data"]["rows"][0]["region"] == 9007199254740993
    data["rows"][0]["region"] = "1.5"
    with pytest.raises(ToolFailure):
        process_data(
            {
                "data": data,
                "operations": [
                    {"operation": "cast", "field": "region", "kind": "integer"}
                ],
            }
        )


def test_empty_and_invalid_operation(dataset):
    dataset["rows"] = []
    assert (
        process_data({"data": dataset, "operations": [calculation()]})["data"]["rows"]
        == []
    )
    with pytest.raises(ToolFailure):
        process_data(
            {"data": dataset, "operations": [{"operation": "eval", "code": "1+1"}]}
        )
