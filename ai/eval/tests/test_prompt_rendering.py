"""전체 입력 JSON의 원문 보존과 출력 가독성·인용 경로를 검증한다."""

import json
import re
from copy import deepcopy

import pytest

from eval.nodes.prompt_rendering import render_prompt


def field(path, value, *, section="input", label="선택한 자료", **extra):
    return {
        "section": section,
        "label": label,
        "path": path,
        "status": "present",
        "value": value,
        **extra,
    }


def test_operational_metadata_is_hidden_and_expectation_ids_are_reversible():
    payload = {
        "evidence": {
            "node": "compose",
            "role": "report_insight",
            "call": {
                "id": "trace-secret",
                "path": "/trace/spans/4",
                "name": "ReportText",
                "output": {"content": "표시할 내용", "hidden": "숨길 내용"},
            },
        },
        "assessment": {
            "expectations": [
                {
                    "id": "original-expectation",
                    "check": "N04-B.1",
                    "row_id": "N04-B.1/report-insight",
                    "node": "compose",
                    "role": "report_insight",
                    "occurrence": 8,
                    "call": "ReportText",
                    "call_index": 7,
                    "path": "/content",
                    "value": "기대하는 내용",
                    "inputs": [{"source": "messages", "path": "/messages/1"}],
                }
            ]
        },
    }
    rendered = render_prompt(
        payload,
        fields=[
            field(
                "/evidence/call/output/content",
                "표시할 내용",
                section="output",
                label="작성한 본문",
            )
        ],
    )
    text = rendered["text"]
    for secret in (
        "trace-secret",
        "/trace/",
        "ReportText",
        "original-expectation",
        "N04-B.1",
        "report_insight",
        "/messages/1",
        "숨길 내용",
        "call_index",
    ):
        assert secret not in text
    assert "[항목 1]" in text and "작성한 본문" in text
    assert "기대하는 내용" not in text
    assert rendered["expectation_ids"] == {"항목 1": "original-expectation"}
    assert all(
        label["path"] != "/evidence/call/output"
        for label in rendered["evidence_labels"].values()
    )


def test_missing_field_and_json_string_projection_preserve_audit_locations():
    payload = {
        "evidence": {"call": {"output": {"arguments_json": '{"view_key":"V01"}'}}}
    }
    fields = [
        field(
            "/evidence/call/output",
            None,
            section="output",
            status="missing",
            missing_path="/evidence/call/output/reason",
        ),
        field(
            "/evidence/call/output/arguments_json",
            "V01",
            section="output",
            json_path="/view_key",
        ),
    ]
    rendered = render_prompt(payload, fields=fields)
    assert "해당 필드가 제공되지 않았습니다" in rendered["text"]
    assert rendered["evidence_labels"]["출력 1"] == {
        "path": "/evidence/call/output",
        "kind": "output",
        "missing_path": "/evidence/call/output/reason",
    }
    assert rendered["evidence_labels"]["출력 2"]["json_path"] == "/view_key"
    assert '{"view_key"' not in rendered["text"]


def test_original_business_ref_is_not_a_generated_reference():
    value = {"$ref": "#/definitions/지역", "id": "business-id"}
    payload = {"evidence": {"inputs": [{"value": value}]}}
    text = render_prompt(payload, fields=[field("/evidence/inputs/0/value", value)])[
        "text"
    ]
    assert "#/definitions/지역" in text and "business-id" in text
    assert "같은 기록" not in text


def test_legacy_related_verdicts_do_not_create_prompt_text_or_citations():
    payload = {
        "assessment": {
            "related_results": [
                {
                    "check": "N-O.5",
                    "title": "전달 내용 보존",
                    "verdict": "실패",
                    "reason": "조건 누락",
                    "details": [
                        {
                            "id": "hidden-detail",
                            "verdict": "실패",
                            "reason": "필수 조건 누락",
                            "evidence": ["/trace/private"],
                        }
                    ],
                }
            ]
        }
    }
    rendered = render_prompt(payload, fields=[])
    assert rendered == {
        "text": "표시할 평가 자료가 없습니다.",
        "evidence_labels": {},
        "expectation_ids": {},
    }


def test_empty_payload_is_recordable():
    assert render_prompt({}, fields=[]) == {
        "text": "표시할 평가 자료가 없습니다.",
        "evidence_labels": {},
        "expectation_ids": {},
    }


