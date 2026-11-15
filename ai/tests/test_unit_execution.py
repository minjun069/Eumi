"""단일 실행도 실제 업무 판단·공통 갱신·호출 기록 경계를 사용한다."""

from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command

from experiments.scenario_fixtures import CATALOG, PROVIDERS
from src.agent_nodes import build_nodes, finish, response, select_work
from src.exceptions import LimitReached
from src.execution import record
from src.execution_trace import TraceRecorder, recording
from src.graph import run_node
from src.tools.interface import create_tools
from src.tools.query import query_data
from tests.helpers import DONE, ScriptedModel, composition, initial, selection

pytestmark = pytest.mark.usefixtures("all_tableau_views")


@pytest.mark.asyncio
async def test_single_real_node_preserves_history_and_does_not_follow_route():
    state = initial("user_request")
    previous = record("decide", "decision", "이전 판단")
    state["results"].append(previous)
    before = deepcopy(state)
    model = ScriptedModel(
        [
            {
                "request": {"goal": "비율 비교", "constraints": {}},
                "reason": "요청 파악",
            }
        ]
    )
    recorder = TraceRecorder()
    with recording(recorder):
        result, target = await run_node(
            "interpret",
            build_nodes(model, PROVIDERS, CATALOG, role="request")["interpret"],
            state,
            finish=finish,
        )
    assert target == "decide"
    assert model.schemas == ["Interpretation"]
    assert result["request"]["goal"] == "비율 비교"
    assert result["results"][0] == previous
    assert len(result["results"]) == 2
    assert result["execution"]["budget"]["steps"]["used"] == 1
    assert state == before
    node, model_span = recorder.spans
    assert node["name"] == "interpret"
    assert model_span["parent_id"] == node["id"]
    assert node["output"]["goto"] == "decide"


@pytest.mark.asyncio
async def test_single_ask_stops_before_wait_and_keeps_real_conversation():
    state = initial("user_request")
    model = ScriptedModel([{"content": "어느 기간인가요?", "reason": "기간 필요"}])
    result, target = await run_node(
        "ask",
        build_nodes(model, PROVIDERS, CATALOG, role="request")["ask"],
        state,
        finish=finish,
    )
    assert target == "wait"
    assert result["execution"]["status"] == "waiting_input"
    assert result["messages"][0].content == state["messages"][0].content
    assert result["messages"][-1].content == "어느 기간인가요?"
    assert len(result["messages"]) == 2
    assert model.schemas == ["Question"]


@pytest.mark.asyncio
async def test_single_node_uses_message_id_reducer_and_write_permissions():
    state = initial()
    state["messages"].append(AIMessage("이전 내용", id="same-response"))

    async def ask(state):
        reply = response(state, "question", "갱신된 질문")
        reply["id"] = "same-response"
        return Command(update={"results": [], "response": reply}, goto="wait")

    result, target = await run_node("ask", ask, state, finish=finish)
    assert target == "wait"
    assert len(result["messages"]) == 2
    assert result["messages"][-1].content == "갱신된 질문"

    async def invalid(state):
        return Command(update={"request": state["request"]}, goto="act")

    failed, target = await run_node("decide", invalid, state, finish=finish)
    assert target == END
    assert failed["execution"]["status"] == "failed"
    assert failed["results"][-1]["decision"] == "execution_failed"


@pytest.mark.asyncio
async def test_single_node_limit_returns_route_without_running_final_compose():
    state = initial()
    state["execution"]["budget"]["steps"]["limit"] = 0
    model = ScriptedModel([])
    result, target = await run_node(
        "act",
        build_nodes(model, PROVIDERS, CATALOG, role="interpretation")["act"],
        state,
        finish=finish,
    )
    assert target == "compose"
    assert model.schemas == []
    assert result["results"][-1]["decision"] == "limit_reached"
    assert result["execution"]["budget"]["final_model_calls"]["used"] == 0


@pytest.mark.asyncio
async def test_selection_only_reuses_act_input_and_records_without_work():
    def unavailable():
        raise AssertionError("선택 평가에서 도구를 실행함")

    providers = {"D3": unavailable}
    state = initial()
    full_state = deepcopy(state)
    chosen = selection("query_data", {"target": "D3"})
    selection_model = ScriptedModel([chosen])
    act_model = ScriptedModel([chosen])
    tools = {tool.name: tool for tool in create_tools(providers, state=state)}
    recorder = TraceRecorder()
    with recording(recorder):
        choice = await select_work(
            selection_model, tools, CATALOG, state, role="interpretation"
        )
    calls = []

    async def fixed_tool(tool, arguments, config):
        calls.append((tool.name, arguments))
        return {"data": {"rows": []}}

    await build_nodes(
        act_model,
        providers,
        CATALOG,
        role="interpretation",
        tool_runner=fixed_tool,
    )["act"](full_state, {})
    assert choice == chosen
    assert [message.content for message in selection_model.inputs[0]] == [
        message.content for message in act_model.inputs[0]
    ]
    assert selection_model.response_schemas == act_model.response_schemas
    assert selection_model.response_options == act_model.response_options
    assert [item["decision"] for item in state["results"]] == ["selection"]
    assert state["execution"]["budget"]["tool_calls"]["used"] == 0
    assert {span["kind"] for span in recorder.spans} == {"model"}
    assert calls == [("query_data", {"target": "D3"})]


