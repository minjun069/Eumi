"""최종 채택된 작성 원문만 기존 노드 기준으로 평가한다. 업무를 재실행하지 않는다."""

import asyncio
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Literal, NotRequired

from pydantic import JsonValue
from typing_extensions import TypedDict

from eval.batch_store import StoredRun, _report, load_batch, prepare_result, save_result
from eval.execution.metrics import operational_supported
from eval.naming import korea_timestamp
from eval.nodes.assessment import AssessmentCancelled, assess_node
from eval.nodes.criteria import load_criteria
from eval.nodes.evidence import NodeEvidence
from eval.nodes.schema import NodeAssessment, expectation_matches, requested_checks
from eval.nodes.scoring import _provenance
from eval.nodes.selection import (
    EvaluationFilter,
    SelectionDecision,
    candidate_cases,
    evaluation_filter,
    plan_case,
)
from eval.output_evidence import (
    ExcludedCall,
    FinalOutputEvidence,
    LinkStatus,
    OutputConnection,
    OutputKind,
    extract_output_evidence,
)
from eval.output_reuse import ReuseSource, find_reused, load_reuse
from eval.provenance import code_hashes
from eval.schema import Case, suite_adapter
from eval.tools.assessment import Verdict, combine_verdicts
from src.execution_trace import TraceRecorder, recording, trace_span


class OutputAssessment(NodeAssessment):
    id: str
    call_id: str
    call_index: int


class OutputComponentResult(TypedDict):
    id: str
    role: str
    kind: OutputKind
    paths: list[str]
    value: JsonValue
    result_id: str | None
    link_status: LinkStatus
    issues: list[str]
    assessment_ids: list[str]
    verdict: Verdict
    complete: bool
    reason: str


class OutputRun(TypedDict):
    run_id: str | None
    case_id: str
    repetition: int
    status: Literal["returned", "not_returned", "unknown"]
    verdict: Verdict
    complete: bool
    reason: str
    components: list[OutputComponentResult]
    issues: list[str]
    connection_checks: list[OutputConnection]
    excluded_calls: list[ExcludedCall]


class QualityRate(TypedDict):
    passed: int
    failed: int
    undetermined: int
    not_applicable: int
    numerator: int
    denominator: int
    rate: float | None


class OutputCheckSummary(QualityRate):
    check: str
    axis: str
    method: str
    unexecuted: int


class OutputSummary(QualityRate):
    verdict: Verdict
    complete: bool
    planned_runs: int
    evaluated_runs: int
    checks: list[OutputCheckSummary]


class OutputSelection(TypedDict):
    filters: EvaluationFilter
    decisions: list[SelectionDecision]
    case_ids: list[str]


class OutputReuse(TypedDict):
    source: ReuseSource
    compatible: bool
    reasons: list[str]
    assessment_ids: list[str]
    reused_count: int


class OutputEvaluation(TypedDict):
    schema_version: Literal["output-evaluation-v1"]
    id: str
    batch_id: str
    suite_id: str
    assessed_at: str
    status: Literal["completed", "cancelled"]
    method: Literal["rules", "all"]
    judge_model: str | None
    criteria: dict[str, JsonValue]
    criteria_sha256: str
    evidence_sha256: dict[str, str]
    evaluator_sha256: dict[str, str]
    provenance: list[dict[str, JsonValue]]
    runs: list[OutputRun]
    assessments: list[OutputAssessment]
    summary: OutputSummary
    judge_trace: dict[str, JsonValue]
    selection: OutputSelection
    limitations: list[str]
    reuse: NotRequired[OutputReuse]


class PlannedCall(TypedDict):
    id: str
    case: Case
    node: NodeEvidence
    format_observation: dict[str, JsonValue]


class PlannedRun(TypedDict):
    case: Case
    entry: StoredRun | None
    repetition: int
    evidence: FinalOutputEvidence
    calls: list[PlannedCall]


def _identity(node, call):
    return f"{node['id']}:{call['id']}"


