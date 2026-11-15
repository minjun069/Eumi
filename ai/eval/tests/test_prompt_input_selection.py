"""모든 검사에서 실제 호출 입력 전체가 판정 프롬프트까지 손실 없이 전달된다."""

import json
import re
from copy import deepcopy

import pytest

from eval.nodes.inputs import select_inputs
from eval.nodes.llm import _prompt
from eval.nodes.prompt_fields import PROFILES
from eval.tests.test_node_inputs import report_item
from eval.tests.test_prompt_fields import CATALOG, OUTPUTS, ROWS


def raw_values(text):
    return [
        json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, re.S)
    ]


def full_call(name):
    history = [
        report_item("draft", "report_draft", output={"content": "첫 설명"}),
        report_item(
            "review", "verification", output={"accepted": True, "call_id": "draft"}
        ),
        report_item("draft", "report_draft", output={"content": "중복 ID의 다른 설명"}),
        report_item(
            "failed", "report_draft", output={"content": "실패한 설명"}, success=False
        ),
        report_item("unreviewed", "report_draft", output={"content": "미검토 설명"}),
        report_item(
            "review-missing",
            "verification",
            output={"accepted": False, "call_id": "missing"},
        ),
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "[업무 지침]\n행동 이상 점수는 학습 기준 행동과의 차이를 나타낸다. "
                "점수 차이 설명에는 process_data의 계산 기록과 결과 열이 필요하다."
            ),
        },
        {
            "role": "developer",
            "content": "[추가 실행 조건]\n비교 기간과 집계 단위를 확인한다.",
            "extra": {"none": None, "empty": []},
        },
        {
            "type": "human",
            "data": {
                "type": "human",
                "content": "[알려지지 않은 구획]\n"
                + json.dumps({"results": history}, ensure_ascii=False),
                "name": "담당자",
            },
        },
        {
            "type": "ai",
            "data": {
                "type": "ai",
                "content": "",
                "tool_calls": [
                    {"name": "process_data", "args": {"value": 0}, "id": "call-tool"}
                ],
            },
        },
        {
            "role": "tool",
            "content": [{"type": "text", "text": "계산 결과 전체"}],
            "tool_call_id": "call-tool",
        },
        {
            "role": "user",
            "content": "두 기간의 점수 차이를 설명해 줘.\n  공백도 보존  ",
        },
    ]
    messages.append(deepcopy(messages[0]))
    return {
        "id": "current",
        "name": name,
        "path": "/trace/spans/1",
        "messages": messages,
        "response_schema": {
            "title": name,
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "판단 이유를 기술한다."}
            },
            "$defs": {"zero": {"enum": [0, False, None, [], {}]}},
        },
        "output": deepcopy(OUTPUTS[name]),
    }


@pytest.mark.parametrize("row_id", ROWS)
def test_every_llm_row_keeps_all_messages_schema_and_original_citation_paths(row_id):
    row = ROWS[row_id]
    assert row["inputs"]["runtime"] == ["모델 호출 입력"]
    assert not row.get("input_scopes")
    for name in PROFILES[row_id]["outputs"]:
        call = full_call(name)
        before = deepcopy(call)
        node = {
            "node": "compose",
            "role": "request",
            "state": {"secret": "UNSENT_STATE_CANARY"},
        }
        evidence = select_inputs(row, node, call, [])
        messages, prompt = _prompt(row, CATALOG, evidence, [{"id": "item"}])
        expected = [*call["messages"], call["response_schema"]]
        assert raw_values(messages[1].content) == expected
        assert [
            entry["value"] for entry in prompt["source_payload"]["evidence"]["inputs"]
        ] == expected
        assert [
            field["value"] for field in prompt["fields"] if field["section"] == "input"
        ] == expected
        assert not evidence["missing_inputs"]
        assert not any(
            path.startswith("/evidence/inputs") for path in prompt["excluded_paths"]
        )
        assert prompt["evidence_mappings"] == []
        for index in range(len(expected)):
            assert prompt["evidence_labels"][f"입력 {index + 1}"] == {
                "path": f"/evidence/inputs/{index}/value",
                "kind": "input",
            }
        assert "UNSENT_STATE_CANARY" not in messages[1].content
        assert "학습 기준 행동" not in messages[0].content
        assert "비교 자료다" in messages[0].content
        assert call == before


def test_answer_metadata_cannot_narrow_override_or_add_to_real_call_inputs():
    row = ROWS["N01-O.2/general"]
    call = full_call("Interpretation")
    node = {"node": "interpret", "role": "request"}
    plain = [{"id": "item"}]
    altered = [
        {
            "id": "item",
            "value": "ORACLE_CANARY",
            "match": "equal",
            "path": "/request/goal",
            "reason": "ORACLE_CANARY",
            "applicable": False,
            "inputs": [
                {"source": "messages", "path": "/5/content", "label": "현재 작업 목표"},
                {"source": "reference", "path": "/secret"},
            ],
        }
    ]
    original_evidence = select_inputs(row, node, call, plain)
    altered_evidence = select_inputs(
        row, node, call, altered, {"secret": "ORACLE_CANARY"}
    )
    assert altered_evidence == original_evidence
    original = _prompt(row, CATALOG, original_evidence, plain)[1]
    changed = _prompt(row, CATALOG, altered_evidence, altered)[1]
    assert changed == original
    assert "ORACLE_CANARY" not in json.dumps(changed)


def test_broken_embedded_json_and_unapproved_history_remain_judge_data():
    row = ROWS["N04-B.1/report-insight"]
    call = full_call("ReportText")
    call["messages"].append({"role": "user", "content": "[작업 이력]\n{broken-json"})
    evidence = select_inputs(
        row, {"node": "compose", "role": "report_insight"}, call, []
    )
    messages, prompt = _prompt(row, CATALOG, evidence, [{"id": "item"}])
    assert not evidence["missing_inputs"]
    inputs = [field for field in prompt["fields"] if field["section"] == "input"]
    assert all(field["status"] == "present" for field in inputs)
    assert raw_values(messages[1].content) == [
        *call["messages"],
        call["response_schema"],
    ]
    history = json.loads(call["messages"][2]["data"]["content"].split("\n", 1)[1])[
        "results"
    ]
    assert [item["id"] for item in history] == [
        "draft",
        "review",
        "draft",
        "failed",
        "unreviewed",
        "review-missing",
    ]
    assert all(
        word in messages[1].content
        for word in ("미검토 설명", "실패한 설명", "중복 ID의 다른 설명", "broken-json")
    )
