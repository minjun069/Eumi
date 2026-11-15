"""저장된 모델 원본·실제 입력·독립 기준으로 노드의 규칙 검사를 수행한다."""

import re
from copy import deepcopy
from math import isfinite

from eval.nodes.format import (
    detail,
    evaluate_format,
    prompt_sections,
    strict_json,
    visual_context,
)
from eval.nodes.schema import DetailResult, NodeExpectation
from eval.tools.assessment import _matches, _read

RULE_CHECKS = frozenset(
    {
        "N-F.1",
        "N-O.1",
        "N-O.8",
        "N-B.1",
        "N02-O.3",
        "N02-B.2",
        "N04-O.2",
    }
)
ROLE_CALLS = {
    "request": {
        "query_data",
        "process_data",
        "validate_visualization",
        "interpretation_agent",
        "visualization_agent",
    },
    "visualization": {"query_data", "process_data", "validate_visualization"},
    **{
        role: {"query_data", "process_data"}
        for role in (
            "interpretation",
            "report_selection",
            "report_description",
            "report_insight",
        )
    },
}


def _output(context):
    raw = context.get("call", {}).get("raw")
    value = strict_json(raw)
    if not isinstance(value, dict):
        raise ValueError("모델의 객체 반환값을 확보하지 못했습니다.")
    return value


def _output_at(output, path):
    # 원본 문자열 자체의 비교는 보존하고 하위 인자 경로만 JSON 객체로 해석한다.
    if path.startswith("/arguments_json/") and isinstance(
        output.get("arguments_json"), str
    ):
        arguments = strict_json(output["arguments_json"])
        return _read(arguments, path[len("/arguments_json") :])
    return _read(output, path)


def _number(text):
    if not isinstance(text, str):
        if type(text) not in {int, float}:
            raise ValueError("추출값이 수치가 아닙니다.")
        return text
    text = text.strip()
    if not re.fullmatch(
        r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
        text,
    ):
        raise ValueError("추출값이 수치 표기 형식이 아닙니다.")
    text = text.replace(",", "")
    value = int(text) if re.fullmatch(r"[+-]?\d+", text) else float(text)
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("추출 수치가 유한하지 않습니다.")
    return value


def _evidence(context, suffix=""):
    return (
        context.get("call", {}).get("path")
        or context.get("report_path")
        or "model-response"
    ) + suffix


def _input_evidence(item, context, output, reference):
    evidence, grounded = [], bool(reference)
    sources = {
        "messages": context.get("call", {}).get("messages"),
        "output": output,
        "reference": reference,
    }
    for selected in item.get("inputs", []):
        source, path = selected["source"], selected["path"]
        value = sources.get(source)
        exists, part = _read(value, path)
        if value is None or not exists:
            return (
                evidence,
                False,
                f"평가 입력 {source}#{path}의 원본을 확보하지 못했습니다.",
            )
        evidence.append(f"{source}#{path}")
        if source in {"messages", "reference"} and part is not None:
            grounded = True
    return evidence, grounded, None


