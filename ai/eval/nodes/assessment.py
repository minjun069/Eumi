"""노드의 단계별 판정을 조정한다. 규칙과 평가 모델은 별도 실행기로 호출한다."""

import asyncio
import json
import re
from copy import deepcopy
from hashlib import sha256

from eval.nodes.criteria import criterion_sections, load_criteria, select_rows
from eval.nodes.format import format_contract, strict_json
from eval.nodes.inputs import select_inputs
from eval.nodes.llm import JudgeCancelled, evaluate_llm
from eval.nodes.rules import evaluate_rules
from eval.nodes.schema import (
    NodeAssessment,
    NodeCheckResult,
    case_expectations,
    case_matches,
    node_expectations_adapter,
    requested_checks,
)
from eval.nodes.schema import (
    expectation_matches as _scope,
)
from eval.provenance import criterion_document_identity
from eval.tools.assessment import combine_verdicts

AXES = ("형식 준수", "필수 내용 충족", "내용 정확성")
# 구현된 규칙의 원문 범위가 달라지면 코드 검토 전까지 규칙을 통과시키지 않는다.
RULES_SHA256 = "55f960ec7a5123e2efb80439f1233d427311bf869ead2d10b7ef916d1e701e1e"


class AssessmentCancelled(asyncio.CancelledError):
    def __init__(self, assessment):
        super().__init__("노드 평가 취소")
        self.assessment = assessment


def rules_digest(catalog):
    parts = {}
    for definition in catalog["checks"].values():
        if definition["method"] != "규칙 기반":
            continue
        try:
            definition_text = json.loads(definition["text"])
        except json.JSONDecodeError:
            parts[definition["id"]] = definition["text"]
        else:
            for binding in definition_text["bindings"]:
                for reference in binding["principles"]:
                    reference["path"] = criterion_document_identity(reference["path"])
            parts[definition["id"]] = json.dumps(
                definition_text, ensure_ascii=False, indent=2
            )
        for row in definition["rows"]:
            for section in criterion_sections(row, catalog):
                source = section["source"]
                key = criterion_document_identity(source["path"]) + source["pointer"]
                parts[key] = section["text"]
    text = "\n".join(parts[key].replace("\r\n", "\n") for key in sorted(parts))
    return sha256(text.encode()).hexdigest()


def _detail(identifier, verdict, reason, *, executed=False, evidence=()):
    return {
        "id": identifier,
        "verdict": verdict,
        "reason": reason,
        "executed": executed,
        "evidence": list(evidence),
    }


def _criteria_value(assessment, key, check):
    value = assessment.get(key)
    return value.get(check) if isinstance(value, dict) else None


def _actual_trigger(check, call):
    """명백히 관측된 적용 조건은 사전 비적용 선언으로 면제하지 않는다."""
    output = call.get("output")
    if not isinstance(output, dict):
        return False
    name = output.get("name")
    if check in {"N02-B.2", "N02-O.3"}:
        return isinstance(name, str) and name != "none"
    if check == "N02-O.4":
        return name == "validate_visualization"
    if check == "N04-O.2":
        return bool(output.get("artifact_ids"))
    if check == "N04-O.3":
        return call.get("name") == "Verification"
    if check == "N-B.3":
        return bool(output.get("content"))
    if check == "N-B.1":
        return (
            bool(output.get("evidence_ids") or output.get("artifact_ids"))
            or name in {"query_data", "process_data"}
            or any(
                v.get("evidence_ids")
                for v in output.get("views", [])
                if isinstance(v, dict)
            )
        )
    if check == "N-O.1":
        written = [output.get("reason", ""), output.get("content", "")]
        written.extend(
            v.get("reason", "") for v in output.get("views", []) if isinstance(v, dict)
        )
        return any(
            isinstance(text, str) and re.search(r"(?<![A-Za-z_])\d", text)
            for text in written
        )
    return False


