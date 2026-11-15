"""Expose the ten actual report model calls as independent evaluation cases.

This is an overlapping model-call view of the same report fixture. Its first
selection, first description and insight drafts duplicate the three first-call
compose cases in compose.json; the ten cases are not ten additional node paths.
"""

from __future__ import annotations

import json
from copy import deepcopy

from report_candidate import (
    PROVIDERS,
    _assessment,
    _facts,
    _number_pattern,
    _requirements,
    number_requirements,
    view_requirements,
)

from eval.nodes.rules import _compare
from eval.schema import case_adapter, suite_adapter
from eval.scripts.node_dataset_basic_reports import basic_report_profiles
from eval.scripts.node_dataset_paths import (
    PathRecorder,
    deterministic_runtime,
    digest,
    dump_state,
    initial_input,
)
from eval.scripts.node_dataset_reports import (
    DESCRIPTION,
    INSIGHT,
    SELECTION,
    _expectations,
)
from src.agent_nodes import prepare_model_call
from src.execution import consume
from src.state import state_adapter


def _prefix_state(step, index):
    """Recover input before an internal call without any final compose output."""
    before = step["before_state"]
    after = step["after_state"]
    assert after["results"][: len(before["results"])] == before["results"]
    assert after["request"] == before["request"]
    state = state_adapter.validate_python(deepcopy(before))
    # Production run_node consumes one step before entering compose. Internal
    # successful draft/review calls consume no extra steps or retry allowance.
    consume(state, "steps")
    state["results"] = deepcopy(after["results"][:index])
    assert not any(
        item["decision"] == "retry"
        for item in state["results"][len(before["results"]) :]
    ), "This extractor covers the successful, non-retry report candidate only"
    assert state["execution"]["budget"] == after["execution"]["budget"]
    assert (
        state["messages"] == state_adapter.validate_python(deepcopy(before))["messages"]
    )
    assert state["response"] == before["response"]
    return state


def _requirements_for(role, view_key):
    if role != DESCRIPTION:
        return _requirements(role)
    requirements = view_requirements(view_key)
    requirements["role_scope"] = role
    return requirements


def _numbers(facts, role, view_key):
    return number_requirements(facts, role, view_key)


