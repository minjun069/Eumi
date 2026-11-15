"""User fixtures derive necessary work from the request and its evidence."""

import asyncio
import json
from copy import deepcopy
from decimal import Decimal
from itertools import product
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from eval.nodes.criteria import load_criteria, select_rows
from eval.nodes.inputs import select_inputs
from eval.nodes.llm import _prompt as judge_prompt
from eval.nodes.rules import _compare
from eval.scripts.node_dataset_basic_users import (
    CONDITIONS,
    ROLES,
    build_basic_user_paths,
)
from eval.scripts.node_dataset_paths import PathRecorder, assemble_paths, validate_paths
from eval.scripts.node_dataset_users import LIMIT, REGION
from eval.scripts.validate_node_dataset import _prompt as prepare_prompt
from src.agent_nodes import Interpretation
from src.settings import Settings
from src.tools.tableau_catalog import registered_catalog

ROOT = Path(__file__).resolve().parents[2] / "eval/scenarios/nodes"


@pytest.fixture(scope="module")
def built():
    snapshot = json.loads((ROOT / "snapshots/data.json").read_text(encoding="utf-8"))
    recorder = PathRecorder(snapshot)
    asyncio.run(build_basic_user_paths(snapshot, recorder))
    cases, sidecar = assemble_paths([], [], recorder)
    return snapshot, cases, sidecar


def path_for(built, role, condition):
    return next(
        path
        for path in built[2]["scenarios"]
        if path["agent_role"] == role and path["conversation_condition"] == condition
    )


def calls(path, *, frame=None):
    return [
        (
            step,
            step["model_outputs"][0],
            json.loads(step["model_outputs"][0]["arguments_json"]),
        )
        for step in path["steps"]
        if step["node"] == "act" and (frame is None or step["frame"] == frame)
    ]


def test_every_role_and_conversation_condition_is_a_complete_agent_path(built):
    _, cases, sidecar = built
    paths = sidecar["scenarios"]
    assert len(paths) == 12
    assert {
        (path["agent_role"], path["conversation_condition"]) for path in paths
    } == set(product(ROLES, CONDITIONS))
    assert all(path["scope"] == "agent" for path in paths)
    assert all(path["terminal"]["status"] == "completed" for path in paths)
    assert not sidecar["partial_groups"]
    assert not validate_paths(sidecar, cases)


def test_new_execution_uses_dialogue_without_restored_internal_results(built):
    selection = built[0]["selection"]
    for path in built[2]["scenarios"]:
        state = path["start_state"]
        condition, role = path["conversation_condition"], path["agent_role"]
        assert state["results"] == [] and state["response"] is None
        assert "task_rationale" not in state
        assert [message["type"] for message in state["messages"]] == (
            ["human"] if condition == "none" else ["human", "ai", "human"]
        )
        goal = path["steps"][0]["model_outputs"][0]["request"]["goal"]
        assert path["task_rationale"]["user_requirement"] == goal
        assert (
            path["task_rationale"]["available_evidence"]
            and path["task_rationale"]["necessary_work"]
        )
        if condition == "new_topic":
            assert selection["comparison_dong_name"] in state["messages"][0]["content"]
            assert selection["comparison_dong_name"] not in goal
        if condition == "clarification_complete":
            assert "어느 지역" in state["messages"][-2]["content"]
            assert selection["dong_code"] in state["messages"][-1]["content"]
            assert not any(step["node"] == "ask" for step in path["steps"])
        if condition == "revision" and role == "visualization":
            assert "같은 동" in state["messages"][-1]["content"]
            assert selection["previous_month"] in str(
                state["request"]["constraints"]["preferred"]
            )
            assert selection["month"] in goal


def test_interpret_and_selection_follow_the_current_node_contract(built):
    for path in built[2]["scenarios"]:
        previous = {}
        for step in path["steps"]:
            if step["node"] == "interpret":
                TypeAdapter(Interpretation).validate_python(step["model_outputs"][0])
                assert step["expected_next_nodes"] == ["decide"]
            if step["node"] == "act":
                preceding = previous[step["frame"]]
                assert preceding["node"] == "decide"
                assert preceding["model_outputs"][0]["next"] == "act"
                assert step["model_outputs"][0]["name"] != "none"
            previous[step["frame"]] = step


