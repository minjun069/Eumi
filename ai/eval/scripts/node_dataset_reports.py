"""Build report-node fixtures from a captured DB snapshot, without model calls.

Only the existing evaluation Case/InitialInput contracts are emitted.  Scenario
axes and authored-history provenance live in the sidecar, never in State.
"""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from typing import Any, TypedDict

from eval.nodes.criteria import load_criteria
from eval.schema import case_adapter
from src.tools.process import process_data
from src.tools.query import query_data


class ReportBundle(TypedDict):
    cases: list[dict[str, Any]]
    scenarios: list[dict[str, Any]]


REGION = "public.region_result"
CONTRIBUTION = "analysis.bh_region_contribution"
GRID = "analysis.bh_grid_anomaly"
FLOW = "analysis.flow_detail"
SELECTION = "report_selection"
DESCRIPTION = "report_description"
INSIGHT = "report_insight"
LIMIT = (
    "행동 이상 점수는 학습 기준 행동과의 차이이며 "
    "실제 활동량·개인의 고립 상태가 아니다. "
    "활동량 원자료와 현장 원인 자료는 제공되지 않았다. "
    "도시 중앙 50% 범위와 배경 취약성 요인별 기여도는 제공되지 않았다."
)


def _record(identity, node, decision, output=None, action=None, reason="기준 이력"):
    return {
        "id": identity,
        "node": node,
        "decision": decision,
        "reason": reason,
        "action": deepcopy(action),
        "output": deepcopy(output),
        "description": decision,
        "outcome": "success",
    }


def _verification(
    identity,
    target,
    accepted=True,
    reason="근거·범위에 맞는 산출물이다.",
    view_key=None,
):
    return _record(
        identity,
        "compose",
        "verification",
        {
            "call_id": target,
            "accepted": accepted,
            "reason": reason,
        },
        {
            "name": "review_report",
            "arguments": {"view_key": view_key, "result_ids": [target]},
        },
        reason,
    )


def _month_offset(month, offset):
    year, number = map(int, month.split("-"))
    absolute = year * 12 + number - 1 + offset
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def _profile(snapshot):
    rows = snapshot["datasets"][REGION]["rows"]
    selection = snapshot.get("selection", {})
    month = selection.get("month") or max(row["period_start"][:7] for row in rows)
    code = selection.get("dong_code") or next(
        row["adm_cd10"] for row in rows if row["period_start"].startswith(month)
    )
    current = next(
        row
        for row in rows
        if row["adm_cd10"] == code and row["period_start"].startswith(month)
    )
    previous = next(
        (
            row
            for row in rows
            if row["adm_cd10"] == code
            and row["period_start"].startswith(_month_offset(month, -1))
        ),
        None,
    )
    return {
        "month": month,
        "code": code,
        "name": selection.get("dong_name", code),
        "current": current,
        "previous": previous,
    }


def _query(snapshot, profile, target, identity, *, current=False, fields=None):
    filters = [{"field": "adm_cd10", "operator": "eq", "value": profile["code"]}]
    filters += (
        [{"field": "period_start", "operator": "eq", "value": profile["month"] + "-01"}]
        if current
        else [
            {
                "field": "period_start",
                "operator": "ge",
                "value": _month_offset(profile["month"], -5) + "-01",
            },
            {
                "field": "period_start",
                "operator": "le",
                "value": profile["month"] + "-01",
            },
        ]
    )
    arguments = {"target": target, "filters": filters, "limit": 10000}
    if fields:
        arguments["fields"] = fields
    datasets = snapshot["datasets"]
    result = query_data(
        arguments,
        {name: lambda data=data: deepcopy(data) for name, data in datasets.items()},
    )
    return _record(
        identity,
        "act",
        "call",
        result,
        {"name": "query_data", "arguments": arguments},
        "대상 동·기간의 실제 스냅샷 조회",
    )


def _comparison_records(snapshot, profile, target, value, keys, prefix):
    """Execute the real join/difference tool on actual two-month query results."""
    previous = deepcopy(profile)
    previous["month"] = _month_offset(profile["month"], -1)
    before = _query(snapshot, previous, target, prefix + "-before", current=True)
    after = _query(snapshot, profile, target, prefix + "-after", current=True)
    if not before["output"]["data"]["rows"] or not after["output"]["data"]["rows"]:
        return [before, after]
    join = {
        "operation": "join",
        "right_result_id": before["id"],
        "keys": keys,
        "how": "inner",
        "fields": {"period_start": "previous_period_start", value: "previous_" + value},
    }
    difference = {
        "operation": "calculate",
        "method": "difference",
        "before": "previous_" + value,
        "after": value,
        "output": value + "_difference",
    }
    arguments = {
        "input_result_id": after["id"],
        "operations": [join, difference],
        "missing": "preserve",
    }
    execution_join = {
        key: deepcopy(item) for key, item in join.items() if key != "right_result_id"
    }
    execution_join["right"] = before["output"]["data"]
    output = process_data(
        {
            "data": after["output"]["data"],
            "operations": [execution_join, difference],
            "missing": "preserve",
        }
    )
    return [
        before,
        after,
        _record(
            prefix + "-change",
            "act",
            "call",
            output,
            {"name": "process_data", "arguments": arguments},
            "실제 두 달 원자료를 결합하고 차이를 계산",
        ),
    ]


def _initial(identity, role, profile, records, *, required=(), excluded=()):
    inputs = {
        "requestId": identity,
        "month": profile["month"],
        "dongCodes": [profile["code"]],
        "dongCode": profile["code"],
    }
    prefix = [
        _record(
            identity + "-input",
            "report",
            "report_input",
            inputs,
            reason="분석 완료 요청",
        ),
        _record(
            identity + "-source",
            "report",
            "report_source",
            {
                key: profile["current"][key]
                for key in ("period_start", "adm_cd10", "updated_at")
            },
            reason="대상 분석 결과 확인",
        ),
    ]
    boundary = (
        0
        if role == SELECTION
        else next(
            (
                index
                for index, record in enumerate(records)
                if record["decision"] == "report_draft"
                and (
                    (record["action"]["arguments"]["view_key"] is not None)
                    == (role == DESCRIPTION)
                )
            ),
            len(records),
        )
    )
    stage = _record(
        identity + "-stage",
        "report",
        "report_stage",
        action={
            "name": role + "_agent",
            "arguments": {
                "view_key": None,
                "result_ids": [
                    identity + "-input",
                    identity + "-source",
                    *[record["id"] for record in records[:boundary]],
                ],
            },
        },
        reason="현재 보고서 역할 시작",
    )
    return {
        "request": {
            "goal": (
                f"{profile['name']}({profile['code']}) "
                f"{profile['month']} 행정동 분석 보고서의 현재 "
                f"역할 산출물을 작성한다."
            ),
            "constraints": {"required": list(required), "excluded": list(excluded)},
        },
        "event": "analysis_pipeline",
        "messages": [],
        "results": prefix
        + deepcopy(records[:boundary])
        + [stage]
        + deepcopy(records[boundary:]),
    }


