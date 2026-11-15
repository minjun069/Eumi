"""실제 서비스 실행에서 채택된 최종 작성본만 원문에 연결한다."""

import asyncio
import json
from copy import deepcopy

import pytest

from eval.nodes.evidence import extract_nodes
from eval.output_evidence import extract_output_evidence
from eval.runner import run_suite
from eval.scenarios.execution.generate import build_suite
from eval.tests.test_evaluation_runner import reports
from src.settings import Settings
from tests.helpers import DONE, ScriptedModel, composition, selection
from tests.test_reports import ReportModel


def calls(evidence):
    return [call for node in evidence["nodes"] for call in node["calls"]]


def change_final(report, change):
    value = deepcopy(report)
    change(value["state"])
    boundary = next(
        span for span in value["trace"]["spans"] if span["kind"] == "execution"
    )
    boundary["output"]["state"] = deepcopy(value["state"])
    return value


@pytest.fixture(scope="module")
def executions(tmp_path_factory):
    async def execute_all():
        source = build_suite()
        results = {}
        root = tmp_path_factory.mktemp("output-evidence")

        async def run(key, case, model):
            case = deepcopy(case)
            case["id"] = key
            suite = {**source, "id": "output-" + key, "cases": [case]}
            folder = await run_suite(
                suite,
                Settings(_env_file=None, langfuse_enabled=False, max_tool_retries=20),
                root,
                model=model,
            )
            (report,) = reports(folder)
            assert report["run"]["status"] == "returned", report["failure"]
            results[key] = report, case
            return report

        user = source["cases"][0]
        answer = {
            "content": "지역 수준의 자료이며 개인 상태를 판단할 수 없습니다.",
            "artifact_ids": [],
            "status": "completed",
            "reason": "요청 범위 설명",
        }
        for role in ("request", "interpretation", "visualization"):
            case = deepcopy(user)
            case["target"] = role
            case.pop("assessment", None)
            await run(
                role,
                case,
                ScriptedModel(
                    [
                        {"request": case["initial"]["request"], "reason": "목표 확인"},
                        DONE,
                        answer,
                    ]
                ),
            )
        data_case = deepcopy(user)
        data_case.update(target="interpretation", providers=["public.region_result"])
        data_case.pop("assessment", None)
        await run(
            "table",
            data_case,
            ScriptedModel(
                [
                    {"request": data_case["initial"]["request"], "reason": "목표 확인"},
                    {"next": "act", "reason": "수치 조회"},
                    selection("query_data", {"target": "public.region_result"}),
                    DONE,
                    composition,
                ]
            ),
        )
        workflow = await run(
            "workflow", source["cases"][2], ReportModel(reject={"EmbedDetailV01": 1})
        )
        await run(
            "partial", source["cases"][2], ReportModel(reject={"EmbedDetailV01": 4})
        )
        await run("reentry", source["cases"][3], ReportModel())
        for role in ("report_selection", "report_description", "report_insight"):
            entered = next(
                span["input"]["initial_state"]
                for span in workflow["trace"]["spans"]
                if span["kind"] == "agent" and span["name"] == role + "_agent"
            )
            initial = {
                key: deepcopy(entered[key])
                for key in ("request", "messages", "results", "response", "execution")
            }
            initial["event"] = entered["execution"]["event"]
            case = {
                "id": role,
                "unit": "agent",
                "target": role,
                "purpose": "역할 단독 반환",
                "initial": initial,
            }
            await run(role, case, ReportModel())
        return results

    return asyncio.run(execute_all())


@pytest.mark.parametrize("role", ["request", "interpretation", "visualization"])
def test_general_final_content_uses_its_actual_composition_call(executions, role):
    report, case = executions[role]
    original = deepcopy(report)
    evidence = extract_output_evidence(report, case)
    assert report == original
    assert evidence["status"] == "returned"
    assert evidence["issues"] == []
    assert [call["name"] for call in calls(evidence)] == ["Composition"]
    assert evidence["components"][0]["value"] == report["state"]["response"]["content"]
    assert evidence["components"][1]["kind"] == "artifacts"
    assert evidence["components"][1]["node"] is None
    assert all(item["link_status"] == "matched" for item in evidence["components"])