def _compare(check_id, item, context, output, reference, tolerance):
    identity = item["id"]
    if item.get("applicable") is False:
        return detail(identity, "비적용", item.get("reason", "비적용 사유가 없습니다."))
    evidence, grounded, missing = _input_evidence(item, context, output, reference)
    if missing:
        return detail(identity, "미판정", missing, evidence)
    if not grounded:
        return detail(
            identity, "미판정", "독립 기준 자료 또는 대조할 실제 입력 근거가 없습니다."
        )
    if "path" not in item:
        return detail(
            identity, "미판정", "비교할 모델 반환값의 경로가 없습니다.", evidence
        )
    path = item["path"]
    try:
        exists, actual = _output_at(output, path)
    except (ValueError, TypeError):
        return detail(
            identity, "미판정", "비교할 호출 인자 JSON을 해석할 수 없습니다.", evidence
        )
    evidence.append(_evidence(context, f"#{path}"))
    if "pattern" in item and exists:
        if not isinstance(actual, str):
            return detail(
                identity,
                "실패",
                "정규식으로 추출할 출력이 문자열이 아닙니다.",
                evidence,
            )
        try:
            pattern = re.compile(item["pattern"])
        except re.error:
            return detail(
                identity,
                "미판정",
                "평가 기준의 추출 정규식이 유효하지 않습니다.",
                evidence,
            )
        if pattern.groups > 1:
            return detail(
                identity, "미판정", "추출 정규식의 캡처 그룹이 여러 개입니다.", evidence
            )
        values = [m[1] if pattern.groups else m[0] for m in pattern.finditer(actual)]
        exists = bool(values)
        actual = values[0] if len(values) == 1 else values
    if item.get("extract") == "number" and exists:
        try:
            actual = (
                [_number(value) for value in actual]
                if isinstance(actual, list)
                else _number(actual)
            )
        except ValueError as exc:
            return detail(identity, "실패", str(exc), evidence)
    mode = item.get("match", "equal")
    if mode in {"equal", "subset"} and "value" not in item:
        return detail(
            identity, "미판정", "독립 기대값이 지정되지 않았습니다.", evidence
        )
    if mode not in {"equal", "subset", "present", "absent"}:
        return detail(identity, "미판정", "지원하지 않는 비교 기준입니다.", evidence)
    if mode in {"present", "absent"}:
        passed = exists if mode == "present" else not exists
    elif check_id == "N04-O.2" and path == "/artifact_ids" and mode == "equal":
        expected = item["value"]
        passed = (
            exists
            and isinstance(actual, list)
            and isinstance(expected, list)
            and all(isinstance(value, str) for value in actual + expected)
            and set(actual) == set(expected)
        )
    else:
        passed = exists and _matches(
            actual,
            item["value"],
            item.get("tolerance", tolerance or {}),
            subset=mode == "subset",
        )
    values = {"actual": deepcopy(actual)} if exists else {}
    if "value" in item:
        values["expected"] = deepcopy(item["value"])
    return detail(
        identity,
        "통과" if passed else "실패",
        "실제 값이 독립 기대 조건과 일치합니다."
        if passed
        else "필수 비교 내용이 없거나 독립 기대 조건과 다릅니다.",
        evidence,
        **values,
    )


def _records(context):
    sections = prompt_sections(context)
    for key in ("작업 결과와 검증 이력", "작업·판단 이력"):
        if isinstance(sections.get(key), list):
            return sections[key], f"messages#[{key}]"
    report = sections.get("보고서 입력")
    if isinstance(report, dict) and isinstance(report.get("results"), list):
        return report["results"], "messages#/results"
    return None, None


def _flatten(records):
    for record in records or []:
        if isinstance(record, dict):
            yield record
            output = record.get("output")
            nested = output.get("results") if isinstance(output, dict) else None
            if isinstance(nested, list):
                yield from _flatten(nested)


def _valid_result(identity, records):
    """실행 성공과 명시된 부적합·취소·검토 기록을 독립적으로 확인한다."""
    rows = list(_flatten(records))
    matches = [row for row in rows if row.get("id") == identity]
    if not matches:
        return "실패", None, "실제 입력에 없는 작업 결과 ID입니다."
    if any(row != matches[0] for row in matches[1:]):
        return "미판정", None, "같은 결과 ID의 입력 기록이 서로 다릅니다."
    record = matches[0]
    output = record.get("output")
    outcome = record.get("outcome")
    if outcome in {"failure", "cancelled"}:
        return "실패", output, "실패·취소한 결과를 선택했습니다."
    if outcome != "success" or not isinstance(output, dict):
        return "미판정", output, "결과의 성공 상태와 반환 본문 근거가 부족합니다."
    if output.get("valid") is False or (output.get("execution") or {}).get(
        "status"
    ) in {
        "failed",
        "cancelled",
    }:
        return "실패", output, "부적합·실패·취소한 결과를 선택했습니다."
    reviews = [
        row.get("output") or {} for row in rows if row.get("decision") == "verification"
    ]
    if any(
        review.get("call_id") == identity and review.get("accepted") is False
        for review in reviews
    ):
        return "실패", output, "검토에서 거부된 결과를 선택했습니다."
    if record.get("decision") != "call" and not any(
        review.get("call_id") == identity and review.get("accepted") is True
        for review in reviews
    ):
        return "실패", output, "성공한 호출 또는 검토를 통과한 결과가 아닙니다."
    return "통과", output, "입력의 성공·검토 상태와 일치하는 유효 결과입니다."


def _arguments(output):
    value = strict_json(output.get("arguments_json"))
    if not isinstance(value, dict):
        raise ValueError("호출 인자가 객체가 아닙니다.")
    return value