@pytest.mark.asyncio
async def test_selection_only_checks_model_budget_before_call():
    state = initial()
    state["execution"]["budget"]["active_seconds"]["limit"] = 0
    model = ScriptedModel([])
    tools = {tool.name: tool for tool in create_tools(PROVIDERS, state=state)}
    with pytest.raises(LimitReached):
        await select_work(model, tools, CATALOG, state, role="interpretation")
    assert model.schemas == []
    assert state["results"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["source", "unknown"])
async def test_tool_boundary_keeps_reference_resolution_and_call_record(reference):
    state = initial()
    source = record(
        "act", "call", "가공 원자료", output=query_data({"target": "D3"}, PROVIDERS)
    )
    source["id"] = "source"
    state["results"].append(source)
    arguments = {
        "input_result_id": reference,
        "operations": [
            {
                "operation": "calculate",
                "method": "percentage",
                "before": "total_households",
                "after": "elderly_single",
                "output": "pct",
            }
        ],
    }
    invoked = []

    async def fixed_tool(tool, actual, config):
        invoked.append(actual)
        assert tool.name == "process_data"
        assert "data" in tool.args_schema["properties"]
        return {"data": actual["data"]}

    model = ScriptedModel([selection("process_data", arguments)])
    recorder = TraceRecorder()
    with recording(recorder):
        result, target = await run_node(
            "act",
            build_nodes(
                model, PROVIDERS, CATALOG, role="interpretation", tool_runner=fixed_tool
            )["act"],
            state,
            finish=finish,
        )
    assert target == "decide"
    called = result["results"][-1]
    assert called["action"]["arguments"] == arguments
    assert result["execution"]["budget"]["tool_calls"]["used"] == 1
    if reference == "source":
        assert invoked[0]["data"] == source["output"]["data"]
        assert "input_result_id" not in invoked[0]
        tool_span = next(span for span in recorder.spans if span["kind"] == "tool")
        assert tool_span["input"]["selected_arguments"] == arguments
        assert tool_span["input"]["resolved_arguments"] == invoked[0]
        assert called["outcome"] == "success"
    else:
        assert invoked == []
        assert called["outcome"] == "failure"
        assert called["output"]["code"] == "invalid_data_reference"


@pytest.mark.asyncio
async def test_agent_boundary_preserves_child_state_and_shared_usage():
    state = initial()
    captured = []

    async def fixed_agent(role, child, config):
        captured.append(deepcopy(child))
        assert role == "interpretation"
        assert child["execution"]["budget"]["agent_calls"]["used"] == 1
        child["response"] = response(child, "final", "하위 해석 결과")
        child["execution"]["status"] = "completed"
        child["execution"]["budget"]["steps"]["used"] += 2
        return child

    model = ScriptedModel([selection("interpretation_agent", {"goal": "하위 목표"})])
    recorder = TraceRecorder()
    with recording(recorder):
        result, target = await run_node(
            "act",
            build_nodes(
                model, PROVIDERS, CATALOG, role="request", agent_runner=fixed_agent
            )["act"],
            state,
            finish=finish,
        )
    assert target == "decide"
    assert model.schemas == ["Selection"]
    assert captured[0]["results"] == []
    assert captured[0]["request"]["constraints"] == state["request"]["constraints"]
    assert captured[0]["execution"]["event"] == state["execution"]["event"]
    assert result["execution"]["budget"]["steps"]["used"] == 3
    assert result["results"][-1]["output"]["response"]["content"] == "하위 해석 결과"
    assert any(span["kind"] == "agent" for span in recorder.spans)


@pytest.mark.asyncio
async def test_real_child_receives_tool_and_renderer_boundaries():
    output = query_data({"target": "D3"}, PROVIDERS)
    tools, renders = [], []

    async def fixed_tool(tool, arguments, config):
        tools.append((tool.name, arguments))
        return deepcopy(output)

    def fixed_renderer(request):
        renders.append(deepcopy(request))
        return {
            "applied": request["spec"],
            "artifact": {"type": "table", "data": {"content": "준비한 표"}},
        }

    model = ScriptedModel(
        [
            selection("interpretation_agent", {"goal": "자료 조회·표 제공"}),
            {"next": "act", "reason": "자료 조회 필요"},
            selection("query_data", {"target": "D3"}),
            DONE,
            composition,
        ]
    )
    recorder = TraceRecorder()
    with recording(recorder):
        result, target = await run_node(
            "act",
            build_nodes(
                model,
                PROVIDERS,
                CATALOG,
                role="request",
                tool_runner=fixed_tool,
                renderer=fixed_renderer,
            )["act"],
            initial(),
            finish=finish,
        )
    assert target == "decide"
    assert tools == [("query_data", {"target": "D3"})]
    assert len(renders) == 1
    child = result["results"][-1]["output"]
    assert child["execution"]["status"] == "completed"
    assert child["response"]["artifacts"][0]["data"]["content"] == "준비한 표"
    assert result["execution"]["budget"]["tool_calls"]["used"] == 2
    tool_spans = [span for span in recorder.spans if span["kind"] == "tool"]
    assert [span["name"] for span in tool_spans] == [
        "query_data",
        "render_visualization",
    ]
