"""등록된 공급 함수에서 자료를 읽어 조건·정렬·필드·페이지를 적용한다."""

from collections.abc import Callable, Mapping
from typing import Annotated, Literal, NotRequired

from pydantic import ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.exceptions import ToolFailure
from src.tools.data import (
    Dataset,
    Scalar,
    Text,
    derived_dataset,
    read_dataset,
    require_columns,
    validate,
)


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class Filter(TypedDict):
    field: Text
    operator: Literal["eq", "ne", "lt", "le", "gt", "ge", "contains", "is_null"]
    value: Scalar


@with_config(ConfigDict(extra="forbid", strict=True))
class Sort(TypedDict):
    field: Text
    descending: bool


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class QueryRequest(TypedDict):
    target: Text
    version: NotRequired[Text]
    as_of: NotRequired[Text]
    filters: NotRequired[list[Filter]]
    fields: NotRequired[Annotated[list[Text], Field(min_length=1)]]
    sort: NotRequired[list[Sort]]
    offset: NotRequired[Annotated[int, Field(ge=0)]]
    limit: NotRequired[Annotated[int, Field(ge=1, le=10000)]]


class QueryResult(TypedDict):
    data: Dataset
    applied: QueryRequest
    total: int
    returned: int
    next_offset: int | None


# 연결 시 이미 허용된 자료원만 등록한다. 공급 함수는 원본 접근 권한을 검사한다.
DataProvider = Callable[[], Dataset]
query_adapter = TypeAdapter(QueryRequest)


def matching_rows(data: Dataset, filters: list[Filter]) -> list[dict[str, Scalar]]:
    columns = require_columns(data, list(dict.fromkeys(f["field"] for f in filters)))
    for condition in filters:
        op, value = condition["operator"], condition["value"]
        kind = columns[condition["field"]]["kind"]
        valid_types = {
            "string": (str,),
            "integer": (int,),
            "number": (int, float),
            "boolean": (bool,),
        }[kind]
        if op == "is_null":
            valid = type(value) is bool
        elif op == "contains":
            valid = kind == "string" and isinstance(value, str)
        else:
            valid = type(value) in valid_types or (value is None and op in {"eq", "ne"})
            valid = valid and not (kind == "boolean" and op not in {"eq", "ne"})
        if not valid:
            raise ToolFailure("invalid_condition")

    def matches(row, condition):
        value = row[condition["field"]]
        expected = condition["value"]
        match condition["operator"]:
            case "is_null":
                return (value is None) == expected
            case "eq":
                return value == expected
            case "ne":
                return value != expected
        if value is None:
            return False
        match condition["operator"]:
            case "contains":
                return expected.casefold() in value.casefold()
            case "lt":
                return value < expected
            case "le":
                return value <= expected
            case "gt":
                return value > expected
            case "ge":
                return value >= expected
        return False

    return [row for row in data["rows"] if all(matches(row, f) for f in filters)]


def query_data(
    request: QueryRequest, providers: Mapping[str, DataProvider]
) -> QueryResult:
    request = validate(query_adapter, request)
    target = request["target"]
    if target not in providers:
        raise ToolFailure("reference_not_found")
    if request.get("offset", 0) and "version" not in request:
        raise ToolFailure("version_required")
    try:
        data = read_dataset(providers[target]())
    except PermissionError as exc:
        raise ToolFailure("permission_denied") from exc
    except (TimeoutError, ConnectionError) as exc:
        raise ToolFailure("read_unavailable", retryable=True) from exc
    if data["reference"]["id"] != target:
        raise ToolFailure("reference_mismatch")
    if "version" in request and request["version"] != data["reference"]["version"]:
        raise ToolFailure("version_mismatch")
    if "as_of" in request and request["as_of"] != data["as_of"]:
        raise ToolFailure("as_of_mismatch")
    fields = request.get("fields", [c["name"] for c in data["columns"]])
    require_columns(data, fields)
    sorting = request.get("sort", [])
    require_columns(data, [item["field"] for item in sorting])
    rows = matching_rows(data, request.get("filters", []))
    # 안정 정렬과 원본 순서로 페이지를 재현한다. null은 방향과 무관하게 마지막.
    for item in reversed(sorting):
        field = item["field"]
        present = [r for r in rows if r[field] is not None]
        absent = [r for r in rows if r[field] is None]
        rows = (
            sorted(present, key=lambda r: r[field], reverse=item["descending"]) + absent
        )
    offset, limit = request.get("offset", 0), request.get("limit", 100)
    selected = rows[offset : offset + limit]
    result = derived_dataset(
        data
        | {
            "columns": [
                next(c for c in data["columns"] if c["name"] == f) for f in fields
            ],
            "rows": [{field: row[field] for field in fields} for row in selected],
        },
        [data],
    )
    applied = request | {
        "version": data["reference"]["version"],
        "as_of": data["as_of"],
        "fields": fields,
        "filters": request.get("filters", []),
        "sort": sorting,
        "offset": offset,
        "limit": limit,
    }
    return {
        "data": result,
        "applied": applied,
        "total": len(rows),
        "returned": len(selected),
        "next_offset": offset + limit if offset + limit < len(rows) else None,
    }