@pytest.mark.parametrize("check", ["N01-O.2", "N01-O.1"])
async def test_interpret_judge_uses_runtime_evidence_without_authored_answers(
    built, check
):
    snapshot, cases, _ = built
    catalog = load_criteria()
    selected_cases = [case for case in cases if case["target"] == "interpret"]
    assert len(selected_cases) == 15
    for case in selected_cases:
        before = deepcopy(case)
        assessment = case["assessment"]
        reference = assessment["reference"][check]
        expected = [
            item for item in assessment["expected"]["items"] if item["check"] == check
        ]
        assert len(expected) == 1
        assert "value" not in expected[0]
        prepared = await prepare_prompt(case, snapshot, Settings(_env_file=None))
        node = {"node": "interpret", "role": case["role"]}
        call = {
            "id": "model-1",
            "name": "Interpretation",
            "path": "/trace/spans/1",
            "messages": prepared["messages"],
            # Missing output content is judged against the actual request.
            "output": {"request": {"goal": "불완전한 목표"}, "reason": "조건 누락"},
        }
        row = select_rows(catalog["checks"][check], node, call)["rows"][0]
        evidence = select_inputs(row, node, call, expected)
        assert not evidence["missing_inputs"]
        messages, prompt = judge_prompt(row, catalog, evidence, expected)
        legacy = deepcopy(expected)
        legacy[0].update(
            value={**reference, "answer": "LEGACY_ANSWER_CANARY"},
            path="/request",
            match="equal",
            applicable=False,
            reason="LEGACY_REASON_CANARY",
            tolerance={"absolute": 123},
            pattern="LEGACY_PATTERN_CANARY",
            extract="text",
        )
        legacy_evidence = select_inputs(row, node, call, legacy, reference)
        assert legacy_evidence == evidence
        assert judge_prompt(row, catalog, legacy_evidence, legacy) == (messages, prompt)
        sent = "\n".join(message.content for message in messages)
        assert "LEGACY_" not in sent
        assert "기대" not in sent and "[별도 평가 자료]" not in sent
        assert "불완전한 목표" in sent
        assert any(label.startswith("입력 ") for label in prompt["evidence_labels"])
        assert prompt["expectation_ids"] == {"항목 1": expected[0]["id"]}
        assert case == before


def test_request_definition_revision_needs_no_fresh_analysis_or_delegation(built):
    path = path_for(built, "request", "revision")
    before = path["start_state"]["messages"][1]["content"]
    latest = path["start_state"]["messages"][-1]["content"]
    assert "정의와 한계는 유지" in latest and "새 수치나 비교·해석은 추가하지" in latest
    assert "학습 기준 행동과의 차이" in before and "개인의 고립 상태" in before
    assert path["task_rationale"]["missing_evidence"] == []
    assert calls(path) == []
    assert {step["frame"] for step in path["steps"]} == {"root"}
    decision = next(step for step in path["steps"] if step["node"] == "decide")
    assert decision["model_outputs"][0]["next"] == "compose"
    assert "이전 실제 답변" in decision["model_outputs"][0]["reason"]
    response = path["terminal"]["state"]["response"]
    assert response["artifacts"] == []
    assert response["content"] == (
        "행동 이상 점수는 기준으로 학습한 행동과 다른 정도를 보여줍니다. "
        "실제 활동량이나 개인의 고립 상태를 확인한 값은 아닙니다."
    )
    assert not any(character.isdigit() for character in response["content"])
    assert path["evidence_refs"][0]["conversation"] == "start_state.messages"


def test_interpretation_revision_adds_requested_comparison_evidence(built):
    path = path_for(built, "interpretation", "revision")
    parent_input = path["entry_transition"]["parent_start_state"]
    prior, latest = (
        parent_input["messages"][1]["content"],
        parent_input["messages"][-1]["content"],
    )
    assert "학습 기준 행동과의 차이" in prior
    assert "정의와 한계는 유지" in latest
    assert "실제 행동 이상 점수·차이·출처를 추가" in latest
    assert "새 수치나 비교·해석은 추가하지" not in latest
    assert path["task_rationale"]["missing_evidence"]
    assert "전문 에이전트 위임" not in path["task_rationale"]["excluded_work"]
    assert [output["name"] for _, output, _ in calls(path)] == [
        "query_data",
        "query_data",
        "process_data",
    ]
    content = path["terminal"]["state"]["response"]["content"]
    assert LIMIT in content and REGION in content


