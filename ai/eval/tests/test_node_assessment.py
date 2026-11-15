"""노드 평가의 단계 중단·원본 증거·조건·모델 오류 연결을 검증한다."""

import asyncio
import json
import re
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from eval.nodes.assessment import AssessmentCancelled, assess_node
from eval.nodes.criteria import load_criteria
from eval.nodes.schema import validate_node_assessment
from src.agent_nodes import record
from src.prompting import (
    compose_messages,
    interpret_messages,
    report_messages,
    selection_messages,
)
from src.settings import Settings
from src.state import create_state, state_adapter


class JudgeModel:
    def __init__(
        self,
        *,
        verdict="통과",
        error=None,
        evidence_path="출력 1",
    ):
        self.verdict = verdict
        self.error = error
        self.evidence_path = evidence_path
        self.calls = []
        self.prompts = []

    def with_structured_output(self, schema, **options):
        return self

    async def ainvoke(self, messages, config):
        payload = messages[-1].content
        self.calls.append(payload)
        self.prompts.append(messages)
        if self.error:
            raise self.error
        comparison = re.findall(r"^\[(입력 \d+)\]", payload, re.MULTILINE)[:1]
        response = {
            "details": [
                {
                    "id": item,
                    "verdict": self.verdict,
                    "reason": "실행 당시 요청과 실제 출력을 검사 기준으로 대조했다.",
                    "evidence": [self.evidence_path, *comparison],
                }
                for item in re.findall(r"^\[(항목 \d+)\]$", payload, re.MULTILINE)
            ],
            "reason": "요청과 반환값을 대조했다.",
        }
        return {"raw": AIMessage(content=json.dumps(response, ensure_ascii=False))}


@pytest.fixture
def catalog():
    return load_criteria()


@pytest.fixture
def node():
    output = {
        "request": {"goal": "지역의 변화를 설명한다."},
        "reason": "요청 대상을 확인했다.",
    }
    state = create_state(
        output["request"],
        Settings(_env_file=None),
        messages=[HumanMessage("지역의 변화를 설명해줘.")],
        version="test",
        event="user_request",
    )
    messages = interpret_messages(state, "request")
    return {
        "id": "node-1",
        "run_id": "run-1",
        "repetition": 1,
        "occurrence": 1,
        "node": "interpret",
        "role": "request",
        "counted": True,
        "complete": True,
        "state": state_adapter.dump_python(state, mode="json"),
        "issues": [],
        "calls": [
            {
                "id": "model-1",
                "name": "Interpretation",
                "raw": json.dumps(output, ensure_ascii=False),
                "output": output,
                "messages": [message.model_dump(mode="json") for message in messages],
                "response_schema": {"title": "Interpretation"},
                "path": "/trace/spans/1",
                "complete": True,
            }
        ],
    }


@pytest.fixture
def case():
    return {
        "id": "case-1",
        "assessment": {
            "checks": ["N-F.1", "N01-O.2", "N01-O.1", "N-B.1", "N-B.2"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {
                        "id": "required-goal",
                        "check": "N01-O.2",
                        "path": "/request/goal",
                        "value": "지역의 변화를 설명한다.",
                    },
                    {
                        "id": "consistent-goal",
                        "check": "N01-O.1",
                        "value": "지역의 변화를 설명한다.",
                    },
                    {
                        "id": "no-data-reference",
                        "check": "N-B.1",
                        "applicable": False,
                        "reason": "자료를 선택하거나 참조한 출력이 없다.",
                    },
                    {
                        "id": "no-untrusted-instruction",
                        "check": "N-B.2",
                        "applicable": False,
                        "reason": "외부 자료의 명령이 입력에 포함되지 않았다.",
                    },
                ],
            },
        },
    }


def checks(result):
    return {item["check"]: item for item in result["checks"]}


def assert_later_stages_skipped(result, axis, reason):
    for check in result["checks"]:
        if check["axis"] != axis:
            assert check["verdict"] == "미판정"
            assert not check["executed"]
            assert all(not d["executed"] for c in check["calls"] for d in c["details"])
            assert reason in check["reason"]