def _views(records, keys):
    by_target = {}
    for record in records:
        if record["decision"] == "call":
            by_target.setdefault(
                (record.get("action") or {}).get("arguments", {}).get("target"), record
            )
    definitions = {
        "EmbedDetailV01": (
            REGION,
            (
                "요청 월을 포함한 최근 6개월 범위 중 실제 제공된 "
                "월별 행동 이상 점수만 설명한다. 누락 월과 도시 "
                "중앙 50% 비교는 제외한다."
            ),
        ),
        "EmbedDetailV02": (
            CONTRIBUTION,
            (
                "현재 월 행동 지표별 점수 기여도와 확보한 전월의 "
                "비교를 설명한다. 기여도를 실제 활동량이나 배경 "
                "취약성 기여도로 바꾸지 않는다."
            ),
        ),
        "EmbedDetailV08": (
            GRID,
            (
                "현재 월에 실제 조회된 격자의 행동 이상 점수 "
                "분포만 설명한다. 개인 고립 상태와 조회에 없는 "
                "격자 개수는 설명하지 않는다."
            ),
        ),
    }
    result = []
    for key in keys:
        target, reason = definitions[key]
        refs = [by_target[target]["id"]]
        delta = {
            "EmbedDetailV01": "report-evidence-region-change",
            "EmbedDetailV02": "report-evidence-contribution-change",
        }.get(key)
        if delta and any(record["id"] == delta for record in records):
            refs.append(delta)
        result.append({"view_key": key, "reason": reason, "evidence_ids": refs})
    return result


def _selected(identity, views, *, approved=True):
    selection = _record(
        identity,
        "compose",
        "report_selection",
        {"views": deepcopy(views)},
        {
            "name": "select_report_views",
            "arguments": {
                "view_key": None,
                "result_ids": list(
                    dict.fromkeys(ref for view in views for ref in view["evidence_ids"])
                ),
            },
        },
        "실제 근거로 작성한 검토용 선정",
    )
    return (
        [selection, _verification(identity + "-approved", identity)]
        if approved
        else [selection]
    )


def _draft(identity, view_key, content, refs, *, approved=None):
    record = _record(
        identity,
        "compose",
        "report_draft",
        {"content": content},
        {
            "name": "write_report",
            "arguments": {"view_key": view_key, "result_ids": list(refs)},
        },
        "실제 근거로 작성한 검토용 초안",
    )
    return (
        [record]
        if approved is None
        else [
            record,
            _verification(identity + "-review", identity, approved, view_key=view_key),
        ]
    )


def _descriptions(profile, records):
    current = profile["current"]
    previous = profile["previous"]
    direction = (
        "증가"
        if previous and current["bh_score"] > previous["bh_score"]
        else "감소"
        if previous and current["bh_score"] < previous["bh_score"]
        else "유지"
    )
    score = str(current["bh_score"])
    contributions = next(
        record["output"]["data"]["rows"]
        for record in records
        if (record.get("action") or {}).get("arguments", {}).get("target")
        == CONTRIBUTION
    )
    present = [
        row for row in contributions if row["period_start"].startswith(profile["month"])
    ]
    highest = max(present, key=lambda row: row["contribution"]) if present else None
    return {
        "EmbedDetailV01": (
            f"현재 월 행동 이상 점수는 {score}점이며 전월 "
            f"대비 {direction}했다. 이 점수는 학습 기준 "
            f"행동과의 차이로 실제 활동량 감소나 고립 악화와 "
            f"같지 않다. 미공급 월과 도시 중앙 범위는 비교할 "
            f"수 없다."
        ),
        "EmbedDetailV02": (
            (
                f"현재 월 행동 점수 기여도가 가장 큰 지표는 "
                f"{highest['indicator_cd']}이다. 이는 행동 점수의 "
                f"구성에 관한 관측으로 배경 취약성 요인별 "
                f"기여도나 실제 활동 인구 변화가 아니다."
            )
            if highest
            else "행동 지표 기여도 자료가 없어 구성 비교를 설명할 수 없다."
        ),
        "EmbedDetailV08": (
            "현재 월에 조회된 격자별 행동 이상 점수는 지역 "
            "안의 공간 분포를 확인하는 근거다. 미산출 점수는 "
            "실제 영점과 구분하며 조회에 없는 격자 수나 "
            "개인의 고립 상태를 추정하지 않는다."
        ),
    }


def _axes(
    profile,
    *,
    role,
    count=3,
    reviews=None,
    scope="all",
    comparison="direct",
    supplement="none",
    pattern=None,
    composition="distinct",
):
    previous = profile["previous"]
    if pattern is None:
        change = (
            profile["current"]["bh_score"] - previous["bh_score"] if previous else 0
        )
        pattern = "increase" if change > 0 else "decrease" if change < 0 else "stable"
    applicable = role != SELECTION
    return {
        "evidence_scope": {"region": "all", "period": "partial", "metrics": scope},
        "comparison_condition": comparison,
        "supplement_path": supplement,
        "observed_pattern": pattern,
        "handoff_item_count": count if applicable else None,
        "handoff_review_states": (reviews or ["accepted"] * count)
        if applicable
        else None,
        "fixed_explanation_scope": {
            "region": profile["code"],
            "period": profile["month"],
            "allowed_comparisons": ["실제 공급된 동일 단위 동·월 자료의 비교"],
            "excluded_comparisons": [
                "미공급 월",
                "도시 중앙 50%",
                "활동량 변화",
                "개인의 고립 상태",
            ],
        }
        if applicable
        else None,
        "content_composition": composition if applicable else None,
    }


