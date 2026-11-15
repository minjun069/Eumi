"""실제 보고서 노드와 고정 모델 응답으로 시작부터 반환까지의 평가 경로를 만든다.

고정 응답은 다음 입력을 만드는 작성 이력이다. 품질 판정 기준은 별도의
assessment에 두며, 결함을 넣은 작성 응답을 정답으로 사용하지 않는다.
"""

from __future__ import annotations

import json
from copy import deepcopy

from eval.scripts.node_dataset_reports import (
    CONTRIBUTION,
    DESCRIPTION,
    FLOW,
    GRID,
    INSIGHT,
    LIMIT,
    REGION,
    SELECTION,
    _descriptions,
    _expectations,
    _month_offset,
    _profile,
    _views,
)
from src.agent_nodes import approved_report_selection
from src.execution import accepted_outputs

KEYS = ("EmbedDetailV01", "EmbedDetailV02", "EmbedDetailV08")
APPROVED = {"accepted": True, "reason": "작성 내용이 조회 근거와 확정 범위에 맞는다."}


def _replace(value, identities):
    if isinstance(value, str):
        return identities.get(value, value)
    if isinstance(value, list):
        return [_replace(item, identities) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, identities) for key, item in value.items()}
    return value


def _initial(prototype, profile, *, count):
    records = deepcopy(
        [
            item
            for item in prototype["initial"]["results"]
            if item["decision"] in {"report_input", "report_source"}
        ]
    )
    for item in records:
        item["id"] = "report-reference-" + item["decision"]
        if item["decision"] == "report_input":
            item["output"]["requestId"] = "report-reference-request"
    required = [
        f"추세 기간: {_month_offset(profile['month'], -5)}~{profile['month']}",
        "서로 다른 상세 뷰 3개, 검증된 설명과 퀵 인사이트 작성",
    ]
    if count == 0:
        required.append(
            "이번 실행은 활동 상세 자료의 설명 가능성을 확인한다. "
            "활동 자료가 없으면 다른 점수 자료로 대체하지 않는다."
        )
    elif count < 3:
        required.append(
            "이번 실행은 월별 행동 점수"
            + ("와 행동 지표별 기여도" if count == 2 else "")
            + "로 설명 가능한 범위에 한정하며 다른 자료를 추가하지 않는다."
        )
    return {
        "request": {
            "goal": f"{profile['month']} {profile['code']} 행정동 분석 보고서 생성",
            "constraints": {"required": required},
        },
        "event": "analysis_pipeline",
        "messages": [],
        "results": records,
        "response": None,
    }


def _facts(state, profile):
    available = accepted_outputs(state)
    selected = approved_report_selection(state)
    return {
        "region": profile["code"],
        "month": profile["month"],
        "source_references": {
            identity: deepcopy(output["data"]["reference"])
            for identity, output in available.items()
            if "data" in output
        },
        "approved_views": deepcopy(selected["output"]["views"]) if selected else [],
        "approved_descriptions": {
            item["id"]: {
                "view_key": item["action"]["arguments"]["view_key"],
                "content": item["output"]["content"],
            }
            for item in state["results"]
            if item["decision"] == "report_draft"
            and item["id"] in available
            and item["action"]["arguments"]["view_key"] is not None
        },
        "limitations": LIMIT,
    }


