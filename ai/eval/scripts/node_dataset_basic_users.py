"""Build twelve fresh user-agent paths against the current production nodes.

Only model replies and conversation fixtures are authored. Query, processing,
visualization validation, child creation and State accumulation use real code.
"""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from typing import Literal, TypedDict

from eval.scripts.node_dataset_paths import PathRecorder, dump_state
from eval.scripts.node_dataset_user_paths import Recorder, _last_call
from eval.scripts.node_dataset_users import LIMIT, REGION, _assessment, numeric_pattern
from src.tools.tableau_catalog import registered_catalog

CONDITIONS = ("none", "new_topic", "revision", "clarification_complete")
ROLES = ("request", "interpretation", "visualization")
CONDITION_LABELS = {
    "none": "이전 대화 없음",
    "new_topic": "이전과 다른 새 주제",
    "revision": "기존 응답 수정",
    "clarification_complete": "AI 추가 질문에 충분한 답변",
}
ROLE_LABELS = {
    "request": "사용자 요청 처리",
    "interpretation": "데이터 분석 결과 해석",
    "visualization": "데이터 시각화",
}
VISUAL_LIMIT = (
    "등록된 표시 설정 검사이며 자료 존재·최신성·실제 화면 표시를 확인한 결과는 아니다."
)


class TaskRationale(TypedDict):
    user_requirement: str
    available_evidence: list[str]
    missing_evidence: list[str]
    necessary_work: list[str]
    excluded_work: list[str]


class UserTask(TypedDict):
    kind: Literal[
        "comparison",
        "current_score",
        "rewrite",
        "detail_map",
        "city_map",
        "detail_pair",
    ]
    goal: str
    interpret_reason: str
    required: list[str]
    views: list[str]
    rationale: TaskRationale


