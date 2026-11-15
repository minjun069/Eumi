"""사용자 관련 역할·대화 조건을 보존한 실제 노드 실행 사본."""

# ruff: noqa: E501 -- Authored Korean conversation and evaluation prose.

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal

from reference_evidence import CONTRIBUTION, DEFINITIONS

from eval.scripts.node_dataset_basic_users import _BasicUsers
from eval.scripts.node_dataset_paths import PathRecorder, dump_state
from eval.scripts.node_dataset_user_paths import _last_call
from eval.scripts.node_dataset_users import REGION, _assessment, numeric_pattern

ACTIVITY = "analysis.bh_region_indicator"
PROVIDERS = [REGION, ACTIVITY, CONTRIBUTION, DEFINITIONS]
GAP = "h29_senior_gender_change_gap"
SHARE = "h18_senior_male_share"


def _difference(after, before):
    return float(Decimal(str(after)) - Decimal(str(before)))


class QualityUsers(_BasicUsers):
    def task(self, role, condition):
        task = super().task(role, condition)
        kind = task["kind"]
        goals = {
            "comparison": f"{self.name}의 {self.month} 행동 이상 신호가 지난달보다 어떤지 설명해주세요.",
            "current_score": f"{self.name}의 {self.month} 행동 이상 점수만 알려주세요.",
            "rewrite": "이전 설명을 같은 뜻의 쉬운 두 문장으로 줄여주세요.",
            "detail_map": f"{self.name}의 {self.month} 상세 지도를 보여주세요.",
            "city_map": f"{self.selected['city_name']} 전체의 {self.month} 배경 취약성 지도를 보여주세요.",
            "detail_pair": f"{self.name}의 {self.month} 상세 지도와 행동 지표 기여도 차트를 함께 보여주세요.",
        }
        task["goal"] = goals[kind]
        task["required"] = ["같은 뜻의 쉬운 두 문장"] if kind == "rewrite" else []
        if role == "interpretation" and condition == "revision":
            task["goal"] = (
                f"이전 정의 설명에 이어 {self.name}의 {self.month} 행동 이상 신호가 "
                "지난달보다 어떤지 설명해주세요."
            )
        task["interpret_reason"] = {
            "none": "현재 질문과 선택 화면의 지역·월을 합쳐 요청 목적을 정리한다.",
            "new_topic": "이전 질문의 지역·목적을 끌어오지 않고 새 질문과 현재 선택을 반영한다.",
            "revision": (
                "이전 설명의 의미를 유지하는 쉬운 두 문장 재서술이다. 새 분석은 요청하지 않았다."
                if kind == "rewrite"
                else "이전 정의 설명을 유지하며 같은 동의 전월 비교를 추가한다."
                if role == "interpretation"
                else "이전 지도의 지역과 목적은 유지하고 요청한 기준 월만 바꾼다."
            ),
            "clarification_complete": "이전 질문의 목적과 방금 알려준 지역·월을 결합한다. 이미 받은 조건을 다시 묻지 않는다.",
        }[condition]
        task["rationale"] = {
            "user_requirement": task["goal"],
            "available_evidence": [
                "실제 이전 대화",
                "현재 질문과 선택 화면의 지역·기준 월",
            ],
            "missing_evidence": (
                []
                if kind == "rewrite"
                else ["이번 요청 범위의 자료 조회·가공 결과"]
                if kind in {"comparison", "current_score"}
                else ["이번 지역·월과 목적에 맞는 등록 뷰의 설정 검사 결과"]
            ),
            "necessary_work": (
                ["이전 정의·한계를 쉬운 두 문장으로 재서술"]
                if kind == "rewrite"
                else ["현재 월 점수만 조회해 요청한 값을 간단히 전달"]
                if kind == "current_score"
                else [
                    "월별 점수·실제 활동·성별 지표를 조회",
                    "같은 지역·기간의 변화 계산",
                    "최근 흐름과 조건별 의미 설명",
                ]
                if kind == "comparison"
                else [
                    "목적에 맞는 등록 뷰 선택",
                    "지역·월 표시 설정 검사",
                    "요청한 모든 산출물 전달",
                ]
            ),
            "excluded_work": (
                ["조회·가공·위임", "새 수치·해석 추가"]
                if kind == "rewrite"
                else [
                    "전월 조회·변화 계산·추세 설명",
                    "기여도·성별 추가 분석",
                    "개인 진단",
                ]
                if kind == "current_score"
                else [
                    "성별 절대 활동 감소나 인과의 확정",
                    "기존 이용자 재참여 관리로 업무를 바꾸기",
                ]
                if kind == "comparison"
                else [
                    "지도 수치나 고립 지역 발명",
                    "설정 검사만으로 실제 화면·최신성 확인을 주장",
                ]
            ),
        }
        return task

    def initial(self, role, condition, task):
        kind = task["kind"]
        selected = {
            "type": "system",
            "content": f"현재 선택 지역: {self.selected['city_name']} {self.name}"
            f"(행정동 코드 {self.code}). 화면 기준 월: {self.month}.",
        }
        prior = []
        if condition == "none":
            latest = (
                f"{self.name}의 행동 이상 신호가 지난달보다 달라졌나요?"
                if role == "interpretation"
                else f"{self.name} 지도를 보여주세요."
            )
        elif condition == "new_topic":
            prior = [
                {
                    "type": "human",
                    "content": f"{self.selected['comparison_dong_name']}의 배경 취약성 점수는 무슨 뜻인가요?",
                },
                {
                    "type": "ai",
                    "content": "지역의 배경 여건을 나타내는 점수입니다. 개인의 고립 상태를 확인한 값은 아닙니다.",
                },
            ]
            latest = (
                f"이번에는 {self.name}의 이번 달 행동 이상 점수만 알려주세요."
                if kind == "current_score"
                else f"이번에는 {self.selected['city_name']} 전체 배경 취약성 지도를 보여주세요."
                if kind == "city_map"
                else f"이번에는 {self.name} 지도를 보여주세요."
            )
        elif condition == "revision":
            visual = role == "visualization"
            prior = [
                {
                    "type": "human",
                    "content": f"{self.name}의 {self.previous} 지도를 보여주세요."
                    if visual
                    else f"{self.name}의 행동 이상 점수는 무슨 뜻인가요?",
                },
                {
                    "type": "ai",
                    "content": f"{self.name}의 {self.previous} 상세 지도 표시 설정을 준비했습니다. 화면 표시 여부는 별도 확인이 필요합니다."
                    if visual
                    else "행동 이상 점수는 학습 기준 행동과의 차이입니다. 실제 활동량이나 개인의 고립 상태를 뜻하지 않습니다.",
                },
            ]
            latest = (
                f"같은 동으로 {self.month} 지도를 보여주세요."
                if visual
                else "그럼 이번 달은 지난달보다 어떤지도 설명해주세요."
                if role == "interpretation"
                else "좀 더 쉽게 두 문장으로 줄여주세요."
            )
        else:
            assert condition == "clarification_complete"
            prior = [
                {
                    "type": "human",
                    "content": "상세 지도와 행동 지표 기여도 차트를 함께 보여주세요."
                    if role == "visualization"
                    else "지난달과 비교하면 어떤가요?",
                },
                {"type": "ai", "content": "어느 지역의 몇 년 몇 월을 기준으로 할까요?"},
            ]
            latest = f"{self.name}, 2025년 12월이요."
        return {
            "event": "user_request",
            "request": {
                "goal": latest,
                "constraints": {
                    "required": task["required"],
                    "preferred": [],
                    "excluded": [],
                },
            },
            "messages": prior + [selected, {"type": "human", "content": latest}],
            "results": [],
            "response": None,
        }

    def analysis_reference(self, comparison):
        periods = (
            [f"2025-{month:02d}-01" for month in range(7, 13)]
            if comparison
            else [self.month + "-01"]
        )
        sources = {}
        targets = PROVIDERS if comparison else [REGION]
        for target in targets:
            rows = self.snapshot["datasets"][target]["rows"]
            sources[target] = deepcopy(
                [
                    row
                    for row in rows
                    if target == DEFINITIONS
                    or (row["adm_cd10"] == self.code and row["period_start"] in periods)
                ]
            )
        region = {row["period_start"]: row for row in sources[REGION]}
        current = region[self.month + "-01"]
        anchors = {"score_current": current["bh_score"]}
        meanings = [
            "행동 점수와 실제 활동값을 구분해 해석하며, 점수를 활동량·개인 고립 확률로 바꾸지 않는다.",
            "현재 양의 기여도 상위 두 항목인 고령층 성별 변화율 차이와 남성 비중을 정의에 연결한다. 고령층 전체가 똑같이 위축됐다는 결론 대신 성별 구성·변화 차이가 중요한 해석축임을 설명한다.",
        ]
        failures = [
            "수치·정의·주의문만 나열하고 이번 신호의 해석축을 생략",
            "점수나 기여도로 특정 성별의 절대 감소·개인 고립을 확정",
            "기여도를 활동 원값의 방향이나 점수 변화의 가산 원인 분해로 취급",
        ]
        if comparison:
            previous = region[self.previous + "-01"]
            anchors.update(
                score_previous=previous["bh_score"],
                score_difference=_difference(current["bh_score"], previous["bh_score"]),
            )
            meanings.extend(
                [
                    "배경 단계 1 유지·배경 점수 소폭 하락과 행동 점수 재상승을 대비해, 제공된 배경 지표의 전반 악화보다 행동 신호 쪽 변화가 두드러짐을 설명한다.",
                    "9월 높음→10~11월 낮아짐→12월 재상승과 활동의 8월 하락→9월 회복→12월 감소를 반영해 연속 악화로 단정하지 않는다.",
                    "활동 평균의 전월 감소 3.26%를 실제 지역 이용 축소로 읽되 주민 접촉 감소와 통근·방문 변화는 구분한다.",
                    "고령 남성 비중과 상대 변화율 차이를 원지표로 확인한다. 여성 활동 감소라면 생활공간 이용·만남 기회 축소 가능성, 여성 유지·남성 증가라면 남성 지역 이용 확대라는 서로 다른 조건을 보존한다.",
                    "현장 확인 제안을 넣는다면 주거지의 외출·왕래 변화 등 발굴할 지역을 검토하는 정보에 연결한다. 기존 이용자의 재참여 관리로 업무를 바꾸지 않는다.",
                ]
            )
            failures.extend(
                [
                    "단순 최고·상승 설명 뒤 확인하세요로 끝냄",
                    "모든 활동 감소를 주민 외출·관계 약화로 확정",
                    "확인 제안만 있고 조건별 해석이 없음",
                ]
            )
        else:
            meanings = [
                "요청한 동·현재 월의 행동 이상 점수를 정확하게 전달한다. 숫자만 간단히 답해도 충족한다."
            ]
            failures = [
                "지역·월·점수를 다르게 답함",
                "현재 값만 묻는 요청에 전월 차이·추세 또는 성별·기여도 분석을 추가",
                "점수만 정확히 답한 결과를 전문 해석이 없다는 이유로 미달 판정",
            ]
        return {
            **({"required_source": "월별 분석 결과"} if comparison else {}),
            "target": {"dong_code": self.code, "months": periods},
            "source_rows": sources,
            "source_references": {
                target: deepcopy(self.snapshot["datasets"][target]["reference"])
                for target in targets
            },
            "numeric_anchors": anchors,
            "required_meanings": meanings,
            "failure_examples": failures,
            "allowed_variations": (
                "정답 문장·특정 단어·문단 순서를 고정하지 않는다. 같은 관측 관계와 조건의 차이를 보존하는 간결한 표현을 허용한다. 모든 원값이나 기여도 수치를 반복할 필요는 없으며 한계를 주의문으로 일일이 출력할 필요도 없다. 잘못된 주장으로 확장하지 않았는지를 검토한다."
                if comparison
                else "점수만 답하거나 점수에 짧은 뜻·출처를 붙이는 표현을 모두 허용한다. 성별 해석, 기여도 설명, 현장 확인 제안, 추가 출처 문구는 필수 조건이 아니다."
            ),
        }

    async def step(
        self,
        node,
        role,
        state,
        output,
        *,
        frame="root",
        reference=None,
        numeric=None,
        child_plan=None,
    ):
        ref = {
            "expected_behavior": output["reason"],
            "allowed_scope": output.get("request", state["request"])["goal"],
            **deepcopy(reference or {}),
        }
        exact = {}
        if node == "interpret":
            ref.update(
                request=deepcopy(output["request"]),
                comparison="지역·월·목적과 실제 수정 조건을 보존한다. 출처·추가 조사 요구를 사용자의 발화에 보태지 않는다.",
            )
        elif node == "decide":
            ref.update(next=output["next"], required_reason=output["reason"])
            exact["N03-O.3"] = {"path": "/next", "value": output["next"]}
        elif node == "act":
            args = json.loads(output["arguments_json"])
            ref.update(selected_name=output["name"], expected_arguments=args)
            exact["N02-O.1"] = {"path": "/name", "value": output["name"]}
            key = {
                "query_data": "target",
                "process_data": "input_result_id",
                "validate_visualization": "parameters",
            }.get(output["name"])
            if key:
                exact["N02-O.3"] = {
                    "path": "/arguments_json/" + key,
                    "value": args[key],
                    "match": "subset",
                }
            ref["argument_comparison"] = (
                "동일한 지역·기간·계산·표시 목적을 보존하는 인자를 허용한다. 문장 일치를 요구하지 않는다."
            )
            if output["name"] == "validate_visualization":
                ref.update(
                    allowed_views=[args["view_key"]],
                    target={"parameters": args["parameters"]},
                    verification_scope="registered_configuration",
                )
            if output["name"].endswith("_agent"):
                ref.update(
                    rule_evaluation="미판정",
                    semantic_review="하위 목표의 지역·기간·목적 보존을 의미로 검토하며 문자열 일치로 대체하지 않는다.",
                )
        elif node == "compose":
            ref["status"] = output["status"]
            ref.setdefault("failure_examples", ref.get("excluded_claims", []))
            ref.setdefault(
                "allowed_variations",
                "요청한 의미와 범위를 보존하는 자연스러운 표현을 허용한다.",
            )
            exact["N04-O.1"] = {"path": "/status", "value": output["status"]}
        anchors = ref.get("numeric_anchors", {})
        if numeric is not None and not anchors:
            anchors = {"value": numeric}
        first = next(iter(anchors.values()), None)
        assessment = _assessment(
            node,
            ref,
            exact,
            artifacts=output.get("artifact_ids", []),
            numeric={
                "path": "/content",
                "pattern": numeric_pattern(first),
                "extract": "number",
                "value": first,
                "tolerance": {"absolute": 0.005, "relative": 0.0},
            }
            if first is not None
            else None,
        )
        if anchors:
            number = next(
                item
                for item in assessment["expected"]["items"]
                if item["check"] == "N-O.1"
            )
            assessment["expected"]["items"] = [
                item
                for item in assessment["expected"]["items"]
                if item["check"] != "N-O.1"
            ]
            for name, value in anchors.items():
                assessment["expected"]["items"].append(
                    dict(
                        number,
                        id="N-O.1-" + name,
                        pattern=numeric_pattern(value),
                        value=value,
                    )
                )
        if node == "compose":
            for item in assessment["expected"]["items"]:
                if item["check"] in {"N-O.2", "N-O.3", "N-O.4", "N-O.5", "N-O.10"}:
                    item["value"] = (
                        "reference의 required_meanings·failure_examples·allowed_variations에 따라 요청 범위에 맞는 의미와 근거를 검토한다. 특정 문구 일치는 요구하지 않는다."
                    )
        return await self.recorder.step(
            node,
            role,
            state,
            [output],
            frame=frame,
            label=output["reason"],
            child_plan=child_plan,
            template={"providers": PROVIDERS, "assessment": assessment},
        )

    async def work(self, state, name, arguments, reason, frame):
        state = await self.decide(state, "interpretation", "act", reason, frame)
        return await self.act(state, "interpretation", name, arguments, reason, frame)

    async def query(self, state, target, start, frame, reason):
        args = {"target": target, "limit": 1000}
        if target != DEFINITIONS:
            args.update(
                filters=[
                    {"field": "adm_cd10", "operator": "eq", "value": self.code},
                    {"field": "period_start", "operator": "ge", "value": start},
                    {
                        "field": "period_start",
                        "operator": "le",
                        "value": self.month + "-01",
                    },
                ],
                sort=[{"field": "period_start", "descending": False}],
            )
        return await self.work(state, "query_data", args, reason, frame)

    async def process(self, state, input_id, operations, frame, reason):
        return await self.work(
            state,
            "process_data",
            {"input_result_id": input_id, "operations": operations, "decimals": 6},
            reason,
            frame,
        )

    async def interpretation(self, state, task, *, frame="root"):
        comparison = task["kind"] == "comparison"
        state = await self.interpret(state, "interpretation", task, frame)
        state = await self.query(
            state,
            REGION,
            "2025-07-01" if comparison else self.month + "-01",
            frame,
            "질문의 기간에 맞는 배경·행동 점수를 조회해 현재 상태를 설명할 근거를 확보한다.",
        )
        region = _last_call(state, "query_data")
        monthly = {row["period_start"]: row for row in region["output"]["data"]["rows"]}
        current = monthly[self.month + "-01"]
        if not comparison:
            state = await self.decide(
                state,
                "interpretation",
                "compose",
                "요청한 동·현재 월의 점수가 확보됐다. 점수만 묻는 질문이므로 추가 분석 없이 값을 전달한다.",
                frame,
            )
            return await self.step(
                "compose",
                "interpretation",
                state,
                {
                    "content": f"{self.name}의 {self.month} 행동 이상 점수는 {current['bh_score']:.2f}점입니다.",
                    "artifact_ids": [],
                    "status": "completed",
                    "reason": "현재 월 점수만 정확히 반환하며 기여도·성별·전월 분석을 추가하지 않는다.",
                },
                frame=frame,
                reference=self.analysis_reference(False),
            )
        scores = None
        if comparison:
            state = await self.process(
                state,
                region["id"],
                [
                    {
                        "operation": "filter",
                        "conditions": [
                            {
                                "field": "period_start",
                                "operator": "eq",
                                "value": self.previous + "-01",
                            }
                        ],
                    }
                ],
                frame,
                "같은 동의 전월 행을 분리해 배경과 행동의 변화 계산을 준비한다.",
            )
            previous_id = _last_call(state, "process_data")["id"]
            state = await self.process(
                state,
                region["id"],
                [
                    {
                        "operation": "filter",
                        "conditions": [
                            {
                                "field": "period_start",
                                "operator": "eq",
                                "value": self.month + "-01",
                            }
                        ],
                    },
                    {
                        "operation": "join",
                        "right_result_id": previous_id,
                        "keys": ["adm_cd10"],
                        "how": "inner",
                        "fields": {
                            "bh_score": "previous_bh_score",
                            "bg_score": "previous_bg_score",
                        },
                    },
                    {
                        "operation": "calculate",
                        "method": "difference",
                        "before": "previous_bh_score",
                        "after": "bh_score",
                        "output": "bh_change",
                    },
                ],
                frame,
                "두 달을 같은 지역으로 결합하고 행동 점수 차이를 실제 가공 도구로 계산한다.",
            )
            scores = _last_call(state, "process_data")["output"]["data"]["rows"][0]
        state = await self.query(
            state,
            CONTRIBUTION,
            self.month + "-01",
            frame,
            "현재 점수를 설명하는 지표가 무엇인지 기여도 전체를 조회한다.",
        )
        contribution = _last_call(state, "query_data")
        state = await self.query(
            state,
            DEFINITIONS,
            self.month + "-01",
            frame,
            "기여도와 원지표의 뜻을 확인해 부호만으로 성별 활동 감소를 단정하지 않는다.",
        )
        definitions = _last_call(state, "query_data")
        state = await self.process(
            state,
            contribution["id"],
            [
                {
                    "operation": "join",
                    "right_result_id": definitions["id"],
                    "keys": ["indicator_cd"],
                    "how": "inner",
                    "fields": {
                        "label": "indicator_label",
                        "definition": "indicator_definition",
                        "interpretation_limit": "indicator_limit",
                    },
                },
                {
                    "operation": "sort",
                    "by": [{"field": "contribution", "descending": True}],
                },
            ],
            frame,
            "현재 기여도와 정의를 결합해 큰 설명 항목을 의미와 함께 읽는다.",
        )
        ranked = _last_call(state, "process_data")["output"]["data"]["rows"]
        assert [row["indicator_cd"] for row in ranked[:2]] == [GAP, SHARE]
        if comparison:
            state = await self.query(
                state,
                ACTIVITY,
                "2025-07-01",
                frame,
                "점수 변화와 실제 이용 규모를 구분하기 위해 6개월 활동 집계·성별 원지표를 조회한다.",
            )
            activity_record = _last_call(state, "query_data")
            activities = {
                row["period_start"]: row
                for row in activity_record["output"]["data"]["rows"]
            }
            state = await self.process(
                state,
                activity_record["id"],
                [
                    {
                        "operation": "filter",
                        "conditions": [
                            {
                                "field": "period_start",
                                "operator": "eq",
                                "value": self.previous + "-01",
                            }
                        ],
                    }
                ],
                frame,
                "전월 활동 평균과 성별 구성 행을 분리한다.",
            )
            previous_id = _last_call(state, "process_data")["id"]
            state = await self.process(
                state,
                activity_record["id"],
                [
                    {
                        "operation": "filter",
                        "conditions": [
                            {
                                "field": "period_start",
                                "operator": "eq",
                                "value": self.month + "-01",
                            }
                        ],
                    },
                    {
                        "operation": "join",
                        "right_result_id": previous_id,
                        "keys": ["adm_cd10"],
                        "how": "inner",
                        "fields": {
                            "activity_hourly_mean": "previous_activity_mean",
                            SHARE: "previous_male_share",
                        },
                    },
                    {
                        "operation": "calculate",
                        "method": "percent_change",
                        "before": "previous_activity_mean",
                        "after": "activity_hourly_mean",
                        "output": "activity_percent_change",
                    },
                ],
                frame,
                "실제 활동 평균의 전월 변화율을 계산해 점수 상승과 같은 뜻으로 취급하지 않는다.",
            )
            actual = _last_call(state, "process_data")["output"]["data"]["rows"][0]
            decline = abs(actual["activity_percent_change"])
            content = (
                f"{self.name}은 제공된 배경 지표의 전반적인 악화보다 행동 이상 신호가 "
                f"다시 커진 변화가 두드러집니다. 행동 점수는 {scores['previous_bh_score']:.2f}점에서 "
                f"{scores['bh_score']:.2f}점으로 {scores['bh_change']:.2f}점 올랐지만, 배경 점수는 "
                f"{scores['previous_bg_score']:.2f}점에서 {scores['bg_score']:.2f}점으로 조금 낮아졌고 "
                "단계 1을 유지했습니다. 9월에 높아졌다가 10~11월에 낮아진 뒤 다시 오른 "
                "흐름이므로 계속 악화됐다고 보기는 어렵습니다.\n\n"
                f"실제 평균 활동규모도 전월보다 {decline:.2f}% 줄어 {actual['activity_hourly_mean']:.2f}가 "
                f"됐습니다. 다만 8월 {activities['2025-08-01']['activity_hourly_mean']:.2f}에서 "
                f"9월 {activities['2025-09-01']['activity_hourly_mean']:.2f}로 회복한 적이 있어, "
                "지역 이용이 등락하다 최근 다시 줄어든 상황으로 읽을 수 있습니다.\n\n"
                "현재 점수를 크게 설명하는 두 항목은 고령층 성별 변화율 차이와 남성 비중입니다. "
                f"원지표에서 남성의 변화율이 여성보다 {actual[GAP]:.2f}%p 높고 남성 비중도 "
                f"{actual['previous_male_share'] * 100:.2f}%에서 {actual[SHARE] * 100:.2f}%로 높아졌습니다. "
                "여성의 실제 활동이 줄었다면 생활공간 이용·이웃과 마주칠 기회가 좁아졌을 "
                "가능성이 있지만, 여성 활동은 유지되고 남성 활동만 늘었다면 남성의 지역 이용 "
                "확대로 해석해야 합니다.\n\n"
                f"전체 이용이 줄고 고령층 성별 차이도 나타났으므로, {self.name} 주거지의 "
                "11~12월 외출·왕래 변화에 관한 현장 정보를 대조해보세요. 성별 차이가 "
                "실제 생활공간 이용에서도 나타나는지, 통근·단기 방문 수요가 줄어든 "
                "영향인지 구분하면 발굴할 지역을 검토하는 데 도움이 됩니다.\n"
                "자료: 월별 분석 결과, 7~12월 활동 집계, 현재 월 행동 지표 기여도와 지표 정의."
            )
        state = await self.decide(
            state,
            "interpretation",
            "compose",
            "질문 범위의 관측·지표 정의와 비교 근거가 확보됐다. 관측의 의미를 설명하고 확인되지 않은 성별 방향·개인 상태는 구분한다.",
            frame,
        )
        return await self.step(
            "compose",
            "interpretation",
            state,
            {
                "content": content,
                "artifact_ids": [],
                "status": "completed",
                "reason": "현재 값 또는 비교 요청에 맞춰 해석축과 조건의 차이를 근거에 연결한다.",
            },
            frame=frame,
            reference=self.analysis_reference(comparison),
        )

    async def visualization(self, state, task, *, frame="root"):
        state = await self.interpret(state, "visualization", task, frame)
        charts = []
        meanings = {
            "EmbedDetailMap": "선택한 동 안의 공간 분포를 볼 상세 지도를 선택한다. 도시 전체 지도와 구별한다.",
            "Embed01VulnerabilityMap": "요청은 도시 전체의 배경 취약성 분포이므로 읍면동으로 좁히지 않는 도시 지도를 선택한다.",
            "EmbedDetailV02": "지도와 함께 요청한 기여도 차트는 현재 점수를 설명하는 지표를 살펴볼 목적이다. 격자 분포와 기여도 역할을 구분한다.",
        }
        for view in task["views"]:
            state = await self.decide(
                state,
                "visualization",
                "act",
                meanings[view] + " 이번 지역·월 설정의 검사와 산출물이 필요하다.",
                frame,
            )
            state = await self.act(
                state,
                "visualization",
                "validate_visualization",
                {"view_key": view, "parameters": self.view_parameters(view)},
                meanings[view],
                frame,
            )
            result = _last_call(state, "validate_visualization")
            assert result["output"]["valid"] is True
            charts.append(result)
        area = (
            self.selected["city_name"] + " 전체"
            if task["kind"] == "city_map"
            else self.name
        )
        purpose = (
            "배경 취약성 지도"
            if task["kind"] == "city_map"
            else "상세 지도와 행동 지표 기여도 차트"
            if task["kind"] == "detail_pair"
            else "상세 지도"
        )
        usage = (
            "지도는 동 안의 분포를, 기여도 차트는 점수의 설명 항목을 볼 수 있도록 함께 연결했습니다. "
            if task["kind"] == "detail_pair"
            else ""
        )
        content = f"{area}의 {self.month} {purpose}를 준비했습니다. {usage}Tableau 표시 설정 검사를 통과한 산출물이며, 실제 화면 표시와 자료 최신성은 이번 검사에서 확인하지 않았습니다."
        ref = {
            "required_source": "Tableau",
            "tool_transfer": True,
            "verification_scope": "registered_configuration",
            "requested_views": task["views"],
            "configurations": [
                {"view_key": view, "parameters": self.view_parameters(view)}
                for view in task["views"]
            ],
            "required_meanings": [meanings[view] for view in task["views"]]
            + [
                "각 뷰의 지역·월과 모든 유효 산출물을 보존한다. 설정 검사와 화면 표시·자료 최신성을 구분한다."
            ],
            "failure_examples": [
                "확보하지 않은 지도 수치·상위 지역·개인 위험을 서술",
                "도시 전체를 한 동으로 좁힘",
                "두 뷰 요청에 하나만 반환",
                "설정 검사만으로 화면 표시 성공을 단정",
            ],
            "allowed_variations": "뷰 제목·적용 범위와 검사 한계를 보존하는 자연스러운 표현을 허용한다. 수치 분석을 추가하는 것은 전문성의 필수 조건이 아니다.",
        }
        state = await self.decide(
            state,
            "visualization",
            "compose",
            "요청한 모든 뷰의 지역·월 설정 검사와 유효 산출물이 확보됐다. 수치를 해석하거나 미확인 화면 상태를 단정할 필요는 없다.",
            frame,
        )
        return await self.step(
            "compose",
            "visualization",
            state,
            {
                "content": content,
                "artifact_ids": [chart["id"] for chart in charts],
                "status": "completed",
                "reason": "질문에 맞는 모든 시각화와 적용 범위·검사 한계를 전달한다.",
            },
            frame=frame,
            reference=ref,
        )

    async def request(self, state, task):
        if task["kind"] == "rewrite":
            return await self.rewrite(state, "request", task, "root")
        specialist = (
            "visualization" if task["kind"] == "detail_map" else "interpretation"
        )
        state = await self.interpret(state, "request", task, "root")
        state = await self.decide(
            state,
            "request",
            "act",
            "질문의 지역·월·목적은 확인됐고 이를 답할 전문 작업의 근거와 산출물이 아직 없다.",
            "root",
        )

        async def child_plan(child_role, child_state):
            assert child_role == specialist
            return await getattr(self, specialist)(
                child_state, task, frame="child-" + specialist
            )

        state = await self.act(
            state,
            "request",
            specialist + "_agent",
            {"goal": state["request"]["goal"]},
            "확인한 질문의 의미를 해당 전문 에이전트에 전달한다. 사용자가 말하지 않은 출처 형식이나 후속 조사 요구를 덧붙이지 않는다.",
            "root",
            child_plan=child_plan,
            reference={
                "goal_semantics": {
                    "region": {"code": self.code, "name": self.name},
                    "current_month": self.month,
                    "purpose": task["goal"],
                }
            },
        )
        call = _last_call(state, specialist + "_agent")
        child = call["output"]
        assert child["execution"]["status"] == "completed"
        state = await self.decide(
            state,
            "request",
            "compose",
            "하위 반환이 질문의 목적을 충족하고 근거·조건별 의미 또는 요청한 시각화 산출물을 포함한다. 내용을 보존해 전달할 수 있다.",
            "root",
        )
        ref = {
            "child_transfer": True,
            "child_content": child["response"]["content"],
            "required_meanings": [
                "하위의 관측·해석 조건·출처와 요청한 산출물을 보존한다."
            ],
            "failure_examples": [
                "하위에 없는 원인이나 고립 진단을 추가",
                "하위 산출물 누락",
            ],
            "allowed_variations": "하위 의미와 필요한 근거를 보존하는 요약·재배열을 허용한다.",
        }
        if specialist == "interpretation":
            ref.update(self.analysis_reference(True))
        else:
            ref.update(
                required_source="Tableau",
                child_artifacts=deepcopy(child["response"]["artifacts"]),
            )
        final = await self.step(
            "compose",
            "request",
            state,
            {
                "content": child["response"]["content"],
                "artifact_ids": [call["id"]] if specialist == "visualization" else [],
                "status": "completed",
                "reason": "질문에 대한 하위 판단과 근거·범위를 보존해 최종 답변으로 통합한다.",
            },
            reference=ref,
        )
        assert final["response"]["artifacts"] == child["response"]["artifacts"]
        return final

    async def delegated(self, role, task, initial):
        parent = PathRecorder(self.snapshot)
        parent.begin(
            "preparation-" + self.recorder.current["id"],
            "전문 역할의 실제 상위 위임 준비",
            "user_request",
            "entry-preparation",
        )
        state = parent.initial_state(initial)
        request = deepcopy(state["request"])
        request["goal"] = task["goal"]
        state = await parent.step(
            "interpret",
            "request",
            state,
            [{"request": request, "reason": task["interpret_reason"]}],
        )
        state = await parent.step(
            "decide",
            "request",
            state,
            [
                {
                    "next": "act",
                    "reason": "질문의 지역·월·목적을 확인했으며, 해석 근거 또는 표시 설정을 확보할 전문 작업이 필요하다.",
                }
            ],
        )
        entered, final = None, None

        async def child_plan(child_role, child_state):
            nonlocal entered, final
            assert child_role == role
            entered = dump_state(child_state)
            final = await getattr(self, role)(child_state, task)
            return final

        state = await parent.step(
            "act",
            "request",
            state,
            [
                {
                    "name": role + "_agent",
                    "arguments_json": json.dumps(
                        {"goal": state["request"]["goal"]}, ensure_ascii=False
                    ),
                    "reason": "질문에 필요한 전문 작업을 위임하고 원래 범위를 유지한다.",
                }
            ],
            child_plan=child_plan,
        )
        assert entered is not None and final is not None
        call = _last_call(state, role + "_agent")
        assert call["output"] == {
            key: dump_state(final)[key] for key in ("response", "results", "execution")
        }
        self.recorder.current["entry_transition"] = {
            "kind": "agent_call",
            "parent_role": "request",
            "parent_start_state": deepcopy(parent.current["start_state"]),
            "parent_steps": [
                {
                    key: deepcopy(value)
                    for key, value in step.items()
                    if key not in {"case_id", "input_ref", "expectation_ref"}
                }
                for step in parent.current["steps"]
            ],
            "call_step_id": parent.current["steps"][-1]["step_id"],
            "after_state": entered,
            "parent_return_record_id": call["id"],
        }
        return final

    async def build(self, role, condition):
        await super().build(role, condition)
        scenario = self.recorder.scenarios[-1]
        scenario["history_provenance"] = (
            "역할·대화 조건은 현행 12개 분류를 유지한다. 이전 발화는 작성한 대화 사례이며 현재 선택 문맥은 snapshot.selection에서 가져왔다. 최초 질문에 평가 기준·출처·확인 절차를 넣지 않았다. 실제 노드와 조회·가공·시각화 검사를 실행했다."
        )
        task = self.task(role, condition)
        if task["kind"] in {"comparison", "current_score"}:
            targets = PROVIDERS if task["kind"] == "comparison" else [REGION]
            scenario["evidence_refs"] = [
                {
                    "snapshot": "snapshots/data.json",
                    "dataset": target,
                    "reference": deepcopy(
                        self.snapshot["datasets"][target]["reference"]
                    ),
                    "adm_cd10": self.code,
                }
                for target in targets
            ]
