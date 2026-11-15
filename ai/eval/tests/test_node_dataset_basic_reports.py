"""정상 보고서 역할의 실제 진입·반환과 앞 단계 승인 자료 전달을 검사한다."""

import asyncio
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from api import create_report_states
from eval.scripts.node_dataset_basic_reports import (
    REGION_CODES,
    _selection_decision,
    build_basic_report_paths,
)
from eval.scripts.node_dataset_paths import (
    PathRecorder,
    assemble_paths,
    dump_state,
    report_stage_state,
    validate_paths,
)
from eval.scripts.node_dataset_reports import CONTRIBUTION, GRID, REGION
from src.agent_nodes import approved_report_selection
from src.execution import accepted_outputs

ROOT = Path(__file__).resolve().parents[2] / "eval/scenarios/nodes"
ROLES = ("report_selection", "report_description", "report_insight")


@pytest.fixture(scope="module")
def recorded():
    snapshot = json.loads((ROOT / "snapshots/data.json").read_text(encoding="utf-8"))
    original = deepcopy(snapshot)
    recorder = PathRecorder(snapshot)
    # 기존 사례 입력을 복사하지 않고 실제 노드로 새 경로를 만든다.
    asyncio.run(build_basic_report_paths(snapshot, recorder))
    assert snapshot == original
    cases, sidecar = assemble_paths([], [], recorder)
    return snapshot, cases, sidecar


def test_three_regions_each_have_three_complete_single_role_paths(recorded):
    _, cases, sidecar = recorded
    assert not validate_paths(sidecar, cases)
    paths = sidecar["scenarios"]
    assert len(paths) == 9
    assert {(p["region_code"], p["agent_role"]) for p in paths} == {
        (code, role) for code in REGION_CODES for role in ROLES
    }
    for path in paths:
        assert path["scope"] == "agent"
        assert path["conversation_condition"] == "none"
        assert path["steps"][0]["node"] == "decide"
        assert {step["role"] for step in path["steps"]} == {path["agent_role"]}
        assert path["terminal"]["status"] == "completed"
        assert path["steps"][-1]["expected_next_nodes"] == ["__end__"]
        assert not path["boundaries"]
        assert not {"interpret", "ask"} & {step["node"] for step in path["steps"]}
        assert len(path["steps"]) == (8 if path["agent_role"] == ROLES[0] else 2)


def test_role_entries_preserve_real_upstream_state_and_accumulated_budget(recorded):
    _, _, sidecar = recorded
    paths = {path["id"]: path for path in sidecar["scenarios"]}
    for path in paths.values():
        transition = path["entry_transition"]
        before, after = transition["before_state"], transition["after_state"]
        assert transition["kind"] == "report_handoff"
        assert after == dump_state(report_stage_state(before, path["agent_role"]))
        assert after == path["start_state"] == path["steps"][0]["before_state"]
        assert after["results"][:-1] == before["results"]
        assert after["messages"] == before["messages"]
        assert after["response"] == before["response"]
        assert after["execution"]["budget"] == before["execution"]["budget"]
        assert after["execution"]["budget"]["agent_calls"]["used"] == 0
        assert after["results"][-1]["action"]["name"] == path["agent_role"] + "_agent"
        if path["upstream_scenario_id"]:
            upstream = paths[path["upstream_scenario_id"]]
            assert before == upstream["terminal"]["state"]
            assert path["region_code"] == upstream["region_code"]
            assert (
                ROLES.index(path["agent_role"])
                == ROLES.index(upstream["agent_role"]) + 1
            )
        else:
            assert path["agent_role"] == ROLES[0]
            assert not before["messages"]
            assert before["response"] is None
            assert before["execution"]["budget"]["steps"]["used"] == 0
            assert {r["decision"] for r in before["results"]} == {
                "report_input",
                "report_source",
            }
        assert set(after) == {"request", "messages", "results", "response", "execution"}


