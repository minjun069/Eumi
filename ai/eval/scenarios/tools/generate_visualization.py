"""시각화 검증(T03)의 등록 설정 검사 사례 100건을 작성한다.

업무 모듈·검증 도구·실행 결과를 읽거나 호출하지 않는다. 산출물 ID는
독립 기대값을 만들지 않고 verify_visualization.py에서 관계를 검증한다.
"""

import argparse
import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "visualization-catalog.json"
DESTINATION = ROOT / "visualization.json"
REVISION = "tableau-public-20261110-v4"
CITY_VIEW = "Embed01RiskMap"
DETAIL_VIEW = "EmbedDetailV01"
COMMON_WARNINGS = [
    "등록 설정 검사 결과입니다. 실제 데이터 유무·최신성·"
    "브라우저 표시 성공은 확인하지 않았습니다.",
    "설정 등록 버전은 원자료 버전이 아닙니다.",
]
CATEGORIES = {
    "registered-view": (("registered-view",), 20),
    "event": (("event-allowed", "event-denied"), 20),
    "unknown-view": (("unknown-view",), 10),
    "filter-all": (("filter-all",), 10),
    "filter-order": (("filter-order",), 10),
    "input-format": (("input-format",), 10),
    "registration": (("registration",), 10),
    "missing": (("missing-parameter", "missing-all-parameters"), 10),
}


def expectation(check, path, value=None, *, match="equal"):
    item = {"check": check, "path": path}
    if match != "equal":
        item["match"] = match
    if match not in {"present", "absent"}:
        item["value"] = deepcopy(value)
    return item


def issue(code, path, requested, allowed=()):
    # 자연어 문구 대신 독립적으로 의미를 판정할 오류 코드·위치·조건을 고정한다.
    return {
        "code": code,
        "path": path,
        "requested": deepcopy(requested),
        "allowed": list(allowed),
        "retryable": False,
    }


def successful_fields(catalog, arguments):
    """등록 자료에서 기대 표시 내용을 구성한다. 입력 적합성을 판정하지 않는다."""
    key = arguments["view_key"]
    view = catalog["views"][key]
    definitions = catalog["input_profiles"][view["input_profile"]]["parameters"]
    source = "/".join((catalog["base_url"], view["workbook"], view["view_name"]))
    filters = []
    for field, sheets in view["filter_targets"].items():
        chosen = arguments.get("filters", {}).get(field)
        for sheet in sheets:
            filters.append(
                {
                    "worksheet": sheet,
                    "field": field,
                    "operation": "all" if chosen is None else "replace",
                    "values": [] if chosen is None else sorted(chosen),
                }
            )
    warnings = COMMON_WARNINGS + view["limitations"]
    if arguments.get("filters"):
        warnings = warnings + view["subset_warnings"]
    return {
        "schema_version": 1,
        "view_key": key,
        "src": source,
        "title": view["title"],
        "period_mode": view["period_mode"],
        "parameters": [
            {"name": name, "data_type": definitions[name]["data_type"], "value": value}
            for name, value in sorted(arguments["parameters"].items())
        ],
        "filters": filters,
        "source": {"label": "Tableau Public · " + view["title"], "uri": source},
        "validation_scope": "registered_configuration",
        "warnings": warnings,
    }


