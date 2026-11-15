"""자료와 표현 명세를 시각화 산출물로 변환한다."""

from html import escape
from math import cos, isfinite, radians
from typing import Annotated, Literal, NotRequired

from pydantic import ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.exceptions import ToolFailure
from src.execution_trace import trace_tool_call
from src.tools.data import (
    DataReference,
    Dataset,
    Source,
    Text,
    read_dataset,
    require_columns,
    validate,
)

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Coordinate = Annotated[list[float], Field(min_length=2, max_length=2)]
Ring = Annotated[list[Coordinate], Field(min_length=4)]
PolygonCoordinates = Annotated[list[Ring], Field(min_length=1)]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class Polygon(TypedDict):
    type: Literal["Polygon"]
    coordinates: PolygonCoordinates


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class MultiPolygon(TypedDict):
    type: Literal["MultiPolygon"]
    coordinates: Annotated[list[PolygonCoordinates], Field(min_length=1)]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class BoundaryFeature(TypedDict):
    code: Text
    geometry: Annotated[Polygon | MultiPolygon, Field(discriminator="type")]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class Boundaries(TypedDict):
    reference: DataReference
    as_of: Text
    sources: Annotated[list[Source], Field(min_length=1)]
    code_system: Text
    crs: Literal["EPSG:4326"]
    features: Annotated[list[BoundaryFeature], Field(min_length=1)]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class ValueRange(TypedDict):
    minimum: float
    maximum: float


@with_config(ConfigDict(extra="forbid", strict=True))
class TableSpec(TypedDict):
    type: Literal["table"]
    title: Text
    fields: NotRequired[Annotated[list[Text], Field(min_length=1)]]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class ChartSpec(TypedDict):
    type: Literal["bar", "line"]
    title: Text
    x: Text
    y: Text
    unit: Text
    x_label: NotRequired[Text]
    y_label: NotRequired[Text]
    legend: NotRequired[Text]
    color: NotRequired[Color]
    value_range: NotRequired[ValueRange]
    orientation: NotRequired[Literal["vertical", "horizontal"]]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class MapSpec(TypedDict):
    type: Literal["map"]
    title: Text
    region: Text
    value: Text
    unit: Text
    code_system: Text
    boundaries: Boundaries
    legend: NotRequired[Text]
    color: NotRequired[Color]
    value_range: NotRequired[ValueRange]


RenderSpec = Annotated[TableSpec | ChartSpec | MapSpec, Field(discriminator="type")]


@with_config(ConfigDict(extra="forbid", strict=True))
class RenderRequest(TypedDict):
    data: Dataset
    spec: RenderSpec


class HtmlData(TypedDict):
    mime_type: Literal["text/html"]
    content: str


class RenderArtifact(TypedDict):
    type: Literal["table", "chart", "map"]
    data: HtmlData


class RenderResult(TypedDict):
    artifact: RenderArtifact
    applied: RenderSpec
    data_reference: DataReference
    sources: list[Source]
    as_of: str
    warnings: list[str]


render_adapter = TypeAdapter(RenderRequest)


def _text(value: object) -> str:
    return escape("결측" if value is None else str(value), quote=True)


def _table(data: Dataset, fields: list[str]) -> str:
    columns = require_columns(data, fields)
    headers = "".join(
        f'<th scope="col">{_text(name)} ({_text(columns[name]["unit"])})</th>'
        for name in fields
    )
    rows = "".join(
        "<tr>" + "".join(f"<td>{_text(row[name])}</td>" for name in fields) + "</tr>"
        for row in data["rows"]
    )
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"


def _measure(data: Dataset, field: str, unit: str) -> list[float | int]:
    column = require_columns(data, [field])[field]
    if column["kind"] not in {"integer", "number"}:
        raise ToolFailure("non_numeric_field")
    if column["unit"] != unit:
        raise ToolFailure("incompatible_units")
    return [row[field] for row in data["rows"] if row[field] is not None]


def _range(values: list[float | int], spec, *, zero: bool) -> tuple[float, float]:
    if "value_range" in spec:
        low, high = spec["value_range"]["minimum"], spec["value_range"]["maximum"]
        if low >= high or any(value < low or value > high for value in values):
            raise ToolFailure("invalid_range")
        if zero and not low <= 0 <= high:
            raise ToolFailure("invalid_range")
    else:
        low, high = min(values), max(values)
        if zero:
            low, high = min(low, 0), max(high, 0)
        if low == high:
            pad = abs(low) * 0.1 or 1
            low, high = low - pad, high + pad
    try:
        finite = all(isfinite(value) for value in (low, high, high - low))
    except OverflowError:
        finite = False
    if not finite:
        raise ToolFailure("invalid_range")
    return low, high


