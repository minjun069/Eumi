"""평가 실행기의 실제 호출 경계·입력 격리·실패 증거 보존을 검증한다."""

import asyncio
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from eval.runner import load_suite, run_suite
from eval.tests.batch_fixtures import read_document
from src.execution import record
from src.settings import Settings
from src.state import create_state, report_artifact
from src.tools.query import query_data
from tests.helpers import DONE, ScriptedModel, selection
from tests.test_reports import ReportModel


@pytest.fixture
def settings():
    return Settings(_env_file=None)


@pytest.fixture
def dataset():
    return {
        "reference": {"id": "activity", "version": "test-v1"},
        "as_of": "2026-09",
        "sources": [{"label": "테스트 자료", "uri": "fixture://activity"}],
        "columns": [
            {
                "name": name,
                "kind": kind,
                "unit": unit,
                "spatial_unit": "district",
                "temporal_unit": "month",
                "denominator": "same population",
            }
            for name, kind, unit in (
                ("region", "string", "code"),
                ("value", "number", "index"),
            )
        ],
        "rows": [{"region": "A", "value": 10.0}, {"region": "B", "value": 20.0}],
    }


def initial():
    return {
        "request": {"goal": "지역별 활동 자료를 확인한다."},
        "event": "analysis_pipeline",
        "messages": [
            {"type": "human", "content": "활동 자료를 알려줘", "id": "human-1"}
        ],
    }


async def test_finalized_run_refreshes_viewer_after_original_evidence_is_saved(
    tmp_path, settings, dataset, monkeypatch
):
    from eval.viewers import catalog as viewer_catalog

    refreshed = []

    def refresh(folder):
        saved = json.loads((folder / "batch.json").read_text(encoding="utf-8"))
        assert saved["ended_at"] is not None
        assert saved["status"] == "returned"
        assert (folder / saved["runs"][0]["path"]).is_file()
        refreshed.append(folder)

    monkeypatch.setattr(viewer_catalog, "refresh_for", refresh)
    folder = await run_suite(suite(tool_case(), dataset=dataset), settings, tmp_path)
    assert refreshed == [folder]


def tool_case(case_id="query", **changes):
    return {
        "id": case_id,
        "unit": "tool",
        "target": "query_data",
        "purpose": "도구를 직접 실행한다.",
        "arguments": {"target": "activity"},
    } | changes


def node_case(target="act", **changes):
    return {
        "id": target,
        "unit": "node",
        "target": target,
        "role": "interpretation",
        "purpose": "노드 한 단계만 실행한다.",
        "initial": initial(),
    } | changes


def suite(*cases, dataset=None):
    value = {
        "schema_version": "evaluation-suite-v1",
        "id": "runner-tests",
        "cases": list(cases),
    }
    if dataset is not None:
        value["datasets"] = {"activity": dataset}
    return value


def read_json(path):
    return read_document(path)


def reports(batch_dir):
    batch = read_json(batch_dir / "batch.json")
    return [read_json(batch_dir / run["path"]) for run in batch["runs"]]


def call_records(report):
    return [item for item in report["state"]["results"] if item["decision"] == "call"]


@pytest.mark.asyncio
async def test_real_tool_uses_prepared_data_and_persists_unjudged_evidence(
    tmp_path, settings, dataset
):
    case = tool_case(
        arguments={
            "target": "activity",
            "filters": [{"field": "region", "operator": "eq", "value": "B"}],
        },
        assessment={"expected": {"intentionally": "different"}, "checks": ["T-O.1"]},
    )
    value = suite(case, dataset=dataset)
    original = deepcopy(value)
    model = ScriptedModel([])

    batch_dir = await run_suite(value, settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "returned"
    assert report["output"]["data"]["rows"] == [{"region": "B", "value": 20.0}]
    assert report["assessment"]["verdict"] == "미판정"
    assert model.inputs == []
    assert value == original
    run = read_json(batch_dir / "batch.json")["runs"][0]
    folder = (batch_dir / run["path"]).parent
    assert all(
        (folder / name).is_file()
        for name in ("report.json", "trace.jsonl", "manifest.json", "case.json")
    )
    assert (folder / "trace.jsonl").read_text(encoding="utf-8").strip()
    assert report["trace"]["coverage"]["unfinished_spans"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        tool_case(target="missing_tool"),
        tool_case(dependencies="stub"),
        tool_case(role="interpretation"),
        node_case(role="missing_role"),
        node_case(arguments={}),
        node_case(unit="selection", target="decide"),
        node_case(unit="selection", dependencies="stub"),
        node_case(model_call="draft"),
        node_case("compose", model_call="draft"),
        node_case("compose", role="report_selection", model_call="draft"),
        node_case(stubs=[{"name": "query_data", "arguments": {}, "output": {}}]),
        node_case(
            dependencies="stub",
            stubs=[
                {
                    "name": "query_data",
                    "arguments": {},
                    "output": {},
                    "error": {"code": "read_error"},
                }
            ],
        ),
    ],
)
async def test_invalid_suite_is_rejected_before_any_case_runs(
    tmp_path, settings, dataset, invalid
):
    model = ScriptedModel([])
    value = suite(tool_case("valid-first"), invalid, dataset=dataset)
    with pytest.raises(ValidationError):
        await run_suite(value, settings, tmp_path, model=model)
    assert model.inputs == []
    assert list(tmp_path.rglob("report.json")) == []