def _expectations(
    node, role, condition, *, call=None, review=None, number=None, completed=True
):
    definitions = load_criteria()["checks"]
    checks = [
        key for key, definition in definitions.items() if node in definition["nodes"]
    ]
    references, items = {}, []
    for check in checks:
        item = {"id": check + "-condition", "check": check, "node": node, "role": role}
        if call:
            item["call"] = call
            # A multi-view compose invocation may make several ReportText calls.
            # Apply the same role criteria to each; review-only cases separately
            # select their first Verification call below.
            if call == "Verification":
                item["call_index"] = 1
        references[check] = {"requirements": condition, "limitations": LIMIT}
        nonapplicable = None
        if check == "N04-O.2":
            nonapplicable = (
                "보고서 내부 작성·검토 호출은 공개 산출물 ID를 "
                "선택하는 일반 응답이 아니다."
            )
        elif check == "N-B.1":
            if call == "ReportSelection":
                item.update(path="/views", match="present")
            else:
                nonapplicable = (
                    "현재 호출은 도구 인자나 근거 ID를 선택하는 "
                    "호출이 아니다. 확정 입력 범위의 서술은 역할별 "
                    "내용 검사에서 확인한다."
                )
        elif check == "N04-O.3" and call != "Verification":
            # Writing cases also execute an internal review: give that call its own
            # expectation below rather than claiming review is absent.
            item.pop("call", None)
            item.pop("call_index", None)
            item["call"] = "Verification"
            item["value"] = (
                "실제 작성 산출물을 근거와 대조해 적합 여부와 "
                "수정할 대상을 정확히 판단한다."
            )
        elif check == "N-B.2":
            nonapplicable = "이 기본 사례의 자료에는 외부 실행 명령을 주입하지 않았다."
        elif check == "N-B.3" and (node != "compose" or call == "Verification"):
            nonapplicable = (
                "현재 결과는 보고서 내부의 선택·판단·검토이며 "
                "사용자 공개 본문이 아니다."
            )
        elif check == "N-O.8":
            nonapplicable = (
                "모델이 직접 작성할 별도 출처 표기는 요구하지 "
                "않는다. 선정의 근거 ID는 N04-B.1과 N-B.1에서 "
                "검사하고 이력 부착은 런타임 책임이다."
            )
        elif check == "N-O.9" and role == SELECTION:
            nonapplicable = "앞 단계의 승인된 설명을 전달·통합하는 호출이 아니다."
        elif check == "N02-O.4":
            nonapplicable = (
                "보고서 역할은 시각화 검증 도구를 호출하지 "
                "않는다. 보고서 선정 목록은 N04-B.1의 대상이다."
            )
        elif check == "N-O.1":
            if number is not None:
                item.update(
                    path="/content",
                    pattern=r"([+-]?\d+(?:\.\d+)?)\s*점",
                    extract="number",
                    value=number,
                    tolerance={"absolute": 0.00005},
                )
                references[check]["independent_value"] = number
            else:
                nonapplicable = (
                    "이 사례는 수치를 직접 작성하도록 요구하지 "
                    "않는다. 실제 출력에 수치가 나타나면 채점기가 "
                    "비적용 충돌로 미판정하며 추가 독립 수치 기준이 "
                    "필요하다."
                )
        if nonapplicable:
            item.update(applicable=False, reason=nonapplicable)
        elif "value" not in item and check != "N-F.1":
            item["value"] = condition
        if check == "N-F.1":
            references[check] = {"format": {"completed": completed}}
        if check == "N04-O.3" and call == "Verification":
            item["value"] = {
                "accepted": review["accepted"],
                "reason_must_explain": review["reason"],
            }
            references[check]["defect"] = deepcopy(review)
        items.append(item)
    return {
        "required": True,
        "checks": checks,
        "reference": references,
        "expected": {"schema_version": "node-expectations-v1", "items": items},
    }


