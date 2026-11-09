"""도구 실행 예제용 합성 자료. 실제 통계나 지역 위험도를 나타내지 않는다."""

from src.tools.data import Dataset
from src.tools.render import Boundaries


def activity() -> Dataset:
    common = {
        "spatial_unit": "synthetic_district",
        "temporal_unit": "month",
        "denominator": "synthetic population",
    }
    return {
        "reference": {"id": "synthetic_activity", "version": "v1"},
        "as_of": "2026-09",
        "sources": [{"label": "가상 지역 합성 자료", "uri": "fixture://activity/v1"}],
        "columns": [
            common | {"name": "region", "kind": "string", "unit": "synthetic_code"},
            common | {"name": "before", "kind": "number", "unit": "index"},
            common | {"name": "after", "kind": "number", "unit": "index"},
        ],
        "rows": [
            {"region": "A", "before": 120.0, "after": 108.0},
            {"region": "B", "before": 100.0, "after": 92.0},
            {"region": "C", "before": 80.0, "after": 72.0},
        ],
    }


def boundaries() -> Boundaries:
    return {
        "reference": {"id": "synthetic_boundaries", "version": "v1"},
        "as_of": "2026",
        "sources": [{"label": "가상 지역 합성 경계", "uri": "fixture://boundaries/v1"}],
        "code_system": "synthetic_code",
        "crs": "EPSG:4326",
        "features": [
            {
                "code": code,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [x, 37.0],
                            [x + 0.1, 37.0],
                            [x + 0.1, 37.1],
                            [x, 37.1],
                            [x, 37.0],
                        ]
                    ],
                },
            }
            for code, x in (("A", 127.0), ("B", 127.1), ("C", 127.2))
        ],
    }
