"""모델·DB 경계만 대체하여 보고서 세 역할의 실제 실행과 공유 State를 검사한다."""

import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from api import create_report_states, execute_reports
from src.execution import accepted_outputs
from src.state import report_artifact
from tests.helpers import section
from tests.test_reports import BODY, ReportModel, generate, setup

ROLES = ("report_selection", "report_description", "report_insight")
NEW_CLAIM = "관측된 점수의 원인은 소득 감소입니다."
DESCRIPTIONS = {
    "EmbedDetailV01": "해당 동의 관측 점수는 42점입니다.",
    "EmbedDetailV02": "비교 가능한 과거 자료는 확보되지 않았습니다.",
    "EmbedDetailV08": "해석은 해당 동의 관측 범위로 제한합니다.",
}


def stage_role(records):
    return next(
        item["action"]["name"].removesuffix("_agent")
        for item in reversed(records)
        if item["decision"] == "report_stage"
    )


def stage_segments(state):
    segments = []
    for item in state["results"]:
        if item["decision"] == "report_stage":
            segments.append((item["action"]["name"].removesuffix("_agent"), []))
        elif segments:
            segments[-1][1].append(item)
    return segments


def recorded_nodes(state, output_dir):
    report = json.loads(
        (output_dir / state["execution"]["run_id"] / "report.json").read_text(
            encoding="utf-8"
        )
    )
    return [span for span in report["trace"]["spans"] if span["kind"] == "node"]


def assert_compose_routes_via_decide(state, output_dir):
    nodes = recorded_nodes(state, output_dir)
    intermediate = []
    for index, node in enumerate(nodes):
        if node["name"] != "compose":
            continue
        output = node["output"]
        assert output["goto"] in {"decide", "__end__"}
        if output["goto"] == "__end__":
            assert output["applied_update"]["response"]["kind"] == "final"
            continue
        assert output["applied_update"]["response"]["kind"] == "intermediate"
        following = nodes[index + 1]
        assert following["name"] == "decide"
        assert stage_role(following["input"]["state"]["results"]) == stage_role(
            node["input"]["state"]["results"]
        )
        intermediate.append((index, node))
    return nodes, intermediate


