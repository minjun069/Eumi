"""제목형 입력, State 보존 및 실제 노드의 호출·검증 경계를 확인한다."""

import json
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from experiments.scenario_fixtures import CATALOG, PROVIDERS
from src.agent_nodes import (
    Composition,
    Decision,
    Interpretation,
    Question,
    Selection,
    Verification,
    build_nodes,
    finish,
    record,
    select_artifacts,
)
from src.exceptions import ToolFailure
from src.execution_trace import TraceRecorder, recording
from src.gemini import create_gemini, structured_call
from src.graph import compile_graph
from src.prompting import (
    ask_messages,
    compose_messages,
    decide_messages,
    interpret_messages,
    selection_messages,
    verification_messages,
)
from src.settings import Settings
from src.state import create_state, state_adapter
from src.tools.tableau import validate_visualization


pytestmark = pytest.mark.usefixtures("all_tableau_views")

def initial(event="analysis_pipeline"):
    return create_state(
        {"goal": "지역별 비율 비교", "constraints": {"required": ["출처 명시"]}},
        Settings(_env_file=None),
        messages=[HumanMessage('사용자 원문\n"비율을 알려줘"')],
        version="test",
        event=event,
    )


def section(messages, title):
    text = messages[1].content.split(f"[{title}]\n", 1)[1]
    return json.JSONDecoder().raw_decode(text)[0]


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.inputs = []

    async def ainvoke(self, messages, config):
        self.inputs.append(messages)
        reply = next(self.replies)
        if callable(reply):
            reply = reply(messages)
        return AIMessage(json.dumps(reply, ensure_ascii=False))


def selection(name, args):
    return {"name": name, "arguments_json": json.dumps(args), "reason": "작업 선택"}


ACCEPT = {"accepted": True, "reason": "범위와 계산 확인"}
DONE = {"next": "compose", "reason": "완료"}


def composition(messages):
    results = section(messages, "작업 결과와 검증 이력")
    accepted = {
        r["output"]["call_id"]
        for r in results
        if r["decision"] == "verification" and r["output"]["accepted"]
    }
    call = next(r for r in reversed(results) if r["id"] in accepted)
    return {
        "content": "시연용 예시 데이터로 계산한 결과입니다.",
        "artifact_ids": [call["id"]],
        "status": "completed",
        "reason": "검증된 계산 결과",
    }


@pytest.mark.parametrize("role", ["request", "interpretation", "visualization"])
def test_each_node_selects_materials_without_mutating_state(role):
    state = initial()
    state["results"] = [
        record(
            "act", "selection", "조회", output=selection("query_data", {"target": "D3"})
        ),
        record(
            "act",
            "call",
            "조회",
            action={"name": "query_data", "arguments": {"target": "D3"}},
            output={"data": {"rows": [{"n": 11}]}},
        ),
    ]
    before = deepcopy(state)
    catalog = {"data_catalog_sentinel": {"title": "조회 목록"}}
    builders = [
        (interpret_messages, Interpretation),
        (verification_messages, Verification),
        (decide_messages, Decision),
        (compose_messages, Composition),
        (ask_messages, Question),
    ]
    for builder, schema in builders:
        messages = builder(state, role, schema)
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)
        assert "[출력 요구사항]" in messages[0].content
        assert state["messages"][0].content in messages[1].content
        assert "data_catalog_sentinel" not in messages[1].content
        assert "query_data: {target" not in messages[0].content
        assert "[시각화 목록과 입력 조건]" not in messages[1].content
        assert "[현재 화면 내용]" not in messages[1].content
        assert "[선택 차트]" not in messages[1].content
        assert "[이전 대화 요약]" not in messages[1].content
    messages = selection_messages(state, role, Selection, catalog)
    assert "data_catalog_sentinel" in messages[1].content
    assert "query_data: {target" in messages[0].content
    assert ("validate_visualization: {" in messages[0].content) == (
        role != "interpretation"
    )
    assert ("interpretation_agent / visualization_agent:" in messages[0].content) == (
        role == "request"
    )
    assert state == before


def test_verification_keeps_nested_source_and_parent_acceptance():
    state = initial()
    child_call = record("act", "call", "원본", output={"data": {"rows": [{"n": 1}]}})
    child_check = record(
        "act",
        "verification",
        "검증",
        output={"accepted": True, "call_id": child_call["id"]},
    )
    parent = record(
        "act", "call", "하위 결과", output={"results": [child_call, child_check]}
    )
    parent_check = record(
        "act",
        "verification",
        "상위 검증",
        output={"accepted": True, "call_id": parent["id"]},
    )
    args = {"input_result_id": child_call["id"]}
    picked = record("act", "selection", "계산", output=selection("process_data", args))
    called = record(
        "act",
        "call",
        "계산",
        action={"name": "process_data", "arguments": args},
        output={"data": {"rows": [{"pct": 25}]}},
    )
    state["results"] = [parent, parent_check, picked, called]
    messages = verification_messages(state, "interpretation", Verification)
    sources = section(messages, "계산 입력의 원본·검증")
    assert sources[0]["output"]["results"][0]["id"] == child_call["id"]
    assert sources[1]["output"]["call_id"] == parent["id"]
    assert section(messages, "검증할 선택·호출 기록")[-1]["id"] == called["id"]


