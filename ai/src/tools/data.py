"""도구 사이에 전달하는 자료 스냅샷과 경계 검증."""

import json
from copy import deepcopy
from hashlib import sha256
from typing import Annotated, Literal, NotRequired

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, with_config
from typing_extensions import TypedDict

from src.exceptions import ToolFailure

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Scalar = str | int | float | bool | None


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class Source(TypedDict):
    label: Text
    uri: Text


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class Column(TypedDict):
    name: Text
    kind: Literal["string", "integer", "number", "boolean"]
    unit: Text
    # 비교할 수 있는 공간·시간 단위와 분모 정의. 기간 값 자체는 행에 둔다.
    spatial_unit: Text
    temporal_unit: Text
    denominator: Text


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class DataReference(TypedDict):
    id: Text
    version: Text


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class Dataset(TypedDict):
    reference: DataReference
    as_of: Text
    sources: Annotated[list[Source], Field(min_length=1)]
    columns: Annotated[list[Column], Field(min_length=1)]
    rows: list[dict[str, Scalar]]
    # 가공·조회 결과의 실제 입력 참조. 별도 State 필드에 복제하지 않는다.
    inputs: NotRequired[list[DataReference]]


dataset_adapter = TypeAdapter(Dataset)


def validate[T](adapter: TypeAdapter[T], value: object, code="invalid_input") -> T:
    """외부 입력·자료원 반환값의 형식 오류를 도구 실패로 전달한다."""
    try:
        return adapter.validate_python(value)
    except ValidationError as exc:
        raise ToolFailure(code) from exc


def read_dataset(value: object, code="invalid_data") -> Dataset:
    data = validate(dataset_adapter, value, code)
    columns = {column["name"]: column for column in data["columns"]}
    if len(columns) != len(data["columns"]):
        raise ToolFailure(code)
    kinds = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
    }
    for row in data["rows"]:
        if row.keys() != columns.keys():
            raise ToolFailure(code)
        for name, value in row.items():
            if value is not None and type(value) not in kinds[columns[name]["kind"]]:
                raise ToolFailure(code)
    return deepcopy(data)


def require_columns(data: Dataset, names: list[str]) -> dict[str, Column]:
    columns = {column["name"]: column for column in data["columns"]}
    if len(set(names)) != len(names) or set(names) - columns.keys():
        raise ToolFailure("invalid_field")
    return columns


def compatible(left: Column, right: Column) -> None:
    if any(
        left[key] != right[key]
        for key in ("unit", "spatial_unit", "temporal_unit", "denominator")
    ):
        raise ToolFailure("incompatible_units")


def derived_dataset(data: Dataset, inputs: list[Dataset]) -> Dataset:
    """결과 내용으로 참조를 만들고 입력 출처·참조를 보존한다."""
    data = deepcopy(data)
    data["inputs"] = []
    data["sources"] = []
    for source in inputs:
        for ref in [source["reference"], *source.get("inputs", [])]:
            if ref not in data["inputs"]:
                data["inputs"].append(deepcopy(ref))
        for citation in source["sources"]:
            if citation not in data["sources"]:
                data["sources"].append(deepcopy(citation))
    payload = {key: value for key, value in data.items() if key != "reference"}
    digest = sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    data["reference"] = {"id": f"derived:{digest}", "version": digest}
    return read_dataset(data)