def build_suite(catalog, snapshot_hash):
    if catalog["revision"] != REVISION:
        raise ValueError("확정한 등록 버전과 기준 자료가 다릅니다.")
    if len(catalog["views"]) != 15:
        raise ValueError("이 묶음의 기준은 등록 뷰 15개입니다.")
    for profile in catalog["input_profiles"].values():
        if any("default" in parameter for parameter in profile["parameters"].values()):
            raise ValueError("매개변수 기본값이 없는 등록 자료가 필요합니다.")
    cases = []

    def add(
        case_id,
        purpose,
        arguments,
        *,
        event="user_request",
        issues=None,
        tags=(),
        equivalent_case=None,
    ):
        valid = issues is None
        items = [
            expectation("T-I.1", "/output/valid", valid),
            expectation(
                "T-O.1", "/output/validation_scope", "registered_configuration"
            ),
            expectation("T-O.2", "/run/status", "returned"),
            expectation("T-O.2", "/failure", None),
            expectation(
                "T-O.2",
                "/output/issues",
                [] if valid else issues,
                match="equal" if valid else "subset",
            ),
        ]
        if valid:
            fields = successful_fields(catalog, arguments)
            items.append(expectation("T-O.1", "/output/artifact/type", "tableau"))
            items.append(
                expectation(
                    "T-O.1", "/output/artifact/data/artifact_id", match="present"
                )
            )
            for name, value in fields.items():
                check = "T-O.5" if name == "source" else "T-O.1"
                items.append(expectation(check, "/output/artifact/data/" + name, value))
            items.extend(
                expectation("T-O.5", path, REVISION)
                for path in (
                    "/output/catalog_revision",
                    "/output/artifact/data/catalog_revision",
                )
            )
        else:
            items.append(expectation("T-O.1", "/output/artifact", None))
            for index in range(len(issues)):
                items.append(
                    expectation(
                        "T-O.2", f"/output/issues/{index}/message", match="present"
                    )
                )
        reference = {
            "catalog": "eval/scenarios/tools/visualization-catalog.json",
            "catalog_sha256": snapshot_hash,
            "catalog_revision": REVISION,
            "specification": "docs/agent/tableau.md",
            "evaluation": "eval/docs/tools.md#13-시각화-설정-검사",
            "rule": purpose,
            "construction": "등록 자료와 시험 조건으로 작성. "
            "도구 실행 결과를 사용하지 않음.",
        }
        if valid:
            reference["view"] = arguments["view_key"]
            reference["profile"] = catalog["views"][arguments["view_key"]][
                "input_profile"
            ]
        if equivalent_case is not None:
            reference["equivalent_case"] = equivalent_case
        cases.append(
            {
                "id": case_id,
                "unit": "tool",
                "target": "validate_visualization",
                "purpose": purpose,
                "initial": {
                    "request": {"goal": purpose},
                    "event": event,
                    "messages": [],
                },
                "arguments": deepcopy(arguments),
                "assessment": {
                    "reference": reference,
                    "expected": {
                        "schema_version": "tool-expectations-v1",
                        "items": items,
                    },
                    "checks": ["T-I.1", "T-O.1", "T-O.2"]
                    + (["T-O.5"] if valid else []),
                    "required": True,
                },
                "tags": ["T03", "valid" if valid else "invalid", *tags],
            }
        )

    city = {
        "view_key": CITY_VIEW,
        "parameters": {
            "p_city": "51110",
            "p_start": "2025-07-01",
            "p_end": "2025-12-01",
        },
        "filters": {"읍면동": ["후평3동", "후평1동"]},
    }
    detail = {
        "view_key": DETAIL_VIEW,
        "parameters": {
            "p_start": "2025-07-01",
            "p_end": "2025-12-01",
            "p_detail_adm": "춘천시 후평3동",
        },
    }
    normal_arguments = {}
    periods = [("07", "12"), ("07", "07"), ("12", "12"), ("08", "10"), ("09", "11")]
    for index, (key, view) in enumerate(catalog["views"].items()):
        arguments = deepcopy(
            city if view["input_profile"] == "monthly_city" else detail
        )
        arguments["view_key"] = key
        start, end = periods[index % len(periods)]
        arguments["parameters"].update(
            p_start=f"2025-{start}-01", p_end=f"2025-{end}-01"
        )
        if view["input_profile"] == "monthly_city" and index % 2:
            arguments["parameters"]["p_city"] = "11680"
            arguments["filters"] = {"읍면동": ["개포1동"]}
        if view["input_profile"] == "monthly_detail" and index % 2:
            arguments["parameters"]["p_detail_adm"] = "강남구 신사동"
        normal_arguments[key] = arguments
        add(
            f"T03-user-{key}",
            f"사용자 요청에서 {key}의 명시한 표시 조건과 출처·한계를 보존한다.",
            arguments,
            tags=("registered-view",),
        )

    analysis_views = catalog["event_views"]["analysis_pipeline"]
    for key in catalog["views"]:
        if key in analysis_views:
            add(
                f"T03-analysis-{key}",
                f"분석 완료 이벤트에서 허용된 {key}를 반환한다.",
                normal_arguments[key],
                event="analysis_pipeline",
                tags=("event-allowed",),
            )
        else:
            add(
                f"T03-analysis-reject-{key}",
                f"분석 완료 이벤트의 허용 목록 밖인 {key}를 거부한다.",
                normal_arguments[key],
                event="analysis_pipeline",
                issues=[
                    issue("view_not_allowed", "view_key", key, sorted(analysis_views))
                ],
                tags=("event-denied",),
            )
    for event in ("user_request", "analysis_pipeline"):
        arguments = deepcopy(city)
        arguments["view_key"] = "UnregisteredView"
        allowed = sorted(
            catalog["views"] if event == "user_request" else analysis_views
        )
        add(
            f"T03-unknown-view-{event}",
            f"{event}에서도 미등록 뷰를 거부한다.",
            arguments,
            event=event,
            issues=[issue("view_not_allowed", "view_key", "UnregisteredView", allowed)],
            tags=("unknown-view",),
        )

    arguments = deepcopy(city)
    del arguments["filters"]
    add(
        "T03-filter-omitted",
        "모든 매개변수를 명시하고 필터를 생략하면 "
        "등록 대상 시트에 전체 선택을 반환한다.",
        arguments,
        tags=("filter-all",),
    )
    arguments = deepcopy(normal_arguments[CITY_VIEW])
    arguments["filters"]["읍면동"].reverse()
    add(
        "T03-filter-order-reversed",
        "읍면동 순서만 뒤집어도 같은 표시 조건과 산출물 ID를 반환한다.",
        arguments,
        tags=("filter-order",),
    )

    for name, base in (("city", city), ("detail", detail)):
        profile = catalog["input_profiles"]["monthly_" + name]
        for parameter in profile["parameters"]:
            arguments = deepcopy(base)
            del arguments["parameters"][parameter]
            add(
                f"T03-missing-{name}-{parameter}",
                f"{name} 프로필의 {parameter} 하나를 생략하면 기본값 없이 거부한다.",
                arguments,
                issues=[
                    issue(
                        "missing_parameter",
                        f"parameters.{parameter}",
                        None,
                        profile["parameters"][parameter]["allowed"],
                    )
                ],
                tags=("missing-parameter",),
            )
        for form in ("omitted", "empty"):
            arguments = deepcopy(base)
            if form == "omitted":
                del arguments["parameters"]
            else:
                arguments["parameters"] = {}
            add(
                f"T03-parameters-{name}-{form}",
                f"{name} 프로필의 parameters {form} 입력에서 "
                "누락한 세 항목을 모두 반환한다.",
                arguments,
                issues=[
                    issue("missing_parameter", f"parameters.{p}", None, d["allowed"])
                    for p, d in profile["parameters"].items()
                ],
                tags=("missing-all-parameters",),
            )

    malformed = []
    arguments = deepcopy(city)
    del arguments["view_key"]
    malformed.append(("view-missing", arguments, "view_key", arguments))
    for suffix, field, value in (
        ("view-number", "view_key", 123),
        ("parameters-array", "parameters", []),
        ("filters-array", "filters", []),
        ("extra-field", "event", "analysis_pipeline"),
    ):
        arguments = deepcopy(city)
        arguments[field] = value
        malformed.append((suffix, arguments, field, value))
    arguments = deepcopy(city)
    arguments["parameters"]["p_city"] = 51110
    malformed.append(("parameter-number", arguments, "parameters.p_city", 51110))
    for suffix, value, path, rejected in (
        ("filter-scalar", "후평3동", "filters.읍면동", "후평3동"),
        ("filter-empty", [], "filters.읍면동", []),
        ("filter-number", [5111061100], "filters.읍면동.0", 5111061100),
    ):
        arguments = deepcopy(city)
        arguments["filters"]["읍면동"] = value
        malformed.append((suffix, arguments, path, rejected))
    for suffix, arguments, path, requested in malformed:
        add(
            f"T03-format-{suffix}",
            f"{path}의 입력 형식 위반을 자동 보정하지 않고 거부한다.",
            arguments,
            issues=[issue("invalid_input", path, requested)],
            tags=("input-format",),
        )

    city_profile = catalog["input_profiles"]["monthly_city"]
    detail_profile = catalog["input_profiles"]["monthly_detail"]
    arguments = deepcopy(city)
    arguments["parameters"]["p_unknown"] = "unknown"
    add(
        "T03-unknown-parameter",
        "등록되지 않은 매개변수 이름을 거부한다.",
        arguments,
        issues=[
            issue(
                "unknown_parameter",
                "parameters.p_unknown",
                "unknown",
                city_profile["parameters"],
            )
        ],
        tags=("registration",),
    )
    arguments = deepcopy(city)
    arguments["filters"]["행정동"] = ["후평3동"]
    add(
        "T03-unknown-filter",
        "등록되지 않은 필터 이름을 거부한다.",
        arguments,
        issues=[
            issue(
                "unsupported_filter",
                "filters.행정동",
                ["후평3동"],
                city_profile["filters"],
            )
        ],
        tags=("registration",),
    )
    for suffix, parameter, value in (
        ("city", "p_city", "99999"),
        ("month", "p_end", "2026-01-01"),
    ):
        arguments = deepcopy(city)
        arguments["parameters"][parameter] = value
        add(
            f"T03-invalid-{suffix}",
            f"{parameter}의 등록 허용값 밖 값을 거부한다.",
            arguments,
            issues=[
                issue(
                    "invalid_parameter_value",
                    f"parameters.{parameter}",
                    value,
                    city_profile["parameters"][parameter]["allowed"],
                )
            ],
            tags=("registration",),
        )
    arguments = deepcopy(detail)
    arguments["parameters"]["p_detail_adm"] = "5111061100"
    add(
        "T03-detail-code",
        "상세 동의 표시값 대신 행정동 코드를 보내면 거부한다.",
        arguments,
        issues=[
            issue(
                "invalid_parameter_value",
                "parameters.p_detail_adm",
                "5111061100",
                detail_profile["parameters"]["p_detail_adm"]["allowed"],
            )
        ],
        tags=("registration",),
    )
    arguments = deepcopy(city)
    arguments["parameters"].update(p_start="2025-12-01", p_end="2025-07-01")
    add(
        "T03-reversed-period",
        "허용된 두 월이라도 시작 월이 종료 월보다 늦으면 거부한다.",
        arguments,
        issues=[
            issue(
                "invalid_period",
                "parameters",
                {"p_start": "2025-12-01", "p_end": "2025-07-01"},
            )
        ],
        tags=("registration",),
    )
    arguments = deepcopy(city)
    arguments["parameters"]["p_city"] = "11680"
    arguments["filters"]["읍면동"] = ["후평3동"]
    add(
        "T03-city-filter-mismatch",
        "강남구 선택에 춘천시 읍면동을 섞으면 필터값을 자동 제외하지 않고 거부한다.",
        arguments,
        issues=[
            issue(
                "invalid_filter_value",
                "filters.읍면동",
                ["후평3동"],
                city_profile["filters"]["읍면동"]["allowed_by"]["11680"],
            )
        ],
        tags=("registration",),
    )
    arguments = deepcopy(city)
    arguments["filters"]["읍면동"] = ["후평3동", "후평3동"]
    add(
        "T03-duplicate-filter",
        "같은 읍면동을 중복 지정하면 자동 중복 제거 없이 거부한다.",
        arguments,
        issues=[
            issue("duplicate_filter_value", "filters.읍면동", ["후평3동", "후평3동"])
        ],
        tags=("registration",),
    )

    if len(cases) != 61:
        raise ValueError("확장 전의 61개 사례 구성이 다릅니다.")

    def city_request(key, city_code, start, end, regions=None, *, empty_filters=False):
        arguments = {
            "view_key": key,
            "parameters": {
                "p_city": city_code,
                "p_start": f"2025-{start}-01",
                "p_end": f"2025-{end}-01",
            },
        }
        if regions is not None:
            arguments["filters"] = {"읍면동": list(regions)}
        elif empty_filters:
            arguments["filters"] = {}
        return arguments

    paired_bases = [
        "T03-user-Embed01BehaviorMap",
        "T03-user-Embed03Vulnerability",
    ]
    # 기존 등록 뷰를 다른 도시·기간·지역 집합으로 요청한다.
    registered_variants = [
        (
            "gangnam-risk",
            CITY_VIEW,
            "11680",
            "08",
            "09",
            ["대치1동", "대치2동"],
        ),
        (
            "chuncheon-vulnerability",
            "Embed01VulnerabilityMap",
            "51110",
            "08",
            "08",
            ["후평1동", "후평2동", "후평3동"],
        ),
        (
            "gangnam-behavior",
            "Embed01BehaviorMap",
            "11680",
            "10",
            "12",
            ["논현1동", "논현2동", "청담동"],
        ),
        (
            "chuncheon-distribution",
            "Embed02RiskDistribution",
            "51110",
            "07",
            "09",
            ["동면", "동내면", "신북읍"],
        ),
        (
            "gangnam-change",
            "Embed05BehaviorChange",
            "11680",
            "11",
            "11",
            ["개포1동", "개포2동", "개포3동", "개포4동"],
        ),
    ]
    for suffix, key, city_code, start, end, regions in registered_variants:
        case_id = f"T03-registered-{suffix}"
        add(
            case_id,
            f"{key}에서 도시 {city_code}의 {start}~{end}월과 "
            f"지정한 {len(regions)}개 읍면동 조건을 보존한다.",
            city_request(key, city_code, start, end, regions),
            tags=("registered-view",),
        )
        paired_bases.append(case_id)

    # 똑같은 요청도 시작 이벤트에 따라 허용 여부만 달라져야 한다.
    for suffix, arguments in (
        (
            "gangnam-distribution",
            city_request(
                "Embed02RiskDistribution",
                "11680",
                "09",
                "11",
                ["역삼1동", "역삼2동", "삼성1동"],
            ),
        ),
        (
            "chuncheon-behavior",
            city_request(
                "Embed01BehaviorMap",
                "51110",
                "07",
                "07",
                ["석사동", "퇴계동", "후평3동"],
            ),
        ),
    ):
        case_id = f"T03-event-user-{suffix}"
        add(
            case_id,
            "사용자 요청에서는 해당 도시·기간·읍면동의 등록 뷰를 허용한다.",
            arguments,
            tags=("event-allowed",),
        )
        paired_bases.append(case_id)
        add(
            f"T03-event-analysis-{suffix}",
            "같은 표시 조건을 분석 완료 이벤트로 요청하면 비허용 뷰로 거부한다.",
            arguments,
            event="analysis_pipeline",
            issues=[
                issue(
                    "view_not_allowed",
                    "view_key",
                    arguments["view_key"],
                    sorted(analysis_views),
                )
            ],
            tags=("event-denied",),
        )
    add(
        "T03-event-analysis-rural-period",
        "분석 완료 이벤트에서 춘천시 동면의 10~12월 활동량 추이를 허용한다.",
        {
            "view_key": "EmbedDetailV07",
            "parameters": {
                "p_start": "2025-10-01",
                "p_end": "2025-12-01",
                "p_detail_adm": "춘천시 동면",
            },
        },
        event="analysis_pipeline",
        tags=("event-allowed",),
    )

    registered_url = "/".join(
        (catalog["base_url"], catalog["views"][CITY_VIEW]["workbook"], CITY_VIEW)
    )
    for suffix, key in (
        ("wrong-case", "embed01RiskMap"),
        ("published-url", registered_url),
        ("display-title", "종합 위험도 지도"),
        ("next-detail-number", "EmbedDetailV09"),
    ):
        for event in ("user_request", "analysis_pipeline"):
            arguments = deepcopy(city)
            arguments["view_key"] = key
            allowed = sorted(
                catalog["views"] if event == "user_request" else analysis_views
            )
            add(
                f"T03-unknown-view-{suffix}-{event}",
                f"{event}에서 등록 ID 대신 {suffix} 표현을 보내도 "
                "자동 변환하지 않는다.",
                arguments,
                event=event,
                issues=[issue("view_not_allowed", "view_key", key, allowed)],
                tags=("unknown-view",),
            )

    for suffix, key, city_code, start, end, empty in (
        ("risk-first-month", CITY_VIEW, "11680", "07", "07", False),
        ("risk-last-month", CITY_VIEW, "51110", "12", "12", True),
        (
            "vulnerability-period",
            "Embed01VulnerabilityMap",
            "11680",
            "08",
            "10",
            False,
        ),
        ("behavior-period", "Embed01BehaviorMap", "51110", "11", "12", True),
        (
            "distribution-period",
            "Embed02RiskDistribution",
            "11680",
            "09",
            "12",
            False,
        ),
        (
            "distribution-month",
            "Embed02RiskDistribution",
            "51110",
            "07",
            "07",
            True,
        ),
        ("vulnerability-month", "Embed03Vulnerability", "11680", "12", "12", False),
        ("change-month", "Embed05BehaviorChange", "51110", "10", "10", True),
        (
            "vulnerability-chuncheon",
            "Embed01VulnerabilityMap",
            "51110",
            "07",
            "11",
            False,
        ),
    ):
        add(
            f"T03-filter-all-{suffix}",
            f"{key}의 도시 {city_code}·{start}~{end}월에서 "
            f"{'빈 필터 객체' if empty else '필터 생략'}는 전체 선택을 뜻한다.",
            city_request(key, city_code, start, end, empty_filters=empty),
            tags=("filter-all",),
        )

    by_id = {case["id"]: case for case in cases}
    for index, base_id in enumerate(paired_bases):
        base = by_id[base_id]
        arguments = deepcopy(base["arguments"])
        regions = arguments["filters"]["읍면동"]
        arguments["filters"]["읍면동"] = (
            regions[1:] + regions[:1] if index % 2 else list(reversed(regions))
        )
        add(
            f"T03-filter-order-{base_id.removeprefix('T03-')}",
            f"{base_id}와 같은 지역 집합의 순서만 바꿔 산출물과 식별자를 보존한다.",
            arguments,
            event=base["initial"]["event"],
            tags=("filter-order",),
            equivalent_case=base_id,
        )

    arguments = deepcopy(city)
    arguments["parameters"]["p_end"] = None
    add(
        "T03-format-date-null",
        "종료 월에 null을 입력하면 문자열로 보정하거나 누락으로 해석하지 않는다.",
        arguments,
        issues=[issue("invalid_input", "parameters.p_end", None)],
        tags=("input-format",),
    )
    arguments = deepcopy(detail)
    arguments["parameters"]["p_city"] = "51110"
    add(
        "T03-registration-other-profile-parameter",
        "도시 프로필의 p_city를 상세 뷰에 추가하면 다른 프로필의 매개변수로 거부한다.",
        arguments,
        issues=[
            issue(
                "unknown_parameter",
                "parameters.p_city",
                "51110",
                detail_profile["parameters"],
            )
        ],
        tags=("registration",),
    )
    arguments = deepcopy(detail)
    arguments["filters"] = {"읍면동": ["후평3동"]}
    add(
        "T03-registration-other-profile-filter",
        "상세 뷰에서 도시 프로필의 읍면동 필터를 사용하면 "
        "등록되지 않은 필터로 거부한다.",
        arguments,
        issues=[issue("unsupported_filter", "filters.읍면동", ["후평3동"])],
        tags=("registration",),
    )

    counts = Counter()
    signatures = set()
    for case in cases:
        categories = [
            name
            for name, (tags, _) in CATEGORIES.items()
            if set(tags) & set(case["tags"])
        ]
        if len(categories) != 1:
            raise ValueError(
                f"사례는 정확히 한 평가 항목에 속해야 합니다: {case['id']}"
            )
        counts[categories[0]] += 1
        signature = json.dumps(
            [case["initial"]["event"], case["arguments"]],
            sort_keys=True,
            ensure_ascii=False,
        )
        if signature in signatures:
            raise ValueError(f"같은 이벤트·도구 입력이 중복되었습니다: {case['id']}")
        signatures.add(signature)
    if counts != {name: count for name, (_, count) in CATEGORIES.items()}:
        raise ValueError(f"평가 항목별 사례 수가 다릅니다: {dict(counts)}")
    if len(cases) != 100 or sum("valid" in case["tags"] for case in cases) != 51:
        raise ValueError("예정한 100건(적합 51, 부적합 49)과 사례 구성이 다릅니다.")
    return {
        "schema_version": "evaluation-suite-v1",
        "id": "tools-visualization-v2",
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="현재 JSON과 독립 재생성 결과의 일치만 검사",
    )
    args = parser.parse_args()
    raw = SNAPSHOT.read_bytes()
    suite = build_suite(json.loads(raw), sha256(raw).hexdigest())
    expected = json.dumps(suite, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        if DESTINATION.read_text(encoding="utf-8") != expected:
            raise SystemExit("저장된 시나리오와 독립 생성 결과가 다릅니다.")
        print("100개 시나리오와 독립 기준 재생성 결과 일치")
    else:
        DESTINATION.write_text(expected, encoding="utf-8", newline="\n")
        print(f"100개 시나리오 저장: {DESTINATION}")


if __name__ == "__main__":
    main()
