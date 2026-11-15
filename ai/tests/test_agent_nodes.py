"""실제 업무 노드의 호출·재개·결과 보존을 검증한다."""

from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from experiments.scenario_fixtures import CATALOG, PROVIDERS
from src.agent_nodes import (
    build_nodes,
    finish,
    record,
    select_artifacts,
)
from src.exceptions import ToolFailure
from src.execution import accepted_outputs
from src.graph import compile_graph
from src.state import state_adapter
from src.tools.tableau import validate_visualization
from tests.helpers import DONE, ScriptedModel, composition, initial, section, selection

pytestmark = pytest.mark.usefixtures("all_tableau_views")


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["user_request", "analysis_pipeline"])
async def test_sufficient_existing_chart_goes_directly_to_composition(event):
    state = initial(event)
    artifact = validate_visualization(
        {
            "view_key": "Embed01VulnerabilityMap",
            "parameters": {
                "p_city": "51110",
                "p_start": "2025-07-01",
                "p_end": "2025-12-01",
            },
        },
        state=state,
    )["artifact"]
    state["request"]["goal"] = "기존 차트의 표시 조건만 설명해줘"
    state["response"] = {
        "id": "previous-chart",
        "kind": "final",
        "label": "기존 차트",
        "content": "춘천시의 2025년 7월~12월 표시 조건입니다.",
        "artifacts": [artifact],
    }
    replies = (
        [{"request": state["request"], "reason": "기존 표시 조건 설명 요청"}]
        if event == "user_request"
        else []
    )
    model = ScriptedModel(
        [
            *replies,
            {"next": "compose", "reason": "기존 산출물에 설명할 표시 조건이 있다."},
            {
                "content": state["response"]["content"],
                "artifact_ids": ["previous"],
                "status": "completed",
                "reason": "확인된 표시 조건 설명",
            },
        ]
    )
    graph = compile_graph(build_nodes(model, {}, [], role="request"), finish=finish)
    result = await graph.ainvoke(state, {})
    assert result["execution"]["status"] == "completed"
    assert model.schemas == (
        ["Interpretation", "Decision", "Composition"]
        if event == "user_request"
        else ["Decision", "Composition"]
    )
    assert result["response"]["artifacts"] == [artifact]
    assert not any(item["node"] == "act" for item in result["results"])
    for resource in ("tool_calls", "agent_calls"):
        assert result["execution"]["budget"][resource]["used"] == 0


@pytest.mark.asyncio
async def test_restored_selection_receives_latest_progress_decision():
    state = initial()
    state["results"].append(
        record(
            "decide",
            "decision",
            "이전 판단",
            output={"next": "compose", "reason": "이전 판단"},
        )
    )
    need = "지역별 전체 가구 수와 독거가구 수가 필요하다."
    nodes = build_nodes(
        ScriptedModel([{"next": "act", "reason": need}]),
        PROVIDERS,
        CATALOG,
        role="interpretation",
    )
    decided = deepcopy(state)
    command = await nodes["decide"](decided, {})
    decided["results"].extend(command.update["results"])
    target = command.goto
    assert target == "act"
    restored = state_adapter.validate_json(state_adapter.dump_json(decided))

    def choose(messages):
        decision = section(messages, "이번 작업의 진행 판단")
        assert len(decision) == 1
        assert decision[0]["id"] == decided["results"][-1]["id"]
        assert decision[0]["output"] == {"next": "act", "reason": need}
        return selection("query_data", {"target": "D3"})

    nodes = build_nodes(
        ScriptedModel([choose]), PROVIDERS, CATALOG, role="interpretation"
    )
    executed = deepcopy(restored)
    command = await nodes["act"](executed, {})
    target = command.goto
    assert target == "decide"
    assert executed["results"][: len(decided["results"])] == decided["results"]
    assert executed["results"][-1]["outcome"] == "success"
    assert executed["results"][-1]["action"]["name"] == "query_data"


@pytest.mark.parametrize(
    "role,name",
    [
        ("report", "validate_visualization"),
        ("interpretation", "visualization_agent"),
        ("request", "none"),
    ],
)
@pytest.mark.asyncio
async def test_disallowed_selection_fails_before_work_and_preserves_results(role, name):
    state = initial()
    previous = record("act", "call", "이전 자료", output={"data": {"rows": []}})
    state["results"].append(previous)
    model = ScriptedModel(
        [
            {"next": "act", "reason": "자료 확보 필요"},
            selection(name, {"goal": "허용되지 않은 작업"}),
        ]
    )
    graph = compile_graph(
        build_nodes(model, PROVIDERS, CATALOG, role=role), finish=finish
    )
    result = await graph.ainvoke(state, {})
    assert result["results"][0] == previous
    failure = result["results"][-1]
    assert failure["decision"] == "execution_failed"
    assert failure["output"]["error_type"] == "ValidationError"
    assert len([r for r in result["results"] if r["decision"] == "call"]) == 1
    assert result["execution"]["budget"]["agent_calls"]["used"] == 0
    assert result["execution"]["budget"]["tool_calls"]["used"] == 0
    assert model.schemas == ["Decision", "Selection"]