def _result_refs(output):
    if output.get("name") == "process_data":
        args = _arguments(output)
        refs = [("input_result_id", args.get("input_result_id"))]
        refs.extend(
            (f"operations/{index}/right_result_id", operation.get("right_result_id"))
            for index, operation in enumerate(args.get("operations", []))
            if operation.get("operation") == "join"
        )
        return refs
    if "artifact_ids" in output:
        return [
            (f"artifact_ids/{index}", value)
            for index, value in enumerate(output["artifact_ids"])
        ]
    if "views" in output:
        return [
            (f"views/{index}/evidence_ids/{position}", value)
            for index, view in enumerate(output["views"])
            for position, value in enumerate(view.get("evidence_ids", []))
        ]
    return []


def _data_scope(context, output):
    sections = prompt_sections(context)
    if output.get("name") == "query_data":
        catalog = sections.get("조회 가능한 자료 목록")
        if not isinstance(catalog, dict):
            return [
                detail(
                    "registered-source",
                    "미판정",
                    "실제로 제공된 조회 자료 목록이 없습니다.",
                )
            ]
        target = _arguments(output).get("target")
        return [
            detail(
                "registered-source",
                "통과" if target in catalog else "실패",
                "선택한 조회 대상과 제공된 자료 목록을 대조했습니다.",
                ["messages#[조회 가능한 자료 목록]"],
                actual=target,
                expected=list(catalog),
            )
        ]
    refs = _result_refs(output)
    if not refs:
        return []
    records, source = _records(context)
    available = sections.get("가공 가능한 결과 ID와 열")
    if output.get("name") == "process_data" and isinstance(available, dict):
        known, source = set(available), "messages#[가공 가능한 결과 ID와 열]"
    elif records is not None:
        known = {record.get("id") for record in _flatten(records)}
    else:
        return [
            detail(
                "allowed-results", "미판정", "사용할 수 있는 작업 결과 목록이 없습니다."
            )
        ]
    results = []
    for path, identity in refs:
        if identity == "previous":
            previous = _previous(context)
            if previous is None:
                results.append(
                    detail(path, "미판정", "기존 공개 산출물의 입력 근거가 없습니다.")
                )
                continue
            allowed = bool(previous)
        else:
            allowed = identity in known
        results.append(
            detail(
                path,
                "통과" if allowed else "실패",
                "선택한 참조와 입력에 제공된 사용 범위를 대조했습니다.",
                [source],
                actual=identity,
            )
        )
    return results


def _call_scope(context, output, reference):
    name = output.get("name")
    allowed = ROLE_CALLS.get(context.get("role"))
    results = [
        detail(
            "role-scope", "미판정", "현재 역할의 호출 허용 범위를 확인할 수 없습니다."
        )
    ]
    if allowed is not None:
        results = [
            detail(
                "role-scope",
                "통과" if name in allowed else "실패",
                "현재 역할의 호출 허용 범위와 대조했습니다.",
                [_evidence(context)],
                actual=name,
                expected=sorted(allowed),
            )
        ]
    schema = context.get("call", {}).get("response_schema") or {}
    bound = (
        schema.get("properties", {}).get("name", {}).get("enum")
        if isinstance(schema, dict)
        else None
    )
    definitions = prompt_sections(context).get("도구 명세")
    if isinstance(definitions, list):
        bound = [
            item.get("function", {}).get("name")
            for item in definitions
            if isinstance(item, dict)
        ]
    if isinstance(bound, list):
        results.append(
            detail(
                "provided-calls",
                "통과" if name in bound else "실패",
                "실제 호출 입력에 제공된 작업 목록과 대조했습니다.",
                [_evidence(context)],
                actual=name,
                expected=bound,
            )
        )
    else:
        results.append(
            detail("provided-calls", "미판정", "실행 당시 제공된 호출 목록이 없습니다.")
        )
    if name == "validate_visualization":
        catalog, source = visual_context(context, reference)
        view = _arguments(output).get("view_key")
        results.append(
            detail("event-view", "미판정", "시작 이벤트에 제공된 뷰 목록이 없습니다.")
            if catalog is None
            else detail(
                "event-view",
                "통과" if view in catalog["views"] else "실패",
                "실행 당시 허용된 뷰 목록과 대조했습니다.",
                [source],
                actual=view,
            )
        )
    return results


def _column_names(columns):
    if not isinstance(columns, list):
        return None
    values = [
        column.get("name") if isinstance(column, dict) else column for column in columns
    ]
    return set(values) if all(isinstance(value, str) for value in values) else None


