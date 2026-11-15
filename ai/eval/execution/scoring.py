"""업무 재실행 없이 EX 기능을 채점하고 여섯 역할의 운영 사용량을 진단한다."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import JsonValue
from typing_extensions import TypedDict

from eval.batch_store import (
    _inside,
    _read,
    load_batch,
    prepare_result,
    save_result,
)
from eval.execution.evidence import load_execution_report
from eval.execution.metrics import (
    FUNCTIONAL_EXCLUSION_REASON,
    ExecutionSummary,
    operational_supported,
    summarize_executions,
)
from eval.execution.rules import ExecutionAssessment, assess_execution
from eval.execution.schema import COMMON_CHECKS, REPORT_CHECKS, supported
from eval.naming import korea_timestamp
from eval.provenance import code_hashes, previous_document_hash
from eval.schema import case_adapter

DOCUMENTS = (
    "eval/docs/methods.md",
    "eval/docs/execution/README.md",
    "eval/docs/execution/common.md",
    "eval/docs/execution/user-request.md",
    "eval/docs/execution/dashboard-report.md",
    "docs/agent/workflow.md",
    "docs/agent/state.md",
    "docs/agent/report.md",
)


class ExecutionEvaluation(TypedDict):
    schema_version: Literal["execution-evaluation-v1"]
    id: str
    batch_id: str
    suite_id: str
    assessed_at: str
    method: Literal["rules"]
    criteria: dict[str, JsonValue]
    criteria_sha256: str
    evidence_sha256: dict[str, str]
    evaluator_sha256: dict[str, str]
    provenance: list[dict[str, JsonValue]]
    selection: dict[str, JsonValue]
    runs: list[ExecutionAssessment]
    summary: ExecutionSummary
    limitations: list[str]


def _criteria_documents():
    root = Path(__file__).resolve().parents[2]
    return {
        name: {
            "sha256": sha256((root / name).read_bytes()).hexdigest(),
            "text": (root / name).read_text(encoding="utf-8"),
        }
        for name in DOCUMENTS
    }


def _provenance(root, entry, case, documents, hashes):
    result = {"run_id": entry["run_id"], "case_criteria": "unknown", "documents": {}}
    relative = f"runs/{entry['run_id']}/case.json"
    path = _inside(root, relative)
    if path.exists():
        original, hashes[relative] = _read(path, root=root, hashes=hashes)
        result["case_criteria"] = (
            "same"
            if original.get("assessment") == case.get("assessment")
            else "changed"
        )
        result["original_assessment"] = original.get("assessment")
    relative = f"runs/{entry['run_id']}/manifest.json"
    path = _inside(root, relative)
    if path.exists():
        manifest, hashes[relative] = _read(path, root=root, hashes=hashes)
        saved = manifest.get("files_sha256", {})
        for name, document in documents.items():
            original = previous_document_hash(saved, name)
            result["documents"][name] = {
                "original_sha256": original,
                "status": "unknown"
                if original is None
                else ("same" if original == document["sha256"] else "changed"),
            }
    return result


def _select(cases, case_ids, check_ids):
    ids = list(dict.fromkeys(case_ids or []))
    checks = list(dict.fromkeys(check_ids or []))
    available = {case["id"]: case for case in cases}
    if set(ids) - available.keys():
        raise ValueError("저장된 실행 계획에 없는 사례 ID입니다")
    if set(checks) - set(COMMON_CHECKS + REPORT_CHECKS):
        raise ValueError("평가 문서에 없는 실행 검사 ID입니다")
    chosen = [
        case
        for case in cases
        if (not ids or case["id"] in ids) and operational_supported(case)
    ]
    if ids and any(not operational_supported(available[case_id]) for case_id in ids):
        raise ValueError("실행 채점·운영 진단 대상은 agent 또는 workflow/report입니다")
    if not chosen:
        raise ValueError("채점·운영 진단할 에이전트·보고서 실행 사례가 없습니다")
    declared = {
        check
        for case in chosen
        if supported(case)
        for check in case.get("assessment", {}).get("checks", [])
        if check in COMMON_CHECKS + REPORT_CHECKS
    }
    if set(checks) - declared:
        raise ValueError("선택한 사례에서 선언하지 않은 검사입니다")
    selected, excluded, functional_excluded = [], [], []
    for case in chosen:
        value = deepcopy(case)
        if not supported(case):
            selected.append(value)
            functional_excluded.append(
                {"case_id": case["id"], "reason": FUNCTIONAL_EXCLUSION_REASON}
            )
            continue
        declared = value.get("assessment", {}).get("checks", [])
        filtered = [
            check
            for check in declared
            if check in COMMON_CHECKS + REPORT_CHECKS
            and (not checks or check in checks)
        ]
        if checks and not filtered:
            excluded.append(
                {
                    "case_id": case["id"],
                    "reason": "선택 검사와 선언한 검사가 겹치지 않음",
                }
            )
            continue
        if "assessment" in value:
            value["assessment"]["checks"] = filtered
        selected.append(value)
    return selected, {
        "case_ids": ids,
        "check_ids": checks,
        "excluded": excluded,
        "functional_excluded": functional_excluded,
    }


def score_executions(
    folder: Path, output: Path | None = None, *, case_ids=None, check_ids=None
) -> Path:
    root, suite, batch, original_cases, entries, hashes = load_batch(folder)
    cases, filters = _select(original_cases, case_ids, check_ids)
    targets = {case["target"] for case in original_cases}
    goals = [
        goal
        for goal in suite.get("execution_performance", [])
        if goal["target"] in targets
    ]
    # 증거를 읽기 전에 출력 경로 충돌을 확인한다. 기존 파일을 덮어쓰지 않는다.
    evaluation_id, destination = prepare_result(root, batch, original_cases, output)
    assessed_at = korea_timestamp()
    documents = _criteria_documents()
    reports, assessments, provenance = [], [], []
    original = {case["id"]: case for case in original_cases}
    for case in cases:
        for repetition in range(1, batch["plan"]["repeat"] + 1):
            entry = entries.get((case["id"], repetition))
            report = (
                load_execution_report(
                    root, entry, case, suite["id"], hashes, observed_at=assessed_at
                )
                if entry
                else None
            )
            if entry:
                provenance.append(
                    _provenance(root, entry, original[case["id"]], documents, hashes)
                )
            if report is not None:
                reports.append(report)
            if supported(case):
                assessment = assess_execution(case, report)
                assessment["repetition"] = repetition
                if entry:
                    assessment["run_id"] = entry["run_id"]
                assessments.append(assessment)
    criteria = {
        "documents": documents,
        "cases": [case_adapter.dump_python(case, mode="json") for case in cases],
        "original_plan": batch["plan"],
        "execution_performance": goals,
        "execution_prices": suite.get("execution_prices"),
    }
    result: ExecutionEvaluation = {
        "schema_version": "execution-evaluation-v1",
        "id": evaluation_id,
        "batch_id": batch["id"],
        "suite_id": suite["id"],
        "assessed_at": assessed_at,
        "method": "rules",
        "criteria": criteria,
        "criteria_sha256": sha256(
            json.dumps(
                criteria, sort_keys=True, ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest(),
        "evidence_sha256": hashes,
        "evaluator_sha256": code_hashes(
            "execution/scoring.py",
            "execution/rules.py",
            "execution/metrics.py",
            "execution/evidence.py",
            "execution/schema.py",
            "schema.py",
            "naming.py",
            "batch_store.py",
            "assessment_store.py",
            "provenance.py",
        ),
        "provenance": provenance,
        "selection": filters | {"selected_case_ids": [case["id"] for case in cases]},
        "runs": assessments,
        "summary": summarize_executions(
            cases,
            batch["plan"]["repeat"],
            assessments,
            reports,
            goals=goals,
            pricing=suite.get("execution_prices"),
        ),
        "limitations": [
            "저장 증거를 현재 기준으로 채점하며 업무·평가 모델을 호출하지 않습니다.",
            "노드 내용 품질·서비스 접수·반환 후 저장·알림·화면 표시는 "
            "평가하지 않습니다.",
            "선택한 검사 범위의 기능 판정이며 제외된 검사의 통과를 뜻하지 않습니다.",
            FUNCTIONAL_EXCLUSION_REASON,
            "기준 변경 여부는 provenance에 기록하며 당시 기준의 판정과 구분합니다.",
            "준비된 기존 상태의 재진입만 평가하며 "
            "실행 간 자동 전달·중단 묶음 재개는 제공하지 않습니다.",
            "불완전한 경계·취소 사용량·재시도 관계·단가는 추정하지 않고 "
            "미판정·측정 누락으로 남깁니다.",
        ],
    }
    return save_result(root, result, destination)
