"""데이터 검색 및 조회(T01)의 조건·결과·입력 오류 사례 60건을 작성한다.

조회·정렬 구현이나 실행 결과를 재사용하지 않는다. 선택한 행의 ID와 순서,
건수·페이지 값·기대 오류를 사례마다 미리 정하고 원본에서 해당 행만 복사한다.
"""

import argparse
import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "query-data.json"
DESTINATION = ROOT / "query.json"
ALL_ACTIVITY = (
    "A01 A02 A03 A04 A05 A06 A07 A08 A09 A10 A11 A12 A13 A14 A15 A16 A17 A18 "
    "A19 A20 A21 A22 A23 A24 A25 A26 A27 A28 A29 A30 A31 A32 A33 A34 A35 A36"
).split()


def expectation(check, path, value=None, *, match="equal"):
    item = {"check": check, "path": path}
    if match != "equal":
        item["match"] = match
    if match not in {"present", "absent"}:
        item["value"] = deepcopy(value)
    return item


def condition(field, operator, value):
    return {"field": field, "operator": operator, "value": value}


def success_expectations(data, arguments, row_ids, *, total, next_offset):
    """입력 조건을 다시 실행하지 않고, 명시한 정답 ID의 원본 행을 투영한다."""
    fields = arguments.get("fields", [column["name"] for column in data["columns"]])
    index = {row["record_id"]: row for row in data["rows"]}
    columns = {column["name"]: column for column in data["columns"]}
    if len(index) != len(data["rows"]):
        raise ValueError("정답 원본의 행 식별자가 중복되었습니다.")
    rows = [{field: index[key][field] for field in fields} for key in row_ids]
    applied = {
        "target": data["reference"]["id"],
        "version": data["reference"]["version"],
        "as_of": data["as_of"],
        "fields": fields,
        "filters": arguments.get("filters", []),
        "sort": arguments.get("sort", []),
        "offset": arguments.get("offset", 0),
        "limit": arguments.get("limit", 100),
    }
    return [
        expectation("T-I.1", "/observations/provider_calls", 1),
        expectation("T-I.1", "/output/applied", applied),
        expectation("T-O.1", "/output/data/rows", rows),
        expectation(
            "T-O.1", "/output/data/columns", [columns[name] for name in fields]
        ),
        expectation("T-O.1", "/output/total", total),
        expectation("T-O.1", "/output/returned", len(row_ids)),
        expectation("T-O.1", "/output/next_offset", next_offset),
        expectation("T-O.2", "/run/status", "returned"),
        expectation("T-O.2", "/failure", None),
        expectation("T-O.5", "/output/data/as_of", data["as_of"]),
        expectation("T-O.5", "/output/data/sources", data["sources"]),
        expectation("T-O.5", "/output/data/inputs", [data["reference"]]),
        expectation("T-O.5", "/output/data/reference/id", match="present"),
        expectation("T-O.5", "/output/data/reference/version", match="present"),
    ]


def failure_expectations(code, provider_calls, *, requested=None, available=None):
    items = [
        expectation("T-I.1", "/observations/provider_calls", provider_calls),
        expectation("T-O.1", "/output", None),
        expectation("T-O.2", "/run/status", "error"),
        expectation("T-O.2", "/failure/type", "ToolFailure"),
        expectation("T-O.2", "/failure/code", code),
        expectation("T-O.2", "/failure/retryable", False),
    ]
    if requested is not None:
        items.extend(
            [
                expectation("T-O.2", "/failure/details/requested", requested),
                expectation("T-O.2", "/failure/details/available", available),
            ]
        )
    return items