class AgentReportModel(ReportModel):
    """응답과 일시 오류만 제어한다. 작업·검토·재처리는 실제 업무 코드가 수행한다."""

    def __init__(
        self,
        *,
        additional_query=False,
        additional_query_role="report_description",
        new_claim=False,
        reject_insight=False,
    ):
        super().__init__()
        self.events = []
        self.tools = []
        self.additional_query = additional_query
        self.additional_query_role = additional_query_role
        self.new_claim = new_claim
        self.reject_insight = reject_insight
        self.review_error_once = False
        self.selection_review_error_once = False
        self.selection_review_reject_once = False
        self.selection_review_rejections = 0

    def with_structured_output(self, schema, **kwargs):
        default = super().with_structured_output(schema, **kwargs)

        async def invoke(messages, config):
            kind = schema["title"]
            records = (
                json.loads(messages[1].content)["results"]
                if messages[1].content.startswith("{")
                else section(messages, "작업 결과와 검증 이력")
            )
            role = stage_role(records)
            current = records[-1]
            view = (current.get("action") or {}).get("arguments", {}).get("view_key")
            self.events.append((kind, role, deepcopy(records)))
            queries = [
                item
                for item in records
                if item["decision"] == "call" and item["outcome"] == "success"
            ]
            needs_extra = (
                self.additional_query
                and role == self.additional_query_role
                and any(
                    item["decision"] == "verification"
                    and (item["output"] or {}).get("accepted") is False
                    for item in records
                )
                and len(queries) == 1
            )
            value = None
            if kind == "Selection":
                self.tools.append(section(messages, "도구 명세", system=True))
                arguments = {"target": "public.region_result"}
                if needs_extra:
                    arguments["fields"] = ["bh_score"]
                value = {
                    "name": "query_data",
                    "arguments_json": json.dumps(arguments),
                    "reason": "설명 검토 중 드러난 근거 확인"
                    if needs_extra
                    else "현재 단계의 필요한 작업 선택",
                }
            elif kind == "Decision" and needs_extra:
                value = {
                    "next": "act",
                    "reason": "검토에서 확인한 부족 근거를 추가 조회로 확보한다.",
                }
            elif kind == "ReportText" and not self.fail_once:
                if view:
                    value = {"content": DESCRIPTIONS[view]}
                else:
                    prior = [
                        item
                        for item in records
                        if item["decision"] == "report_draft"
                        and item["action"]["arguments"]["view_key"] is None
                        and item["outcome"] == "success"
                    ]
                    value = {"content": "\n".join(DESCRIPTIONS.values())}
                    if self.reject_insight or (self.new_claim and not prior):
                        value["content"] = "\n".join(
                            [NEW_CLAIM, *list(DESCRIPTIONS.values())[1:]]
                        )
            elif kind == "Verification":
                if self.review_error_once and view == "EmbedDetailV01":
                    self.review_error_once = False
                    self.calls.append((kind, view, deepcopy(messages)))
                    raise ConnectionError("temporary review failure")
                target_ids = current["action"]["arguments"]["result_ids"]
                target = next(item for item in records if item["id"] == target_ids[0])
                if target["decision"] == "report_selection":
                    if self.selection_review_error_once:
                        self.selection_review_error_once = False
                        self.calls.append((kind, view, deepcopy(messages)))
                        raise ConnectionError("temporary selection review failure")
                    if (
                        self.selection_review_reject_once
                        or self.selection_review_rejections
                    ):
                        self.selection_review_reject_once = False
                        self.selection_review_rejections = max(
                            0, self.selection_review_rejections - 1
                        )
                        value = {
                            "accepted": False,
                            "reason": "선정 설명 범위를 근거에 맞게 제한해야 합니다.",
                        }
                    elif (
                        self.additional_query
                        and self.additional_query_role == role
                        and len(queries) < 2
                    ):
                        value = {
                            "accepted": False,
                            "reason": "선정 근거가 부족하여 추가 조회가 필요합니다.",
                        }
                elif target["decision"] == "report_draft":
                    if (
                        self.additional_query
                        and self.additional_query_role == role
                        and view in {"EmbedDetailV01", None}
                        and len(queries) < 2
                    ):
                        value = {
                            "accepted": False,
                            "reason": "작성 근거가 부족하여 추가 조회가 필요합니다.",
                        }
                    elif role == "report_insight":
                        unsupported = NEW_CLAIM in target["output"]["content"]
                        value = {
                            "accepted": not unsupported,
                            "reason": "검증된 설명에 없는 원인 주장을 제거해야 합니다."
                            if unsupported
                            else "검증된 설명의 범위와 일치합니다.",
                        }
            if value is None:
                return await default.ainvoke(messages, config)
            self.calls.append((kind, view, deepcopy(messages)))
            return {"raw": AIMessage(json.dumps(value, ensure_ascii=False))}

        return RunnableLambda(invoke)


