"""실제 서비스와 독립 모델 호출의 입력 공유·원문 수집 경계를 검사한다."""

import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import TypeAdapter, ValidationError

from experiments.scenario_fixtures import CATALOG, PROVIDERS
from src.agent_nodes import (
    Decision,
    NoModelCall,
    begin_report_call,
    build_nodes,
    prepare_model_call,
    prepare_report_call,
)
from src.execution import record
from src.execution_trace import TraceRecorder, recording
from src.gemini import raw_call, structured_call
from src.tools.interface import create_tools
from tests.helpers import DONE, ScriptedModel, initial, selection

pytestmark = pytest.mark.usefixtures("all_tableau_views")


def report_state(*, selected=False, draft=False, approved=False, insight=False):
    """업무 실행 대신 이미 확보한 근거·선정·초안 기록만 준비한다."""
    state = initial()
    evidence = record("act", "call", "근거 조회", output={"data": {"rows": []}})
    state["results"].append(evidence)
    if not selected:
        return state
    begin_report_call(
        state,
        "report_selection",
        "select_report_views",
        None,
        [evidence["id"]],
        "근거가 있는 상세 뷰 선정",
    )
    selection = state["results"][-1]
    selection["outcome"] = "success"
    selection["output"] = {
        "views": [
            {
                "view_key": "EmbedDetailV01",
                "reason": "변화 확인",
                "evidence_ids": [evidence["id"]],
            }
        ]
    }
    if not draft and not approved and not insight:
        return state
    state["results"].append(
        record(
            "compose",
            "verification",
            "근거 일치",
            output={
                "call_id": selection["id"],
                "accepted": True,
                "reason": "근거 일치",
            },
        )
    )
    if not draft and not insight:
        return state
    begin_report_call(
        state,
        "report_draft",
        "write_report",
        "EmbedDetailV01",
        [selection["id"], evidence["id"]],
        "보고서 문장 작성",
    )
    description = state["results"][-1]
    description["outcome"] = "success"
    description["output"] = {"content": "확보한 자료의 관측 범위입니다."}
    if insight:
        state["results"].append(
            record(
                "compose",
                "verification",
                "근거 일치",
                output={
                    "call_id": description["id"],
                    "accepted": True,
                    "reason": "근거 일치",
                },
            )
        )
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node,value",
    [
        (
            "interpret",
            {
                "request": {"goal": "지역별 비교", "constraints": {}},
                "reason": "요청 파악",
            },
        ),
        ("act", selection("query_data", {"target": "D3"})),
        ("decide", DONE),
        (
            "compose",
            {
                "content": "확인한 자료입니다.",
                "artifact_ids": [],
                "status": "completed",
                "reason": "작성 완료",
            },
        ),
        ("ask", {"content": "비교 기간은 언제인가요?", "reason": "기간 확인"}),
    ],
)
async def test_generic_preparation_matches_service_messages_and_schema(node, value):
    state = initial("user_request")
    before = deepcopy(state)
    tools = {t.name: t for t in create_tools(PROVIDERS, state=state)}
    prepared = prepare_model_call(
        node, state, role="request", catalog=CATALOG, tools=tools
    )
    assert state == before
    model = ScriptedModel([value])
    await build_nodes(model, PROVIDERS, CATALOG, role="request")[node](
        deepcopy(state), {}
    )
    assert model.inputs == [prepared["messages"]]
    assert model.response_schemas == [TypeAdapter(prepared["schema"]).json_schema()]
    assert model.response_options == [
        {
            "method": "json_schema",
            "strict": prepared["strict"],
            "include_raw": True,
        }
    ]
    assert prepared["strict"] is (node == "act")
    assert prepared["stage"] is None