class _BasicUsers:
    def __init__(self, snapshot, recorder):
        self.snapshot, self.recorder = snapshot, recorder
        self.selected = snapshot["selection"]
        self.code = self.selected["dong_code"]
        self.name = self.selected["dong_name"]
        self.month = self.selected["month"]
        self.previous = self.selected["previous_month"]
        self.catalog = registered_catalog()
        labels = self.catalog["input_profiles"]["monthly_city"]["parameters"]["p_city"][
            "labels"
        ]
        self.city_code = next(
            code
            for code, label in labels.items()
            if label.endswith(self.selected["city_name"])
        )
        self.parameters = {
            "p_start": self.month + "-01",
            "p_end": self.month + "-01",
            "p_detail_adm": self.selected["city_name"] + " " + self.name,
        }

    def task(self, role, condition) -> UserTask:
        """Author the requested work before authoring any expected node replies."""
        kind = "comparison"
        if role == "visualization":
            kind = {
                "none": "detail_map",
                "new_topic": "city_map",
                "revision": "detail_map",
                "clarification_complete": "detail_pair",
            }[condition]
        elif condition == "revision" and role == "request":
            kind = "rewrite"
        elif condition == "new_topic":
            kind = "detail_map" if role == "request" else "current_score"

        views = []
        if kind == "rewrite":
            goal = (
                f"이전 답변의 {self.name} 행동 이상 점수 정의와 개인 상태를 "
                "판단할 수 없다는 한계를 같은 의미의 쉬운 두 문장으로 다시 쓴다. "
                "새 수치·비교·해석은 추가하지 않는다."
            )
            required = [
                "이전 정의와 한계의 의미를 유지한다.",
                "쉬운 두 문장으로 줄이고 새 수치·비교·해석을 추가하지 않는다.",
            ]
            available = [
                "실제 이전 답변에 있는 점수 정의와 해석 한계",
                "추가 분석 없이 표현만 수정하라는 현재 요청",
            ]
            missing, work = [], ["이전 대화의 정의·한계를 쉬운 두 문장으로 재작성"]
            excluded = [
                "자료 조회",
                "계산",
                "전문 에이전트 위임",
                "새 수치·원인·비교 추가",
            ]
        elif kind in {"comparison", "current_score"}:
            if kind == "comparison":
                goal = (
                    f"{self.name}({self.code})의 {self.month} 행동 이상 점수를 "
                    f"{self.previous}와 비교하고 점수 차이·출처·해석 한계를 설명한다."
                )
                required = [
                    "같은 행정동의 두 달 행동 이상 점수를 비교한다.",
                    "관측한 점수 변화·출처·해석 한계를 함께 설명한다.",
                ]
                missing = [
                    "현재 월과 전월의 실제 행동 이상 점수",
                    "같은 행정동의 두 달 차이 계산 결과",
                ]
                work = [
                    "두 달의 원자료 조회",
                    "현재 월에서 전월을 뺀 차이 계산",
                    "관측된 변화·출처·해석 한계 설명",
                ]
                if role == "request":
                    work.insert(0, "자료 조회·계산·해석을 해석 에이전트에 위임")
            else:
                goal = (
                    f"{self.name}({self.code})의 {self.month} 행동 이상 점수만 "
                    "확인하고 출처·해석 한계를 설명한다. 전월 비교는 하지 않는다."
                )
                required = [
                    "요청한 동·현재 월의 행동 이상 점수만 설명한다.",
                    "출처·해석 한계를 밝히고 전월 비교는 하지 않는다.",
                ]
                missing = ["현재 월의 실제 행동 이상 점수"]
                work = ["현재 월 원자료 조회", "현재 점수·출처·해석 한계 설명"]
            available = [
                "대화에서 확정된 행정동과 요청 월",
                "등록 자료원·지표 정의; 이번 실행의 점수 조회 결과는 아직 없음",
            ]
            excluded = ["개인 진단", "관측되지 않은 원인 단정"]
            if kind == "current_score":
                excluded += ["전월 조회", "차이 계산", "기간 추세 설명"]
            if role == "interpretation" and condition == "revision":
                goal = "이전 답변의 점수 정의·해석 한계를 유지하면서 " + goal
                required.append("이전 답변의 점수 정의와 해석 한계를 유지한다.")
                available.append("이전 실제 답변의 점수 정의·해석 한계")
        else:
            if kind == "city_map":
                goal = (
                    f"{self.selected['city_name']}({self.city_code}) 전체의 "
                    f"{self.month} "
                    "배경 취약성 지도를 보여 주고 적용 조건·확인 한계를 설명한다. "
                    "특정 동으로 좁히지 않는다."
                )
                views = ["Embed01VulnerabilityMap"]
                required = [
                    "도시 전체의 종료월 배경 취약성 지도를 제공한다.",
                    "읍면동 필터로 지역 범위를 좁히지 않는다.",
                    "설정 검사와 실제 표시 확인의 차이를 안내한다.",
                ]
            else:
                requested = (
                    "상세 지도와 행동 지표 기여도 차트"
                    if kind == "detail_pair"
                    else "상세 지도"
                )
                goal = (
                    f"{self.selected['city_name']} {self.name}({self.code})의 "
                    f"{self.month} "
                    f"{requested}를 표시할 설정과 적용 조건·한계를 제공한다."
                )
                views = ["EmbedDetailMap"] + (
                    ["EmbedDetailV02"] if kind == "detail_pair" else []
                )
                required = [
                    f"요청한 동·월의 {requested}를 제공한다.",
                    "설정 검사와 실제 표시 확인의 차이를 안내한다.",
                ]
            available = [
                "대화에서 확정된 지역·월·시각화 목적",
                "등록된 뷰·입력 프로필·허용값; 이번 요청 설정의 검사 결과는 아직 없음",
            ]
            missing = [
                f"{self.catalog['views'][view]['title']}의 "
                "요청 조건 검사와 유효한 산출물"
                for view in views
            ]
            work = [
                "요청 목적에 맞는 등록 뷰 선택",
                "요청한 각 뷰의 표시 조건 검사",
                "모든 요청 산출물과 설정 검사의 한계 반환",
            ]
            if role == "request":
                work.insert(0, "표시 설정과 산출물 확보를 시각화 에이전트에 위임")
            excluded = [
                "표시 설정 검사만으로 실제 화면 표시·자료 최신성 단정",
                "불필요한 수치 조회·계산",
            ]

        reasons = {
            "none": "현재 발화에 명시한 대상·월·작업 목적을 요청으로 정리한다.",
            "new_topic": "이전 주제는 종료했고 현재 발화가 지정한 "
            "새 대상·작업 목적만 이번 요청에 반영한다.",
            "revision": (
                "이전 대화의 동과 상세 지도 목적을 유지하고 "
                "사용자가 바꾼 월만 반영한다."
                if role == "visualization"
                else "이전 답변의 정의·한계를 유지하고 같은 동의 두 달 실제 "
                "점수·차이·출처를 추가하는 수정 요청으로 정리한다."
                if role == "interpretation"
                else "이전 답변의 정의·한계를 가리키는 수정 요청이다. "
                "표현만 쉽게 줄이고 새 분석을 추가하지 않는 조건을 유지한다."
            ),
            "clarification_complete": (
                "이전 발화의 상세 지도와 행동 지표 기여도 차트 두 목적을 "
                "유지하고 추가 답변의 동·월을 결합한다."
                if role == "visualization"
                else "이전 발화의 전월 비교 목적과 "
                "추가 답변의 행정동·기준 월을 결합한다."
            ),
        }
        return {
            "kind": kind,
            "goal": goal,
            "interpret_reason": reasons[condition],
            "required": required,
            "views": views,
            "rationale": {
                "user_requirement": goal,
                "available_evidence": available,
                "missing_evidence": missing,
                "necessary_work": work,
                "excluded_work": excluded,
            },
        }

    def initial(self, role, condition, task):
        preferred = []
        if condition == "none":
            latest, prior = task["goal"], []
        elif condition == "new_topic":
            latest = "이전 설명은 여기까지 하고 새 요청입니다. " + task["goal"]
            prior = [
                {
                    "type": "human",
                    "content": f"{self.selected['comparison_dong_name']}의 "
                    "배경 취약성 점수는 개인의 상태인가요?",
                },
                {
                    "type": "ai",
                    "content": "지역 수준의 배경 취약성 점수이며 개인 상태를 "
                    "확인한 결과는 아닙니다.",
                },
            ]
        elif condition == "revision":
            visual = role == "visualization"
            latest = (
                f"같은 동을 유지하고 기간을 {self.month}로 바꿔서 "
                "상세 지도 표시 조건을 수정해 주세요."
                if visual
                else "그 설명의 정의와 한계는 유지하고 같은 동의 "
                f"{self.month}와 {self.previous} 실제 행동 이상 점수·차이·출처를 "
                "추가해서 답변을 수정해 주세요."
                if role == "interpretation"
                else "그 설명의 정의와 한계는 유지하고 쉬운 두 문장으로 "
                "짧게 다시 써 주세요. 새 수치나 비교·해석은 추가하지 마세요."
            )
            prior = [
                {
                    "type": "human",
                    "content": f"{self.name}의 {self.previous} 상세 지도를 보여 주세요."
                    if visual
                    else f"{self.name}의 행동 이상 점수가 "
                    "무엇을 뜻하는지 설명해 주세요.",
                },
                {
                    "type": "ai",
                    "content": (
                        f"{self.name}의 {self.previous} 상세 지도 표시 조건을 "
                        "안내했습니다. 실제 화면 표시 성공은 별도로 확인해야 합니다."
                        if visual
                        else f"{self.name}의 행동 이상 점수는 학습 기준 행동과의 "
                        "차이를 뜻합니다. 실제 활동량이나 개인의 고립 상태를 "
                        "뜻하지 않습니다."
                    ),
                },
            ]
            preferred = (
                [
                    f"현재 화면 선택 지역: {self.name}({self.code})",
                    f"현재 화면 선택 월: {self.previous}",
                ]
                if visual
                else []
            )
        else:
            assert condition == "clarification_complete"
            prior = [
                {
                    "type": "human",
                    "content": "상세 지도와 행동 지표 기여도 차트를 함께 보여 주세요."
                    if role == "visualization"
                    else "행동 이상 점수를 전월과 비교하고 "
                    "차이·출처·해석 한계를 설명해 주세요.",
                },
                {
                    "type": "ai",
                    "content": "어느 지역의 몇 년 몇 월을 기준으로 할까요?",
                },
            ]
            latest = (
                f"{self.selected['city_name']} {self.name}({self.code}), "
                f"{self.month}로 해 주세요."
            )
        initial = {
            "event": "user_request",
            "request": {
                "goal": latest,
                "constraints": {
                    "required": task["required"],
                    "preferred": preferred,
                    "excluded": [],
                },
            },
            "messages": prior + [{"type": "human", "content": latest}],
            "results": [],
            "response": None,
        }
        return initial

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
            ref["request"] = deepcopy(output["request"])
            ref["comparison"] = (
                "대상·기간·목적·조건을 보존하는 같은 의미의 표현을 허용한다."
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
            if key is not None:
                exact["N02-O.3"] = {
                    "path": "/arguments_json/" + key,
                    "value": args[key],
                    "match": "subset",
                }
            ref["argument_comparison"] = (
                "필터·가공 인자는 동일한 대상·기간·원자료·계산 결과를 보존하는 "
                "표현을 허용한다. 하위 목표도 확인된 요청 의미를 보존하면 "
                "다른 문장으로 표현할 수 있다."
            )
            if output["name"].endswith("_agent"):
                ref.update(
                    rule_evaluation="미판정",
                    semantic_review=(
                        "현재 규칙 평가기는 자연어 목표의 의미 동등성을 판정하지 "
                        "않는다. 문자열 일치나 존재 여부를 정답으로 대체하지 않으며 "
                        "goal_semantics에 명시한 대상·기간·목적·조건의 보존을 "
                        "자연어로 검토한다. "
                        "적용 대상이므로 비적용으로 처리하지 않는다."
                    ),
                )
            if output["name"] == "validate_visualization":
                ref.update(
                    allowed_views=[args["view_key"]],
                    target={"parameters": deepcopy(args["parameters"])},
                    verification_scope="registered_configuration",
                )
        elif node == "compose":
            ref.update(status=output["status"], expected_content=output["content"])
            exact["N04-O.1"] = {"path": "/status", "value": output["status"]}
        assessment = _assessment(
            node,
            ref,
            exact,
            artifacts=output.get("artifact_ids", []),
            numeric=(
                {
                    "path": "/content",
                    "pattern": numeric_pattern(numeric),
                    "extract": "number",
                    "value": numeric,
                    "tolerance": {"absolute": 0.01, "relative": 0.0},
                }
                if numeric is not None
                else None
            ),
        )
        return await self.recorder.step(
            node,
            role,
            state,
            [output],
            frame=frame,
            label=output["reason"],
            child_plan=child_plan,
            template={"providers": [REGION], "assessment": assessment},
        )

    async def interpret(self, state, role, task, frame):
        request = deepcopy(state["request"])
        request["goal"] = task["goal"]
        return await self.step(
            "interpret",
            role,
            state,
            {
                "request": request,
                "reason": task["interpret_reason"],
            },
            frame=frame,
        )

    async def decide(self, state, role, target, reason, frame):
        return await self.step(
            "decide",
            role,
            state,
            {"next": target, "reason": reason},
            frame=frame,
        )

    async def act(
        self, state, role, name, args, reason, frame, *, child_plan=None, reference=None
    ):
        return await self.step(
            "act",
            role,
            state,
            {
                "name": name,
                "arguments_json": json.dumps(args, ensure_ascii=False),
                "reason": reason,
            },
            frame=frame,
            child_plan=child_plan,
            reference=reference,
        )

    def query_args(self, month):
        return {
            "target": REGION,
            "filters": [
                {"field": "period_start", "operator": "eq", "value": month + "-01"},
                {"field": "adm_cd10", "operator": "eq", "value": self.code},
            ],
        }

    async def interpretation(self, state, task, *, frame="root"):
        role = "interpretation"
        if task["kind"] == "rewrite":
            return await self.rewrite(state, role, task, frame)
        state = await self.interpret(state, role, task, frame)
        comparison = task["kind"] == "comparison"
        state = await self.decide(
            state,
            role,
            "act",
            "대상과 두 비교 월은 확인됐지만 실제 점수 원자료가 없다. "
            "먼저 현재 월의 점수가 필요하다."
            if comparison
            else "대상과 현재 월은 확인됐지만 실제 점수가 없다. "
            "현재 월 점수만 확보하면 되며 전월 자료와 차이 계산은 요청하지 않았다.",
            frame,
        )
        state = await self.act(
            state,
            role,
            "query_data",
            self.query_args(self.month),
            "확인된 행정동·현재 월의 행동 이상 점수 원자료를 조회한다.",
            frame,
        )
        current = _last_call(state, "query_data")
        assert current["outcome"] == "success" and current["output"]["total"] == 1
        if not comparison:
            value = current["output"]["data"]["rows"][0]["bh_score"]
            state = await self.decide(
                state,
                role,
                "compose",
                "요청한 동·현재 월의 실제 행동 이상 점수와 출처가 확보됐다. "
                "전월 비교는 제외했으므로 현재 값과 정의·한계를 설명할 수 있다.",
                frame,
            )
            return await self.step(
                "compose",
                role,
                state,
                {
                    "content": f"{self.name}의 {self.month} 행동 이상 점수는 "
                    f"{value}입니다. 출처 public.region_result. {LIMIT}",
                    "artifact_ids": [],
                    "status": "completed",
                    "reason": "요청한 현재 월의 점수·출처·해석 한계만 설명하고 "
                    "전월 비교를 추가하지 않는다.",
                },
                frame=frame,
                numeric=value,
                reference={
                    "required_source": "public[.]region_result",
                    "required_limitations": [LIMIT],
                    "observations": {"after": value},
                    "target": {"dong_code": self.code, "months": [self.month]},
                    "source_reference": deepcopy(
                        self.snapshot["datasets"][REGION]["reference"]
                    ),
                },
            )
        state = await self.decide(
            state,
            role,
            "act",
            "현재 월 점수는 확보했고 전월 점수가 없어 "
            "비교가 아직 불가능하다. 같은 행정동의 전월 점수가 추가로 필요하다.",
            frame,
        )
        state = await self.act(
            state,
            role,
            "query_data",
            self.query_args(self.previous),
            "이미 확보한 현재 월을 반복하지 않고 비교 대상 전월을 조회한다.",
            frame,
        )
        previous = _last_call(state, "query_data")
        assert previous["outcome"] == "success" and previous["output"]["total"] == 1
        state = await self.decide(
            state,
            role,
            "act",
            "동일 행정동의 두 달 점수를 확보했다. "
            "현재 월에서 전월을 뺀 차이를 계산해야 한다.",
            frame,
        )
        state = await self.act(
            state,
            role,
            "process_data",
            {
                "input_result_id": current["id"],
                "operations": [
                    {
                        "operation": "join",
                        "right_result_id": previous["id"],
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
            "같은 행정동의 두 조회 결과를 결합해 "
            "현재 월과 전월의 점수 차이를 계산한다.",
            frame,
        )
        processed = _last_call(state, "process_data")
        row = processed["output"]["data"]["rows"][0]
        current_value = current["output"]["data"]["rows"][0]["bh_score"]
        previous_value = previous["output"]["data"]["rows"][0]["bh_score"]
        difference = float(Decimal(str(current_value)) - Decimal(str(previous_value)))
        assert row["bh_change"] == difference
        state = await self.decide(
            state,
            role,
            "compose",
            "두 달 점수·같은 행정동 조건·차이 계산과 "
            "출처가 확보되어 관측된 변화와 해석 한계를 설명할 수 있다.",
            frame,
        )
        direction = "증가" if difference > 0 else "감소" if difference < 0 else "유지"
        content = (
            f"{self.name}의 {self.previous} 행동 이상 점수는 {previous_value}, "
            f"{self.month}는 {current_value}입니다. 현재 월에서 전월을 뺀 "
            f"차이는 {difference}점으로 {direction}했습니다. "
            f"출처 public.region_result. {LIMIT}"
        )
        return await self.step(
            "compose",
            role,
            state,
            {
                "content": content,
                "artifact_ids": [],
                "status": "completed",
                "reason": "실제 점수와 차이·출처·해석 한계를 보존해 "
                "비교 결과를 반환한다.",
            },
            frame=frame,
            numeric=difference,
            reference={
                "required_source": "public[.]region_result",
                "required_limitations": [LIMIT],
                "observations": {
                    "before": previous_value,
                    "after": current_value,
                    "difference": difference,
                },
                "target": {
                    "dong_code": self.code,
                    "months": [self.previous, self.month],
                },
                "source_reference": deepcopy(
                    self.snapshot["datasets"][REGION]["reference"]
                ),
                "independent_calculation": (
                    f"{current_value} - {previous_value} = {difference}"
                ),
            },
        )

    async def rewrite(self, state, role, task, frame):
        state = await self.interpret(state, role, task, frame)
        state = await self.decide(
            state,
            role,
            "compose",
            "이전 실제 답변에 점수의 정의와 개인 상태를 판단할 수 없다는 한계가 "
            "모두 있다. 사용자는 같은 의미의 짧은 재작성만 요청했고 "
            "새 수치·비교를 제외했으므로 추가 근거가 필요하지 않다.",
            frame,
        )
        return await self.step(
            "compose",
            role,
            state,
            {
                "content": "행동 이상 점수는 기준으로 학습한 행동과 다른 정도를 "
                "보여줍니다. 실제 활동량이나 개인의 고립 상태를 확인한 값은 아닙니다.",
                "artifact_ids": [],
                "status": "completed",
                "reason": "이전 대화에 있는 정의·한계를 쉬운 두 문장으로 줄이고 "
                "새 사실이나 수치를 추가하지 않는다.",
            },
            frame=frame,
            reference={
                "evidence_origin": "messages: 이전 AI 답변",
                "required_meanings": [
                    "학습 기준 행동과의 차이",
                    "실제 활동량이나 개인의 고립 상태를 뜻하지 않음",
                ],
                "excluded_claims": ["새 수치", "기간 비교", "새 원인·해석"],
            },
        )

    def view_parameters(self, view):
        if self.catalog["views"][view]["input_profile"] == "monthly_city":
            return {
                "p_city": self.city_code,
                "p_start": self.month + "-01",
                "p_end": self.month + "-01",
            }
        return deepcopy(self.parameters)

    async def visualization(self, state, task, *, frame="root"):
        role = "visualization"
        state = await self.interpret(state, role, task, frame)
        charts = []
        for index, view in enumerate(task["views"]):
            title = self.catalog["views"][view]["title"]
            if index:
                need = (
                    "상세 지도 설정과 산출물은 확보했다. 그러나 전체 요청에는 "
                    "행동 지표 기여도 차트도 포함되어 그 표시 조건 검사와 "
                    "산출물이 추가로 필요하다."
                )
            elif task["kind"] == "city_map":
                need = (
                    "새 요청은 특정 동의 행동 상세 지도가 아니라 도시 전체의 "
                    "현재 월 배경 취약성 지도이다. 대상·월·목적은 확정됐고 "
                    "그 범위에 맞는 표시 조건 검사와 산출물이 필요하다."
                )
            else:
                need = (
                    "요청한 동·월·상세 지도 목적은 확정됐지만 이번 조건의 "
                    "검사 결과와 산출물은 없다. 현재 요청 조건으로 "
                    "표시 설정을 검사해야 한다."
                )
            state = await self.decide(state, role, "act", need, frame)
            state = await self.act(
                state,
                role,
                "validate_visualization",
                {"view_key": view, "parameters": self.view_parameters(view)},
                f"{title} 목적에 맞는 등록 뷰와 이번 지역·월의 표시 조건을 검사한다.",
                frame,
            )
            chart = _last_call(state, "validate_visualization")
            assert chart["outcome"] == "success" and chart["output"]["valid"] is True
            charts.append(chart)
        state = await self.decide(
            state,
            role,
            "compose",
            "요청한 모든 시각화의 지역·월 설정이 등록 기준에 적합하고 "
            "각각의 유효한 Tableau 산출물이 확보됐다. "
            "실제 화면 표시나 자료 최신성을 확인한 것은 아니다.",
            frame,
        )
        area = self.selected["city_name"] + (
            " 전체" if task["kind"] == "city_map" else " " + self.name
        )
        titles = "와 ".join(
            self.catalog["views"][view]["title"] for view in task["views"]
        )
        return await self.step(
            "compose",
            role,
            state,
            {
                "content": f"{area}의 {self.month} {titles} Tableau 표시 설정을 "
                f"제공합니다. {VISUAL_LIMIT}",
                "artifact_ids": [chart["id"] for chart in charts],
                "status": "completed",
                "reason": "요청한 각 시각화의 유효한 산출물을 모두 선택하고 "
                "적용 조건·확인 한계를 반환한다.",
            },
            frame=frame,
            reference={
                "required_source": "Tableau",
                "required_limitations": [VISUAL_LIMIT],
                "tool_transfer": True,
                "verification_scope": "registered_configuration",
                "requested_views": task["views"],
                "configurations": [
                    {"view_key": view, "parameters": self.view_parameters(view)}
                    for view in task["views"]
                ],
            },
        )

    async def request(self, state, task):
        role, frame = "request", "root"
        if task["kind"] == "rewrite":
            return await self.rewrite(state, role, task, frame)
        visual = task["kind"] == "detail_map"
        specialist = "visualization" if visual else "interpretation"
        state = await self.interpret(state, role, task, frame)
        state = await self.decide(
            state,
            role,
            "act",
            "새 요청의 지역·월·상세 지도 목적은 확인됐지만 "
            "표시 조건 검사와 산출물이 없다. 시각화 전문 작업으로 보완해야 한다."
            if visual
            else "지역·두 달 비교 목적은 확인됐지만 실제 점수·차이 근거가 없다. "
            "자료 조회·계산을 포함한 해석 전문 작업이 필요하다.",
            frame,
        )

        async def child_plan(child_role, child_state):
            assert child_role == specialist
            return await getattr(self, specialist)(
                child_state, task, frame="child-" + specialist
            )

        semantics = {
            "region": {"code": self.code, "name": self.name},
            "periods": {"current": self.month},
            "purpose": "상세 지도 표시 설정과 산출물 제공"
            if visual
            else "행동 이상 점수의 현재 월과 전월 비교",
            "required_details": ["표시 조건", "설정 검사와 실제 표시 확인의 한계"]
            if visual
            else ["자료 출처", "해석 한계"],
        }
        if not visual:
            semantics.update(
                measure="행동 이상 점수",
                comparison="현재 월과 전월을 비교하고 점수 차이를 설명한다.",
            )
            semantics["periods"]["previous"] = self.previous
        state = await self.act(
            state,
            role,
            specialist + "_agent",
            {"goal": state["request"]["goal"]},
            "확인된 동·월·상세 지도 목적과 적용 조건·한계 요구를 "
            "시각화 전문 에이전트에 전달한다."
            if visual
            else "확인된 동·두 달·점수 비교 목적과 출처·한계 요구를 "
            "해석 전문 에이전트에 전달한다.",
            frame,
            child_plan=child_plan,
            reference={"goal_semantics": semantics},
        )
        call = _last_call(state, specialist + "_agent")
        child = call["output"]
        assert child["execution"]["status"] == "completed"
        difference = (
            None
            if visual
            else _last_call(child, "process_data")["output"]["data"]["rows"][0][
                "bh_change"
            ]
        )
        state = await self.decide(
            state,
            role,
            "compose",
            "하위 반환에 요청한 동·월의 검사된 상세 지도 산출물과 "
            "표시 조건·확인 한계가 모두 있어 그대로 통합할 수 있다."
            if visual
            else "하위 반환에 두 달 점수·차이·출처·해석 한계가 모두 포함되어 "
            "최종 답변으로 통합할 수 있다.",
            frame,
        )
        ref = {
            "child_transfer": True,
            "child_content": child["response"]["content"],
            "required_source": "Tableau" if visual else "public[.]region_result",
            "required_limitations": [VISUAL_LIMIT if visual else LIMIT],
        }
        if visual:
            ref.update(
                verification_scope="registered_configuration",
                requested_views=task["views"],
                child_artifacts=deepcopy(child["response"]["artifacts"]),
            )
        else:
            ref["observations"] = {"difference": difference}
        state = await self.step(
            "compose",
            role,
            state,
            {
                "content": child["response"]["content"],
                "artifact_ids": [call["id"]] if visual else [],
                "status": "completed",
                "reason": "하위의 의미·출처·한계와 요청한 시각화 산출물을 "
                "보존해 최종 답변을 반환한다."
                if visual
                else "하위의 관측값·의미·출처·한계를 보존해 최종 답변을 반환한다.",
            },
            numeric=difference,
            reference=ref,
        )
        assert state["response"]["artifacts"] == child["response"]["artifacts"]
        return state

    async def delegated(self, role, task, initial):
        """Prepare an actual parent call, recording only its child as eval cases."""
        parent = PathRecorder(self.snapshot)
        parent.begin(
            "preparation-" + self.recorder.current["id"],
            "독립 전문 에이전트 평가의 실제 상위 위임 준비",
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
        if task["kind"] == "comparison":
            need = (
                "요청한 동·두 비교 월과 출처·해석 한계 요구는 확인됐다. "
                "두 달의 실제 점수와 차이 계산 근거가 없어 전문 해석 작업이 필요하다."
            )
        elif task["kind"] == "current_score":
            need = (
                "새 요청의 동·현재 월은 확인됐지만 실제 점수와 그 값을 설명할 "
                "근거가 없다. 전월 비교 없이 현재 값의 전문 해석이 필요하다."
            )
        else:
            need = (
                "요청한 지역·월과 시각화 목적은 확인됐지만 요청한 각 표시 설정의 "
                "검사 결과와 산출물이 없다. 시각화 전문 작업이 필요하다."
            )
        state = await parent.step(
            "decide",
            "request",
            state,
            [{"next": "act", "reason": need}],
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
                    "reason": "확정한 대상·기간·목적·조건을 해당 전문 에이전트에 "
                    "전달해 부족한 근거와 요청 산출물을 확보한다.",
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
        task = self.task(role, condition)
        initial = self.initial(role, condition, task)
        self.recorder.begin(
            f"basic-{role}-{condition}",
            f"{ROLE_LABELS[role]} · {CONDITION_LABELS[condition]}",
            "user_request",
            f"basic-{role}",
            axes={"conversation_condition": condition},
            source_groups=[],
        )
        self.recorder.current.update(
            scope="agent",
            agent_role=role,
            conversation_condition=condition,
            region_code=self.city_code if task["kind"] == "city_map" else self.code,
            expected_summary=task["goal"],
            task_rationale=deepcopy(task["rationale"]),
            evidence_refs=[
                {
                    "snapshot": "snapshots/data.json",
                    "dataset": REGION,
                    "reference": deepcopy(
                        self.snapshot["datasets"][REGION]["reference"]
                    ),
                    "adm_cd10": self.code,
                    "months": [self.previous, self.month]
                    if task["kind"] == "comparison"
                    else [self.month],
                },
            ]
            if task["kind"] in {"comparison", "current_score"}
            else [
                {
                    "conversation": "start_state.messages",
                    "message_index": 1,
                    "meaning": "이전 AI 답변의 정의·해석 한계",
                }
            ]
            if task["kind"] == "rewrite"
            else [
                {
                    "catalog": "src/tools/tableau_catalog.json",
                    "view_key": view,
                    "parameters": self.view_parameters(view),
                }
                for view in task["views"]
            ],
        )
        if role == "request":
            state = self.recorder.initial_state(initial)
            state = await self.request(state, task)
        else:
            state = await self.delegated(role, task, initial)
        self.recorder.end(state, terminal="completed")


async def build_basic_user_paths(snapshot: dict, recorder: Recorder) -> None:
    """Regenerate 3 roles × 4 conversation conditions without importing old cases."""
    paths = _BasicUsers(snapshot, recorder)
    for role in ROLES:
        for condition in CONDITIONS:
            await paths.build(role, condition)
