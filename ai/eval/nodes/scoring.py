"""시나리오 실행과 독립적으로 저장 증거를 읽어 노드 평가 기록을 저장한다."""

import asyncio
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import JsonValue
from typing_extensions import TypedDict

from eval.batch_store import (
    StoredRun,
    _inside,
    _read,
    _report,
    load_batch,
    prepare_result,
    save_result,
)
from eval.naming import korea_timestamp
from eval.nodes.assessment import AssessmentCancelled, _scope, assess_node
from eval.nodes.criteria import CriteriaCatalog, load_criteria, select_rows
from eval.nodes.evidence import NodeEvidence, extract_nodes, select_nodes
from eval.nodes.metrics import NodeSummary, summarize_nodes
from eval.nodes.schema import (
    CaseScopeEvidence,
    NodeAssessment,
    case_expectations,
    requested_checks,
)
from eval.nodes.selection import (
    EvaluationFilter,
    RunCase,
    SelectionDecision,
    aggregate_cases,
    candidate_cases,
    evaluation_filter,
    plan_case,
)
from eval.provenance import code_hashes, previous_document_hash
from eval.schema import Assessment, Case, suite_adapter
from src.execution_trace import TraceRecorder, recording, trace_span


class ScoredRun(TypedDict):
    run_id: str | None
    case_id: str
    repetition: int
    verdict: str
    complete: bool
    reason: str
    node_ids: list[str]
    unmatched_expectations: list[str]
    unmatched_checks: list[str]
    model_scope: list[CaseScopeEvidence]


class SelectedRun(TypedDict):
    case_id: str
    repetition: int
    assessment: Assessment


class SelectionRecord(TypedDict):
    filters: EvaluationFilter
    decisions: list[SelectionDecision]
    case_ids: list[str]
    run_cases: list[SelectedRun]


class NodeEvaluation(TypedDict):
    schema_version: Literal["node-evaluation-v1"]
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
    runs: list[ScoredRun]
    assessments: list[NodeAssessment]
    nodes: list[NodeSummary]
    judge_trace: dict[str, JsonValue]
    limitations: list[str]
    selection: SelectionRecord


class PlannedRun(TypedDict):
    case: Case
    repetition: int
    entry: StoredRun | None
    nodes: list[NodeEvidence]
    scope: list[CaseScopeEvidence]


def _provenance(root, entry, case, catalog, hashes):
    result = {"run_id": entry["run_id"], "case_criteria": "unknown", "documents": {}}
    case_path = f"runs/{entry['run_id']}/case.json"
    path = _inside(root, case_path)
    if path.exists():
        original, digest = _read(path, root=root, hashes=hashes)
        hashes[case_path] = digest
        result["case_criteria"] = (
            "same"
            if original.get("assessment") == case.get("assessment")
            else "changed"
        )
        result["original_assessment"] = original.get("assessment")
    manifest_path = f"runs/{entry['run_id']}/manifest.json"
    path = _inside(root, manifest_path)
    if path.exists():
        original, digest = _read(path, root=root, hashes=hashes)
        hashes[manifest_path] = digest
        saved = original.get("files_sha256", {})
        for name, document in catalog["documents"].items():
            previous = previous_document_hash(saved, name)
            result["documents"][name] = {
                "original_sha256": previous,
                "status": "unknown"
                if previous is None
                else "same"
                if previous == document["sha256"]
                else "changed",
            }
    return result