@pytest.mark.parametrize(
    "role,stage,state_factory,schema_name",
    [
        ("report_selection", "selection", lambda: report_state(), "ReportSelection"),
        (
            "report_selection",
            "selection_review",
            lambda: report_state(selected=True),
            "Verification",
        ),
        (
            "report_description",
            "draft",
            lambda: report_state(selected=True, approved=True),
            "ReportText",
        ),
        (
            "report_description",
            "draft_review",
            lambda: report_state(selected=True, draft=True),
            "Verification",
        ),
        (
            "report_description",
            "review_retry",
            lambda: report_state(selected=True, draft=True),
            "Verification",
        ),
        (
            "report_insight",
            "draft",
            lambda: report_state(selected=True, insight=True),
            "ReportText",
        ),
    ],
)
def test_report_preparation_uses_existing_targets_without_mutating_state(
    role,
    stage,
    state_factory,
    schema_name,
):
    state = state_factory()
    before = deepcopy(state)
    prepared = prepare_model_call(
        "compose", state, role=role, catalog=CATALOG, report_stage=stage
    )
    assert state == before
    assert prepared["schema"].__name__ == schema_name
    assert prepared["stage"] == stage
    context = json.loads(prepared["messages"][1].content)
    pending = context["results"][-1]
    assert pending["output"] is None
    assert pending["outcome"] == "failure"
    assert len(context["results"]) == len(state["results"]) + 1
    original_ids = {item["id"] for item in state["results"]}
    assert set(pending["action"]["arguments"]["result_ids"]) <= original_ids
    if stage in {"draft_review", "review_retry", "selection_review"}:
        assert pending["action"]["arguments"]["result_ids"] == [
            state["results"][-1]["id"]
        ]


def test_existing_pending_report_call_is_reused_and_wrong_stage_rejected():
    state, stage = prepare_report_call(
        report_state(selected=True, draft=True), "report_description", "draft_review"
    )
    before = deepcopy(state)
    prepared = prepare_model_call(
        "compose", state, role="report_description", catalog=CATALOG, report_stage=stage
    )
    context = json.loads(prepared["messages"][1].content)
    assert state == before
    assert context["results"][-1]["id"] == state["results"][-1]["id"]
    assert len(context["results"]) == len(state["results"])
    with pytest.raises(ValueError, match="단계"):
        prepare_report_call(state, "report_description", "draft")


@pytest.mark.parametrize(
    "state,role,stage",
    [
        (report_state(), "report_description", "draft"),
        (report_state(), "report_selection", "selection_review"),
        (report_state(selected=True, approved=True), "report_selection", None),
        (
            report_state(selected=True, approved=True),
            "report_description",
            "draft_review",
        ),
    ],
)
def test_report_without_existing_model_target_is_not_executed(state, role, stage):
    before = deepcopy(state)
    with pytest.raises(ValueError):
        prepare_model_call(
            "compose", state, role=role, catalog=CATALOG, report_stage=stage
        )
    assert state == before


def normalize_report_messages(messages):
    context = json.loads(messages[1].content)
    # 독립 준비·서비스 실행은 서로 다른 새 호출 ID를 부여한다.
    pending = context["results"][-1]
    pending["id"] = "pending"
    return messages[0].content, context


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,state_factory,replies",
    [
        (
            "report_selection",
            lambda: report_state(),
            [
                {"views": []},
                {"accepted": True, "reason": "근거 일치"},
            ],
        ),
        (
            "report_selection",
            lambda: report_state(selected=True),
            [
                {"accepted": True, "reason": "근거 일치"},
            ],
        ),
        (
            "report_description",
            lambda: report_state(selected=True, approved=True),
            [
                {"content": "확보한 자료의 관측 범위입니다."},
                {"accepted": True, "reason": "근거 일치"},
            ],
        ),
        (
            "report_description",
            lambda: report_state(selected=True, draft=True),
            [
                {"accepted": True, "reason": "근거 일치"},
            ],
        ),
        (
            "report_insight",
            lambda: report_state(selected=True, insight=True),
            [
                {"content": "첫째입니다.\n둘째입니다.\n셋째입니다."},
                {"accepted": True, "reason": "근거 일치"},
            ],
        ),
    ],
)
async def test_report_first_call_matches_actual_service(role, state_factory, replies):
    state = state_factory()
    before = deepcopy(state)
    prepared = prepare_model_call("compose", state, role=role, catalog=CATALOG)
    model = ScriptedModel(replies)
    await build_nodes(model, PROVIDERS, CATALOG, role=role)["compose"](
        deepcopy(state), {}
    )
    assert normalize_report_messages(model.inputs[0]) == normalize_report_messages(
        prepared["messages"]
    )
    assert model.response_schemas[0] == TypeAdapter(prepared["schema"]).json_schema()
    assert state == before