def test_loading_suite_validates_duplicate_case_ids(tmp_path):
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite(tool_case(), tool_case())), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_suite(path)


@pytest.mark.asyncio
async def test_tool_failure_is_saved_and_later_case_still_runs(
    tmp_path, settings, dataset
):
    value = suite(
        tool_case("bad-field", arguments={"target": "activity", "fields": ["absent"]}),
        tool_case("valid"),
        dataset=dataset,
    )
    batch_dir = await run_suite(value, settings, tmp_path, model=ScriptedModel([]))
    failed, succeeded = reports(batch_dir)
    assert failed["run"]["status"] == "error"
    assert failed["failure"]["code"] == "invalid_field"
    assert succeeded["run"]["status"] == "returned"
    assert succeeded["output"]["returned"] == 2
    assert all(
        report["assessment"]["verdict"] == "미판정" for report in (failed, succeeded)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event,view_key,parameters",
    [
        ("user_request", "Embed01RiskMap", {"p_city": "51110"}),
        ("analysis_pipeline", "EmbedDetailV01", {"p_detail_adm": "춘천시 후평3동"}),
    ],
)
async def test_visualization_missing_parameters_are_saved_without_defaults(
    tmp_path, settings, event, view_key, parameters
):
    complete = parameters | {"p_start": "2025-07-01", "p_end": "2025-12-01"}
    value = suite(
        *(
            tool_case(
                case_id,
                target="validate_visualization",
                initial=initial() | {"event": event},
                arguments={"view_key": view_key, "parameters": values},
            )
            for case_id, values in (
                ("missing-period", parameters),
                ("complete", complete),
            )
        )
    )
    original = deepcopy(value)
    model = ScriptedModel([])

    batch_dir = await run_suite(value, settings, tmp_path, model=model)

    rejected, accepted = reports(batch_dir)
    assert rejected["run"]["status"] == accepted["run"]["status"] == "returned"
    assert rejected["output"]["valid"] is False
    assert rejected["output"]["artifact"] is None
    assert {
        (issue["code"], issue["path"]) for issue in rejected["output"]["issues"]
    } == {
        ("missing_parameter", "parameters.p_start"),
        ("missing_parameter", "parameters.p_end"),
    }
    assert accepted["output"]["valid"] is True
    assert {
        item["name"]: item["value"]
        for item in accepted["output"]["artifact"]["data"]["parameters"]
    } == complete
    assert model.inputs == []
    assert value == original


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["compose", "ask"])
async def test_single_node_preserves_input_and_stops_before_applying_model_output(
    tmp_path, settings, target
):
    previous = record("decide", "decision", "기존 판단", output={"next": target})
    case = node_case(target, role="request")
    case["initial"]["results"] = [previous]
    case["initial"]["messages"].append(
        {"type": "ai", "content": "이전 안내", "id": "ai-previous"}
    )
    reply = {"content": "현재 응답", "reason": "테스트용 모델 응답"}
    if target == "compose":
        reply |= {"artifact_ids": [], "status": "completed"}
    model = ScriptedModel([reply])
    batch_dir = await run_suite(suite(case), settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    state = report["state"]
    assert [message["content"] for message in state["messages"]] == [
        "활동 자료를 알려줘",
        "이전 안내",
    ]
    assert state["results"] == [previous]
    assert state["response"] is None
    assert state["execution"]["budget"]["steps"]["used"] == 0
    assert state["execution"]["status"] == "queued"
    assert json.loads(report["output"]["raw"]) == reply
    assert report["run"]["evaluation_scope"] == "model_output"
    assert [
        span["name"] for span in report["trace"]["spans"] if span["kind"] == "node"
    ] == [target]
    assert len(model.inputs) == 1
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,arguments",
    [
        ("query_data", {"target": "not-registered"}),
        ("interpretation_agent", {"goal": "도구를 호출하지 않고 선택만 기록한다."}),
    ],
)
async def test_selection_never_calls_selected_dependency_or_exposes_expected_answer(
    tmp_path, settings, name, arguments
):
    sentinel = "EVALUATOR_ONLY_EXPECTATION_99117"
    case = node_case(
        unit="selection", role="request", assessment={"expected": sentinel}
    )
    model = ScriptedModel([selection(name, arguments)])
    batch_dir = await run_suite(suite(case), settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "returned"
    output = json.loads(report["output"]["raw"])
    assert output["name"] == name
    assert json.loads(output["arguments_json"]) == arguments
    assert report["state"]["results"] == []
    assert call_records(report) == []
    budget = report["state"]["execution"]["budget"]
    assert budget["tool_calls"]["used"] == budget["agent_calls"]["used"] == 0
    assert report["state"]["execution"]["status"] != "completed"
    assert sentinel not in json.dumps(report["state"], ensure_ascii=False)
    assert all(
        sentinel not in message.content
        for messages in model.inputs
        for message in messages
    )
    assert model.schemas == ["Selection"]
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
async def test_repetition_keeps_model_inputs_isolated_without_consuming_stubs(
    tmp_path, settings, dataset
):
    arguments = {"target": "activity"}
    returned = query_data(arguments, {"activity": lambda: dataset})
    case = node_case(
        dependencies="stub",
        stubs=[
            {
                "name": "query_data",
                "arguments": arguments,
                "output": returned,
                "uses": 1,
            }
        ],
    )
    value = suite(case, dataset=dataset)
    original = deepcopy(value)
    model = ScriptedModel([selection("query_data", arguments)] * 2)
    batch_dir = await run_suite(value, settings, tmp_path, model=model, repeat=2)

    first, second = reports(batch_dir)
    assert first["run"]["id"] != second["run"]["id"]
    assert (
        first["state"]["execution"]["run_id"] != second["state"]["execution"]["run_id"]
    )
    assert [first["run"]["repetition"], second["run"]["repetition"]] == [1, 2]
    for report in (first, second):
        assert report["run"]["status"] == "returned"
        assert report["fixtures"]["unexpected"] == []
        assert report["fixtures"]["unused"] == []
        assert report["fixtures"]["calls"] == []
        assert call_records(report) == []
        assert report["state"]["execution"]["budget"]["tool_calls"]["used"] == 0
        assert json.loads(report["output"]["raw"])["name"] == "query_data"
    assert value == original
    first["state"]["request"]["goal"] = "다른 요청"
    assert (
        second["state"]["request"]["goal"]
        == original["cases"][0]["initial"]["request"]["goal"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["name", "arguments"])
async def test_node_raw_selection_never_matches_or_calls_a_stub(
    tmp_path, settings, dataset, mismatch
):
    expected = {"target": "activity"}
    stub = {"name": "query_data", "arguments": expected, "output": {"returned": 99117}}
    actual = expected | {"limit": 1} if mismatch == "arguments" else expected
    if mismatch == "name":
        stub["name"] = "process_data"
    case = node_case(dependencies="stub", stubs=[stub])
    model = ScriptedModel([selection("query_data", actual)])
    batch_dir = await run_suite(
        suite(case, dataset=dataset), settings, tmp_path, model=model
    )

    (report,) = reports(batch_dir)
    assert report["fixtures"]["unexpected"] == []
    assert report["fixtures"]["unused"] == []
    assert call_records(report) == []
    assert json.loads(report["output"]["raw"])["name"] == "query_data"
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
async def test_prepared_tool_error_is_outside_node_output_collection(
    tmp_path, settings
):
    arguments = {"target": "activity"}
    case = node_case(
        dependencies="stub",
        stubs=[
            {
                "name": "query_data",
                "arguments": arguments,
                "error": {"code": "test_read_unavailable", "retryable": True},
            }
        ],
    )
    model = ScriptedModel([selection("query_data", arguments)])
    batch_dir = await run_suite(suite(case), settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    assert call_records(report) == []
    assert report["run"]["status"] == "returned"
    assert json.loads(report["output"]["raw"])["name"] == "query_data"
    assert report["failure"] is None
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
async def test_agent_uses_real_workflow_with_prepared_child_response(
    tmp_path, settings
):
    child_reply = {
        "response": {
            "id": "child-response",
            "kind": "final",
            "label": "하위 결과",
            "content": "준비된 해석 결과",
            "artifacts": [],
        },
        "results": [],
        "status": "completed",
        "error": None,
    }
    case = {
        "id": "request-agent",
        "unit": "agent",
        "target": "request",
        "purpose": "상위 흐름을 실행하고 하위 호출만 교체한다.",
        "initial": initial(),
        "dependencies": "stub",
        "stubs": [
            {
                "name": "interpretation_agent",
                "arguments": {"goal": "해석"},
                "output": child_reply,
            }
        ],
    }
    model = ScriptedModel(
        [
            {"next": "act", "reason": "하위 해석 필요"},
            selection("interpretation_agent", {"goal": "해석"}),
            DONE,
            {
                "content": "통합 응답",
                "artifact_ids": [],
                "status": "completed",
                "reason": "준비된 하위 응답 통합",
            },
        ]
    )
    batch_dir = await run_suite(suite(case), settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    assert report["state"]["response"]["content"] == "통합 응답"
    assert report["state"]["execution"]["status"] == "completed"
    (called,) = call_records(report)
    assert called["output"]["response"] == child_reply["response"]
    assert report["state"]["execution"]["budget"]["agent_calls"]["used"] == 1
    assert model.schemas == ["Decision", "Selection", "Decision", "Composition"]
    assert report["fixtures"]["unexpected"] == []
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
async def test_child_error_boundary_is_separate_from_parent_partial_return(
    tmp_path,
    settings,
):
    def child_unavailable(_messages):
        raise ConnectionError("child unavailable")

    case = {
        "id": "handled-child-error",
        "unit": "agent",
        "target": "request",
        "purpose": "하위 오류 뒤 상위의 부분 반환 경계를 보존한다.",
        "initial": initial(),
    }
    model = ScriptedModel(
        [
            {"next": "act", "reason": "해석 필요"},
            selection("interpretation_agent", {"goal": "자료 확인"}),
            child_unavailable,
            DONE,
            {
                "content": "해석을 실행하지 못해 현재 확인한 범위만 안내합니다.",
                "artifact_ids": [],
                "status": "partial",
                "reason": "하위 처리 오류",
            },
        ]
    )
    root = await run_suite(suite(case), settings, tmp_path, model=model)
    (report,) = reports(root)
    assert report["run"]["status"] == "returned"
    assert report["state"]["execution"]["status"] == "partial"
    (child,) = [s for s in report["trace"]["spans"] if s["kind"] == "agent"]
    assert child["output"]["execution"]["status"] == "failed"
    assert child["output"]["execution"]["error"]["code"] == "runtime_error"
    assert model.schemas == [
        "Decision",
        "Selection",
        "Decision",
        "Decision",
        "Composition",
    ]
    assert report["state"]["execution"]["budget"]["steps"]["used"] == 5


@pytest.mark.asyncio
async def test_cancelled_model_attempt_is_saved_before_cancellation_propagates(
    tmp_path, settings
):
    def cancel(_messages):
        raise asyncio.CancelledError

    model = ScriptedModel([cancel])
    with pytest.raises(asyncio.CancelledError):
        await run_suite(suite(node_case("compose")), settings, tmp_path, model=model)

    (batch_path,) = tmp_path.rglob("batch.json")
    (report,) = reports(batch_path.parent)
    assert report["run"]["status"] == "cancelled"
    assert read_json(batch_path)["runs"][0]["status"] == "cancelled"
    assert report["assessment"]["verdict"] == "미판정"
    assert report["trace"]["coverage"]["unfinished_spans"] == 0
    assert any(
        span.get("error", {}).get("type") == "CancelledError"
        for span in report["trace"]["spans"]
    )


@pytest.mark.asyncio
async def test_model_failure_keeps_execution_evidence_and_remains_unjudged(
    tmp_path, settings
):
    def unavailable(_messages):
        raise ConnectionError("test model unavailable")

    model = ScriptedModel([unavailable])
    batch_dir = await run_suite(
        suite(node_case("compose")), settings, tmp_path, model=model
    )

    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "error"
    assert report["state"]["execution"]["status"] == "queued"
    assert report["state"]["results"] == []
    assert report["assessment"]["verdict"] == "미판정"
    assert any(
        span.get("error", {}).get("type") == "ConnectionError"
        for span in report["trace"]["spans"]
    )
    assert report["trace"]["coverage"]["unfinished_spans"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filters", [{"unit": "tool"}, {"target": "query_data"}, {"case_ids": ["chosen"]}]
)
async def test_batch_filters_execute_only_selected_cases(
    tmp_path, settings, dataset, filters
):
    model = ScriptedModel([])
    value = suite(tool_case("chosen"), node_case("compose"), dataset=dataset)
    batch_dir = await run_suite(value, settings, tmp_path, model=model, **filters)

    (report,) = reports(batch_dir)
    assert report["run"]["case_id"] == "chosen"
    assert report["run"]["status"] == "returned"
    assert model.inputs == []
    assert read_json(batch_dir / "batch.json")["planned_runs"] == 1


@pytest.mark.asyncio
async def test_agent_question_is_saved_as_waiting_without_fabricated_answer(
    tmp_path, settings
):
    starting = initial() | {"event": "user_request"}
    case = {
        "id": "question-agent",
        "unit": "agent",
        "target": "request",
        "purpose": "질문에서 종료하고 사용자의 답을 만들어 넣지 않는다.",
        "initial": starting,
    }
    model = ScriptedModel(
        [
            {
                "request": starting["request"],
                "reason": "지역 필요",
            },
            {"next": "ask", "reason": "사용자만 제공할 정보 필요"},
            {"content": "어느 지역을 확인할까요?", "reason": "지역 확인"},
        ]
    )
    batch_dir = await run_suite(suite(case), settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "returned"
    assert report["state"]["execution"]["status"] == "waiting_input"
    assert report["state"]["response"]["kind"] == "question"
    assert [
        message["content"]
        for message in report["state"]["messages"]
        if message["type"] == "human"
    ] == ["활동 자료를 알려줘"]
    assert model.schemas == ["Interpretation", "Decision", "Question"]
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
async def test_invalid_selected_argument_is_saved_without_dependency_validation(
    tmp_path, settings
):
    expected = {"target": "activity", "limit": 1}
    actual = {"target": "activity", "limit": True}
    case = node_case(
        dependencies="stub",
        stubs=[
            {"name": "query_data", "arguments": expected, "output": {"returned": 1}}
        ],
    )
    model = ScriptedModel([selection("query_data", actual)])
    batch_dir = await run_suite(suite(case), settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "returned"
    assert report["failure"] is None
    assert report["fixtures"]["calls"] == []
    assert report["fixtures"]["unexpected"] == []
    assert report["fixtures"]["unused"] == []
    assert call_records(report) == []
    assert json.loads(json.loads(report["output"]["raw"])["arguments_json"]) == actual


@pytest.mark.asyncio
async def test_agent_cancellation_keeps_last_completed_node_results_and_budget(
    tmp_path, settings, dataset
):
    entered = asyncio.Event()

    class WaitingCompositionModel(ScriptedModel):
        def with_structured_output(self, schema, **kwargs):
            runnable = super().with_structured_output(schema, **kwargs)
            if schema["title"] != "Composition":
                return runnable

            async def invoke(messages, config):
                reply = await runnable.ainvoke(messages, config)
                entered.set()
                await asyncio.Future()
                return reply

            return RunnableLambda(invoke)

    case = {
        "id": "cancel-after-query",
        "unit": "agent",
        "target": "interpretation",
        "purpose": "작성 취소 시 앞서 끝난 조회와 판단 상태를 보존한다.",
        "initial": initial(),
    }
    model = WaitingCompositionModel(
        [
            {"next": "act", "reason": "자료 조회 필요"},
            selection("query_data", {"target": "activity"}),
            DONE,
            {
                "content": "아직 반환되지 않은 응답",
                "artifact_ids": [],
                "status": "completed",
                "reason": "작성 대기",
            },
        ]
    )
    task = asyncio.create_task(
        run_suite(suite(case, dataset=dataset), settings, tmp_path, model=model)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    (batch_path,) = tmp_path.rglob("batch.json")
    (report,) = reports(batch_path.parent)
    assert report["run"]["status"] == "cancelled"
    (called,) = call_records(report)
    assert called["outcome"] == "success"
    assert called["output"]["data"]["rows"] == dataset["rows"]
    assert report["state"]["results"][-1]["node"] == "decide"
    assert report["state"]["results"][-1]["output"]["next"] == "compose"
    budget = report["state"]["execution"]["budget"]
    assert budget["steps"]["used"] == 3
    assert budget["tool_calls"]["used"] == 1
    completed = next(
        span
        for span in reversed(report["trace"]["spans"])
        if span["kind"] == "node" and span["name"] == "decide"
    )
    assert budget == completed["output"]["applied_update"]["execution"]["budget"]
    assert model.schemas == ["Decision", "Selection", "Decision", "Composition"]
    cancelled = next(
        span
        for span in report["trace"]["spans"]
        if span["kind"] == "node" and span["name"] == "compose"
    )
    observed = cancelled["output"]["observed_state"]
    assert observed["execution"]["budget"]["steps"]["used"] == 4
    assert observed["results"] == report["state"]["results"]
    assert "applied_update" not in cancelled["output"]
    boundary = next(s for s in report["trace"]["spans"] if s["kind"] == "execution")
    assert boundary["error"]["type"] == "CancelledError"
    assert "state" not in boundary["output"]
    assert report["assessment"]["verdict"] == "미판정"


def report_suite(unit="workflow", target="report"):
    inputs = {
        "requestId": "evaluation-report",
        "month": "2025-12",
        "dongCodes": ["1168066000"],
        "dongCode": "1168066000",
    }
    starting = {
        "request": {"goal": "대치2동 2025년 12월 분석 보고서를 작성한다."},
        "event": "analysis_pipeline",
        "messages": [],
        "results": [
            record("report", "report_input", "테스트 보고서 요청", output=inputs),
            record(
                "report",
                "report_source",
                "테스트 분석 결과 시점",
                output={
                    "period_start": "2025-12-01",
                    "adm_cd10": "1168066000",
                    "updated_at": "2025-12-15T00:00:00",
                },
            ),
        ],
    }
    data = {
        "reference": {"id": "public.region_result", "version": "test-v1"},
        "as_of": "2025-12-15",
        "sources": [{"label": "테스트 점수", "uri": "fixture://scores"}],
        "columns": [
            {
                "name": "bh_score",
                "kind": "number",
                "unit": "점수",
                "spatial_unit": "행정동",
                "temporal_unit": "월",
                "denominator": "해당 없음",
            }
        ],
        "rows": [{"bh_score": 42.0}],
    }
    case = {
        "id": "report-workflow",
        "unit": unit,
        "target": target,
        "purpose": "선정·설명·검토를 거쳐 보고서 산출물을 반환한다.",
        "initial": starting,
    }
    return suite(case) | {"datasets": {"public.region_result": data}}


@pytest.mark.asyncio
async def test_report_selection_stops_before_review_state_application_and_transition(
    tmp_path,
    settings,
):
    value = report_suite("node", "compose")
    case = value["cases"][0]
    case["role"] = "report_selection"
    data = value["datasets"]["public.region_result"]
    evidence = record(
        "act",
        "call",
        "미리 확보한 관측 자료",
        action={"name": "query_data", "arguments": {"target": "public.region_result"}},
        output=query_data(
            {"target": "public.region_result"},
            {"public.region_result": lambda: deepcopy(data)},
        ),
    )
    case["initial"]["results"].append(evidence)
    upstream = deepcopy(case["initial"]["results"])
    chosen = {
        "views": [
            {
                "view_key": "EmbedDetailV01",
                "reason": "해당 동의 관측 점수와 도시 범위를 비교한다.",
                "evidence_ids": [evidence["id"]],
            }
        ],
    }
    rejection = "도시 비교의 근거가 없어 설명 범위를 다시 판단해야 합니다."
    model = ScriptedModel([chosen, {"accepted": False, "reason": rejection}])

    batch_dir = await run_suite(value, settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    state = report["state"]
    assert report["run"]["status"] == "returned"
    assert json.loads(report["output"]["raw"]) == chosen
    assert state["execution"]["status"] == "queued"
    assert state["response"] is None
    assert state["results"] == upstream
    assert model.schemas == ["ReportSelection"]
    assert [
        span["name"] for span in report["trace"]["spans"] if span["kind"] == "node"
    ] == ["compose"]
    budget = state["execution"]["budget"]
    assert budget["steps"]["used"] == 0
    assert budget["tool_calls"]["used"] == budget["agent_calls"]["used"] == 0
    assert budget["retries"]["used"] == 0
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
@pytest.mark.parametrize("dependencies", ["real", "stub"])
async def test_report_workflow_generates_reviewed_artifact_without_api_or_database(
    tmp_path, settings, dependencies
):
    value = report_suite()
    case = value["cases"][0]
    case["dependencies"] = dependencies
    if dependencies == "stub":
        data = value["datasets"]["public.region_result"]
        case["stubs"] = [
            {
                "name": "query_data",
                "arguments": {"target": "public.region_result"},
                "output": query_data(
                    {"target": "public.region_result"},
                    {"public.region_result": lambda: deepcopy(data)},
                ),
                "uses": 10,
            }
        ]
    inputs = value["cases"][0]["initial"]["results"][0]["output"]
    model = ReportModel()
    batch_dir = await run_suite(value, settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "returned"
    assert report["run"]["unit"] == "workflow"
    assert report["run"]["role"] is None
    assert report["state"]["execution"]["status"] == "completed"
    artifact = report_artifact(report["state"])
    assert artifact["adm_cd10"] == inputs["dongCode"]
    assert artifact["result_updated_at"] == "2025-12-15T00:00:00"
    assert [artifact[f"graph_{index}"] for index in range(1, 4)] == [
        "EmbedDetailV01",
        "EmbedDetailV02",
        "EmbedDetailV08",
    ]
    assert all(artifact[f"desc_{index}"] for index in range(1, 4))
    assert len(artifact["quick_insight"].splitlines()) == 3
    assert [kind for kind, _, _ in model.calls].count("ReportText") == 4
    assert [kind for kind, _, _ in model.calls].count("Verification") == 5
    assert not any(
        item["decision"] == "report_save" for item in report["state"]["results"]
    )
    assert not any(span["kind"] == "database" for span in report["trace"]["spans"])
    assert report["fixtures"]["unexpected"] == []
    if dependencies == "stub":
        assert report["fixtures"]["calls"]
        assert all(c["name"] == "query_data" for c in report["fixtures"]["calls"])
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
async def test_report_agents_execute_their_own_common_graph_and_preserve_upstream(
    tmp_path, settings
):
    previous = None
    for role, writes in (
        ("report_selection", []),
        ("report_description", ["EmbedDetailV01", "EmbedDetailV02", "EmbedDetailV08"]),
        ("report_insight", [None]),
    ):
        value = report_suite("agent", role)
        starting = value["cases"][0]["initial"]
        if previous is not None:
            starting["results"] = deepcopy(previous["results"])
            starting["response"] = deepcopy(previous["response"])
            starting["budget"] = deepcopy(previous["execution"]["budget"])
        upstream = deepcopy(starting["results"])
        before_steps = starting.get("budget", {}).get("steps", {}).get("used", 0)
        model = ReportModel()

        batch_dir = await run_suite(value, settings, tmp_path / role, model=model)

        (report,) = reports(batch_dir)
        assert report["run"]["status"] == "returned"
        assert report["run"]["role"] == role
        assert report["assessment"]["verdict"] == "미판정"
        state = report["state"]
        assert state["results"][: len(upstream)] == upstream
        nodes = [s for s in report["trace"]["spans"] if s["kind"] == "node"]
        assert nodes[0]["name"] == "decide"
        assert {"decide", "compose"} <= {s["name"] for s in nodes}
        if role == "report_selection":
            assert "act" in {s["name"] for s in nodes}
        else:
            assert not any(s["name"] == "act" for s in nodes)
        assert state["execution"]["budget"]["steps"]["used"] == (
            before_steps + len(nodes)
        )
        assert [view for kind, view, _ in model.calls if kind == "ReportText"] == writes
        assert sum(kind == "ReportSelection" for kind, _, _ in model.calls) == (
            role == "report_selection"
        )
        assert not any(r["decision"] == "report_save" for r in state["results"])
        previous = state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unit,target,change",
    [
        ("agent", "report", None),
        ("workflow", "report_selection", None),
        ("workflow", "report", "missing_source"),
        ("agent", "report_selection", "wrong_event"),
        ("agent", "report_description", "missing_source"),
        ("agent", "report_insight", "missing_input"),
        ("workflow", "report", "role"),
    ],
)
async def test_report_evaluation_validates_role_and_workflow_inputs_before_execution(
    tmp_path, settings, unit, target, change
):
    value = report_suite(unit, target)
    case = value["cases"][0]
    if change == "missing_source":
        case["initial"]["results"] = case["initial"]["results"][:1]
    elif change == "missing_input":
        case["initial"]["results"] = case["initial"]["results"][1:]
    elif change == "wrong_event":
        case["initial"]["event"] = "user_message"
    elif change == "role":
        case["role"] = "report_selection"
    model = ReportModel()
    with pytest.raises(ValidationError):
        await run_suite(value, settings, tmp_path, model=model)
    assert model.calls == []
    assert not list(tmp_path.rglob("report.json"))


@pytest.mark.asyncio
async def test_cancelled_report_workflow_preserves_completed_stage_and_shared_budget(
    tmp_path, settings
):
    writing = asyncio.Event()

    class WaitingReportModel(ReportModel):
        def with_structured_output(self, schema, **kwargs):
            runnable = super().with_structured_output(schema, **kwargs)
            if schema["title"] != "ReportText":
                return runnable

            async def wait_before_draft(messages, config):
                writing.set()
                await asyncio.Event().wait()

            return RunnableLambda(wait_before_draft)

    task = asyncio.create_task(
        run_suite(report_suite(), settings, tmp_path, model=WaitingReportModel())
    )
    await asyncio.wait_for(writing.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    (report,) = reports(next(tmp_path.glob("*/batch.json")).parent)
    assert report["run"]["status"] == "cancelled"
    state = report["state"]
    assert any(
        r["decision"] == "composition"
        and (r["action"] or {}).get("name") == "report_selection_agent"
        for r in state["results"]
    )
    assert [
        r["action"]["name"] for r in state["results"] if r["decision"] == "report_stage"
    ] == ["report_selection_agent", "report_description_agent"]
    assert state["execution"]["budget"]["steps"]["used"] >= 5
    assert state["execution"]["budget"]["tool_calls"]["used"] >= 1
    assert report["trace"]["coverage"]["unfinished_spans"] == 0
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
async def test_report_reentry_uses_provided_state_and_restarts_only_failed_role(
    tmp_path,
    settings,
):
    class FailedDescriptionModel(ReportModel):
        def with_structured_output(self, schema, **kwargs):
            runnable = super().with_structured_output(schema, **kwargs)
            if schema["title"] != "ReportText":
                return runnable

            async def unavailable(_messages, config):
                raise ConnectionError("description unavailable")

            return RunnableLambda(unavailable)

    first_dir = await run_suite(
        report_suite(), settings, tmp_path / "first", model=FailedDescriptionModel()
    )
    (first,) = reports(first_dir)
    previous = first["state"]
    assert previous["execution"]["error"] is not None
    assert any(item["decision"] == "execution_failed" for item in previous["results"])
    value = report_suite()
    case = value["cases"][0]
    case["initial"] = {
        "request": deepcopy(previous["request"]),
        "messages": deepcopy(previous["messages"]),
        "event": previous["execution"]["event"],
        "results": deepcopy(previous["results"]),
        "response": deepcopy(previous["response"]),
        "execution": deepcopy(previous["execution"]),
    }
    original_initial = deepcopy(case["initial"])
    second_dir = await run_suite(
        value, settings, tmp_path / "reentry", model=ReportModel()
    )
    (second,) = reports(second_dir)
    assert case["initial"] == original_initial
    state = second["state"]
    assert state["execution"]["status"] == "completed"
    assert state["results"][: len(previous["results"])] == previous["results"]
    roles = [s for s in second["trace"]["spans"] if s["kind"] == "agent"]
    assert [s["name"] for s in roles] == [
        "report_description_agent",
        "report_insight_agent",
    ]
    boundary = next(s for s in second["trace"]["spans"] if s["kind"] == "execution")
    supplied = boundary["input"]["initial_state"]
    assert supplied["results"] == previous["results"]
    assert supplied["execution"]["budget"] == previous["execution"]["budget"]
    assert supplied["execution"]["run_id"] != previous["execution"]["run_id"]
    assert (
        roles[0]["input"]["initial_state"]["execution"]["budget"]
        == (previous["execution"]["budget"])
    )
    nodes = [s for s in second["trace"]["spans"] if s["kind"] == "node"]
    assert state["execution"]["budget"]["steps"]["used"] == (
        previous["execution"]["budget"]["steps"]["used"] + len(nodes)
    )


@pytest.mark.asyncio
async def test_finalizing_compose_keeps_error_context_without_applying_completion(
    tmp_path, settings
):
    case = node_case("compose")
    base = create_state(
        case["initial"]["request"],
        settings,
        messages=case["initial"]["messages"],
        version="test",
        event="analysis_pipeline",
    )
    budget = deepcopy(base["execution"]["budget"])
    for name in ("steps", "tool_calls", "active_seconds"):
        budget[name]["used"] = budget[name]["limit"]
    limit_error = {"code": "execution_limit_exceeded", "cause": "테스트 일반 한도 도달"}
    case["initial"] |= {"budget": budget, "execution_error": limit_error}
    model = ScriptedModel(
        [
            {
                "content": "확보한 자료 범위에서 마무리합니다.",
                "artifact_ids": [],
                "status": "completed",
                "reason": "한도 후 종료 응답",
            }
        ]
    )
    batch_dir = await run_suite(suite(case), settings, tmp_path, model=model)

    (report,) = reports(batch_dir)
    state = report["state"]
    assert report["run"]["status"] == "returned"
    assert state["execution"]["status"] == "queued"
    assert state["execution"]["error"] == limit_error
    assert state["response"] is None
    assert json.loads(report["output"]["raw"])["status"] == "completed"
    updated = state["execution"]["budget"]
    assert all(
        updated[name] == budget[name]
        for name in ("steps", "tool_calls", "active_seconds")
    )
    assert updated == budget
    assert model.schemas == ["Composition"]
    assert report["assessment"]["verdict"] == "미판정"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,reply",
    [
        (
            "interpret",
            {
                "request": {"goal": "변경 목표"},
                "needs_input": True,
                "reason": "질문 필요",
            },
        ),
        (
            "act",
            selection("interpretation_agent", {"goal": "실행하면 안 되는 하위 호출"}),
        ),
        ("decide", {"next": "ask", "reason": "서비스에서는 compose로 보정될 선택"}),
        (
            "compose",
            {
                "content": "작성 원문",
                "artifact_ids": ["missing"],
                "status": "completed",
                "reason": "실행하면 실패할 산출물 선택",
            },
        ),
        ("ask", {"content": "어느 지역인가요?", "reason": "대상 필요"}),
    ],
)
async def test_all_node_outputs_are_preserved_without_business_state_changes(
    tmp_path, settings, target, reply
):
    model = ScriptedModel([reply])
    batch_dir = await run_suite(
        suite(node_case(target)), settings, tmp_path, model=model
    )
    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "returned"
    assert json.loads(report["output"]["raw"]) == reply
    start = next(s for s in report["trace"]["spans"] if s["kind"] == "evaluation")
    assert report["state"] == start["input"]["initial_state"]
    assert not any(
        s["kind"] in {"tool", "agent", "artifact"} for s in report["trace"]["spans"]
    )
    assert len(model.inputs) == 1


@pytest.mark.asyncio
async def test_malformed_raw_response_is_saved_without_sdk_parsed_repair(
    tmp_path, settings
):
    original = '{"next": "ask", invalid-json'

    class RawModel:
        def with_structured_output(self, _schema, **_options):
            async def invoke(_messages, config):
                return {"raw": AIMessage(original), "parsed": DONE}

            return RunnableLambda(invoke)

    batch_dir = await run_suite(
        suite(node_case("decide")), settings, tmp_path, model=RawModel()
    )
    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "returned"
    assert report["failure"] is None
    assert report["output"]["raw"] == original
    assert report["state"]["results"] == []
    span = next(s for s in report["trace"]["spans"] if s["kind"] == "model")
    assert span["output"]["sdk_response"]["content"] == original
    assert "validated" not in span["output"]


@pytest.mark.asyncio
async def test_report_review_uses_prepared_selection_and_stops_before_completion(
    tmp_path, settings
):
    value = report_suite("node", "compose")
    case = value["cases"][0]
    case.update(role="report_selection", model_call="selection_review")
    selected = record(
        "compose",
        "report_selection",
        "준비한 선정",
        action={
            "name": "select_report_views",
            "arguments": {"view_key": None, "result_ids": []},
        },
        output={"views": []},
    )
    case["initial"]["results"].append(selected)
    previous = deepcopy(case["initial"]["results"])
    verdict = {"accepted": True, "reason": "준비된 선정의 근거 확인"}
    model = ScriptedModel([verdict])
    batch_dir = await run_suite(value, settings, tmp_path, model=model)
    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "returned"
    assert model.schemas == ["Verification"]
    assert json.loads(report["output"]["raw"]) == verdict
    assert report["state"]["results"] == previous
    assert report["state"]["response"] is None
    assert report["state"]["execution"]["status"] == "queued"
    actual_input = json.loads(model.inputs[0][1].content)
    assert actual_input["results"][-1]["action"]["arguments"]["result_ids"] == [
        selected["id"]
    ]


@pytest.mark.asyncio
async def test_report_review_without_existing_target_does_not_generate_a_draft(
    tmp_path, settings
):
    value = report_suite("node", "compose")
    value["cases"][0].update(role="report_selection", model_call="selection_review")
    model = ScriptedModel([])
    batch_dir = await run_suite(value, settings, tmp_path, model=model)
    (report,) = reports(batch_dir)
    assert report["run"]["status"] == "error"
    assert model.inputs == []
    assert report["state"]["response"] is None