@pytest.mark.parametrize("path", ["/next", None])
def test_only_actual_output_enum_is_rendered(path):
    expected = {"id": "one", "value": "act"}
    if path is not None:
        expected["path"] = path
    payload = {
        "evidence": {"call": {"output": {"next": "act"}}},
        "assessment": {"expectations": [expected]},
    }
    text = render_prompt(
        payload, fields=[field("/evidence/call/output/next", "act", section="output")]
    )["text"]
    assert text.count("“작업 수행”") == 1
    assert "“act”" not in text


@pytest.mark.parametrize("path", ["/content", "/data/name"])
def test_only_actual_output_data_strings_are_rendered(path):
    payload = {
        "evidence": {
            "call": {"output": {"content": "act", "data": {"name": "query_data"}}}
        },
        "assessment": {"expectations": [{"id": "one", "path": path, "value": "act"}]},
    }
    text = render_prompt(
        payload,
        fields=[field("/evidence/call/output/content", "act", section="output")],
    )["text"]
    assert text.count("“act”") == 1
    assert "“작업 수행”" not in text


@pytest.mark.parametrize("nested", [True, False])
def test_business_absence_keys_do_not_hide_other_values(nested):
    record = {"section_absent": True, "risk": 99, "reason": "업무 원문 필드"}
    value = [record] if nested else record
    payload = {"evidence": {"inputs": [{"value": value}]}}
    text = render_prompt(payload, fields=[field("/evidence/inputs/0/value", value)])[
        "text"
    ]
    assert "99" in text and "업무 원문 필드" in text
    assert "실행 당시 이 범위가 제공되지 않았습니다" not in text


def test_assessment_data_is_not_rendered():
    value = {"section_absent": True, "risk": 99, "reason": "별도 기준 자료"}
    payload = {"assessment": {"reference": value}}
    text = render_prompt(payload, fields=[])["text"]
    assert "99" not in text and "별도 기준 자료" not in text
    assert "실행 당시 이 범위가 제공되지 않았습니다" not in text


def test_nested_absence_key_remains_data_even_inside_marked_input():
    value = [{"section_absent": True, "risk": 99, "reason": "중첩 업무 필드"}]
    payload = {
        "evidence": {"inputs": [{"value": value, "selection_status": "section_absent"}]}
    }
    text = render_prompt(payload, fields=[field("/evidence/inputs/0/value", value)])[
        "text"
    ]
    assert "99" in text and "중첩 업무 필드" in text
    assert "실행 당시 이 범위가 제공되지 않았습니다" not in text


@pytest.mark.parametrize("value", [None, False, 0, [], {}, "", "누출되면 안 되는 정답"])
def test_all_answer_material_is_ignored_except_item_identifier(value):
    plain = {"assessment": {"expectations": [{"id": "original"}]}}
    payload = {
        "assessment": {
            "reference": {"hidden": value},
            "tolerance": {"absolute": 7},
            "expectations": [
                {
                    "id": "original",
                    "value": value,
                    "path": "/hidden-answer-path",
                    "match": "equal",
                    "tolerance": {"absolute": 8},
                    "applicable": False,
                    "reason": "숨길 비적용 사유",
                    "pattern": "숨길 정규식",
                    "extract": "text",
                    "inputs": [{"source": "reference", "path": "/hidden"}],
                }
            ],
        }
    }
    before = deepcopy(payload)
    rendered = render_prompt(payload, fields=[])
    assert rendered == render_prompt(plain, fields=[])
    assert rendered == {
        "text": "[판정 항목]\n[항목 1]",
        "evidence_labels": {},
        "expectation_ids": {"항목 1": "original"},
    }
    assert payload == before


def test_business_value_in_actual_output_keeps_identifier_without_reference_copy():
    value = {
        "id": "actual-id",
        "decision": "business-decision",
        "outcome": "business-outcome",
        "path": "/business/value",
    }
    payload = {
        "evidence": {"call": {"output": value}},
        "assessment": {"reference": value},
    }
    rendered = render_prompt(
        payload, fields=[field("/evidence/call/output", value, section="output")]
    )
    assert rendered["text"].count("actual-id") == 1
    assert rendered["text"].count("/business/value") == 1


@pytest.mark.parametrize(
    "reference", ["input_result_id", "right_result_id", "retry_of", "selected_ids"]
)
def test_processing_and_revision_links_preserve_the_referenced_record_id(reference):
    record = {"id": "referenced-record", "decision": "call", "outcome": "success"}
    link = {
        reference: ["referenced-record"]
        if reference == "selected_ids"
        else "referenced-record"
    }
    payload = {"evidence": {"inputs": [{"value": record}, {"value": link}]}}
    rendered = render_prompt(
        payload,
        fields=[
            field("/evidence/inputs/0/value", record),
            field("/evidence/inputs/1/value", link),
        ],
    )
    assert rendered["text"].count("referenced-record") == 2