def _run_result(
    case, repetition, entry, assessments, nodes, catalog, *, scope=None, row_ids=None
):
    scope_nodes = scope if scope is not None else nodes
    requested = requested_checks(case, scope_nodes)
    items = case_expectations(case, scope_nodes)
    unmatched = [
        item["id"]
        for item in items
        if item["check"] in requested
        and not any(
            node["node"] in catalog["checks"][item["check"]]["nodes"]
            and _scope(item, node)
            and any(
                _scope(item, node, call, index)
                and (
                    selection := select_rows(
                        catalog["checks"][item["check"]], node, call, row_ids=row_ids
                    )
                )["rows"]
                and not selection["missing_context"]
                and any(
                    item.get("row_id", row["row_id"]) == row["row_id"]
                    for row in selection["rows"]
                )
                for index, call in enumerate(node["calls"], 1)
            )
            for node in nodes
        )
    ]
    unmatched_checks = sorted(
        requested
        - {
            check["check"]
            for assessment in assessments
            for check in assessment.get("checks", [])
        }
    )
    verdicts = [a["verdict"] for a in assessments]
    complete = (
        bool(assessments)
        and all(a["complete"] for a in assessments)
        and not unmatched
        and not unmatched_checks
    )
    if "실패" in verdicts:
        verdict = "실패"
    elif (
        assessments
        and all(a["complete"] and a["verdict"] == "통과" for a in assessments)
        and not unmatched
        and not unmatched_checks
    ):
        verdict = "통과"
    else:
        verdict, complete = "미판정", False
    return {
        "run_id": entry["run_id"] if entry else None,
        "case_id": case["id"],
        "repetition": repetition,
        "verdict": verdict,
        "complete": complete,
        "reason": "선택한 모델 호출에 평가할 요청 검사가 없습니다."
        if not requested
        else "요청한 검사에 대응하는 노드 판정이 없습니다."
        if unmatched_checks
        else "노드 평가 결과를 종합했습니다."
        if assessments
        else "예정 실행의 노드 증거가 없습니다.",
        "node_ids": [a["node_id"] for a in assessments],
        "unmatched_expectations": unmatched,
        "unmatched_checks": unmatched_checks,
        "model_scope": scope or [],
    }