def test_specialists_begin_at_actual_parent_delegation_and_return_to_that_call(built):
    for path in built[2]["scenarios"]:
        entry = path.get("entry_transition")
        start = path["start_state"]
        if path["agent_role"] == "request":
            assert entry is None
            assert start["execution"]["budget"]["steps"]["used"] == 0
            assert start["execution"]["budget"]["agent_calls"]["used"] == 0
            continue
        assert entry["kind"] == "agent_call" and entry["parent_role"] == "request"
        assert entry["after_state"] == start == path["steps"][0]["before_state"]
        assert path["steps"][0]["frame"] == "root"
        parents = entry["parent_steps"]
        assert [step["node"] for step in parents] == ["interpret", "decide", "act"]
        assert all(step["role"] == "request" for step in parents)
        assert all(
            not ({"case_id", "input_ref", "expectation_ref"} & step.keys())
            for step in parents
        )
        parent_call = parents[-1]
        assert entry["call_step_id"] == parent_call["step_id"]
        assert parent_call["before_state"] == parents[-2]["after_state"]
        assert parents[0]["before_state"] == entry["parent_start_state"]
        choice = parent_call["model_outputs"][0]
        assert choice["name"] == path["agent_role"] + "_agent"
        assert json.loads(choice["arguments_json"])["goal"] == start["request"]["goal"]
        before = parent_call["before_state"]
        assert start["messages"] == before["messages"]
        assert start["request"]["constraints"] == before["request"]["constraints"]
        assert start["results"] == [] and start["response"] is None
        assert start["execution"]["status"] == "queued"
        assert start["execution"]["run_id"] != before["execution"]["run_id"]
        assert start["execution"]["event"] == before["execution"]["event"]
        assert start["execution"]["version"] == before["execution"]["version"]
        assert before["execution"]["budget"]["steps"]["used"] == 2
        assert before["execution"]["budget"]["agent_calls"]["used"] == 0
        expected_budget = deepcopy(before["execution"]["budget"])
        expected_budget["steps"]["used"] += 1
        expected_budget["agent_calls"]["used"] += 1
        assert start["execution"]["budget"] == expected_budget
        returned = next(
            item
            for item in parent_call["after_state"]["results"]
            if item["id"] == entry["parent_return_record_id"]
        )
        assert returned["decision"] == "call" and returned["outcome"] == "success"
        assert returned["output"] == {
            key: path["terminal"]["state"][key]
            for key in ("response", "results", "execution")
        }
        assert (
            parent_call["after_state"]["execution"]["budget"]
            == path["terminal"]["state"]["execution"]["budget"]
        )


def test_request_delegates_the_required_specialty_and_preserves_child_results(built):
    for path in built[2]["scenarios"]:
        children = [step for step in path["steps"] if step["frame"] != "root"]
        if (
            path["agent_role"] != "request"
            or path["conversation_condition"] == "revision"
        ):
            assert children == []
            continue
        specialist = (
            "visualization"
            if path["conversation_condition"] == "new_topic"
            else "interpretation"
        )
        assert {step["role"] for step in children} == {specialist}
        assert children[0]["node"] == "interpret" and children[-1]["node"] == "compose"
        parent_calls = calls(path, frame="root")
        assert len(parent_calls) == 1
        parent, output, _ = parent_calls[0]
        assert output["name"] == specialist + "_agent"
        returned = next(
            item["output"]
            for item in parent["after_state"]["results"]
            if (item.get("action") or {}).get("name") == specialist + "_agent"
            and item["decision"] == "call"
        )
        assert returned["results"] == children[-1]["after_state"]["results"]
        response = path["terminal"]["state"]["response"]
        assert response["content"] == returned["response"]["content"]
        assert response["artifacts"] == returned["response"]["artifacts"]
        if specialist == "visualization":
            assert len(response["artifacts"]) == 1
            assert calls(path)[-1][1]["name"] == "validate_visualization"
            assert calls(path)[-1][2]["view_key"] == "EmbedDetailMap"
            assert not any(
                output["name"] in {"query_data", "process_data"}
                for _, output, _ in calls(path)
            )