def test_actual_rendered_artifacts_are_separate_from_selected_model_ids(executions):
    report, case = executions["table"]
    evidence = extract_output_evidence(report, case)
    artifact = next(
        item for item in evidence["components"] if item["kind"] == "artifacts"
    )
    assert {item["type"] for item in artifact["value"]} == {"table", "data"}
    assert artifact["node"] is None and artifact["link_status"] == "matched"
    assert calls(evidence)[0]["output"]["artifact_ids"]
    changed = change_final(report, lambda state: state["response"]["artifacts"].clear())
    evidence = extract_output_evidence(changed, case)
    assert evidence["components"][1]["link_status"] == "mismatch"
    assert len(calls(evidence)) == 1  # 본문 원문의 품질과 공개 산출물 누락은 분리한다.


def test_workflow_keeps_only_approved_final_writers_with_original_call_indices(
    executions,
):
    report, case = executions["workflow"]
    evidence = extract_output_evidence(report, case)
    assert evidence["issues"] == []
    assert len(evidence["components"]) == 5
    assert [call["name"] for call in calls(evidence)].count("ReportSelection") == 1
    assert [call["name"] for call in calls(evidence)].count("ReportText") == 4
    original_calls = {
        call["id"]: call
        for node in extract_nodes(report, case)
        for call in node["calls"]
    }
    assert all(call == original_calls[call["id"]] for call in calls(evidence))
    assert any(call["index"] > 1 for call in calls(evidence))
    excluded = {item["call_id"] for item in evidence["excluded_calls"]}
    assert all(
        call["id"] in excluded
        for call in original_calls.values()
        if call["name"] == "Verification"
    )
    drafts = [
        item
        for item in report["state"]["results"]
        if item["decision"] == "report_draft"
        and item["action"]["arguments"]["view_key"] == "EmbedDetailV01"
    ]
    assert len(drafts) == 2
    chosen_ids = {item["result_id"] for item in evidence["components"]}
    assert drafts[-1]["id"] in chosen_ids and drafts[0]["id"] not in chosen_ids
    assert any(original_calls[key]["name"] == "ReportText" for key in excluded)


@pytest.mark.parametrize(
    "role,count",
    [("report_selection", 1), ("report_description", 3), ("report_insight", 1)],
)
def test_standalone_report_role_does_not_score_approved_upstream_content(
    executions, role, count
):
    report, case = executions[role]
    evidence = extract_output_evidence(report, case)
    assert evidence["issues"] == []
    assert len(calls(evidence)) == count
    assert {node["role"] for node in evidence["nodes"]} == {role}
    assert {item["kind"] for item in evidence["components"]} == {role}
    changed = change_final(
        report, lambda state: state["response"].update(content="변경된 최종 반환")
    )
    altered = extract_output_evidence(changed, case)
    assert altered["nodes"] == []
    assert all(item["link_status"] == "mismatch" for item in altered["components"])
    assert all(
        check["status"] != "matched"
        for check in altered["connection_checks"]
        if check["id"].startswith(role)
    )


def test_partial_report_scores_only_returned_approved_components(executions):
    report, case = executions["partial"]
    assert report["state"]["execution"]["status"] == "partial"
    evidence = extract_output_evidence(report, case)
    assert evidence["issues"] == []
    assert len(evidence["components"]) == 4
    assert "report.description.1" not in {item["id"] for item in evidence["components"]}
    assert len(calls(evidence)) == 4


def test_reentry_preserves_missing_origin_of_preexisting_approved_selection(executions):
    report, case = executions["reentry"]
    evidence = extract_output_evidence(report, case)
    chosen = next(
        item for item in evidence["components"] if item["kind"] == "report_selection"
    )
    assert chosen["node"] is None and chosen["link_status"] == "missing"
    assert len(calls(evidence)) == 2
    assert all(call["name"] == "ReportText" for call in calls(evidence))


def test_identical_report_text_requires_its_actual_pending_record_input(executions):
    report, case = deepcopy(executions["workflow"])
    original = extract_output_evidence(report, case)
    part = next(
        item for item in original["components"] if item["id"] == "report.description.1"
    )
    call_id = part["node"]["calls"][0]["id"]
    span = next(span for span in report["trace"]["spans"] if span["id"] == call_id)
    message = span["input"]["messages"][-1]
    payload = json.loads(message["content"])
    assert payload["results"][-1]["id"] == part["result_id"]
    payload["results"][-1]["id"] = "different-writer-record"
    message["content"] = json.dumps(payload, ensure_ascii=False)
    evidence = extract_output_evidence(report, case)
    changed = next(item for item in evidence["components"] if item["id"] == part["id"])
    assert changed["node"] is None and changed["link_status"] == "missing"
    assert len(calls(evidence)) == 4