async def test_format_failure_stops_later_stages_without_model_calls(
    case, node, catalog
):
    node["calls"][0]["raw"] = '{"request":{},"reason":""}'
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    assert result["verdict"] == "실패"
    assert result["complete"]
    assert checks(result)["N-F.1"]["executed"]
    assert_later_stages_skipped(result, "형식 준수", "선행 단계 실패")
    assert not model.calls


@pytest.mark.parametrize("raw,verdict", [(None, "미판정"), ('{"content":', "실패")])
async def test_unfinished_original_blocks_without_using_parsed_output(
    case, node, catalog, raw, verdict
):
    node["calls"][0].update(raw=raw, complete=False)
    node["complete"] = False
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    assert result["verdict"] == verdict
    assert result["complete"] is (verdict == "실패")
    assert checks(result)["N-F.1"]["verdict"] == verdict
    assert_later_stages_skipped(result, "형식 준수", "선행 단계 " + verdict)
    assert not model.calls


async def test_missing_original_even_with_parsed_output_cannot_pass(
    case, node, catalog
):
    node["calls"][0]["raw"] = None
    result = await assess_node(case, node, catalog=catalog, model=JudgeModel())
    assert checks(result)["N-F.1"]["verdict"] == "미판정"
    assert not checks(result)["N-F.1"]["executed"]
    assert result["verdict"] == "미판정"


async def test_required_content_failure_skips_accuracy(case, node, catalog):
    model = JudgeModel(verdict="실패")
    result = await assess_node(case, node, catalog=catalog, model=model)
    assert checks(result)["N-F.1"]["verdict"] == "통과"
    assert checks(result)["N01-O.2"]["verdict"] == "실패"
    assert result["verdict"] == "실패"
    assert result["complete"]
    for check in result["checks"]:
        if check["axis"] == "내용 정확성":
            assert check["reason"] == "선행 단계 실패로 미실행"
            assert not check["executed"]
    assert len(model.calls) == 1