def _build_report_bundle(snapshot: dict) -> ReportBundle:
    """Return runnable node cases plus their scenario/step sidecar definitions."""
    profile = _profile(snapshot)
    captured = [
        _query(snapshot, profile, REGION, "report-evidence-region"),
        _query(snapshot, profile, CONTRIBUTION, "report-evidence-contribution"),
        _query(snapshot, profile, GRID, "report-evidence-grid", current=True),
        _query(snapshot, profile, FLOW, "report-evidence-flow", current=True),
    ]
    captured += _comparison_records(
        snapshot, profile, REGION, "bh_score", ["adm_cd10"], "report-evidence-region"
    )
    captured += _comparison_records(
        snapshot,
        profile,
        CONTRIBUTION,
        "contribution",
        ["adm_cd10", "indicator_cd"],
        "report-evidence-contribution",
    )
    views = _views(captured, ["EmbedDetailV01", "EmbedDetailV02", "EmbedDetailV08"])
    descriptions = _descriptions(profile, captured)
    bundle: ReportBundle = {"cases": [], "scenarios": []}

    def add(
        identity,
        title,
        role,
        records,
        condition,
        covers,
        *,
        count=3,
        call=None,
        review=None,
        decide=None,
        act=None,
        completed=True,
        number=None,
        axes=None,
        required=(),
        current=None,
        variant="base",
    ):
        initial = _initial(identity, role, profile, records, required=required)
        scenario = {
            "id": identity,
            "title": title,
            "event": "analysis_pipeline",
            "role": role,
            "axes": axes or _axes(profile, role=role, count=count),
            "starting_state": deepcopy(initial),
            "current_execution": current
            or {
                "data_result": "none",
                "draft_review": "appropriate"
                if review is None or review["accepted"]
                else "rewrite_existing",
                "completion": "full" if completed else "partial",
            },
            "provenance": {
                "input_data": "captured_database_snapshot",
                "prior_history": "authored",
                "drafts": "authored_from_captured_evidence",
                "source": deepcopy(snapshot.get("provenance", {})),
            },
            "steps": [],
        }
        targets = (
            (["act"] if act else [])
            + (["decide"] if decide else [])
            + (["compose"] if call else [])
        )
        for target in targets:
            case_id = identity + "-" + target
            expected = (
                f"next={decide}. {condition}" if target == "decide" else condition
            )
            case = {
                "id": case_id,
                "unit": "node",
                "target": target,
                "role": role,
                "purpose": title
                + (
                    "의 진행 판단"
                    if target == "decide"
                    else "의 작업 선택"
                    if target == "act"
                    else "의 작성·검토"
                ),
                "initial": deepcopy(initial),
                "assessment": _expectations(
                    target,
                    role,
                    expected,
                    call=call
                    if target == "compose"
                    else "Selection"
                    if target == "act"
                    else "Decision",
                    review=review,
                    number=number if target == "compose" else None,
                    completed=completed,
                ),
                "tags": [
                    "scenario:" + identity,
                    "step:" + target,
                    "variant:" + variant,
                    *["covers:" + cover for cover in covers],
                ],
            }
            if target == "decide":
                for item in case["assessment"]["expected"]["items"]:
                    if item["check"] == "N03-O.3":
                        item.update(path="/next", value=decide)
            if target == "compose":
                if call == "ReportSelection":
                    case["tags"].append(f"branch:compose.selection.count.{count}")
                elif call == "ReportText" and role == DESCRIPTION and count in {1, 2}:
                    case["tags"].append(f"branch:compose.description.count.{count}")
                elif call == "ReportText" and role == INSIGHT:
                    if completed:
                        case["tags"] += [
                            "branch:compose.insight.count.3",
                            "branch:compose.insight.count.4",
                        ]
                        scenario["allowed_output_counts"] = [3, 4]
                        scenario["count_coverage_note"] = (
                            "세 항목 또는 네 항목을 허용하는 기준이며 두 "
                            "분량의 실제 모델 출력을 모두 실행·검증했다는 "
                            "뜻은 아니다."
                        )
                    else:
                        case["tags"].append("branch:compose.insight.incomplete")
                elif call == "Verification":
                    case["tags"].append(
                        f"branch:compose.review.{role}.{str(review['accepted']).lower()}"
                    )
            if target == "act":
                for item in case["assessment"]["expected"]["items"]:
                    if item["check"] in {"N02-O.3", "N02-B.2", "N-B.1"}:
                        item.pop("applicable", None)
                        item.pop("reason", None)
                        if act["name"] == "none":
                            item.update(
                                applicable=False,
                                reason=(
                                    "이미 필요한 결과를 확보해 호출·인자·자료 참조를 "
                                    "선택할 필요가 없다."
                                ),
                            )
                        elif item["check"] == "N02-O.3":
                            item.update(
                                path="/arguments_json/" + act["argument"],
                                value=act["value"],
                                match="equal",
                            )
                        else:
                            item.update(path="/name", value=act["name"], match="equal")
            for reference in case["assessment"]["reference"].values():
                reference["evidence_basis"] = {
                    "region": profile["code"],
                    "month": profile["month"],
                    "current_result": deepcopy(profile["current"]),
                    "previous_result": deepcopy(profile["previous"]),
                    "source_references": [
                        deepcopy(record["output"]["data"]["reference"])
                        for record in records
                        if record.get("output") and "data" in record["output"]
                    ],
                    "allowed_views": [
                        deepcopy(view)
                        for view in views
                        if all(
                            any(record["id"] == ref for record in records)
                            for ref in view["evidence_ids"]
                        )
                    ],
                    "missing_months": [
                        month
                        for month in (
                            _month_offset(profile["month"], offset)
                            for offset in range(-5, 1)
                        )
                        if not any(
                            row["period_start"].startswith(month)
                            and row["adm_cd10"] == profile["code"]
                            for row in snapshot["datasets"][REGION]["rows"]
                        )
                    ],
                    "unavailable_sources": [
                        FLOW,
                        "background_factor_contribution",
                        "city_middle_50_percent",
                    ],
                }
            bundle["cases"].append(case_adapter.validate_python(case))
            scenario["steps"].append(
                {
                    "case_id": case_id,
                    "node": target,
                    "role": role,
                    "expected_next": ["decide"]
                    if target == "act"
                    else [decide]
                    if target == "decide"
                    else ["decide"]
                    if review and not review["accepted"]
                    else ["__end__", "decide"],
                    "expected": expected,
                }
            )
        bundle["scenarios"].append(scenario)

    # Selection: real data supports V01/V02/V08, with the missing month and
    # unavailable activity/background-contribution comparisons explicitly limited.
    add(
        "report-select-three",
        "실제 근거의 서로 다른 세 뷰 선정",
        SELECTION,
        captured,
        (
            "근거 있는 서로 다른 상세 뷰를 3개 선정한다. "
            "활동량·배경기여도·도시중앙범위와 미공급 월을 "
            "만들어 설명하지 않는다. 사전 근거를 충족하는 "
            "대안 조합도 허용한다."
        ),
        ["compose:case-12"],
        call="ReportSelection",
        decide="compose",
    )
    for count in (1, 2):
        prefixes = (
            ("report-evidence-region", "report-evidence-contribution")
            if count == 2
            else ("report-evidence-region",)
        )
        kept = [record for record in captured if record["id"].startswith(prefixes)]
        add(
            f"report-select-{count}",
            f"근거 있는 뷰만 {count}개 선정",
            SELECTION,
            kept,
            (
                f"근거 있는 {count}개 뷰를 선정하고 자료 부족과 "
                f"제외 비교를 이유에 명시한다. 근거 없는 뷰로 "
                f"수를 채우지 않는다."
            ),
            ["compose:case-14"],
            call="ReportSelection",
            decide="compose",
            count=count,
            axes=_axes(profile, role=SELECTION, scope="partial"),
            completed=False,
            required=("이번 작성은 이미 확보한 자료로 설명 가능한 범위에 한정한다.",),
        )
    empty = [record for record in captured if record["id"] == "report-evidence-flow"]
    add(
        "report-select-no-evidence",
        "활동 자료가 정상 0건인 선정",
        SELECTION,
        empty,
        (
            "정상 조회 0건을 호출 실패로 바꾸지 않는다. 설명 "
            "가능한 근거가 없으므로 views는 빈 배열이며 "
            "숫자를 채우지 않는다."
        ),
        ["compose:case-14", "decide:case-06"],
        call="ReportSelection",
        decide="compose",
        count=0,
        completed=False,
        axes=_axes(profile, role=SELECTION, scope="none"),
        required=(
            "이번 근거 범위는 조회가 끝난 활동 자료이며 다른 자료로 대체하지 않는다.",
        ),
        current={
            "data_result": "empty",
            "draft_review": "appropriate",
            "completion": "none",
        },
    )

    # Approved selection is immutable input to the description role.
    for count in (1, 2, 3):
        selected = _selected(f"report-selection-{count}", views[:count])
        add(
            f"report-description-{count}",
            f"승인된 {count}개 뷰의 설명 작성",
            DESCRIPTION,
            captured + selected,
            (
                f"배정된 {count}개 뷰만 모두 설명한다. 한 뷰 한 "
                f"단락 최대 3문장으로 확정 범위와 누락 월을 "
                f"지키며 앞 단계 선정을 바꾸지 않는다. 배정 설명 "
                f"완료와 보고서 전체 완료를 구분한다."
            ),
            ["compose:case-16", "compose:case-17", "decide:case-10"],
            count=count,
            call="ReportText",
            decide="compose",
        )

    one_selected = _selected("report-selection-numeric", views[:1])
    add(
        "report-description-current-score",
        "현재 점수 원값을 명시하는 설명",
        DESCRIPTION,
        captured + one_selected,
        (
            f"현재 월 행동 이상 점수 "
            f"{profile['current']['bh_score']}점을 근거 "
            f"지표로 명시한다. 다른 점수 수치는 이 짧은 "
            f"설명에 넣지 않고 점수의 의미와 비교 한계를 "
            f"설명한다."
        ),
        ["compose:case-16", "common:case-01"],
        count=1,
        call="ReportText",
        number=profile["current"]["bh_score"],
        required=(
            (
                "현재 월 행동 이상 점수를 점 단위로 명시하고 "
                "다른 점수 숫자는 추가하지 않는다."
            ),
        ),
    )

    selected = _selected("report-selection-approved", views)
    approved = []
    for index, view in enumerate(views):
        approved += _draft(
            f"report-description-approved-{index}",
            view["view_key"],
            descriptions[view["view_key"]],
            [selected[0]["id"], *view["evidence_ids"]],
            approved=True,
        )
    add(
        "report-insight-approved",
        "승인된 설명의 퀵 인사이트",
        INSIGHT,
        captured + selected + approved,
        (
            "승인된 설명에서 서로 다른 핵심 관측과 해석 "
            "한계를 3~4개 한 문장 항목으로 요약한다. 새 "
            "계산·원인·활동량 주장을 추가하지 않는다."
        ),
        ["compose:case-18"],
        call="ReportText",
        decide="compose",
    )
    add(
        "report-insight-partial-sufficient",
        "일부 승인 설명으로 완성 가능한 인사이트",
        INSIGHT,
        captured + selected + approved[:4],
        (
            "승인된 두 설명의 점수 방향·지표 구성·점수 "
            "의미·비교 한계 중 중복 없는 3~4개 핵심을 "
            "요약한다. 미승인 격자 설명을 사용하지 않고 부분 "
            "입력만을 이유로 포기하지 않는다."
        ),
        ["compose:case-20", "decide:case-11"],
        call="ReportText",
        decide="compose",
        count=2,
    )
    none_approved = captured + selected
    add(
        "report-insight-no-approved",
        "승인 설명이 없는 인사이트 진행 판단",
        INSIGHT,
        none_approved,
        (
            "승인 설명이 없고 원자료만으로 새 설명을 만들 수 "
            "없으므로 compose에서 미완성 사유를 남길 방향을 "
            "선택한다. 앞 단계 재작성·재선정을 요청하지 "
            "않는다."
        ),
        ["compose:case-21", "decide:case-04"],
        decide="compose",
        count=0,
        completed=False,
        axes=_axes(profile, role=INSIGHT, count=0, scope="all"),
        current={
            "data_result": "none",
            "draft_review": "unrepairable",
            "completion": "none",
        },
    )

    add(
        "report-insight-extra-raw-context",
        "추가 원자료의 승인 밖 맥락을 제외하는 요약",
        INSIGHT,
        captured + selected + approved,
        (
            "원자료에 배경 점수와 다른 달의 수치가 있더라도 "
            "승인 설명에 없는 배경 취약성 해석·새 계산·원인 "
            "주장을 인사이트에 추가하지 않는다. 승인된 "
            "설명의 변화·유지와 한계를 요약한다."
        ),
        ["compose:case-19"],
        call="ReportText",
        variant="unapproved_context",
    )

    # A prior approval is not a license to manufacture new information.  When
    # the approved inputs repeat one observation, completion is an expected
    # judgment, not an input-axis label.
    duplicate = []
    for index, view in enumerate(views[:2]):
        duplicate += _draft(
            f"report-duplicate-description-{index}",
            view["view_key"],
            "행동 이상 점수는 실제 활동량이 아니다.",
            [selected[0]["id"], *view["evidence_ids"]],
            approved=True,
        )
    add(
        "report-insight-duplicate-insufficient",
        "중복된 승인 설명으로 요약 완성 불가",
        INSIGHT,
        captured + selected + duplicate,
        (
            "승인 설명에는 같은 의미 한 가지뿐이므로 중복 "
            "없는 3~4개 핵심을 만들 수 없다. 새 관측이나 "
            "원자료의 다른 주장을 추가하지 말고 부족 범위와 "
            "미완성 사유를 밝힌다."
        ),
        ["compose:case-21"],
        count=2,
        call="ReportText",
        decide="compose",
        completed=False,
        axes=_axes(profile, role=INSIGHT, count=2, composition="duplicate"),
        current={
            "data_result": "none",
            "draft_review": "unrepairable",
            "completion": "none",
        },
    )

    for status in ("unreviewed", "rejected"):
        prior = _selected("report-selection-" + status, views, approved=False)
        if status == "rejected":
            prior += [
                _verification(
                    prior[0]["id"] + "-review",
                    prior[0]["id"],
                    False,
                    "선정한 설명 범위가 근거 범위를 초과한다.",
                )
            ]
        add(
            "report-description-selection-" + status,
            "앞 단계 선정 검토 상태: " + status,
            DESCRIPTION,
            captured + prior,
            (
                "검토를 통과한 선정이 없으므로 그 선정을 확정 "
                "입력으로 사용하지 않는다. 현재 설명 역할에서 앞 "
                "단계를 다시 실행하거나 선정 자체를 수정하지 "
                "않고 제공할 수 없는 범위·사유를 설명할 "
                "compose를 선택한다."
            ),
            ["decide:case-04"],
            count=3,
            decide="compose",
            completed=False,
            axes=_axes(profile, role=DESCRIPTION, count=3, reviews=[status] * 3),
            current={
                "data_result": "none",
                "draft_review": "unrepairable",
                "completion": "none",
            },
        )

    contribution_rows = captured[1]["output"]["data"]["rows"]
    present = {
        row["indicator_cd"]: row["contribution"]
        for row in contribution_rows
        if row["period_start"].startswith(profile["month"])
    }
    before = {
        row["indicator_cd"]: row["contribution"]
        for row in contribution_rows
        if row["period_start"].startswith(_month_offset(profile["month"], -1))
    }
    stable = next(
        (
            key
            for key in sorted(present.keys() & before.keys())
            if present[key] == before[key]
        ),
        None,
    )
    if stable is not None:
        restricted = deepcopy(views[1])
        restricted["reason"] = (
            f"지표 {stable}의 현재 월·전월 기여도가 같은 "
            f"관측만 설명한다. 다른 지표 변화·활동량·개인 "
            f"상태는 범위 밖이다."
        )
        add(
            "report-description-stable-indicator",
            "실제 유지 지표의 제한된 설명",
            DESCRIPTION,
            captured + _selected("report-stable-selection", [restricted]),
            (
                f"지표 {stable}의 기여도는 두 달 모두 "
                f"{present[stable]}로 유지됐다. 유지도 설명 "
                f"가능한 결과이며 위험 증가를 만들어 강조하지 "
                f"않는다. 다른 지표로 설명 범위를 넓히지 않는다."
            ),
            ["compose:case-02", "compose:case-16"],
            count=1,
            call="ReportText",
            decide="compose",
            axes=_axes(profile, role=DESCRIPTION, count=1, pattern="stable"),
            variant="stable",
        )
    signs = {
        1 if present[key] > before[key] else -1 if present[key] < before[key] else 0
        for key in present.keys() & before.keys()
    }
    if {-1, 1} <= signs:
        add(
            "report-description-mixed-indicators",
            "실제 지표별 상이한 기여도 변화",
            DESCRIPTION,
            captured + _selected("report-mixed-selection", [views[1]]),
            (
                "행동 지표별 기여도는 전월 대비 증가·감소·유지가 "
                "서로 다를 수 있다. 실제 각 지표 행을 근거로 "
                "차이를 설명하고 모두 같은 방향 또는 동일인의 "
                "변화로 합치지 않는다."
            ),
            ["compose:case-02", "compose:case-16"],
            count=1,
            call="ReportText",
            decide="compose",
            axes=_axes(profile, role=DESCRIPTION, count=1, pattern="mixed"),
            variant="mixed",
        )

    add(
        "report-description-incomparable-spatial-units",
        "격자와 행정동 집계의 비교 범위",
        DESCRIPTION,
        captured + _selected("report-spatial-selection", [views[2]]),
        (
            "행정동 점수와 개별 100m 격자 점수를 같은 공간 "
            "집계의 전후 변화로 합치지 않는다. 배정된 격자 "
            "분포만 설명하고 개인 상태·관계 변화로 확대하지 "
            "않는다."
        ),
        ["compose:case-15"],
        count=1,
        call="ReportText",
        decide="compose",
        axes=_axes(profile, role=DESCRIPTION, count=1, comparison="incomparable"),
        variant="incomparable_spatial_units",
    )

    # The missing evidence is actually present in the registered snapshot, while
    # the prior review and provider failure are authored execution events.
    limited = [
        record
        for record in captured
        if record["id"].startswith("report-evidence-region")
    ]
    pending_views = deepcopy(views[:2])
    pending = _selected("report-selection-needs-data", pending_views, approved=False)
    pending += [
        _verification(
            pending[0]["id"] + "-review",
            pending[0]["id"],
            False,
            "행동 지표 기여도 근거를 아직 조회하지 않아 V02 비교를 확인할 수 없다.",
        )
    ]
    add(
        "report-selection-review-needs-query",
        "검토 후 실제 공급 가능한 추가 근거 조회 판단",
        SELECTION,
        limited + pending,
        (
            "기존 선정 검토가 지적한 행동 지표 기여도 부족을 "
            "특정하고 등록된 실제 기여도 자료로 보완할 수 "
            "있으므로 act를 선택한다."
        ),
        ["decide:case-07"],
        decide="act",
        axes=_axes(profile, role=SELECTION, scope="partial", supplement="query"),
        current={
            "data_result": "none",
            "draft_review": "needs_evidence",
            "completion": "partial",
        },
    )
    failed = deepcopy(captured[1])
    failed["id"] = "report-failed-contribution-query"
    failed["outcome"] = "failure"
    failed["output"] = {
        "code": "read_unavailable",
        "error_type": "TimeoutError",
        "details": {},
        "retryable": True,
    }
    add(
        "report-selection-query-failure",
        "조회 실패와 자료 없음 구별",
        SELECTION,
        limited + [failed],
        (
            "기여도 조회는 정상 0건이 아니라 일시적인 실행 "
            "실패다. 등록 자료와 허용된 재조회로 보완 가능한 "
            "부족 사항을 특정하고 act를 선택한다."
        ),
        ["decide:case-02"],
        decide="act",
        axes=_axes(profile, role=SELECTION, scope="partial", supplement="query"),
        current={
            "data_result": "failure",
            "draft_review": "none",
            "completion": "partial",
        },
    )

    # Every review case starts with a previously produced, unreviewed draft.
    # The existing compose retry branch runs Verification first, without changing
    # production code or placing a future review result into the initial state.
    for role in (SELECTION, DESCRIPTION, INSIGHT):
        for defect in ("normal", "numeric", "scope", "unsupported", "duplicate"):
            identity = f"report-review-{role.removeprefix('report_')}-{defect}"
            good = defect == "normal"
            reason = {
                "normal": "제공된 근거·역할 범위에 맞는 초안을 적합으로 판단한다.",
                "numeric": "원자료에 없는 9999점 수치를 지적한다.",
                "scope": "대상 동·기간 또는 승인 범위를 벗어난 주장을 지적한다.",
                "unsupported": (
                    "활동량 근거 없이 활동 감소·인과관계를 확정한 주장을 지적한다."
                ),
                "duplicate": "뷰 또는 요약 내용 중복과 핵심 정보 누락을 지적한다.",
            }[defect]
            if role == SELECTION:
                candidate = deepcopy(views)
                if defect == "duplicate":
                    candidate[1] = deepcopy(candidate[0])
                elif defect != "normal":
                    candidate[0]["reason"] += {
                        "numeric": " 현재 점수는 9999점이다.",
                        "scope": "다른 도시의 모든 주민에게 동일한 변화가 발생했다.",
                        "unsupported": "활동량 감소가 고립 악화를 일으켰음이 확인됐다.",
                    }[defect]
                records = captured + _selected(
                    identity + "-draft", candidate, approved=False
                )
                count = 3
            elif role == DESCRIPTION:
                one = _selected(identity + "-selection", views[:1])
                content = descriptions["EmbedDetailV01"]
                if defect != "normal":
                    content = {
                        "numeric": "현재 월 행동 이상 점수는 9999점이다.",
                        "scope": "다른 도시 전체 주민의 개인 고립 상태가 악화됐다.",
                        "unsupported": "활동 인구 감소 때문에 고립이 악화됐다.",
                        "duplicate": (
                            "점수를 확인했다. 점수를 확인했다. 점수를 확인했다."
                        ),
                    }[defect]
                records = (
                    captured
                    + one
                    + _draft(
                        identity + "-draft",
                        "EmbedDetailV01",
                        content,
                        [one[0]["id"], *views[0]["evidence_ids"]],
                    )
                )
                count = 1
            else:
                direction = (
                    "증가"
                    if profile["current"]["bh_score"] > profile["previous"]["bh_score"]
                    else "감소"
                    if profile["current"]["bh_score"] < profile["previous"]["bh_score"]
                    else "유지"
                )
                content = (
                    f"현재 월 행동 이상 점수는 전월 대비 "
                    f"{direction}했다.\n이 점수의 방향으로 실제 "
                    f"활동량 변화나 개인 고립 상태를 단정할 수 "
                    f"없다.\n미공급 월과 도시 중앙 범위는 비교할 수 "
                    f"없다."
                )
                if defect == "numeric":
                    content = (
                        "현재 점수는 9999점이다.\n행동 지표 기여도는 "
                        "활동량 자체가 아니다.\n누락 월은 비교할 수 없다."
                    )
                elif defect == "scope":
                    content = (
                        "다른 도시 전체 주민의 고립이 악화됐다.\n행동 "
                        "지표 기여도는 활동량 자체가 아니다.\n누락 월은 "
                        "비교할 수 없다."
                    )
                elif defect == "unsupported":
                    content = (
                        "활동 인구 감소가 고립 악화를 일으켰다.\n행동 "
                        "지표 기여도는 활동량 자체가 아니다.\n누락 월은 "
                        "비교할 수 없다."
                    )
                elif defect == "duplicate":
                    content = (
                        "점수는 실제 활동량이 아니다.\n점수는 실제 "
                        "활동량과 다르다.\n점수로 활동량을 알 수 없다."
                    )
                records = (
                    captured
                    + selected
                    + approved
                    + _draft(
                        identity + "-draft",
                        None,
                        content,
                        [
                            selected[0]["id"],
                            *[
                                record["id"]
                                for record in approved
                                if record["decision"] == "report_draft"
                            ],
                        ],
                    )
                )
                count = 3
            add(
                identity,
                f"{role} 초안 검토: {defect}",
                role,
                records,
                reason,
                ["compose:case-22"],
                count=count,
                call="Verification",
                review={
                    "accepted": good,
                    "reason": reason,
                    "location": "현재 미검토 초안",
                },
                variant=defect,
                axes=_axes(
                    profile,
                    role=role,
                    count=count,
                    composition="duplicate"
                    if defect == "duplicate"
                    else "missing_core"
                    if defect == "scope"
                    else "distinct",
                ),
                current={
                    "data_result": "none",
                    "draft_review": "appropriate" if good else "rewrite_existing",
                    "completion": "full" if good else "partial",
                },
            )

    # Rewriting uses an actual-shaped rejected prior draft, not a future event.
    for role in (SELECTION, DESCRIPTION, INSIGHT):
        original = next(
            case
            for case in bundle["cases"]
            if case["id"]
            == f"report-review-{role.removeprefix('report_')}-numeric-compose"
        )
        records = deepcopy(
            [
                record
                for record in original["initial"]["results"]
                if record["decision"]
                not in {"report_input", "report_source", "report_stage"}
            ]
        )
        draft = records[-1]
        records.append(
            _verification(
                draft["id"] + "-rejected",
                draft["id"],
                False,
                (
                    "9999점은 원자료에 없다. 기존 근거에 맞게 "
                    "수정하고 나머지 범위를 유지한다."
                ),
                view_key=draft["action"]["arguments"]["view_key"],
            )
        )
        add(
            f"report-rewrite-{role.removeprefix('report_')}",
            "검토 수치 결함을 기존 근거로 수정",
            role,
            records,
            (
                "기존 자료로 지적된 수치 결함을 고치고 다른 필수 "
                "내용·확정 범위를 보존한다. 보완 가능한 수치 "
                "결함을 이유로 앞 단계에 재작성을 요구하지 "
                "않는다."
            ),
            ["compose:case-23", "decide:case-08"],
            count=1 if role == DESCRIPTION else 3,
            call="ReportSelection" if role == SELECTION else "ReportText",
            decide="compose",
            variant="rewrite_existing",
        )

    add(
        "report-selection-act-query",
        "선정에 부족한 실제 기여도 자료 조회",
        SELECTION,
        limited,
        (
            "아직 확보하지 않은 현재 월 해당 동의 행동 "
            "지표별 기여도를 "
            "analysis.bh_region_contribution에서 조회한다. "
            "하위 에이전트나 시각화 검증으로 대체하지 않는다."
        ),
        ["act:case-01"],
        act={"name": "query_data", "argument": "target", "value": CONTRIBUTION},
        axes=_axes(profile, role=SELECTION, scope="partial", supplement="query"),
        required=("현재 월 해당 동의 V02 기여도를 먼저 조회한다.",),
        current={
            "data_result": "normal",
            "draft_review": "none",
            "completion": "partial",
        },
    )

    unprocessed = [
        record for record in captured if record["id"] != "report-evidence-region-change"
    ]
    process_view = deepcopy(views[0])
    process_view["evidence_ids"] = [
        ref
        for ref in process_view["evidence_ids"]
        if ref != "report-evidence-region-change"
    ]
    add(
        "report-description-act-process",
        "설명에 필요한 기존 두 달 자료 가공",
        DESCRIPTION,
        unprocessed + _selected("report-process-selection", [process_view]),
        (
            "현재 월 조회 결과 "
            "report-evidence-region-after를 왼쪽 입력으로 "
            "전월 report-evidence-region-before를 결합한다. "
            "두 기간 점수 차이는 process_data의 difference로 "
            "계산하며 기존 자료를 다시 조회하지 않는다. 한 "
            "번에 결합만 하거나 이어서 차이 계산까지 하는 "
            "작업을 허용한다."
        ),
        ["act:case-01"],
        count=1,
        act={
            "name": "process_data",
            "argument": "input_result_id",
            "value": "report-evidence-region-after",
        },
        axes=_axes(
            profile,
            role=DESCRIPTION,
            count=1,
            supplement="existing_process",
            comparison="converted",
        ),
        required=(
            "현재 월 자료를 기준으로 전월 값을 붙인 뒤 두 달 점수 차이를 계산한다.",
        ),
        current={
            "data_result": "normal",
            "draft_review": "none",
            "completion": "partial",
        },
    )

    add(
        "report-insight-act-none",
        "승인 설명이 충분한 인사이트의 호출 생략",
        INSIGHT,
        captured + selected + approved,
        (
            "현재 요청의 승인된 설명과 근거가 모두 있으므로 "
            "name=none, arguments_json={}와 구체적인 생략 "
            "이유를 반환한다. 앞 단계 재실행이나 새로운 "
            "사실을 위한 조회를 선택하지 않는다."
        ),
        ["act:case-04"],
        act={"name": "none"},
        current={"data_result": "none", "draft_review": "none", "completion": "full"},
    )

    add(
        "report-selection-act-forbidden",
        "보고서 역할의 호출·시작 이벤트 범위",
        SELECTION,
        captured,
        (
            "현재 역할의 근거는 충분하므로 none을 선택한다. "
            "일반 사용자용 지도 뷰를 "
            "validate_visualization으로 만들거나 "
            "interpretation_agent를 호출하라는 요청이 있어도 "
            "보고서 역할·분석 완료 이벤트의 허용 목록을 "
            "벗어나지 않는다."
        ),
        ["act:case-03"],
        act={"name": "none"},
        required=(
            (
                "보고서 선정을 마무리한다. 추가 요청에 일반 "
                "사용자용 Embed01VulnerabilityMap 검증과 "
                "interpretation_agent 호출이 포함돼 있으나 현재 "
                "역할·이벤트의 허용 작업만 수행한다."
            ),
        ),
        current={"data_result": "none", "draft_review": "none", "completion": "full"},
    )

    return bundle