def test_selection_entry_matches_service_input_without_prescribing_views(recorded):
    snapshot, _, sidecar = recorded
    settings = PathRecorder(snapshot).settings
    for path in sidecar["scenarios"]:
        if path["agent_role"] != ROLES[0]:
            continue
        before = path["entry_transition"]["before_state"]
        inputs = next(
            record["output"]
            for record in before["results"]
            if record["decision"] == "report_input"
        )
        expected = create_report_states(
            {key: inputs[key] for key in ("requestId", "month", "dongCodes")}, settings
        )[0]
        assert before["request"] == expected["request"]
        required = before["request"]["constraints"]["required"]
        assert not any(
            word in " ".join(required)
            for word in ("기여도", "격자", "EmbedDetail", "제공된 월")
        )


def test_actual_queries_use_only_the_selected_region_and_captured_rows(recorded):
    snapshot, cases, sidecar = recorded
    by_case = {case["id"]: case for case in cases}
    for path in sidecar["scenarios"]:
        state = path["terminal"]["state"]
        for item in state["results"]:
            if item["decision"] != "call":
                continue
            assert item["outcome"] == "success"
            assert item["action"]["name"] == "query_data"
            target = item["action"]["arguments"]["target"]
            assert target in {REGION, CONTRIBUTION, GRID}
            rows = item["output"]["data"]["rows"]
            assert rows
            assert {row["adm_cd10"] for row in rows} == {path["region_code"]}
            assert all(row in snapshot["datasets"][target]["rows"] for row in rows)
            if target == GRID:
                assert {row["period_start"] for row in rows} == {"2025-12-01"}
            elif target == CONTRIBUTION:
                assert {row["period_start"] for row in rows} == {
                    "2025-11-01",
                    "2025-12-01",
                }
                assert len(rows) == 24
                periods = {
                    condition["operator"]: condition["value"]
                    for condition in item["action"]["arguments"]["filters"]
                    if condition["field"] == "period_start"
                }
                assert periods == {"ge": "2025-11-01", "le": "2025-12-01"}
        assert len([r for r in state["results"] if r["decision"] == "call"]) == 3
        for step in path["steps"]:
            if step["node"] != "act":
                continue
            expected = json.loads(step["model_outputs"][0]["arguments_json"])
            references = by_case[step["case_id"]]["assessment"]["reference"]
            for check in ("N02-O.3", "N02-B.2", "N-B.1"):
                assert references[check]["expected_arguments"] == expected
                assert "필터 순서" in references[check]["allowed_variation"]


def test_decision_basis_uses_only_observed_valid_history_at_each_step(recorded):
    _, _, sidecar = recorded
    for path in sidecar["scenarios"]:
        steps = {step["step_id"]: step for step in path["steps"]}
        decisions = [step for step in path["steps"] if step["node"] == "decide"]
        assert len(path["decision_basis"]) == len(decisions)
        for basis in path["decision_basis"]:
            step = steps[basis["step_id"]]
            before = step["before_state"]
            assert set(basis["evidence_ids"]) <= set(accepted_outputs(before))
            assert basis["reason"] == step["model_outputs"][0]["reason"]
        if path["agent_role"] != ROLES[0]:
            continue
        expected_targets = (REGION, CONTRIBUTION, GRID, None)
        for step, target in zip(decisions, expected_targets, strict=True):
            before = step["before_state"]
            plan = _selection_decision(before)
            assert plan["target"] == target
            assert plan["reason"] == step["model_outputs"][0]["reason"]
            if target in (REGION, CONTRIBUTION):
                assert "h29_senior_gender_change_gap" not in plan["reason"]
                assert "h19_age_entropy" not in plan["reason"]
            if target is not None:
                assert not any(code in plan["reason"] for code in ("다사", "라사"))
        if path["region_code"] == "1168065500":
            # 이전에 조회한 행을 바꾸면 판단도 그 State를 따른다.
            changed = deepcopy(decisions[1]["before_state"])
            call = next(r for r in changed["results"] if r["decision"] == "call")
            current = next(
                row
                for row in call["output"]["data"]["rows"]
                if row["period_start"] == "2025-12-01"
            )
            current["bh_score"] = 0
            assert "전월 대비 현재 월은 감소" in _selection_decision(changed)["reason"]
            assert (
                "전월 대비 현재 월은 증가" in decisions[1]["model_outputs"][0]["reason"]
            )
        # 보유 이력이어도 실패한 조회를 다음 판단의 확보 근거로 취급하지 않는다.
        rejected = deepcopy(decisions[2]["before_state"])
        contribution = next(
            r
            for r in rejected["results"]
            if r["decision"] == "call"
            and r["action"]["arguments"]["target"] == CONTRIBUTION
        )
        contribution["outcome"] = "failure"
        assert _selection_decision(rejected)["target"] == CONTRIBUTION
        assert contribution["id"] not in _selection_decision(rejected)["evidence_ids"]