@pytest.mark.parametrize(
    ("condition", "output_condition", "request_text", "accuracy_reason"),
    [
        (
            "preferred",
            "required",
            "A동의 최근 변화를 설명해줘. 가능하면 B동과도 비교해줘.",
            "가능하면 하라는 B동 비교를 필수 조건으로 바꾸어 해석했다.",
        ),
        (
            "required",
            "preferred",
            "A동의 최근 변화를 설명하고 반드시 B동과도 비교해줘.",
            "반드시 하라는 B동 비교를 선호 조건으로 낮추어 해석했다.",
        ),
        (
            "required",
            None,
            "A동의 최근 변화를 설명하고 반드시 B동과도 비교해줘.",
            "B동 비교를 이유에는 인식했지만 정리한 목표·조건에는 보존하지 않았다.",
        ),
    ],
)
async def test_accuracy_uses_original_request_after_required_content_passes(
    case, node, catalog, condition, output_condition, request_text, accuracy_reason
):
    goal = "A동의 최근 변화를 설명한다."
    comparison = "B동과 비교한다."
    original_request = {
        "goal": goal,
        "constraints": {condition: [comparison]},
    }
    output = {
        "request": {"goal": goal},
        "reason": "A동의 변화 설명과 B동 비교가 요청되었다.",
    }
    if output_condition:
        output["request"]["constraints"] = {output_condition: [comparison]}
    state = create_state(
        original_request,
        Settings(_env_file=None),
        messages=[HumanMessage(request_text)],
        version="test",
        event="user_request",
    )
    node["state"] = state_adapter.dump_python(state, mode="json")
    node["calls"][0].update(
        raw=json.dumps(output, ensure_ascii=False),
        output=output,
        messages=[
            message.model_dump(mode="json")
            for message in interpret_messages(state, "request")
        ],
    )
    case["assessment"]["checks"] = ["N-F.1", "N01-O.2", "N01-O.1"]
    case["assessment"]["expected"]["items"] = [
        {
            "id": "required-topics",
            "check": "N01-O.2",
            "value": "AUTHORED_COVERAGE_ANSWER_MUST_NOT_REACH_JUDGE",
        },
        {
            "id": "optional-comparison",
            "check": "N01-O.1",
            "value": "AUTHORED_ACCURACY_ANSWER_MUST_NOT_REACH_JUDGE",
        },
    ]
    inclusion_reason = "포함 검사에서는 A동 설명과 B동 비교 내용이 모두 확인됐다."

    class InclusionThenAccuracy(JudgeModel):
        async def ainvoke(self, messages, config):
            first = not self.calls
            self.verdict = "통과" if first else "실패"
            returned = await super().ainvoke(messages, config)
            response = json.loads(returned["raw"].content)
            reason = inclusion_reason if first else accuracy_reason
            response["reason"] = reason
            for detail in response["details"]:
                detail["reason"] = reason
            returned["raw"] = AIMessage(
                content=json.dumps(response, ensure_ascii=False)
            )
            return returned

    model = InclusionThenAccuracy()
    result = await assess_node(case, node, catalog=catalog, model=model)
    results = checks(result)
    required, accuracy = results["N01-O.2"], results["N01-O.1"]
    assert results["N-F.1"]["verdict"] == required["verdict"] == "통과"
    assert accuracy["verdict"] == result["verdict"] == "실패"
    assert required["executed"] and accuracy["executed"] and result["complete"]
    assert len(model.calls) == 2
    assert required["details"][0]["reason"] == inclusion_reason
    assert accuracy["details"][0]["reason"] == accuracy_reason
    assert required["related_checks"] == accuracy["related_checks"] == []
    required_prompt = required["calls"][0]["judge"]["prompt"]
    delivered_output = {
        field["path"]: field.get("value")
        for field in required_prompt["fields"]
        if field["section"] == "output"
    }
    assert delivered_output["/evidence/call/output/reason"] == output["reason"]

    accuracy_prompt = accuracy["calls"][0]["judge"]["prompt"]
    sent = "\n".join(message.content for message in model.prompts[1])
    assert all(
        "MUST_NOT_REACH_JUDGE" not in message.content
        for messages in model.prompts
        for message in messages
    )
    assert request_text in sent and output["reason"] in sent
    assert comparison in sent and "필수 조건" in sent
    assert inclusion_reason not in sent
    assert "기존 판정의 재사용" not in sent
    for key in ("payload", "source_payload"):
        assert "related_results" not in accuracy_prompt[key]["assessment"]
    assert accuracy_prompt["source_payload"]["evidence"]["call"]["output"] == output
    assert not any(
        label["path"].startswith("/assessment/related_results/")
        for label in accuracy_prompt["evidence_labels"].values()
    )


async def test_rules_only_leaves_required_llm_unknown_and_blocks_accuracy(
    case, node, catalog
):
    result = await assess_node(case, node, catalog=catalog, method="rules")
    assert checks(result)["N-F.1"]["verdict"] == "통과"
    assert checks(result)["N01-O.2"]["verdict"] == "미판정"
    assert not checks(result)["N01-O.2"]["executed"]
    assert checks(result)["N01-O.1"]["reason"] == "선행 단계 미판정으로 미실행"
    assert not result["complete"]


async def test_changed_rule_source_blocks_before_any_rule_or_model_execution(
    case, node, catalog
):
    catalog["checks"]["N-F.1"]["text"] += " 변경된 형식 조건"
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    format_check = checks(result)["N-F.1"]
    assert format_check["verdict"] == "미판정"
    assert not format_check["executed"]
    assert "기준 문서가 구현 버전과 다릅니다" in format_check["reason"]
    assert_later_stages_skipped(result, "형식 준수", "선행 단계 미판정")
    assert not model.calls


async def test_rule_nonapplication_does_not_skip_llm_judgment(case, node, catalog):
    model = JudgeModel()
    before = deepcopy((case, node, catalog))
    result = await assess_node(case, node, catalog=catalog, model=model)
    assert result["verdict"] == "통과"
    assert result["complete"]
    assert checks(result)["N-B.1"]["verdict"] == "비적용"
    assert checks(result)["N-B.2"]["verdict"] == "통과"
    assert checks(result)["N-B.2"]["executed"]
    assert checks(result)["N-B.1"]["executed"]
    assert checks(result)["N01-O.1"]["verdict"] == "통과"
    assert len(model.calls) == 3
    assert (case, node, catalog) == before