def _process_inputs(context, output):
    records, source = _records(context)
    args = _arguments(output)
    results, datasets = [], {}
    for path, identity in _result_refs(output):
        if records is None:
            results.append(
                detail(
                    path,
                    "미판정",
                    "참조 결과의 성공·검토 상태를 확인할 이력이 없습니다.",
                )
            )
            continue
        verdict, data, reason = _valid_result(identity, records)
        if verdict == "통과" and not isinstance(data.get("data"), dict):
            verdict, reason = "실패", "가공할 자료 본문을 가진 결과가 아닙니다."
        if verdict == "통과":
            datasets[identity] = _column_names(data["data"].get("columns"))
        results.append(detail(path, verdict, reason, [source], actual=identity))
    current = datasets.get(args.get("input_result_id"))
    for index, operation in enumerate(args.get("operations", [])):
        key = f"operation-columns/{index}"
        if current is None:
            results.append(
                detail(key, "미판정", "연산 입력의 열 정보를 확보하지 못했습니다.")
            )
            continue
        kind = operation.get("operation")
        required = []
        if kind == "calculate":
            required = [operation["before"], operation["after"]]
        elif kind == "aggregate":
            required = [operation["field"], *operation["group_by"]]
        elif kind == "join":
            required = operation["keys"]
        elif kind == "filter":
            required = [item["field"] for item in operation["conditions"]]
        elif kind == "cast":
            required = [operation["field"]]
        elif kind == "sort":
            required = [item["field"] for item in operation["by"]]
        unknown = set(required) - current
        results.append(
            detail(
                key,
                "실패" if unknown else "통과",
                "입력에 없는 열을 참조했습니다."
                if unknown
                else "연산에 필요한 입력 열이 있습니다.",
                [source],
                actual=required,
                expected=sorted(current),
            )
        )
        if unknown:
            current = None
            continue
        if kind == "calculate":
            current = current | {operation["output"]}
        elif kind == "aggregate":
            current = set(operation["group_by"]) | {operation["output"]}
        elif kind == "join":
            right = datasets.get(operation["right_result_id"])
            needed = set(operation["keys"]) | set(operation["fields"])
            results.append(
                detail(
                    f"join-columns/{index}",
                    "미판정"
                    if right is None
                    else "통과"
                    if needed <= right
                    else "실패",
                    "결합할 오른쪽 원본의 열과 대조합니다.",
                    [source],
                )
            )
            current = (
                current | set(operation["fields"].values())
                if right is not None and needed <= right
                else None
            )
    if "fields" in args:
        results.append(
            detail(
                "result-columns",
                "미판정"
                if current is None
                else "통과"
                if set(args["fields"]) <= current
                else "실패",
                "마지막 연산 후의 열과 반환 열을 대조합니다.",
                [source] if source else [],
            )
        )
    return results


def _visual_values(context, output, reference):
    args = _arguments(output)
    catalog, source = visual_context(context, reference)
    if catalog is None:
        return [
            detail(
                "visual-values", "미판정", "시각화 입력 조건의 당시 원본이 없습니다."
            )
        ]
    view = catalog["views"].get(args.get("view_key"), {})
    profile = catalog.get("input_profiles", {}).get(view.get("input_profile"))
    if not isinstance(profile, dict):
        return [
            detail(
                "visual-values",
                "미판정",
                "매개변수·필터 허용값 근거가 없습니다.",
                [source],
            )
        ]
    results = []
    parameters = args.get("parameters", {})
    for name, value in parameters.items():
        definition = profile.get("parameters", {}).get(name, {})
        allowed = definition.get("allowed")
        results.append(
            detail(
                f"parameter/{name}",
                "미판정"
                if not isinstance(allowed, list)
                else "통과"
                if value in allowed
                else "실패",
                "실행 당시 매개변수 허용값과 대조합니다.",
                [source],
                actual=value,
            )
        )
    for rule in profile.get("date_orders", []):
        start, end = parameters.get(rule.get("start")), parameters.get(rule.get("end"))
        if not isinstance(start, str) or not isinstance(end, str):
            results.append(
                detail(
                    "date-order",
                    "미판정",
                    "기간 선후 관계를 비교할 날짜가 없습니다.",
                    [source],
                )
            )
        else:
            results.append(
                detail(
                    "date-order",
                    "통과" if start <= end else "실패",
                    "등록된 시작·종료 날짜의 선후 관계를 대조합니다.",
                    [source],
                )
            )
    selected = catalog.get("selected", {}).get(args.get("view_key"), {})
    for name, values in args.get("filters", {}).items():
        definition = profile.get("filters", {}).get(name, {})
        allowed = definition.get("allowed")
        if "depends_on" in definition:
            parameter = definition["depends_on"]
            allowed = definition.get("allowed_by", {}).get(parameters.get(parameter))
            if allowed is None and selected.get("parameters", {}).get(
                parameter
            ) == parameters.get(parameter):
                allowed = selected.get("filters", {}).get(name, {}).get("allowed")
        results.append(
            detail(
                f"filter/{name}",
                "미판정"
                if not isinstance(allowed, list)
                else "통과"
                if all(value in allowed for value in values)
                else "실패",
                "선택한 매개변수에 해당하는 필터 허용값과 대조합니다.",
                [source],
                actual=values,
            )
        )
    return results or [
        detail(
            "visual-values",
            "미판정",
            "시각화 선택값을 대조할 근거가 없습니다.",
            [source],
        )
    ]


