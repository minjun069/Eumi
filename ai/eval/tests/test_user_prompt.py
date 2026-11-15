"""전체 실행 입력의 보존·인용과 별도 기대답안의 비노출을 확인한다."""

import json
import re
from copy import deepcopy

import pytest
from langchain_core.messages import messages_to_dict

from eval.nodes.criteria import load_criteria, select_rows
from eval.nodes.inputs import select_inputs
from eval.nodes.llm import _prompt, _system_prompt, evaluate_llm
from eval.tests.test_node_inputs import report_item
from eval.tests.test_node_llm import JudgeModel
from src.prompting import report_messages
from tests.helpers import initial

pytestmark = pytest.mark.usefixtures("all_tableau_views")

APPROVED = "한빛동의 2026년 10월 사회적 고립 위험 신호는 9월보다 증가했다."
OUTPUT = APPROVED + " 이 변화는 교통 부족 때문에 발생했다."


def insight(check="N04-B.1"):
    catalog = load_criteria()
    node = {"node": "compose", "role": "report_insight"}
    definition = select_rows(catalog["checks"][check], node, {"name": "ReportText"})[
        "rows"
    ][0]
    state = initial()
    state["request"] = {
        "goal": "한빛동 2026년 10월 승인 설명의 핵심을 요약한다.",
        "constraints": {"required": ["승인된 설명의 범위 유지"]},
    }
    state["results"] = [
        report_item(
            "설명-17", "report_draft", view="V01", output={"content": APPROVED}
        ),
        report_item(
            "검토-21",
            "verification",
            output={"call_id": "설명-17", "accepted": True, "reason": "적합"},
        ),
        report_item("작성-22", "report_draft", refs=["설명-17"], success=False),
    ]
    call = {
        "id": "model-call",
        "name": "ReportText",
        "path": "/spans/0",
        "messages": messages_to_dict(
            report_messages(state, "draft", {}, role="report_insight")
        ),
        "response_schema": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "핵심 요약"}},
            "required": ["content"],
        },
        "output": {"content": OUTPUT},
    }
    expected = [
        {"id": "summary", "check": check, "value": "10월 신호 증가를 요약한다."}
    ]
    evidence = select_inputs(definition, node, call, expected)
    return catalog, definition, evidence, expected


def test_insight_user_prompt_preserves_all_messages_and_review_history():
    catalog, row, evidence, expected = insight()
    before = deepcopy(evidence)
    messages, prompt = _prompt(row, catalog, evidence, expected)
    system, user = [message.content for message in messages]
    assert system == _system_prompt(row, catalog, evidence)[0]
    assert OUTPUT in user  # 근거 없는 새 주장도 평가 출력에서 그대로 남긴다.
    shown = [
        json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", user, re.S)
    ]
    assert shown == [entry["value"] for entry in evidence["inputs"]]
    assert APPROVED in user
    for identifier in ("설명-17", "검토-21", "작성-22"):
        assert identifier in user
        assert identifier in json.dumps(prompt["source_payload"], ensure_ascii=False)
    assert prompt["evidence_mappings"] == []
    assert not any(
        path.startswith("/evidence/inputs") for path in prompt["excluded_paths"]
    )
    assert (
        prompt["source_payload"]["evidence"]["inputs"]
        == prompt["payload"]["evidence"]["inputs"]
    )
    assert evidence == before


async def test_full_message_citation_restores_the_preserved_input():
    catalog, row, evidence, expected = insight()
    _, prompt = _prompt(row, catalog, evidence, expected)
    alias, original = next(
        (alias, label)
        for alias, label in prompt["evidence_labels"].items()
        if label["kind"] == "input" and label["path"] == "/evidence/inputs/1/value"
    )
    output_alias = next(
        alias
        for alias, label in prompt["evidence_labels"].items()
        if label["kind"] == "output"
    )
    model = JudgeModel(
        {
            "details": [
                {
                    "id": "항목 1",
                    "verdict": "실패",
                    "reason": "승인 설명에 없는 교통 원인을 추가했다.",
                    "evidence": [alias, output_alias],
                }
            ],
            "reason": "승인된 설명과 원본 출력을 대조했다.",
        }
    )
    result = await evaluate_llm(row, catalog, evidence, expected, model=model)
    assert result["executed"] and result["verdict"] == "실패"
    assert original["path"] in result["details"][0]["evidence"]
    assert result["prompt"]["payload"]["evidence"]["inputs"][1] == evidence["inputs"][1]