async def test_authored_nonapplication_does_not_exclude_llm_check(case, node, catalog):
    case["assessment"]["expected"]["items"][0].update(
        applicable=False, reason="평가에서 빼고 싶다."
    )
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    required = checks(result)["N01-O.2"]
    assert required["verdict"] == "통과"
    assert required["executed"]
    assert len(model.calls) == 3
    assert all("평가에서 빼고 싶다." not in prompt for prompt in model.calls)


async def test_checks_only_llm_assessment_does_not_require_expected_items(
    case, node, catalog
):
    case["assessment"] = {"checks": ["N01-O.2"]}
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    judged = checks(result)["N01-O.2"]
    assert result["verdict"] == judged["verdict"] == "통과"
    assert result["complete"] and judged["executed"]
    assert len(model.calls) == 1
    assert judged["details"][0]["id"] == "N01-O.2"
    assert "기대" not in model.calls[0]


async def test_legacy_answer_material_does_not_change_selected_evidence_or_prompt(
    case, node, catalog
):
    case["assessment"] = {
        "checks": ["N01-O.2"],
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [{"id": "stable-item", "check": "N01-O.2"}],
        },
    }
    model = JudgeModel()
    plain = await assess_node(case, node, catalog=catalog, model=model)
    enriched = deepcopy(case)
    oracle = "LEGACY_ORACLE_MUST_NOT_REACH_JUDGE"
    enriched["assessment"]["expected"]["items"][0].update(
        value={"answer": oracle},
        path="/" + oracle,
        match="absent",
        pattern=oracle,
        extract="text",
        applicable=False,
        reason=oracle,
        tolerance={"absolute": 123},
        inputs=[{"source": "reference", "label": "기준 자료", "path": "/" + oracle}],
    )
    enriched["assessment"].update(
        reference={"N01-O.2": {oracle: "독립 기준으로 쓰지 않을 자료"}},
        tolerance={"N01-O.2": {"absolute": 456}},
    )
    original = deepcopy(enriched)
    with_oracle = await assess_node(enriched, node, catalog=catalog, model=model)
    assert plain["verdict"] == with_oracle["verdict"] == "통과"
    assert len(model.calls) == 2 and model.prompts[0] == model.prompts[1]
    plain_call = checks(plain)["N01-O.2"]["calls"][0]
    oracle_call = checks(with_oracle)["N01-O.2"]["calls"][0]
    assert plain_call["judge"]["prompt"] == oracle_call["judge"]["prompt"]
    assert oracle not in json.dumps(oracle_call["judge"], ensure_ascii=False)
    assert oracle_call["details"][0]["id"] == "stable-item"
    assert all(
        path.startswith("/evidence/") for path in oracle_call["details"][0]["evidence"]
    )
    assert all(
        label["kind"] in {"input", "output"}
        for label in oracle_call["judge"]["prompt"]["evidence_labels"].values()
    )
    assert enriched == original


@pytest.mark.parametrize("scope", [{"call": "MissingCall"}, {"call_index": 2}])
async def test_expected_call_scope_absence_remains_unknown(case, node, catalog, scope):
    case["assessment"]["checks"] = ["N01-O.2"]
    case["assessment"]["expected"]["items"][0].update(scope)
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    required = checks(result)["N01-O.2"]
    assert required["verdict"] == "미판정"
    assert required["calls"] == []
    assert required["details"][0]["id"] == "required-goal"
    assert "지정한 모델 호출" in required["details"][0]["reason"]
    assert not model.calls


async def test_evaluator_error_is_unknown_and_saved_with_attempt_evidence(
    case, node, catalog
):
    model = JudgeModel(error=RuntimeError("private model response"))
    result = await assess_node(case, node, catalog=catalog, model=model)
    required = checks(result)["N01-O.2"]
    assert required["verdict"] == "미판정"
    assert required["executed"]
    assert required["calls"][0]["judge"]["error"] == {"type": "RuntimeError"}
    assert (
        required["calls"][0]["judge"]["prompt"]["messages"][1]["content"]
        == model.calls[0]
    )
    assert checks(result)["N01-O.1"]["reason"] == "선행 단계 미판정으로 미실행"
    assert "private model response" not in json.dumps(result)
    assert not result["complete"]


