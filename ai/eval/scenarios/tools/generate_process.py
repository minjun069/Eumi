"""데이터 가공(T02)의 평가 항목 11개에 각각 10건, 총 110건을 작성한다.

업무 모듈이나 실행 결과는 읽지 않는다. 정답 수치, 행 순서, 결합 결과,
반올림값과 단계별 건수는 아래에 명시하며 도구 연산을 재실행하지 않는다.
"""

import argparse
import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "process-data.json"
DESTINATION = ROOT / "process.json"


def expectation(check, path, value=None, *, match="equal"):
    item = {"check": check, "path": path}
    if match != "equal":
        item["match"] = match
    if match not in {"present", "absent"}:
        item["value"] = deepcopy(value)
    return item


def calculate(method="difference", output="result"):
    return {
        "operation": "calculate",
        "method": method,
        "before": "before",
        "after": "after",
        "output": output,
    }


def aggregate(method="sum", field="value", output="summary"):
    return {
        "operation": "aggregate",
        "method": method,
        "field": field,
        "group_by": ["area"],
        "output": output,
    }


def sort(field, descending=False):
    return {"operation": "sort", "by": [{"field": field, "descending": descending}]}


def column(source, original_name, **changes):
    original = next(item for item in source["columns"] if item["name"] == original_name)
    return deepcopy(original) | changes


def declared_rows(source, identifiers, values, output="result"):
    """명시된 정답 순서와 수치를 원본의 설명 열에 붙인다. 연산은 수행하지 않는다."""
    rows = {row["record_id"]: row for row in source["rows"]}
    return [
        deepcopy(rows[key]) | {output: value}
        for key, value in zip(identifiers, values, strict=True)
    ]