def test_required_insight_content_uses_actual_approval_without_expected_answer():
    catalog, row, evidence, expected = insight("N04-O.1")
    # 출력에 빠진 내용도 실제 승인 원문을 보고 확인할 수 있어야 한다.
    evidence["call"]["output"] = {"content": "정리할 내용이 없습니다."}
    _, prompt = _prompt(row, catalog, evidence, expected)
    user = prompt["messages"][1]["content"]
    assert expected[0]["value"] not in user
    assert APPROVED in user
    assert APPROVED in json.dumps(prompt["source_payload"], ensure_ascii=False)
    assert "검토-21" in user
    assert "정리할 내용이 없습니다." in user
    assert all(
        label["kind"] != "assessment" for label in prompt["evidence_labels"].values()
    )


async def test_missing_reference_selection_does_not_block_actual_evidence_judgment():
    catalog, row, evidence, expected = insight()
    expected[0]["inputs"] = [
        {"source": "reference", "path": "/missing", "label": "기준 자료"}
    ]
    original = deepcopy(expected)
    _, prompt = _prompt(row, catalog, evidence, expected)
    input_alias = next(
        alias
        for alias, label in prompt["evidence_labels"].items()
        if label["kind"] == "input"
    )
    output_alias = next(
        alias
        for alias, label in prompt["evidence_labels"].items()
        if label["kind"] == "output"
    )
    model = JudgeModel(
        {
            "details": [
                {
                    "id": "항목 1",
                    "verdict": "실패",
                    "reason": "승인 설명에 없는 교통 원인을 추가했다.",
                    "evidence": [input_alias, output_alias],
                }
            ],
            "reason": "실제 승인 설명과 출력을 대조했다.",
        }
    )
    result = await evaluate_llm(row, catalog, evidence, expected, model=model)
    assert result["executed"] and len(model.calls) == 1
    assert result["verdict"] == "실패"
    assert result["details"][0]["id"] == "summary"
    assert result["prompt"]["assessment_fields"] == []
    assert expected == original


def test_prepared_answer_values_cannot_change_prompt_or_leak_into_payload():
    catalog, row, evidence, expected = insight()
    plain = [{"id": expected[0]["id"], "check": row["id"]}]
    expected[0].update(
        value={"answer": "별도정답_전송금지", "reference": "별도근거_전송금지"},
        tolerance={"absolute": 391.25, "relative": 0.875},
        inputs=[
            {"source": "reference", "path": "/private-basis", "label": "기준 자료"}
        ],
        path="/private-output",
        match="equal",
        reason="기대답안해설_전송금지",
    )
    original_expected, original_evidence = deepcopy(expected), deepcopy(evidence)
    baseline_messages, baseline = _prompt(row, catalog, evidence, plain)
    messages, prompt = _prompt(row, catalog, evidence, expected)
    assert messages == baseline_messages
    assert prompt == baseline
    assert prompt["payload"]["assessment"] == {"expectations": [{"id": "summary"}]}
    assert prompt["source_payload"]["assessment"] == prompt["payload"]["assessment"]
    assert prompt["expectation_ids"] == {"항목 1": "summary"}
    assert "[판정 항목]\n[항목 1]" in messages[1].content
    assert "[별도 평가 자료]" not in messages[1].content
    assert all(
        label["kind"] != "assessment" for label in prompt["evidence_labels"].values()
    )
    serialized = json.dumps(prompt, ensure_ascii=False)
    for hidden in (
        "별도정답_전송금지",
        "별도근거_전송금지",
        "기대답안해설_전송금지",
        "/private-basis",
        "/private-output",
        "391.25",
        "0.875",
    ):
        assert hidden not in serialized
    assert expected == original_expected
    assert evidence == original_evidence