def _svg(title: str, body: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 560" '
        f'role="img" aria-label="{_text(title)}"><title>{_text(title)}</title>'
        '<rect width="900" height="560" fill="white"/>' + body + "</svg>"
    )


def _chart(data: Dataset, spec: ChartSpec) -> tuple[str, ChartSpec, list[str]]:
    require_columns(data, [spec["x"], spec["y"]])
    values = _measure(data, spec["y"], spec["unit"])
    if not values:
        raise ToolFailure("no_plottable_data")
    if len(data["rows"]) > 200:
        raise ToolFailure("too_many_marks")
    labels = [row[spec["x"]] for row in data["rows"]]
    if None in labels or len(set(labels)) != len(labels):
        raise ToolFailure("ambiguous_axis")
    low, high = _range(values, spec, zero=spec["type"] == "bar")
    applied = spec | {
        "color": spec.get("color", "#2563eb"),
        "legend": spec.get("legend", spec["y"]),
        "x_label": spec.get("x_label", spec["x"]),
        "y_label": spec.get("y_label", spec["y"]),
        "value_range": {"minimum": low, "maximum": high},
    }
    color = applied["color"]
    if spec.get("orientation") == "horizontal":
        if spec["type"] != "bar":
            raise ToolFailure("invalid_input")
        return _horizontal_bar(data, applied, low, high)
    step = 760 / len(labels)

    def y(value):
        return 430 - (value - low) / (high - low) * 340

    body = [f'<text x="70" y="30" font-size="20">{_text(spec["title"])}</text>']
    for tick in range(5):
        value = low + (high - low) * tick / 4
        ordinate = y(value)
        body.append(f'<path d="M70 {ordinate}H830" stroke="#e2e8f0"/>')
        body.append(
            f'<text x="62" y="{ordinate + 4}" text-anchor="end" '
            f'font-size="12">{value:.5g}</text>'
        )
    points = []
    for index, row in enumerate(data["rows"]):
        x = 70 + step * (index + 0.5)
        value = row[spec["y"]]
        label = str(row[spec["x"]])
        short_label = label if len(label) <= 16 else label[:15] + "…"
        body.append(
            f'<text x="{x}" y="452" text-anchor="end" '
            f'transform="rotate(-35 {x} 452)" font-size="11">'
            f"<title>{_text(label)}</title>{_text(short_label)}</text>"
        )
        if value is None:
            points.append(None)
            continue
        ordinate = y(value)
        tooltip = f"{_text(label)}: {_text(value)} {_text(spec['unit'])}"
        if spec["type"] == "bar":
            baseline = y(0)
            body.append(
                f'<rect x="{x - step * 0.32}" y="{min(ordinate, baseline)}" '
                f'width="{step * 0.64}" height="{abs(ordinate - baseline)}" '
                f'fill="{color}"><title>{tooltip}</title></rect>'
            )
        else:
            points.append((x, ordinate))
            body.append(
                f'<circle cx="{x}" cy="{ordinate}" r="4" fill="{color}">'
                f"<title>{tooltip}</title></circle>"
            )
    if spec["type"] == "line":
        # 결측 구간을 건너 연결하지 않는다. x는 입력 행 순서의 등간격 범주다.
        path, connected = [], False
        for point in points:
            if point is None:
                connected = False
            else:
                path.append(f"{'L' if connected else 'M'}{point[0]} {point[1]}")
                connected = True
        body.append(
            f'<path d="{" ".join(path)}" fill="none" stroke="{color}" '
            'stroke-width="2"/>'
        )
    body.extend(
        [
            '<text x="450" y="540" text-anchor="middle">'
            f"{_text(applied['x_label'])}</text>",
            f'<text x="70" y="63">{_text(applied["y_label"])} '
            f"({_text(spec['unit'])})</text>",
            f'<text x="620" y="63" fill="{color}">■ {_text(applied["legend"])}</text>',
        ]
    )
    warnings = []
    if len(values) < len(data["rows"]):
        warnings.append("결측값은 표시하지 않으며 선을 연결하지 않습니다.")
    if spec["type"] == "line":
        warnings.append("가로축은 입력 행 순서의 등간격 범주입니다.")
    return _svg(spec["title"], "".join(body)), applied, warnings