def test_delegated_goals_have_task_specific_semantics_without_literal_constraints(
    built,
):
    selected = built[0]["selection"]
    by_id = {case["id"]: case for case in built[1]}
    checked = set()
    for path in built[2]["scenarios"]:
        if path["agent_role"] != "request":
            continue
        assert not any(
            "그대로 전달" in condition or "목표 문구" in condition
            for condition in path["start_state"]["request"]["constraints"]["required"]
        )
        for step, output, args in calls(path, frame="root"):
            goal = args["goal"]
            assert all(
                value in goal
                for value in (selected["dong_code"], selected["month"], "한계")
            )
            assessment = by_id[step["case_id"]]["assessment"]
            ref = assessment["reference"]["N02-O.3"]
            assert ref["allowed_scope"] == goal
            semantics = ref["goal_semantics"]
            assert semantics["region"]["code"] == selected["dong_code"]
            if output["name"] == "interpretation_agent":
                assert all(
                    value in goal
                    for value in (
                        selected["previous_month"],
                        "행동 이상 점수",
                        "비교",
                        "출처",
                    )
                )
                assert semantics["periods"] == {
                    "current": selected["month"],
                    "previous": selected["previous_month"],
                }
                assert semantics["required_details"] == ["자료 출처", "해석 한계"]
            else:
                assert output["name"] == "visualization_agent"
                assert "상세 지도" in goal and "행동 이상 점수" not in goal
                assert semantics["periods"] == {"current": selected["month"]}
                assert "산출물" in semantics["purpose"]
            assert ref["rule_evaluation"] == "미판정"
            items = [
                item
                for item in assessment["expected"]["items"]
                if item["check"] == "N02-O.3"
            ]
            assert items
            for item in items:
                assert item.get("applicable") is not False
                assert "path" not in item and "value" not in item
                assert (
                    _compare("N02-O.3", item, {}, output, ref, {})["verdict"]
                    == "미판정"
                )
            checked.add((path["conversation_condition"], output["name"]))
    assert checked == {
        ("none", "interpretation_agent"),
        ("clarification_complete", "interpretation_agent"),
        ("new_topic", "visualization_agent"),
    }


def test_comparison_paths_obtain_both_months_and_calculate_the_actual_difference(built):
    snapshot = built[0]
    selected = snapshot["selection"]
    rows = {
        row["period_start"]: row
        for row in snapshot["datasets"][REGION]["rows"]
        if row["adm_cd10"] == selected["dong_code"]
    }
    current = Decimal(str(rows[selected["month"] + "-01"]["bh_score"]))
    previous = Decimal(str(rows[selected["previous_month"] + "-01"]["bh_score"]))
    comparisons = [
        *product(("request", "interpretation"), ("none", "clarification_complete")),
        ("interpretation", "revision"),
    ]
    for role, condition in comparisons:
        path = path_for(built, role, condition)
        query_args = [
            args for _, output, args in calls(path) if output["name"] == "query_data"
        ]
        assert {
            next(
                item["value"]
                for item in args["filters"]
                if item["field"] == "period_start"
            )
            for args in query_args
        } == {selected["month"] + "-01", selected["previous_month"] + "-01"}
        process = [
            args for _, output, args in calls(path) if output["name"] == "process_data"
        ]
        assert len(process) == 1
        assert any(
            operation.get("method") == "difference"
            for operation in process[0]["operations"]
        )
        content = path["terminal"]["state"]["response"]["content"]
        assert all(
            str(number) in content for number in (current, previous, current - previous)
        )
        assert REGION in content and LIMIT in content
        assert (
            path["evidence_refs"][0]["reference"]
            == snapshot["datasets"][REGION]["reference"]
        )


def test_current_score_request_requires_only_one_month_and_no_calculation(built):
    path = path_for(built, "interpretation", "new_topic")
    selected = built[0]["selection"]
    requested = calls(path)
    assert [output["name"] for _, output, _ in requested] == ["query_data"]
    assert {item["field"]: item["value"] for item in requested[0][2]["filters"]} == {
        "adm_cd10": selected["dong_code"],
        "period_start": selected["month"] + "-01",
    }
    compose = path["steps"][-1]
    assessment = next(case for case in built[1] if case["id"] == compose["case_id"])[
        "assessment"
    ]
    ref = assessment["reference"]["N-O.1"]
    value = next(
        row["bh_score"]
        for row in built[0]["datasets"][REGION]["rows"]
        if row["adm_cd10"] == selected["dong_code"]
        and row["period_start"] == selected["month"] + "-01"
    )
    assert ref["observations"] == {"after": value}
    assert ref["target"] == {
        "dong_code": selected["dong_code"],
        "months": [selected["month"]],
    }
    assert "independent_calculation" not in ref
    item = next(
        item for item in assessment["expected"]["items"] if item["check"] == "N-O.1"
    )
    assert item["value"] == value
    content = path["terminal"]["state"]["response"]["content"]
    assert str(value) in content and LIMIT in content and REGION in content
    assert all(
        word not in content
        for word in (
            selected["previous_month"],
            "차이 계산",
            "증가했습니다",
            "감소했습니다",
        )
    )
    assert any(
        "전월 자료와 차이 계산은 요청하지" in step["model_outputs"][0]["reason"]
        for step in path["steps"]
        if step["node"] == "decide"
    )