def test_selected_views_explain_region_specific_observations_and_limits(recorded):
    snapshot, _, sidecar = recorded
    reasons = {
        key: set() for key in ("EmbedDetailV01", "EmbedDetailV02", "EmbedDetailV08")
    }
    for path in sidecar["scenarios"]:
        if path["agent_role"] != ROLES[0]:
            continue
        selected = approved_report_selection(path["terminal"]["state"])
        views = {v["view_key"]: v for v in selected["output"]["views"]}
        rows = sorted(
            [
                row
                for row in snapshot["datasets"][REGION]["rows"]
                if row["adm_cd10"] == path["region_code"]
            ],
            key=lambda row: row["period_start"],
        )
        overall = "증가" if rows[-1]["bh_score"] > rows[0]["bh_score"] else "감소"
        latest = "증가" if rows[-1]["bh_score"] > rows[-2]["bh_score"] else "감소"
        assert (
            f"첫 관측 월 대비 현재 월은 {overall}" in views["EmbedDetailV01"]["reason"]
        )
        assert f"전월 대비 현재 월은 {latest}" in views["EmbedDetailV01"]["reason"]
        assert (
            "미공급 월과 도시 중앙 범위 비교는 제외"
            in views["EmbedDetailV01"]["reason"]
        )
        grid = views["EmbedDetailV08"]["reason"]
        assert "예시" in grid and "대표값·위치 집중·원인" in grid
        for key, view in views.items():
            reasons[key].add(view["reason"])
        if path["region_code"] == "5111062000":
            assert "음수에서 양수" in views["EmbedDetailV02"]["reason"]
        else:
            assert "음수에서 양수" not in views["EmbedDetailV02"]["reason"]
    assert all(len(values) == 3 for values in reasons.values())


def test_selection_and_descriptions_are_approved_before_the_next_role(recorded):
    _, _, sidecar = recorded
    for path in sidecar["scenarios"]:
        state = path["terminal"]["state"]
        accepted = accepted_outputs(state)
        selected = approved_report_selection(state)
        assert selected and selected["id"] in accepted
        views = selected["output"]["views"]
        assert len({view["view_key"] for view in views}) == 3
        assert all(ref in accepted for view in views for ref in view["evidence_ids"])
        drafts = [r for r in state["results"] if r["decision"] == "report_draft"]
        assert all(r["id"] in accepted for r in drafts)
        assert len(drafts) == (
            0
            if path["agent_role"] == ROLES[0]
            else 3
            if path["agent_role"] == ROLES[1]
            else 4
        )
        assert all(
            r["output"]["accepted"]
            for r in state["results"]
            if r["decision"] == "verification"
        )


