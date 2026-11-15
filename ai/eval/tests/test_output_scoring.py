"""최종 채택 원문·전체 작성 입력·기존 기준·분리 저장을 실제 실행으로 검증한다."""

import asyncio
import json
from copy import deepcopy

import pytest

from eval.assessment_store import load_assessment
from eval.output_evidence import extract_output_evidence
from eval.output_scoring import score_outputs
from eval.runner import run_suite
from eval.scenarios.execution.generate import build_suite
from eval.tests.batch_fixtures import read_document
from eval.tests.test_node_scoring import Judge
from src.settings import Settings
from tests.helpers import DONE, ScriptedModel
from tests.test_reports import ReportModel

CHECKS = ["N-F.1", "N04-O.1"]


def read(path):
    return load_assessment(path) if path.is_dir() else read_document(path)


@pytest.fixture
async def request_run(tmp_path):
    suite = build_suite()
    suite["cases"] = [suite["cases"][0]]
    case = suite["cases"][0]
    model = ScriptedModel(
        [
            {"request": case["initial"]["request"], "reason": "목표 확인"},
            DONE,
            {
                "content": "행정동 단위의 자료로 개인 상태를 판정할 수 없습니다.",
                "artifact_ids": [],
                "status": "completed",
                "reason": "주어진 범위 설명",
            },
        ]
    )
    return await run_suite(
        suite, Settings(_env_file=None, langfuse_enabled=False), tmp_path, model=model
    )


async def report_run(tmp_path, *, reject=None):
    suite = build_suite()
    suite["cases"] = [suite["cases"][2]]
    return await run_suite(
        suite,
        Settings(_env_file=None, langfuse_enabled=False, max_tool_retries=20),
        tmp_path,
        model=ReportModel(reject=reject),
    )


def report_path(folder):
    return folder / read(folder / "batch.json")["runs"][0]["path"]


async def test_final_response_preserves_sources_and_complete_original_input(
    request_run,
):
    originals = {p: p.read_bytes() for p in request_run.rglob("*") if p.is_file()}
    stored = read(report_path(request_run))
    case = read(request_run / "suite.json")["cases"][0]
    expected = extract_output_evidence(stored, case)["nodes"][0]["calls"][0]
    judge = Judge()
    first = await score_outputs(
        request_run, method="all", model=judge, check_ids=CHECKS
    )
    value = read(first)
    assert value["schema_version"] == "output-evaluation-v1"
    assert value["summary"]["verdict"] == "통과"
    assert value["summary"]["complete"]
    assert len(value["assessments"]) == len(judge.calls) == 1
    assessment = value["assessments"][0]
    response, artifacts = value["runs"][0]["components"]
    assert (
        response["assessment_ids"] == artifacts["assessment_ids"] == [assessment["id"]]
    )
    assert artifacts["verdict"] == "비적용"
    assert (
        value["criteria"]["cases"][0]["assessment"]["expected"]["schema_version"]
        == "execution-expectations-v1"
    )
    assert value["criteria"]["effective_cases"][0]["assessment"]["checks"] == sorted(
        CHECKS
    )
    judged = next(
        check for check in assessment["checks"] if check["check"] == "N04-O.1"
    )["calls"][0]["judge"]
    inputs = judged["prompt"]["source_payload"]["evidence"]["inputs"]
    assert [
        item["value"] for item in inputs if item["source"] == "messages"
    ] == expected["messages"]
    assert [
        item["value"] for item in inputs if item["source"] == "response_schema"
    ] == [expected["response_schema"]]
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    assert "operational" not in value["summary"]
    assert value["judge_trace"]["counts"]["model"] == 1
    second = await score_outputs(request_run, check_ids=["N-F.1"])
    assert first != second
    assert read(first) == value
    with pytest.raises(FileExistsError):
        await score_outputs(request_run, first)