@pytest.mark.asyncio
async def test_each_report_agent_runs_common_nodes_in_order_with_immutable_inputs(
    tmp_path,
):
    model = AgentReportModel()
    state, db = await generate(tmp_path, model)
    assert state["execution"]["status"] == "completed"
    assert [role for role, _ in stage_segments(state)] == list(ROLES)
    for role, records in stage_segments(state):
        assert {"decide", "compose"} <= {item["node"] for item in records}
        kinds = [kind for kind, current_role, _ in model.events if current_role == role]
        assert kinds[0] == "Decision"
        assert ("Selection" in kinds) == (role == ROLES[0])
        assert ("act" in {item["node"] for item in records}) == (role == ROLES[0])
        assert "ReportSelection" in kinds if role == ROLES[0] else "ReportText" in kinds
    selected = next(
        item for item in state["results"] if item["decision"] == "report_selection"
    )
    for _, role, records in model.events:
        if role != ROLES[0]:
            inherited = next(item for item in records if item["id"] == selected["id"])
            assert inherited["output"]["views"] == selected["output"]["views"]
    assert (
        len(
            [
                item
                for item in state["results"]
                if item["decision"] == "report_selection"
            ]
        )
        == 1
    )
    assert all(
        not tool["function"]["name"].endswith("_agent")
        for tools in model.tools
        for tool in tools
    )
    assert all(
        not item["action"]["name"].endswith("_agent")
        for item in state["results"]
        if item["decision"] == "call"
    )
    assert len(db.saved) == 1


@pytest.mark.asyncio
async def test_description_review_can_fetch_evidence_and_resume_its_own_agent(tmp_path):
    model = AgentReportModel(additional_query=True)
    state, db = await generate(tmp_path, model)
    selected = next(
        item for item in state["results"] if item["decision"] == "report_selection"
    )
    description = next(
        records for role, records in stage_segments(state) if role == ROLES[1]
    )
    additional = [item for item in description if item["decision"] == "call"]
    drafts = [
        item
        for item in description
        if item["decision"] == "report_draft"
        and item["action"]["arguments"]["view_key"] == "EmbedDetailV01"
    ]
    assert len(additional) == 1 and len(drafts) == 2
    rejected = next(
        item
        for item in description
        if item["decision"] == "verification"
        and item["output"].get("accepted") is False
    )
    assert description.index(drafts[0]) < description.index(rejected)
    assert (
        description.index(rejected)
        < description.index(additional[0])
        < description.index(drafts[1])
    )
    assert additional[0]["id"] in drafts[1]["action"]["arguments"]["result_ids"]
    assert all(
        additional[0]["id"] not in view["evidence_ids"]
        for view in selected["output"]["views"]
    )
    assert [role for role, _ in stage_segments(state)] == list(ROLES)
    assert state["execution"]["budget"]["tool_calls"]["used"] == 2
    assert state["execution"]["budget"]["retries"]["used"] == 1
    assert state["execution"]["status"] == "completed" and db.saved[0]["desc_1"]
    nodes, intermediate = assert_compose_routes_via_decide(state, tmp_path)
    assert len(intermediate) == 1
    index, _ = intermediate[0]
    assert [node["name"] for node in nodes[index : index + 5]] == [
        "compose",
        "decide",
        "act",
        "decide",
        "compose",
    ]
    decision = next(
        item
        for item in description
        if item["decision"] == "decision" and item["output"]["next"] == "act"
    )
    assert description.index(rejected) < description.index(decision)
    assert description.index(decision) < description.index(additional[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ROLES[0], ROLES[2]])
async def test_selection_and_insight_fetch_only_after_their_progress_decision(
    tmp_path, role
):
    model = AgentReportModel(additional_query=True, additional_query_role=role)
    state, db = await generate(tmp_path, model)
    nodes, intermediate = assert_compose_routes_via_decide(state, tmp_path)
    assert len(intermediate) == 1
    index, node = intermediate[0]
    assert stage_role(node["input"]["state"]["results"]) == role
    assert [item["name"] for item in nodes[index : index + 5]] == [
        "compose",
        "decide",
        "act",
        "decide",
        "compose",
    ]
    records = next(items for current, items in stage_segments(state) if current == role)
    added = [item for item in records if item["decision"] == "call"][-1]
    draft = next(
        item
        for item in reversed(records)
        if item["decision"] in {"report_selection", "report_draft"}
    )
    assert added["id"] in draft["action"]["arguments"]["result_ids"]
    assert [current for current, _ in stage_segments(state)] == list(ROLES)
    if role == ROLES[2]:
        upstream = {
            item["id"]: item
            for item in node["input"]["state"]["results"]
            if item["decision"] in {"report_selection", "report_draft"}
        }
        assert upstream
        for item in state["results"]:
            if item["id"] in upstream:
                assert item == upstream[item["id"]]
        assert NEW_CLAIM not in db.saved[0]["quick_insight"]
    budget = assert_actual_usage(state, tmp_path)
    assert budget["tool_calls"]["used"] == 2
    assert budget["retries"]["used"] == 1
    assert state["execution"]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES[:2])