def _previous(context):
    sections = prompt_sections(context)
    if isinstance(sections.get("기존 공개 산출물"), list):
        return sections["기존 공개 산출물"]
    return None


def _artifacts(context, output):
    if not isinstance(output.get("artifact_ids"), list):
        return []
    records, source = _records(context)
    results = []
    for index, identity in enumerate(output["artifact_ids"]):
        key = f"artifact/{index}"
        if identity == "previous":
            previous = _previous(context)
            results.append(
                detail(
                    key,
                    "미판정" if previous is None else "통과" if previous else "실패",
                    "기존 공개 산출물의 입력 존재 여부를 대조합니다.",
                    ["messages#[기존 공개 산출물]"],
                )
            )
        elif records is None:
            results.append(
                detail(key, "미판정", "선택한 산출물의 작업 결과 이력이 없습니다.")
            )
        else:
            verdict, data, reason = _valid_result(identity, records)
            if verdict == "통과":
                has_artifact = (
                    isinstance(data.get("data"), dict)
                    or isinstance(data.get("artifact"), dict)
                    or bool((data.get("response") or {}).get("artifacts"))
                )
                if not has_artifact:
                    verdict, reason = "실패", "공개할 산출물·자료가 없는 결과입니다."
            results.append(detail(key, verdict, reason, [source], actual=identity))
    return results


def evaluate_rules(
    check_id: str,
    context: dict,
    expectations: list[NodeExpectation],
    *,
    reference=None,
    tolerance=None,
) -> list[DetailResult]:
    """노드 호출 하나의 담당 조건만 판정하며 업무 코드·모델은 실행하지 않는다."""
    if check_id not in RULE_CHECKS:
        raise ValueError(f"지원하지 않는 노드 규칙 검사: {check_id}")
    if check_id == "N-F.1":
        return evaluate_format(context, reference)
    try:
        output = _output(context)
    except (ValueError, TypeError):
        return [
            detail(
                "model-output",
                "미판정",
                "내용 비교에 필요한 모델 원본 JSON을 확보하지 못했습니다.",
            )
        ]
    results = [
        _compare(check_id, item, context, output, reference, tolerance)
        for item in expectations
    ]
    try:
        if check_id == "N-B.1":
            results.extend(_data_scope(context, output))
        elif check_id == "N02-B.2":
            results.extend(_call_scope(context, output, reference))
        elif check_id == "N02-O.3" and output.get("name") == "process_data":
            results.extend(_process_inputs(context, output))
        elif check_id == "N02-O.3" and output.get("name") == "validate_visualization":
            results.extend(_visual_values(context, output, reference))
        elif check_id == "N04-O.2":
            results.extend(_artifacts(context, output))
    except (AttributeError, KeyError, TypeError, ValueError):
        results.append(
            detail(
                "input-evidence",
                "미판정",
                "호출 인자 또는 입력 증거의 구조를 확인할 수 없습니다.",
            )
        )
    if not expectations and check_id in {"N-O.1", "N-O.8", "N02-O.3", "N04-O.2"}:
        results.append(
            detail(
                "independent-criteria",
                "미판정",
                "필수 내용·요청 조건·유지할 결과를 대조할 독립 기대 항목이 없습니다.",
            )
        )
    return results or [
        detail("criteria", "미판정", "검사할 대상과 대조할 사용 범위 기준이 없습니다.")
    ]