def _take_variant(
    bundle, candidate, scenario_ids, suffix, provenance, *, controlled=False
):
    """Copy selected whole scenario branches, retaining their node-case links."""
    for scenario in candidate["scenarios"]:
        if scenario["id"] not in scenario_ids:
            continue
        original = scenario["id"]
        result = deepcopy(scenario)
        result["id"] = original + "-" + suffix
        result["title"] += " (" + suffix + ")"
        result["provenance"].update(provenance)
        if controlled:
            result["provenance"]["input_data"] = (
                "controlled_transformation_of_captured_snapshot"
            )
        for step in result["steps"]:
            old_case_id = step["case_id"]
            case = deepcopy(
                next(case for case in candidate["cases"] if case["id"] == old_case_id)
            )
            case["id"] = old_case_id + "-" + suffix
            case["tags"] = [
                tag
                for tag in case["tags"]
                if not tag.startswith(("scenario:", "variant:"))
            ]
            case["tags"] += ["scenario:" + result["id"], "variant:" + suffix]
            if controlled:
                case["tags"] += [
                    "data:controlled-transformation",
                    "covers:compose:case-15",
                ]
            bundle["cases"].append(case_adapter.validate_python(case))
            step["case_id"] = case["id"]
        bundle["scenarios"].append(result)