async def test_existing_evidence_revision_returns_to_compose_without_work_selection(
    tmp_path, role
):
    model = AgentReportModel()
    if role == ROLES[0]:
        model.selection_review_reject_once = True
    else:
        model.reject = {"EmbedDetailV01": 1}
    state, _ = await generate(tmp_path, model)
    nodes, intermediate = assert_compose_routes_via_decide(state, tmp_path)
    assert len(intermediate) == 1
    index, node = intermediate[0]
    assert stage_role(node["input"]["state"]["results"]) == role
    assert [item["name"] for item in nodes[index : index + 3]] == [
        "compose",
        "decide",
        "compose",
    ]
    assert [kind for kind, _, _ in model.events].count("Selection") == 1
    budget = assert_actual_usage(state, tmp_path)
    assert budget["tool_calls"]["used"] == 1
    assert budget["retries"]["used"] == 1
    assert state["execution"]["status"] == "completed"


@pytest.mark.asyncio
async def test_selection_revisions_use_shared_budget_without_description_revision_cap(
    tmp_path,
):
    model = AgentReportModel()
    model.selection_review_rejections = 4
    state, _ = await generate(tmp_path, model)
    _, intermediate = assert_compose_routes_via_decide(state, tmp_path)
    assert len(intermediate) == 4
    assert [kind for kind, _, _ in model.events].count("ReportSelection") == 5
    assert [role for role, _ in stage_segments(state)] == list(ROLES)
    assert not any(item["decision"] == "report_retry" for item in state["results"])
    assert assert_actual_usage(state, tmp_path)["retries"]["used"] == 4
    assert state["execution"]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_all", [False, True])
async def test_insight_new_claims_are_revised_or_null_without_upstream_execution(
    tmp_path, reject_all
):
    model = AgentReportModel(new_claim=True, reject_insight=reject_all)
    state, db = await generate(tmp_path, model)
    insights = [
        item
        for item in state["results"]
        if item["decision"] == "report_draft"
        and item["action"]["arguments"]["view_key"] is None
    ]
    assert len(insights) == (4 if reject_all else 2)
    assert [role for role, _ in stage_segments(state)] == list(ROLES)
    descriptions = [
        item
        for item in state["results"]
        if item["decision"] == "report_draft"
        and item["action"]["arguments"]["view_key"] is not None
    ]
    assert len(descriptions) == 3
    available = accepted_outputs(state)
    for description in descriptions:
        assert description["id"] in available
        assert description["id"] in insights[0]["action"]["arguments"]["result_ids"]
    assert insights[0]["id"] not in available
    assert not any(item["decision"] == "report_retry" for item in state["results"])
    assert all(db.saved[0][f"desc_{index}"] for index in range(1, 4))
    nodes, intermediate = assert_compose_routes_via_decide(state, tmp_path)
    assert len(intermediate) == (3 if reject_all else 1)
    for index, _ in intermediate:
        assert [item["name"] for item in nodes[index : index + 3]] == [
            "compose",
            "decide",
            "compose",
        ]
    assert [kind for kind, _, _ in model.events].count("Selection") == 1
    if reject_all:
        assert db.saved[0]["quick_insight"] is None
        assert state["execution"]["status"] == "partial"
    else:
        assert NEW_CLAIM not in db.saved[0]["quick_insight"]
        assert state["execution"]["status"] == "completed"