def test_score_difference_oracle_preserves_the_sign(built):
    by_id = {case["id"]: case for case in built[1]}
    compared = set()
    for path in built[2]["scenarios"]:
        for step in path["steps"]:
            if step["node"] != "compose":
                continue
            assessment = by_id[step["case_id"]]["assessment"]
            ref = assessment["reference"]["N-O.1"]
            if "difference" not in ref.get("observations", {}):
                continue
            item = next(
                item
                for item in assessment["expected"]["items"]
                if item["check"] == "N-O.1"
            )
            assert item["value"] == 5.24
            original = deepcopy(step["model_outputs"][0])
            positive, negative = deepcopy(original), deepcopy(original)
            positive["content"] = original["content"].replace(
                "차이는 5.24점", "차이는 +5.24점"
            )
            negative["content"] = original["content"].replace(
                "차이는 5.24점", "차이는 -5.24점"
            )
            assert positive != original and negative != original
            for output, verdict in (
                (original, "통과"),
                (positive, "통과"),
                (negative, "실패"),
            ):
                assert (
                    _compare(
                        "N-O.1",
                        item,
                        {"node": "compose", "role": step["role"]},
                        output,
                        ref,
                        {},
                    )["verdict"]
                    == verdict
                )
            compared.add((path["agent_role"], path["conversation_condition"]))
    assert compared == {
        *product(("request", "interpretation"), ("none", "clarification_complete")),
        ("interpretation", "revision"),
    }


def test_visualization_requests_use_the_requested_scope_and_registered_profile(built):
    catalog = registered_catalog()
    for condition in CONDITIONS:
        path = path_for(built, "visualization", condition)
        requested = calls(path)
        assert all(
            output["name"] == "validate_visualization" for _, output, _ in requested
        )
        views = [args["view_key"] for _, _, args in requested]
        assert views == (
            {
                "new_topic": ["Embed01VulnerabilityMap"],
                "clarification_complete": ["EmbedDetailMap", "EmbedDetailV02"],
            }.get(condition, ["EmbedDetailMap"])
        )
        for _, _, args in requested:
            params = args["parameters"]
            assert (
                params["p_start"]
                == params["p_end"]
                == built[0]["selection"]["month"] + "-01"
            )
            profile = catalog["views"][args["view_key"]]["input_profile"]
            if condition == "new_topic":
                assert profile == "monthly_city" and params["p_city"] == "11680"
                assert "filters" not in args and "p_detail_adm" not in params
                assert path["region_code"] == "11680"
                assert "전체" in path["steps"][0]["model_outputs"][0]["request"]["goal"]
            else:
                assert profile == "monthly_detail"
                assert params["p_detail_adm"] == "강남구 도곡1동"
        response = path["terminal"]["state"]["response"]
        assert len(response["artifacts"]) == len(views)
        assert all(artifact["type"] == "tableau" for artifact in response["artifacts"])
        assert "실제 화면 표시를 확인한 결과는 아니다" in response["content"]


def test_clarification_preserves_both_original_visualization_purposes_and_artifacts(
    built,
):
    path = path_for(built, "visualization", "clarification_complete")
    assert (
        "상세 지도와 행동 지표 기여도 차트를 함께"
        in path["start_state"]["messages"][0]["content"]
    )
    assert (
        "상세 지도와 행동 지표 기여도 차트"
        in path["steps"][0]["model_outputs"][0]["request"]["goal"]
    )
    assert len(path["task_rationale"]["missing_evidence"]) == 2
    first, second = calls(path)
    after_first = next(
        step
        for step in path["steps"]
        if step["node"] == "decide"
        and "행동 지표 기여도 차트도 포함" in step["model_outputs"][0]["reason"]
    )
    assert after_first["model_outputs"][0]["next"] == "act"
    assert second[2]["view_key"] == "EmbedDetailV02"
    chart_calls = [
        item
        for item in path["terminal"]["state"]["results"]
        if item["decision"] == "call"
        and (item.get("action") or {}).get("name") == "validate_visualization"
    ]
    assert all(item["output"]["valid"] for item in chart_calls)
    assert path["steps"][-1]["model_outputs"][0]["artifact_ids"] == [
        item["id"] for item in chart_calls
    ]
    assert first[2]["parameters"] == second[2]["parameters"]