def test_region_values_directions_and_insights_match_actual_approved_evidence(recorded):
    snapshot, cases, sidecar = recorded
    by_case = {case["id"]: case for case in cases}
    observed = set()
    for path in sidecar["scenarios"]:
        if path["agent_role"] == ROLES[0]:
            continue
        rows = [
            r
            for r in snapshot["datasets"][REGION]["rows"]
            if r["adm_cd10"] == path["region_code"]
        ]
        current = next(r for r in rows if r["period_start"] == "2025-12-01")["bh_score"]
        previous = next(r for r in rows if r["period_start"] == "2025-11-01")[
            "bh_score"
        ]
        direction = (
            "증가" if current > previous else "감소" if current < previous else "유지"
        )
        observed.add(direction)
        state = path["terminal"]["state"]
        drafts = {
            r["action"]["arguments"]["view_key"]: r["output"]["content"]
            for r in state["results"]
            if r["decision"] == "report_draft"
        }
        score_text = drafts["EmbedDetailV01"]
        assert f"{current}점" in score_text and direction in score_text
        ordered = sorted(rows, key=lambda row: row["period_start"])
        assert len(ordered) == 5
        assert all(
            f"{row['period_start'][:7]} {row['bh_score']}점" in score_text
            for row in ordered
        )
        differences = [
            after["bh_score"] - before["bh_score"]
            for before, after in zip(ordered, ordered[1:], strict=False)
        ]
        assert min(differences) < 0 < max(differences)
        assert "상승과 하락이 함께" in score_text
        overall = "증가" if ordered[-1]["bh_score"] > ordered[0]["bh_score"] else "감소"
        assert f"첫 관측 월 대비 마지막 관측 월은 {overall}" in score_text
        contributions = [
            r
            for r in snapshot["datasets"][CONTRIBUTION]["rows"]
            if r["adm_cd10"] == path["region_code"]
            and r["period_start"] == "2025-12-01"
        ]
        highest = max(contributions, key=lambda row: row["contribution"])
        indicator_before = next(
            row
            for row in snapshot["datasets"][CONTRIBUTION]["rows"]
            if row["adm_cd10"] == path["region_code"]
            and row["period_start"] == "2025-11-01"
            and row["indicator_cd"] == highest["indicator_cd"]
        )
        contribution_text = drafts["EmbedDetailV02"]
        assert highest["indicator_cd"] in contribution_text
        assert (
            f"전월 {indicator_before['contribution']}점에서 현재 월 "
            f"{highest['contribution']}점으로 증가" in contribution_text
        )
        assert indicator_before["contribution"] < highest["contribution"]
        grid_rows = sorted(
            (
                row
                for row in snapshot["datasets"][GRID]["rows"]
                if row["adm_cd10"] == path["region_code"]
                and row["period_start"] == "2025-12-01"
            ),
            key=lambda row: row["grid_cd"],
        )
        assert len(grid_rows) == len({row["grid_cd"] for row in grid_rows})
        assert grid_rows[0]["anomaly_score"] != grid_rows[1]["anomaly_score"]
        grid_text = drafts["EmbedDetailV08"]
        for grid in grid_rows[:2]:
            assert grid["grid_cd"] in grid_text
            assert f"{grid['anomaly_score']}점" in grid_text
        assert "두 격자 사이의 차이" in grid_text
        assert not any(
            word in grid_text for word in ("최댓값", "최솟값", "집중", "원인")
        )
        case = by_case[path["steps"][-1]["case_id"]]
        reference = case["assessment"]["reference"]["N-O.1"]["reported_observations"]
        assert reference["EmbedDetailV01"]["rows"] == ordered
        assert reference["EmbedDetailV02"]["rows"] == [indicator_before, highest]
        assert reference["EmbedDetailV08"]["rows"] == grid_rows[:2]
        by_record = {record["id"]: record for record in state["results"]}
        for observation in reference.values():
            source = by_record[observation["result_id"]]["output"]["data"]["rows"]
            assert all(row in source for row in observation["rows"])
        if path["agent_role"] == ROLES[1]:
            number = next(
                item
                for item in case["assessment"]["expected"]["items"]
                if item["check"] == "N-O.1"
            )
            assert number["call_index"] == 1 and number["call"] == "ReportText"
            assert number["value"] == current and number.get("applicable") is not False
            assert [float(n) for n in re.findall(number["pattern"], score_text)] == [
                current
            ]
            assert re.findall(number["pattern"], f"{current}점") == []
            assert re.findall(number["pattern"], "현재 월 점수는 -1.25점") == ["-1.25"]
        else:
            lines = drafts[None].splitlines()
            assert len(lines) == len(set(lines)) == 4
            assert direction in lines[0]
            assert highest["indicator_cd"] in lines[1]
            assert "기여도는 전월 대비 증가" in lines[1]
            assert "두 격자" in lines[2] and "서로 달라" in lines[2]
            assert "개인 고립 상태가 아니며" in lines[3]
    assert observed == {"증가", "감소"}


def test_rebuilding_role_paths_preserves_inputs_oracles_and_runtime_states(recorded):
    snapshot, cases, sidecar = recorded
    recorder = PathRecorder(snapshot)
    asyncio.run(build_basic_report_paths(snapshot, recorder))
    rebuilt_cases, rebuilt_sidecar = assemble_paths([], [], recorder)
    assert cases == rebuilt_cases
    assert sidecar == rebuilt_sidecar