async def test_requested_subset_has_only_requested_results(case, node, catalog):
    case["assessment"]["checks"] = ["N-F.1", "N01-O.2"]
    result = await assess_node(case, node, catalog=catalog, model=JudgeModel())
    assert checks(result)["N-F.1"]["verdict"] == "통과"
    assert checks(result)["N01-O.2"]["verdict"] == "통과"
    assert set(checks(result)) == {"N-F.1", "N01-O.2"}
    assert result["verdict"] == "통과"
    assert result["complete"]


async def test_failure_does_not_hide_unknown_in_same_item_across_calls(
    case, node, catalog
):
    class FailThenError(JudgeModel):
        async def ainvoke(self, messages, config):
            if self.calls:
                raise TimeoutError("second judgment unavailable")
            return await super().ainvoke(messages, config)

    second = deepcopy(node["calls"][0])
    second.update(id="model-2", path="/trace/spans/2")
    node["calls"].append(second)
    result = await assess_node(
        case, node, catalog=catalog, model=FailThenError(verdict="실패")
    )
    required = checks(result)["N01-O.2"]
    assert required["verdict"] == "실패"
    assert required["details"][0]["verdict"] == "실패"
    assert [call["details"][0]["verdict"] for call in required["calls"]] == [
        "실패",
        "미판정",
    ]
    assert required["calls"][1]["judge"]["error"]["type"] == "TimeoutError"
    assert result["verdict"] == "실패"
    assert not result["complete"]


async def test_judge_reason_cannot_disguise_executed_unknown_as_stage_skip(
    case, node, catalog
):
    class FailThenUnknown(JudgeModel):
        async def ainvoke(self, messages, config):
            self.verdict = "미판정" if self.calls else "실패"
            result = await super().ainvoke(messages, config)
            payload = json.loads(result["raw"].content)
            for detail in payload["details"]:
                detail["reason"] = "선행 단계 실패로 미실행"
            result["raw"] = AIMessage(content=json.dumps(payload, ensure_ascii=False))
            return result

    case["assessment"]["checks"] = ["N01-O.2"]
    node["calls"].append({**deepcopy(node["calls"][0]), "id": "second"})
    result = await assess_node(case, node, catalog=catalog, model=FailThenUnknown())
    assert result["verdict"] == "실패"
    assert checks(result)["N01-O.2"]["calls"][1]["details"][0]["executed"]
    assert not result["complete"]


async def test_cancellation_preserves_future_call_scoped_expectations(
    case, node, catalog
):
    items = case["assessment"]["expected"]["items"]
    required = items.pop(0)
    items[:0] = [
        {**required, "id": "first-call", "call_index": 1},
        {**required, "id": "third-call", "call_index": 3},
    ]
    first = node["calls"][0]
    node["calls"].extend(
        {**deepcopy(first), "id": f"model-{index}", "path": f"/trace/spans/{index}"}
        for index in (2, 3)
    )
    with pytest.raises(AssessmentCancelled) as caught:
        await assess_node(
            case,
            node,
            catalog=catalog,
            model=JudgeModel(error=asyncio.CancelledError()),
        )
    result = caught.value.assessment
    required_result = checks(result)["N01-O.2"]
    by_id = {item["id"]: item for item in required_result["details"]}
    assert set(by_id) == {"first-call", "third-call"}
    assert all(item["verdict"] == "미판정" for item in by_id.values())
    assert not by_id["third-call"]["executed"]
    assert required_result["calls"][0]["id"] == first["id"]
    assert required_result["calls"][0]["details"][0]["id"] == "first-call"
    assert required_result["calls"][0]["details"][0]["verdict"] == "미판정"
    assert checks(result)["N-F.1"]["verdict"] == "통과"
    assert not result["complete"]