def _evaluation_case(case, checks):
    value = deepcopy(case)
    original = value.get("assessment", {})
    expected = original.get("expected", {})
    assessment = deepcopy(original)
    if (
        isinstance(expected, dict)
        and expected.get("schema_version") == "node-expectations-v1"
    ):
        assessment["expected"]["items"] = [
            item for item in expected["items"] if item["check"] in checks
        ]
    else:
        assessment["expected"] = {
            "schema_version": "node-expectations-v1",
            "items": [],
        }
    assessment["checks"] = sorted(checks)
    value["assessment"] = assessment
    return value


def _call_case(case, node, evidence):
    """원래 호출 범위의 비교 자료와 관측한 섹션 분량 적용 조건만 연결한다."""
    value = deepcopy(case)
    call = node["calls"][0]
    previous_issues = len(call["issues"])
    prepared = value["assessment"]
    prepared["expected"]["items"] = [
        item
        for item in prepared["expected"]["items"]
        if expectation_matches(item, node, call, call["index"])
    ]
    observation = {}
    adopted = [
        component
        for component in evidence["components"]
        if component["link_status"] == "matched"
        and component["kind"] in {"report_description", "report_insight"}
        and component["node"] is not None
        and component["node"]["id"] == node["id"]
        and any(c["id"] == call["id"] for c in component["node"]["calls"])
    ]
    if adopted and call["name"] == "ReportText":
        reference = prepared.setdefault("reference", {})
        format_reference = (
            reference.setdefault("N-F.1", {}) if isinstance(reference, dict) else None
        )
        if not isinstance(format_reference, dict):
            call["issues"].append(
                "기존 분량 적용 기준이 객체가 아니어서 확인할 수 없습니다."
            )
        else:
            condition = format_reference.setdefault("format", {})
            if (
                not isinstance(condition, dict)
                or condition.get("completed", True) is not True
            ):
                call["issues"].append(
                    "기존 분량 적용 조건과 실제 반환된 승인 작성본이 상충합니다."
                )
            else:
                condition["completed"] = True
                observation = {
                    "completed": True,
                    "scope": "adopted_report_section",
                    "paths": list(
                        dict.fromkeys(p for c in adopted for p in c["paths"])
                    ),
                    "result_ids": [c["result_id"] for c in adopted],
                    "reason": "승인된 작성본이 실제 반환 섹션에 채택됐습니다. "
                    "보고서 전체 완료나 내용 통과를 뜻하지 않습니다.",
                }
    issues = call["issues"][previous_issues:]
    if issues:
        observation.update(status="undetermined", reasons=issues)
        observation.setdefault("paths", [call["path"]])
        if adopted:
            observation.update(
                scope="adopted_report_section",
                observed_completed=True,
                paths=list(dict.fromkeys(p for c in adopted for p in c["paths"])),
                result_ids=[c["result_id"] for c in adopted],
            )
    elif observation:
        observation.update(status="observed", reasons=[])
    return value, observation


def _component_result(component, planned, assessed, source_node=None):
    result = {key: deepcopy(value) for key, value in component.items() if key != "node"}
    node = component["node"] or source_node
    identities = [_identity(node, call) for call in node["calls"]] if node else []
    selected = [identity for identity in identities if identity in planned]
    values = [assessed[identity] for identity in selected if identity in assessed]
    if component["link_status"] != "matched":
        verdict, complete, reason = (
            "미판정",
            False,
            "최종 반환물과 작성 원문을 연결하지 못했습니다.",
        )
    elif component["kind"] == "artifacts":
        verdict, complete, reason = (
            "비적용",
            True,
            "산출물 선택은 동일 작성 호출의 판정을 참조합니다. "
            "코드가 구성한 산출물의 표시 품질은 별도로 채점하지 않습니다.",
        )
    elif not node or not identities:
        verdict, complete, reason = "미판정", False, "채택된 작성 호출 원문이 없습니다."
    elif not selected:
        verdict, complete, reason = (
            "비적용",
            True,
            "선택한 검사 행이 이 최종 작성 호출에 적용되지 않습니다.",
        )
    else:
        verdict = combine_verdicts(
            [item["verdict"] for item in values]
            + (["미판정"] if len(values) != len(selected) else [])
        )
        complete = len(values) == len(selected) and all(
            item["complete"] for item in values
        )
        reason = (
            "채택된 작성 호출의 검사 결과를 연결했습니다."
            if complete
            else "채택된 작성 호출의 일부 품질 검사가 미완료입니다."
        )
    return {
        **result,
        "assessment_ids": [item["id"] for item in values],
        "verdict": verdict,
        "complete": complete,
        "reason": reason,
    }