def _template(prototype, state, profile, node, role, condition, *, output=None):
    """검사 목록은 현행 생성기를 재사용하고 근거 ID는 현재 State에서만 구성한다."""
    call = (
        "Selection"
        if node == "act"
        else "Decision"
        if node == "decide"
        else "ReportSelection"
        if role == SELECTION
        else "ReportText"
    )
    assessment = _expectations(node, role, condition, call=call)
    for reference in assessment["reference"].values():
        reference["evidence_basis"] = _facts(state, profile)
    items = assessment["expected"]["items"]
    if node == "decide":
        for item in items:
            if item["check"] == "N03-O.3":
                item.update(path="/next", value=output["next"])
    elif node == "act":
        arguments = json.loads(output["arguments_json"])
        for item in items:
            if item["check"] == "N02-O.1":
                item.update(path="/name", value=output["name"])
            if item["check"] not in {"N02-O.3", "N02-B.2", "N-B.1"}:
                continue
            item.pop("applicable", None)
            item.pop("reason", None)
            if output["name"] == "none":
                item.update(
                    applicable=False,
                    reason=(
                        "추가 호출이 필요하지 않거나 허용 범위에서 보완할 수 없어 "
                        "호출·자료 참조를 선택하지 않는다."
                    ),
                )
            elif item["check"] != "N02-O.3":
                item.update(path="/name", value=output["name"])
        # 경로 생성 응답의 정렬·필터 순서·출력 열 이름을 품질 정답으로 고정하지 않는다.
        # 이번 단계의 자료원 또는 이미 확보한 입력 ID만 독립 필수 조건으로 대조한다.
        original = next(item for item in items if item["check"] == "N02-O.3")
        if arguments:
            items.remove(original)
            keys = (
                ("target",) if output["name"] == "query_data" else ("input_result_id",)
            )
            for key in keys:
                items.append(
                    {
                        **original,
                        "id": "N02-O.3-" + key,
                        "path": "/arguments_json/" + key,
                        "value": deepcopy(arguments[key]),
                        "match": "equal",
                    }
                )
    return {
        "purpose": condition,
        "assessment": assessment,
        "providers": [REGION, CONTRIBUTION, GRID, FLOW],
        "tags": [tag for tag in prototype.get("tags", []) if tag.startswith("covers:")],
    }


def _quick_insight(profile, descriptions, keys):
    """고정 초안은 승인 설명에 이미 포함한 관측과 한계만 요약한다."""
    direction = (
        "증가"
        if profile["current"]["bh_score"] > profile["previous"]["bh_score"]
        else "감소"
        if profile["current"]["bh_score"] < profile["previous"]["bh_score"]
        else "유지"
    )
    lines = [f"현재 월 행동 이상 점수는 전월 대비 {direction}했다."]
    if "EmbedDetailV02" in keys:
        lines.append(descriptions["EmbedDetailV02"].split(". ", 1)[0] + ".")
    if "EmbedDetailV08" in keys:
        lines.append(
            "조회된 격자 점수는 지역 안의 행동 이상 점수 공간 분포를 보여준다."
        )
    if len(lines) < 3:
        lines.append("행동 이상 점수는 실제 활동량이나 개인의 고립 상태가 아니다.")
        lines.append("미공급 월과 도시 중앙 범위는 비교할 수 없다.")
    else:
        lines.append(
            "행동 점수는 실제 활동량이나 개인 고립 상태가 아니며 "
            "미공급 월과 도시 중앙 범위는 비교할 수 없다."
        )
    return "\n".join(lines)


