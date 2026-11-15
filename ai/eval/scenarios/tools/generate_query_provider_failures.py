"""데이터 검색 및 조회(T01)의 권한·읽기 장애·설정 격리 40건을 작성한다.

실행기는 이 입력을 사례별 자료 공급 함수에 적용한다.
이 스크립트는 고정 자료와 기대값을 생성하며 도구·실행기·채점을 호출하지 않는다.
"""

import argparse
import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "query-data.json"
DESTINATION = ROOT / "query-provider-failures.json"
PROVIDERS = ["activity", "comparison"]
FAILURES = (
    ("PermissionError", "permission_denied", False, "권한 부족"),
    ("TimeoutError", "read_unavailable", True, "시간 초과"),
    ("ConnectionError", "read_unavailable", True, "연결 실패"),
)


def expectation(check, path, value=None, *, match="equal"):
    item = {"check": check, "path": path}
    if match != "equal":
        item["match"] = match
    if match not in {"present", "absent"}:
        item["value"] = deepcopy(value)
    return item


def trace_expectations(arguments, *, error_type=None, data=None):
    status = "error" if error_type else "success"
    provider = {
        "kind": "provider",
        "name": arguments["target"],
        "status": status,
        "input": {"query": deepcopy(arguments)},
    }
    if error_type:
        provider["error"] = {"type": error_type, "code": None, "http_status": None}
    else:
        provider["output"] = {"reference": deepcopy(data["reference"])}
    # 실행기에서는 evaluation span 뒤에 도구·자료원 span을 순서대로 만든다.
    # 배열 전체의 종류·이름도 대조하여 위치만 같은 다른 호출을 통과시키지 않는다.
    spans = [
        {"kind": "evaluation", "name": "query_data", "status": status},
        {"kind": "tool", "name": "query_data", "status": status},
        provider,
    ]
    items = [
        expectation("T-O.2", "/trace/spans", spans, match="subset"),
        expectation("T-O.2", "/observations/provider_calls", 1),
    ]
    if error_type:
        items.append(expectation("T-O.1", "/trace/spans/2/output", match="absent"))
    return items


def success_expectations(arguments, data, rows, *, total=None):
    fields = arguments.get("fields", [column["name"] for column in data["columns"]])
    columns = {column["name"]: column for column in data["columns"]}
    total = len(rows) if total is None else total
    offset, limit = arguments.get("offset", 0), arguments.get("limit", 100)
    applied = deepcopy(arguments) | {
        "version": data["reference"]["version"],
        "as_of": data["as_of"],
        "fields": fields,
        "filters": deepcopy(arguments.get("filters", [])),
        "sort": deepcopy(arguments.get("sort", [])),
        "offset": offset,
        "limit": limit,
    }
    return [
        expectation("T-I.1", "/output/applied", applied),
        expectation(
            "T-O.1", "/output/data/rows", [{f: row[f] for f in fields} for row in rows]
        ),
        expectation("T-O.1", "/output/data/columns", [columns[f] for f in fields]),
        expectation("T-O.1", "/output/total", total),
        expectation("T-O.1", "/output/returned", len(rows)),
        expectation(
            "T-O.1",
            "/output/next_offset",
            offset + limit if offset + limit < total else None,
        ),
        expectation("T-O.2", "/run/status", "returned"),
        expectation("T-O.2", "/failure", None),
        expectation("T-O.5", "/output/data/inputs", [data["reference"]]),
        expectation("T-O.5", "/output/data/sources", data["sources"]),
        expectation("T-O.5", "/output/data/as_of", data["as_of"]),
        *trace_expectations(arguments, data=data),
    ]


def failure_expectations(arguments, error_type, code, retryable):
    # 권한 거부는 입력·권한 검사의 결과, 읽기 장애 코드는 처리 상태의 결과다.
    code_check = "T-I.1" if error_type == "PermissionError" else "T-O.2"
    return [
        expectation(code_check, "/failure/code", code),
        expectation("T-O.1", "/output", None),
        expectation("T-O.2", "/run/status", "error"),
        expectation("T-O.2", "/failure/type", "ToolFailure"),
        expectation("T-O.2", "/failure/retryable", retryable),
        expectation(
            "T-O.2",
            "/failure/cause",
            {"type": error_type, "code": None, "http_status": None},
        ),
        *trace_expectations(arguments, error_type=error_type),
    ]


