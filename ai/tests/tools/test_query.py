from copy import deepcopy

import pytest

from src.exceptions import ToolFailure
from src.tools.query import query_data


def test_filter_sort_project_page_and_provenance(dataset):
    original = deepcopy(dataset)
    result = query_data(
        {
            "target": "activity",
            "fields": ["region", "before"],
            "filters": [{"field": "before", "operator": "ge", "value": 100}],
            "sort": [{"field": "before", "descending": False}],
            "limit": 1,
        },
        {"activity": lambda: dataset},
    )
    assert result["data"]["rows"] == [{"region": "B", "before": 100.0}]
    assert result["total"] == 2 and result["returned"] == 1
    assert result["data"]["inputs"] == [dataset["reference"]]
    assert result["data"]["sources"] == dataset["sources"]
    page = query_data(
        result["applied"] | {"offset": result["next_offset"]},
        {"activity": lambda: dataset},
    )
    assert page["data"]["rows"] == [{"region": "A", "before": 120.0}]
    assert page["next_offset"] is None
    result["data"]["sources"][0]["label"] = "changed"
    assert dataset == original


def test_empty_is_success_and_null_sorts_last(dataset):
    result = query_data(
        {
            "target": "activity",
            "filters": [{"field": "region", "operator": "eq", "value": "missing"}],
        },
        {"activity": lambda: dataset},
    )
    assert result["returned"] == result["total"] == 0
    for descending in (False, True):
        result = query_data(
            {
                "target": "activity",
                "sort": [{"field": "after", "descending": descending}],
            },
            {"activity": lambda: dataset},
        )
        assert result["data"]["rows"][-1]["after"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"target": "arbitrary_sql"},
        {"sql": "select 1"},
        {"limit": 0},
        {"limit": True},
        {"offset": 1},
        {"version": "old"},
        {"as_of": "old"},
        {"fields": ["unknown"]},
        {"fields": ["region", "region"]},
        {"filters": [{"field": "before", "operator": "ge", "value": "100"}]},
        {"filters": [{"field": "before", "operator": "contains", "value": "1"}]},
        {"filters": [{"field": "region", "operator": "is_null", "value": "true"}]},
    ],
)
def test_invalid_query_is_rejected(dataset, patch):
    with pytest.raises(ToolFailure):
        query_data({"target": "activity"} | patch, {"activity": lambda: dataset})


@pytest.mark.parametrize(
    "error,retryable",
    [
        (PermissionError, False),
        (TimeoutError, True),
        (ConnectionError, True),
    ],
)
def test_provider_failures_are_not_empty_results(error, retryable):
    def fail():
        raise error("internal provider detail")

    with pytest.raises(ToolFailure) as caught:
        query_data({"target": "activity"}, {"activity": fail})
    assert caught.value.retryable is retryable
    assert "internal provider detail" not in str(caught.value)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "120"])
def test_invalid_provider_values_are_rejected(dataset, bad):
    dataset["rows"][0]["before"] = bad
    with pytest.raises(ToolFailure):
        query_data({"target": "activity"}, {"activity": lambda: dataset})


def test_provider_schema_reference_and_page_version(dataset):
    for bad in (
        dataset | {"reference": {"id": "other", "version": "v1"}},
        dataset | {"columns": dataset["columns"] * 2},
        dataset | {"rows": [{"region": "A"}]},
    ):
        with pytest.raises(ToolFailure):
            query_data({"target": "activity"}, {"activity": lambda bad=bad: bad})
    first = query_data(
        {"target": "activity", "limit": 1}, {"activity": lambda: dataset}
    )
    dataset["reference"]["version"] = "v2"
    with pytest.raises(ToolFailure):
        query_data(first["applied"] | {"offset": 1}, {"activity": lambda: dataset})


def test_text_search_and_missing_filter(dataset):
    result = query_data(
        {
            "target": "activity",
            "filters": [
                {"field": "region", "operator": "contains", "value": "c"},
                {"field": "after", "operator": "is_null", "value": True},
            ],
        },
        {"activity": lambda: dataset},
    )
    assert [row["region"] for row in result["data"]["rows"]] == ["C"]