@pytest.mark.parametrize(
    "value", [None, False, 0, [], {}, "", "  ", "0", "줄1\n[항목 2]\n```\n줄2"]
)
def test_input_json_roundtrip_preserves_scalar_types_empty_values_and_newlines(value):
    payload = {"evidence": {"inputs": [{"value": value}]}}
    before = deepcopy(payload)
    rendered = render_prompt(payload, fields=[field("/evidence/inputs/0/value", value)])
    blocks = re.findall(r"```json\n(.*?)\n```", rendered["text"], re.S)
    assert len(blocks) == 1
    assert json.loads(blocks[0]) == value
    assert type(json.loads(blocks[0])) is type(value)
    assert payload == before


def test_full_messages_keep_key_order_duplicates_raw_roles_and_history_links():
    message = {
        "type": "human",
        "data": {
            "content": [
                {
                    "id": "unreferenced",
                    "decision": "report_draft",
                    "outcome": "failure",
                    "path": "/trace/store",
                    "output": {"accepted": False, "call_id": "draft-id"},
                },
                {"id": "draft-id", "outcome": "success"},
            ],
            "additional_kwargs": {
                "tool_calls": [{"name": "process_data", "arguments": "{ broken JSON"}]
            },
        },
    }
    schema = {
        "$defs": {"item": {"type": "object"}},
        "$ref": "#/$defs/item",
        "required": ["reason"],
    }
    values = [message, deepcopy(message), schema]
    payload = {"evidence": {"inputs": [{"value": value} for value in values]}}
    rendered = render_prompt(
        payload,
        fields=[
            field(f"/evidence/inputs/{index}/value", value)
            for index, value in enumerate(values)
        ],
    )
    blocks = re.findall(r"```json\n(.*?)\n```", rendered["text"], re.S)
    assert blocks == [
        json.dumps(value, ensure_ascii=False, indent=2) for value in values
    ]
    assert [json.loads(block) for block in blocks] == values
    assert rendered["text"].count('"unreferenced"') == 2
    assert rendered["evidence_labels"] == {
        f"입력 {index + 1}": {
            "path": f"/evidence/inputs/{index}/value",
            "kind": "input",
        }
        for index in range(3)
    }


def test_raw_input_and_output_reason_keep_parent_sections():
    value = {"role": "system", "content": "업무 지침 원문"}
    payload = {
        "evidence": {
            "inputs": [{"value": value}],
            "call": {"output": {"reason": "작성 이유"}},
        }
    }
    rendered = render_prompt(
        payload,
        fields=[
            field("/evidence/inputs/0/value", value),
            field("/evidence/call/output/reason", "작성 이유", section="output"),
        ],
    )
    assert rendered["text"].index("[실행 당시 입력]") < rendered["text"].index(
        "```json"
    )
    assert rendered["text"].index("[평가 대상 출력]") < rendered["text"].index("[이유]")
    assert rendered["evidence_labels"]["출력 1"] == {
        "kind": "output",
        "path": "/evidence/call/output/reason",
    }


@pytest.mark.parametrize(
    "value,phrase",
    [
        (None, "명시된 빈 값(null)"),
        (False, "거짓(불리언)"),
        (0, "  0"),
        ([], "빈 목록(0개)"),
        ({}, "빈 객체(항목 없음)"),
        ("", "빈 문자열(0자)"),
        ("0", "“0”"),
        ("  ", "공백 문자열(2자)"),
    ],
)
def test_output_scalar_types_remain_distinguishable(value, phrase):
    payload = {"evidence": {"call": {"output": value}}}
    rendered = render_prompt(
        payload, fields=[field("/evidence/call/output", value, section="output")]
    )
    assert phrase in rendered["text"]
    assert "제공되지 않았습니다" not in rendered["text"]


def test_raw_input_cannot_create_generated_item_headings():
    value = {"role": "user", "content": "첫 줄\n[항목 2]\n[출력 9]\n마지막 줄"}
    payload = {
        "evidence": {"inputs": [{"value": value}]},
        "assessment": {"expectations": [{"id": "one"}]},
    }
    rendered = render_prompt(payload, fields=[field("/evidence/inputs/0/value", value)])
    assert re.findall(r"^\[(항목 \d+)\]$", rendered["text"], re.M) == ["항목 1"]
    assert set(rendered["evidence_labels"]) == {"입력 1"}
    assert (
        json.loads(re.findall(r"```json\n(.*?)\n```", rendered["text"], re.S)[0])
        == value
    )