def build_suite(datasets, source_hash):
    cases = []

    def add(case_id, purpose, arguments, items, category, reference):
        cases.append(
            {
                "id": case_id,
                "unit": "tool",
                "target": "process_data",
                "purpose": purpose,
                "arguments": deepcopy(arguments),
                "assessment": {
                    "reference": {
                        "source": "eval/scenarios/tools/process-data.json",
                        "source_sha256": source_hash,
                        "specification": "docs/agent/components.md#22-데이터-가공",
                        "evaluation": "eval/docs/tools.md#12-데이터-가공",
                        "rule": purpose,
                        "construction": "원본과 명시한 계산값·행 수로 작성. "
                        "업무 함수를 실행하지 않음.",
                        **reference,
                    },
                    "expected": {
                        "schema_version": "tool-expectations-v1",
                        "items": items,
                    },
                    "checks": ["T-I.1", "T-O.1", "T-O.2", "T-O.5"],
                    "tolerance": {"absolute": 0, "relative": 0},
                    "required": True,
                },
                "tags": [
                    "T02",
                    category,
                    "rejected" if "failure_code" in reference else "normal",
                ],
            }
        )

    def normal(
        case_id,
        purpose,
        source_name,
        operations,
        rows,
        columns,
        counts,
        totals,
        *,
        category,
        settings=None,
        inputs=None,
        derivation,
    ):
        source = datasets[source_name]
        arguments = {"data": source, "operations": operations, **(settings or {})}
        source_names = inputs or [source_name]
        references = [datasets[name]["reference"] for name in source_names]
        sources = [
            citation for name in source_names for citation in datasets[name]["sources"]
        ]
        items = [
            expectation("T-I.1", "/output/operations", operations),
            expectation("T-I.1", "/observations/provider_calls", 0),
            expectation("T-O.1", "/output/data/rows", rows),
            expectation("T-O.1", "/output/data/columns", columns),
            expectation("T-O.1", "/output/input_rows", totals[0]),
            expectation("T-O.1", "/output/output_rows", totals[1]),
            expectation("T-O.1", "/output/excluded_rows", totals[2]),
            expectation(
                "T-O.1",
                "/output/counts",
                [
                    {
                        "operation": name,
                        "input_rows": before,
                        "output_rows": after,
                        "excluded_rows": excluded,
                    }
                    for name, before, after, excluded in counts
                ],
            ),
            expectation("T-O.1", "/output/missing", arguments.get("missing", "error")),
            expectation("T-O.1", "/output/decimals", arguments.get("decimals")),
            expectation("T-O.2", "/run/status", "returned"),
            expectation("T-O.2", "/failure", None),
            expectation("T-O.5", "/output/data/as_of", source["as_of"]),
            expectation("T-O.5", "/output/data/inputs", references),
            expectation("T-O.5", "/output/data/sources", sources),
            expectation("T-O.5", "/output/data/reference/id", match="present"),
            expectation("T-O.5", "/output/data/reference/version", match="present"),
        ]
        add(
            case_id,
            purpose,
            arguments,
            items,
            category,
            {
                "datasets": source_names,
                "calculation": derivation,
                "expected_totals": {
                    "input": totals[0],
                    "output": totals[1],
                    "excluded": totals[2],
                },
            },
        )

    def reject(
        case_id,
        purpose,
        source_name,
        operations,
        code,
        index,
        *,
        category,
        settings=None,
        details=None,
    ):
        arguments = {
            "data": datasets[source_name],
            "operations": operations,
            **(settings or {}),
        }
        items = [
            expectation("T-I.1", "/failure/code", code),
            expectation("T-I.1", "/observations/provider_calls", 0),
            expectation("T-O.1", "/output", None),
            expectation("T-O.2", "/run/status", "error"),
            expectation("T-O.2", "/failure/type", "ToolFailure"),
            expectation("T-O.2", "/failure/retryable", False),
            expectation(
                "T-O.1",
                "/failure/details/operation_index",
                index,
                match="absent" if index is None else "equal",
            ),
            {
                "check": "T-O.5",
                "path": "/output/data/sources",
                "applicable": False,
                "reason": "가공을 거부하여 결과 자료와 출처를 반환하지 않는 사례다.",
            },
        ]
        for name, value in (details or {}).items():
            items.append(expectation("T-O.2", "/failure/details/" + name, value))
        add(
            case_id,
            purpose,
            arguments,
            items,
            category,
            {
                "dataset": source_name,
                "failure_code": code,
                "operation_index": index,
                "failure_reason": purpose,
            },
        )

    # 계산값은 사전 계산한 상수다. 같은 수치에 대해 네 방식의 의미를 구분한다.
    answers = {
        "positive": {
            "ids": ["R1", "R2", "R3"],
            "difference": [25, 20, 0],
            "ratio": [1.25, 1.25, 1],
            "percentage": [125, 125, 100],
            "percent_change": [25, 25, 0],
        },
        "mixed": {
            "ids": ["N1", "N2", "N3"],
            "difference": [-20, -40, 10],
            "ratio": [0.75, 0, 0.5],
            "percentage": [75, 0, 50],
            "percent_change": [-25, -100, -50],
        },
    }
    formulas = {
        "difference": "after-before",
        "ratio": "after/before",
        "percentage": "after/before×100",
        "percent_change": "(after-before)/before×100",
    }
    units = {
        "difference": "index",
        "ratio": "ratio",
        "percentage": "%",
        "percent_change": "%",
    }
    for family, values in answers.items():
        name = "calc_" + family
        data = datasets[name]
        for method in formulas:
            normal(
                f"T02-calculate-{family}-{method}",
                f"{family} 수치 묶음의 {method} 계산값과 단위를 보존한다.",
                name,
                [calculate(method)],
                declared_rows(data, values["ids"], values[method]),
                data["columns"]
                + [
                    column(
                        data, "before", name="result", kind="number", unit=units[method]
                    )
                ],
                [("calculate", 3, 3, 0)],
                (3, 3, 0),
                category="calculation",
                derivation={
                    "formula": formulas[method],
                    "expected_values": values[method],
                },
            )

    grouped = datasets["aggregate_values"]
    group_answers = {
        "sum": [60, 45],
        "mean": [20, 15],
        "min": [10, 5],
        "max": [30, 25],
        "count": [3, 3],
    }
    for method, values in group_answers.items():
        result_column = column(grouped, "value", name="summary", kind="number")
        if method == "count":
            result_column.update(kind="integer", unit="rows", denominator="rows")
        normal(
            f"T02-aggregate-{method}",
            f"두 지역의 {method} 집계값을 반환하고 "
            "그룹으로 합친 행을 제외 건수에 넣지 않는다.",
            "aggregate_values",
            [aggregate(method)],
            [
                {"area": "시험동A", "summary": values[0]},
                {"area": "시험동B", "summary": values[1]},
            ],
            [column(grouped, "area"), result_column],
            [("aggregate", 6, 2, 0)],
            (6, 2, 0),
            category="aggregation",
            derivation={
                "groups": {"시험동A": [10, 20, 30], "시험동B": [5, 15, 25]},
                "expected": values,
            },
        )

    missing = datasets["calc_missing"]
    calculation_columns = missing["columns"] + [
        column(missing, "before", name="result", kind="number")
    ]
    reject(
        "T02-missing-calculate-error",
        "계산할 두 열 중 하나라도 결측이면 error 규칙에 따라 거부한다.",
        "calc_missing",
        [calculate()],
        "missing_value",
        0,
        category="missing",
        settings={"missing": "error"},
    )
    normal(
        "T02-missing-calculate-drop",
        "계산에 필요한 결측 두 행만 제외하고 정상 두 행을 계산한다.",
        "calc_missing",
        [calculate()],
        declared_rows(missing, ["M1", "M4"], [25, 0]),
        calculation_columns,
        [("calculate", 4, 2, 2)],
        (4, 2, 2),
        category="missing",
        settings={"missing": "drop"},
        derivation="M2는 after, M3는 before가 결측이다. M1=125-100=25, M4=50-50=0.",
    )
    normal(
        "T02-missing-calculate-preserve",
        "결측 결과를 null로 유지하고 내림차순 정렬에서도 결측 두 행을 마지막에 둔다.",
        "calc_missing",
        [calculate(), sort("result", True)],
        declared_rows(missing, ["M1", "M4", "M2", "M3"], [25, 0, None, None]),
        calculation_columns,
        [("calculate", 4, 4, 0), ("sort", 4, 4, 0)],
        (4, 4, 0),
        category="missing",
        settings={"missing": "preserve"},
        derivation="결측 행을 0으로 채우거나 제외하지 않는다. "
        "결과 순서는 25, 0, null, null이다.",
    )
    missing_group = datasets["aggregate_missing"]
    group_columns = [
        column(missing_group, "area"),
        column(missing_group, "value", name="summary", kind="number"),
    ]
    reject(
        "T02-missing-aggregate-error",
        "집계 대상 열에 결측이 있으면 합계를 만들어 반환하지 않는다.",
        "aggregate_missing",
        [aggregate()],
        "missing_value",
        0,
        category="missing",
        settings={"missing": "error"},
    )
    normal(
        "T02-missing-aggregate-drop",
        "결측 한 행만 제외한 뒤 지역별 합계를 내며 "
        "그룹 축소를 제외 건수로 세지 않는다.",
        "aggregate_missing",
        [aggregate()],
        [{"area": "시험동A", "summary": 40}, {"area": "시험동B", "summary": 45}],
        group_columns,
        [("aggregate", 6, 2, 1)],
        (6, 2, 1),
        category="missing",
        settings={"missing": "drop"},
        derivation="A=10+30=40, B=5+15+25=45. 결측 G2만 제외하여 제외 수는 1이다.",
    )
    normal(
        "T02-missing-aggregate-preserve",
        "결측이 포함된 그룹의 합계 전체를 null로 유지하고 정상 그룹과 구분한다.",
        "aggregate_missing",
        [aggregate(), sort("summary", True)],
        [{"area": "시험동B", "summary": 45}, {"area": "시험동A", "summary": None}],
        group_columns,
        [("aggregate", 6, 2, 0), ("sort", 2, 2, 0)],
        (6, 2, 0),
        category="missing",
        settings={"missing": "preserve"},
        derivation="A는 결측을 포함하므로 null, B는 45이며 제외 행은 0이다.",
    )

    zero = datasets["zero_values"]
    for method in ("ratio", "percentage", "percent_change"):
        reject(
            f"T02-zero-{method}",
            f"분모가 0인 {method} 계산을 거부하고 정상값으로 대체하지 않는다.",
            "zero_values",
            [calculate(method)],
            "zero_denominator",
            0,
            category="zero-denominator",
        )
    normal(
        "T02-zero-difference",
        "차이는 나눗셈이 아니므로 기준값 0도 정상 계산한다.",
        "zero_values",
        [calculate()],
        declared_rows(zero, ["Z1", "Z2", "Z3", "Z4"], [10, -5, 20, 0]),
        zero["columns"] + [column(zero, "before", name="result", kind="number")],
        [("calculate", 4, 4, 0)],
        (4, 4, 0),
        category="zero-denominator",
        derivation="10-0=10, 5-10=-5, 40-20=20, 0-0=0.",
    )
    for name, label in (
        ("unit", "측정 단위"),
        ("spatial", "공간 단위"),
        ("temporal", "시간 단위"),
        ("denominator", "분모 정의"),
    ):
        reject(
            f"T02-incompatible-{name}",
            f"비교할 두 열의 {label}가 다르면 계산을 거부한다.",
            "incompatible_" + name,
            [calculate()],
            "incompatible_units",
            0,
            category="incompatible",
        )

    def join(right_name="join_right", how="left", destination="joined_benchmark"):
        return {
            "operation": "join",
            "right": datasets[right_name],
            "keys": ["area", "month"],
            "how": how,
            "fields": {"benchmark": destination},
        }

    left, right = datasets["join_left"], datasets["join_right"]
    joined_columns = left["columns"] + [
        column(right, "benchmark", name="joined_benchmark")
    ]
    normal(
        "T02-join-inner",
        "동·월이 모두 맞는 두 행을 결합하고 미결합 한 행만 제외한 뒤 값을 정렬한다.",
        "join_left",
        [join(how="inner"), sort("joined_benchmark", True)],
        [
            {
                "area": "시험동C",
                "month": "2025-12",
                "value": 30,
                "joined_benchmark": 300,
            },
            {
                "area": "시험동A",
                "month": "2025-12",
                "value": 10,
                "joined_benchmark": 100,
            },
        ],
        joined_columns,
        [("join", 3, 2, 1), ("sort", 2, 2, 0)],
        (3, 2, 1),
        category="join",
        inputs=["join_left", "join_right"],
        derivation="왼쪽 A·C가 오른쪽과 일치한다. "
        "B만 제외하고 C(300), A(100) 순서로 반환한다.",
    )
    normal(
        "T02-join-left",
        "왼쪽 행을 모두 유지하고 미결합 값은 missing=error에서도 null로 반환한다.",
        "join_left",
        [join()],
        [
            {
                "area": "시험동A",
                "month": "2025-12",
                "value": 10,
                "joined_benchmark": 100,
            },
            {
                "area": "시험동B",
                "month": "2025-12",
                "value": 20,
                "joined_benchmark": None,
            },
            {
                "area": "시험동C",
                "month": "2025-12",
                "value": 30,
                "joined_benchmark": 300,
            },
        ],
        joined_columns,
        [("join", 3, 3, 0)],
        (3, 3, 0),
        category="join",
        settings={"missing": "error"},
        inputs=["join_left", "join_right"],
        derivation="A=100, B는 대응 없음(null), C=300. "
        "오른쪽에만 있는 D는 왼쪽 결합 결과에 추가하지 않는다.",
    )
    for suffix, source, right_name, code, reason in (
        (
            "duplicate-right",
            "join_left",
            "join_right_duplicate",
            "ambiguous_join",
            "오른쪽 결합 키가 중복되면 임의 행을 고르지 않는다.",
        ),
        (
            "missing-right-key",
            "join_left",
            "join_right_missing",
            "ambiguous_join",
            "오른쪽 결합 키 결측을 같은 값으로 묶지 않는다.",
        ),
        (
            "missing-left-key",
            "join_left_missing",
            "join_right",
            "missing_join_key",
            "왼쪽 결합 키가 결측이면 결합을 거부한다.",
        ),
        (
            "key-type",
            "join_left",
            "join_right_type",
            "join_key_mismatch",
            "결합 키 자료형이 다르면 문자열·숫자를 자동 변환하지 않는다.",
        ),
        (
            "as-of",
            "join_left",
            "join_right_time",
            "as_of_mismatch",
            "좌우 원본 기준 시점이 다르면 결합을 거부한다.",
        ),
    ):
        reject(
            "T02-join-" + suffix,
            reason,
            source,
            [join(right_name)],
            code,
            0,
            category="join",
        )
    reject(
        "T02-join-column-collision",
        "결합 결과 열이 기존 열과 충돌하면 덮어쓰지 않는다.",
        "join_left",
        [join(destination="value")],
        "duplicate_field",
        0,
        category="join",
    )

    ties = datasets["round_ties"]
    normal(
        "T02-round-zero",
        "모든 연산 뒤에 0자리 반올림하며 정확한 중간값은 짝수 쪽을 선택한다.",
        "round_ties",
        [calculate(output="delta"), aggregate(field="delta")],
        [
            {"area": "시험동A", "summary": 2},
            {"area": "시험동B", "summary": 4},
            {"area": "시험동C", "summary": 5},
            {"area": "시험동D", "summary": -2},
        ],
        [column(ties, "area"), column(ties, "before", name="summary", kind="number")],
        [("calculate", 5, 5, 0), ("aggregate", 5, 4, 0)],
        (5, 4, 0),
        category="rounding",
        settings={"decimals": 0},
        derivation="A:2.5→2, B:3.5→4, C:2.5+2.5=5→5(행별 반올림4 아님), D:-2.5→-2.",
    )
    precise = datasets["round_precise"]
    for decimals, values in (
        (2, [1.23, 2.35, -1.23]),
        (12, [1.234567891234, 2.345678912346, -1.234567891235]),
    ):
        rows = declared_rows(precise, ["P1", "P2", "P3"], values)
        for row, value in zip(rows, values, strict=True):
            row["after"] = value
        normal(
            f"T02-round-{decimals}",
            f"최종 모든 실수 열을 {decimals}자리로 반올림하고 원본 정수는 보존한다.",
            "round_precise",
            [calculate("ratio")],
            rows,
            precise["columns"]
            + [column(precise, "before", name="result", kind="number", unit="ratio")],
            [("calculate", 3, 3, 0)],
            (3, 3, 0),
            category="rounding",
            settings={"decimals": decimals},
            derivation={
                "ratio_denominator": 1,
                "expected_after_and_result": values,
                "tolerance": "exact",
            },
        )

    for name, kind, ids, values in (
        ("cast_number", "number", ["C1", "C2", "C3"], [12.5, 0, -3.25]),
        ("cast_integer", "integer", ["I1", "I2", "I3"], [9007199254740993, 42, -7]),
    ):
        data = datasets[name]
        normal(
            "T02-" + name.replace("_", "-"),
            f"문자열을 {kind}로 명시 변환하고 정밀도를 보존한다.",
            name,
            [{"operation": "cast", "field": "text_value", "kind": kind}],
            [
                {"record_id": key, "text_value": value}
                for key, value in zip(ids, values, strict=True)
            ],
            [column(data, "record_id"), column(data, "text_value", kind=kind)],
            [("cast", 3, 3, 0)],
            (3, 3, 0),
            category="cast",
            derivation={
                "expected_values": values,
                "large_integer": "9007199254740993을 9007199254740992로 줄이지 않음"
                if kind == "integer"
                else None,
            },
        )
    reject(
        "T02-cast-lossy-integer",
        "12.5를 정수로 잘라내지 않고 손실 변환을 거부한다.",
        "cast_number",
        [{"operation": "cast", "field": "text_value", "kind": "integer"}],
        "invalid_cast",
        0,
        category="cast",
    )
    reject(
        "T02-cast-invalid-text",
        "숫자가 아닌 문자열을 임의 값으로 바꾸지 않는다.",
        "cast_invalid",
        [{"operation": "cast", "field": "text_value", "kind": "number"}],
        "invalid_cast",
        0,
        category="cast",
    )

    empty_filter = {
        "operation": "filter",
        "conditions": [{"field": "value", "operator": "gt", "value": 1000}],
    }
    normal(
        "T02-fields-empty-aggregate",
        "필터 결과가 빈 경우 count 집계도 빈 결과이며 최종 열 선택 순서를 보존한다.",
        "aggregate_values",
        [empty_filter, aggregate("count", output="row_count")],
        [],
        [
            column(
                grouped,
                "value",
                name="row_count",
                kind="integer",
                unit="rows",
                denominator="rows",
            ),
            column(grouped, "area"),
        ],
        [("filter", 6, 0, 6), ("aggregate", 0, 0, 0)],
        (6, 0, 6),
        category="fields",
        settings={"fields": ["row_count", "area"]},
        derivation="원본 여섯 값은 모두 1000 이하이므로 제외6·출력0이다. "
        "count=0인 측정 행을 생성하지 않는다.",
    )
    reject(
        "T02-fields-missing-after-aggregate",
        "집계 후 남지 않은 원본 열을 최종 반환 열로 지정하면 거부한다.",
        "aggregate_values",
        [aggregate()],
        "invalid_field",
        None,
        category="fields",
        settings={"fields": ["record_id"]},
        details={"requested": ["record_id"], "available": ["area", "summary"]},
    )

    positive_filter = {
        "operation": "filter",
        "conditions": [{"field": "before", "operator": "gt", "value": 0}],
    }
    ratio = calculate("ratio")
    order = sort("after", True)
    normal(
        "T02-order-filter-first",
        "분모0 행을 먼저 제외한 뒤 비율을 계산하고 정렬하면 정상 두 행을 반환한다.",
        "zero_values",
        [positive_filter, ratio, order],
        declared_rows(zero, ["Z3", "Z2"], [2, 0.5]),
        zero["columns"]
        + [column(zero, "before", name="result", kind="number", unit="ratio")],
        [("filter", 4, 2, 2), ("calculate", 2, 2, 0), ("sort", 2, 2, 0)],
        (4, 2, 2),
        category="operation-order",
        derivation="Z1·Z4 제외 후 Z2=5/10=0.5,Z3=40/20=2. after 내림차순은 Z3,Z2.",
    )
    reject(
        "T02-order-filter-too-late",
        "같은 세 연산에서 필터를 계산 뒤로 옮기면 두 번째 단계의 분모0을 보고한다.",
        "zero_values",
        [order, ratio, positive_filter],
        "zero_denominator",
        1,
        category="operation-order",
    )
    reject(
        "T02-invalid-empty-operations",
        "빈 연산 목록은 도구 입력 단계에서 거부한다.",
        "calc_positive",
        [],
        "invalid_input",
        None,
        category="invalid-input",
    )
    reject(
        "T02-invalid-decimals",
        "반올림13자리는 지원 상한12로 자동 보정하지 않고 입력 단계에서 거부한다.",
        "calc_positive",
        [calculate()],
        "invalid_input",
        None,
        category="invalid-input",
        settings={"decimals": 13},
    )

    # 확장 사례의 정답도 수치·순서·건수를 미리 선언한다. 기존 48건은 유지한다.
    positive = datasets["calc_positive"]
    positive_columns = positive["columns"] + [
        column(positive, "before", name="result", kind="number")
    ]
    normal(
        "T02-calculate-reversed-difference",
        "기준 열과 비교 열을 뒤집으면 차이의 부호도 반대가 된다.",
        "calc_positive",
        [calculate() | {"before": "after", "after": "before"}],
        declared_rows(positive, ["R1", "R2", "R3"], [-25, -20, 0]),
        positive_columns,
        [("calculate", 3, 3, 0)],
        (3, 3, 0),
        category="calculation",
        derivation="100-125=-25, 80-100=-20, 50-50=0.",
    )
    normal(
        "T02-calculate-self-ratio",
        "같은 비영 열을 두 피연산자로 지정하면 비율은 모두 1이다.",
        "calc_positive",
        [calculate("ratio") | {"after": "before"}],
        declared_rows(positive, ["R1", "R2", "R3"], [1, 1, 1]),
        positive["columns"]
        + [column(positive, "before", name="result", kind="number", unit="ratio")],
        [("calculate", 3, 3, 0)],
        (3, 3, 0),
        category="calculation",
        derivation="100/100=80/80=50/50=1. 같은 열 이름을 오류로 중복 취급하지 않는다.",
    )

    for method, value in (
        ("sum", 105),
        ("mean", 17.5),
        ("min", 5),
        ("max", 30),
        ("count", 6),
    ):
        result_column = column(grouped, "value", name="summary", kind="number")
        if method == "count":
            result_column.update(kind="integer", unit="rows", denominator="rows")
        normal(
            f"T02-aggregate-global-{method}",
            f"그룹 열을 비우면 전체 여섯 행의 {method} 값을 한 행에 반환한다.",
            "aggregate_values",
            [aggregate(method) | {"group_by": []}],
            [{"summary": value}],
            [result_column],
            [("aggregate", 6, 1, 0)],
            (6, 1, 0),
            category="aggregation",
            derivation={"values": [10, 20, 30, 5, 15, 25], "expected": value},
        )

    for policy, ids, values, kind, excluded in (
        ("drop", ["M1", "M3", "M4"], [125, 60, 50], "integer", 1),
        ("preserve", ["M1", "M2", "M3", "M4"], ["125", None, "60", "50"], "string", 0),
    ):
        normal(
            "T02-missing-cast-" + policy,
            f"after 열만 {policy} 규칙으로 변환하며 다른 열의 결측은 그대로 둔다.",
            "calc_missing",
            [{"operation": "cast", "field": "after", "kind": kind}],
            declared_rows(missing, ids, values, output="after"),
            [
                column(
                    missing,
                    c["name"],
                    **({"kind": kind} if c["name"] == "after" else {}),
                )
                for c in missing["columns"]
            ],
            [("cast", 4, len(ids), excluded)],
            (4, len(ids), excluded),
            category="missing",
            settings={"missing": policy},
            derivation="after 결측은 M2뿐이다. "
            "M3의 before 결측은 해당 변환 대상이 아니다.",
        )
    for policy, values, excluded in (("preserve", [None, 3], 0), ("drop", [2, 3], 1)):
        normal(
            "T02-missing-count-" + policy,
            f"count 집계도 {policy} 결측 규칙을 적용하고 "
            "측정 행을 임의로 보충하지 않는다.",
            "aggregate_missing",
            [aggregate("count")],
            [
                {"area": "시험동A", "summary": values[0]},
                {"area": "시험동B", "summary": values[1]},
            ],
            [
                column(missing_group, "area"),
                column(
                    missing_group,
                    "value",
                    name="summary",
                    kind="integer",
                    unit="rows",
                    denominator="rows",
                ),
            ],
            [("aggregate", 6, 2, excluded)],
            (6, 2, excluded),
            category="missing",
            settings={"missing": policy},
            derivation={"A": [10, None, 30], "B": [5, 15, 25], "expected": values},
        )

    zero_both_filter = {
        "operation": "filter",
        "conditions": [{"field": "record_id", "operator": "eq", "value": "Z4"}],
    }
    for method, values in (
        ("ratio", [0.5, 2]),
        ("percentage", [50, 200]),
        ("percent_change", [-50, 100]),
    ):
        reject(
            f"T02-zero-both-{method}",
            f"분자와 분모가 모두 0이어도 {method} 결과를 0이나 1로 대체하지 않는다.",
            "zero_values",
            [zero_both_filter, calculate(method)],
            "zero_denominator",
            1,
            category="zero-denominator",
        )
        normal(
            f"T02-zero-excluded-{method}",
            f"0분모 행을 제외한 나머지 두 행에는 {method} 계산을 적용한다.",
            "zero_values",
            [positive_filter, calculate(method)],
            declared_rows(zero, ["Z2", "Z3"], values),
            zero["columns"]
            + [
                column(zero, "before", name="result", kind="number", unit=units[method])
            ],
            [("filter", 4, 2, 2), ("calculate", 2, 2, 0)],
            (4, 2, 2),
            category="zero-denominator",
            derivation={"pairs": [[10, 5], [20, 40]], "expected": values},
        )

    for name, method in (
        ("unit", "ratio"),
        ("spatial", "percentage"),
        ("temporal", "percent_change"),
        ("denominator", "ratio"),
    ):
        reject(
            f"T02-incompatible-after-sort-{name}",
            f"정렬을 먼저 수행해도 {name} 불일치는 다음 {method} 계산에서 거부한다.",
            "incompatible_" + name,
            [sort("before", True), calculate(method)],
            "incompatible_units",
            1,
            category="incompatible",
        )
    reject(
        "T02-incompatible-text-operands",
        "동 이름 문자열의 차이를 계산하지 않는다.",
        "calc_positive",
        [calculate() | {"before": "area", "after": "area"}],
        "non_numeric_field",
        0,
        category="incompatible",
    )
    reject(
        "T02-incompatible-cast-to-text",
        "숫자 열을 문자열로 변환한 뒤에는 자동 재변환 없이 계산을 거부한다.",
        "calc_positive",
        [{"operation": "cast", "field": "before", "kind": "string"}, calculate()],
        "non_numeric_field",
        1,
        category="incompatible",
    )

    normal(
        "T02-join-single-key",
        "단일 동 이름 키의 내부 결합에서 왼쪽 일치 행 순서를 보존한다.",
        "join_left",
        [join(how="inner") | {"keys": ["area"]}],
        [
            deepcopy(left["rows"][0]) | {"joined_benchmark": 100},
            deepcopy(left["rows"][2]) | {"joined_benchmark": 300},
        ],
        joined_columns,
        [("join", 3, 2, 1)],
        (3, 2, 1),
        category="join",
        inputs=["join_left", "join_right"],
        derivation="동 이름이 유일한 오른쪽 A·C가 일치한다. "
        "왼쪽 A,C 순서이며 B만 제외한다.",
    )
    normal(
        "T02-join-multiple-fields",
        "여러 오른쪽 열을 명시한 새 이름으로 결합하고 미일치 행에는 각각 null을 둔다.",
        "join_left",
        [join() | {"fields": {"benchmark": "benchmark_value", "month": "right_month"}}],
        [
            deepcopy(left["rows"][0])
            | {"benchmark_value": 100, "right_month": "2025-12"},
            deepcopy(left["rows"][1]) | {"benchmark_value": None, "right_month": None},
            deepcopy(left["rows"][2])
            | {"benchmark_value": 300, "right_month": "2025-12"},
        ],
        left["columns"]
        + [
            column(right, "benchmark", name="benchmark_value"),
            column(right, "month", name="right_month"),
        ],
        [("join", 3, 3, 0)],
        (3, 3, 0),
        category="join",
        inputs=["join_left", "join_right"],
        derivation="A,C에서 두 열을 가져오고 B의 새 두 열은 null이다. "
        "오른쪽 D는 추가하지 않는다.",
    )

    for decimals, values in (
        (1, [1.2, 2.3, -1.2]),
        (3, [1.235, 2.346, -1.235]),
        (4, [1.2346, 2.3457, -1.2346]),
        (6, [1.234568, 2.345679, -1.234568]),
        (8, [1.23456789, 2.34567891, -1.23456789]),
        (10, [1.2345678912, 2.3456789123, -1.2345678912]),
    ):
        rows = declared_rows(precise, ["P1", "P2", "P3"], values)
        for row, value in zip(rows, values, strict=True):
            row["after"] = value
        normal(
            f"T02-round-{decimals}",
            f"양·음수와 원본 실수 열에 최종 {decimals}자리 반올림을 적용한다.",
            "round_precise",
            [calculate("ratio")],
            rows,
            precise["columns"]
            + [column(precise, "before", name="result", kind="number", unit="ratio")],
            [("calculate", 3, 3, 0)],
            (3, 3, 0),
            category="rounding",
            settings={"decimals": decimals},
            derivation={"denominator": 1, "expected_after_and_result": values},
        )
    tie_rows = declared_rows(ties, ["T1", "T2", "T3", "T4", "T5"], [2, 4, 2, 2, -2])
    for row, value in zip(tie_rows, [2, 4, 2, 2, -2], strict=True):
        row["after"] = value
    normal(
        "T02-round-ties-without-aggregate",
        "집계하지 않은 2.5·3.5·-2.5는 각각 짝수 방향으로 최종 반올림한다.",
        "round_ties",
        [calculate()],
        tie_rows,
        ties["columns"] + [column(ties, "before", name="result", kind="number")],
        [("calculate", 5, 5, 0)],
        (5, 5, 0),
        category="rounding",
        settings={"decimals": 0},
        derivation="2.5→2, 3.5→4, -2.5→-2이며 C의 두 행은 따로 2가 된다.",
    )

    normal(
        "T02-cast-measurement-string",
        "수치 열을 문자열로 명시 변환하되 단위와 다른 열은 유지한다.",
        "calc_positive",
        [{"operation": "cast", "field": "before", "kind": "string"}],
        declared_rows(
            positive, ["R1", "R2", "R3"], ["100", "80", "50"], output="before"
        ),
        [
            column(
                positive,
                c["name"],
                **({"kind": "string"} if c["name"] == "before" else {}),
            )
            for c in positive["columns"]
        ],
        [("cast", 3, 3, 0)],
        (3, 3, 0),
        category="cast",
        derivation="100,80,50의 문자열은 '100','80','50'이다.",
    )
    normal(
        "T02-cast-whole-number-integer",
        "수치형 열의 정수 값은 손실 없이 정수형 열로 변환한다.",
        "calc_positive",
        [{"operation": "cast", "field": "after", "kind": "integer"}],
        positive["rows"],
        [
            column(
                positive,
                c["name"],
                **({"kind": "integer"} if c["name"] == "after" else {}),
            )
            for c in positive["columns"]
        ],
        [("cast", 3, 3, 0)],
        (3, 3, 0),
        category="cast",
        derivation="125,100,50은 소수 부분이 없는 정수다.",
    )
    reject(
        "T02-cast-fractional-number-integer",
        "문자열뿐 아니라 실수 2.5도 정수로 자르지 않는다.",
        "round_ties",
        [{"operation": "cast", "field": "after", "kind": "integer"}],
        "invalid_cast",
        0,
        category="cast",
    )
    reject(
        "T02-cast-invalid-text-integer",
        "숫자가 아닌 문자열의 정수 변환도 거부한다.",
        "cast_invalid",
        [{"operation": "cast", "field": "text_value", "kind": "integer"}],
        "invalid_cast",
        0,
        category="cast",
    )
    integer_data = datasets["cast_integer"]
    normal(
        "T02-cast-filtered-number",
        "선택한 두 문자열을 실수형 수치로 변환하며 소수점 표기와 음수 부호를 해석한다.",
        "cast_integer",
        [
            {
                "operation": "filter",
                "conditions": [{"field": "record_id", "operator": "ne", "value": "I1"}],
            },
            {"operation": "cast", "field": "text_value", "kind": "number"},
        ],
        [{"record_id": "I2", "text_value": 42}, {"record_id": "I3", "text_value": -7}],
        [
            column(integer_data, "record_id"),
            column(integer_data, "text_value", kind="number"),
        ],
        [("filter", 3, 2, 1), ("cast", 2, 2, 0)],
        (3, 2, 1),
        category="cast",
        derivation="I1 제외 후 '42.0'은 42, '-7'은 -7이다.",
    )
    normal(
        "T02-cast-number-string-number",
        "수치→문자열→수치의 명시 변환을 각각 기록하고 원래 값을 보존한다.",
        "calc_positive",
        [
            {"operation": "cast", "field": "before", "kind": "string"},
            {"operation": "cast", "field": "before", "kind": "number"},
        ],
        positive["rows"],
        positive["columns"],
        [("cast", 3, 3, 0), ("cast", 3, 3, 0)],
        (3, 3, 0),
        category="cast",
        derivation="100→'100'→100, 80→'80'→80, 50→'50'→50.",
    )

    for suffix, fields, rows, columns in (
        (
            "result-only",
            ["result"],
            [{"result": 25}, {"result": 20}, {"result": 0}],
            [positive_columns[-1]],
        ),
        (
            "result-area",
            ["result", "area"],
            [
                {"result": 25, "area": "시험동A"},
                {"result": 20, "area": "시험동B"},
                {"result": 0, "area": "시험동C"},
            ],
            [positive_columns[-1], column(positive, "area")],
        ),
    ):
        normal(
            "T02-fields-" + suffix,
            "계산으로 만든 열을 지정한 순서와 범위로만 반환한다: " + ",".join(fields),
            "calc_positive",
            [calculate()],
            rows,
            columns,
            [("calculate", 3, 3, 0)],
            (3, 3, 0),
            category="fields",
            settings={"fields": fields},
            derivation="차이25,20,0을 계산하고 명시한 열만 선택한다.",
        )
    normal(
        "T02-fields-aggregate-value-only",
        "집계 뒤 그룹 열을 출력에서 제외해도 그룹별 측정값 두 행을 유지한다.",
        "aggregate_values",
        [aggregate()],
        [{"summary": 60}, {"summary": 45}],
        [column(grouped, "value", name="summary", kind="number")],
        [("aggregate", 6, 2, 0)],
        (6, 2, 0),
        category="fields",
        settings={"fields": ["summary"]},
        derivation="A합60,B합45의 행 순서를 유지한다.",
    )
    normal(
        "T02-fields-cast-value-only",
        "큰 정수 변환 결과만 선택해도 9007199254740993의 정밀도를 보존한다.",
        "cast_integer",
        [{"operation": "cast", "field": "text_value", "kind": "integer"}],
        [{"text_value": 9007199254740993}, {"text_value": 42}, {"text_value": -7}],
        [column(integer_data, "text_value", kind="integer")],
        [("cast", 3, 3, 0)],
        (3, 3, 0),
        category="fields",
        settings={"fields": ["text_value"]},
        derivation="문자열 세 값을 정수9007199254740993,42,-7로 변환하고 "
        "ID열은 제외한다.",
    )
    for suffix, source_name, operations, fields in (
        ("duplicate", "calc_positive", [calculate()], ["area", "area"]),
        ("unknown-calculation", "calc_positive", [calculate()], ["unknown"]),
        ("unmapped-right", "join_left", [join()], ["benchmark"]),
        (
            "unknown-cast",
            "cast_integer",
            [{"operation": "cast", "field": "text_value", "kind": "integer"}],
            ["before"],
        ),
    ):
        reject(
            "T02-fields-" + suffix,
            "최종 반환 열의 중복 또는 없는 이름을 거부한다: " + ",".join(fields),
            source_name,
            operations,
            "invalid_field",
            None,
            category="fields",
            settings={"fields": fields},
        )

    result_filter = {
        "operation": "filter",
        "conditions": [{"field": "result", "operator": "gt", "value": 0}],
    }
    normal(
        "T02-order-derived-filter-sort",
        "생성된 차이를 필터와 정렬에서 사용하며 단계별 행 수를 기록한다.",
        "calc_positive",
        [calculate(), result_filter, sort("result")],
        declared_rows(positive, ["R2", "R1"], [20, 25]),
        positive_columns,
        [("calculate", 3, 3, 0), ("filter", 3, 2, 1), ("sort", 2, 2, 0)],
        (3, 2, 1),
        category="operation-order",
        derivation="차이25,20,0 중0을 제외하고20(R2),25(R1) 순서로 반환한다.",
    )
    normal(
        "T02-order-sort-before-aggregate",
        "입력을 먼저 정렬하면 집계 그룹은 정렬된 자료에서 처음 등장한 순서를 따른다.",
        "aggregate_values",
        [sort("value"), aggregate()],
        [{"area": "시험동B", "summary": 45}, {"area": "시험동A", "summary": 60}],
        [
            column(grouped, "area"),
            column(grouped, "value", name="summary", kind="number"),
        ],
        [("sort", 6, 6, 0), ("aggregate", 6, 2, 0)],
        (6, 2, 0),
        category="operation-order",
        derivation="최소5인 B가10인 A보다 먼저 등장한다. B합45,A합60.",
    )
    normal(
        "T02-order-cast-before-sort",
        "문자열을 정수로 바꾼 뒤 수치 오름차순으로 정렬한다.",
        "cast_integer",
        [
            {"operation": "cast", "field": "text_value", "kind": "integer"},
            sort("text_value"),
        ],
        [
            {"record_id": "I3", "text_value": -7},
            {"record_id": "I2", "text_value": 42},
            {"record_id": "I1", "text_value": 9007199254740993},
        ],
        [
            column(integer_data, "record_id"),
            column(integer_data, "text_value", kind="integer"),
        ],
        [("cast", 3, 3, 0), ("sort", 3, 3, 0)],
        (3, 3, 0),
        category="operation-order",
        derivation="-7<42<9007199254740993.",
    )
    bad_text = datasets["cast_invalid"]
    normal(
        "T02-order-filter-before-cast",
        "변환할 수 없는 문자열을 먼저 제외하면 남은 문자열만 정상 변환한다.",
        "cast_invalid",
        [
            {
                "operation": "filter",
                "conditions": [{"field": "record_id", "operator": "eq", "value": "B2"}],
            },
            {"operation": "cast", "field": "text_value", "kind": "number"},
        ],
        [{"record_id": "B2", "text_value": 12}],
        [column(bad_text, "record_id"), column(bad_text, "text_value", kind="number")],
        [("filter", 2, 1, 1), ("cast", 1, 1, 0)],
        (2, 1, 1),
        category="operation-order",
        derivation="B1을 제외하고 B2의 '12'만12로 변환한다.",
    )
    for suffix, source_name, operations, code, index in (
        (
            "aggregate-before-original-calculation",
            "calc_positive",
            [aggregate(field="before"), calculate()],
            "invalid_field",
            1,
        ),
        (
            "duplicate-calculation-output",
            "calc_positive",
            [calculate(), calculate("ratio")],
            "duplicate_field",
            1,
        ),
        (
            "join-fails-third",
            "join_left",
            [
                {"operation": "filter", "conditions": []},
                sort("area"),
                join("join_right_duplicate"),
            ],
            "ambiguous_join",
            2,
        ),
        (
            "cast-before-filter",
            "cast_invalid",
            [
                sort("record_id"),
                {"operation": "cast", "field": "text_value", "kind": "number"},
                {
                    "operation": "filter",
                    "conditions": [
                        {"field": "record_id", "operator": "eq", "value": "B2"}
                    ],
                },
            ],
            "invalid_cast",
            1,
        ),
    ):
        reject(
            "T02-order-" + suffix,
            f"{suffix} 순서에서 실패한 연산 위치 {index}와 {code}를 반환한다.",
            source_name,
            operations,
            code,
            index,
            category="operation-order",
        )

    for suffix, operations, settings in (
        ("negative-decimals", [calculate()], {"decimals": -1}),
        ("text-decimals", [calculate()], {"decimals": "2"}),
        ("unknown-missing-policy", [calculate()], {"missing": "zero"}),
        ("empty-fields", [calculate()], {"fields": []}),
        ("unknown-method", [calculate("multiply")], {}),
        ("empty-sort", [{"operation": "sort", "by": []}], {}),
        ("empty-join-keys", [join() | {"keys": []}], {}),
        ("unknown-operation", [{"operation": "execute", "code": "1+1"}], {}),
    ):
        reject(
            "T02-invalid-" + suffix,
            f"{suffix} 입력을 보정하거나 임의 연산으로 실행하지 않고 거부한다.",
            "calc_positive",
            operations,
            "invalid_input",
            None,
            category="invalid-input",
            settings=settings,
        )

    category_counts = Counter(case["tags"][1] for case in cases)
    if (
        len(cases) != 110
        or len(category_counts) != 11
        or set(category_counts.values()) != {10}
    ):
        raise ValueError(f"11개 평가 항목에 각각10건이어야 합니다: {category_counts}")
    fingerprints = [json.dumps(case["arguments"], sort_keys=True) for case in cases]
    if len(set(fingerprints)) != len(cases):
        raise ValueError("입력이 같은 사례가 중복되었습니다.")
    return {
        "schema_version": "evaluation-suite-v1",
        "id": "tools-process-v2",
        "datasets": deepcopy(datasets),
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="현재 JSON과 독립 재생성 결과 비교"
    )
    args = parser.parse_args()
    raw = SOURCE.read_bytes()
    suite = build_suite(json.loads(raw)["datasets"], sha256(raw).hexdigest())
    content = json.dumps(suite, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        if DESTINATION.read_text(encoding="utf-8") != content:
            raise SystemExit("저장된 가공 사례와 독립 재생성 결과가 다릅니다.")
        print("Process scenarios match the independently generated 110 cases.")
    else:
        DESTINATION.write_text(content, encoding="utf-8", newline="\n")
        print(f"Saved 110 process scenarios: {DESTINATION}")


if __name__ == "__main__":
    main()