def build_suite(datasets, source_hash):
    cases = []
    fields = [column["name"] for column in datasets["activity"]["columns"]]

    def add(case_id, purpose, arguments, items, *, rows=None, category):
        reference = {
            "source": "eval/scenarios/tools/query-data.json",
            "source_sha256": source_hash,
            "dataset": arguments["target"],
            "specification": "docs/agent/components.md#21-데이터-검색조회",
            "evaluation": "eval/docs/tools.md#11-데이터-검색-및-조회",
            "rule": purpose,
            "construction": "명시한 정답 행 목록·건수·오류로 작성. "
            "조회 도구를 호출하지 않음.",
        }
        if rows is not None:
            reference["expected_record_ids"] = rows
        cases.append(
            {
                "id": case_id,
                "unit": "tool",
                "target": "query_data",
                "purpose": purpose,
                "arguments": deepcopy(arguments),
                "assessment": {
                    "reference": reference,
                    "expected": {
                        "schema_version": "tool-expectations-v1",
                        "items": items,
                    },
                    "checks": ["T-I.1", "T-O.1", "T-O.2"]
                    + (["T-O.5"] if rows is not None else []),
                    "required": True,
                },
                "tags": ["T01", "normal" if rows is not None else "rejected", category],
            }
        )

    def normal(
        case_id, purpose, arguments, ids, total, next_offset=None, category="query"
    ):
        row_ids = ids.split() if isinstance(ids, str) else list(ids)
        add(
            case_id,
            purpose,
            arguments,
            success_expectations(
                datasets[arguments["target"]],
                arguments,
                row_ids,
                total=total,
                next_offset=next_offset,
            ),
            rows=row_ids,
            category=category,
        )

    def reject(
        case_id,
        purpose,
        arguments,
        code,
        calls,
        *,
        requested=None,
        category="invalid-input",
    ):
        add(
            case_id,
            purpose,
            arguments,
            failure_expectations(code, calls, requested=requested, available=fields),
            category=category,
        )

    normal(
        "T01-query-all",
        "조건을 생략하면 원본 36행과 적용한 기본 조건을 반환한다.",
        {"target": "activity"},
        ALL_ACTIVITY,
        36,
    )
    normal(
        "T01-filter-eq",
        "시험동B 조건과 일치하는 9행만 반환한다.",
        {"target": "activity", "filters": [condition("area", "eq", "시험동B")]},
        "A10 A11 A12 A13 A14 A15 A16 A17 A18",
        9,
    )
    normal(
        "T01-filter-ne",
        "65세 이상을 제외한 두 연령집단 24행을 반환한다.",
        {"target": "activity", "filters": [condition("age_group", "ne", "65+")]},
        "A01 A02 A04 A05 A07 A08 A10 A11 A13 A14 A16 A17 "
        "A19 A20 A22 A23 A25 A26 A28 A29 A31 A32 A34 A35",
        24,
    )
    normal(
        "T01-filter-contains",
        "문자열 포함 조건의 영문 대소문자를 구분하지 않는다.",
        {"target": "activity", "filters": [condition("record_id", "contains", "a0")]},
        "A01 A02 A03 A04 A05 A06 A07 A08 A09",
        9,
    )
    normal(
        "T01-filter-boolean",
        "논리값 true인 행을 숫자·문자열과 구분하여 조회한다.",
        {"target": "activity", "filters": [condition("quality_ok", "eq", True)]},
        "A01 A03 A04 A06 A07 A09 A10 A12 A13 A15 A16 A18 "
        "A19 A21 A22 A24 A25 A27 A28 A30 A31 A33 A34 A36",
        24,
    )
    normal(
        "T01-filter-null",
        "활동량이 결측인 두 행만 반환하며 실제 0은 포함하지 않는다.",
        {
            "target": "activity",
            "filters": [condition("activity_count", "is_null", True)],
        },
        "A05 A29",
        2,
    )
    normal(
        "T01-filter-not-null",
        "결측이 아닌 활동량 34행을 반환하고 0을 보존한다.",
        {
            "target": "activity",
            "filters": [condition("activity_count", "is_null", False)],
        },
        "A01 A02 A03 A04 A06 A07 A08 A09 A10 A11 A12 A13 A14 A15 A16 A17 A18 "
        "A19 A20 A21 A22 A23 A24 A25 A26 A27 A28 A30 A31 A32 A33 A34 A35 A36",
        34,
    )
    normal(
        "T01-filter-compound",
        "점수의 경계값 0·1은 포함하고 활동량의 경계값 100·200은 제외한다.",
        {
            "target": "activity",
            "filters": [
                condition("signal_score", "ge", 0),
                condition("signal_score", "le", 1),
                condition("activity_count", "gt", 100),
                condition("activity_count", "lt", 200),
            ],
        },
        "A11 A12 A13 A14 A15 A16 A17 A18 A19",
        9,
    )

    normal(
        "T01-sort-ascending",
        "오름차순에서 동률은 원본 순서, 결측은 마지막에 둔다.",
        {
            "target": "activity",
            "sort": [{"field": "activity_count", "descending": False}],
        },
        "A01 A02 A03 A04 A06 A07 A08 A09 A10 A11 A12 A13 A14 A15 A16 A17 A18 "
        "A19 A20 A21 A22 A23 A24 A25 A26 A27 A28 A30 A31 A32 A33 A34 A35 A36 A05 A29",
        36,
        category="sort-fields",
    )
    normal(
        "T01-sort-descending",
        "내림차순에서도 동률의 원본 순서와 결측 마지막을 보존한다.",
        {
            "target": "activity",
            "sort": [{"field": "activity_count", "descending": True}],
        },
        "A36 A35 A34 A33 A32 A31 A30 A28 A27 A26 A25 A24 A23 A22 A21 A20 A19 A18 "
        "A17 A16 A14 A15 A13 A12 A11 A10 A09 A08 A07 A06 A04 A02 A03 A01 A05 A29",
        36,
        category="sort-fields",
    )
    normal(
        "T01-sort-multiple",
        "동 이름 내림차순 뒤 점수 오름차순을 적용하고 각 동의 결측을 마지막에 둔다.",
        {
            "target": "activity",
            "sort": [
                {"field": "area", "descending": True},
                {"field": "signal_score", "descending": False},
            ],
        },
        "A31 A36 A32 A28 A33 A29 A34 A30 A35 A21 A26 A22 A27 A23 A19 A24 A20 A25 "
        "A11 A16 A12 A17 A13 A18 A14 A10 A15 A01 A02 A07 A03 A08 A04 A09 A05 A06",
        36,
        category="sort-fields",
    )
    normal(
        "T01-selected-fields",
        "조회 조건에 쓴 동 이름을 반환하지 않아도 필터를 적용하고 "
        "지정 열 순서를 보존한다.",
        {
            "target": "activity",
            "filters": [condition("area", "eq", "시험동A")],
            "fields": ["activity_count", "record_id"],
        },
        "A01 A02 A03 A04 A05 A06 A07 A08 A09",
        9,
        category="sort-fields",
    )

    normal(
        "T01-no-matching-records",
        "유효한 조건의 일치 행이 없으면 정상 0건과 출처를 반환한다.",
        {
            "target": "activity",
            "filters": [condition("area", "eq", "일치하지않는시험동")],
        },
        [],
        0,
        category="pagination",
    )
    normal(
        "T01-limit-minimum",
        "최소 허용 반환 수 1을 적용하고 다음 시작 위치를 알린다.",
        {"target": "activity", "limit": 1},
        "A01",
        36,
        1,
        "pagination",
    )
    normal(
        "T01-default-page",
        "101행에서 기본 최대 100행만 반환하고 다음 시작 위치 100을 알린다.",
        {"target": "activity_pages"},
        [f"P{number:03}" for number in range(1, 101)],
        101,
        100,
        "pagination",
    )
    normal(
        "T01-first-page",
        "버전을 명시한 첫 페이지는 10행과 다음 시작 위치 10을 반환한다.",
        {
            "target": "activity_pages",
            "version": "activity_pages-v1",
            "offset": 0,
            "limit": 10,
        },
        "P001 P002 P003 P004 P005 P006 P007 P008 P009 P010",
        101,
        10,
        "pagination",
    )
    normal(
        "T01-last-page",
        "마지막 페이지에서 남은 1행과 다음 페이지 없음 정보를 반환한다.",
        {
            "target": "activity_pages",
            "version": "activity_pages-v1",
            "offset": 100,
            "limit": 10,
        },
        "P101",
        101,
        None,
        "pagination",
    )
    normal(
        "T01-offset-beyond-end",
        "시작 위치가 전체 행 수를 넘으면 전체 건수를 보존한 정상 0건을 반환한다.",
        {
            "target": "activity_pages",
            "version": "activity_pages-v1",
            "offset": 150,
            "limit": 10,
        },
        [],
        101,
        None,
        "pagination",
    )

    normal(
        "T01-version-time-match",
        "자료 버전·기준 시점이 일치하고 최대 허용 한도 10000이면 원본을 반환한다.",
        {
            "target": "activity",
            "version": "activity-v1",
            "as_of": "2025-12-31",
            "limit": 10000,
        },
        ALL_ACTIVITY,
        36,
        category="version-time",
    )
    reject(
        "T01-version-mismatch",
        "요청 버전과 실제 원본 버전이 다르면 조회 자료를 반환하지 않는다.",
        {"target": "activity", "version": "activity-v0"},
        "version_mismatch",
        1,
        category="version-time",
    )
    reject(
        "T01-as-of-mismatch",
        "요청 기준 시점과 실제 원본 시점이 다르면 조회 자료를 반환하지 않는다.",
        {"target": "activity", "as_of": "2025-11-30"},
        "as_of_mismatch",
        1,
        category="version-time",
    )
    reject(
        "T01-page-version-missing",
        "다음 페이지 요청에 버전이 없으면 자료원을 읽기 전에 거부한다.",
        {"target": "activity", "offset": 1},
        "version_required",
        0,
        category="version-time",
    )

    reject(
        "T01-unregistered-source",
        "등록되지 않은 자료를 임의로 조회하거나 SQL로 해석하지 않는다.",
        {"target": "unregistered"},
        "reference_not_found",
        0,
    )
    reject(
        "T01-unknown-filter-field",
        "없는 열을 조회 조건으로 쓰면 해당 열과 허용 열을 알린다.",
        {"target": "activity", "filters": [condition("missing_column", "eq", "x")]},
        "invalid_field",
        1,
        requested=["missing_column"],
    )
    reject(
        "T01-unknown-return-field",
        "없는 반환 열을 임의로 만들지 않는다.",
        {"target": "activity", "fields": ["missing_column"]},
        "invalid_field",
        1,
        requested=["missing_column"],
    )
    reject(
        "T01-unknown-sort-field",
        "없는 정렬 열을 임의로 대체하지 않는다.",
        {
            "target": "activity",
            "sort": [{"field": "missing_column", "descending": False}],
        },
        "invalid_field",
        1,
        requested=["missing_column"],
    )
    reject(
        "T01-unknown-operator",
        "허용하지 않는 조회 연산자를 자료 읽기 전에 거부한다.",
        {"target": "activity", "filters": [condition("area", "in", "시험동A")]},
        "invalid_input",
        0,
    )
    reject(
        "T01-condition-type",
        "정수 열의 숫자 모양 문자열을 정수로 자동 변환하지 않는다.",
        {"target": "activity", "filters": [condition("activity_count", "eq", "100")]},
        "invalid_condition",
        1,
    )
    reject(
        "T01-limit-zero",
        "반환 한도 0을 기본값으로 보정하지 않고 거부한다.",
        {"target": "activity", "limit": 0},
        "invalid_input",
        0,
    )
    reject(
        "T01-limit-over-maximum",
        "반환 한도 10001을 10000으로 줄이지 않고 거부한다.",
        {"target": "activity", "limit": 10001},
        "invalid_input",
        0,
    )
    reject(
        "T01-negative-offset",
        "음수 시작 위치를 0으로 보정하지 않고 거부한다.",
        {"target": "activity", "offset": -1},
        "invalid_input",
        0,
    )
    reject(
        "T01-extra-sql",
        "임의 SQL 필드를 포함한 입력을 자료 읽기 전에 거부한다.",
        {"target": "activity", "sql": "SELECT * FROM activity"},
        "invalid_input",
        0,
    )
    reject(
        "T01-duplicate-fields",
        "반환 열 중복을 자동 제거하지 않고 거부한다.",
        {"target": "activity", "fields": ["record_id", "record_id"]},
        "invalid_field",
        1,
        requested=["record_id", "record_id"],
    )
    reject(
        "T01-duplicate-sort",
        "같은 정렬 열을 두 번 지정하면 거부한다.",
        {
            "target": "activity",
            "sort": [
                {"field": "record_id", "descending": False},
                {"field": "record_id", "descending": True},
            ],
        },
        "invalid_field",
        1,
        requested=["record_id", "record_id"],
    )
    reject(
        "T01-contains-on-number",
        "숫자 열에 문자열 포함 검색을 적용하지 않는다.",
        {
            "target": "activity",
            "filters": [condition("activity_count", "contains", "10")],
        },
        "invalid_condition",
        1,
    )
    reject(
        "T01-null-flag-string",
        "결측 검사 값은 논리값이어야 하며 문자열 true를 변환하지 않는다.",
        {
            "target": "activity",
            "filters": [condition("activity_count", "is_null", "true")],
        },
        "invalid_condition",
        1,
    )

    normal(
        "T01-filter-boolean-false",
        "논리값 false인 12행을 true와 구분하여 조회한다.",
        {"target": "activity", "filters": [condition("quality_ok", "eq", False)]},
        "A02 A05 A08 A11 A14 A17 A20 A23 A26 A29 A32 A35",
        12,
    )
    normal(
        "T01-filter-month-age",
        "11월 이후와 65세 이상 조건을 함께 적용해 두 달의 해당 집단만 반환한다.",
        {
            "target": "activity",
            "filters": [
                condition("month", "ge", "2025-11"),
                condition("age_group", "eq", "65+"),
            ],
        },
        "A06 A09 A15 A18 A24 A27 A33 A36",
        8,
    )

    normal(
        "T01-sort-score-descending",
        "한 지역의 소수 점수를 내림차순으로 정렬해 동률 순서와 결측 마지막을 보존한다.",
        {
            "target": "activity",
            "filters": [condition("area", "eq", "시험동A")],
            "sort": [{"field": "signal_score", "descending": True}],
        },
        "A05 A04 A09 A03 A08 A02 A07 A01 A06",
        9,
        category="sort-fields",
    )
    normal(
        "T01-sort-boolean-ascending",
        "논리값 정렬에서 false를 먼저 놓고 같은 값 안에서는 원본 순서를 유지한다.",
        {
            "target": "activity",
            "filters": [condition("area", "eq", "시험동B")],
            "sort": [{"field": "quality_ok", "descending": False}],
        },
        "A11 A14 A17 A10 A12 A13 A15 A16 A18",
        9,
        category="sort-fields",
    )
    normal(
        "T01-sort-multiple-opposite",
        "10월 자료를 지역 오름차순·활동량 내림차순으로 정렬하고 "
        "지역별 결측을 뒤에 둔다.",
        {
            "target": "activity",
            "filters": [condition("month", "eq", "2025-10")],
            "sort": [
                {"field": "area", "descending": False},
                {"field": "activity_count", "descending": True},
            ],
        },
        "A02 A03 A01 A12 A11 A10 A21 A20 A19 A30 A28 A29",
        12,
        category="sort-fields",
    )
    normal(
        "T01-sort-hidden-column",
        "반환하지 않는 활동량 열로 정렬한 뒤 행 식별자만 반환한다.",
        {
            "target": "activity",
            "filters": [condition("area", "eq", "시험동A")],
            "sort": [{"field": "activity_count", "descending": True}],
            "fields": ["record_id"],
        },
        "A09 A08 A07 A06 A04 A02 A03 A01 A05",
        9,
        category="sort-fields",
    )
    normal(
        "T01-selected-score-only",
        "점수 한 열만 선택해 원본 순서와 결측값을 보존하고 "
        "식별자 열을 추가하지 않는다.",
        {"target": "comparison", "fields": ["signal_score"]},
        "C01 C02 C03",
        3,
        category="sort-fields",
    )
    normal(
        "T01-selected-all-reversed",
        "모든 열을 원본의 역순으로 지정하면 행 순서는 유지하고 반환 열 순서만 바뀐다.",
        {
            "target": "comparison",
            "fields": [
                "quality_ok",
                "signal_score",
                "activity_count",
                "age_group",
                "month",
                "area",
                "record_id",
            ],
        },
        "C01 C02 C03",
        3,
        category="sort-fields",
    )

    normal(
        "T01-offset-exact-end",
        "시작 위치가 전체 101행과 같으면 총건수를 보존한 정상 0건을 반환한다.",
        {
            "target": "activity_pages",
            "version": "activity_pages-v1",
            "offset": 101,
            "limit": 1,
        },
        [],
        101,
        category="pagination",
    )
    normal(
        "T01-middle-page",
        "중간 페이지에서 51번째부터 10행을 반환하고 다음 시작 위치 60을 알린다.",
        {
            "target": "activity_pages",
            "version": "activity_pages-v1",
            "offset": 50,
            "limit": 10,
        },
        "P051 P052 P053 P054 P055 P056 P057 P058 P059 P060",
        101,
        60,
        "pagination",
    )
    normal(
        "T01-page-filter-before-offset",
        "지역 필터와 내림차순 정렬을 적용한 9행에서 시작 위치와 한도를 적용한다.",
        {
            "target": "activity",
            "version": "activity-v1",
            "filters": [condition("area", "eq", "시험동C")],
            "sort": [{"field": "activity_count", "descending": True}],
            "offset": 2,
            "limit": 3,
        },
        "A25 A24 A23",
        9,
        5,
        "pagination",
    )
    normal(
        "T01-page-null-tail",
        "활동량 정렬의 마지막 페이지에 있는 결측 두 행을 원본 순서대로 반환한다.",
        {
            "target": "activity",
            "version": "activity-v1",
            "sort": [{"field": "activity_count", "descending": False}],
            "offset": 34,
            "limit": 2,
        },
        "A05 A29",
        36,
        category="pagination",
    )

    normal(
        "T01-version-only",
        "시점 없이 일치하는 비교 자료 버전만 지정해도 실제 시점과 세 행을 반환한다.",
        {"target": "comparison", "version": "comparison-v1"},
        "C01 C02 C03",
        3,
        category="version-time",
    )
    normal(
        "T01-as-of-only",
        "버전 없이 일치하는 시점과 결측 조건을 지정하면 "
        "실제 버전과 일치 행을 반환한다.",
        {
            "target": "comparison",
            "as_of": "2025-12-31",
            "filters": [condition("activity_count", "is_null", True)],
        },
        "C03",
        1,
        category="version-time",
    )
    normal(
        "T01-page-version-time-match",
        "다음 페이지도 버전과 기준 시점이 모두 일치하면 마지막 한 행을 반환한다.",
        {
            "target": "activity_pages",
            "version": "activity_pages-v1",
            "as_of": "2025-12-31",
            "offset": 100,
            "limit": 1,
        },
        "P101",
        101,
        category="version-time",
    )
    reject(
        "T01-version-mismatch-page",
        "다음 페이지의 요청 버전이 실제 자료와 다르면 부분 자료도 반환하지 않는다.",
        {
            "target": "activity_pages",
            "version": "activity_pages-v0",
            "offset": 10,
            "limit": 10,
        },
        "version_mismatch",
        1,
        category="version-time",
    )
    reject(
        "T01-as-of-mismatch-with-version",
        "자료 버전이 일치해도 요청 기준 시점이 다르면 조회를 거부한다.",
        {
            "target": "comparison",
            "version": "comparison-v1",
            "as_of": "2025-10-31",
        },
        "as_of_mismatch",
        1,
        category="version-time",
    )
    reject(
        "T01-page-version-missing-filtered",
        "조건을 제한한 다음 페이지라도 버전이 없으면 자료원 호출 전에 거부한다.",
        {
            "target": "comparison",
            "filters": [condition("quality_ok", "eq", False)],
            "offset": 1,
            "limit": 1,
        },
        "version_required",
        0,
        category="version-time",
    )

    reject(
        "T01-empty-fields",
        "빈 반환 열 목록을 전체 열 선택으로 보정하지 않고 거부한다.",
        {"target": "activity", "fields": []},
        "invalid_input",
        0,
    )
    reject(
        "T01-sort-direction-string",
        "정렬 방향의 문자열 false를 논리값으로 변환하지 않고 거부한다.",
        {
            "target": "activity",
            "sort": [{"field": "activity_count", "descending": "false"}],
        },
        "invalid_input",
        0,
    )
    reject(
        "T01-fractional-offset",
        "소수 시작 위치를 정수로 잘라내지 않고 거부한다.",
        {"target": "activity", "offset": 0.5},
        "invalid_input",
        0,
    )
    reject(
        "T01-boolean-limit",
        "논리값 true를 반환 한도 1로 바꾸지 않고 거부한다.",
        {"target": "activity", "limit": True},
        "invalid_input",
        0,
    )
    reject(
        "T01-boolean-range-condition",
        "논리값 열에는 같음·다름 외의 범위 비교를 적용하지 않는다.",
        {"target": "activity", "filters": [condition("quality_ok", "lt", True)]},
        "invalid_condition",
        1,
    )
    reject(
        "T01-boolean-on-integer",
        "정수 열에 지정한 논리값 true를 숫자 1로 해석하지 않는다.",
        {"target": "activity", "filters": [condition("activity_count", "eq", True)]},
        "invalid_condition",
        1,
    )

    category_counts = Counter(case["tags"][-1] for case in cases)
    if category_counts != {
        "query": 10,
        "sort-fields": 10,
        "pagination": 10,
        "version-time": 10,
        "invalid-input": 20,
    }:
        raise ValueError("예정한 조회 사례의 항목별 수량과 구성이 다릅니다.")
    return {
        "schema_version": "evaluation-suite-v1",
        "id": "tools-query-v2",
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
    source = json.loads(raw)
    suite = build_suite(source["datasets"], sha256(raw).hexdigest())
    content = json.dumps(suite, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        if DESTINATION.read_text(encoding="utf-8") != content:
            raise SystemExit("저장된 조회 사례와 독립 재생성 결과가 다릅니다.")
        print("Query scenarios match the independently generated 60 cases.")
    else:
        DESTINATION.write_text(content, encoding="utf-8", newline="\n")
        print(f"Saved 60 query scenarios: {DESTINATION}")


if __name__ == "__main__":
    main()
