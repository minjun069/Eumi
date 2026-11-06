"""실제 업무 노드·그래프·도구를 실행하고 외부 모델 응답만 대체한다."""

import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from experiments.scenario_fixtures import CATALOG, PROVIDERS, households
from src.agent_nodes import build_nodes, finish, select_artifacts
from src.exceptions import ToolFailure
from src.execution_trace import TraceRecorder, recording
from src.graph import compile_graph
from src.settings import Settings
from src.state import create_state, state_adapter
from src.tools.process import process_data
from src.tools.render import render_visualization


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)

    async def ainvoke(self, messages, config):
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)
        context = json.loads(messages[1].content.split("\n", 1)[1])
        assert (
            not {"provided_results", "selection", "call_output", "verified_ids"}
            & context.keys()
        )
        reply = next(self.replies)
        if callable(reply):
            reply = reply(context)
        return AIMessage(
            json.dumps(reply, ensure_ascii=False),
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        )


def selection(name, args):
    return {"name": name, "arguments_json": json.dumps(args), "reason": "test"}


def last_call(context):
    return next(
        r["id"] for r in reversed(context["results"]) if r["decision"] == "call"
    )


def initial(event="analysis_pipeline"):
    settings = Settings(_env_file=None)
    return create_state(
        {"goal": "test"}, settings, messages=[], version="test", event=event
    )


def graph(replies, **settings):
    return compile_graph(
        build_nodes(
            ScriptedModel(replies),
            PROVIDERS,
            CATALOG,
            Settings(_env_file=None, **settings),
            role="interpretation",
        ),
        finish=finish,
        checkpointer=InMemorySaver(),
    )


@pytest.mark.asyncio
async def test_actual_query_calculation_verification_and_artifact():
    def verify_query(context):
        selected, called = context["results"][-2:]
        assert selected["decision"] == "selection"
        assert selected["output"]["name"] == "query_data"
        assert called["action"]["name"] == "query_data"
        assert called["output"]["data"]["rows"] == households()["rows"]
        return {"accepted": True, "reason": "State 조회 결과 확인"}

    g = graph(
        [
            selection("query_data", {"target": "D3"}),
            verify_query,
            {"next": "act", "reason": "비율 계산 필요"},
            lambda c: selection(
                "process_data",
                {
                    "input_result_id": last_call(c),
                    "operations": [
                        {
                            "operation": "calculate",
                            "method": "percentage",
                            "before": "total_households",
                            "after": "elderly_single",
                            "output": "pct",
                        },
                        {
                            "operation": "sort",
                            "by": [{"field": "pct", "descending": True}],
                        },
                    ],
                    "decimals": 1,
                },
            ),
            {"accepted": True, "reason": "분모·정렬 확인"},
            {"next": "compose", "reason": "충분"},
            lambda c: {
                "content": "시연용 예시 데이터",
                "artifact_ids": [last_call(c)],
                "status": "completed",
                "reason": "근거 확보",
            },
        ]
    )
    original = initial()
    result = await g.ainvoke(original, {"configurable": {"thread_id": "pipeline"}})
    state_adapter.validate_python(result)
    assert original["results"] == []
    assert len({r["id"] for r in result["results"]}) == len(result["results"])
    assert result["execution"]["status"] == "completed"
    data = result["response"]["artifacts"][1]["data"]["dataset"]
    assert [r["pct"] for r in data["rows"]] == [14.4, 12.5, 11.2, 9.6, 7.1]
    assert [r["region"] for r in data["rows"]] == ["C동", "A동", "E동", "B동", "D동"]
    assert all(m.type != "human" for m in result["messages"])


