"""같은 실행 코드에서 State 이벤트별 명세·검증·하위 실행·재개를 확인한다."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from src import visualization_instructions
from src.agent_nodes import build_nodes, finish
from src.graph import compile_graph
from src.runtime import resume_graph, run_graph
from src.settings import Settings
from src.state import create_state, state_adapter
from src.tools import tableau, tableau_catalog
from src.tools.interface import create_tools
from src.tools.tableau import validate_visualization
from src.visualization_instructions import visualization_context

MAP = "Embed01RiskMap"
OTHER = "Embed03Vulnerability"
EVENTS = ("analysis_pipeline", "user_request")


def initial(event="user_request"):
    return create_state(
        {"goal": "이벤트별 시각화 검증"},
        Settings(_env_file=None),
        messages=[],
        version="test",
        event=event,
    )


@pytest.fixture
def catalog(monkeypatch):
    value = json.loads(
        Path(tableau_catalog.__file__)
        .with_name("tableau_catalog.json")
        .read_text(encoding="utf-8")
    )
    value["event_views"] = {"analysis_pipeline": [MAP], "user_request": [OTHER]}
    value = tableau_catalog.validate_catalog(value)
    for module in (tableau_catalog, tableau, visualization_instructions):
        monkeypatch.setattr(module, "registered_catalog", lambda: value)
    return value


def selection(name="validate_visualization", **args):
    return {"name": name, "arguments_json": json.dumps(args), "reason": "검증"}


INTERPRET = {
    "request": {"goal": "이벤트별 시각화 검증"},
    "reason": "확인",
    "needs_input": False,
}
ACCEPT = {"accepted": True, "reason": "조건 확인"}
DONE = {"next": "compose", "reason": "검사 완료"}
COMPOSE = {
    "content": "검사 결과 안내",
    "artifact_ids": [],
    "status": "partial",
    "reason": "검사",
}


class Model:
    def __init__(self, replies=None):
        self.replies = iter(replies) if replies is not None else None
        self.messages = []

    async def ainvoke(self, messages, config):
        self.messages.append(messages)
        if self.replies is not None:
            reply = next(self.replies)
        else:
            schema = json.loads(
                messages[0].content.split("아래 JSON Schema를 정확히 준수한다.\n")[1]
            )
            reply = {
                "Interpretation": INTERPRET,
                "Selection": selection(view_key=MAP),
                "Verification": ACCEPT,
                "Decision": DONE,
                "Composition": COMPOSE,
            }[schema["title"]]
        return AIMessage(json.dumps(reply, ensure_ascii=False))


def graph(model, *, role="visualization", saver=None):
    return compile_graph(
        build_nodes(model, {}, [], role=role), finish=finish, checkpointer=saver
    )


@pytest.mark.parametrize("event,key", list(zip(EVENTS, (MAP, OTHER), strict=True)))
def test_event_limits_description_schema_and_validation(catalog, event, key):
    state = initial(event)
    context = visualization_context(state, include_inputs=True)
    assert list(context["views"]) == [key]
    tool = next(
        t for t in create_tools({}, state=state) if t.name == "validate_visualization"
    )
    assert tool.args_schema["properties"]["view_key"]["enum"] == [key]
    assert tool.invoke({"view_key": key})["valid"]
    forbidden = OTHER if key == MAP else MAP
    rejected = tool.invoke({"view_key": forbidden})
    assert not rejected["valid"] and rejected["artifact"] is None
    assert rejected["issues"][0]["code"] == "view_not_allowed"
    assert rejected["issues"][0]["allowed"] == [key]
    for supplied in (
        {"event": "user_request"},
        {"state": initial()},
        {"allowed_view_keys": [forbidden]},
    ):
        result = tool.invoke({"view_key": forbidden, **supplied})
        assert result["issues"][0]["code"] == "invalid_input"
    assert state["execution"]["event"] == event


def test_empty_mapping_and_unrelated_profiles(catalog):
    catalog["input_profiles"]["unrelated"] = {
        "parameters": {},
        "filters": {},
        "date_orders": [],
    }
    catalog["views"][OTHER].update(input_profile="unrelated", filter_targets={})
    assert (
        "unrelated"
        not in visualization_context(initial(EVENTS[0]), include_inputs=True)[
            "input_profiles"
        ]
    )
    catalog["event_views"][EVENTS[0]] = []
    assert visualization_context(initial(EVENTS[0]), include_inputs=True) == {
        "views": {},
        "input_profiles": {},
        "selected": {},
    }
    result = validate_visualization({"view_key": MAP}, state=initial(EVENTS[0]))
    assert result["issues"][0]["allowed"] == [] and result["artifact"] is None


@pytest.mark.parametrize(
    "mapping",
    [
        {},
        {"analysis_pipeline": [MAP]},
        {"analysis_pipeline": ["missing"], "user_request": []},
        {"analysis_pipeline": [MAP, MAP], "user_request": []},
        {"analysis_pipeline": [], "user_request": [], "unknown": []},
    ],
)
def test_bad_event_mapping_is_configuration_error(catalog, mapping):
    with pytest.raises(ValueError):
        tableau_catalog.validate_catalog(catalog | {"event_views": mapping})


@pytest.mark.parametrize("event", [None, "unknown", "", 1])
def test_invalid_state_event_rejected(event):
    with pytest.raises(ValidationError):
        initial(event)


def test_missing_event_is_not_defaulted():
    state = initial()
    del state["execution"]["event"]
    with pytest.raises(ValidationError):
        state_adapter.validate_python(state)


def test_deployed_event_assignment_and_detail_parameter_values():
    catalog = tableau_catalog.visualization_catalog()
    detail = {f"EmbedDetailV{i:02}" for i in range(1, 9)}
    assert tableau_catalog.allowed_views(initial("analysis_pipeline")) == detail
    assert catalog["event_views"]["user_request"] == "all"
    assert tableau_catalog.allowed_views(initial()) == set(catalog["views"])
    assert len(catalog["views"]) == 15
    for key in catalog["views"]:
        state = initial("analysis_pipeline")
        result = validate_visualization({"view_key": key}, state=state)
        assert result["valid"] is (key in detail)
        user_result = validate_visualization({"view_key": key}, state=initial())
        assert user_result["valid"]
        assert "v2_0_6_connection_map_fixed" in user_result["artifact"]["data"]["src"]
    for key in detail | {"EmbedDetailMap"}:
        result = validate_visualization(
            {"view_key": key, "parameters": {"p_detail_adm": "춘천시 후평3동"}},
            state=initial(),
        )
        assert result["valid"]
        assert {
            p["name"]: p["value"] for p in result["artifact"]["data"]["parameters"]
        }["p_detail_adm"] == "춘천시 후평3동"
        invalid = validate_visualization(
            {"view_key": key, "parameters": {"p_detail_adm": "5111061100"}},
            state=initial(),
        )
        assert invalid["issues"][0]["code"] == "invalid_parameter_value"


def test_all_includes_new_registration_without_expanding_explicit_list(catalog):
    catalog["event_views"]["user_request"] = "all"
    catalog["views"]["NewView"] = deepcopy(catalog["views"][MAP])
    tableau_catalog.validate_catalog(catalog)
    assert "NewView" in tableau_catalog.allowed_views(initial())
    assert "NewView" not in tableau_catalog.allowed_views(initial("analysis_pipeline"))
    assert validate_visualization({"view_key": "NewView"}, state=initial())["valid"]
    assert not validate_visualization({"view_key": "unregistered"}, state=initial())[
        "valid"
    ]


@pytest.mark.asyncio
async def test_shared_graph_keeps_concurrent_event_policies_separate(catalog):
    model = Model()
    shared = graph(model)
    states = [initial(event) for event in EVENTS]
    before = deepcopy(states)
    results = await asyncio.gather(*(run_graph(shared, state) for state in states))
    assert states == before
    for event, result in zip(EVENTS, results, strict=True):
        called = next(r["output"] for r in result["results"] if r["decision"] == "call")
        assert called["valid"] is (event == "analysis_pipeline")
        assert result["results"][0]["node"] == (
            "act" if event == "analysis_pipeline" else "interpret"
        )
        assert result["execution"]["event"] == event
    for messages in model.messages:
        marker = "[시각화 목록과 입력 조건]\n"
        if marker in messages[1].content:
            content = messages[1].content
            execution = json.JSONDecoder().raw_decode(
                content.split("[실행 조건]\n")[1]
            )[0]
            visible = json.JSONDecoder().raw_decode(content.split(marker)[1])[0]
            assert list(visible["views"]) == catalog["event_views"][execution["event"]]


@pytest.mark.parametrize("event", EVENTS)
@pytest.mark.asyncio
async def test_child_inherits_event_and_cannot_call_other_event_view(catalog, event):
    start = [INTERPRET] if event == "user_request" else []
    forbidden = OTHER if event == "analysis_pipeline" else MAP
    model = Model(
        [
            *start,
            selection("visualization_agent", goal="시각화"),
            *start,
            selection(view_key=forbidden),
            DONE,
            COMPOSE,
            ACCEPT,
            DONE,
            COMPOSE,
        ]
    )
    result = await run_graph(graph(model, role="request"), initial(event))
    child = next(r["output"] for r in result["results"] if r["decision"] == "call")
    assert child["execution"]["event"] == event
    called = next(r["output"] for r in child["results"] if r["decision"] == "call")
    assert called["issues"][0]["code"] == "view_not_allowed"


@pytest.mark.parametrize("event,key", list(zip(EVENTS, (MAP, OTHER), strict=True)))
@pytest.mark.asyncio
async def test_rebuilt_graph_resumes_saved_event_without_scope_injection(
    catalog, event, key
):
    saver = InMemorySaver()
    start = [INTERPRET] if event == "user_request" else []
    waiting = await run_graph(
        graph(
            Model(
                [
                    *start,
                    selection("none"),
                    {"next": "ask", "reason": "대상 필요"},
                    {"content": "대상을 알려주세요.", "reason": "대상 필요"},
                ]
            ),
            role="request",
            saver=saver,
        ),
        initial(event),
    )
    assert waiting["execution"]["status"] == "waiting_input"
    rebuilt = graph(
        Model(
            [
                INTERPRET,
                selection(view_key=key),
                ACCEPT,
                DONE,
                COMPOSE,
            ]
        ),
        role="request",
        saver=saver,
    )
    resumed = await resume_graph(
        rebuilt,
        waiting["execution"]["run_id"],
        waiting["response"]["id"],
        "위험도 지도",
    )
    assert resumed["execution"]["event"] == event
    called = next(r["output"] for r in resumed["results"] if r["decision"] == "call")
    assert called["valid"]
