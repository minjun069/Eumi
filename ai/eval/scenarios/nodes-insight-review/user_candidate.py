"""현실적인 한 질문에 대한 결론 중심의 사용자 응답 검토 사본.

작성한 모델 응답을 실제 노드·조회·가공·상하위 State 전달로 실행한다.
기대조건은 평가 자료에만 두며 외부 모델의 자율 수행 결과를 뜻하지 않는다.
"""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal

from reference_evidence import CONTRIBUTION, DEFINITIONS, METHOD

from eval.scripts.node_dataset_basic_users import _BasicUsers
from eval.scripts.node_dataset_paths import PathRecorder
from eval.scripts.node_dataset_user_paths import _last_call
from eval.scripts.node_dataset_users import REGION, _assessment, numeric_pattern

QUESTION = "도곡1동은 지난달보다 어떤가요?"
GENDER_GAP = "h29_senior_gender_change_gap"
MALE_SHARE = "h18_senior_male_share"
PROVIDERS = [REGION, CONTRIBUTION, DEFINITIONS]


class _InsightUser(_BasicUsers):
    def task(self, role, condition):
        task = super().task(role, condition)
        task.update(
            goal=QUESTION,
            required=[],
            interpret_reason=(
                "선택 지역인 도곡1동의 2025년 12월이 전월인 11월과 비교해 "
                "어떤 상태인지 묻는 요청이다. 사용자가 요구하지 않은 출처 형식이나 "
                "추가 조사·분량 조건은 요청에 넣지 않는다."
            ),
            rationale={
                "user_requirement": QUESTION,
                "available_evidence": [
                    "현재 질문과 선택 화면의 지역·기준 월",
                    "조회 가능한 월별 분석 결과·행동 지표 기여도·지표 정의 자료원",
                ],
                "missing_evidence": [
                    "전월과 현재 월의 배경·행동 점수 및 최근 월별 흐름",
                    "행동 지표 기여도의 비교와 그 지표가 뜻하는 실제 분석 축",
                ],
                "necessary_work": [
                    "해석 에이전트에 비교와 의미 설명을 위임",
                    "월별 점수와 기여도·정의를 조회하고 실제 가공 도구로 비교",
                    "유지된 축과 변화한 축을 연결해 질문에 대한 판단을 제시",
                ],
                "excluded_work": [
                    "사용자가 분석 절차·출처·후속 확인을 요구했다고 바꾸기",
                    "기여도를 원지표 증감이나 전체 점수 변화의 가산 분해로 해석",
                    "개인 상태·특정 성별 활동 감소·시설 원인을 근거 없이 확정",
                ],
            },
        )
        return task

    def quality_reference(self):
        """실행 입력과 분리한 원자료 기준 및 필수 의미; 정답 문구를 고정하지 않는다."""
        monthly = {
            row["period_start"]: deepcopy(row)
            for row in self.snapshot["datasets"][REGION]["rows"]
            if row["adm_cd10"] == self.code
            and "2025-08-01" <= row["period_start"] <= "2025-12-01"
        }
        assert sorted(monthly) == [f"2025-{m:02d}-01" for m in range(8, 13)]
        before, after = monthly["2025-11-01"], monthly["2025-12-01"]
        contributions = {}
        for row in self.snapshot["datasets"][CONTRIBUTION]["rows"]:
            if row["adm_cd10"] == self.code and row["period_start"] in (
                "2025-11-01",
                "2025-12-01",
            ):
                contributions.setdefault(row["indicator_cd"], {})[
                    row["period_start"]
                ] = deepcopy(row)
        assert len(contributions) == 12
        for values in contributions.values():
            values["difference"] = float(
                Decimal(str(values["2025-12-01"]["contribution"]))
                - Decimal(str(values["2025-11-01"]["contribution"]))
            )
        return {
            "required_source": "월별 분석 결과",
            "source_references": {
                name: deepcopy(self.snapshot["datasets"][name]["reference"])
                for name in PROVIDERS
            },
            "target": {"dong_code": self.code, "months": sorted(monthly)},
            "observations": {
                "before": before["bh_score"],
                "after": after["bh_score"],
                "difference": float(
                    Decimal(str(after["bh_score"])) - Decimal(str(before["bh_score"]))
                ),
                "background_before": before["bg_score"],
                "background_after": after["bg_score"],
            },
            "source_rows": {
                REGION: monthly,
                CONTRIBUTION: contributions,
                DEFINITIONS: {
                    row["indicator_cd"]: deepcopy(row)
                    for row in self.snapshot["datasets"][DEFINITIONS]["rows"]
                },
            },
            "required_meanings": [
                "질문에 직접 답하는 종합판단이 필요하다. 배경 점수는 7.25에서 "
                "7.09로 소폭 낮아지고 단계 1을 유지하는데 행동 점수는 "
                "47.82에서 53.06으로 5.24점 높아져, 제공된 지표로는 배경의 "
                "전반적 악화보다 학습 기준에서 벗어난 행동 신호가 커졌다는 "
                "관계를 설명한다.",
                "9월에 높아졌다가 10~11월에 낮아지고 12월에 다시 높아진 "
                "흐름을 반영해, 연속적인 악화나 지속 추세로 확정하지 않는다. "
                "모든 월의 숫자를 나열할 필요는 없다.",
                "12월의 큰 양의 기여 두 항목인 고령층 성별 변화율 격차와 "
                "고령층 남성 비중을 정의에 연결한다. 두 항목 모두 전월보다 "
                "기여도가 커졌으며, 전자는 남녀 활동의 전월 변화율 차이, "
                "후자는 고령층 활동 중 남성 비중이다. 기여도 증가는 원지표 "
                "증가와 다르다.",
                "따라서 고령층 전체를 한 집단의 일률적 활동 위축으로 보지 않고, "
                "남녀 활동의 구성과 변화 차이를 구분하는 것이 이번 신호를 "
                "이해하는 중요한 축이라는 해석을 제시한다.",
                "기여도는 한 지표를 같은 도시·같은 달의 중앙값으로 바꿨을 때의 "
                "모델 점수 차이다. 큰 양의 기여를 성별 활동 변화의 방향이나 "
                "원인으로 바꾸지 않으며, 어떤 성별의 활동이 줄었는지는 원값 "
                "없이 확정할 수 없음을 해당 해석에 연결한다.",
            ],
            "required_limitations": [
                "배경 안정은 제공된 배경 지표 범위의 판단이다.",
                "행동 이상 점수는 학습 기준 행동과의 차이이며 "
                "개인의 고립 진단이 아니다.",
                "기여도는 실제 활동량·원지표값·변화 방향·가산 원인분해가 아니다.",
            ],
            "excluded_claims": [
                "미달: 이전 사본처럼 '최근 5개월 최고이니 기여도·활동값·이후 월을 "
                "확인하세요'로 끝내고, 유지된 배경과 달라진 행동의 관계 및 "
                "성별 구성·변화 차이가 갖는 의미를 결론으로 제시하지 않는다.",
                "미달: 정확한 수치·정의·일반 주의문을 나열하지만 이번 지역을 "
                "어떻게 이해할지 판단이 없다.",
                "미달: 기여도 수치가 커졌으므로 고령 남성 활동이 감소했다거나 "
                "남녀 차이가 확대됐다고 원지표 방향을 확정한다.",
                "미달: 기여도 합계나 두 항목의 비율을 점수 상승의 설명률로 쓴다.",
                "미달: 배경 점수의 소폭 하락을 주민 여건의 전반적 개선으로, "
                "행동 점수 상승을 개인 고립 악화·지속 악화로 단정한다.",
            ],
            "comparison": (
                "특정 결론 문장·단어·문단 순서와 기여도 수치의 전부 나열은 "
                "요구하지 않는다. 배경/행동의 대비, 등락 뒤 재상승, 정의에 "
                "근거한 고령 성별 해석축이라는 관계와 한계를 보존하면 허용한다. "
                "다른 근거 있는 설명도 가능하나 관측 나열과 일반 확인 제안만으로 "
                "판단을 대신할 수 없다. 후속 제안은 선택 사항이며 없어도 감점하지 "
                "않는다. 숫자 규칙 통과만으로 의미 기준 통과를 인정하지 않는다."
            ),
        }

    async def step(self, node, role, state, output, **kwargs):
        reference = {
            "expected_behavior": output["reason"],
            "allowed_scope": state["request"]["goal"],
            **deepcopy(kwargs.get("reference") or {}),
        }
        exact = {}
        if node == "interpret":
            reference.update(
                request=deepcopy(output["request"]),
                comparison="동·월·전월 비교 목적을 보존하며 "
                "사용자 요구를 추가하지 않는다.",
            )
        elif node == "decide":
            reference.update(next=output["next"], required_reason=output["reason"])
            exact["N03-O.3"] = {"path": "/next", "value": output["next"]}
        elif node == "act":
            arguments = json.loads(output["arguments_json"])
            reference.update(selected_name=output["name"], expected_arguments=arguments)
            exact["N02-O.1"] = {"path": "/name", "value": output["name"]}
            key = {"query_data": "target", "process_data": "input_result_id"}.get(
                output["name"]
            )
            if key:
                exact["N02-O.3"] = {
                    "path": "/arguments_json/" + key,
                    "value": arguments[key],
                    "match": "subset",
                }
            reference["argument_comparison"] = (
                "대상·기간·비교의 의미를 보존하는 동등한 입력을 허용한다. "
                "하위 목표에는 실제 질문의 의미를 전달하며 평가 기준을 넣지 않는다."
            )
        elif node == "compose":
            reference.update(self.quality_reference())
            reference.update(status=output["status"])
            exact["N04-O.1"] = {"path": "/status", "value": "completed"}
        assessment = _assessment(
            node,
            reference,
            exact,
            artifacts=[],
            numeric=(
                {
                    "path": "/content",
                    "pattern": numeric_pattern(5.24),
                    "extract": "number",
                    "value": 5.24,
                    "tolerance": {"absolute": 0.005, "relative": 0.0},
                }
                if node == "compose"
                else None
            ),
        )
        if node == "compose":
            number_item = next(
                item
                for item in assessment["expected"]["items"]
                if item["check"] == "N-O.1"
            )
            assessment["expected"]["items"] = [
                item
                for item in assessment["expected"]["items"]
                if item["check"] != "N-O.1"
            ]
            for name, value in reference["observations"].items():
                item = deepcopy(number_item)
                item.update(
                    id=f"N-O.1-{name}", pattern=numeric_pattern(value), value=value
                )
                assessment["expected"]["items"].append(item)
            for item in assessment["expected"]["items"]:
                if item["check"] in {"N-O.2", "N-O.3", "N-O.4", "N-O.5", "N-O.10"}:
                    item["value"] = (
                        "reference.required_meanings·required_limitations·comparison의 "
                        "의미 기준을 충족한다. 수치·현상·확인 제안만 있는 답과 "
                        "근거에서 종합판단을 "
                        "도출한 답을 구별하고 excluded_claims의 미달 예시를 적용한다."
                    )
        return await self.recorder.step(
            node,
            role,
            state,
            [output],
            frame=kwargs.get("frame", "root"),
            label=output["reason"],
            child_plan=kwargs.get("child_plan"),
            template={"providers": PROVIDERS, "assessment": assessment},
        )

    async def work(self, state, name, arguments, reason, frame):
        state = await self.decide(state, "interpretation", "act", reason, frame)
        return await self.act(state, "interpretation", name, arguments, reason, frame)

    async def process(self, state, operations, input_id, reason, frame, *, decimals=6):
        return await self.work(
            state,
            "process_data",
            {
                "input_result_id": input_id,
                "operations": operations,
                "decimals": decimals,
            },
            reason,
            frame,
        )

    async def interpretation(self, state, task, *, frame="child-interpretation"):
        role = "interpretation"
        state = await self.interpret(state, role, task, frame)
        state = await self.work(
            state,
            "query_data",
            {
                "target": REGION,
                "filters": [
                    {"field": "adm_cd10", "operator": "eq", "value": self.code},
                    {"field": "period_start", "operator": "ge", "value": "2025-08-01"},
                    {"field": "period_start", "operator": "le", "value": "2025-12-01"},
                ],
                "sort": [{"field": "period_start", "descending": False}],
                "limit": 100,
            },
            "전월 비교에 필요한 배경·행동 점수와 최근 흐름을 조회해, "
            "어떤 축이 달라졌는지와 연속된 변화인지 판단할 근거를 확보한다.",
            frame,
        )
        monthly = _last_call(state, "query_data")
        assert monthly["output"]["total"] == monthly["output"]["returned"] == 5
        state = await self.process(
            state,
            [
                {
                    "operation": "filter",
                    "conditions": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": "2025-11-01",
                        }
                    ],
                }
            ],
            monthly["id"],
            "월별 자료가 확보됐다. 두 점수의 전월 차이를 계산할 11월 행을 분리한다.",
            frame,
        )
        previous_id = _last_call(state, "process_data")["id"]
        state = await self.process(
            state,
            [
                {
                    "operation": "filter",
                    "conditions": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": "2025-12-01",
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
                        "bg_grade": "previous_bg_grade",
                    },
                },
                {
                    "operation": "calculate",
                    "method": "difference",
                    "before": "previous_bh_score",
                    "after": "bh_score",
                    "output": "bh_change",
                },
                {
                    "operation": "calculate",
                    "method": "difference",
                    "before": "previous_bg_score",
                    "after": "bg_score",
                    "output": "bg_change",
                },
            ],
            monthly["id"],
            "같은 지역의 11월과 12월을 결합해 배경과 행동의 차이를 각각 계산한다.",
            frame,
        )
        scores = _last_call(state, "process_data")["output"]["data"]["rows"][0]
        assert (scores["bh_change"], scores["bg_change"]) == (5.24, -0.16)
        state = await self.work(
            state,
            "query_data",
            {
                "target": CONTRIBUTION,
                "filters": [
                    {"field": "adm_cd10", "operator": "eq", "value": self.code},
                    {"field": "period_start", "operator": "ge", "value": "2025-11-01"},
                    {"field": "period_start", "operator": "le", "value": "2025-12-01"},
                ],
                "sort": [{"field": "period_start", "descending": False}],
                "limit": 100,
            },
            "배경 점수는 소폭 낮아지고 행동 점수는 5.24점 높아졌다. "
            "행동 쪽에서 어떤 분석 축이 두드러지는지 두 달의 기여도 전체를 확인한다.",
            frame,
        )
        contribution = _last_call(state, "query_data")
        assert (
            contribution["output"]["total"] == contribution["output"]["returned"] == 24
        )
        state = await self.work(
            state,
            "query_data",
            {"target": DEFINITIONS, "limit": 100},
            "지표 기여도를 확보했으므로 지표의 실제 의미와 기여도 산출 방법을 "
            "조회한다. 코드명이나 기여도 부호만으로 활동 방향을 정하지 않는다.",
            frame,
        )
        definitions = _last_call(state, "query_data")
        assert definitions["output"]["total"] == definitions["output"]["returned"] == 13
        definition_rows = {
            row["indicator_cd"]: row for row in definitions["output"]["data"]["rows"]
        }
        assert {GENDER_GAP, MALE_SHARE, METHOD} <= definition_rows.keys()
        state = await self.process(
            state,
            [
                {
                    "operation": "filter",
                    "conditions": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": "2025-11-01",
                        }
                    ],
                }
            ],
            contribution["id"],
            "두 달의 같은 지표를 비교할 수 있도록 11월 기여도 12개를 분리한다.",
            frame,
        )
        previous_contribution = _last_call(state, "process_data")["id"]
        state = await self.process(
            state,
            [
                {
                    "operation": "filter",
                    "conditions": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": "2025-12-01",
                        }
                    ],
                },
                {
                    "operation": "join",
                    "right_result_id": previous_contribution,
                    "keys": ["adm_cd10", "indicator_cd"],
                    "how": "inner",
                    "fields": {"contribution": "previous_contribution"},
                },
                {
                    "operation": "calculate",
                    "method": "difference",
                    "before": "previous_contribution",
                    "after": "contribution",
                    "output": "contribution_change",
                },
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
            contribution["id"],
            "12월 기여도 전체에 전월값과 실제 지표 정의를 결합하고 차이를 "
            "계산한다. 큰 양의 기여 항목과 그 의미를 함께 읽는다.",
            frame,
        )
        compared = _last_call(state, "process_data")["output"]["data"]["rows"]
        assert len(compared) == 12
        assert [row["indicator_cd"] for row in compared[:2]] == [GENDER_GAP, MALE_SHARE]
        assert all(row["contribution_change"] > 0 for row in compared[:2])
        state = await self.decide(
            state,
            role,
            "compose",
            "배경은 단계 1을 유지하고 행동 점수는 등락 뒤 다시 상승했다. 현재 큰 "
            "양의 기여 두 항목은 고령층 남녀의 변화율 차이와 남성 비중으로, "
            "고령층 전체의 일률적 변화보다 성별 구성·변화 차이를 구분하는 "
            "해석이 필요하다. 원값 없이 어느 성별이 감소했는지는 정하지 않는다.",
            frame,
        )
        content = (
            "도곡1동은 지난달보다 행동 이상 신호가 커졌습니다. 다만 제공된 "
            "지표로 보면 배경 여건이 전반적으로 나빠졌다기보다, 행동이 학습 "
            "기준에서 더 벗어난 상황으로 해석할 수 있습니다.\n\n"
            f"행동 이상 점수는 {scores['previous_bh_score']:.2f}점에서 "
            f"{scores['bh_score']:.2f}점으로 {scores['bh_change']:.2f}점 올랐지만, "
            f"배경 점수는 {scores['previous_bg_score']:.2f}점에서 "
            f"{scores['bg_score']:.2f}점으로 소폭 낮아졌고 단계도 1로 같습니다. "
            "9월에 높아졌다가 10~11월에 낮아진 뒤 12월에 다시 오른 흐름이라, "
            "계속 악화되는 추세로 보기는 어렵습니다. 행동 이상 점수는 학습 "
            "기준과의 차이를 보여주며 개인의 고립 상태를 뜻하지 않습니다.\n\n"
            "이번 신호를 이해할 핵심은 고령층을 남녀로 나눠 보는 것입니다. "
            "현재 점수에서 큰 양의 기여를 보인 두 항목은 ‘고령 남녀의 활동 "
            "변화율 차이’와 ‘고령층 활동 중 남성 비중’이며, 두 항목 모두 "
            "전월보다 기여도가 커졌습니다. 해당 항목을 "
            "같은 도시·같은 달의 중앙값으로 바꾸면 점수가 낮아진다는 뜻이므로, "
            "고령층 전체가 함께 위축됐다고 보기보다 남녀의 활동 구성과 변화 "
            "차이를 구분해 읽는 것이 맞습니다. 다만 실제 활동값이 없어 남성과 "
            "여성 중 누가 줄었는지, 비중이 어느 방향으로 바뀌었는지는 아직 "
            "알 수 없습니다.\n\n"
            "어느 격자부터 살펴볼지도 이어서 정리해드릴까요?\n"
            "자료: 2025년 8~12월 월별 분석 결과, "
            "11~12월 행동 지표 기여도 및 지표 정의."
        )
        return await self.step(
            "compose",
            role,
            state,
            {
                "content": content,
                "artifact_ids": [],
                "status": "completed",
                "reason": "유지된 배경과 달라진 행동 신호를 비교한 판단, "
                "등락 뒤 재상승, "
                "고령층 성별 구성·변화의 해석축을 근거와 한계에 연결한다.",
            },
            frame=frame,
        )

    async def request(self, state, task):
        role, frame = "request", "root"
        state = await self.interpret(state, role, task, frame)
        state = await self.decide(
            state,
            role,
            "act",
            "대상과 비교 월은 명확하다. 전월 대비 상태를 설명할 분석 결과가 "
            "아직 없으므로 해석 에이전트에 조회와 비교·의미 설명을 위임한다.",
            frame,
        )

        async def child_plan(child_role, child_state):
            assert child_role == "interpretation"
            return await self.interpretation(child_state, task)

        state = await self.act(
            state,
            role,
            "interpretation_agent",
            {"goal": state["request"]["goal"]},
            "도곡1동의 2025년 12월이 전월과 비교해 어떤지 설명하는 목적을 전달한다.",
            frame,
            child_plan=child_plan,
            reference={
                "goal_semantics": {
                    "region": {"code": self.code, "name": self.name},
                    "periods": {"current": self.month, "previous": self.previous},
                    "purpose": "전월과 비교한 상태와 의미 설명",
                    "required_details": [],
                }
            },
        )
        child = _last_call(state, "interpretation_agent")["output"]
        assert child["execution"]["status"] == "completed"
        state = await self.decide(
            state,
            role,
            "compose",
            "하위가 배경·행동의 비교와 최근 흐름, 지표 정의에 근거한 "
            "성별 해석축을 반환했다. 핵심 판단·근거·해석 범위를 보존해 답한다.",
            frame,
        )
        return await self.step(
            "compose",
            role,
            state,
            {
                "content": child["response"]["content"],
                "artifact_ids": [],
                "status": "completed",
                "reason": "하위의 직접 판단과 근거를 통합해 "
                "짧은 질문에 답하고 원지표 방향과 개인 상태의 한계를 보존한다.",
            },
            frame=frame,
            reference={
                "child_transfer": True,
                "child_content": child["response"]["content"],
            },
        )


