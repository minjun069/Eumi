"""요청한 연산에 따라 자료를 가공하고 결과를 구성한다."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Annotated, Literal, NotRequired

from pydantic import ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.exceptions import ToolFailure
from src.execution_trace import trace_span
from src.tools.data import (
    Column,
    Dataset,
    Text,
    compatible,
    derived_dataset,
    read_dataset,
    require_columns,
    validate,
)
from src.tools.query import Filter, Sort, matching_rows


@with_config(ConfigDict(extra="forbid", strict=True))
class Calculate(TypedDict):
    operation: Literal["calculate"]
    method: Literal["difference", "ratio", "percentage", "percent_change"]
    before: Text
    after: Text
    output: Text


@with_config(ConfigDict(extra="forbid", strict=True))
class Aggregate(TypedDict):
    operation: Literal["aggregate"]
    method: Literal["sum", "mean", "min", "max", "count"]
    field: Text
    group_by: list[Text]
    output: Text


@with_config(ConfigDict(extra="forbid", strict=True))
class Join(TypedDict):
    operation: Literal["join"]
    right: Dataset
    keys: Annotated[list[Text], Field(min_length=1)]
    how: Literal["inner", "left"]
    # 오른쪽 원본 열 -> 새 결과 열. 덮어쓰기와 자동 suffix는 허용하지 않는다.
    fields: Annotated[dict[Text, Text], Field(min_length=1)]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class FilterRows(TypedDict):
    operation: Literal["filter"]
    conditions: list[Filter]


@with_config(ConfigDict(extra="forbid", strict=True))
class Cast(TypedDict):
    operation: Literal["cast"]
    field: Text
    kind: Literal["string", "integer", "number"]


@with_config(ConfigDict(extra="forbid", strict=True))
class SortRows(TypedDict):
    operation: Literal["sort"]
    by: Annotated[list[Sort], Field(min_length=1)]


Operation = Annotated[
    Calculate | Aggregate | Join | FilterRows | Cast | SortRows,
    Field(discriminator="operation"),
]


@with_config(ConfigDict(extra="forbid", strict=True))
class ProcessRequest(TypedDict):
    data: Dataset
    operations: Annotated[list[Operation], Field(min_length=1)]
    missing: NotRequired[Literal["error", "drop", "preserve"]]
    fields: NotRequired[Annotated[list[Text], Field(min_length=1)]]
    decimals: NotRequired[Annotated[int, Field(ge=0, le=12)]]


class OperationCount(TypedDict):
    operation: str
    input_rows: int
    output_rows: int
    excluded_rows: int


class ProcessResult(TypedDict):
    data: Dataset
    operations: list[Operation]
    missing: Literal["error", "drop", "preserve"]
    decimals: int | None
    input_rows: int
    output_rows: int
    excluded_rows: int
    counts: list[OperationCount]


process_adapter = TypeAdapter(ProcessRequest)


def _number_column(column: Column) -> None:
    if column["kind"] not in {"number", "integer"}:
        raise ToolFailure("non_numeric_field")


def _finite(value: int | float) -> int | float:
    try:
        valid = isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ToolFailure("non_finite_result")
    return value


def _missing_rows(data: Dataset, fields: list[str], policy: str) -> int:
    absent = [row for row in data["rows"] if any(row[f] is None for f in fields)]
    if absent and policy == "error":
        raise ToolFailure("missing_value")
    if policy == "drop":
        data["rows"] = [
            row for row in data["rows"] if all(row[f] is not None for f in fields)
        ]
        return len(absent)
    return 0


def _calculate(data: Dataset, op: Calculate, missing: str) -> int:
    before, after, output = op["before"], op["after"], op["output"]
    columns = require_columns(data, list(dict.fromkeys([before, after])))
    if output in columns:
        raise ToolFailure("duplicate_field")
    for field in (before, after):
        _number_column(columns[field])
    compatible(columns[before], columns[after])
    excluded = _missing_rows(data, [before, after], missing)
    for row in data["rows"]:
        left, right = row[before], row[after]
        if left is None or right is None:
            row[output] = None
            continue
        if op["method"] != "difference" and left == 0:
            raise ToolFailure("zero_denominator")
        try:
            value = right - left
            if op["method"] == "ratio":
                value = right / left
            elif op["method"] == "percentage":
                value = right / left * 100
            elif op["method"] == "percent_change":
                value = (right - left) / left * 100
            row[output] = _finite(value)
        except OverflowError as exc:
            raise ToolFailure("non_finite_result") from exc
    column = columns[before] | {"name": output, "kind": "number"}
    if op["method"] != "difference":
        column["unit"] = "ratio" if op["method"] == "ratio" else "%"
    data["columns"].append(column)
    return excluded


def _aggregate(data: Dataset, op: Aggregate, missing: str) -> int:
    groups, field = op["group_by"], op["field"]
    columns = require_columns(data, groups)
    require_columns(data, [field])
    if op["output"] in groups:
        raise ToolFailure("duplicate_field")
    if op["method"] != "count":
        _number_column(columns[field])
    excluded = _missing_rows(data, list(dict.fromkeys([*groups, field])), missing)
    buckets = {}
    for row in data["rows"]:
        key = tuple(row[name] for name in groups)
        buckets.setdefault(key, []).append(row[field])
    rows = []
    for key, values in buckets.items():
        # preserve에서는 결측을 생략한 집계를 만들어 내지 않는다.
        if None in values:
            value = None
        elif op["method"] == "count":
            value = len(values)
        elif op["method"] == "sum":
            value = _finite(sum(values))
        elif op["method"] == "mean":
            value = _finite(sum(values) / len(values))
        elif op["method"] == "min":
            value = min(values)
        else:
            value = max(values)
        rows.append(dict(zip(groups, key, strict=True)) | {op["output"]: value})
    column = columns[field] | {"name": op["output"], "kind": "number"}
    if op["method"] == "count":
        column.update(kind="integer", unit="rows", denominator="rows")
    data["columns"] = [columns[name] for name in groups] + [column]
    data["rows"] = rows
    return excluded


def _join(data: Dataset, op: Join, inputs: list[Dataset]) -> int:
    right = read_dataset(op["right"])
    if data["as_of"] != right["as_of"]:
        raise ToolFailure("as_of_mismatch")
    keys, mapping = op["keys"], op["fields"]
    left_columns = require_columns(data, keys)
    right_columns = require_columns(right, keys)
    require_columns(right, list(mapping))
    if (
        len(set(mapping.values())) != len(mapping)
        or set(mapping.values()) & left_columns.keys()
    ):
        raise ToolFailure("duplicate_field")
    for key in keys:
        compatible(left_columns[key], right_columns[key])
        if left_columns[key]["kind"] != right_columns[key]["kind"]:
            raise ToolFailure("join_key_mismatch")
    index = {}
    for row in right["rows"]:
        key = tuple(row[name] for name in keys)
        if None in key or key in index:
            raise ToolFailure("ambiguous_join")
        index[key] = row
    rows = []
    for row in data["rows"]:
        key = tuple(row[name] for name in keys)
        if None in key:
            raise ToolFailure("missing_join_key")
        match = index.get(key)
        if match is None and op["how"] == "inner":
            continue
        rows.append(
            row | {dest: match[src] if match else None for src, dest in mapping.items()}
        )
    excluded = len(data["rows"]) - len(rows)
    data["rows"] = rows
    data["columns"].extend(
        right_columns[src] | {"name": dest} for src, dest in mapping.items()
    )
    inputs.append(right)
    return excluded


def _cast(data: Dataset, op: Cast, missing: str) -> int:
    field, kind = op["field"], op["kind"]
    columns = require_columns(data, [field])
    excluded = _missing_rows(data, [field], missing)
    for row in data["rows"]:
        value = row[field]
        if value is None:
            continue
        try:
            if kind == "string":
                row[field] = str(value)
            else:
                if isinstance(value, bool):
                    raise ValueError("Boolean is not a measurement")
                if kind == "integer":
                    number = Decimal(str(value))
                    if not number.is_finite() or number != number.to_integral_value():
                        raise ValueError("Lossy integer conversion")
                    row[field] = int(number)
                else:
                    row[field] = _finite(float(value))
        except (ValueError, OverflowError, InvalidOperation) as exc:
            raise ToolFailure("invalid_cast") from exc
    columns[field]["kind"] = kind
    return excluded


def process_data(request: ProcessRequest) -> ProcessResult:
    request = validate(process_adapter, request)
    data = read_dataset(request["data"])
    inputs = [deepcopy(data)]
    missing = request.get("missing", "error")
    counts: list[OperationCount] = []
    for op in request["operations"]:
        with trace_span(
            "operation",
            op["operation"],
            {"operation": op, "data": data, "missing": missing},
        ) as span:
            before = len(data["rows"])
            match op["operation"]:
                case "calculate":
                    excluded = _calculate(data, op, missing)
                case "aggregate":
                    excluded = _aggregate(data, op, missing)
                case "join":
                    excluded = _join(data, op, inputs)
                case "cast":
                    excluded = _cast(data, op, missing)
                case "filter":
                    data["rows"] = matching_rows(data, op["conditions"])
                    excluded = before - len(data["rows"])
                case "sort":
                    require_columns(
                        data, list(dict.fromkeys(s["field"] for s in op["by"]))
                    )
                    for order in reversed(op["by"]):
                        field = order["field"]
                        present = [r for r in data["rows"] if r[field] is not None]
                        absent = [r for r in data["rows"] if r[field] is None]
                        data["rows"] = (
                            sorted(
                                present,
                                key=lambda r: r[field],
                                reverse=order["descending"],
                            )
                            + absent
                        )
                    excluded = 0
            counts.append(
                {
                    "operation": op["operation"],
                    "input_rows": before,
                    "output_rows": len(data["rows"]),
                    "excluded_rows": excluded,
                }
            )
            if span:
                span.update(output={"data": data, "counts": counts[-1]})
    if "fields" in request:
        columns = require_columns(data, request["fields"])
        data["columns"] = [columns[name] for name in request["fields"]]
        data["rows"] = [
            {name: row[name] for name in request["fields"]} for row in data["rows"]
        ]
    if "decimals" in request:
        for row in data["rows"]:
            for name, value in row.items():
                if type(value) is float:
                    row[name] = round(value, request["decimals"])
    return {
        "data": derived_dataset(data, inputs),
        "operations": request["operations"],
        "missing": missing,
        "decimals": request.get("decimals"),
        "input_rows": len(inputs[0]["rows"]),
        "output_rows": len(data["rows"]),
        "excluded_rows": sum(item["excluded_rows"] for item in counts),
        "counts": counts,
    }
