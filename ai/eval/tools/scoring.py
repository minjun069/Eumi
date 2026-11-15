"""저장된 도구 실행 증거를 채점하고 별도 평가 결과를 남긴다."""

import json
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import JsonValue
from typing_extensions import TypedDict

from eval.batch_store import _report, load_batch, prepare_result, save_result
from eval.naming import korea_timestamp
from eval.provenance import code_hashes
from eval.schema import suite_adapter
from eval.tools.assessment import RunAssessment, assess_run
from eval.tools.metrics import ToolSummary, summarize_tools


class ScoredBatch(TypedDict):
    schema_version: Literal["tool-evaluation-v1"]
    id: str
    batch_id: str
    suite_id: str
    assessed_at: str
    criteria: dict[str, JsonValue]
    criteria_sha256: str
    evidence_sha256: dict[str, str]
    evaluator_sha256: dict[str, str]
    runs: list[RunAssessment]
    tools: list[ToolSummary]
    limitations: list[str]


def score_batch(folder: Path, output: Path | None = None) -> Path:
    """준비된 계획 전체를 평가한다. 실행을 재호출하거나 증거를 덮어쓰지 않는다."""
    root, suite, batch, cases, entries, hashes = load_batch(folder)
    evaluation_id, destination = prepare_result(root, batch, cases, output)
    plan = batch["plan"]
    case_ids = plan["case_ids"]
    reports = []
    assessments = []
    for case in cases:
        for repetition in range(1, plan["repeat"] + 1):
            entry = entries.get((case["id"], repetition))
            report = _report(root, entry, case, suite["id"], hashes) if entry else None
            assessment = assess_run(case, report, repetition=repetition)
            if report is None:
                reason = (
                    "실행 등록은 있으나 report.json이 누락되어 증거 확인이 불가합니다."
                    if entry
                    else "예정한 실행이 묶음에 등록되지 않았습니다"
                )
                assessment["reason"] = reason
                if entry:
                    assessment["run_id"] = entry["run_id"]
                for check in assessment["checks"]:
                    check["reason"] = reason
            else:
                reports.append(report)
            assessments.append(assessment)

    normalized = suite_adapter.dump_python(suite, mode="json")
    selected = {case["id"]: case for case in normalized["cases"]}
    criteria = {
        "suite_id": suite["id"],
        "data_source": normalized.get("data_source", "prepared"),
        "cases": [selected[case_id] for case_id in case_ids],
        "performance": normalized.get("performance", []),
        "plan": plan,
    }
    if "database_fixture" in normalized:
        criteria["database_fixture"] = normalized["database_fixture"]
    result: ScoredBatch = {
        "schema_version": "tool-evaluation-v1",
        "id": evaluation_id,
        "batch_id": batch["id"],
        "suite_id": suite["id"],
        "assessed_at": korea_timestamp(),
        "criteria": criteria,
        "criteria_sha256": sha256(
            json.dumps(
                criteria,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest(),
        "evidence_sha256": hashes,
        "evaluator_sha256": code_hashes(
            "tools/assessment.py",
            "tools/metrics.py",
            "tools/scoring.py",
            "schema.py",
            "database.py",
            "naming.py",
            "batch_store.py",
            "assessment_store.py",
            "provenance.py",
        ),
        "runs": assessments,
        "tools": summarize_tools(
            cases,
            plan["repeat"],
            assessments,
            reports,
            performance=suite.get("performance", []),
        ),
        "limitations": [
            "저장 증거를 현재 평가 코드로 판정합니다. 실제 업무를 재실행하지 않습니다.",
            "현재 suite.json 기준의 재판정이며 "
            "실행 전에 준비한 기준과 같은지는 확인하지 않습니다.",
            "채점 대상: query_data·process_data·validate_visualization. "
            "다른 단위는 범위 밖입니다.",
            "기준이나 실행 증거가 부족한 검사는 미판정으로 남깁니다.",
        ],
    }
    return save_result(root, result, destination)