@pytest.mark.parametrize("target,status", [("D3", "partial"), ("unknown", "failed")])
@pytest.mark.asyncio
async def test_later_model_failure_preserves_call_outcome(target, status):
    def unavailable(messages):
        raise ConnectionError("model unavailable")

    model = ScriptedModel(
        [
            {"next": "act", "reason": "자료 확보 필요"},
            selection("query_data", {"target": target}),
            unavailable,
        ]
    )
    graph = compile_graph(
        build_nodes(model, PROVIDERS, CATALOG, role="interpretation"),
        finish=finish,
    )
    result = await graph.ainvoke(initial(), {})
    assert result["execution"]["status"] == status
    assert model.schemas == ["Decision", "Selection", "Decision"]
    called = next(r for r in result["results"] if r["decision"] == "call")
    assert (called["outcome"] == "success") == (target == "D3")
    assert not any(r["decision"] == "verification" for r in result["results"])


@pytest.mark.asyncio
async def test_query_calculate_compose_and_restore_without_verification():
    def calculate(messages):
        records = section(messages, "작업 결과와 검증 이력")
        query = next(r for r in records if r["decision"] == "call")
        return selection(
            "process_data",
            {
                "input_result_id": query["id"],
                "operations": [
                    {
                        "operation": "calculate",
                        "method": "percentage",
                        "before": "total_households",
                        "after": "elderly_single",
                        "output": "pct",
                    }
                ],
            },
        )

    model = ScriptedModel(
        [
            {"next": "act", "reason": "지역별 가구 수와 독거가구 수 필요"},
            selection("query_data", {"target": "D3"}),
            {"next": "act", "reason": "계산 필요"},
            calculate,
            DONE,
            composition,
        ]
    )
    graph = compile_graph(
        build_nodes(model, PROVIDERS, CATALOG, role="interpretation"),
        finish=finish,
    )
    result = await graph.ainvoke(initial(), {})
    assert result["execution"]["status"] == "completed", result["results"]
    assert len(result["response"]["artifacts"]) == 2
    assert [m.content for m in result["messages"] if m.type == "human"] == [
        initial()["messages"][0].content
    ]
    assert result["messages"][-1].content == result["response"]["content"]
    assert model.schemas == [
        "Decision",
        "Selection",
        "Decision",
        "Selection",
        "Decision",
        "Composition",
    ]
    assert not any(r["decision"] == "verification" for r in result["results"])
    calls = [
        r for r in result["results"] if r["node"] == "act" and r["decision"] == "call"
    ]
    assert calls[-1]["output"]["data"]["rows"][0]["pct"] == 12.5
    restored = state_adapter.validate_json(state_adapter.dump_json(result))
    node = build_nodes(
        ScriptedModel([composition]),
        PROVIDERS,
        CATALOG,
        role="interpretation",
    )["compose"]
    command = await node(restored, {})
    assert command.update["response"]["artifacts"] == result["response"]["artifacts"]
    for item in restored["results"]:
        if item["decision"] == "call":
            item["outcome"] = "failure"
    with pytest.raises(ToolFailure):
        select_artifacts(restored)


@pytest.mark.asyncio
async def test_child_agent_returns_usable_results_without_parent_verification():
    model = ScriptedModel(
        [
            {"next": "act", "reason": "전문 해석 필요"},
            selection("interpretation_agent", {"goal": "자료 조회"}),
            {"next": "act", "reason": "해석에 필요한 자료 확보"},
            selection("query_data", {"target": "D3"}),
            DONE,
            composition,
            DONE,
            composition,
        ]
    )
    graph = compile_graph(
        build_nodes(model, PROVIDERS, CATALOG, role="request"),
        finish=finish,
    )
    result = await graph.ainvoke(initial(), {})
    assert result["execution"]["status"] == "completed", result["results"]
    assert result["response"]["artifacts"]
    assert model.schemas == [
        "Decision",
        "Selection",
        "Decision",
        "Selection",
        "Decision",
        "Composition",
        "Decision",
        "Composition",
    ]
    child = next(r["output"] for r in result["results"] if r["decision"] == "call")
    assert child["execution"]["status"] == "completed"
    assert result["response"]["artifacts"] == child["response"]["artifacts"]


