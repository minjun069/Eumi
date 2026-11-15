"""같은 실행 코드에서 State 이벤트별 명세·검증·하위 실행·재개를 확인한다."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
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
from tests.helpers import ScriptedModel, section

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
}
ACT = {"next": "act", "reason": "요청한 표시 설정의 검증 필요"}
DONE = {"next": "compose", "reason": "검사 완료"}
COMPOSE = {
    "content": "검사 결과 안내",
    "artifact_ids": [],
    "status": "partial",
    "reason": "검사",
}


class Model(ScriptedModel):
    def __init__(self, replies=None):
        super().__init__(replies or [])
        self.automatic = replies is None
        self.messages = self.inputs

    def with_structured_output(self, schema, **kwargs):
        if not self.automatic:
            return super().with_structured_output(schema, **kwargs)

        async def invoke(messages, config):
            self.inputs.append(messages)
            needs_work = schema["title"] == "Decision" and not any(
                item["decision"] == "call"
                for item in section(messages, "작업 결과와 검증 이력")
            )
            reply = {
                "Interpretation": INTERPRET,
                "Selection": selection(view_key=MAP),
                "Decision": ACT if needs_work else DONE,
                "Composition": COMPOSE,
            }[schema["title"]]
            return {"raw": AIMessage(json.dumps(reply, ensure_ascii=False))}

        return RunnableLambda(invoke)


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
    result = tool.invoke({"view_key": forbidden, "event": "user_request"})
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
        {"analysis_pipeline": [MAP]},
        {"analysis_pipeline": ["missing"], "user_request": []},
    ],
)
def test_bad_event_mapping_is_configuration_error(catalog, mapping):
    with pytest.raises(ValueError):
        tableau_catalog.validate_catalog(catalog | {"event_views": mapping})


def test_unknown_state_event_rejected():
    with pytest.raises(ValidationError):
        initial("unknown")


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
    # 지도·기간 분포·상세 뷰의 서로 다른 입력 규격만 대표로 검사한다.
    for key in ("Embed01RiskMap", "Embed02RiskDistribution", "EmbedDetailV01"):
        state = initial("analysis_pipeline")
        result = validate_visualization({"view_key": key}, state=state)
        assert result["valid"] is (key in detail)
        user_result = validate_visualization({"view_key": key}, state=initial())
        assert user_result["valid"]
        registered = catalog["views"][key]
        assert user_result["artifact"]["data"]["src"].endswith(
            f"/{registered['workbook']}/{registered['view_name']}"
        )
    result = validate_visualization(
        {
            "view_key": "EmbedDetailV01",
            "parameters": {"p_detail_adm": "춘천시 후평3동"},
        },
        state=initial(),
    )
    assert result["valid"]
    assert {p["name"]: p["value"] for p in result["artifact"]["data"]["parameters"]}[
        "p_detail_adm"
    ] == "춘천시 후평3동"
    invalid = validate_visualization(
        {"view_key": "EmbedDetailV01", "parameters": {"p_detail_adm": "5111061100"}},
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
            "decide" if event == "analysis_pipeline" else "interpret"
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


@pytest.mark.asyncio
async def test_child_inherits_event_and_cannot_call_other_event_view(catalog):
    event = "analysis_pipeline"
    model = Model(
        [
            ACT,
            selection("visualization_agent", goal="시각화"),
            ACT,
            selection(view_key=OTHER),
            DONE,
            COMPOSE,
            DONE,
            COMPOSE,
        ]
    )
    result = await run_graph(graph(model, role="request"), initial(event))
    child = next(r["output"] for r in result["results"] if r["decision"] == "call")
    assert child["execution"]["event"] == event
    called = next(r["output"] for r in child["results"] if r["decision"] == "call")
    assert called["issues"][0]["code"] == "view_not_allowed"


@pytest.mark.asyncio
async def test_rebuilt_graph_resumes_saved_event_without_scope_injection(catalog):
    event, key = "analysis_pipeline", MAP
    saver = InMemorySaver()
    waiting = await run_graph(
        graph(
            Model(
                [
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
                ACT,
                selection(view_key=key),
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


@pytest.mark.usefixtures("all_tableau_views")
def test_followup_receives_selected_city_only_and_is_isolated():
    artifact = validate_visualization(
        {"view_key": "Embed01RiskMap", "parameters": {"p_city": "11680"}},
        state=initial(),
    )["artifact"]
    state = {"response": {"artifacts": [artifact]}}
    state["execution"] = initial()["execution"]
    context = visualization_context(state, include_inputs=True)
    selected = context["selected"]["Embed01RiskMap"]["filters"]["읍면동"]["allowed"]
    assert "역삼1동" in selected and "후평3동" not in selected
    selected.clear()
    assert visualization_context(state, include_inputs=True)["selected"][
        "Embed01RiskMap"
    ]["filters"]["읍면동"]["allowed"]


@pytest.mark.usefixtures("all_tableau_views")
def test_invalid_dependency_does_not_expose_default_domain_as_selected():
    state = {
        "results": [
            {
                "action": {
                    "name": "validate_visualization",
                    "arguments": {
                        "view_key": "Embed01RiskMap",
                        "parameters": {"p_city": 51110},
                    },
                }
            }
        ]
    }
    state["execution"] = initial()["execution"]
    context = visualization_context(state, include_inputs=True)
    assert "allowed" not in context["selected"]["Embed01RiskMap"]["filters"]["읍면동"]


@pytest.mark.usefixtures("all_tableau_views")
def test_latest_attempt_supersedes_previous_view_conditions():
    artifact = validate_visualization(
        {"view_key": "Embed01RiskMap", "parameters": {"p_city": "11680"}},
        state=initial(),
    )["artifact"]
    state = {
        "response": {"artifacts": [artifact]},
        "results": [
            {
                "action": {
                    "name": "validate_visualization",
                    "arguments": {
                        "view_key": "Embed01RiskMap",
                        "parameters": {"p_city": "51110"},
                    },
                }
            }
        ],
    }
    state["execution"] = initial()["execution"]
    context = visualization_context(state, include_inputs=True)
    selected = context["selected"]["Embed01RiskMap"]["filters"]["읍면동"]["allowed"]
    assert "후평3동" in selected and "역삼1동" not in selected