def _horizontal_bar(data, spec, low, high):
    def x(value):
        return 120 + (value - low) / (high - low) * 650

    body = [f'<text x="70" y="30" font-size="20">{_text(spec["title"])}</text>']
    for tick in range(5):
        value = low + (high - low) * tick / 4
        position = x(value)
        body.append(f'<path d="M{position} 75V445" stroke="#e2e8f0"/>')
        body.append(
            f'<text x="{position}" y="470" text-anchor="middle">{value:.5g}</text>'
        )
    step = 350 / len(data["rows"])
    for index, row in enumerate(data["rows"]):
        y = 90 + step * (index + 0.5)
        body.append(
            f'<text x="110" y="{y + 5}" text-anchor="end">'
            f"{_text(row[spec['x']])}</text>"
        )
        value = row[spec["y"]]
        if value is None:
            continue
        position, zero = x(value), x(0)
        body.append(
            f'<rect x="{min(position, zero)}" y="{y - step * 0.3}" '
            f'width="{abs(position - zero)}" height="{step * 0.6}" '
            f'fill="{spec["color"]}"/>'
        )
        body.append(
            f'<text x="{position + 7}" y="{y + 5}">'
            f"{value:.1f}{_text(spec['unit'])}</text>"
        )
    body.append(
        f'<text x="450" y="520" text-anchor="middle">'
        f"{_text(spec['y_label'])} ({_text(spec['unit'])})</text>"
    )
    warnings = (
        ["결측값은 표시하지 않습니다."]
        if any(r[spec["y"]] is None for r in data["rows"])
        else []
    )
    return _svg(spec["title"], "".join(body)), spec, warnings


def _polygons(feature: BoundaryFeature):
    geometry = feature["geometry"]
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    return geometry["coordinates"]


def _map(data: Dataset, spec: MapSpec) -> tuple[str, MapSpec, list[str]]:
    column = require_columns(data, [spec["region"], spec["value"]])[spec["region"]]
    boundaries = spec["boundaries"]
    if column["kind"] != "string" or not (
        column["unit"] == spec["code_system"] == boundaries["code_system"]
    ):
        raise ToolFailure("region_code_mismatch")
    values = _measure(data, spec["value"], spec["unit"])
    if not values:
        raise ToolFailure("no_plottable_data")
    rows = {row[spec["region"]]: row[spec["value"]] for row in data["rows"]}
    features = {feature["code"]: feature for feature in boundaries["features"]}
    if (
        None in rows
        or len(rows) != len(data["rows"])
        or len(features) != len(boundaries["features"])
    ):
        raise ToolFailure("ambiguous_region")
    if rows.keys() - features.keys():
        raise ToolFailure("boundary_not_found")
    # 자료에 없는 지역은 배경 경계를 보여 주되 결측으로 구별한다.
    coordinates = []
    for feature in features.values():
        for polygon in _polygons(feature):
            for ring in polygon:
                if ring[0] != ring[-1]:
                    raise ToolFailure("invalid_boundary")
                area = sum(
                    a[0] * b[1] - b[0] * a[1]
                    for a, b in zip(ring, ring[1:], strict=False)
                )
                if area == 0:
                    raise ToolFailure("invalid_boundary")
                for lon, lat in ring:
                    if not -180 <= lon <= 180 or not -90 < lat < 90:
                        raise ToolFailure("invalid_boundary")
                    coordinates.append((lon, lat))
    west, east = min(p[0] for p in coordinates), max(p[0] for p in coordinates)
    south, north = min(p[1] for p in coordinates), max(p[1] for p in coordinates)
    if west == east or south == north or east - west > 180:
        raise ToolFailure("unsupported_bounds")
    aspect = cos(radians((north + south) / 2))
    scale = min(760 / ((east - west) * aspect), 350 / (north - south))
    x_offset = (900 - (east - west) * aspect * scale) / 2
    y_offset = 80 + (350 - (north - south) * scale) / 2

    def point(lon, lat):
        return x_offset + (lon - west) * aspect * scale, y_offset + (
            north - lat
        ) * scale

    low, high = _range(values, spec, zero=False)
    color = spec.get("color", "#2563eb")
    base = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    body = [f'<text x="70" y="30" font-size="20">{_text(spec["title"])}</text>']
    for code, feature in features.items():
        value = rows.get(code)
        if value is None:
            fill = "#d1d5db"
        else:
            weight = 0.15 + 0.85 * (value - low) / (high - low)
            fill = "#" + "".join(
                f"{round(255 + (channel - 255) * weight):02x}" for channel in base
            )
        paths = []
        for polygon in _polygons(feature):
            for ring in polygon:
                points = [point(lon, lat) for lon, lat in ring]
                paths.append(
                    "M" + " L".join(f"{x:.3f} {y:.3f}" for x, y in points) + " Z"
                )
        body.append(
            f'<path d="{" ".join(paths)}" fill="{fill}" fill-rule="evenodd" '
            f'stroke="#64748b"><title>{_text(code)}: {_text(value)} '
            f"{_text(spec['unit'])}</title></path>"
        )
    legend = spec.get("legend", spec["value"])
    light = "#" + "".join(
        f"{round(255 + (channel - 255) * 0.15):02x}" for channel in base
    )
    body.append(
        f'<defs><linearGradient id="scale"><stop stop-color="{light}"/>'
        f'<stop offset="1" stop-color="{color}"/></linearGradient></defs>'
        '<rect x="70" y="470" width="300" height="16" fill="url(#scale)"/>'
    )
    body.append(
        f'<text x="70" y="455">{_text(legend)} ({_text(spec["unit"])})</text>'
        f'<text x="70" y="510">{low:.5g}</text>'
        f'<text x="370" y="510" text-anchor="end">{high:.5g}</text>'
        '<rect x="460" y="470" width="18" height="16" fill="#d1d5db"/>'
        '<text x="488" y="484">자료 없음</text>'
    )
    warnings = ["경위도를 지역 중심 위도로 보정해 표시한 참고 지도입니다."]
    if features.keys() - rows.keys() or any(value is None for value in rows.values()):
        warnings.append("자료가 없는 지역은 회색으로 표시합니다.")
    applied = spec | {
        "color": color,
        "legend": legend,
        "value_range": {"minimum": low, "maximum": high},
    }
    return _svg(spec["title"], "".join(body)), applied, warnings