def assert_actual_usage(state, output_dir):
    nodes = recorded_nodes(state, output_dir)
    budget = state["execution"]["budget"]
    assert budget["steps"]["used"] == len(nodes)
    assert budget["tool_calls"]["used"] == len(
        [item for item in state["results"] if item["decision"] == "call"]
    )
    assert budget["agent_calls"]["used"] == 0
    usage = [
        span["input"]["state"]["execution"]["budget"]["steps"]["used"] for span in nodes
    ]
    assert usage == list(range(len(nodes)))
    for resource in ("steps", "tool_calls", "active_seconds"):
        for previous, current in zip(nodes, nodes[1:], strict=False):
            assert (
                current["input"]["state"]["execution"]["budget"][resource]
                == (
                    previous["output"]["applied_update"]["execution"]["budget"][
                        resource
                    ]
                )
            )
        assert (
            budget[resource]
            == (nodes[-1]["output"]["applied_update"]["execution"]["budget"][resource])
        )
    return budget


@pytest.mark.asyncio
async def test_stage_transitions_share_budget_without_reset_or_double_count(tmp_path):
    state, _ = await generate(tmp_path, AgentReportModel())
    budget = assert_actual_usage(state, tmp_path)
    assert budget["steps"]["used"] == 8
    assert budget["tool_calls"]["used"] == 1
    assert budget["retries"]["used"] == 0


@pytest.mark.asyncio
async def test_error_retry_resumes_failed_agent_and_keeps_prior_outputs_and_usage(
    tmp_path,
):
    model = AgentReportModel()
    model.fail_once = "EmbedDetailV02"
    state, db = await generate(tmp_path, model)
    assert [role for role, _ in stage_segments(state)] == [
        *ROLES[:2],
        ROLES[1],
        ROLES[2],
    ]
    assert len([kind for kind, _, _ in model.events if kind == "ReportSelection"]) == 1
    assert [view for kind, view, _ in model.calls if kind == "ReportText"].count(
        "EmbedDetailV01"
    ) == 1
    assert [view for kind, view, _ in model.calls if kind == "ReportText"].count(
        "EmbedDetailV02"
    ) == 2
    budget = assert_actual_usage(state, tmp_path)
    assert budget["retries"]["used"] == 1
    assert state["execution"]["status"] == "completed" and len(db.saved) == 1


@pytest.mark.asyncio
async def test_review_error_retry_and_later_revision_are_counted_once_each(
    tmp_path,
):
    model = AgentReportModel(additional_query=True)
    model.review_error_once = True
    state, db = await generate(tmp_path, model)
    assert [role for role, _ in stage_segments(state)] == [
        *ROLES[:2],
        ROLES[1],
        ROLES[2],
    ]
    drafts = [
        item
        for item in state["results"]
        if item["decision"] == "report_draft"
        and item["action"]["arguments"]["view_key"] == "EmbedDetailV01"
    ]
    assert len(drafts) == 2
    assert state["execution"]["budget"]["retries"]["used"] == 2
    assert state["execution"]["status"] == "completed" and db.saved[0]["desc_1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_after_retry", [False, True])
async def test_selection_review_error_preserves_selection_and_retries_only_review(
    tmp_path,
    reject_after_retry,
):
    model = AgentReportModel()
    model.selection_review_error_once = True
    model.selection_review_reject_once = reject_after_retry
    state, db = await generate(tmp_path, model)
    selections = [
        item for item in state["results"] if item["decision"] == "report_selection"
    ]
    original = selections[0]
    reviews = [
        item
        for item in state["results"]
        if item["decision"] == "verification"
        and item["action"]
        and item["action"]["arguments"]["result_ids"] == [original["id"]]
    ]
    assert original["outcome"] == "success"
    assert [item["outcome"] for item in reviews] == ["failure", "success"]
    assert reviews[1]["output"]["accepted"] is not reject_after_retry
    assert len(selections) == (2 if reject_after_retry else 1)
    retry = next(
        item for item in state["results"] if item["decision"] == "report_retry"
    )
    assert state["results"].index(reviews[0]) < state["results"].index(retry)
    assert state["results"].index(retry) < state["results"].index(reviews[1])
    if reject_after_retry:
        assert state["results"].index(reviews[1]) < state["results"].index(
            selections[1]
        )
        assert original["id"] not in accepted_outputs(state)
    else:
        assert original["id"] in accepted_outputs(state)
    assert [role for role, _ in stage_segments(state)] == [ROLES[0], *ROLES]
    budget = assert_actual_usage(state, tmp_path)
    assert budget["retries"]["used"] == (2 if reject_after_retry else 1)
    assert state["execution"]["status"] == "completed" and len(db.saved) == 1


