"""실제 세 지역의 보고서 역할별 정상 진입·반환 경로를 만든다.

기존 사례를 잘라 쓰지 않고 현재 노드로 조회·작성·검토를 실행한다.
후속 역할은 앞 역할의 실제 반환 State와 누적 예산을 그대로 이어받는다.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, TypedDict

from eval.scripts.node_dataset_paths import PathRecorder, dump_state, report_stage_state
from eval.scripts.node_dataset_report_paths import (
    APPROVED,
    KEYS,
    _template,
)
from eval.scripts.node_dataset_reports import (
    CONTRIBUTION,
    DESCRIPTION,
    GRID,
    INSIGHT,
    REGION,
    SELECTION,
    _initial,
    _month_offset,
    _profile,
)
from src.agent_nodes import approved_report_selection, last_report_draft
from src.execution import accepted_outputs
from src.state import report_input

REGION_CODES = ("1168065500", "1168063000", "5111062000")
ROLE_NAMES = {
    SELECTION: "시각화 선정",
    DESCRIPTION: "시각화 설명",
    INSIGHT: "퀵 인사이트",
}


class ReportProfile(TypedDict):
    month: str
    code: str
    name: str
    current: dict[str, Any]
    previous: dict[str, Any]


class ReportObservations(TypedDict):
    monthly_scores: list[dict[str, Any]]
    contribution: list[dict[str, Any]]
    grid_examples: list[dict[str, Any]]


class ReportDecision(TypedDict):
    target: str | None
    reason: str
    evidence_ids: list[str]


def basic_report_profiles(snapshot: dict) -> list[ReportProfile]:
    """스냅샷에 지역명·전월·현재 월의 실제 근거가 있는 세 동을 고른다."""
    regions = {item["adm_cd10"]: item for item in snapshot["selection"]["grid_regions"]}
    profiles = []
    for code in REGION_CODES:
        region = regions[code]
        chosen = {
            **snapshot,
            "selection": {
                **snapshot["selection"],
                "dong_code": code,
                "dong_name": region["adm_nm"],
            },
        }
        profile = _profile(chosen)
        if profile["previous"] is None:
            raise ValueError(f"Previous-month evidence is absent for {code}")
        for target in (REGION, CONTRIBUTION, GRID):
            if not any(
                row["adm_cd10"] == code
                and row["period_start"] == profile["month"] + "-01"
                for row in snapshot["datasets"][target]["rows"]
            ):
                raise ValueError(f"Current-month evidence is absent: {code} {target}")
        profiles.append(profile)
    return profiles


def _evidence(state):
    """현재 State에서 성공·유효한 실제 조회 기록만 읽는다."""
    accepted = accepted_outputs(state)
    return {
        item["action"]["arguments"]["target"]: item
        for item in state["results"]
        if item["decision"] == "call"
        and item["id"] in accepted
        and item["action"]["name"] == "query_data"
    }


def _query_arguments(state, target):
    inputs = report_input(state)
    month = inputs["month"]
    filters = [{"field": "adm_cd10", "operator": "eq", "value": inputs["dongCode"]}]
    if target == GRID:
        filters.append(
            {"field": "period_start", "operator": "eq", "value": month + "-01"}
        )
    else:
        start = _month_offset(month, -5 if target == REGION else -1)
        filters.extend(
            [
                {"field": "period_start", "operator": "ge", "value": start + "-01"},
                {"field": "period_start", "operator": "le", "value": month + "-01"},
            ]
        )
    return {"target": target, "filters": filters, "limit": 10000}


def _contribution_pair(month, rows):
    current = max(
        (row for row in rows if row["period_start"] == month + "-01"),
        key=lambda row: row["contribution"],
    )
    previous = next(
        row
        for row in rows
        if row["indicator_cd"] == current["indicator_cd"]
        and row["period_start"] == _month_offset(month, -1) + "-01"
    )
    return [previous, current]


def _score_observation(month, rows):
    ordered = sorted(rows, key=lambda row: row["period_start"])
    current = next(row for row in ordered if row["period_start"] == month + "-01")
    previous = next(
        row
        for row in ordered
        if row["period_start"] == _month_offset(month, -1) + "-01"
    )
    directions = {
        _direction(before["bh_score"], after["bh_score"])
        for before, after in zip(ordered, ordered[1:], strict=False)
    }
    pattern = (
        "상승과 하락이 함께 나타났고"
        if {"증가", "감소"} <= directions
        else "같은 방향의 변화 또는 유지가 나타났고"
    )
    overall = _direction(ordered[0]["bh_score"], current["bh_score"])
    latest = _direction(previous["bh_score"], current["bh_score"])
    return (
        f"확보한 월별 점수에는 {pattern} 첫 관측 월 대비 현재 월은 {overall}, "
        f"전월 대비 현재 월은 {latest}했다."
    )


def _contribution_observation(month, rows):
    previous, current = _contribution_pair(month, rows)
    direction = _direction(previous["contribution"], current["contribution"])
    sign = (
        " 음수에서 양수로 바뀌었다."
        if previous["contribution"] < 0 < current["contribution"]
        else ""
    )
    return (
        f"현재 최고 기여 지표인 {current['indicator_cd']}의 기여도는 "
        f"전월 대비 {direction}했다.{sign}"
    )


def _selection_decision(state) -> ReportDecision:
    """자료 수집 뒤에 기록된 관측으로 다음 필요 자료를 판단하는 고정 응답이다."""
    inputs = report_input(state)
    records = _evidence(state)
    evidence_ids = [item["id"] for item in records.values()]
    if REGION not in records:
        target = REGION
        reason = (
            f"{inputs['month']} {inputs['dongCode']}의 분석 대상·기간은 확인됐지만 "
            "조회한 관측값이 없어 설명할 현상을 아직 정할 수 없다. "
            "요청한 추세 기간의 동별 분석 점수를 "
            "조회해 현재 상태와 월별 변화를 먼저 확인한다."
        )
    else:
        score = _score_observation(
            inputs["month"], records[REGION]["output"]["data"]["rows"]
        )
        if CONTRIBUTION not in records:
            target = CONTRIBUTION
            reason = (
                score + " 현재 자료만으로는 행동 점수의 지표별 구성을 확인할 수 없어 "
                "현재 월과 전월의 지표 기여도를 조회한다."
            )
        elif GRID not in records:
            target = GRID
            contribution = _contribution_observation(
                inputs["month"], records[CONTRIBUTION]["output"]["data"]["rows"]
            )
            reason = (
                score
                + " "
                + contribution
                + " 확보한 자료는 동 단위 점수와 기여도여서 동 내부 격자 차이는 "
                "확인할 수 없다. 같은 월의 격자 점수를 조회해 공간 단위의 설명 "
                "근거를 확보한다."
            )
        else:
            target = None
            reason = " ".join(view["reason"] for view in _selection_views(state))
    return {"target": target, "reason": reason, "evidence_ids": evidence_ids}


def _observations(month, evidence) -> ReportObservations:
    """조회한 행에서 설명할 값만 고른다. 새 집계나 원자료 변경은 하지 않는다."""
    rows = {
        item["action"]["arguments"]["target"]: item["output"]["data"]["rows"]
        for item in evidence
    }
    monthly = sorted(rows[REGION], key=lambda row: row["period_start"])
    grids = sorted(rows[GRID], key=lambda row: row["grid_cd"])
    if len({row["grid_cd"] for row in grids}) != len(grids):
        raise ValueError("Current-month grid codes must be unique")
    first = next(row for row in grids if row["anomaly_score"] is not None)
    second = next(
        row
        for row in grids
        if row["anomaly_score"] is not None
        and row["anomaly_score"] != first["anomaly_score"]
    )
    return {
        "monthly_scores": monthly,
        "contribution": _contribution_pair(month, rows[CONTRIBUTION]),
        "grid_examples": [first, second],
    }


def _selection_views(state):
    month = report_input(state)["month"]
    records = _evidence(state)
    observations = _observations(month, records.values())
    first, second = observations["grid_examples"]
    reasons = (
        _score_observation(month, observations["monthly_scores"])
        + " 월별 추세 뷰로 전체 흐름과 최근 방향을 함께 설명한다. "
        "실제 제공된 월만 사용하며 미공급 월과 도시 중앙 범위 비교는 제외한다.",
        _contribution_observation(month, observations["contribution"])
        + " 행동 지표 구성 뷰로 전체 점수와 구별되는 지표별 전월 변화를 설명한다. "
        "기여도를 실제 활동량이나 배경 취약성의 요인별 기여도로 바꾸지 않는다.",
        f"현재 월 {first['grid_cd']}와 {second['grid_cd']}의 행동 이상 점수가 "
        "서로 다르다. 격자 분포 뷰로 동 단위 점수에서 보이지 않는 실제 격자 "
        "예시의 차이를 설명한다. 예시를 전체 분포의 대표값·위치 집중·원인이나 "
        "개인 고립 상태로 확대하지 않는다.",
    )
    return [
        {"view_key": key, "reason": reason, "evidence_ids": [records[target]["id"]]}
        for key, target, reason in zip(
            KEYS, (REGION, CONTRIBUTION, GRID), reasons, strict=True
        )
    ]


def _observed_profile(state, name) -> ReportProfile:
    inputs = report_input(state)
    rows = _evidence(state)[REGION]["output"]["data"]["rows"]
    return {
        "month": inputs["month"],
        "code": inputs["dongCode"],
        "name": name,
        "current": next(
            row for row in rows if row["period_start"] == inputs["month"] + "-01"
        ),
        "previous": next(
            row
            for row in rows
            if row["period_start"] == _month_offset(inputs["month"], -1) + "-01"
        ),
    }


def _direction(before, after):
    return "증가" if after > before else "감소" if after < before else "유지"


def _basic_descriptions(profile, observations):
    monthly = observations["monthly_scores"]
    sequence = ", ".join(
        f"{row['period_start'][:7]} {row['bh_score']}점" for row in monthly
    )
    directions = {
        _direction(before["bh_score"], after["bh_score"])
        for before, after in zip(monthly, monthly[1:], strict=False)
    }
    pattern = (
        "상승과 하락이 함께 나타났고"
        if {"증가", "감소"} <= directions
        else "같은 방향의 변화 또는 유지가 나타났고"
    )
    overall = _direction(monthly[0]["bh_score"], monthly[-1]["bh_score"])
    latest = _direction(profile["previous"]["bh_score"], profile["current"]["bh_score"])
    previous, current = observations["contribution"]
    contribution_direction = _direction(
        previous["contribution"], current["contribution"]
    )
    first, second = observations["grid_examples"]
    return {
        KEYS[0]: (
            f"제공된 월의 행동 이상 점수는 {sequence} 순이다. "
            f"관측 기간에는 {pattern} "
            f"첫 관측 월 대비 마지막 관측 월은 {overall}했으며, "
            f"현재 월 점수는 {profile['current']['bh_score']}점으로 "
            f"전월 대비 {latest}했다. "
            "행동 점수는 실제 활동량이나 개인의 고립 상태가 아니며 "
            "미공급 월과 도시 중앙 범위는 비교하지 않는다."
        ),
        KEYS[1]: (
            "현재 월 행동 지표 중 점수 기여도가 가장 큰 지표는 "
            f"{current['indicator_cd']}다. "
            f"이 지표의 기여도는 전월 {previous['contribution']}점에서 현재 월 "
            f"{current['contribution']}점으로 {contribution_direction}했다. "
            "기여도는 행동 점수에 대한 기여이며 실제 활동량이나 배경 취약성의 "
            "요인별 기여도로 해석하지 않는다."
        ),
        KEYS[2]: (
            f"현재 월 조회 예시에서 {first['grid_cd']} 격자의 행동 이상 점수는 "
            f"{first['anomaly_score']}점이고 {second['grid_cd']} 격자는 "
            f"{second['anomaly_score']}점으로 두 격자 값이 다르다. "
            "이 관측은 인용한 두 격자 사이의 차이이며 미산출 점수는 실제 영점과 "
            "구분하고 개인의 고립 상태를 추정하지 않는다."
        ),
    }


def _basic_insight(profile, observations):
    latest = _direction(profile["previous"]["bh_score"], profile["current"]["bh_score"])
    previous, current = observations["contribution"]
    contribution_direction = _direction(
        previous["contribution"], current["contribution"]
    )
    return "\n".join(
        [
            "관측 기간에는 상승과 하락이 함께 나타났고 "
            f"현재 월 행동 이상 점수는 전월 대비 {latest}했다.",
            f"현재 최고 기여 지표인 {current['indicator_cd']}의 "
            f"기여도는 전월 대비 {contribution_direction}했다.",
            "설명에 인용한 두 격자의 현재 월 행동 이상 점수가 서로 달라 "
            "해당 예시 간 차이를 확인할 수 있다.",
            "행동 점수는 실제 활동량이나 개인 고립 상태가 아니며 "
            "미공급 월과 도시 중앙 범위는 비교할 수 없다.",
        ]
    )


def _entry(recorder, profile):
    initial = _initial(
        f"basic-report-{profile['code']}",
        SELECTION,
        profile,
        [],
        required=[
            f"추세 기간: {_month_offset(profile['month'], -5)}~{profile['month']}",
            "서로 다른 상세 뷰 3개, 검증된 설명과 퀵 인사이트 작성",
        ],
    )
    initial["request"]["goal"] = (
        f"{profile['month']} {profile['code']} 행정동 분석 보고서 생성"
    )
    # 역할 진입 기록은 실제 report_flow와 같은 helper에서 한 번만 추가한다.
    initial["results"] = [
        item for item in initial["results"] if item["decision"] != "report_stage"
    ]
    return recorder.initial_state(initial)


def _assessment(state, profile, node, role, outputs, condition):
    template = _template({}, state, profile, node, role, condition, output=outputs[0])
    template["providers"] = [REGION, CONTRIBUTION, GRID]
    template["tags"] += ["basic-agent", "conversation:none"]
    assessment = template["assessment"]
    if node == "act":
        for check in ("N02-O.3", "N02-B.2", "N-B.1"):
            assessment["reference"][check].update(
                expected_arguments=json.loads(outputs[0]["arguments_json"]),
                allowed_variation=(
                    "대상 지역·기간·자료원을 보존하는 동등한 인자 표현을 허용하며 "
                    "필터 순서를 정답으로 고정하지 않는다."
                ),
            )
    if node == "compose" and role in (DESCRIPTION, INSIGHT):
        records = _evidence(state)
        observations = _observations(report_input(state)["month"], records.values())
        assessment["reference"]["N-O.1"]["reported_observations"] = {
            view_key: {"result_id": records[target]["id"], "rows": deepcopy(rows)}
            for view_key, target, rows in (
                (KEYS[0], REGION, observations["monthly_scores"]),
                (KEYS[1], CONTRIBUTION, observations["contribution"]),
                (KEYS[2], GRID, observations["grid_examples"]),
            )
        }
    if node == "compose" and role == DESCRIPTION:
        item = next(
            value
            for value in assessment["expected"]["items"]
            if value["check"] == "N-O.1"
        )
        item.pop("applicable", None)
        item.pop("reason", None)
        item.update(
            call="ReportText",
            call_index=1,
            path="/content",
            pattern=r"현재\s*월\s*점수는\s*([+-]?\d+(?:\.\d+)?)\s*점(?!수)",
            extract="number",
            value=profile["current"]["bh_score"],
            tolerance={"absolute": 0.00005},
        )
        assessment["reference"]["N-O.1"]["independent_value"] = profile["current"][
            "bh_score"
        ]
    return template


async def build_basic_report_paths(snapshot: dict, recorder: PathRecorder) -> None:
    """보고서 3역할 × 실제 3지역을 각각 하나의 독립 에이전트 경로로 기록한다."""
    for profile in basic_report_profiles(snapshot):
        state = _entry(recorder, profile)
        upstream_id = None

        async def step(node, role, current, outputs, condition, *, selected=profile):
            return await recorder.step(
                node,
                role,
                current,
                outputs,
                template=_assessment(current, selected, node, role, outputs, condition),
                label=condition,
            )

        async def decide(role, current, target, condition, evidence_ids):
            result = await step(
                "decide",
                role,
                current,
                [{"next": target, "reason": condition}],
                condition,
            )
            recorder.current.setdefault("decision_basis", []).append(
                {
                    "step_id": recorder.current["steps"][-1]["step_id"],
                    "evidence_ids": list(evidence_ids),
                    "reason": condition,
                }
            )
            return result

        for role in (SELECTION, DESCRIPTION, INSIGHT):
            identity = f"basic-{role}-{profile['code']}"
            before = dump_state(state)
            state = report_stage_state(state, role)
            recorder.begin(
                identity,
                f"{profile['name']} {profile['month']} {ROLE_NAMES[role]} 정상 실행",
                "analysis_pipeline",
                "basic-report",
                axes={"selected_view_count": 3, "current_event": "normal"},
            )
            recorder.current.update(
                scope="agent",
                agent_role=role,
                region_code=profile["code"],
                region_name=profile["name"],
                conversation_condition="none",
                upstream_scenario_id=upstream_id,
                entry_transition={
                    "kind": "report_handoff",
                    "before_state": before,
                    "after_state": dump_state(state),
                },
            )
            if role == SELECTION:
                while (plan := _selection_decision(state))["target"] is not None:
                    arguments = _query_arguments(state, plan["target"])
                    reason = plan["reason"]
                    state = await decide(
                        role, state, "act", reason, plan["evidence_ids"]
                    )
                    previous = len(state["results"])
                    state = await step(
                        "act",
                        role,
                        state,
                        [
                            {
                                "name": "query_data",
                                "arguments_json": json.dumps(
                                    arguments, ensure_ascii=False
                                ),
                                "reason": reason,
                            }
                        ],
                        reason,
                    )
                    calls = [
                        item
                        for item in state["results"][previous:]
                        if item["decision"] == "call" and item["outcome"] == "success"
                    ]
                    if len(calls) != 1:
                        raise AssertionError("Expected one actual successful tool call")
                reason = plan["reason"]
                evidence_ids = plan["evidence_ids"]
                outputs = [
                    {"views": _selection_views(state)},
                    deepcopy(APPROVED),
                ]
            elif role == DESCRIPTION:
                selected = approved_report_selection(state)
                if selected is None:
                    raise AssertionError("Descriptions require an approved selection")
                evidence_ids = [
                    selected["id"],
                    *[r["id"] for r in _evidence(state).values()],
                ]
                observed = _observed_profile(state, profile["name"])
                observations = _observations(
                    observed["month"], _evidence(state).values()
                )
                descriptions = _basic_descriptions(observed, observations)
                reason = (
                    "승인된 세 뷰와 그 근거가 모두 있어 추가 조회 없이 각 설명을 "
                    "작성한다. 제공된 월별 점수와 전체·전월 방향, 동일 행동 지표의 "
                    "전월 기여도 비교, 실제 격자 두 행의 예시를 설명하고 "
                    "승인 범위와 제외한 비교를 보존한다."
                )
                outputs = [
                    output
                    for view in selected["output"]["views"]
                    for output in (
                        {"content": descriptions[view["view_key"]]},
                        deepcopy(APPROVED),
                    )
                ]
            else:
                selected = approved_report_selection(state)
                if selected is None:
                    raise AssertionError("Insights require an approved selection")
                drafts = [
                    last_report_draft(state, view["view_key"])
                    for view in selected["output"]["views"]
                ]
                accepted = accepted_outputs(state)
                if not all(draft and draft["id"] in accepted for draft in drafts):
                    raise AssertionError("Insights require approved descriptions")
                evidence_ids = [draft["id"] for draft in drafts]
                observed = _observed_profile(state, profile["name"])
                observations = _observations(
                    observed["month"], _evidence(state).values()
                )
                reason = (
                    "세 뷰의 승인 설명이 있어 추가 조회 없이 서로 다른 핵심 관측과 "
                    "해석 한계를 3~4문장으로 요약한다. 승인 설명에 없는 수치·"
                    "원인·개인 진단을 추가하지 않는다."
                )
                outputs = [
                    {"content": _basic_insight(observed, observations)},
                    deepcopy(APPROVED),
                ]
            state = await decide(role, state, "compose", reason, evidence_ids)
            state = await step("compose", role, state, outputs, reason)
            recorder.end(state, terminal="completed")
            upstream_id = identity