@pytest.mark.asyncio
async def test_rejected_result_is_not_published_and_rework_preserves_history():
    g = graph(
        [
            selection("query_data", {"target": "D3", "limit": 1}),
            {"accepted": False, "reason": "5개 동 중 1개만 조회"},
            {"next": "act", "reason": "전체 범위 필요"},
            selection("query_data", {"target": "D3"}),
            {"accepted": True, "reason": "전체 범위 충족"},
            {"next": "compose", "reason": "충분"},
            lambda c: {
                "content": "5개 동",
                "artifact_ids": [last_call(c)],
                "status": "completed",
                "reason": "완료",
            },
        ]
    )
    result = await g.ainvoke(initial(), {"configurable": {"thread_id": "rework"}})
    calls = [r for r in result["results"] if r["decision"] == "call"]
    assert len(calls) == 2
    with pytest.raises(ToolFailure, match="도구"):
        select_artifacts(result, [calls[0]["id"]])
    assert len(result["response"]["artifacts"][1]["data"]["dataset"]["rows"]) == 5


@pytest.mark.asyncio
async def test_question_resume_retains_run_and_prior_artifacts():
    def compose_with_previous(context):
        assert context["response"]["artifacts"]
        return {
            "content": "자료가 없어 설명할 수 없습니다.",
            "artifact_ids": ["previous"],
            "status": "failed",
            "reason": "자료 없음",
        }

    model = ScriptedModel(
        [
            {
                "request": {"goal": "지역 확인"},
                "reason": "필수 정보 없음",
                "needs_input": True,
            },
            {"next": "ask", "reason": "지역 필요"},
            {"content": "어느 지역인가요?", "reason": "지역 필요"},
            {
                "request": {"goal": "A동 설명"},
                "reason": "답변 반영",
                "needs_input": False,
            },
            selection("none", {}),
            {"next": "compose", "reason": "자료 없음 안내"},
            compose_with_previous,
        ]
    )
    g = compile_graph(
        build_nodes(
            model, PROVIDERS, CATALOG, Settings(_env_file=None), role="request"
        ),
        finish=finish,
        checkpointer=InMemorySaver(),
    )
    state = initial("user_request")
    state["response"] = {
        "id": "old",
        "kind": "final",
        "label": "old",
        "content": "old",
        "artifacts": [{"type": "chart", "data": {"id": "selected"}}],
    }
    config = {"configurable": {"thread_id": "question"}}
    waiting = await g.ainvoke(state, config)
    assert waiting["execution"]["status"] == "waiting_input"
    result = await g.ainvoke(Command(resume="A동"), config)
    assert result["execution"]["run_id"] == state["execution"]["run_id"]
    assert result["response"]["artifacts"] == state["response"]["artifacts"]
    assert [m.content for m in result["messages"] if m.type == "human"] == ["A동"]


@pytest.mark.asyncio
async def test_model_cannot_inject_data_instead_of_observed_result():
    g = graph(
        [
            selection(
                "process_data",
                {"input_result_id": "invented", "data": households(), "operations": []},
            ),
            {"next": "compose", "reason": "호출 실패"},
            {
                "content": "실패",
                "artifact_ids": [],
                "status": "failed",
                "reason": "실패",
            },
        ]
    )
    result = await g.ainvoke(initial(), {"configurable": {"thread_id": "injection"}})
    failure = next(r for r in result["results"] if r["decision"] == "call_failed")
    assert failure["output"]["code"] == "invalid_data_reference"
    assert result["response"]["artifacts"] == []


def test_percentage_and_horizontal_chart_use_original_counts():
    source = households()
    original = deepcopy(source)
    result = process_data(
        {
            "data": source,
            "operations": [
                {
                    "operation": "calculate",
                    "method": "percentage",
                    "before": "total_households",
                    "after": "elderly_single",
                    "output": "pct",
                },
                {"operation": "sort", "by": [{"field": "pct", "descending": True}]},
            ],
            "decimals": 1,
        }
    )
    rendered = render_visualization(
        {
            "data": result["data"],
            "spec": {
                "type": "bar",
                "title": "시연용 예시 데이터",
                "x": "region",
                "y": "pct",
                "unit": "%",
                "orientation": "horizontal",
                "value_range": {"minimum": 0.0, "maximum": 20.0},
            },
        }
    )
    assert source == original
    html = rendered["artifact"]["data"]["content"]
    assert "14.4%" in html and "12.5%" in html
    assert html.index("C동") < html.index("A동") < html.index("E동")
    assert rendered["applied"]["orientation"] == "horizontal"
    assert rendered["data_reference"] == result["data"]["reference"]