async def score_nodes(
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
) -> Path:
    """저장 증거에 규칙·평가 모델을 적용한다. 업무를 재실행하지 않는다."""
    if method not in {"rules", "all"} or (method == "all" and model is None):
        raise ValueError("all 평가에는 별도 평가 모델이 필요합니다")
    if judge_model is not None and (
        not isinstance(judge_model, str) or not judge_model.strip()
    ):
        raise ValueError("평가 모델 식별자는 비어 있지 않은 문자열이어야 합니다")
    selected_model = judge_model
    if selected_model is None and model is not None:
        for attribute in ("model_name", "model"):
            value = getattr(model, attribute, None)
            if isinstance(value, str) and value.strip():
                selected_model = value
                break
    root, suite, batch, cases, entries, hashes = load_batch(folder)
    original_cases = cases
    cases = [case for case in cases if case["unit"] != "tool"]
    if not cases:
        raise ValueError("평가 계획에 노드·선택·에이전트·흐름 사례가 없습니다")
    catalog: CriteriaCatalog = load_criteria(criteria_root)
    filters: EvaluationFilter = evaluation_filter(
        cases, catalog, case_ids=case_ids, check_ids=check_ids, row_ids=row_ids
    )
    candidates, decisions = candidate_cases(cases, catalog, filters)
    selected_rows = filters["row_ids"]
    evaluation_id, destination = prepare_result(root, batch, original_cases, output)
    evaluator_hashes = code_hashes()
    # 평가 모델 비용·오류는 업무 trace와 분리해서 저장한다.
    recorder = TraceRecorder()
    assessments: list[NodeAssessment] = []
    evidences: list[NodeEvidence] = []
    scope_evidence: list[CaseScopeEvidence] = []
    runs: list[ScoredRun] = []
    provenance = []
    cancelled = False
    normalized = suite_adapter.dump_python(suite, mode="json")
    normalized_cases = {case["id"]: case for case in normalized["cases"]}
    # 판단 모델 호출 전에 전체 대상 계획을 확정한다. 취소 뒤에도 같은 분모를 쓴다.
    planned: list[PlannedRun] = []
    run_cases: list[RunCase] = []
    for case in candidates:
        for repetition in range(1, batch["plan"]["repeat"] + 1):
            entry = entries.get((case["id"], repetition))
            report = _report(root, entry, case, suite["id"], hashes) if entry else None
            run_scope: list[CaseScopeEvidence] = []
            raw_nodes = (
                extract_nodes(report, case, repetition, scope=run_scope)
                if report
                else []
            )
            effective, run_decisions = plan_case(
                case, raw_nodes, catalog, repetition, row_ids=selected_rows
            )
            decisions.extend(run_decisions)
            run_cases.append({"case": effective, "repetition": repetition})
            if not requested_checks(effective, run_scope):
                continue
            nodes = select_nodes(
                deepcopy(raw_nodes), effective, catalog, row_ids=selected_rows
            )
            scope_evidence.extend(run_scope)
            evidences.extend(nodes)
            if entry:
                provenance.append(
                    _provenance(
                        root, entry, normalized_cases[case["id"]], catalog, hashes
                    )
                )
            planned.append(
                {
                    "case": effective,
                    "repetition": repetition,
                    "entry": entry,
                    "nodes": nodes,
                    "scope": run_scope,
                }
            )
    cases = aggregate_cases(candidates, run_cases)
    try:
        with (
            recording(recorder),
            trace_span("evaluation", "node_judge", {"evaluation_id": evaluation_id}),
        ):
            for run in planned:
                case, repetition, entry = run["case"], run["repetition"], run["entry"]
                nodes, run_scope = run["nodes"], run["scope"]
                current = []
                for node in nodes:
                    try:
                        assessment = await assess_node(
                            case,
                            node,
                            catalog=catalog,
                            model=model,
                            method=method,
                            row_ids=selected_rows,
                        )
                    except AssessmentCancelled as exc:
                        current.append(exc.assessment)
                        assessments.append(exc.assessment)
                        runs.append(
                            _run_result(
                                case,
                                repetition,
                                entry,
                                current,
                                nodes,
                                catalog,
                                scope=run_scope,
                                row_ids=selected_rows,
                            )
                        )
                        raise
                    current.append(assessment)
                    assessments.append(assessment)
                runs.append(
                    _run_result(
                        case,
                        repetition,
                        entry,
                        current,
                        nodes,
                        catalog,
                        scope=run_scope,
                        row_ids=selected_rows,
                    )
                )
    except asyncio.CancelledError:
        cancelled = True
    completed_slots = {(run["case_id"], run["repetition"]) for run in runs}
    for run in planned:
        case, repetition = run["case"], run["repetition"]
        if (case["id"], repetition) not in completed_slots:
            pending = _run_result(
                case,
                repetition,
                run["entry"],
                [],
                [],
                catalog,
                scope=run["scope"],
                row_ids=selected_rows,
            )
            pending["reason"] = "평가 취소로 미실행"
            runs.append(pending)
    criteria = {
        "documents": catalog["documents"],
        "checks": catalog["checks"],
        "cases": [normalized_cases[case["id"]] for case in cases],
        "plan": batch["plan"],
        "node_performance": normalized.get("node_performance", []),
        "selection": filters,
        "effective_cases": suite_adapter.dump_python(
            {**suite, "cases": cases}, mode="json"
        )["cases"],
    }
    result: NodeEvaluation = {
        "schema_version": "node-evaluation-v1",
        "id": evaluation_id,
        "batch_id": batch["id"],
        "suite_id": suite["id"],
        "assessed_at": korea_timestamp(),
        "status": "cancelled" if cancelled else "completed",
        "method": method,
        "judge_model": selected_model,
        "criteria": criteria,
        "criteria_sha256": sha256(
            json.dumps(
                criteria, sort_keys=True, ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest(),
        "evidence_sha256": hashes,
        "evaluator_sha256": evaluator_hashes,
        "provenance": provenance,
        "runs": runs,
        "assessments": assessments,
        "nodes": summarize_nodes(
            cases,
            batch["plan"]["repeat"],
            assessments,
            evidences,
            performance=suite.get("node_performance", []),
            scope_evidence=scope_evidence,
            row_ids=selected_rows,
            catalog=catalog,
            run_cases=run_cases,
        ),
        "judge_trace": recorder.export(),
        "limitations": [
            "현재 정형 평가 정의(JSON)와 저장 증거로 재판정하며 "
            "업무를 재실행하지 않습니다.",
            "사례·데이터셋과 기대 조건의 충분성·독립성은 별도로 준비·검토해야 합니다.",
            "provenance의 same/changed/unknown은 실행 당시 기준과의 비교이며 "
            "기준 변경 승인을 뜻하지 않습니다.",
            "규칙 기준 원문이 구현 버전과 다르면 규칙 판정을 보류합니다. "
            "LLM 기준은 매 평가 실행 때 JSON에서 상황에 맞는 행만 선택합니다.",
            "rules 방식은 LLM 검사를 미실행으로 남기며 "
            "선행 단계 미판정 이후 검사를 실행하지 않습니다.",
            "사용량은 노드·역할별로 집계합니다. 모델·입력 규모별 비교는 "
            "원본 추적과 시험 조건을 별도로 확인해야 합니다.",
        ],
        "selection": {
            "filters": filters,
            "decisions": decisions,
            "case_ids": [case["id"] for case in cases],
            "run_cases": [
                {
                    "case_id": run["case"]["id"],
                    "repetition": run["repetition"],
                    "assessment": run["case"].get("assessment", {}),
                }
                for run in run_cases
            ],
        },
    }
    destination = save_result(root, result, destination)
    if cancelled:
        raise asyncio.CancelledError(f"중단 전 노드 판정 저장: {destination}")
    return destination
