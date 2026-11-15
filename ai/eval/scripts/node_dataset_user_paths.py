"""Complete user-request paths through the real nodes with authored model replies.

Source rows come from the immutable snapshot. The recorder owns State execution,
call/return boundaries and shared node identities; this module supplies scenarios
and model responses, never a replacement graph or node implementation.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from decimal import Decimal
from typing import Any, Protocol

from eval.scripts.node_dataset_users import (
    FLOW,
    LIMIT,
    REGION,
    _assessment,
    numeric_pattern,
)
from src.state import State


class Recorder(Protocol):
    def begin(
        self, identity, title, event, family, axes=None, source_groups=None
    ) -> Any: ...

    def initial_state(self, initial: dict) -> State: ...

    async def step(
        self,
        node: str,
        role: str,
        state: State,
        outputs: list[dict],
        template: dict | None = None,
        label: str = "",
        frame: str = "root",
        child_plan: Callable[[str, State], Awaitable[State]] | None = None,
        provider_failures: dict | None = None,
    ) -> State: ...

    def end(self, state: State, terminal: str = "completed") -> Any: ...


def _last_call(state: State, name: str) -> dict:
    return next(
        item
        for item in reversed(state["results"])
        if item["decision"] == "call" and item["action"]["name"] == name
    )


class _UserPaths:
    def __init__(self, snapshot: dict, bundle: dict, recorder: Recorder):
        self.snapshot = snapshot
        self.recorder = recorder
        self.cases = {case["id"]: case for case in bundle["cases"]}
        self.groups = {scenario["id"]: scenario for scenario in bundle["scenarios"]}
        self.selected = snapshot["selection"]
        self.code = self.selected["dong_code"]
        self.name = self.selected["dong_name"]
        self.month = self.selected["month"]
        self.previous = self.selected["previous_month"]

    def source(self, group: str, node: str, role: str | None = None) -> dict:
        return next(
            self.cases[step["case_id"]]
            for step in self.groups[group]["steps"]
            if step["node"] == node and (role is None or step["role"] == role)
        )

    def begin(self, group: str, suffix="", *, title=None, initial=None) -> State:
        source = self.groups[group]
        self.recorder.begin(
            "path-" + group + suffix,
            title or source["title"],
            "user_request",
            source["family"],
            axes=deepcopy(source["axes"]),
            source_groups=[group],
        )
        if initial is None:
            initial = self.cases[source["steps"][0]["case_id"]]["initial"]
        prepared = deepcopy(initial)
        # A current request starts with dialogue and explicit public context.
        # Internal query/process histories are produced by the path itself.
        prepared["results"] = []
        constraints = prepared["request"].setdefault("constraints", {})
        constraints.setdefault("required", []).append(
            "하위 에이전트에 위임할 때 확정한 작업 목표 문구를 그대로 전달한다."
        )
        return self.recorder.initial_state(prepared)

    def template(
        self,
        node: str,
        role: str,
        label: str,
        value: dict,
        source: dict | None = None,
        *,
        reference: dict | None = None,
        numeric: float | None = None,
    ) -> dict:
        item = deepcopy(source or {})
        for key in ("dependencies", "stubs", "provider_failures"):
            item.pop(key, None)
        ref = {
            "required_limitations": [LIMIT],
            "allowed_scope": "이번 요청에서 특정한 지역·기간·지표와 실제 확보 근거",
            "expected_behavior": label,
            **deepcopy(reference or {}),
        }
        exact = {}
        if node == "interpret":
            ref.update(needs_input=value["needs_input"], request=value["request"])
            exact["N01-O.1"] = {
                "path": "/needs_input",
                "value": value["needs_input"],
            }
        elif node == "act":
            arguments = json.loads(value["arguments_json"])
            ref.update(selected_name=value["name"], expected_arguments=arguments)
            exact["N02-O.1"] = {"path": "/name", "value": value["name"]}
            key = {
                "query_data": "target",
                "process_data": "input_result_id",
                "validate_visualization": "parameters",
                "interpretation_agent": "goal",
                "visualization_agent": "goal",
            }.get(value["name"])
            if key is not None:
                exact["N02-O.3"] = {
                    "path": "/arguments_json/" + key,
                    "value": arguments[key],
                    "match": "subset",
                }
            if value["name"].endswith("_agent"):
                ref["argument_comparison"] = (
                    "현재 요청의 필수 조건에 따라 확정한 작업 목표 문구를 "
                    "그대로 전달한다."
                )
            source_ref = (source or {}).get("assessment", {}).get("reference", {})
            for check_ref in source_ref.values():
                if isinstance(check_ref, dict) and "allowed_views" in check_ref:
                    ref["allowed_views"] = deepcopy(check_ref["allowed_views"])
            ref["argument_order"] = (
                "필터·정렬·연산의 표현과 순서는 같은 대상·계산 결과를 "
                "보존하는 허용 대안을 의미 기준으로 비교한다."
            )
        elif node == "decide":
            ref.update(next=value["next"], required_reason=value["reason"])
            exact["N03-O.3"] = {"path": "/next", "value": value["next"]}
        elif node == "compose":
            ref["status"] = value["status"]
            exact["N04-O.1"] = {"path": "/status", "value": value["status"]}
        item.update(
            unit="node",
            target=node,
            role=role,
            purpose=label,
            providers=[REGION, FLOW],
            assessment=_assessment(
                node,
                ref,
                exact,
                artifacts=value.get("artifact_ids"),
                numeric=(
                    {
                        "path": "/content",
                        "pattern": numeric_pattern(numeric, magnitude_only=True),
                        "extract": "number",
                        "value": abs(numeric),
                        "tolerance": {"absolute": 0.01, "relative": 0.0},
                    }
                    if numeric is not None
                    else None
                ),
            ),
        )
        return item

    async def step(
        self,
        node,
        role,
        state,
        value,
        label,
        *,
        source=None,
        frame="root",
        reference=None,
        numeric=None,
        child_plan=None,
        provider_failures=None,
    ):
        template = self.template(
            node, role, label, value, source, reference=reference, numeric=numeric
        )
        return await self.recorder.step(
            node,
            role,
            state,
            [value],
            template=template,
            label=label,
            frame=frame,
            child_plan=child_plan,
            provider_failures=provider_failures,
        )

    async def interpret(
        self,
        state,
        goal=None,
        *,
        role="request",
        needs=False,
        source=None,
        frame="root",
    ):
        request = deepcopy(state["request"])
        if goal is not None:
            request["goal"] = goal
        label = (
            "현재 요청·대화에서 목적과 확보한 조건을 보존하고 "
            "부족한 사용자 정보를 구분한다."
        )
        return await self.step(
            "interpret",
            role,
            state,
            {"request": request, "reason": label, "needs_input": needs},
            label,
            source=source,
            frame=frame,
        )

    async def decide(self, state, target, reason, *, role, source=None, frame="root"):
        return await self.step(
            "decide",
            role,
            state,
            {"next": target, "reason": reason},
            reason,
            source=source,
            frame=frame,
        )

    async def act(
        self,
        state,
        name,
        arguments,
        label,
        *,
        role,
        source=None,
        frame="root",
        child_plan=None,
        provider_failures=None,
    ):
        return await self.step(
            "act",
            role,
            state,
            {
                "name": name,
                "arguments_json": json.dumps(arguments, ensure_ascii=False),
                "reason": label,
            },
            label,
            source=source,
            frame=frame,
            child_plan=child_plan,
            provider_failures=provider_failures,
        )

    async def compose(
        self,
        state,
        content,
        *,
        role,
        status="completed",
        artifacts=None,
        source=None,
        frame="root",
        reference=None,
        numeric=None,
    ):
        label = "유효 근거의 수치·의미·출처·한계와 미해결 범위를 보존해 응답한다."
        return await self.step(
            "compose",
            role,
            state,
            {
                "content": content,
                "artifact_ids": artifacts or [],
                "status": status,
                "reason": label,
            },
            label,
            source=source,
            frame=frame,
            reference=reference,
            numeric=numeric,
        )

    def query_arguments(self, month, code=None, target=REGION):
        return {
            "target": target,
            "filters": [
                {"field": "period_start", "operator": "eq", "value": month + "-01"},
                {"field": "adm_cd10", "operator": "eq", "value": code or self.code},
            ],
        }

    async def score_child(
        self,
        role,
        state,
        *,
        previous=None,
        month=None,
        fail=False,
        activity=False,
        explain_chart=False,
    ):
        frame = "child-interpretation"
        previous, month = previous or self.previous, month or self.month
        state = await self.interpret(
            state,
            role=role,
            source=self.source("U1-score-change", "interpret", "interpretation"),
            frame=frame,
        )
        state = await self.act(
            state,
            "query_data",
            self.query_arguments(month),
            "요청한 동의 현재 월 행동 이상 점수를 조회한다.",
            role=role,
            source=self.source("U1-score-change", "act", "interpretation"),
            frame=frame,
            provider_failures={REGION: "PermissionError"} if fail else None,
        )
        current = _last_call(state, "query_data")
        if fail:
            assert current["outcome"] == "failure"
            state = await self.decide(
                state,
                "compose",
                "자료원 접근이 거부되어 점수 근거를 확보하지 못했고 "
                "다른 공급 경로가 없다.",
                role=role,
                frame=frame,
            )
            return await self.compose(
                state,
                "자료원 public.region_result 접근이 거부되어 요청한 점수 비교를 "
                "제공하지 못했습니다. 정상 조회의 0건과 다르며 "
                "실제 활동량·개인 상태도 확인하지 못했습니다.",
                role=role,
                status="failed",
                frame=frame,
                reference={
                    "required_source": "public[.]region_result",
                    "required_limitations": [
                        "자료원 접근 실패로 점수 비교 근거를 확보하지 못했다."
                    ],
                },
            )
        state = await self.decide(
            state,
            "act",
            "현재 월 점수만 확보했고 전월 점수와 차이 계산이 남아 있다.",
            role=role,
            source=self.source("U1-score-change", "decide", "interpretation"),
            frame=frame,
        )
        state = await self.act(
            state,
            "query_data",
            self.query_arguments(previous),
            "이미 확보한 현재 월을 반복 조회하지 않고 비교할 전월을 조회한다.",
            role=role,
            source=self.source("U1-score-change", "act", "interpretation"),
            frame=frame,
        )
        before = _last_call(state, "query_data")
        state = await self.decide(
            state,
            "act",
            "두 달 원자료를 확보했으며 차이를 계산한다.",
            role=role,
            frame=frame,
        )
        state = await self.act(
            state,
            "process_data",
            {
                "input_result_id": current["id"],
                "operations": [
                    {
                        "operation": "join",
                        "right_result_id": before["id"],
                        "keys": ["adm_cd10"],
                        "how": "inner",
                        "fields": {"bh_score": "previous_bh_score"},
                    },
                    {
                        "operation": "calculate",
                        "method": "difference",
                        "before": "previous_bh_score",
                        "after": "bh_score",
                        "output": "bh_change",
                    },
                ],
                "decimals": 2,
            },
            "같은 행정동의 두 달 점수를 결합하고 차이를 계산한다.",
            role=role,
            source=self.cases["U1-score-change.08.act"],
            frame=frame,
        )
        row = _last_call(state, "process_data")["output"]["data"]["rows"][0]
        independent = float(
            Decimal(str(current["output"]["data"]["rows"][0]["bh_score"]))
            - Decimal(str(before["output"]["data"]["rows"][0]["bh_score"]))
        )
        assert row["bh_change"] == independent
        if activity:
            state = await self.decide(
                state,
                "act",
                "점수 비교는 확보했고 함께 요청한 활동량 자료가 남아 있다.",
                role=role,
                frame=frame,
            )
            state = await self.act(
                state,
                "query_data",
                self.query_arguments(month, target=FLOW),
                "요청한 활동량 자료를 별도 자료원에서 조회한다.",
                role=role,
                frame=frame,
                provider_failures={FLOW: "PermissionError"},
            )
            assert _last_call(state, "query_data")["outcome"] == "failure"
        if explain_chart:
            state = await self.decide(
                state,
                "act",
                "설명 근거는 확보했고 기존 차트 설정을 바꿀 요청은 없다.",
                role=role,
                frame=frame,
            )
            state = await self.act(
                state,
                "none",
                {},
                "확보한 설명 근거를 사용하며 "
                "기존 차트를 재검증하거나 새로 만들지 않는다.",
                role=role,
                source=self.source("U3-explain-chart", "act"),
                frame=frame,
            )
        state = await self.decide(
            state,
            "compose",
            "요청한 점수와 차이가 확보되어 제공 범위와 한계를 설명한다.",
            role=role,
            frame=frame,
        )
        content = (
            f"{self.name}의 {previous} 행동 이상 점수는 {row['previous_bh_score']}, "
            f"{month}는 {row['bh_score']}이며 차이는 {row['bh_change']}점입니다. "
            f"출처 public.region_result. {LIMIT}"
        )
        if explain_chart:
            content += (
                " 기존 Tableau 지도는 등록된 지역·기간의 행동 이상 점수를 공간적으로 "
                "보여줍니다. 표시 조건은 변경하지 않았으며 "
                "실제 화면 표시 성공은 확인하지 않았습니다."
            )
        if activity:
            content += " 활동량은 analysis.flow_detail 접근 거부로 제공하지 못했습니다."
        return await self.compose(
            state,
            content,
            role=role,
            status="partial" if activity else "completed",
            source=self.source(
                "U1-partial" if activity else "U1-score-change", "compose"
            ),
            frame=frame,
            reference={
                "required_source": "public[.]region_result",
                "observations": {
                    "before": row["previous_bh_score"],
                    "after": row["bh_score"],
                    "difference": independent,
                },
                "target": {"dong_code": self.code, "months": [previous, month]},
                "independent_calculation": (
                    f"{row['bh_score']} - {row['previous_bh_score']} = {independent}"
                ),
                "source_reference": deepcopy(
                    self.snapshot["datasets"][REGION]["reference"]
                ),
            },
            numeric=independent,
        )

    async def delegate(
        self,
        state,
        child_role,
        plan,
        *,
        compose_source=None,
        previous=False,
        numeric_field=None,
    ):
        state = await self.act(
            state,
            child_role + "_agent",
            {"goal": state["request"]["goal"]},
            "해석 또는 시각화 전문 작업에 확인된 목표·조건·대화를 전달한다.",
            role="request",
            source=self.source("U1-delegate-" + child_role, "act"),
            child_plan=plan,
        )
        child = _last_call(state, child_role + "_agent")
        output = child["output"]
        assert output.get("response") is not None, output
        status = output["execution"]["status"]
        state = await self.decide(
            state,
            "compose",
            "하위 반환의 제공 범위·미해결 사항을 확인하고 최종 응답으로 통합한다.",
            role="request",
            source=self.source("U1-score-change", "decide", "request"),
        )
        artifacts = (
            ["previous"]
            if previous
            else ([child["id"]] if output["response"]["artifacts"] else [])
        )
        numeric = next(
            (
                row[numeric_field]
                for item in reversed(output["results"])
                if item["decision"] == "call" and item["outcome"] == "success"
                for row in (item.get("output") or {}).get("data", {}).get("rows", [])
                if numeric_field in row
            ),
            None,
        )
        if child_role == "visualization":
            limitations = [
                "등록된 표시 설정 검사이며 자료 존재·최신성·화면 표시 확인은 아니다."
            ]
        elif numeric_field == "bg_score":
            limitations = [
                "지역 수준의 점수이며 개인 상태나 원인을 확인한 결과는 아니다."
            ]
        elif numeric is not None:
            limitations = [LIMIT]
        else:
            limitations = ["자료 미확보 사유를 밝히고 관측값을 추정하지 않는다."]
        return await self.compose(
            state,
            output["response"]["content"],
            role="request",
            status=status,
            artifacts=artifacts,
            source=compose_source
            or self.source("U1-score-change", "compose", "request"),
            reference={
                "child_transfer": True,
                "child_content": output["response"]["content"],
                "required_limitations": limitations,
                "observations": {numeric_field: numeric} if numeric is not None else {},
                "required_source": "Tableau"
                if child_role == "visualization"
                else "public[.]region_result|analysis[.]flow_detail",
            },
            numeric=numeric,
        )

    async def score_path(
        self,
        group,
        *,
        suffix="",
        fail=False,
        activity=False,
        previous=None,
        month=None,
        explain_chart=False,
    ):
        state = self.begin(group, suffix)
        if explain_chart:
            source = self.source(group, "compose")
            state["response"] = deepcopy(source["initial"]["response"])
        resolved = (
            f"{self.name}의 {previous or self.previous}과 "
            f"{month or self.month} 행동 이상 점수 및 "
            "전월 대비 점수 차이를 설명해줘."
        )
        if group == "U3-followup":
            resolved += " 이전 답변의 점수 차이가 의미하는 범위와 한계를 설명한다."
        if activity:
            resolved += " 시간대별 활동량도 설명해줘."
        if explain_chart:
            resolved += (
                " 대화에 제공된 기존 Tableau 차트의 의미를 설명하고 "
                "표시 조건은 바꾸지 않는다."
            )
        source = next(
            (
                self.cases[s["case_id"]]
                for s in self.groups[group]["steps"]
                if s["node"] == "interpret"
            ),
            self.source("U1-score-change", "interpret", "request"),
        )
        state = await self.interpret(state, resolved, source=source)

        async def child_plan(role, child):
            return await self.score_child(
                role,
                child,
                previous=previous,
                month=month,
                fail=fail,
                activity=activity,
                explain_chart=explain_chart,
            )

        state = await self.delegate(
            state,
            "interpretation",
            child_plan,
            previous=explain_chart,
            numeric_field="bh_change",
        )
        self.recorder.end(state, terminal=state["execution"]["status"])

    async def question_path(self, group):
        state = self.begin(group)
        enough_region = group == "U6-clarification"
        goal = (
            f"{self.name}의 기준월과 전월 행동 이상 점수 비교"
            if enough_region
            else state["request"]["goal"]
        )
        state = await self.interpret(
            state, goal, needs=True, source=self.source(group, "interpret")
        )
        state = await self.decide(
            state,
            "ask",
            "확보한 조건을 유지하고 사용자만 정할 필수 정보를 요청한다.",
            role="request",
            source=self.source(group, "decide"),
        )
        content = (
            f"{self.name}의 몇 년 몇 월을 기준으로 전월과 비교할까요?"
            if enough_region
            else "어느 지역의 몇 년 몇 월을 기준으로 전월과 비교할까요?"
        )
        reference = {
            "known_information": [self.name] if enough_region else [],
            "missing_information": ["기준 연월"]
            if enough_region
            else ["대상 지역", "기준 연월"],
            "do_not_ask": ["대상 지역"] if enough_region else ["DB 값", "도구명"],
        }
        state = await self.step(
            "ask",
            "request",
            state,
            {"content": content, "reason": "필수 사용자 정보가 부족하다."},
            "확보한 정보를 다시 묻지 않고 부족한 대상·기간만 구체적으로 질문한다.",
            source=self.source(group, "ask"),
            reference=reference,
        )
        self.recorder.end(state, terminal="waiting_input")

    async def point_path(self, group):
        state = self.begin(group)
        code, name = (
            self.selected["comparison_dong_code"],
            self.selected["comparison_dong_name"],
        )
        goal = (
            f"{name}의 {self.month} 배경 취약성 점수만 설명한다. "
            "이전 행동 점수 비교 요청은 폐기한다."
        )
        state = await self.interpret(
            state, goal, source=self.source(group, "interpret")
        )

        async def child_plan(role, child):
            frame = "child-interpretation"
            child = await self.interpret(child, role=role, frame=frame)
            child = await self.act(
                child,
                "query_data",
                self.query_arguments(self.month, code),
                "새 요청의 지역·기간에 해당하는 배경 점수를 조회한다.",
                role=role,
                frame=frame,
            )
            row = _last_call(child, "query_data")["output"]["data"]["rows"][0]
            child = await self.decide(
                child,
                "compose",
                "새 요청의 배경 취약성 점수가 확보되었다.",
                role=role,
                frame=frame,
            )
            return await self.compose(
                child,
                f"{name}의 {self.month} 배경 취약성 점수는 {row['bg_score']}입니다. "
                "출처 public.region_result. 지역 수준의 점수이며 "
                "개인 상태나 원인을 확인한 결과는 아닙니다.",
                role=role,
                frame=frame,
                numeric=row["bg_score"],
                reference={
                    "required_source": "public[.]region_result",
                    "required_limitations": [
                        "지역 수준의 점수이며 개인 상태나 원인을 확인한 결과는 아니다."
                    ],
                    "observations": {"bg_score": row["bg_score"]},
                    "target": {"dong_code": code, "month": self.month},
                },
            )

        state = await self.delegate(
            state, "interpretation", child_plan, numeric_field="bg_score"
        )
        self.recorder.end(state)

    async def empty_path(self):
        group = "U1-empty-source"
        state = self.begin(group)
        state = await self.interpret(state)

        async def child_plan(role, child):
            frame = "child-interpretation"
            child = await self.interpret(child, role=role, frame=frame)
            child = await self.act(
                child,
                "query_data",
                self.query_arguments(self.month, target=FLOW),
                "요청한 지역·월의 실제 활동 상세 자료를 조회한다.",
                role=role,
                frame=frame,
            )
            assert _last_call(child, "query_data")["output"]["total"] == 0
            child = await self.decide(
                child,
                "act",
                "정상 조회가 0건이며 같은 조회를 반복할 보완 경로가 없다.",
                role=role,
                frame=frame,
            )
            child = await self.act(
                child,
                "none",
                {},
                "정상 0건 결과를 보존하고 같은 조회를 반복하지 않는다.",
                role=role,
                source=self.source(group, "act"),
                frame=frame,
            )
            child = await self.decide(
                child,
                "compose",
                "공급되는 활동 상세 자료가 없어 제공 불가 사유를 설명한다.",
                role=role,
                source=self.source(group, "decide"),
                frame=frame,
            )
            return await self.compose(
                child,
                f"{self.name}의 {self.month} analysis.flow_detail 조회는 "
                "정상 완료됐지만 자료가 0건입니다. 호출 실패는 아니며 "
                "시간대별 활동량을 설명할 근거가 없습니다. "
                "활동량이나 개인 상태를 추정하지 않습니다.",
                role=role,
                status="failed",
                source=self.source(group, "compose"),
                frame=frame,
                reference={
                    "required_source": "analysis[.]flow_detail",
                    "empty_source": FLOW,
                    "required_limitations": [
                        "정상 조회 0건과 호출 실패를 구분하고 "
                        "실제 활동량을 추정하지 않는다."
                    ],
                },
            )

        state = await self.delegate(state, "interpretation", child_plan)
        self.recorder.end(state, terminal="failed")

    async def chart_path(self, group):
        state = self.begin(group)
        original = self.source(group, "act")
        ref = original["assessment"]["reference"]["N02-O.3"]
        arguments = deepcopy(ref.get("expected_arguments"))
        if not arguments:
            arguments = {
                "view_key": "EmbedDetailMap",
                "parameters": deepcopy(ref["parameters"]),
            }
        previous_response = next(
            (
                self.cases[s["case_id"]]["initial"].get("response")
                for s in self.groups[group]["steps"]
                if self.cases[s["case_id"]]["initial"].get("response")
            ),
            None,
        )
        state["response"] = deepcopy(previous_response)
        goal = (
            state["request"]["goal"]
            + " 적용할 대상과 기간은 다음 표시 설정을 따른다: "
            + json.dumps(arguments, ensure_ascii=False)
        )
        interpret_source = next(
            (
                self.cases[s["case_id"]]
                for s in self.groups[group]["steps"]
                if s["node"] == "interpret"
            ),
            None,
        )
        state = await self.interpret(state, goal, source=interpret_source)

        async def child_plan(role, child):
            frame = "child-visualization"
            child = await self.interpret(child, role=role, frame=frame)
            child = await self.act(
                child,
                "validate_visualization",
                arguments,
                "요청한 목적·대상·기간의 등록된 표시 설정을 검사한다.",
                role=role,
                source=original,
                frame=frame,
            )
            chart = _last_call(child, "validate_visualization")
            assert chart["output"]["valid"] is True
            child = await self.decide(
                child,
                "compose",
                "요청 조건의 시각화 설정이 등록 기준에 적합하다.",
                role=role,
                frame=frame,
            )
            return await self.compose(
                child,
                "요청한 지역·기간의 Tableau 표시 설정을 등록 기준으로 검사했습니다. "
                "자료 존재·최신성·실제 화면 표시는 별도로 확인하지 않았습니다.",
                role=role,
                artifacts=[chart["id"]],
                frame=frame,
                reference={
                    "required_source": "Tableau",
                    "verification_scope": "registered_configuration",
                    "required_limitations": [
                        "등록된 설정 검사이며 자료 존재·최신성·화면 표시 확인은 아니다."
                    ],
                },
            )

        source = next(
            (
                self.cases[s["case_id"]]
                for s in self.groups[group]["steps"]
                if s["node"] == "compose"
            ),
            None,
        )
        state = await self.delegate(
            state, "visualization", child_plan, compose_source=source
        )
        self.recorder.end(state)


async def build_user_paths(snapshot: dict, bundle: dict, recorder: Recorder) -> None:
    """Add 15 complete paths while retaining the original node cases separately."""
    paths = _UserPaths(snapshot, bundle, recorder)
    await paths.score_path("U1-score-change")
    await paths.score_path("U1-score-change", suffix="-query-failure", fail=True)
    await paths.question_path("U1-missing")
    await paths.empty_path()
    await paths.score_path("U1-partial", activity=True)
    await paths.point_path("U2-new-topic")
    await paths.score_path("U3-followup")
    await paths.score_path("U3-explain-chart", explain_chart=True)
    await paths.score_path("U4-change", previous="2025-10", month="2025-11")
    await paths.chart_path("U4-period")
    await paths.chart_path("U4-whole-city")
    await paths.score_path("U5-clarification")
    await paths.question_path("U6-clarification")
    await paths.point_path("U7-new-goal-during-question")
    await paths.chart_path("U1-alternative-view")