@pytest.mark.asyncio
async def test_shared_step_limit_preserves_reviewed_results_and_does_not_restart_budget(
    tmp_path,
):
    settings, db = setup(tmp_path)
    states = create_report_states(BODY, settings)
    states[0]["execution"]["budget"]["steps"]["limit"] = 6
    await db.prepare_report(states[0])
    await execute_reports(states, database=db, model=AgentReportModel())
    state = states[0]
    row = report_artifact(state)
    assert row["graph_1"] == "EmbedDetailV01" and row["desc_1"]
    assert row["quick_insight"] is None
    assert row == db.saved[0]
    assert state["execution"]["budget"]["steps"] == {"used": 6, "limit": 6}
    assert state["execution"]["budget"]["final_model_calls"]["used"] <= 1
    assert state["execution"]["status"] == "partial"
    assert not any(item["decision"] == "report_retry" for item in state["results"])


@pytest.mark.asyncio
async def test_step_limit_after_review_stops_before_decision_and_preserves_upstream(
    tmp_path,
):
    settings, db = setup(tmp_path)
    states = create_report_states(BODY, settings)
    states[0]["execution"]["budget"]["steps"]["limit"] = 8
    await db.prepare_report(states[0])
    model = AgentReportModel(
        additional_query=True, additional_query_role="report_insight"
    )

    await execute_reports(states, database=db, model=model)

    state = states[0]
    nodes = recorded_nodes(state, tmp_path)
    assert [node["name"] for node in nodes[-3:]] == ["compose", "decide", "compose"]
    rejected, limited, finalized = nodes[-3:]
    assert rejected["output"]["goto"] == "decide"
    assert rejected["output"]["applied_update"]["response"]["kind"] == "intermediate"
    assert limited["output"]["node_update"] is None
    assert limited["output"]["goto"] == "compose"
    assert finalized["output"]["goto"] == "__end__"
    assert finalized["output"]["applied_update"]["response"]["kind"] == "final"
    assert [kind for kind, role, _ in model.events if role == "report_insight"] == [
        "Decision",
        "ReportText",
        "Verification",
    ]
    assert [role for role, _ in stage_segments(state)] == list(ROLES)
    upstream = {
        item["id"]: item
        for item in rejected["input"]["state"]["results"]
        if item["decision"] in {"report_selection", "report_draft", "verification"}
    }
    for item in state["results"]:
        if item["id"] in upstream:
            assert item == upstream[item["id"]]
    row = report_artifact(state)
    assert [row[f"desc_{index}"] for index in range(1, 4)] == list(
        DESCRIPTIONS.values()
    )
    assert row["quick_insight"] is None and db.saved == [row]
    budget = state["execution"]["budget"]
    assert budget["steps"] == {"used": 8, "limit": 8}
    assert budget["tool_calls"]["used"] == 1
    assert budget["retries"]["used"] == 0
    assert budget["final_model_calls"]["used"] <= 1
    assert state["execution"]["status"] == "partial"
    assert any(item["decision"] == "limit_reached" for item in state["results"])
    assert not any(item["decision"] == "report_retry" for item in state["results"])