@pytest.mark.asyncio
async def test_request_calls_specialist_and_integrates_its_actual_table():
    model = ScriptedModel(
        [
            {
                "request": {"goal": "가구 설명"},
                "reason": "요청 확인",
                "needs_input": False,
            },
            selection("interpretation_agent", {"goal": "D3 가구 구성 설명"}),
            {
                "request": {"goal": "D3 가구 구성 설명"},
                "reason": "대상 확인",
                "needs_input": False,
            },
            selection("query_data", {"target": "D3"}),
            {"accepted": True, "reason": "자료 확인"},
            {"next": "compose", "reason": "설명 가능"},
            lambda c: {
                "content": "시연용 예시 데이터",
                "artifact_ids": [last_call(c)],
                "status": "completed",
                "reason": "하위 완료",
            },
            {"accepted": True, "reason": "하위 결과 검증"},
            {"next": "compose", "reason": "통합 가능"},
            lambda c: {
                "content": "통합 답변",
                "artifact_ids": [last_call(c)],
                "status": "completed",
                "reason": "상위 완료",
            },
        ]
    )
    g = compile_graph(
        build_nodes(
            model, PROVIDERS, CATALOG, Settings(_env_file=None), role="request"
        ),
        finish=finish,
        checkpointer=InMemorySaver(),
    )
    recorder = TraceRecorder()
    with recording(recorder):
        result = await g.ainvoke(
            initial("user_request"), {"configurable": {"thread_id": "nested"}}
        )
    child_trace = next(s for s in recorder.spans if s["kind"] == "agent")
    first_node = next(s for s in recorder.spans if s["parent_id"] == child_trace["id"])
    assert child_trace["input"]["initial_state"] == first_node["input"]["state"]
    assert child_trace["input"]["initial_state"]["results"] == []
    assert "provided_results" not in child_trace["input"]
    assert child_trace["input"]["catalog"] == CATALOG
    assert child_trace["output"]["execution"]["status"] == "completed"
    assert "api_key" not in child_trace["input"]["settings"]
    child = next(r["output"] for r in result["results"] if r["decision"] == "call")
    assert child["execution"]["status"] == "completed"
    assert result["response"]["artifacts"] == child["response"]["artifacts"]
    assert any(
        r["action"] and r["action"]["name"] == "query_data" for r in child["results"]
    )


@pytest.mark.asyncio
async def test_failed_queries_stop_at_retry_limit():
    failures = []
    for _ in range(3):
        failures += [
            selection("query_data", {"target": "unknown"}),
            {"next": "act", "reason": "보완 필요"},
        ]
    g = graph(
        failures
        + [
            {"next": "act", "reason": "모델이 한도를 무시해도 중단"},
            {
                "content": "조회 실패",
                "artifact_ids": [],
                "status": "failed",
                "reason": "한도",
            },
        ],
        max_tool_retries=2,
    )
    result = await g.ainvoke(initial(), {"configurable": {"thread_id": "limits"}})
    assert sum(r["action"] is not None for r in result["results"]) == 3
    assert result["execution"]["status"] == "failed"
    assert any(r["decision"] == "limit_reached" for r in result["results"])


@pytest.mark.asyncio
async def test_scenario_retains_checkpoint_on_model_error(tmp_path):
    from scenario_demo import run_scenario, save_case

    class UnavailableModel:
        async def ainvoke(self, messages, config):
            raise ConnectionError("private provider response must not be saved")

    case = await run_scenario("S1", UnavailableModel(), Settings(_env_file=None))
    assert case["state"]["execution"]["status"] == "failed"
    assert case["failure"]["error_type"] == "ConnectionError"
    assert case["metrics"]["model_calls"] == 0
    save_case(case, tmp_path)
    report = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert "private provider response" not in report
    assert not any(m.type == "human" for m in case["state"]["messages"])