@pytest.mark.asyncio
async def test_query_calculate_verify_compose_and_restore():
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

    def verify(messages):
        picked, called = section(messages, "검증할 선택·호출 기록")
        assert picked["output"]["name"] == called["action"]["name"]
        assert called["output"]["data"]["rows"]
        if called["action"]["name"] == "process_data":
            source = section(messages, "계산 입력의 원본·검증")
            assert source[-1]["output"]["accepted"]
            assert all("pct" in row for row in called["output"]["data"]["rows"])
        return ACCEPT

    model = ScriptedModel(
        [
            selection("query_data", {"target": "D3"}),
            verify,
            {"next": "act", "reason": "계산 필요"},
            calculate,
            verify,
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
    assert len([r for r in result["results"] if r["decision"] == "verification"]) == 2
    restored = state_adapter.validate_json(state_adapter.dump_json(result))
    node = build_nodes(
        ScriptedModel([composition]),
        PROVIDERS,
        CATALOG,
        role="interpretation",
    )["compose"]
    command = await node(restored, {})
    assert command.update["response"]["artifacts"] == result["response"]["artifacts"]
    for record_item in restored["results"]:
        if record_item["decision"] == "verification":
            record_item["output"]["accepted"] = False
    with pytest.raises(ToolFailure):
        select_artifacts(
            restored, [r["id"] for r in restored["results"] if r["decision"] == "call"]
        )


@pytest.mark.asyncio
async def test_child_agent_uses_state_and_parent_verifies_returned_records():
    def verify_child(messages):
        called = section(messages, "검증할 선택·호출 기록")[-1]
        assert called["action"]["name"] == "interpretation_agent"
        assert called["output"]["execution"]["event"] == "analysis_pipeline"
        assert any(r["decision"] == "verification" for r in called["output"]["results"])
        return ACCEPT

    model = ScriptedModel(
        [
            selection("interpretation_agent", {"goal": "자료 조회"}),
            selection("query_data", {"target": "D3"}),
            ACCEPT,
            DONE,
            composition,
            verify_child,
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


@pytest.mark.asyncio
async def test_question_resume_preserves_actual_dialogue():
    state = initial("user_request")

    def reinterpret(messages):
        assert "서울" in messages[1].content
        assert "어느 지역인가요?" in messages[1].content
        return {
            "request": {"goal": "서울 자료"},
            "needs_input": False,
            "reason": "답변 반영",
        }

    model = ScriptedModel(
        [
            {"request": state["request"], "needs_input": True, "reason": "지역 필요"},
            {"next": "ask", "reason": "지역 필요"},
            {"content": "어느 지역인가요?", "reason": "지역 필요"},
            reinterpret,
            selection("none", {}),
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
@pytest.mark.parametrize("invalid", [False, True])
async def test_adapter_sends_exact_messages_and_validates_without_assembling(invalid):
    class Model:
        async def ainvoke(self, received, config):
            assert received is messages
            return AIMessage("not JSON" if invalid else json.dumps(DONE))

    messages = decide_messages(initial(), "interpretation", Decision)
    trace = TraceRecorder()
    with recording(trace):
        if invalid:
            with pytest.raises(ValidationError):
                await structured_call(Model(), Decision, messages, {})
        else:
            value, _ = await structured_call(Model(), Decision, messages, {})
            assert value == DONE
    assert trace.spans[0]["input"]["messages"][1]["content"] == messages[1].content
    assert "context" not in trace.spans[0]["input"]
    assert trace.spans[0]["status"] == ("error" if invalid else "success")


@pytest.mark.asyncio
async def test_tableau_invalid_conditions_are_repaired_and_previous_is_preserved():
    valid = {
        "view_key": "Embed01VulnerabilityMap",
        "parameters": {"p_city": "51110"},
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
            selection("validate_visualization", invalid),
            {"next": "act", "reason": "조건 수정"},
            repair,
            ACCEPT,
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
@pytest.mark.parametrize("bad_response", [False, True])
async def test_real_adapter_http_payload_and_failure_trace(monkeypatch, bad_response):
    requests = []
    content = "invalid JSON" if bad_response else json.dumps(DONE)

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "gemini-3-flash-preview",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    original = httpx.AsyncClient

    class Client(original):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr("src.gemini.httpx.AsyncClient", Client)
    model = create_gemini(
        Settings(_env_file=None, model="gemini-3-flash-preview", api_key="test-secret")
    )
    trace = TraceRecorder(secrets=["test-secret"])
    messages = decide_messages(initial(), "interpretation", Decision)
    try:
        with recording(trace):
            if bad_response:
                with pytest.raises(ValidationError):
                    await structured_call(model, Decision, messages, {})
            else:
                value, _ = await structured_call(model, Decision, messages, {})
                assert value == DONE
    finally:
        await model.bound.http_async_client.aclose()
    assert requests[0]["messages"][1]["content"] == messages[1].content
    assert requests[0]["response_format"] == {"type": "json_object"}
    span = trace.spans[0]
    assert span["http_request"]["body"] == requests[0]
    assert span["output"]["sdk_response"]["content"] == content
    assert span["status"] == ("error" if bad_response else "success")
    assert "test-secret" not in json.dumps(trace.spans)