def _run_result(run, assessments) -> OutputRun:
    evidence = run["evidence"]
    planned = {item["id"] for item in run["calls"]}
    parts = []
    for part in evidence["components"]:
        source_node = next(
            (
                peer["node"]
                for peer in evidence["components"]
                if part["kind"] == "artifacts"
                and part["result_id"] is not None
                and peer["result_id"] == part["result_id"]
                and peer["role"] == part["role"]
                and peer["kind"] == "response"
                and peer["link_status"] == "matched"
            ),
            None,
        )
        parts.append(_component_result(part, planned, assessments, source_node))
    unresolved = (
        evidence["status"] != "returned" or bool(evidence["issues"]) or not parts
    )
    verdict = combine_verdicts(
        [part["verdict"] for part in parts] + (["미판정"] if unresolved else [])
    )
    complete = not unresolved and all(part["complete"] for part in parts)
    return {
        "run_id": run["entry"]["run_id"] if run["entry"] else None,
        "case_id": run["case"]["id"],
        "repetition": run["repetition"],
        "status": evidence["status"],
        "verdict": verdict,
        "complete": complete,
        "reason": "최종 채택 작성물의 선택 검사 결과입니다."
        if complete
        else "최종 반환 연결 또는 선택한 품질 검사가 미완료입니다.",
        "components": parts,
        "issues": evidence["issues"],
        "connection_checks": evidence["connection_checks"],
        "excluded_calls": evidence["excluded_calls"],
    }


def _rates(items) -> QualityRate:
    counts = {
        name: sum(item["verdict"] == value for item in items)
        for name, value in (
            ("passed", "통과"),
            ("failed", "실패"),
            ("undetermined", "미판정"),
            ("not_applicable", "비적용"),
        )
    }
    denominator = counts["passed"] + counts["failed"]
    return {
        **counts,
        "numerator": counts["passed"],
        "denominator": denominator,
        "rate": counts["passed"] / denominator if denominator else None,
    }


def _summary(runs, assessments, planned, catalog) -> OutputSummary:
    grouped = {}
    assessed = {item["id"]: item for item in assessments}
    for item in assessments:
        for check in item["checks"]:
            grouped.setdefault(check["check"], []).append(check)
    for run in planned:
        for call in run["calls"]:
            completed = {
                item["check"] for item in assessed.get(call["id"], {}).get("checks", [])
            }
            for identifier in sorted(
                requested_checks(call["case"], [call["node"]]) - completed
            ):
                definition = catalog["checks"][identifier]
                grouped.setdefault(identifier, []).append(
                    {
                        "axis": definition["axis"],
                        "method": definition["method"],
                        "executed": False,
                        "verdict": "미판정",
                    }
                )
    return {
        **_rates(runs),
        "verdict": combine_verdicts([run["verdict"] for run in runs]),
        "complete": bool(runs) and all(run["complete"] for run in runs),
        "planned_runs": len(runs),
        "evaluated_runs": sum(
            bool(run["components"])
            and any(part["assessment_ids"] for part in run["components"])
            for run in runs
        ),
        "checks": [
            {
                "check": name,
                "axis": values[0]["axis"],
                "method": values[0]["method"],
                "unexecuted": sum(not item["executed"] for item in values),
                **_rates(values),
            }
            for name, values in grouped.items()
        ],
    }