async def build_report_paths(snapshot, bundle, recorder) -> None:
    """8개 완전 경로를 기록한다. 기존 부분 사례와 프로덕션 코드는 수정하지 않는다."""
    by_id = {case["id"]: case for case in bundle["cases"]}
    base = by_id["report-select-three-compose"]
    profile = _profile(snapshot)
    captured = [
        deepcopy(item)
        for item in base["initial"]["results"]
        if item["decision"] == "call" and item["outcome"] == "success"
    ]
    views = _views(captured, KEYS)
    descriptions = _descriptions(profile, captured)

    async def step(state, node, role, outputs, condition, template_id):
        template = _template(
            by_id[template_id],
            state,
            profile,
            node,
            role,
            condition,
            output=outputs[0] if outputs else None,
        )
        return await recorder.step(
            node, role, state, outputs, template=template, label=condition
        )

    async def decide(state, role, target, reason, template_id):
        return await step(
            state,
            "decide",
            role,
            [{"next": target, "reason": reason}],
            reason,
            template_id,
        )

    async def retrieve(state, records, identities):
        for index, source in enumerate(records):
            arguments = _replace(source["action"]["arguments"], identities)
            name = source["action"]["name"]
            reason = (
                "현재 보고서 범위에 필요한 자료를 조회한다."
                if name == "query_data"
                else "확보한 같은 동의 두 달 자료로 차이를 계산한다."
            )
            previous = len(state["results"])
            state = await step(
                state,
                "act",
                SELECTION,
                [
                    {
                        "name": name,
                        "arguments_json": json.dumps(arguments, ensure_ascii=False),
                        "reason": reason,
                    }
                ],
                reason,
                "report-selection-act-query-act"
                if name == "query_data"
                else "report-description-act-process-act",
            )
            called = [
                item
                for item in state["results"][previous:]
                if item["decision"] == "call" and item["outcome"] == "success"
            ]
            if len(called) != 1:
                raise AssertionError("Expected one successful actual report tool call")
            identities[source["id"]] = called[0]["id"]
            last = index == len(records) - 1
            state = await decide(
                state,
                SELECTION,
                "compose" if last else "act",
                "확보한 자료의 범위에서 선정문을 작성하고 검토한다."
                if last
                else "선정할 표현 범위에 필요한 자료 확보와 가공이 남아 있다.",
                "report-select-three-decide",
            )
        return state

    async def start_writing(state, role, template_id, *, available=True):
        state = recorder.report_stage(state, role)
        reason = (
            "앞 단계의 검증된 결과가 있어 추가 조회 없이 자기 산출물을 작성한다."
            if available
            else "승인된 작성 대상이 없고 보완할 수 없어 미완성으로 반환한다."
        )
        state = await step(
            state,
            "act",
            role,
            [{"name": "none", "arguments_json": "{}", "reason": reason}],
            reason,
            "report-insight-act-none-act",
        )
        return await decide(state, role, "compose", reason, template_id)

    paths = [
        ("three", 3, "서로 다른 세 뷰의 보고서 완성", None),
        ("one", 1, "한 뷰의 근거로 보고서 부분 완성", None),
        ("two", 2, "두 뷰의 근거로 보고서 부분 완성", None),
        ("selection-rewrite", 3, "선정 수치 결함을 기존 근거로 수정", SELECTION),
        ("description-rewrite", 3, "설명 수치 결함을 기존 근거로 수정", DESCRIPTION),
        ("additional-query", 3, "선정 검토 후 기여도 근거를 추가 조회", "query"),
        ("no-evidence", 0, "정상 조회 0건으로 보고서 미완성 종료", None),
        ("insight-rewrite", 3, "중복 인사이트를 승인 설명으로 수정", INSIGHT),
    ]
    for variant, count, title, fault in paths:
        recorder.begin(
            "report-path-" + variant,
            title,
            "analysis_pipeline",
            "report",
            axes={"selected_view_count": count, "current_event": fault or "normal"},
            source_groups=[
                "report-select-three"
                if count == 3
                else f"report-select-{count}"
                if count
                else "report-select-no-evidence",
                "report-description-" + str(count)
                if count
                else "report-insight-no-approved",
                "report-insight-approved" if count else "report-insight-no-approved",
            ],
        )
        recorder.current["history_contract"] = (
            "고정 모델 응답과 실제 도구로 만든 기준 이력이며 "
            "실제 업무 모델 결과가 아니다. "
            "품질 정답은 assessment에 있고 결함 응답은 경로를 만드는 사건이다."
        )
        recorder.current["events"] = []
        state = recorder.initial_state(_initial(base, profile, count=count))
        state = recorder.report_stage(state, SELECTION)
        identities = {}
        allowed_prefixes = (
            ("report-evidence-flow",)
            if count == 0
            else ("report-evidence-region",)
            if count == 1
            else ("report-evidence-region", "report-evidence-contribution")
            if count == 2
            else (
                "report-evidence-region",
                "report-evidence-contribution",
                "report-evidence-grid",
            )
        )
        queries = [item for item in captured if item["id"].startswith(allowed_prefixes)]
        delayed = []
        if fault == "query":
            delayed = [item for item in queries if "contribution" in item["id"]]
            queries = [item for item in queries if "contribution" not in item["id"]]
        state = await retrieve(state, queries, identities)
        chosen = _replace(views[:count], identities)
        selection_condition = (
            "현재 확보한 근거로 입증할 수 있는 서로 다른 뷰만 선정하고 "
            "설명 범위·제외 비교를 명시한다. 작성 내용의 실제 결함은 검토에서 지적한다."
        )
        if fault in {SELECTION, "query"}:
            bad = deepcopy(chosen)
            if fault == SELECTION:
                bad[0]["reason"] += " 현재 점수는 9999점이다."
                review_reason = (
                    "9999점은 원자료에 없으므로 기존 근거의 실제 수치로 수정한다."
                )
            else:
                bad[1]["evidence_ids"] = [identities["report-evidence-region"]]
                bad[1]["reason"] = "행동 기여도는 지역 분석 점수만으로 설명한다."
                review_reason = (
                    "V02의 행동 기여도 자료가 아직 없어 해당 근거를 조회해야 한다."
                )
            recorder.current["events"].append(
                {"stage": SELECTION, "defect": fault, "review": review_reason}
            )
            state = await step(
                state,
                "compose",
                SELECTION,
                [{"views": bad}, {"accepted": False, "reason": review_reason}],
                selection_condition,
                "report-select-three-compose",
            )
            state = await decide(
                state,
                SELECTION,
                "act" if delayed else "compose",
                review_reason,
                "report-selection-review-needs-query-decide"
                if delayed
                else "report-rewrite-selection-decide",
            )
            if delayed:
                state = await retrieve(state, delayed, identities)
                chosen = _replace(views[:count], identities)
        state = await step(
            state,
            "compose",
            SELECTION,
            [{"views": chosen}, APPROVED],
            selection_condition,
            "report-select-three-compose"
            if count == 3
            else f"report-select-{count}-compose"
            if count
            else "report-select-no-evidence-compose",
        )
        state = await start_writing(
            state,
            DESCRIPTION,
            f"report-description-{count}-decide"
            if count
            else "report-insight-no-approved-decide",
            available=bool(count),
        )
        description_condition = (
            "승인된 선정의 뷰와 설명 범위를 유지하며 각 뷰를 한 단락 최대 세 문장으로 "
            "설명하고 검토한다. 수치·의미·출처·한계를 왜곡하지 않는다."
        )
        if fault == DESCRIPTION:
            reason = (
                "9999점은 원자료에 없다. 기존 월별 점수 근거로 해당 설명을 수정한다."
            )
            recorder.current["events"].append(
                {"stage": DESCRIPTION, "defect": "numeric", "review": reason}
            )
            state = await step(
                state,
                "compose",
                DESCRIPTION,
                [
                    {"content": "현재 월 행동 이상 점수는 9999점이다."},
                    {"accepted": False, "reason": reason},
                ],
                description_condition,
                "report-description-3-compose",
            )
            state = await decide(
                state,
                DESCRIPTION,
                "compose",
                reason,
                "report-rewrite-description-decide",
            )
        outputs = [
            output
            for key in KEYS[:count]
            for output in ({"content": descriptions[key]}, APPROVED)
        ]
        state = await step(
            state,
            "compose",
            DESCRIPTION,
            outputs,
            description_condition
            if count
            else "승인된 선정이 없어 설명을 미완성으로 반환한다.",
            f"report-description-{count}-compose"
            if count
            else "report-description-1-compose",
        )
        state = await start_writing(
            state, INSIGHT, "report-insight-approved-decide", available=bool(count)
        )
        insight_condition = (
            "검토를 통과한 설명의 서로 다른 관측과 한계를 세 문장 또는 네 문장으로 "
            "요약한다. 새로운 수치·계산·원인·승인 밖 주장을 추가하지 않는다."
        )
        if fault == INSIGHT:
            reason = (
                "세 문장이 같은 뜻을 반복한다. 승인 설명의 서로 다른 핵심을 보존한다."
            )
            recorder.current["events"].append(
                {"stage": INSIGHT, "defect": "duplicate", "review": reason}
            )
            state = await step(
                state,
                "compose",
                INSIGHT,
                [
                    {
                        "content": (
                            "점수는 활동량이 아니다.\n점수는 실제 활동량과 다르다.\n"
                            "점수로 활동량을 알 수 없다."
                        )
                    },
                    {"accepted": False, "reason": reason},
                ],
                insight_condition,
                "report-insight-approved-compose",
            )
            state = await decide(
                state, INSIGHT, "compose", reason, "report-rewrite-insight-decide"
            )
        state = await step(
            state,
            "compose",
            INSIGHT,
            [{"content": _quick_insight(profile, descriptions, KEYS[:count])}, APPROVED]
            if count
            else [],
            insight_condition
            if count
            else "승인된 설명이 없어 인사이트를 미완성으로 반환한다.",
            "report-insight-approved-compose",
        )
        state = recorder.publish_report(state)
        recorder.end(state, terminal=state["execution"]["status"])