@pytest.mark.parametrize(
    "node_name,role,call_name,required_check,target,output",
    [
        (
            "act",
            "interpretation",
            "Selection",
            "N02-O.2",
            "N02-B.2",
            {
                "name": "interpretation_agent",
                "arguments_json": '{"goal":"자료 설명"}',
                "reason": "자료 설명을 요청한다.",
            },
        ),
        (
            "compose",
            "request",
            "Composition",
            "N04-O.1",
            "N04-O.2",
            {
                "content": "확인한 내용을 설명한다.",
                "artifact_ids": ["missing-artifact"],
                "status": "completed",
                "reason": "산출물을 제공한다.",
            },
        ),
    ],
)
async def test_false_nonapplication_cannot_hide_observed_rule_violation(
    case, node, catalog, node_name, role, call_name, required_check, target, output
):
    state = state_adapter.validate_python(node["state"])
    if node_name == "act":
        state["results"].append(
            record(
                "decide",
                "decision",
                "요청을 설명할 지역 자료를 확보해야 한다.",
                output={
                    "next": "act",
                    "reason": "요청을 설명할 지역 자료를 확보해야 한다.",
                },
            )
        )
        messages = selection_messages(
            state,
            role,
            {},
            definitions=[
                {
                    "type": "function",
                    "function": {
                        "name": "query_data",
                        "description": "자료 조회",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )
    else:
        messages = compose_messages(state, role)
    node.update(node=node_name, role=role)
    node["calls"][0].update(
        name=call_name,
        output=output,
        raw=json.dumps(output, ensure_ascii=False),
        messages=[message.model_dump(mode="json") for message in messages],
        response_schema={"title": call_name},
    )
    case["assessment"]["expected"]["items"] = [
        {"id": "required", "check": required_check, "value": "요청 이유와 필요한 설명"},
        {
            "id": "no-material-limit",
            "check": "N-O.5",
            "applicable": False,
            "reason": "자료를 해석하는 문장이 없다.",
        },
        {
            "id": "declared-inapplicable",
            "check": target,
            "applicable": False,
            "reason": "사례에서는 호출·산출물 선택을 기대하지 않는다.",
        },
    ]
    case["assessment"]["checks"] = ["N-F.1"] + [
        item["check"] for item in case["assessment"]["expected"]["items"]
    ]
    result = await assess_node(
        case,
        node,
        catalog=catalog,
        model=JudgeModel(evidence_path="출력 1"),
    )
    checked = checks(result)
    assert checked["N-F.1"]["verdict"] == "통과"
    assert checked[required_check]["verdict"] == "통과"
    target_result = checked[target]
    assert target_result["executed"]
    assert target_result["verdict"] == "실패"
    by_id = {item["id"]: item for item in target_result["details"]}
    assert by_id["declared-inapplicable"]["verdict"] == "미판정"
    violation = "role-scope" if node_name == "act" else "artifact/0"
    assert by_id[violation]["verdict"] == "실패"
    assert result["verdict"] == "실패"
    assert not result["complete"]


def insight_node(node):
    approved = record(
        "compose",
        "report_draft",
        "설명 작성",
        action={
            "name": "write_report",
            "arguments": {"view_key": "V01", "result_ids": []},
        },
        output={"content": "검토를 통과한 설명"},
    )
    approved["id"] = "approved"
    review = record(
        "compose",
        "verification",
        "설명 검토",
        output={"call_id": "approved", "accepted": True, "reason": "근거 일치"},
    )
    extra = record(
        "act",
        "call",
        "추가 자료",
        output={"data": {"rows": [{"text": "추가 자료의 새 주장"}]}},
    )
    draft = record(
        "compose",
        "report_draft",
        "인사이트 작성",
        action={
            "name": "write_report",
            "arguments": {"view_key": None, "result_ids": ["approved"]},
        },
        success=False,
    )
    state = deepcopy(node["state"])
    state["request"] = {"goal": "핵심 요약"}
    state["results"] = [approved, review, extra, draft]
    sent = report_messages(state, "draft", {}, role="report_insight")
    writing = deepcopy(node["calls"][0])
    writing.update(
        name="ReportText",
        output={"content": "승인된 내용의 요약"},
        raw=json.dumps({"content": "승인된 내용의 요약"}, ensure_ascii=False),
        messages=[message.model_dump(mode="json") for message in sent],
    )
    reviewing = deepcopy(writing)
    reviewing.update(
        id="review-call",
        name="Verification",
        output={"accepted": True, "reason": "검토"},
        raw=json.dumps({"accepted": True, "reason": "검토"}, ensure_ascii=False),
    )
    for call in (writing, reviewing):
        call["raw"] = json.dumps(call["output"], ensure_ascii=False)
    node.update(node="compose", role="report_insight", calls=[writing, reviewing])
    return node


async def test_insight_row_receives_full_inputs_and_skips_other_call_type(
    case, node, catalog
):
    catalog["checks"] = {"N04-B.1": catalog["checks"]["N04-B.1"]}
    case["assessment"] = {
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [
                {
                    "id": "approved-summary",
                    "check": "N04-B.1",
                    "value": "승인된 설명 요약",
                },
            ],
        },
        "tolerance": {"N04-B.1": {"absolute": 0}},
    }
    model = JudgeModel(evidence_path="출력 1")
    actual_node = insight_node(node)
    result = await assess_node(case, actual_node, catalog=catalog, model=model)
    judged = checks(result)["N04-B.1"]
    assert judged["verdict"] == "통과"
    assert len(model.calls) == 1
    assert judged["calls"][0]["row_id"] == "N04-B.1/report-insight"
    assert judged["calls"][1]["details"][0]["verdict"] == "비적용"
    sent = model.calls[0]
    assert "missing_inputs" not in sent
    assert "추가 자료의 새 주장" in sent
    prompt = judged["calls"][0]["judge"]["prompt"]
    assert [
        entry["value"]
        for entry in prompt["payload"]["evidence"]["inputs"]
        if entry["source"] == "messages"
    ] == actual_node["calls"][0]["messages"]
    system = model.prompts[0][0].content
    assert "N04-B.1/report-insight" not in system
    assert "퀵 인사이트" in system
    assert "N04-B.1/report-selection" not in system


async def test_explicit_expectation_for_excluded_review_is_unjudged(
    case, node, catalog
):
    catalog["checks"] = {"N04-B.1": catalog["checks"]["N04-B.1"]}
    case["assessment"]["checks"] = ["N04-B.1"]
    case["assessment"]["expected"]["items"] = [
        {
            "id": "wrong-call",
            "check": "N04-B.1",
            "call": "Verification",
            "value": "검토 출력",
        },
    ]
    model = JudgeModel(evidence_path="출력 1")
    result = await assess_node(case, insight_node(node), catalog=catalog, model=model)
    assert checks(result)["N04-B.1"]["verdict"] == "미판정"
    assert not model.calls
    case["assessment"]["expected"]["items"][0].update(
        applicable=False, reason="사례에서 비적용으로 선언한 조건"
    )
    declared_inactive = await assess_node(
        case, insight_node(node), catalog=catalog, model=model
    )
    assert declared_inactive == result
    assert not model.calls


async def test_raw_output_can_pass_after_runtime_or_state_update_failure(
    case, node, catalog
):
    node.update(complete=False, state={}, issues=["노드 종료·상태 반영 없음"])
    node["calls"][0].update(
        complete=False, status="error", error={"type": "RuntimeError"}
    )
    result = await assess_node(case, node, catalog=catalog, model=JudgeModel())
    assert result["verdict"] == "통과"
    assert result["complete"]


async def test_raw_is_the_only_output_used_even_without_format_check(
    case, node, catalog
):
    case["assessment"]["checks"] = ["N01-O.2"]
    node["calls"][0]["output"] = {"request": {"goal": "후처리한 다른 내용"}}
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    assert set(checks(result)) == {"N01-O.2"}
    assert result["verdict"] == "통과"
    assert "지역의 변화를 설명한다." in model.calls[0]
    assert "후처리한 다른 내용" not in model.calls[0]
    node["calls"][0]["raw"] = "not JSON"
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    assert result["verdict"] == "미판정"
    assert not model.calls


async def test_format_scope_keeps_original_call_index_and_excludes_other_calls(
    case, node, catalog
):
    case["assessment"] = {
        "checks": ["N-F.1"],
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [
                {"id": "third", "check": "N-F.1", "call_index": 3},
            ],
        },
    }
    first = deepcopy(node["calls"][0])
    first.update(id="bad", raw="not JSON", index=1)
    node["calls"][0]["index"] = 3
    node["calls"].insert(0, first)
    result = await assess_node(case, node, catalog=catalog, method="rules")
    assert result["verdict"] == "통과"
    assert [(c["id"], c["index"]) for c in checks(result)["N-F.1"]["calls"]] == [
        ("model-1", 3)
    ]


async def test_format_failure_of_one_call_does_not_block_another_call(
    case, node, catalog
):
    case["assessment"]["checks"] = ["N-F.1", "N01-O.2"]
    second = deepcopy(node["calls"][0])
    second.update(id="second", path="/trace/spans/2")
    node["calls"][0]["raw"] = "not JSON"
    node["calls"].append(second)
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    required = checks(result)["N01-O.2"]
    assert [(c["id"], c["details"][0]["verdict"]) for c in required["calls"]] == [
        ("model-1", "미판정"),
        ("second", "통과"),
    ]
    assert required["calls"][0]["details"][0]["reason"] == "선행 단계 실패로 미실행"
    assert len(model.calls) == 1
    assert result["verdict"] == "실패"
    assert result["complete"]


async def test_no_requested_checks_does_not_invent_assessments(case, node, catalog):
    case["assessment"]["checks"] = []
    model = JudgeModel()
    result = await assess_node(case, node, catalog=catalog, model=model)
    assert result["checks"] == []
    assert result["verdict"] == "미판정"
    assert not model.calls


async def test_selected_format_row_keeps_full_catalog_rule_guard(case, node, catalog):
    case["assessment"] = {"checks": ["N-F.1"]}
    result = await assess_node(
        case, node, catalog=catalog, method="rules", row_ids=["N-F.1/interpret"]
    )
    assert result["verdict"] == "통과"
    assert checks(result)["N-F.1"]["calls"][0]["row_id"] == "N-F.1/interpret"


async def test_known_row_mismatch_does_not_call_judge(case, node, catalog):
    model = JudgeModel()
    result = await assess_node(
        case, node, catalog=catalog, model=model, row_ids=["N-F.1/decide"]
    )
    assert result["checks"] == []
    assert result["verdict"] == "미판정"
    assert not model.calls


async def test_expectations_bound_to_other_row_are_not_sent_or_marked_missing(
    case, node, catalog
):
    case["assessment"] = {
        "checks": ["N04-B.1"],
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [
                {
                    "id": "summary",
                    "check": "N04-B.1",
                    "row_id": "N04-B.1/report-insight",
                    "value": "승인된 설명 요약",
                },
                {
                    "id": "description",
                    "check": "N04-B.1",
                    "row_id": "N04-B.1/report-description",
                    "value": "설명",
                },
            ],
        },
        "tolerance": {"N04-B.1": {"absolute": 0}},
    }
    model = JudgeModel(evidence_path="출력 1")
    result = await assess_node(case, insight_node(node), catalog=catalog, model=model)
    judged = checks(result)["N04-B.1"]
    assert judged["verdict"] == "통과"
    assert [item["id"] for item in judged["details"]] == ["summary"]
    assert len(model.calls) == 1
    assert re.findall(r"^\[(항목 \d+)\]$", model.calls[0], re.MULTILINE) == ["항목 1"]


async def test_row_filter_keeps_missing_tool_condition_unjudged(case, node, catalog):
    case["assessment"] = {"checks": ["N-F.1"]}
    node.update(node="act", role="request")
    node["calls"][0].update(name="Selection", raw=None, output=None)
    result = await assess_node(
        case,
        node,
        catalog=catalog,
        method="rules",
        row_ids=["N-F.1/act-visualization"],
    )
    assert result["verdict"] == "미판정"
    assert "실행 증거가 부족" in checks(result)["N-F.1"]["reason"]


def test_row_binding_must_belong_to_its_check():
    with pytest.raises(ValueError, match="해당 검사의 평가 행"):
        validate_node_assessment(
            {
                "expected": {
                    "schema_version": "node-expectations-v1",
                    "items": [
                        {
                            "id": "wrong-owner",
                            "check": "N-F.1",
                            "row_id": "N01-O.2/general",
                        }
                    ],
                }
            }
        )
