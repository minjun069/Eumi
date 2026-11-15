"""시나리오 시작 State를 실제 실행기에 연결하고 모델 응답만 대체한다."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from eval.assessment_store import load_assessment
from eval.execution.schema import COMMON_CHECKS, REPORT_CHECKS
from eval.execution.scoring import score_executions
from eval.output_scoring import score_outputs
from eval.runner import run_suite
from eval.scenario_input import load_scenario_suite
from eval.tests.test_evaluation_runner import read_json, reports
from src.execution_trace import TraceRecorder
from src.settings import Settings
from src.state import report_artifact, state_adapter
from tests.helpers import DONE, ScriptedModel, section, selection
from tests.test_reports import ReportModel

DATASET = Path(__file__).parents[2] / "eval" / "scenarios" / "nodes"
INDEX = DATASET / "scenarios.json"
ASSESSMENT_MARKER = "ASSESSMENT_ONLY_NOT_A_WORK_INSTRUCTION"
CONTENT = (
    "행동 이상 점수는 학습된 패턴과 다른 정도입니다. 개인의 고립을 확정하지 않습니다."
)


def scenario(case_id):
    return read_json(DATASET / "scenarios" / (case_id.replace("_", "-") + ".json"))


def completion(messages):
    return {
        "content": CONTENT,
        "artifact_ids": [],
        "status": "completed",
        "reason": "현재 요청과 확보한 근거에 따른 반환",
    }


def visualization_completion(messages):
    checked = next(
        item
        for item in reversed(section(messages, "작업 결과와 검증 이력"))
        if item["decision"] == "call"
        and (item["action"] or {}).get("name") == "validate_visualization"
        and item["outcome"] == "success"
    )
    assert checked["output"]["valid"] is True
    return completion(messages) | {"artifact_ids": [checked["id"]]}


def model_messages(model):
    return (
        model.inputs
        if isinstance(model, ScriptedModel)
        else [messages for _, _, messages in model.calls]
    )


def assert_scored_execution(folder, case, report, supplied, boundary, model):
    original = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    evaluated = load_assessment(score_executions(folder))
    assert all(path.read_bytes() == content for path, content in original.items())
    assert evaluated["selection"]["selected_case_ids"] == [case["id"]]
    assert evaluated["provenance"][0]["case_criteria"] == "same"
    functional = evaluated["summary"]["functional"]
    if case["target"] in {"request", "report"}:
        assert set(case["assessment"]["expected"]) == {
            "schema_version",
            "situation",
            "entry",
        }
        (assessment,) = evaluated["runs"]
        assert assessment["case_id"] == case["id"]
        assert assessment["verdict"] == "통과", assessment["checks"]
        assert assessment["complete"]
        assert [item["check"] for item in assessment["checks"]] == list(
            COMMON_CHECKS + (REPORT_CHECKS if case["unit"] == "workflow" else ())
        )
        assert functional["verdict"] == "통과"
        assert functional["complete"]
        assert functional["cases"]["denominator"] == 1
        assert evaluated["selection"]["functional_excluded"] == []
    else:
        assert evaluated["runs"] == []
        assert functional["verdict"] == "미판정"
        assert not functional["complete"]
        assert functional["checks"] == []
        assert functional["cases"]["denominator"] == 0
        (excluded,) = evaluated["selection"]["functional_excluded"]
        assert excluded["case_id"] == case["id"]
        assert excluded["reason"]
    operational = evaluated["summary"]["operational"]
    (measured,) = operational["runs"]
    assert measured["case_id"] == case["id"]
    assert measured["run_id"] == report["run"]["id"]
    assert measured["started"] and measured["ended"] and measured["returned"]
    assert measured["evidence_complete"]
    assert measured["outcome"] == measured["returned_status"] == "completed"
    assert measured["timing_scope"] == "execution"
    assert measured["elapsed_seconds"] == boundary["elapsed_seconds"]
    assert measured["elapsed_seconds"] >= 0
    for name, before in supplied["execution"]["budget"].items():
        after = report["state"]["execution"]["budget"][name]
        assert measured["budget_delta"][name] == after["used"] - before["used"]
    assert measured["model_calls"] == len(model_messages(model))
    spans = report["trace"]["spans"]
    assert measured["tool_calls"] == sum(span["kind"] == "tool" for span in spans)
    # Report role transitions are boundaries, not new child-agent calls.
    assert measured["agent_calls"] == measured["budget_delta"]["agent_calls"] == 0
    assert measured["node_entries"] == sum(span["kind"] == "node" for span in spans)
    assert measured["node_entries"] == measured["budget_delta"]["steps"]
    assert measured["retries"] == measured["budget_delta"]["retries"] == 0
    assert measured["input_tokens"] is measured["output_tokens"] is None
    assert measured["missing_token_calls"] == {
        "input_tokens": len(model_messages(model)),
        "output_tokens": len(model_messages(model)),
    }
    assert measured["cost"] is None
    assert operational["verdict"] == "미판정" and not operational["complete"]
    assert operational["goals"] == []
    (repetition,) = operational["repetitions"]
    assert repetition["planned"] == repetition["started"] == repetition["ended"] == 1
    assert repetition["missing_repetitions"] == []
    for name in ("elapsed_seconds", "model_calls", "tool_calls", "agent_calls"):
        assert repetition["measurements"][name]["sample_count"] == 1
        assert repetition["measurements"][name]["mean"] == measured[name]
    for name in ("input_tokens", "output_tokens", "cost"):
        assert repetition["measurements"][name]["sample_count"] == 0
        assert repetition["measurements"][name]["missing_count"] == 1
    assert evaluated["summary"]["report_completion"] == (
        {"numerator": 1, "denominator": 1, "rate": 1.0}
        if case["unit"] == "workflow"
        else {"numerator": 0, "denominator": 0, "rate": None}
    )


async def execute(tmp_path, case_id, model, *, unit="agent"):
    loaded = load_scenario_suite(
        INDEX,
        unit=unit,
        target="report" if unit == "workflow" else None,
        case_ids=[case_id],
    )
    suite = loaded["suite"]
    (case,) = suite["cases"]
    case.setdefault("assessment", {})["reference"] = {"marker": ASSESSMENT_MARKER}
    original = deepcopy(suite)
    files_before = {
        path.relative_to(DATASET) for path in DATASET.rglob("*") if path.is_file()
    }
    hashes_before = {
        name: sha256((DATASET / name).read_bytes()).hexdigest()
        for name in loaded["source_files_sha256"]
    }
    assert loaded["source_files_sha256"] == hashes_before
    assert case.get("dependencies", "real") == "real"
    assert "stubs" not in case
    assert set(case["initial"]) == {
        "request",
        "messages",
        "results",
        "response",
        "event",
        "execution",
    }
    # The supplied execution's limits must win over deployment defaults.
    settings = Settings(
        _env_file=None, max_steps=1, max_tool_calls=1, langfuse_enabled=False
    )
    folder = await run_suite(
        suite,
        settings,
        tmp_path,
        model=model,
        source_path=INDEX,
        source_files_sha256=loaded["source_files_sha256"],
        source_selection=loaded["selection"],
    )
    (report,) = reports(folder)
    assert suite == original
    assert report["run"]["status"] == "returned", report["failure"]
    assert report["state"]["execution"]["status"] == "completed"
    assert report["state"]["execution"]["error"] is None
    assert files_before == {
        path.relative_to(DATASET) for path in DATASET.rglob("*") if path.is_file()
    }
    assert hashes_before == {
        name: sha256((DATASET / name).read_bytes()).hexdigest()
        for name in hashes_before
    }
    assert (folder / "suite.json").is_file()
    manifest_path = next((folder / "runs").glob("*/manifest.json"))
    manifest = read_json(manifest_path)["evaluation"]
    assert manifest["source_files_sha256"] == loaded["source_files_sha256"]
    assert manifest["source_selection"] == loaded["selection"]
    boundary = next(
        span for span in report["trace"]["spans"] if span["kind"] == "execution"
    )
    supplied = boundary["input"]["initial_state"]
    source = scenario(case_id)
    expected = (
        source["entry_transition"]["before_state"]
        if unit == "workflow"
        else source["start_state"]
    )
    expected = TraceRecorder().snapshot(state_adapter.validate_python(expected))
    expected["execution"]["run_id"] = report["run"]["id"]
    assert supplied == expected
    assert report["state"]["results"][: len(expected["results"])] == expected["results"]
    prior_messages = report["state"]["messages"][: len(expected["messages"])]
    for before, after in zip(expected["messages"], prior_messages, strict=True):
        # LangGraph assigns an ID to messages that arrive without one.
        normalized = before | {"id": after["id"]} if before["id"] is None else before
        assert after == normalized
    nodes = [span for span in report["trace"]["spans"] if span["kind"] == "node"]
    assert report["state"]["execution"]["budget"]["steps"]["used"] == (
        expected["execution"]["budget"]["steps"]["used"] + len(nodes)
    )
    for name, original_budget in expected["execution"]["budget"].items():
        final_budget = report["state"]["execution"]["budget"][name]
        assert final_budget["limit"] == original_budget["limit"]
        assert final_budget["used"] >= original_budget["used"]
    for messages in model_messages(model):
        encoded = json.dumps(TraceRecorder().snapshot(messages), ensure_ascii=False)
        assert ASSESSMENT_MARKER not in encoded
        assert '"model_outputs"' not in encoded
        assert '"task_rationale"' not in encoded
        assert '"decision_basis"' not in encoded
        assert '"entry_transition"' not in encoded
    assert ASSESSMENT_MARKER not in json.dumps(report["state"], ensure_ascii=False)
    assert_scored_execution(folder, case, report, supplied, boundary, model)
    # 같은 21개 시나리오에서 만든 실행 증거를 그대로 최종 품질 평가에 전달한다.
    before_quality = {
        path: path.read_bytes()
        for path in (folder / "runs").rglob("*")
        if path.is_file()
    }
    call_count = len(model_messages(model))
    quality = load_assessment(await score_outputs(folder, check_ids=["N-F.1"]))
    assert quality["selection"]["case_ids"] == [case["id"]]
    assert (
        quality["criteria"]["cases"][0]["assessment"]
        == read_json(folder / "suite.json")["cases"][0]["assessment"]
    )
    assert quality["assessments"]
    assert all(item["node"] == "compose" for item in quality["assessments"])
    assert "model" not in quality["judge_trace"]["counts"]
    assert len(model_messages(model)) == call_count
    assert all(path.read_bytes() == raw for path, raw in before_quality.items())
    return report, supplied, nodes


@pytest.mark.asyncio
async def test_request_revision_runs_direct_composition_with_previous_conversation(
    tmp_path,
):
    case_id = "basic-request-revision"
    request = deepcopy(scenario(case_id)["start_state"]["request"])
    model = ScriptedModel(
        [{"request": request, "reason": "기존 설명 수정"}, DONE, completion]
    )

    report, supplied, nodes = await execute(tmp_path, case_id, model)

    assert [span["name"] for span in nodes] == ["interpret", "decide", "compose"]
    assert model.schemas == ["Interpretation", "Decision", "Composition"]
    assert len(supplied["messages"]) == 3
    assert report["state"]["response"]["content"] == CONTENT
    assert not any(
        span["kind"] in {"tool", "agent"} for span in report["trace"]["spans"]
    )
    assert report["state"]["execution"]["budget"]["tool_calls"]["used"] == 0
    assert report["state"]["execution"]["budget"]["agent_calls"]["used"] == 0
    first_input = json.dumps(
        TraceRecorder().snapshot(model.inputs[0]), ensure_ascii=False
    )
    assert all(message["content"] in first_input for message in supplied["messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "tool", "arguments", "compose"),
    [
        (
            "basic-interpretation-new_topic",
            "query_data",
            {
                "target": "public.region_result",
                "filters": [
                    {"field": "period_start", "operator": "eq", "value": "2025-12-01"},
                    {"field": "adm_cd10", "operator": "eq", "value": "1168065500"},
                ],
            },
            completion,
        ),
        (
            "basic-visualization-revision",
            "validate_visualization",
            {
                "view_key": "EmbedDetailMap",
                "parameters": {
                    "p_start": "2025-12-01",
                    "p_end": "2025-12-01",
                    "p_detail_adm": "강남구 도곡1동",
                },
            },
            visualization_completion,
        ),
    ],
)
async def test_specialist_continues_inherited_state_and_uses_actual_tool(
    tmp_path, case_id, tool, arguments, compose
):
    request = deepcopy(scenario(case_id)["start_state"]["request"])
    model = ScriptedModel(
        [
            {"request": request, "reason": "현재 전문 역할의 목적 확인"},
            {"next": "act", "reason": "현재 요청의 근거 또는 표시 설정 확인"},
            selection(tool, arguments),
            DONE,
            compose,
        ]
    )

    report, supplied, nodes = await execute(tmp_path, case_id, model)

    assert [span["name"] for span in nodes] == [
        "interpret",
        "decide",
        "act",
        "decide",
        "compose",
    ]
    assert supplied["execution"]["budget"]["steps"]["used"] == 3
    assert supplied["execution"]["budget"]["agent_calls"]["used"] == 1
    assert report["state"]["execution"]["budget"]["steps"]["used"] == 8
    assert report["state"]["execution"]["budget"]["agent_calls"]["used"] == 1
    assert report["state"]["execution"]["budget"]["tool_calls"]["used"] == 1
    calls = [item for item in report["state"]["results"] if item["decision"] == "call"]
    assert len(calls) == 1
    assert calls[0]["action"] == {"name": tool, "arguments": arguments}
    assert calls[0]["outcome"] == "success"
    assert any(span["kind"] == "tool" for span in report["trace"]["spans"])
    assert not any(span["kind"] == "agent" for span in report["trace"]["spans"])
    if tool == "query_data":
        rows = calls[0]["output"]["data"]["rows"]
        assert rows
        assert all(row["period_start"] == "2025-12-01" for row in rows)
        assert all(row["adm_cd10"] == "1168065500" for row in rows)
    else:
        (artifact,) = report["state"]["response"]["artifacts"]
        assert artifact["type"] == "tableau"
        assert artifact["data"]["view_key"] == "EmbedDetailMap"
        assert artifact["data"]["validation_scope"] == "registered_configuration"


@pytest.mark.asyncio
async def test_report_description_reuses_approved_selection_without_restarting_it(
    tmp_path,
):
    case_id = "basic-report_description-1168065500"
    model = ReportModel()

    report, supplied, nodes = await execute(tmp_path, case_id, model)

    assert [span["name"] for span in nodes] == ["decide", "compose"]
    assert [kind for kind, _, _ in model.calls] == [
        "Decision",
        "ReportText",
        "Verification",
        "ReportText",
        "Verification",
        "ReportText",
        "Verification",
    ]
    assert supplied["execution"]["budget"]["steps"]["used"] == 8
    assert supplied["execution"]["budget"]["tool_calls"]["used"] == 3
    assert report["state"]["execution"]["budget"]["steps"]["used"] == 10
    assert report["state"]["execution"]["budget"]["tool_calls"]["used"] == 3
    assert not any(
        span["kind"] in {"tool", "agent"} for span in report["trace"]["spans"]
    )
    added = report["state"]["results"][len(supplied["results"]) :]
    assert any(
        item["decision"] == "composition"
        and item["action"]["name"] == "report_description_agent"
        for item in added
    )
    assert not any(
        artifact["type"] == "analysis_report"
        for artifact in report["state"]["response"]["artifacts"]
    )
    approved = {
        item["action"]["arguments"]["result_ids"][0]
        for item in supplied["results"]
        if item["decision"] == "verification" and item["output"]["accepted"]
    }
    first_draft_context = json.loads(model.calls[1][2][1].content)
    assert approved <= {item["id"] for item in first_draft_context["results"]}


@pytest.mark.asyncio
async def test_report_workflow_starts_before_selection_and_runs_all_three_roles(
    tmp_path,
):
    case_id = "basic-report_selection-1168065500"
    model = ReportModel()

    report, supplied, nodes = await execute(tmp_path, case_id, model, unit="workflow")

    assert [item["decision"] for item in supplied["results"]] == [
        "report_input",
        "report_source",
    ]
    assert supplied["messages"] == []
    roles = [span for span in report["trace"]["spans"] if span["kind"] == "agent"]
    names = [
        "report_selection_agent",
        "report_description_agent",
        "report_insight_agent",
    ]
    assert [span["name"] for span in roles] == names
    stages = [
        item
        for item in report["state"]["results"]
        if item["decision"] == "report_stage"
    ]
    assert [item["action"]["name"] for item in stages] == names
    assert len(nodes) == 8
    # This test model chooses one real query; fixture paths contain three.
    assert sum(kind == "Selection" for kind, _, _ in model.calls) == 1
    assert report["state"]["execution"]["budget"]["tool_calls"]["used"] == 1
    row = report_artifact(report["state"])
    assert row["period_start"] == "2025-12-01"
    assert row["adm_cd10"] == "1168065500"
    assert all(row[name] for name in ("desc_1", "desc_2", "desc_3", "quick_insight"))
    for previous, following in zip(roles, roles[1:], strict=False):
        before = following["input"]["initial_state"]
        returned = previous["output"]
        assert before["execution"]["budget"] == returned["execution"]["budget"]
        assert before["results"][:-1] == returned["results"]
        assert before["messages"] == returned["messages"]