async def test_default_checks_do_not_invent_independent_answers_or_include_reviews(
    request_run,
):
    value = read(await score_outputs(request_run))
    assert value["summary"]["verdict"] == "미판정"
    assert (
        "N04-O.3" not in value["criteria"]["effective_cases"][0]["assessment"]["checks"]
    )
    assert (
        value["criteria"]["effective_cases"][0]["assessment"]["expected"]["items"] == []
    )
    assert "model" not in value["judge_trace"]["counts"]
    reasons = [
        detail["reason"]
        for item in value["assessments"]
        for check in item["checks"]
        for detail in check["details"]
    ]
    assert any("LLM" in reason for reason in reasons)
    assert any("독립 기대" in reason or "선행 단계" in reason for reason in reasons)


async def test_existing_independent_scope_is_preserved_but_not_sent_as_llm_answer(
    request_run,
):
    path = request_run / "suite.json"
    suite = read(path)
    suite["cases"][0]["assessment"] = {
        "required": True,
        "checks": ["N-F.1", "N04-O.1", "N04-O.2"],
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [
                {
                    "id": "no-artifacts",
                    "check": "N04-O.2",
                    "node": "compose",
                    "role": "request",
                    "occurrence": 1,
                    "call": "Composition",
                    "call_index": 1,
                    "path": "/artifact_ids",
                    "value": [],
                    "inputs": [{"source": "messages", "path": "/0"}],
                },
                {
                    "id": "legacy-answer",
                    "check": "N04-O.1",
                    "value": "DO-NOT-SEND-GOLD",
                },
                {
                    "id": "other-call",
                    "check": "N04-O.2",
                    "node": "compose",
                    "occurrence": 2,
                    "path": "/artifact_ids",
                    "value": ["old"],
                },
            ],
        },
        "reference": {"N04-O.1": "DO-NOT-SEND-REFERENCE"},
    }
    path.write_text(json.dumps(suite, ensure_ascii=False), encoding="utf-8")
    judge = Judge()
    value = read(
        await score_outputs(
            request_run, method="all", model=judge, check_ids=[*CHECKS, "N04-O.2"]
        )
    )
    assert value["summary"]["verdict"] == "통과"
    prepared = value["criteria"]["call_cases"][0]["assessment"]
    assert {item["id"] for item in prepared["expected"]["items"]} == {
        "no-artifacts",
        "legacy-answer",
    }
    assert prepared["reference"]["N04-O.1"] == "DO-NOT-SEND-REFERENCE"
    assert "DO-NOT-SEND" not in str(judge.calls)
    assert value["provenance"][0]["case_criteria"] == "changed"


async def test_missing_planned_repeat_is_not_hidden_by_final_output_selection(
    request_run,
):
    path = request_run / "batch.json"
    batch = read(path)
    batch["plan"]["repeat"] = batch["planned_runs"] = 2
    path.write_text(json.dumps(batch), encoding="utf-8")
    value = read(await score_outputs(request_run, check_ids=["N-F.1"]))
    assert len(value["runs"]) == value["summary"]["planned_runs"] == 2
    assert [run["verdict"] for run in value["runs"]] == ["통과", "미판정"]
    assert value["summary"]["complete"] is False
    assert value["summary"]["evaluated_runs"] == 1
    assert len(value["criteria"]["call_cases"]) == 1
    assert value["summary"]["checks"][0]["undetermined"] == 0
    assert value["summary"]["checks"][0]["unexecuted"] == 0


async def test_unlinked_final_output_never_calls_quality_model(request_run):
    path = report_path(request_run)
    report = read(path)
    report["state"]["response"]["content"] = "변경된 최종 본문"
    boundary = next(
        span for span in report["trace"]["spans"] if span["kind"] == "execution"
    )
    boundary["output"]["state"] = deepcopy(report["state"])
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    judge = Judge()
    value = read(
        await score_outputs(request_run, method="all", model=judge, check_ids=CHECKS)
    )
    assert judge.calls == []
    assert value["summary"]["verdict"] == "미판정"
    assert not value["summary"]["complete"]
    assert value["summary"]["failed"] == 0