@pytest.mark.asyncio
async def test_question_resume_preserves_actual_dialogue():
    state = initial("user_request")

    def reinterpret(messages):
        assert "서울" in messages[1].content
        assert "어느 지역인가요?" in messages[1].content
        return {
            "request": {"goal": "서울 자료"},
            "reason": "답변 반영",
        }

    model = ScriptedModel(
        [
            {"request": state["request"], "reason": "지역이 지정되지 않은 요청"},
            {"next": "ask", "reason": "지역 필요"},
            {"content": "어느 지역인가요?", "reason": "지역 필요"},
            reinterpret,
            DONE,
            {
                "content": "자료 없음",
                "artifact_ids": [],
                "status": "partial",
                "reason": "미확보",
            },
        ]
    )
    graph = compile_graph(
        build_nodes(model, PROVIDERS, CATALOG, role="request"),
        finish=finish,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "prompt-resume"}}
    waiting = await graph.ainvoke(state, config)
    assert waiting["execution"]["status"] == "waiting_input"
    result = await graph.ainvoke(Command(resume="서울"), config)
    assert result["execution"]["status"] == "partial"


@pytest.mark.asyncio
async def test_tableau_invalid_conditions_are_repaired_and_previous_is_preserved():
    valid = {
        "view_key": "Embed01VulnerabilityMap",
        "parameters": {
            "p_city": "51110",
            "p_start": "2025-07-01",
            "p_end": "2025-12-01",
        },
        "filters": {"읍면동": ["후평3동"]},
    }
    invalid = valid | {"filters": {"읍면동": ["역삼1동"]}}

    def repair(messages):
        catalog = section(messages, "시각화 목록과 입력 조건")
        allowed = catalog["selected"][valid["view_key"]]["filters"]["읍면동"]["allowed"]
        assert "후평3동" in allowed and "역삼1동" not in allowed
        records = section(messages, "작업 결과와 검증 이력")
        rejected = next(r for r in records if r["decision"] == "call")
        assert rejected["output"]["valid"] is False
        assert rejected["output"]["issues"]
        return selection("validate_visualization", valid)

    model = ScriptedModel(
        [
            {"next": "act", "reason": "요청한 표시 조건의 검증 필요"},
            selection("validate_visualization", invalid),
            {"next": "act", "reason": "조건 수정"},
            repair,
            DONE,
            composition,
        ]
    )
    graph = compile_graph(
        build_nodes(model, {}, [], role="visualization"), finish=finish
    )
    result = await graph.ainvoke(initial(), {})
    assert result["execution"]["status"] == "completed", result["results"]
    assert result["response"]["artifacts"] == [
        validate_visualization(valid, state=initial())["artifact"]
    ]
    response = deepcopy(result["response"])
    followup = ScriptedModel(
        [
            {
                "content": "기존 차트 설명",
                "artifact_ids": ["previous"],
                "status": "completed",
                "reason": "기존 산출물 유지",
            }
        ]
    )
    command = await build_nodes(followup, {}, [], role="visualization")["compose"](
        result, {}
    )
    assert command.update["response"]["artifacts"] == response["artifacts"]
    assert section(followup.inputs[0], "기존 공개 산출물") == response["artifacts"]
    assert "[선택 차트]" not in followup.inputs[0][1].content


@pytest.mark.asyncio
async def test_failed_calls_stop_at_shared_retry_limit():
    state = initial()
    state["execution"]["budget"]["retries"]["limit"] = 1
    retry = {"next": "act", "reason": "재시도"}
    failed = {
        "content": "조회 실패",
        "artifact_ids": [],
        "status": "failed",
        "reason": "한도",
    }
    choose = selection("query_data", {"target": "unknown"})
    model = ScriptedModel([retry, choose, retry, choose, retry, choose, failed])
    graph = compile_graph(
        build_nodes(model, PROVIDERS, CATALOG, role="interpretation"), finish=finish
    )
    result = await graph.ainvoke(state, {})
    assert result["execution"]["error"]["code"] == "execution_limit_exceeded"
    assert result["execution"]["budget"]["retries"]["used"] == 1
    assert result["execution"]["budget"]["tool_calls"]["used"] == 2
    calls = [r for r in result["results"] if r["decision"] == "call"]
    assert len(calls) == 2 and all(r["outcome"] == "failure" for r in calls)
    assert result["response"]["artifacts"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments", [{"data": {"rows": []}}, {"input_result_id": "unobserved"}]
)
async def test_processing_rejects_model_invented_data(arguments):
    state = initial()
    model = ScriptedModel([selection("process_data", arguments)])
    command = await build_nodes(model, PROVIDERS, CATALOG, role="interpretation")[
        "act"
    ](state, {})
    called = next(r for r in command.update["results"] if r["decision"] == "call")
    assert called["outcome"] == "failure"
    assert called["output"]["code"] == "invalid_data_reference"
    assert accepted_outputs(state) == {}
