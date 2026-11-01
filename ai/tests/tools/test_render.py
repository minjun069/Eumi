from copy import deepcopy
from html.parser import HTMLParser
from xml.etree import ElementTree

import pytest

from src.exceptions import ToolFailure
from src.state import response_adapter
from src.tools.render import render_visualization


class HtmlReader(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):
        self.text.append(data)


def svg_root(content):
    start, end = content.index("<svg"), content.index("</svg>") + 6
    return ElementTree.fromstring(content[start:end])


def chart(kind="bar", **changes):
    return {
        "type": kind,
        "title": "활동지수",
        "x": "region",
        "y": "after",
        "unit": "index",
    } | changes


@pytest.fixture
def boundaries():
    def polygon(code, x):
        return {
            "code": code,
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[x, 37.0], [x + 0.1, 37.0], [x + 0.1, 37.1], [x, 37.1], [x, 37.0]],
                ],
            },
        }

    return {
        "reference": {"id": "districts", "version": "boundary-v1"},
        "as_of": "2026",
        "sources": [{"label": "합성 경계", "uri": "fixture://boundaries"}],
        "code_system": "code",
        "crs": "EPSG:4326",
        "features": [polygon("A", 127.0), polygon("B", 127.1), polygon("C", 127.2)],
    }


def map_spec(boundaries, **changes):
    return {
        "type": "map",
        "title": "활동지수 지도",
        "region": "region",
        "value": "after",
        "unit": "index",
        "code_system": "code",
        "boundaries": boundaries,
    } | changes


def test_table_has_real_cells_units_versions_and_safe_text(dataset):
    dataset["rows"][0]["region"] = '<script>alert("x")</script>'
    original = deepcopy(dataset)
    result = render_visualization(
        {
            "data": dataset,
            "spec": {"type": "table", "title": "비교", "fields": ["region", "after"]},
        }
    )
    artifact = result["artifact"]
    content = artifact["data"]["content"]
    reader = HtmlReader(content)
    assert "table" in reader.tags and "script" not in reader.tags
    assert '<script>alert("x")</script>' in reader.text
    assert "108.0" in reader.text and "결측" in reader.text
    assert "index" in content and "fixture://activity" in content and "v1" in content
    response_adapter.validate_python(
        {
            "id": "result",
            "kind": "final",
            "label": "표",
            "content": "비교 결과",
            "artifacts": [artifact],
        }
    )
    assert dataset == original


@pytest.mark.parametrize("kind", ["bar", "line"])
def test_chart_has_real_svg_values_applied_range_and_missing_note(dataset, kind):
    result = render_visualization({"data": dataset, "spec": chart(kind)})
    svg = svg_root(result["artifact"]["data"]["content"])
    assert svg.tag.endswith("svg")
    assert any("A: 108.0 index" in (node.text or "") for node in svg.iter())
    assert result["applied"]["value_range"]["maximum"] == 108
    assert result["warnings"]
    if kind == "bar":
        assert result["applied"]["value_range"]["minimum"] == 0


def test_line_gaps_and_negative_bars(dataset):
    dataset["rows"][0]["after"] = -10
    dataset["rows"][1]["after"] = None
    dataset["rows"][2]["after"] = 10
    line = render_visualization({"data": dataset, "spec": chart("line")})
    svg = svg_root(line["artifact"]["data"]["content"])
    path = [n for n in svg.iter() if n.attrib.get("stroke-width") == "2"][0]
    assert path.attrib["d"].count("M") == 2 and "L" not in path.attrib["d"]
    bars = render_visualization({"data": dataset, "spec": chart()})
    assert bars["applied"]["value_range"] == {"minimum": -10, "maximum": 10}


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": "percent"},
        {"y": "region"},
        {"x": "unknown"},
        {"color": 'red" onload="alert(1)'},
        {"value_range": {"minimum": 0, "maximum": 10}},
        {"value_range": {"minimum": 90, "maximum": 120}},
        {"value_range": {"minimum": 120, "maximum": 120}},
        {"value_range": {"minimum": 0, "maximum": float("inf")}},
    ],
)
def test_invalid_chart_settings(dataset, changes):
    with pytest.raises(ToolFailure):
        render_visualization({"data": dataset, "spec": chart(**changes)})


def test_no_chart_data_duplicate_axis_and_extreme_range(dataset):
    for rows in (
        [],
        [dataset["rows"][2]],
        [dataset["rows"][0]] * 2,
        [
            {"region": "A", "before": 1, "after": -1e308},
            {"region": "B", "before": 1, "after": 1e308},
        ],
    ):
        with pytest.raises(ToolFailure):
            render_visualization({"data": dataset | {"rows": rows}, "spec": chart()})
    result = render_visualization(
        {"data": dataset | {"rows": []}, "spec": {"type": "table", "title": "Empty"}}
    )
    assert result["warnings"] == ["조회된 자료가 없습니다."]


def test_map_preserves_boundary_provenance_and_missing_regions(dataset, boundaries):
    original = deepcopy(boundaries)
    result = render_visualization({"data": dataset, "spec": map_spec(boundaries)})
    svg = svg_root(result["artifact"]["data"]["content"])
    shapes = [n for n in svg.iter() if n.attrib.get("fill-rule") == "evenodd"]
    assert len(shapes) == 3
    assert shapes[2].attrib["fill"] == "#d1d5db"
    assert shapes[0].attrib["fill"] != shapes[1].attrib["fill"]
    assert "boundary-v1" in result["artifact"]["data"]["content"]
    assert result["sources"] == dataset["sources"] + boundaries["sources"]
    assert boundaries == original


def test_multipolygon_and_holes(dataset, boundaries):
    ring = boundaries["features"][0]["geometry"]["coordinates"][0]
    hole = [[127.02, 37.02], [127.03, 37.02], [127.03, 37.03], [127.02, 37.02]]
    boundaries["features"][0]["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [[ring, hole]],
    }
    result = render_visualization({"data": dataset, "spec": map_spec(boundaries)})
    svg = svg_root(result["artifact"]["data"]["content"])
    shapes = [n for n in svg.iter() if n.attrib.get("fill-rule") == "evenodd"]
    assert shapes[0].attrib["d"].count("M") == 2


@pytest.mark.parametrize(
    "failure", ["codes", "missing", "duplicate", "ring", "coordinate", "crs", "unit"]
)
def test_map_rejects_invalid_data_and_boundaries(dataset, boundaries, failure):
    spec = map_spec(boundaries)
    if failure == "codes":
        spec["code_system"] = "different"
    if failure == "missing":
        boundaries["features"].pop()
    if failure == "duplicate":
        boundaries["features"].append(boundaries["features"][0])
    if failure == "ring":
        boundaries["features"][0]["geometry"]["coordinates"][0].pop()
    if failure == "coordinate":
        boundaries["features"][0]["geometry"]["coordinates"][0][1] = [999.0, 37.0]
    if failure == "crs":
        boundaries["crs"] = "EPSG:3857"
    if failure == "unit":
        spec["unit"] = "%"
    with pytest.raises(ToolFailure):
        render_visualization({"data": dataset, "spec": spec})