async def test_missing_saved_schema_keeps_original_input_without_reconstruction(
    request_run,
):
    path = report_path(request_run)
    report = read(path)
    compose = next(
        span
        for span in report["trace"]["spans"]
        if span["kind"] == "node" and span["name"] == "compose"
    )
    model = next(
        span
        for span in report["trace"]["spans"]
        if span["kind"] == "model" and span["parent_id"] == compose["id"]
    )
    model["input"].pop("response_schema", None)
    messages = deepcopy(model["input"]["messages"])
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    original = path.read_bytes()
    judge = Judge()
    value = read(
        await score_outputs(request_run, method="all", model=judge, check_ids=CHECKS)
    )
    assert len(judge.calls) == 1
    assert value["summary"]["verdict"] == "통과"
    judged = next(
        check
        for check in value["assessments"][0]["checks"]
        if check["check"] == "N04-O.1"
    )["calls"][0]["judge"]
    inputs = judged["prompt"]["source_payload"]["evidence"]["inputs"]
    assert [item["value"] for item in inputs] == messages
    assert all(item["source"] == "messages" for item in inputs)
    assert path.read_bytes() == original


async def test_adopted_report_sections_reach_llm_after_length_check_and_skip_old_drafts(
    tmp_path,
):
    folder = await report_run(tmp_path, reject={"EmbedDetailV01": 1})
    report = read(report_path(folder))
    assert report["state"]["execution"]["status"] == "completed"
    judge = Judge()
    value = read(
        await score_outputs(folder, method="all", model=judge, check_ids=CHECKS)
    )
    assert value["summary"]["verdict"] == "통과", value["runs"]
    assert len(value["assessments"]) == len(judge.calls) == 5
    assert (
        len({(item["node_id"], item["call_id"]) for item in value["assessments"]}) == 5
    )
    excluded = {item["call_id"] for item in value["runs"][0]["excluded_calls"]}
    assert excluded
    assert not excluded & {item["call_id"] for item in value["assessments"]}
    lengths = [
        detail
        for item in value["assessments"]
        for check in item["checks"]
        if check["check"] == "N-F.1"
        for detail in check["details"]
        if detail["id"] == "length"
    ]
    assert len(lengths) == 4 and all(item["verdict"] == "통과" for item in lengths)
    observed = [
        item["format_observation"]
        for item in value["criteria"]["call_cases"]
        if item["format_observation"]
    ]
    assert len(observed) == 4
    assert all(
        item["completed"] is True and item["paths"] and item["result_ids"]
        for item in observed
    )


async def test_partial_report_applies_length_to_returned_approved_sections(tmp_path):
    folder = await report_run(tmp_path, reject={"EmbedDetailV01": 4})
    assert read(report_path(folder))["state"]["execution"]["status"] == "partial"
    judge = Judge()
    value = read(
        await score_outputs(folder, method="all", model=judge, check_ids=CHECKS)
    )
    sections = [
        item
        for item in value["assessments"]
        if item["role"] in {"report_description", "report_insight"}
    ]
    assert sections
    assert all(item["verdict"] == "통과" for item in sections)
    assert len(judge.calls) == len(value["assessments"])
    assert all(
        item["assessment"]["reference"]["N-F.1"]["format"]["completed"]
        for item in value["criteria"]["call_cases"]
        if item["format_observation"]
    )


@pytest.mark.parametrize("expectation_kind", ["node", "absent", "execution"])
async def test_conflicting_explicit_completion_condition_is_preserved_and_held(
    tmp_path,
    expectation_kind,
):
    folder = await report_run(tmp_path)
    path = folder / "suite.json"
    suite = read(path)
    assessment = {
        "checks": CHECKS,
        "reference": {"N-F.1": {"format": {"completed": False}}},
        "tolerance": {"N-F.1": {"absolute": 0}},
    }
    if expectation_kind == "node":
        assessment["expected"] = {"schema_version": "node-expectations-v1", "items": []}
    elif expectation_kind == "execution":
        assessment["checks"] = suite["cases"][0]["assessment"]["checks"]
        assessment["expected"] = suite["cases"][0]["assessment"]["expected"]
    suite["cases"][0]["assessment"] = assessment
    path.write_text(json.dumps(suite), encoding="utf-8")
    judge = Judge()
    value = read(
        await score_outputs(folder, method="all", model=judge, check_ids=CHECKS)
    )
    sections = [
        item
        for item in value["assessments"]
        if item["role"] in {"report_description", "report_insight"}
    ]
    assert sections and all(item["verdict"] == "미판정" for item in sections)
    assert len(judge.calls) == 1  # 선정 작성만 분량 조건과 무관하게 평가한다.
    assert all(
        item["assessment"]["reference"]["N-F.1"]["format"]["completed"] is False
        for item in value["criteria"]["call_cases"]
    )
    assert all(
        item["assessment"]["tolerance"] == assessment["tolerance"]
        for item in value["criteria"]["call_cases"]
    )
    observations = [
        item["format_observation"]
        for item in value["criteria"]["call_cases"]
        if item["format_observation"]
    ]
    assert len(observations) == 4
    assert all(
        item["status"] == "undetermined"
        and any("상충" in reason for reason in item["reasons"])
        and item["paths"]
        for item in observations
    )


