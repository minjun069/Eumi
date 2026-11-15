"""저장된 호출 입력의 전체 원문·순서·응답 형식과 손상 경계를 확인한다."""

import json
from copy import deepcopy

import pytest

from eval.nodes.inputs import select_inputs
from src.agent_nodes import record


def definition():
    return {
        "inputs": {
            "runtime": ["모델 호출 입력"],
            "result": ["모델 반환값"],
            "assessment": [],
        }
    }


def call(messages, **extra):
    return {
        "id": "call-1",
        "name": "Composition",
        "path": "/spans/0",
        "output": {"content": "출력"},
        "messages": messages,
        **extra,
    }


def report_item(identity, decision, *, refs=(), view=None, output=None, success=True):
    item = record(
        "compose",
        decision,
        "기록",
        action={
            "name": "review_report" if decision == "verification" else "write_report",
            "arguments": {"view_key": view, "result_ids": list(refs)},
        },
        output=output,
        success=success,
    )
    item["id"] = identity
    return item


def test_complete_messages_and_schema_preserve_order_duplicates_roles_and_values():
    messages = [
        {
            "type": "system",
            "content": "[업무 지침]\n학습 기준 행동과의 차이다.  ",
            "id": "system-id",
        },
        {"role": "developer", "content": "정의되지 않은 구획도 그대로 제공한다."},
        {
            "type": "human",
            "data": {"content": "전체 요청", "type": "human", "name": "담당자"},
        },
        {
            "type": "ai",
            "content": [],
            "tool_calls": [
                {"name": "query_data", "args": {"limit": 0}, "id": "tool-1"}
            ],
        },
        {
            "role": "tool",
            "content": [{"type": "text", "text": "행 전체"}],
            "tool_call_id": "tool-1",
        },
        {
            "type": "system",
            "content": "[업무 지침]\n학습 기준 행동과의 차이다.  ",
            "id": "system-id",
        },
    ]
    schema = {
        "type": "object",
        "properties": {"value": {"enum": [None, False, 0, [], {}]}},
    }
    original = call(messages, response_schema=schema)
    before = deepcopy(original)
    result = select_inputs(
        definition(), {"node": "compose", "role": "request"}, original, []
    )
    assert not result["missing_inputs"]
    assert [item["value"] for item in result["inputs"]] == [*messages, schema]
    assert [item["path"] for item in result["inputs"]] == [
        *[f"/messages/{i}" for i in range(6)],
        "/response_schema",
    ]
    assert [item["source"] for item in result["inputs"]] == [
        *(["messages"] * 6),
        "response_schema",
    ]
    assert "응답 형식" in result["inputs"][-1]["label"]
    result["inputs"][0]["value"]["content"] = "사본 변경"
    assert original == before


def test_oracle_paths_reference_and_unsent_state_cannot_replace_original_inputs():
    original = call(
        [
            {"role": "system", "content": "온전한 지침"},
            {"role": "user", "content": "온전한 요청"},
        ]
    )
    node = {"node": "compose", "state": {"secret": "미전송 자료"}}
    plain = select_inputs(definition(), node, original, [])
    altered = select_inputs(
        definition(),
        node,
        original,
        [
            {
                "id": "oracle",
                "value": "정답",
                "inputs": [
                    {
                        "source": "messages",
                        "path": "/1/content",
                        "label": "현재 작업 목표",
                    },
                    {"source": "state", "path": "/secret"},
                    {"source": "reference", "path": "/hidden"},
                ],
            }
        ],
        {"hidden": "준비한 정답"},
    )
    assert altered == plain
    assert "미전송 자료" not in json.dumps(altered, ensure_ascii=False)


@pytest.mark.parametrize(
    "messages",
    [
        None,
        [],
        {},
        "broken",
        [None],
        [{"role": "user"}],
        [{"role": 3, "content": "x"}],
        [{"role": "user", "content": 3}],
        [{"type": "human", "data": []}],
    ],
)
def test_missing_or_damaged_messages_are_diagnostic_without_state_fallback(messages):
    original = call(messages)
    before = deepcopy(original)
    result = select_inputs(
        definition(),
        {
            "node": "compose",
            "state": {"messages": [{"role": "user", "content": "대체 금지"}]},
        },
        original,
        [],
    )
    assert result["missing_inputs"]
    assert "대체 금지" not in json.dumps(result, ensure_ascii=False)
    assert original == before


@pytest.mark.parametrize(
    "schema", [None, {}, {"type": "object", "description": "전체 스키마"}]
)
def test_missing_schema_is_not_filled_from_current_code(schema):
    original = call([{"role": "user", "content": "요청"}], response_schema=schema)
    result = select_inputs(definition(), {"node": "compose"}, original, [])
    assert not result["missing_inputs"]
    assert len(result["inputs"]) == (1 if schema is None else 2)
    if schema is not None:
        assert result["inputs"][-1]["value"] == schema


def test_damaged_schema_is_preserved_and_diagnosed():
    original = call([{"role": "user", "content": "요청"}], response_schema=[])
    result = select_inputs(definition(), {"node": "compose"}, original, [])
    assert result["missing_inputs"]
    assert result["inputs"][-1]["value"] == []


def test_report_input_retains_unapproved_failed_unreferenced_and_conflicting_records():
    records = [
        report_item("duplicate", "report_draft", output={"content": "승인 전 초안"}),
        report_item("duplicate", "report_draft", output={"content": "상충한 초안"}),
        report_item(
            "review",
            "verification",
            output={"call_id": "duplicate", "accepted": False, "reason": "거절"},
        ),
        report_item(
            "failed", "call", output={"rows": [{"raw": "별도 자료"}]}, success=False
        ),
    ]
    text = json.dumps(
        {"request": {"goal": "작성"}, "results": records, "views": []},
        ensure_ascii=False,
    )
    original = call(
        [
            {"role": "system", "content": "승인된 설명만 근거로 사용한다."},
            {"role": "user", "content": text},
        ]
    )
    result = select_inputs(
        definition(), {"node": "compose", "role": "report_insight"}, original, []
    )
    assert not result["missing_inputs"]
    assert result["inputs"][1]["value"] == original["messages"][1]
    assert json.loads(result["inputs"][1]["value"]["content"])["results"] == records


def test_input_selection_requires_selected_row():
    with pytest.raises(ValueError, match="평가 행을 선택"):
        select_inputs({"rows": []}, {"node": "compose"}, call([]), [])