@pytest.mark.asyncio
async def test_child_returns_tool_result_without_parent_data_injection():
    def child_request(context):
        assert context["results"] == []
        return interpreted

    def verify_child(context):
        selected, called = context["results"][-2:]
        assert selected["decision"] == "selection"
        assert called["action"]["name"] == "interpretation_agent"
        assert called["output"]["response"]["artifacts"]
        assert called["output"]["results"]
        return valid

    def child_result(context):
        child = next(
            r["output"]
            for r in context["results"]
            if r["action"] and r["action"]["name"] == "interpretation_agent"
        )
        return next(
            r["id"]
            for r in child["results"]
            if r["action"] and r["action"]["name"] == "process_data"
        )

    interpreted = {
        "request": {"goal": "가구 비율 설명과 비교표"},
        "reason": "확인",
        "needs_input": False,
    }
    valid = {"accepted": True, "reason": "검증"}
    more = {"next": "act", "reason": "다음 작업"}
    done = {"next": "compose", "reason": "완료"}
    model = ScriptedModel(
        [
            interpreted,
            selection("query_data", {"target": "D3"}),
            valid,
            more,
            selection("interpretation_agent", {"goal": "D3 가구 비율 비교표와 설명"}),
            child_request,
            selection("query_data", {"target": "D3"}),
            valid,
            more,
            lambda c: selection(
                "process_data",
                {
                    "input_result_id": last_call(c),
                    "operations": [
                        {
                            "operation": "calculate",
                            "method": "percentage",
                            "before": "total_households",
                            "after": "elderly_single",
                            "output": "pct",
                        },
                        {
                            "operation": "sort",
                            "by": [{"field": "pct", "descending": True}],
                        },
                    ],
                    "decimals": 1,
                },
            ),
            valid,
            done,
            lambda c: {
                "content": "비교표",
                "artifact_ids": [last_call(c)],
                "status": "completed",
                "reason": "완료",
            },
            verify_child,
            done,
            lambda c: {
                "content": "통합 비교표",
                "artifact_ids": [child_result(c)],
                "status": "completed",
                "reason": "완료",
            },
        ]
    )
    g = compile_graph(
        build_nodes(
            model, PROVIDERS, CATALOG, Settings(_env_file=None), role="request"
        ),
        finish=finish,
        checkpointer=InMemorySaver(),
    )
    result = await g.ainvoke(
        initial("user_request"), {"configurable": {"thread_id": "shared-data"}}
    )
    assert result["execution"]["status"] == "completed"
    dataset = result["response"]["artifacts"][1]["data"]["dataset"]
    assert [row["pct"] for row in dataset["rows"]] == [14.4, 12.5, 11.2, 9.6, 7.1]
    child = next(
        r["output"]
        for r in result["results"]
        if r["action"] and r["action"]["name"] == "interpretation_agent"
    )
    assert [r["action"]["name"] for r in child["results"] if r["action"]] == [
        "query_data",
        "process_data",
    ]
    # 상위의 하위 호출 검증을 거부하면 하위 산출물 ID도 공개할 수 없다.
    rejected = deepcopy(result)
    parent_call = next(
        r
        for r in result["results"]
        if r["action"] and r["action"]["name"] == "interpretation_agent"
    )
    for r in rejected["results"]:
        if (
            r["decision"] == "verification"
            and r["output"]["call_id"] == parent_call["id"]
        ):
            r["output"]["accepted"] = False
    with pytest.raises(ToolFailure):
        select_artifacts(rejected, [child_result(result)])

    # 새 노드 인스턴스는 저장한 State만으로 하위 결과를 다시 선택한다.
    restored = state_adapter.validate_json(state_adapter.dump_json(result))
    restored_nodes = build_nodes(
        ScriptedModel(
            [
                lambda c: {
                    "content": "복원한 비교표",
                    "artifact_ids": [child_result(c)],
                    "status": "completed",
                    "reason": "저장한 호출·검증 이력 사용",
                }
            ]
        ),
        PROVIDERS,
        CATALOG,
        Settings(_env_file=None),
        role="request",
    )
    command = await restored_nodes["compose"](restored, {})
    assert command.update["response"]["artifacts"] == result["response"]["artifacts"]