@pytest.mark.parametrize("status", ["cancelled", "error", "running"])
def test_nonreturned_execution_never_scores_its_previous_response(executions, status):
    report, case = deepcopy(executions["request"])
    report["run"]["status"] = status
    evidence = extract_output_evidence(report, case)
    assert evidence["status"] == "not_returned"
    assert (
        evidence["response"] is None
        and evidence["nodes"] == evidence["components"] == []
    )


@pytest.mark.parametrize("change", ["missing", "unfinished", "conflict"])
def test_missing_or_conflicting_return_boundary_does_not_use_report_state(
    executions, change
):
    report, case = deepcopy(executions["request"])
    boundary = next(
        span for span in report["trace"]["spans"] if span["kind"] == "execution"
    )
    if change == "missing":
        report["trace"]["spans"].remove(boundary)
    elif change == "unfinished":
        boundary["ended_at"] = None
    else:
        report["state"]["response"]["content"] = "변경"
    evidence = extract_output_evidence(report, case)
    assert evidence["status"] == "unknown" and evidence["nodes"] == []


def test_mutated_final_content_or_missing_model_raw_cannot_reuse_content_verdict(
    executions,
):
    report, case = executions["request"]
    changed = change_final(
        report, lambda state: state["response"].update(content="원문과 다른 반환")
    )
    evidence = extract_output_evidence(changed, case)
    assert evidence["components"][0]["link_status"] == "mismatch"
    assert evidence["nodes"] == []
    changed = deepcopy(report)
    model = next(
        span
        for span in changed["trace"]["spans"]
        if span["kind"] == "model" and span["name"] == "Composition"
    )
    model["output"] = {}
    evidence = extract_output_evidence(changed, case)
    assert evidence["components"][0]["link_status"] == "missing"
    assert evidence["nodes"] == []


@pytest.mark.parametrize("field", ["desc_1", "graph_1", "quick_insight"])
def test_report_output_mutation_excludes_the_affected_original_writer(
    executions, field
):
    report, case = executions["workflow"]
    changed = change_final(
        report,
        lambda state: state["response"]["artifacts"][0]["data"].update({field: None}),
    )
    evidence = extract_output_evidence(changed, case)
    altered = [
        item for item in evidence["components"] if item["link_status"] == "mismatch"
    ]
    assert altered and all(item["node"] is None for item in altered)
    assert len(calls(evidence)) < 5


def test_question_return_has_no_composition_target_and_missing_report_is_explicit(
    executions,
):
    report, case = executions["request"]
    changed = change_final(
        report, lambda state: state["response"].update(kind="question")
    )
    evidence = extract_output_evidence(changed, case)
    assert evidence["status"] == "returned" and evidence["nodes"] == []
    assert evidence["issues"]
    missing = extract_output_evidence(None, case)
    assert missing["status"] == "unknown" and missing["issues"]


@pytest.mark.parametrize(
    "change",
    ["node_output", "node_before", "duplicate_model", "invalid_report_selection"],
)
def test_damaged_trace_or_approval_records_hold_quality_instead_of_crashing(
    executions, change
):
    key = "workflow" if change == "invalid_report_selection" else "request"
    report, case = deepcopy(executions[key])
    if change == "invalid_report_selection":

        def break_selection(state):
            record = next(
                item
                for item in state["results"]
                if item["decision"] == "report_selection"
            )
            record["output"]["views"] = [None]

        report = change_final(report, break_selection)
    else:
        node = next(
            span
            for span in report["trace"]["spans"]
            if span["kind"] == "node" and span["name"] == "compose"
        )
        if change == "node_output":
            node["output"] = []
        elif change == "node_before":
            node["input"]["state"]["results"] = 3
        else:
            model = next(
                span
                for span in report["trace"]["spans"]
                if span["kind"] == "model" and span["name"] == "Composition"
            )
            report["trace"]["spans"].append({**model, "name": "ConflictingComposition"})
    evidence = extract_output_evidence(report, case)
    assert evidence["nodes"] == [] and evidence["issues"]