@trace_tool_call(render_adapter)
def render_visualization(request: RenderRequest) -> RenderResult:
    request = validate(render_adapter, request)
    data = read_dataset(request["data"])
    spec = request["spec"]
    sources = list(data["sources"])
    warnings = []
    if spec["type"] == "table":
        fields = spec.get("fields", [c["name"] for c in data["columns"]])
        body = _table(data, fields)
        applied = spec | {"fields": fields}
        artifact_type = "table"
        if not data["rows"]:
            warnings.append("조회된 자료가 없습니다.")
    else:
        if spec["type"] == "map":
            body, applied, warnings = _map(data, spec)
            artifact_type = "map"
            for source in spec["boundaries"]["sources"]:
                if source not in sources:
                    sources.append(source)
            fields = [spec["region"], spec["value"]]
        else:
            body, applied, warnings = _chart(data, spec)
            artifact_type = "chart"
            fields = [spec["x"], spec["y"]]
        body += (
            "<details><summary>표로 보기</summary>"
            + _table(data, fields)
            + "</details>"
        )
    provenance = f"<p>자료: {_text(data['reference']['id'])} · 버전: "
    provenance += (
        f"{_text(data['reference']['version'])} · 기준 시점: {_text(data['as_of'])}</p>"
    )
    if spec["type"] == "map":
        boundary = spec["boundaries"]
        provenance += f"<p>경계: {_text(boundary['reference']['id'])} · 버전: "
        provenance += (
            f"{_text(boundary['reference']['version'])} · 기준 시점: "
            f"{_text(boundary['as_of'])}</p>"
        )
    provenance += (
        "<ul>"
        + "".join(f"<li>{_text(s['label'])}: {_text(s['uri'])}</li>" for s in sources)
        + "</ul>"
    )
    notes = "".join(f"<p>{_text(note)}</p>" for note in warnings)
    content = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_text(spec['title'])}</title><style>"
        "body{font-family:system-ui,sans-serif;color:#1e293b;margin:24px;max-width:1100px}"
        "svg{width:100%;height:auto}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #cbd5e1;padding:8px;text-align:left}"
        "th{background:#f1f5f9}p,li{overflow-wrap:anywhere}details{margin-top:16px}"
        f"</style></head><body><h1>{_text(spec['title'])}</h1>"
        f"{body}{notes}{provenance}</body></html>"
    )
    return {
        "artifact": {
            "type": artifact_type,
            "data": {"mime_type": "text/html", "content": content},
        },
        "applied": applied,
        "data_reference": data["reference"],
        "sources": sources,
        "as_of": data["as_of"],
        "warnings": warnings,
    }