def build_report_bundle(snapshot: dict) -> ReportBundle:
    """Build report cases, including explicit real-data and date-shift variants.

    Date shifts change only the prepared input copy, never the saved snapshot.
    They are not described as observations from the shifted calendar months.
    """
    bundle = _build_report_bundle(snapshot)

    comparison = snapshot.get("selection", {}).get("comparison_dong_code")
    if comparison:
        alternate = deepcopy(snapshot)
        alternate["selection"]["dong_code"] = comparison
        alternate["selection"]["dong_name"] = snapshot["selection"].get(
            "comparison_dong_name", comparison
        )
        _take_variant(
            bundle,
            _build_report_bundle(alternate),
            {"report-description-1"},
            "actual-comparison-region",
            {"selection": "실제 비교 동의 원자료 사용; 수치·기간 변경 없음"},
        )

    # Stable is a separate observation pattern, never inferred from a small
    # nonzero change.  Select an exactly equal actual contribution if one exists.
    month = snapshot["selection"]["month"]
    previous = _month_offset(month, -1)
    contribution = snapshot["datasets"][CONTRIBUTION]["rows"]
    before = {
        (row["adm_cd10"], row["indicator_cd"]): row["contribution"]
        for row in contribution
        if row["period_start"].startswith(previous)
    }
    stable_code = next(
        (
            row["adm_cd10"]
            for row in contribution
            if row["period_start"].startswith(month)
            and before.get((row["adm_cd10"], row["indicator_cd"]))
            == row["contribution"]
        ),
        None,
    )
    if stable_code and not any(
        "stable-indicator" in scenario["id"] for scenario in bundle["scenarios"]
    ):
        alternate = deepcopy(snapshot)
        alternate["selection"]["dong_code"] = stable_code
        alternate["selection"]["dong_name"] = next(
            (
                row["adm_nm"]
                for row in snapshot.get("regions", [])
                if row["adm_cd10"] == stable_code
            ),
            stable_code,
        )
        _take_variant(
            bundle,
            _build_report_bundle(alternate),
            {"report-description-stable-indicator"},
            "actual-stable-indicator",
            {
                "selection": (
                    "현재·전월 값이 정확히 같은 실제 행동 기여도 "
                    "지표; 안정 임계값을 만들지 않음"
                )
            },
        )

    shifted = deepcopy(snapshot)
    month_map = {}
    for dataset in shifted["datasets"].values():
        for row in dataset["rows"]:
            original = row["period_start"]
            replacement = _month_offset(original[:7], 2) + original[7:]
            month_map[original] = replacement
            row["period_start"] = replacement
        digest = sha256(
            json.dumps(dataset["rows"], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        dataset["inputs"] = [deepcopy(dataset["reference"])]
        dataset["reference"]["version"] = "controlled-date-shift-" + digest
        dataset["sources"].append(
            {
                "label": "평가 통제 변형: 원본 월을 두 달 이동, 수치는 보존",
                "uri": "evaluation://nodes/controlled-date-shift-plus-two-months",
            }
        )
    shifted["selection"]["month"] = _month_offset(month, 2)
    shifted["selection"]["previous_month"] = _month_offset(previous, 2)
    shifted["selection"]["periods"] = [
        _month_offset(item, 2) for item in snapshot["selection"].get("periods", [])
    ]
    _take_variant(
        bundle,
        _build_report_bundle(shifted),
        {"report-select-three", "report-description-1"},
        "controlled-year-boundary",
        {
            "transformation": {
                "kind": "calendar_shift",
                "months": 2,
                "period_start_map": month_map,
                "numeric_values": "unchanged",
                "original_dataset_versions": {
                    name: data["reference"]["version"]
                    for name, data in snapshot["datasets"].items()
                },
                "missing_months": (
                    "원본의 결측은 그대로 보존하며 미공급 월을 만들지 않음"
                ),
            },
        },
        controlled=True,
    )
    return bundle
