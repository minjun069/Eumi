"""합성 자료는 테스트 경계에만 둔다."""

import pytest


@pytest.fixture
def dataset():
    def column(name, kind="number", unit="index"):
        return {
            "name": name,
            "kind": kind,
            "unit": unit,
            "spatial_unit": "district",
            "temporal_unit": "month",
            "denominator": "same population",
        }

    return {
        "reference": {"id": "activity", "version": "v1"},
        "as_of": "2026-09",
        "sources": [{"label": "합성 자료", "uri": "fixture://activity"}],
        "columns": [
            column("region", "string", "code"),
            column("before"),
            column("after"),
        ],
        "rows": [
            {"region": "A", "before": 120.0, "after": 108.0},
            {"region": "B", "before": 100.0, "after": 92.0},
            {"region": "C", "before": 80.0, "after": None},
        ],
    }