async def test_explicit_reuse_requires_identical_scope_and_default_rejudges(
    request_run,
):
    first_judge = Judge()
    first = await score_outputs(
        request_run,
        method="all",
        model=first_judge,
        judge_model="test",
        check_ids=CHECKS,
    )
    reused_judge = Judge()
    reused = read(
        await score_outputs(
            request_run,
            method="all",
            model=reused_judge,
            judge_model="test",
            check_ids=CHECKS,
            reuse=first,
        )
    )
    assert reused["reuse"]["compatible"] and reused["reuse"]["reused_count"] == 1
    assert reused_judge.calls == []
    assert reused["assessments"] == read(first)["assessments"]
    different = read(
        await score_outputs(
            request_run,
            method="all",
            model=Judge(),
            judge_model="changed",
            check_ids=CHECKS,
            reuse=first,
        )
    )
    assert not different["reuse"]["compatible"]
    assert different["reuse"]["reused_count"] == 0
    again = Judge()
    await score_outputs(
        request_run, method="all", model=again, judge_model="test", check_ids=CHECKS
    )
    assert len(again.calls) == 1


async def test_cancelled_judge_preserves_completed_and_pending_plan(request_run):
    judge = Judge(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await score_outputs(request_run, method="all", model=judge, check_ids=CHECKS)
    path = next(path for path in (request_run / "assessments").glob("*.json"))
    value = read(path)
    assert value["status"] == "cancelled"
    assert value["summary"]["verdict"] == "미판정"
    assert value["summary"]["planned_runs"] == 1
    assert value["summary"]["complete"] is False
    assert value["assessments"][0]["checks"][0]["verdict"] == "통과"


async def test_cancelled_report_retains_unstarted_known_calls_in_check_summary(
    tmp_path,
):
    folder = await report_run(tmp_path)
    judge = Judge(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await score_outputs(folder, method="all", model=judge, check_ids=CHECKS)
    path = next((folder / "assessments").glob("*.json"))
    value = read(path)
    assert value["status"] == "cancelled"
    assert len(value["criteria"]["call_cases"]) == 5
    assert len(value["assessments"]) == len(judge.calls) == 1
    assert value["summary"]["verdict"] == "미판정"
    assert value["summary"]["complete"] is False
    assert value["summary"]["planned_runs"] == 1
    checks = {item["check"]: item for item in value["summary"]["checks"]}
    assert checks["N-F.1"]["passed"] == 1
    assert checks["N-F.1"]["undetermined"] == checks["N-F.1"]["unexecuted"] == 4
    assert checks["N04-O.1"]["passed"] == 0
    assert checks["N04-O.1"]["undetermined"] == 5
    assert checks["N04-O.1"]["unexecuted"] == 4
    assert checks["N04-O.1"]["rate"] is None


@pytest.mark.parametrize(
    "options",
    [{"check_ids": ["N04-O.3"]}, {"check_ids": ["N01-O.2"]}, {"case_ids": ["missing"]}],
)
async def test_invalid_final_output_scope_is_rejected_before_judging(
    request_run, options
):
    judge = Judge()
    with pytest.raises(ValueError):
        await score_outputs(request_run, method="all", model=judge, **options)
    assert judge.calls == []