def _call_assessment(state, profile, role, stage, view_key, output):
    review = stage in {"selection_review", "draft_review"}
    condition = (
        "현재 선정·초안이 해당 뷰의 관측을 기간 맥락·조건별 생활 이용 "
        "해석·현재 수준과 최근 변화 구분 등 승인된 상황판단으로 "
        "설명하는지 실제 근거에 대조한다. 모든 뷰에 생활접촉 가설·인과·"
        "실행 조치를 요구하지 않는다. 현재 분포만으로 변화 위치를 "
        "추정하면 부적절하지만, 선정에서 연결한 같은 격자의 실제 월별 "
        "자료로 보완 비교하는 것은 허용한다. 보고서 전체의 상황판단과 "
        "필요한 조건부 확인 행동을 보며 관측·조건·권고를 구분한다."
        if review
        else "현재 호출의 승인 범위 안에서 실제 관측을 연결해 해당 뷰의 "
        "상황을 해석한다. 등락·회복 맥락, 실제 변화 조건에 따른 생활 이용 "
        "해석, 현재 수준과 과거 지속·최근 변화 구분을 근거에 맞게 사용한다. "
        "모든 뷰에 가설이나 실행 조치를 붙이지 않으며 필요한 확인 제안은 "
        "대상·기간·조건을 구체적으로 쓴다. 현재 분포 화면과 같은 격자의 "
        "실제 과거 자료를 추가로 대조한 결과를 구분한다. 미확인 성별 절대 "
        "감소·주소·현장 변화·개인의 고립 상태를 사실로 만들지 않는다."
    )
    base = _assessment(state, profile, "compose", role, [output], condition)[
        "assessment"
    ]
    facts = _facts(state)
    requirements = _requirements_for(role, view_key)
    schema = (
        "Verification"
        if review
        else "ReportSelection"
        if role == SELECTION
        else "ReportText"
    )
    if review:
        assessment = _expectations(
            "compose",
            role,
            condition,
            call=schema,
            review={
                "accepted": True,
                "reason": "현재 초안이 실제 관측을 시간 맥락·조건별 해석·공간 "
                "비교 중 승인된 범위에 연결해 상황을 설명한다. 필요한 확인 "
                "제안은 대상·기간·조건을 보존하며, 조건부 성별 해석이나 "
                "현장 확인을 이미 관측한 사실로 만들지 않아 승인한다.",
            },
        )
        for check, reference in assessment["reference"].items():
            reference.update(deepcopy(base["reference"].get(check, {})))
        target_id = output["call_id"]
        target = next(item for item in state["results"] if item["id"] == target_id)
        assessment["reference"]["N04-O.3"].update(
            expected_review={
                "accepted": True,
                "reason_must_explain": (
                    "해당 뷰의 실제 관측이 어떤 상황판단을 지지하는지 "
                    "설명한다. 최근 감소를 이전 등락·회복과 연결한 해석은 "
                    "행동 제안 없이도 허용한다. 성별 구성 변화는 여성의 "
                    "실제 감소와 여성 유지 속 남성 증가 같은 조건에 따라 "
                    "생활 이용 해석을 구분할 수 있으며 프로그램·발굴 운영 "
                    "조치를 강제하지 않는다. 그 조건을 확인된 사실이나 "
                    "가능한 모든 경우로 취급하지 않는다. 현재 격자 분포만으로 "
                    "변화 위치를 추정하는 것은 거부하되, 같은 격자의 실제 "
                    "월별 값·순위가 선정 근거에 연결됐다면 지속·상승 비교를 "
                    "허용한다. 현재 화면의 관측과 과거 자료의 보완 비교를 "
                    "구분했는지 확인한다. 보고서 전체에는 근거에 따른 상황판단과 "
                    "필요한 확인 행동이 있어야 하며, 주거지 여부를 확인한 뒤 "
                    "해당 기간의 현장 정보를 대조하는 조건부 제안으로도 "
                    "충분하다. 발굴 편중·미방문 이력·상담 실행을 필수로 "
                    "요구하지 않는다. 숫자·주의문·권고만으로 해석을 대신하면 "
                    "미달이다. 미확인 성별 절대 감소·주소·현장 변화·개인의 "
                    "고립 상태를 사실화하면 승인하지 않는다. 요약은 승인된 "
                    "설명의 해석·대상·기간·조건을 보존하고 모든 수치·가설·"
                    "조치를 반복할 필요는 없다. "
                    "'문제없음' 또는 '근거와 일치'만 반복하면 부족하다."
                ),
            },
            target_record_id=target_id,
            target_draft=deepcopy(target["output"]),
        )
    else:
        assessment = base
    for reference in assessment["reference"].values():
        reference.update(deepcopy(requirements))
        reference["independent_observations"] = deepcopy(facts)
        reference["numeric_comparison"] = (
            "원자료와 실제 가공값을 기준으로 비교한다. 화면 기여도는 소수 셋째 "
            "자리 표현을 허용하되 기준에는 원자료 여섯 자리 값을 보존한다. "
            "전월→현재·차이·양음·개수의 관계를 함께 확인하며 숫자 포함만으로 "
            "의미 정확성을 인정하지 않는다."
        )
    items = assessment["expected"]["items"]
    for item in items:
        item["call"] = schema
        item["call_index"] = 1
        if item["check"] == "N04-O.3":
            if review:
                item.update(
                    value=deepcopy(
                        assessment["reference"]["N04-O.3"]["expected_review"]
                    )
                )
            else:
                for key in ("value", "path", "match", "pattern"):
                    item.pop(key, None)
                item.update(
                    applicable=False,
                    reason="이번 사례는 작성 한 호출이며 "
                    "후속 검토는 별도 model_call 사례로 평가한다.",
                )
    if not review and role != SELECTION:
        assessment["expected"]["items"] = [i for i in items if i["check"] != "N-O.1"]
        for label, value in _numbers(facts, role, view_key):
            assessment["expected"]["items"].append(
                {
                    "id": f"N-O.1-{label}",
                    "check": "N-O.1",
                    "node": "compose",
                    "role": role,
                    "call": schema,
                    "call_index": 1,
                    "path": "/content",
                    "pattern": _number_pattern(value),
                    "extract": "number",
                    "value": value,
                    "tolerance": {
                        "absolute": 0.0005 if "contribution" in label else 0.005
                    },
                }
            )
    return assessment