async def score_outputs(
    folder: Path,
    output: Path | None = None,
    *,
    model=None,
    judge_model: str | None = None,
    method: Literal["rules", "all"] = "rules",
    criteria_root: Path | None = None,
    case_ids: list[str] | None = None,
    check_ids: list[str] | None = None,
    row_ids: list[str] | None = None,
    reuse: Path | None = None,
) -> Path:
    """최종 채택 호출에 기존 compose 검사를 적용하고 별도 품질 결과를 저장한다."""
    if method not in {"rules", "all"} or (method == "all" and model is None):
        raise ValueError("all 평가에는 별도 평가 모델이 필요합니다")
    if judge_model is not None and (
        not isinstance(judge_model, str) or not judge_model.strip()
    ):
        raise ValueError("평가 모델 식별자는 비어 있지 않은 문자열이어야 합니다")
    if judge_model is None and model is not None:
        judge_model = next(
            (
                value
                for key in ("model_name", "model")
                if isinstance(value := getattr(model, key, None), str) and value.strip()
            ),
            None,
        )
    root, suite, batch, original_cases, entries, hashes = load_batch(folder)
    available = [case for case in original_cases if operational_supported(case)]
    if not available:
        raise ValueError("최종 출력을 평가할 에이전트·보고서 실행 사례가 없습니다")
    catalog = load_criteria(criteria_root)
    checks = {
        key
        for key, definition in catalog["checks"].items()
        if "compose" in definition["nodes"] and key != "N04-O.3"
    }
    filters = evaluation_filter(
        available, catalog, case_ids=case_ids, check_ids=check_ids, row_ids=row_ids
    )
    if set(filters["check_ids"] or []) - checks or any(
        identity.partition("/")[0] not in checks
        for identity in filters["row_ids"] or []
    ):
        raise ValueError(
            "최종 출력에는 compose 작성 검사만 선택할 수 있습니다. "
            "검토 판정은 제외합니다"
        )
    candidates, decisions = candidate_cases(
        [_evaluation_case(case, checks) for case in available], catalog, filters
    )
    if not candidates:
        raise ValueError("선택한 범위에 최종 출력 평가 사례가 없습니다")
    identifier, destination = prepare_result(root, batch, original_cases, output)
    normalized = {
        case["id"]: case
        for case in suite_adapter.dump_python(suite, mode="json")["cases"]
    }
    planned, provenance = [], []
    for case in candidates:
        for repetition in range(1, batch["plan"]["repeat"] + 1):
            entry = entries.get((case["id"], repetition))
            report = _report(root, entry, case, suite["id"], hashes) if entry else None
            evidence = extract_output_evidence(report, case, repetition)
            calls, seen = [], set()
            for original_node in evidence["nodes"]:
                for original_call in original_node["calls"]:
                    call_id = _identity(original_node, original_call)
                    if call_id in seen:
                        continue
                    seen.add(call_id)
                    node = deepcopy(original_node)
                    node["calls"] = [deepcopy(original_call)]
                    effective, observed = _call_case(case, node, evidence)
                    effective, selected = plan_case(
                        effective,
                        [node],
                        catalog,
                        repetition,
                        row_ids=filters["row_ids"],
                    )
                    decisions.extend(selected)
                    if requested_checks(effective, [node]):
                        calls.append(
                            PlannedCall(
                                id=call_id,
                                case=effective,
                                node=node,
                                format_observation=observed,
                            )
                        )
            planned.append(
                PlannedRun(
                    case=case,
                    entry=entry,
                    repetition=repetition,
                    evidence=evidence,
                    calls=calls,
                )
            )
            if entry:
                provenance.append(
                    _provenance(root, entry, normalized[case["id"]], catalog, hashes)
                )
    criteria = {
        "documents": catalog["documents"],
        "checks": catalog["checks"],
        "cases": [normalized[case["id"]] for case in candidates],
        "plan": batch["plan"],
        "selection": filters,
        "effective_cases": [
            suite_adapter.dump_python({**suite, "cases": [case]}, mode="json")["cases"][
                0
            ]
            for case in candidates
        ],
        "call_cases": [
            {
                "assessment_id": item["id"],
                "case_id": item["case"]["id"],
                "repetition": run["repetition"],
                "node_id": item["node"]["id"],
                "call_id": item["node"]["calls"][0]["id"],
                "assessment": item["case"]["assessment"],
                "format_observation": item["format_observation"],
            }
            for run in planned
            for item in run["calls"]
        ],
    }
    digest = sha256(
        json.dumps(
            criteria, sort_keys=True, ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
    evaluator_hashes = code_hashes()
    pool = (
        load_reuse(
            reuse,
            batch_id=batch["id"],
            method=method,
            judge_model=judge_model,
            criteria_sha256=digest,
            evidence_sha256=hashes,
            evaluator_sha256=evaluator_hashes,
        )
        if reuse is not None
        else None
    )
    recorder = TraceRecorder()
    assessments, reused_ids, cancelled = {}, [], False
    try:
        with (
            recording(recorder),
            trace_span("evaluation", "output_judge", {"evaluation_id": identifier}),
        ):
            for run in planned:
                for item in run["calls"]:
                    case, node = item["case"], item["node"]
                    call = node["calls"][0]
                    cached = (
                        find_reused(
                            pool, case["id"], run["repetition"], node["id"], call["id"]
                        )
                        if pool
                        else None
                    )
                    if cached is not None:
                        assessments[item["id"]] = cached
                        reused_ids.append(item["id"])
                        continue
                    try:
                        value = await assess_node(
                            case,
                            node,
                            catalog=catalog,
                            model=model,
                            method=method,
                            row_ids=filters["row_ids"],
                        )
                    except AssessmentCancelled as exc:
                        assessments[item["id"]] = {
                            **exc.assessment,
                            "id": item["id"],
                            "call_id": call["id"],
                            "call_index": call["index"],
                        }
                        raise
                    assessments[item["id"]] = {
                        **value,
                        "id": item["id"],
                        "call_id": call["id"],
                        "call_index": call["index"],
                    }
    except asyncio.CancelledError:
        cancelled = True
    runs = [_run_result(run, assessments) for run in planned]
    result: OutputEvaluation = {
        "schema_version": "output-evaluation-v1",
        "id": identifier,
        "batch_id": batch["id"],
        "suite_id": suite["id"],
        "assessed_at": korea_timestamp(),
        "status": "cancelled" if cancelled else "completed",
        "method": method,
        "judge_model": judge_model,
        "criteria": criteria,
        "criteria_sha256": digest,
        "evidence_sha256": hashes,
        "evaluator_sha256": evaluator_hashes,
        "provenance": provenance,
        "runs": runs,
        "assessments": list(assessments.values()),
        "summary": _summary(runs, list(assessments.values()), planned, catalog),
        "judge_trace": recorder.export(),
        "selection": {
            "filters": filters,
            "decisions": decisions,
            "case_ids": [case["id"] for case in candidates],
        },
        "limitations": [
            "최종 반환에 채택된 compose 작성 호출만 기존 노드 기준으로 평가합니다.",
            "이전 초안·검토 호출의 실패는 최종 채택본의 품질 실패로 합산하지 않습니다.",
            "연결 불일치·원문 누락은 관측 사유와 품질 미판정으로 남기며 "
            "새 EX 판정을 만들지 않습니다.",
            "규칙의 독립 비교값이 없으면 추정하지 않습니다. "
            "LLM에는 작성 당시 메시지·응답 형식 전체와 기존 검사 기준을 제공합니다.",
            "선택한 검사 범위의 품질이며 EX 연결 검증·운영 지표·서비스 화면 품질을 "
            "대신하지 않습니다.",
            "승인된 보고서 섹션의 분량 적용은 전체 보고서의 완료 또는 내용 통과를 "
            "뜻하지 않습니다.",
        ],
    }
    if pool is not None:
        result["reuse"] = {
            key: pool[key] for key in ("source", "compatible", "reasons")
        } | {"assessment_ids": reused_ids, "reused_count": len(reused_ids)}
    destination = save_result(root, result, destination)
    if cancelled:
        raise asyncio.CancelledError(f"중단 전 최종 출력 품질 판정 저장: {destination}")
    return destination