def _merged(details):
    """같은 기대 조건의 여러 작성·검토 호출 결과를 한 번만 집계한다."""
    groups = {}
    for detail in details:
        groups.setdefault(detail["id"], []).append(detail)
    result = []
    for identifier, values in groups.items():
        verdict = combine_verdicts([value["verdict"] for value in values])
        result.append(
            _detail(
                identifier,
                verdict,
                " / ".join(dict.fromkeys(v["reason"] for v in values)),
                executed=any(v.get("executed", False) for v in values),
                evidence=dict.fromkeys(
                    path for v in values for path in v.get("evidence", [])
                ),
            )
        )
    return result


def _finish(case, node, checks, *, cancelled=False) -> NodeAssessment:
    verdict = combine_verdicts([check["verdict"] for check in checks])
    unresolved = False
    for check in checks:
        call_details = [d for call in check["calls"] for d in call["details"]]
        recorded = {d["id"] for d in call_details}
        details = call_details + [
            d for d in check["details"] if d["id"] not in recorded
        ]
        unresolved |= any(
            d["verdict"] == "미판정"
            and not (
                d["reason"] == "선행 단계 실패로 미실행"
                and not d.get("executed", False)
            )
            for d in details
        )
        if not details and check["verdict"] == "미판정":
            unresolved |= check["reason"] != "선행 단계 실패로 미실행"
    complete = bool(checks) and not unresolved and not cancelled
    return {
        "node_id": node["id"],
        "run_id": node.get("run_id"),
        "case_id": case["id"],
        "repetition": node["repetition"],
        "node": node["node"],
        "role": node.get("role"),
        "counted": node["counted"],
        "verdict": verdict,
        "complete": complete,
        "checks": checks,
        "reason": "취소 전 완료한 판정과 미완료 항목을 보존했습니다."
        if cancelled
        else "적용 검사와 단계별 중단 사유를 함께 기록했습니다.",
    }