def build_report_calls(snapshot: dict, recorder: PathRecorder) -> tuple[dict, dict]:
    """Return an existing-schema suite and coverage metadata; write no files."""
    profiles = {p["code"]: p for p in basic_report_profiles(snapshot)}
    providers = PROVIDERS
    catalog = {name: deepcopy(snapshot["catalog"][name]) for name in providers}
    cases, coverage = [], []
    for scenario in recorder.scenarios:
        role = scenario["agent_role"]
        if role not in {SELECTION, DESCRIPTION, INSIGHT}:
            continue
        profile = profiles[scenario["region_code"]]
        compose_steps = [s for s in scenario["steps"] if s["node"] == "compose"]
        assert len(compose_steps) == 1, (
            "Expected one successful compose per report role"
        )
        step = compose_steps[0]
        before_count = len(step["before_state"]["results"])
        records = step["after_state"]["results"]
        model_records = [
            (index, item)
            for index, item in enumerate(records)
            if index >= before_count
            and item["node"] == "compose"
            and (item.get("action") or {}).get("name")
            in {
                "select_report_views",
                "write_report",
                "review_report",
            }
        ]
        assert len(model_records) == len(step["model_outputs"])
        for ordinal, ((index, record), authored) in enumerate(
            zip(model_records, step["model_outputs"], strict=True), start=1
        ):
            assert record["outcome"] == "success"
            assert all(record["output"].get(k) == v for k, v in authored.items())
            name = record["action"]["name"]
            stage = (
                "selection"
                if name == "select_report_views"
                else "draft"
                if name == "write_report"
                else "selection_review"
                if role == SELECTION
                else "draft_review"
            )
            state = _prefix_state(step, index)
            frozen = dump_state(state)
            with deterministic_runtime(digest([scenario["id"], ordinal, "call-input"])):
                prepared = prepare_model_call(
                    "compose", state, role=role, catalog=catalog, report_stage=stage
                )
            assert dump_state(state) == frozen
            context = json.loads(prepared["messages"][1].content)
            pending = context["results"][-1]
            assert pending["output"] is None and pending["outcome"] == "failure"
            assert pending["action"] == record["action"]
            prior_ids = {item["id"] for item in state["results"]}
            future_ids = {item["id"] for item in records[index:]}
            assert not prior_ids & future_ids
            context_ids = {item["id"] for item in context["results"][:-1]}
            assert context_ids <= prior_ids
            assert not context_ids & future_ids
            assert set(pending["action"]["arguments"]["result_ids"]) <= prior_ids
            view_key = record["action"]["arguments"]["view_key"]
            case = {
                "id": f"insight-review-call-{role.replace('_', '-')}-{ordinal}",
                "unit": "node",
                "target": "compose",
                "role": role,
                "model_call": stage,
                "purpose": f"보고서 내부 {stage} 독립 호출: {view_key or role}",
                "initial": initial_input(state),
                "providers": list(providers),
                "assessment": _call_assessment(
                    state, profile, role, stage, view_key, record["output"]
                ),
                "tags": [
                    "insight-review-candidate",
                    "independent-report-call",
                    "overlaps-compose-first-call"
                    if ordinal == 1
                    else "internal-followup-call",
                ],
            }
            case_adapter.validate_python(case)
            numeric_checks = 0
            for item in case["assessment"]["expected"]["items"]:
                if item["check"] != "N-O.1" or item.get("applicable") is False:
                    continue
                detail = _compare(
                    "N-O.1",
                    item,
                    {"role": role, "call": {"path": record["id"]}},
                    record["output"],
                    case["assessment"]["reference"]["N-O.1"],
                    {},
                )
                assert detail["verdict"] == "통과", (case["id"], detail)
                numeric_checks += 1
            cases.append(case)
            coverage.append(
                {
                    "case_id": case["id"],
                    "scenario_id": scenario["id"],
                    "source_step_id": step["step_id"],
                    "source_case_id": step["case_id"],
                    "source_result_id": record["id"],
                    "source_model_ordinal": ordinal,
                    "role": role,
                    "model_call": stage,
                    "view_key": view_key,
                    "schema": prepared["schema"].__name__,
                    "prefix_result_count": index,
                    "excluded_current_and_later": len(records) - index,
                    "future_results_in_input": False,
                    "duplicates_first_compose_call": ordinal == 1,
                    "authored_numeric_checks_passed": numeric_checks,
                }
            )
    assert len(cases) == 10, f"Expected 10 report calls, got {len(cases)}"
    assert [
        sum(c["role"] == role for c in cases)
        for role in (SELECTION, DESCRIPTION, INSIGHT)
    ] == [2, 6, 2]
    suite = {
        "schema_version": "evaluation-suite-v1",
        "id": "node-insight-review-report-calls",
        "data_source": "prepared",
        "datasets": {name: deepcopy(snapshot["datasets"][name]) for name in providers},
        "catalog": catalog,
        "cases": cases,
    }
    suite_adapter.validate_python(suite)
    return suite, {
        "purpose": "같은 보고서의 내부 모델 호출 10개를 "
        "각각 독립 평가하는 중복 관점 묶음",
        "model_calls": 10,
        "first_compose_overlaps": 3,
        "additional_internal_calls": 7,
        "new_scenario_paths": 0,
        "overlap_note": "선정·첫 설명·인사이트 작성 3개는 compose.json의 "
        "최초 호출과 중복하므로 노드 경로 수에 합산하지 않는다.",
        "future_results_in_input": False,
        "model_preparation_checked": 10,
        "authored_numeric_checks_passed": sum(
            item["authored_numeric_checks_passed"] for item in coverage
        ),
        "external_model_evaluation": "not_run",
        "cases": coverage,
    }