class RawModel:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def with_structured_output(self, schema, **options):
        async def invoke(messages, config):
            self.calls.append((schema, options, messages, config))
            return {
                "raw": self.response,
                "parsed": DONE,
                "parsing_error": ValueError("invalid"),
            }

        return RunnableLambda(invoke)


@pytest.mark.asyncio
async def test_raw_call_keeps_malformed_text_and_sdk_evidence_without_validation():
    response = AIMessage(
        "```json\nnot valid JSON\n```",
        response_metadata={"model_name": "raw-model"},
        usage_metadata={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
    )
    model = RawModel(response)
    state = initial()
    before = deepcopy(state)
    prepared = prepare_model_call(
        "decide", state, role="interpretation", catalog=CATALOG
    )
    recorder = TraceRecorder()
    with recording(recorder):
        actual, usage = await raw_call(
            model, prepared["schema"], prepared["messages"], {}
        )
    assert actual is response
    assert usage["model"] == "raw-model"
    assert usage["tokens"] == response.usage_metadata
    assert usage["elapsed_seconds"] >= 0
    assert len(model.calls) == 1
    assert state == before
    span = recorder.spans[0]
    assert span["status"] == "success"
    assert span["output"] == {"sdk_response": response.model_dump(mode="json")}
    with pytest.raises(ValidationError), recording(recorder):
        await structured_call(model, Decision, prepared["messages"], {})
    assert recorder.spans[-1]["status"] == "error"
    assert recorder.spans[-1]["output"]["sdk_response"]["content"] == response.content
    assert model.calls[0][:3] == model.calls[1][:3]
    assert model.calls[0][3]["configurable"] == model.calls[1][3]["configurable"]


@pytest.mark.asyncio
async def test_raw_report_call_does_not_generate_followup_review_or_update_state():
    state = report_state(selected=True, approved=True)
    before = deepcopy(state)
    prepared = prepare_model_call(
        "compose", state, role="report_description", catalog=CATALOG
    )
    model = RawModel(AIMessage('{"content":"새 초안입니다."}'))
    actual, _ = await raw_call(model, prepared["schema"], prepared["messages"], {})
    assert actual.content == '{"content":"새 초안입니다."}'
    assert len(model.calls) == 1
    assert state == before


def test_completed_report_is_distinct_from_missing_target_and_never_finalized():
    completed = report_state(selected=True, approved=True)
    before = deepcopy(completed)
    with pytest.raises(NoModelCall):
        prepare_model_call(
            "compose", completed, role="report_selection", catalog=CATALOG
        )
    assert completed == before
    missing = report_state()
    with pytest.raises(ValueError) as caught:
        prepare_model_call(
            "compose",
            missing,
            role="report_description",
            catalog=CATALOG,
            report_stage="draft_review",
        )
    assert not isinstance(caught.value, NoModelCall)


def test_finalizing_report_has_no_model_call_and_does_not_publish_response():
    state = report_state(selected=True, approved=True)
    state["execution"]["error"] = {
        "code": "execution_limit_exceeded",
        "message": "실행 한도",
        "details": {},
        "retryable": False,
    }
    before = deepcopy(state)
    with pytest.raises(NoModelCall):
        prepare_model_call("compose", state, role="report_description", catalog=CATALOG)
    assert state == before
    assert state["response"] is None
