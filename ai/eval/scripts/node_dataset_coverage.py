"""현행 JSON 검사 행과 실제 평가 기대 항목의 연결을 집계한다.

연결은 시험 범위를 설명하며 모델의 통과나 문장 의미의 정확성을 뜻하지 않는다.
과거 시험 번호·분기 태그는 현행 검사 연결의 근거로 사용하지 않는다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from eval.nodes.criteria import load_criteria, select_rows
from eval.nodes.schema import case_expectations, case_model_name

AI_ROOT = Path(__file__).resolve().parents[2]
DOC_ROOT = AI_ROOT / "eval/docs/nodes"
DOCUMENTS = ("common", "interpret", "act", "decide", "compose", "ask")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _documents() -> tuple[list[dict], list[dict], dict[str, dict]]:
    catalog = load_criteria(AI_ROOT)
    documents, rows, checks = [], [], {}
    for identifier, definition in catalog["checks"].items():
        checks[identifier] = {
            "id": identifier,
            "source": definition["source"]["path"],
            "line": definition["source"]["line"],
            "raw": definition["text"],
            "sha256": _hash(definition["text"]),
        }
        for row in definition["rows"]:
            rows.append(
                {
                    "id": row["row_id"],
                    "check": identifier,
                    "source": row["source"]["path"],
                    "line": row["source"]["line"],
                    "pointer": row["source"]["pointer"],
                    "when": row["when"],
                    "applicability": row["applicability"],
                    "raw": row["text"],
                    "sha256": _hash(row["text"]),
                }
            )
    for source, document in catalog["documents"].items():
        documents.append(
            {
                "path": source,
                "sha256": document["sha256"],
                "criterion_row_count": sum(row["source"] == source for row in rows),
                "check_ids": [
                    identifier
                    for identifier, definition in checks.items()
                    if definition["source"] == source
                ],
            }
        )
    for name in (*DOCUMENTS, "README"):
        path = DOC_ROOT / f"{name}.md"
        documents.append(
            {
                "path": path.relative_to(AI_ROOT).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "criterion_row_count": 0,
                "check_ids": [],
            }
        )
    return documents, rows, checks


def _first_call_name(case: dict) -> str:
    return case_model_name(case) or (
        "ReportSelection" if case["role"] == "report_selection" else "ReportText"
    )


def _items(case: dict) -> list[dict]:
    # 단독 노드 평가는 최초 모델 반환값만 측정한다. 뒤의 내부 검토 기대 항목을
    # 같은 사례의 검사 커버리지에 더하지 않는다.
    node = {
        "node": case["target"],
        "role": case["role"],
        "occurrence": 1,
        "calls": [{"name": _first_call_name(case), "index": 1}],
    }
    return case_expectations(case, [node])


def _contexts(case: dict, item: dict | None = None) -> list[dict]:
    """평가 기대 항목에서 호출·도구 조건을 읽는다. 경로 모의 응답은 쓰지 않는다."""
    items = _items(case)
    if not items and case.get("assessment", {}).get("required") is False:
        return []
    call = _first_call_name(case)
    if item and item.get("call", call) != call:
        return []
    names = set()
    for entry in items:
        if entry.get("applicable") is False:
            continue
        value = entry.get("value")
        if entry.get("path") == "/name" and isinstance(value, str):
            names.add(value)
        elif entry.get("path") == "" and isinstance(value, dict):
            if isinstance(value.get("name"), str):
                names.add(value["name"])
    return (
        [{"name": call, "output": {"name": name}} for name in sorted(names)]
        if names
        else [{"name": call, "output": None}]
    )


def _selected(definition: dict, case: dict, item: dict | None = None) -> set[str]:
    rows = set()
    for call in _contexts(case, item):
        selected = select_rows(
            definition,
            {"node": case["target"], "role": case["role"]},
            call,
            row_ids=[item["row_id"]] if item and item.get("row_id") else None,
        )
        if not selected["missing_context"]:
            rows.update(row["row_id"] for row in selected["rows"])
    return rows


def _trace(case_ids: list[str], sidecar: dict) -> dict:
    index = sidecar.get("case_index", {})
    usages, partial_usages = [], []
    for identity in sorted(set(case_ids)):
        entry = index.get(identity, {})
        usages.extend({"case_id": identity, **use} for use in entry.get("usages", []))
        partial_usages.extend(
            {"case_id": identity, **use} for use in entry.get("partial_usages", [])
        )
    usages.sort(key=lambda item: (item["scenario_id"], item["step_id"]))
    partial_usages.sort(key=lambda item: (item["group_id"], item["step_id"]))
    scenario_ids = sorted({usage["scenario_id"] for usage in usages})
    return {
        "scenario_ids": scenario_ids,
        "usages": usages,
        "partial_group_ids": sorted({usage["group_id"] for usage in partial_usages}),
        "partial_usages": partial_usages,
        "counts": {
            "complete_scenario_count": len(scenario_ids),
            "unique_node_case_count": len(set(case_ids)),
            "path_node_execution_count": len(usages),
        },
    }


def build_coverage(cases: list[dict], sidecar: dict | None = None) -> dict:
    """검사 행별 연결·비적용·시험 범위 밖을 분리해 양방향으로 기록한다."""
    sidecar = sidecar or {}
    cases = sorted(cases, key=lambda case: case["id"])
    documents, rows, definitions = _documents()
    catalog = load_criteria(AI_ROOT)
    candidates = {row["id"]: set() for row in rows}
    links: dict[str, list[dict[str, Any]]] = {row["id"]: [] for row in rows}
    exclusions: dict[str, list[dict]] = {row["id"]: [] for row in rows}
    gaps = []
    for case in cases:
        identity = case["id"]
        declared = set(case.get("assessment", {}).get("checks", []))
        for definition in catalog["checks"].values():
            for row_id in _selected(definition, case):
                candidates[row_id].add(identity)
        active_scope_items = _items(case)
        original_items = case.get("assessment", {}).get("expected", {}).get("items", [])
        for item_index, item in enumerate(original_items):
            if item not in active_scope_items:
                continue
            identifier = item["check"]
            definition = catalog["checks"].get(identifier)
            invalid = (
                definition is None
                or identifier not in declared
                or item.get("node", case["target"]) != case["target"]
                or item.get("role", case["role"]) != case["role"]
            )
            selected = _selected(definition, case, item) if definition else set()
            if invalid or (item.get("row_id") and not selected):
                gaps.append(
                    {
                        "kind": "invalid_reference",
                        "case_id": identity,
                        "item_id": item["id"],
                        "check": identifier,
                        "reason": "기대 항목의 검사·행·노드·역할 연결이 맞지 않는다.",
                    }
                )
                continue
            excluded = (
                definition["method"] == "규칙 기반" and item.get("applicable") is False
            )
            if not selected and definition["method"] == "LLM 기반":
                # 작성 호출에는 검토 전용 행이 적용되지 않는 등 실제 호출 범위로
                # 제외한다. 사전에 적은 비적용 답안은 근거로 삼지 않는다.
                contexts = [
                    select_rows(
                        definition,
                        {"node": case["target"], "role": case["role"]},
                        call,
                    )
                    for call in _contexts(case, item)
                ]
                if not any(context["missing_context"] for context in contexts):
                    continue
            if not selected and not excluded:
                gaps.append(
                    {
                        "kind": "missing_context",
                        "case_id": identity,
                        "item_id": item["id"],
                        "check": identifier,
                        "reason": "적용 기대 항목의 호출 조건에 맞는 검사 행이 없다.",
                    }
                )
            for row_id in sorted(selected):
                entry = {
                    "case_id": identity,
                    "item_id": item["id"],
                    "item_pointer": f"/expected/items/{item_index}",
                }
                if excluded:
                    exclusions[row_id].append({**entry, "reason": item["reason"]})
                else:
                    links[row_id].append(entry)
    for row in rows:
        row_id = row["id"]
        linked = sorted({link["case_id"] for link in links[row_id]})
        excluded = {item["case_id"] for item in exclusions[row_id]}
        missing = sorted(candidates[row_id] - set(linked) - excluded)
        status = "mapped" if linked else "uncovered" if missing else "out_of_scope"
        row.update(
            status=status,
            case_ids=linked,
            eligible_case_ids=sorted(candidates[row_id]),
            missing_expectation_case_ids=missing,
            expectation_links=links[row_id],
            not_applicable=exclusions[row_id],
            reason=(
                "해당 조건의 실제 평가 기대 항목에 연결했다."
                if linked
                else "해당 호출 조건의 사례에 적용 기대 항목이 없다."
                if missing
                else "이번 묶음에 적용 기대 항목이 필요한 호출 조건이 없다."
            ),
            **_trace(linked, sidecar),
        )
        if missing:
            gaps.append(
                {
                    "kind": "missing_expectation",
                    "row_id": row_id,
                    "case_ids": missing,
                    "reason": (
                        "호출 조건에 맞는 검사 기대 항목 또는 비적용 사유가 없다."
                    ),
                }
            )
    checks = []
    for identifier, definition in definitions.items():
        children = [row for row in rows if row["check"] == identifier]
        linked = sorted({case for row in children for case in row["case_ids"]})
        status = (
            "mapped"
            if linked
            else "uncovered"
            if any(row["status"] == "uncovered" for row in children)
            else "out_of_scope"
        )
        checks.append(
            {
                **definition,
                "row_ids": [row["id"] for row in children],
                "case_ids": linked,
                "status": status,
                **_trace(linked, sidecar),
            }
        )
    return {
        "schema_version": "node-dataset-coverage-v3",
        "dataset_scope": sidecar.get("dataset_scope"),
        "scope": (
            "현행 JSON 검사 행과 적용 기대 항목의 연결 현황이다. "
            "행 내부의 모든 상황·예외, 의미 품질, 모델 통과율을 뜻하지 않는다."
        ),
        "summary": {
            "case_count": len(cases),
            "criterion_row_count": len(rows),
            "mapped_criterion_rows": sum(row["status"] == "mapped" for row in rows),
            "uncovered_criterion_rows": sum(
                row["status"] == "uncovered" for row in rows
            ),
            "out_of_scope_criterion_rows": sum(
                row["status"] == "out_of_scope" for row in rows
            ),
            "check_count": len(checks),
            "checks_with_active_expectations": sum(
                check["status"] == "mapped" for check in checks
            ),
            **_trace([case["id"] for case in cases], sidecar)["counts"],
        },
        "documents": documents,
        "criterion_rows": rows,
        "checks": checks,
        "gaps": gaps,
        "node_cases": {
            case["id"]: {
                "criterion_row_ids": [
                    row["id"] for row in rows if case["id"] in row["case_ids"]
                ],
                "check_ids": [
                    check["id"] for check in checks if case["id"] in check["case_ids"]
                ],
                **_trace([case["id"]], sidecar),
            }
            for case in cases
        },
    }