async def assess_node(
    case, node, *, catalog=None, model=None, method="all", row_ids=None
) -> NodeAssessment:
    if method not in {"rules", "all"}:
        raise ValueError("노드 평가는 rules 또는 all 방식으로 실행합니다")
    catalog = catalog or load_criteria()
    # 후처리된 값이나 오래된 파싱 결과가 원문을 대신하지 않게 한다.
    node = deepcopy(node)
    if not case_matches(case, node):
        return _finish(case, node, [])
    node["calls"] = [
        {**call, "index": call.get("index", index)}
        for index, call in enumerate(node.get("calls", []), 1)
        if case_matches(case, node, call, index)
    ]
    for call in node.get("calls", []):
        try:
            call["output"] = strict_json(call.get("raw"))
        except (ValueError, TypeError):
            call["output"] = None
    assessment = case.get("assessment", {})
    expected = assessment.get("expected")
    items = []
    if (
        isinstance(expected, dict)
        and expected.get("schema_version") == "node-expectations-v1"
    ):
        items = node_expectations_adapter.validate_python(expected)["items"]
        selected_ids = {
            item["id"] for item in case_expectations(case, [node], row_ids=row_ids)
        }
        items = [item for item in items if item["id"] in selected_ids]
    requested = requested_checks(case, [node], row_ids=row_ids)
    definitions = [
        d
        for d in catalog["checks"].values()
        if d["id"] in requested
        and node["node"] in d["nodes"]
        and (
            not any(item["check"] == d["id"] for item in items)
            or any(item["check"] == d["id"] and _scope(item, node) for item in items)
        )
    ]
    definitions.sort(key=lambda d: AXES.index(d["axis"]))
    checks: list[NodeCheckResult] = []
    blocked: dict[str, str] = {}
    compatible_rules = rules_digest(catalog) == RULES_SHA256
    for axis in AXES:
        stage: dict[str, list[str]] = {}
        for definition in (d for d in definitions if d["axis"] == axis):
            identifier = definition["id"]
            scoped = [
                item
                for item in items
                if item["check"] == identifier and _scope(item, node)
            ]
            result: NodeCheckResult = {
                "check": identifier,
                "axis": axis,
                "method": definition["method"],
                "executed": False,
                "verdict": "미판정",
                "reason": "",
                "details": [],
                "calls": [],
                "related_checks": [],
            }
            row_selections = [
                select_rows(definition, node, call, row_ids=row_ids)
                for call in node.get("calls", [])
            ]
            reason = None
            if reason is None and not node.get("calls"):
                reason = "평가할 모델 원문 호출 증거가 없습니다."
            if reason:
                result["reason"] = reason
                result["details"] = [
                    _detail(item["id"], "미판정", reason) for item in scoped
                ]
            else:
                details, seen_items = [], set()
                for position, call in enumerate(node["calls"], 1):
                    index = call.get("index", position)
                    selection = row_selections[position - 1]
                    selected = [
                        item for item in scoped if _scope(item, node, call, index)
                    ]
                    if not selection["missing_context"]:
                        matching_rows = {row["row_id"] for row in selection["rows"]}
                        excluded = [
                            item
                            for item in selected
                            if "row_id" in item and item["row_id"] not in matching_rows
                        ]
                        seen_items.update(item["id"] for item in excluded)
                        selected = [item for item in selected if item not in excluded]
                        if row_ids is not None and not matching_rows:
                            seen_items.update(item["id"] for item in selected)
                            continue
                    # 특정 호출만 지정한 검사를 다른 호출에 중복 적용하지 않는다.
                    if scoped and not selected:
                        continue
                    seen_items.update(item["id"] for item in selected)
                    if call["id"] in blocked:
                        skipped = [
                            _detail(item["id"], "미판정", blocked[call["id"]])
                            for item in selected
                        ] or [_detail(identifier, "미판정", blocked[call["id"]])]
                        details.extend(skipped)
                        result["calls"].append(
                            {
                                "id": call["id"],
                                "name": call["name"],
                                "index": index,
                                "details": skipped,
                            }
                        )
                        continue
                    if selection["missing_context"] or not selection["rows"]:
                        missing = selection["missing_context"]
                        tool_condition = any(
                            candidate["when"].get("tools")
                            for candidate in definition["rows"]
                        )
                        conflict = any(
                            (
                                definition["method"] == "LLM 기반"
                                or item.get("applicable") is not False
                            )
                            and (
                                "call" in item or "call_index" in item or tool_condition
                            )
                            for item in selected
                        )
                        verdict = "미판정" if missing or conflict else "비적용"
                        reason = (
                            "평가 행을 선택할 실행 증거가 부족하거나 모호합니다: "
                            + ", ".join(missing)
                            if missing
                            else (
                                "지정한 검사 항목의 호출 범위와 "
                                "평가 행의 적용 상황이 다릅니다."
                            )
                            if conflict
                            else "현재 역할·호출에 적용하는 평가 행이 없습니다."
                        )
                        row_details = [
                            _detail(item["id"], verdict, reason) for item in selected
                        ] or [_detail(identifier, verdict, reason)]
                        details.extend(row_details)
                        result["calls"].append(
                            {
                                "id": call["id"],
                                "name": call["name"],
                                "index": index,
                                "details": row_details,
                            }
                        )
                        continue
                    row = selection["rows"][0]
                    context = {
                        "node": node["node"],
                        "role": node.get("role"),
                        "call": call,
                        "criterion": row,
                        "report_path": node.get("paths", {}).get(
                            "report", "report.json"
                        ),
                    }
                    reference = (
                        _criteria_value(assessment, "reference", identifier)
                        if definition["method"] == "규칙 기반"
                        else None
                    )
                    tolerance = (
                        _criteria_value(assessment, "tolerance", identifier)
                        if definition["method"] == "규칙 기반"
                        else None
                    )
                    call_result = {
                        "id": call["id"],
                        "name": call["name"],
                        "index": index,
                        "row_id": row["row_id"],
                    }
                    if identifier == "N-F.1":
                        call_result["format_contract"] = format_contract(context)
                    unavailable = (
                        call.get("raw") is None
                        or not call.get("messages")
                        or bool(call.get("issues"))
                    )
                    if definition["method"] == "규칙 기반" and not compatible_rules:
                        call_details = [
                            _detail(
                                item["id"],
                                "미판정",
                                "규칙의 기준 문서가 구현 버전과 다릅니다. "
                                "변경된 기준에 맞춰 규칙 코드를 검토해야 합니다.",
                            )
                            for item in selected
                        ] or [
                            _detail(
                                identifier,
                                "미판정",
                                "규칙의 기준 문서가 구현 버전과 다릅니다. "
                                "변경된 기준에 맞춰 규칙 코드를 검토해야 합니다.",
                            )
                        ]
                    elif unavailable:
                        call_details = [
                            _detail(
                                item["id"],
                                "미판정",
                                "실제 모델 입력·원문 또는 직접 호출 연결이 부족합니다.",
                            )
                            for item in selected
                        ] or [
                            _detail(
                                identifier,
                                "미판정",
                                "실제 모델 입력·원문 또는 직접 호출 연결이 부족합니다.",
                            )
                        ]
                    elif identifier != "N-F.1" and not isinstance(call["output"], dict):
                        call_details = [
                            _detail(
                                item["id"],
                                "미판정",
                                "내용 비교에 필요한 모델 원본 JSON 객체가 없습니다.",
                            )
                            for item in selected
                        ] or [
                            _detail(
                                identifier,
                                "미판정",
                                "내용 비교에 필요한 모델 원본 JSON 객체가 없습니다.",
                            )
                        ]
                    elif (
                        definition["method"] == "규칙 기반"
                        and selected
                        and all(item.get("applicable") is False for item in selected)
                    ):
                        always = row["applicability"].endswith("항상")
                        actual_trigger = _actual_trigger(identifier, call)
                        call_details = [
                            _detail(
                                item["id"],
                                "미판정" if always or actual_trigger else "비적용",
                                "항상 적용하는 검사 전체를 비적용으로 둘 수 없습니다."
                                if always
                                else (
                                    "실제 출력이 비적용 선언과 충돌합니다. "
                                    "적용 기준을 확인해야 합니다."
                                )
                                if actual_trigger
                                else item["reason"],
                                executed=not always,
                            )
                            for item in selected
                        ]
                        if actual_trigger and definition["method"] == "규칙 기반":
                            call_details.extend(
                                evaluate_rules(
                                    identifier,
                                    context,
                                    [],
                                    reference=reference,
                                    tolerance=tolerance,
                                )
                            )
                    elif definition["method"] == "규칙 기반":
                        call_details = evaluate_rules(
                            identifier,
                            context,
                            selected,
                            reference=reference,
                            tolerance=tolerance,
                        )
                    elif method == "rules" or model is None:
                        call_details = [
                            _detail(
                                item["id"],
                                "미판정",
                                "LLM 평가 실행기가 실행되지 않았습니다.",
                            )
                            for item in selected
                        ]
                        if not call_details:
                            call_details = [
                                _detail(
                                    identifier,
                                    "미판정",
                                    "LLM 평가 실행기가 실행되지 않았습니다.",
                                )
                            ]
                    else:
                        # LLM은 실행 당시 자료와 기준으로 적용 여부도 판단한다.
                        # 사례의 답안·비적용 선언으로 판정을 생략하지 않는다.
                        evidence = select_inputs(row, node, call, selected)
                        try:
                            judged = await evaluate_llm(
                                row,
                                catalog,
                                evidence,
                                selected,
                                model=model,
                            )
                        except asyncio.CancelledError as exc:
                            if isinstance(exc, JudgeCancelled):
                                call_result["judge"] = exc.result
                            interrupted = [
                                _detail(
                                    item["id"],
                                    "미판정",
                                    "평가 모델 호출 중 취소",
                                    executed=True,
                                )
                                for item in selected
                            ]
                            call_result["details"] = interrupted
                            result["calls"].append(call_result)
                            details.extend(interrupted)
                            recorded = {detail["id"] for detail in details}
                            details.extend(
                                _detail(item["id"], "미판정", "평가 취소로 미실행")
                                for item in scoped
                                if item["id"] not in recorded
                            )
                            result.update(
                                details=_merged(details),
                                reason="평가 모델 호출 중 취소",
                            )
                            result["verdict"] = combine_verdicts(
                                [d["verdict"] for d in result["details"]]
                            )
                            result["executed"] = True
                            checks.append(result)
                            done = {c["check"] for c in checks}
                            for pending in definitions:
                                if pending["id"] not in done:
                                    checks.append(
                                        {
                                            "check": pending["id"],
                                            "axis": pending["axis"],
                                            "method": pending["method"],
                                            "executed": False,
                                            "verdict": "미판정",
                                            "reason": "평가 취소로 미실행",
                                            "details": [
                                                _detail(
                                                    item["id"],
                                                    "미판정",
                                                    "평가 취소로 미실행",
                                                )
                                                for item in items
                                                if item["check"] == pending["id"]
                                                and _scope(item, node)
                                            ],
                                            "calls": [],
                                            "related_checks": [],
                                        }
                                    )
                            raise AssessmentCancelled(
                                _finish(case, node, checks, cancelled=True)
                            ) from exc
                        call_details = deepcopy(judged["details"])
                        if not call_details:
                            call_details = [
                                _detail(
                                    identifier,
                                    "미판정",
                                    judged["reason"],
                                    executed=judged.get("executed", False),
                                )
                            ]
                        for detail in call_details:
                            detail.setdefault("executed", judged.get("executed", False))
                        if row["applicability"].endswith("항상") and all(
                            d["verdict"] == "비적용" for d in call_details
                        ):
                            call_details.append(
                                _detail(
                                    "applicability",
                                    "미판정",
                                    "항상 적용하는 검사의 판정이 없습니다.",
                                )
                            )
                        call_result["judge"] = judged
                    call_result["details"] = deepcopy(call_details)
                    details.extend(call_details)
                    result["calls"].append(call_result)
                for item in scoped:
                    if item["id"] not in seen_items:
                        details.append(
                            _detail(
                                item["id"],
                                "미판정",
                                "지정한 모델 호출이 실행 증거에 없습니다.",
                            )
                        )
                result["details"] = _merged(details)
                result["verdict"] = combine_verdicts(
                    [d["verdict"] for d in result["details"]]
                )
                result["executed"] = any(d["executed"] for d in result["details"])
                result["reason"] = (
                    "세부 항목을 종합했습니다."
                    if details
                    else "판정할 검사 항목·호출이 없습니다."
                )
                if not details and not result["calls"]:
                    continue
            checks.append(result)
            for call_result in result["calls"]:
                stage.setdefault(call_result["id"], []).append(
                    combine_verdicts([d["verdict"] for d in call_result["details"]])
                )
            if not result["calls"] and reason:
                for position, call in enumerate(node.get("calls", []), 1):
                    if not scoped or any(
                        _scope(item, node, call, position) for item in scoped
                    ):
                        stage.setdefault(call["id"], []).append("미판정")
            reasons = {d["reason"] for d in result["details"]}
            if len(reasons) == 1:
                result["reason"] = next(iter(reasons))
        for call_id, verdicts in stage.items():
            if call_id not in blocked:
                if "실패" in verdicts:
                    blocked[call_id] = "선행 단계 실패로 미실행"
                elif "미판정" in verdicts:
                    blocked[call_id] = "선행 단계 미판정으로 미실행"
    return _finish(case, node, checks)