async def build_user_candidate(snapshot: dict, recorder: PathRecorder) -> dict:
    """원본과 독립된 사용자 요청 사본 한 개를 실제 실행하고 경로를 반환한다."""
    paths = _InsightUser(snapshot, recorder)
    assert (paths.code, paths.month, paths.previous) == (
        "1168065500",
        "2025-12",
        "2025-11",
    )
    task = paths.task("request", "none")
    recorder.begin(
        "insight-request-none",
        "사용자 요청 처리 · 전월 대비 종합판단",
        "user_request",
        "insight-review-request",
        axes={"conversation_condition": "none"},
        source_groups=[],
    )
    recorder.current.update(
        scope="agent",
        agent_role="request",
        conversation_condition="none",
        region_code=paths.code,
        expected_summary=task["goal"],
        task_rationale=deepcopy(task["rationale"]),
        history_provenance=(
            "basic-request-none의 검토용 사본. 최초 질문은 현실적인 전월 비교 "
            "한 문장으로 바꿨다. 원본 snapshot.selection의 지역명·행정동 코드·"
            "기준 월을 선택 화면의 식별 문맥으로 제공하며 "
            "출처·후속 확인·평가 기준을 사용자 요구로 넣지 않았다. 지표 정의를 "
            "추가한 prepared 자료원을 실제 조회하고 고정 모델 응답으로 현재 "
            "노드·도구·상하위 전달을 실행했다. 원본은 변경하지 않았다."
        ),
        evidence_refs=[
            {
                "snapshot": "snapshots/data.json",
                "dataset": name,
                "reference": deepcopy(snapshot["datasets"][name]["reference"]),
                "adm_cd10": paths.code,
            }
            for name in PROVIDERS
        ],
    )
    state = recorder.initial_state(
        {
            "event": "user_request",
            "request": {"goal": QUESTION},
            "messages": [
                {
                    "type": "system",
                    "content": f"선택 지역: {paths.selected['city_name']} "
                    f"{paths.name}(행정동 코드 {paths.code}). "
                    f"화면 기준 월: {paths.month}.",
                },
                {"type": "human", "content": QUESTION},
            ],
            "results": [],
            "response": None,
        }
    )
    state = await paths.request(state, task)
    recorder.end(state, terminal="completed")
    return recorder.scenarios[-1]