def build_suite(snapshot, snapshot_hash):
    datasets = deepcopy(snapshot["datasets"])
    if len(datasets["activity"]["rows"]) != 36:
        raise ValueError("activity 원본은 예정한 36행이어야 합니다.")
    if len(datasets["comparison"]["rows"]) != 3:
        raise ValueError("comparison 원본은 예정한 3행이어야 합니다.")
    cases = []

    def add(
        case_id,
        purpose,
        arguments,
        items,
        *,
        error_type=None,
        failure_target="activity",
        providers=PROVIDERS,
        tags=(),
    ):
        case = {
            "id": case_id,
            "unit": "tool",
            "target": "query_data",
            "purpose": purpose,
            "arguments": deepcopy(arguments),
            "providers": list(providers),
            "assessment": {
                "reference": {
                    "path": "eval/scenarios/tools/query-data.json",
                    "sha256": snapshot_hash,
                    "dataset": deepcopy(datasets[arguments["target"]]["reference"]),
                    "rules": "eval/docs/tools.md: T01 및 T-I.1, T-O.1·.2·.5",
                    "execution_condition": (
                        "실행기가 provider_failures를 "
                        "사례별 자료 공급 함수에 적용한다. "
                        "입력 조건과 적용 범위는 "
                        "eval/docs/runner.md의 자료원 장애를 따른다."
                    ),
                    "trace_condition": (
                        "현재 단위 실행기의 추적은 evaluation→tool→provider 순서다. "
                        "시간·실행 ID는 비교하지 않으며 "
                        "추적 계층 변경 시 기준을 재검토한다."
                    ),
                },
                "expected": {"schema_version": "tool-expectations-v1", "items": items},
                "checks": list(dict.fromkeys(item["check"] for item in items)),
                "required": True,
            },
            "tags": ["T01", "provider-failures", *tags],
        }
        if error_type:
            case["provider_failures"] = {failure_target: error_type}
        cases.append(case)

    absent_id = "NO-SUCH-RECORD"
    if any(row["record_id"] == absent_id for row in datasets["activity"]["rows"]):
        raise ValueError("정상 0건 사례의 비교값이 원본 자료에 존재합니다.")
    empty_arguments = {
        "target": "activity",
        "filters": [{"field": "record_id", "operator": "eq", "value": absent_id}],
    }
    add(
        "T01-provider-normal-zero",
        "등록된 activity를 정상 조회하되 일치 행이 없어 빈 자료와 정상 0건을 반환한다.",
        empty_arguments,
        success_expectations(empty_arguments, datasets["activity"], []),
        tags=("normal-zero",),
    )

    for error_type, code, retryable, label in FAILURES:
        activity_arguments = {"target": "activity"}
        comparison_arguments = {"target": "comparison"}
        add(
            f"T01-provider-{error_type}",
            f"등록된 activity 공급 함수에서 {label}을 발생시켜 "
            "정상 0건 대신 원인 예외와 재시도 가능 여부를 보존한다.",
            activity_arguments,
            failure_expectations(activity_arguments, error_type, code, retryable),
            error_type=error_type,
            tags=("failure", error_type),
        )
        add(
            f"T01-provider-{error_type}-other-target",
            f"activity에 {label}을 설정한 상태에서 comparison을 조회하면 "
            "comparison 공급 함수만 한 번 호출하고 원본 3행을 반환한다.",
            comparison_arguments,
            success_expectations(
                comparison_arguments,
                datasets["comparison"],
                datasets["comparison"]["rows"],
            ),
            error_type=error_type,
            tags=("isolation", error_type),
        )
        add(
            f"T01-provider-{error_type}-recovery",
            f"직전 사례의 activity {label} 설정을 다음 사례에서 생략하면 "
            "정상 공급 함수로 원본 36행을 반환한다.",
            activity_arguments,
            success_expectations(
                activity_arguments,
                datasets["activity"],
                datasets["activity"]["rows"],
            ),
            tags=("recovery", error_type),
        )

    def condition(field, operator, value):
        return {"field": field, "operator": operator, "value": value}

    # 조건별 빈 결과는 알려진 자료 범위 밖 값 또는 상호 배타적인 조건으로 구성한다.
    empty_variants = [
        ("negative-count", "activity", [condition("activity_count", "lt", 0)]),
        ("above-count", "activity", [condition("activity_count", "gt", 360)]),
        ("negative-score", "activity", [condition("signal_score", "lt", 0)]),
        ("above-score", "activity", [condition("signal_score", "gt", 1)]),
        ("before-month", "activity", [condition("month", "lt", "2025-10")]),
        ("comparison-id", "comparison", [condition("record_id", "eq", "MISSING")]),
        (
            "contradiction",
            "comparison",
            [condition("record_id", "eq", "C01"), condition("record_id", "eq", "C02")],
        ),
        ("page-quality", "activity_pages", [condition("quality_ok", "eq", False)]),
        ("above-page", "activity_pages", [condition("activity_count", "gt", 101)]),
    ]
    for name, target, filters in empty_variants:
        arguments = {"target": target, "filters": filters}
        add(
            f"T01-provider-normal-zero-{name}",
            f"{target}의 {name} 조건은 자료와 일치하지 않아 정상 0건을 반환한다.",
            arguments,
            success_expectations(arguments, datasets[target], []),
            providers=list(datasets),
            tags=("normal-zero",),
        )

    # 각 행은 장애 조회, 다른 자료원 조회, 장애 해제 후 동일 조회의 순서다.
    # 정답 ID·순서·전체 건수는 입력 조건으로부터 독립적으로 미리 지정한다.
    variants = [
        (
            "comparison-row",
            0,
            {"target": "comparison", "filters": [condition("record_id", "eq", "C01")]},
            ["C01"],
            1,
            {"target": "activity", "filters": [condition("record_id", "eq", "A01")]},
            ["A01"],
            1,
        ),
        (
            "comparison-page",
            1,
            {
                "target": "comparison",
                "limit": 2,
                "fields": ["record_id", "activity_count"],
            },
            ["C01", "C02"],
            3,
            {"target": "activity", "filters": [condition("record_id", "eq", "A02")]},
            ["A02"],
            1,
        ),
        (
            "comparison-null",
            2,
            {
                "target": "comparison",
                "filters": [condition("signal_score", "is_null", True)],
            },
            ["C03"],
            1,
            {"target": "activity", "filters": [condition("record_id", "eq", "A03")]},
            ["A03"],
            1,
        ),
        (
            "last-page",
            0,
            {
                "target": "activity_pages",
                "version": "activity_pages-v1",
                "offset": 100,
                "limit": 2,
            },
            ["P101"],
            101,
            {
                "target": "comparison",
                "sort": [{"field": "record_id", "descending": True}],
                "limit": 2,
            },
            ["C03", "C02"],
            3,
        ),
        (
            "page-range",
            1,
            {
                "target": "activity_pages",
                "filters": [condition("activity_count", "ge", 100)],
            },
            ["P100", "P101"],
            2,
            {"target": "activity", "limit": 2},
            ["A01", "A02"],
            36,
        ),
        (
            "reverse-page",
            2,
            {
                "target": "activity_pages",
                "sort": [{"field": "activity_count", "descending": True}],
                "limit": 3,
            },
            ["P101", "P100", "P099"],
            101,
            {"target": "comparison", "fields": ["record_id"], "limit": 1},
            ["C01"],
            3,
        ),
        (
            "selected-fields",
            0,
            {
                "target": "activity",
                "version": "activity-v1",
                "fields": ["record_id", "signal_score"],
                "filters": [condition("record_id", "eq", "A36")],
            },
            ["A36"],
            1,
            {
                "target": "activity_pages",
                "filters": [condition("activity_count", "eq", 101)],
            },
            ["P101"],
            1,
        ),
    ]

    def expected_rows(target, record_ids):
        indexed = {row["record_id"]: row for row in datasets[target]["rows"]}
        return [indexed[record_id] for record_id in record_ids]

    for (
        name,
        failure_index,
        arguments,
        row_ids,
        total,
        other,
        other_ids,
        other_total,
    ) in variants:
        error_type, code, retryable, label = FAILURES[failure_index]
        target = arguments["target"]
        add(
            f"T01-provider-{error_type}-{name}",
            f"{target}의 {name} 조회에서 {label}의 원인·재시도 여부를 보존한다.",
            arguments,
            failure_expectations(arguments, error_type, code, retryable),
            error_type=error_type,
            failure_target=target,
            providers=list(datasets),
            tags=("failure", error_type),
        )
        add(
            f"T01-provider-{error_type}-{name}-other-target",
            f"{target}에 {label}이 있어도 "
            f"{other['target']}의 {name} 조회는 정상 처리한다.",
            other,
            success_expectations(
                other,
                datasets[other["target"]],
                expected_rows(other["target"], other_ids),
                total=other_total,
            ),
            error_type=error_type,
            failure_target=target,
            providers=list(datasets),
            tags=("isolation", error_type),
        )
        add(
            f"T01-provider-{error_type}-{name}-recovery",
            f"앞 사례의 {target} {label} 설정을 제거하면 "
            f"{name} 조회 결과가 정상 복구된다.",
            arguments,
            success_expectations(
                arguments, datasets[target], expected_rows(target, row_ids), total=total
            ),
            providers=list(datasets),
            tags=("recovery", error_type),
        )

    categories = Counter(case["tags"][2] for case in cases)
    if categories != {
        "normal-zero": 10,
        "failure": 10,
        "isolation": 10,
        "recovery": 10,
    }:
        raise ValueError(f"항목별 10건 구성이 다릅니다: {categories}")
    if sum("provider_failures" in case for case in cases) != 20:
        raise ValueError("장애 설정이 필요한 20건 구성이 다릅니다.")
    return {
        "schema_version": "evaluation-suite-v1",
        "id": "tools-query-provider-failures-v2",
        "datasets": datasets,
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="저장 JSON과 재생성 결과의 일치만 검사"
    )
    args = parser.parse_args()
    raw = SNAPSHOT.read_bytes()
    suite = build_suite(json.loads(raw), sha256(raw).hexdigest())
    expected = json.dumps(suite, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        if DESTINATION.read_text(encoding="utf-8") != expected:
            raise SystemExit("저장된 장애 시나리오와 재생성 결과가 다릅니다.")
        print("장애 시나리오 40건 재생성 일치. 도구 실행·채점 결과 검증은 아님.")
    else:
        DESTINATION.write_text(expected, encoding="utf-8", newline="\n")
        print(f"장애 시나리오 40건 저장: {DESTINATION}")


if __name__ == "__main__":
    main()
