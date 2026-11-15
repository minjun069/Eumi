"""검사별 필드 선택이 판정 근거·실패·승인 연결을 보존하는지 확인한다."""

import json
from copy import deepcopy

import pytest

from eval.nodes.criteria import load_criteria
from eval.nodes.prompt_fields import PROFILES, project_fields, situation_text

CATALOG = load_criteria()
ROWS = {
    row["row_id"]: row
    for check in CATALOG["checks"].values()
    if check["method"] == "LLM 기반"
    for row in check["rows"]
}
OUTPUTS = {
    "Interpretation": {
        "request": {
            "goal": "2026년 A동의 연령대별 위험 변화와 완료 기준 비교",
            "constraints": {
                "required": ["지역·집단만 해석"],
                "preferred": ["이전 기간 비교"],
                "excluded": ["개인 추정"],
            },
        },
        "reason": "대상과 기간을 사용자 요청에서 확인했다.",
    },
    "Selection": {
        "name": "validate_visualization",
        "arguments_json": '{"view_key":"V01","filters":{"age":["60"]}}',
        "reason": "진행 판단에서 필요한 비교 자료를 확보한다.",
    },
    "Decision": {"next": "act", "reason": "기간 비교 자료가 부족하다."},
    "Composition": {
        "content": "관측된 변화이며 인과관계는 확인하지 못했다.",
        "artifact_ids": ["valid-view"],
        "status": "partial",
        "reason": "등록된 뷰의 해당 기간 최신성은 확인되지 않았다.",
    },
    "Question": {"content": "비교할 기간을 알려 주세요.", "reason": "사용자 조건 필요"},
    "ReportSelection": {
        "views": [{"view_key": "V01", "reason": "A동 변화", "evidence_ids": ["data"]}]
    },
    "ReportText": {"content": "A동의 비율이 증가했다. 인과관계는 확인되지 않았다."},
    "Verification": {"accepted": False, "reason": "새 인과관계가 근거에 없다."},
}


def evidence(name="Composition", *, output=None, inputs=(), role="request"):
    return {
        "node": "compose",
        "role": role,
        "call": {
            "name": name,
            "output": deepcopy(OUTPUTS[name] if output is None else output),
        },
        "inputs": list(inputs),
    }


def entry(label, value, *, path="/messages/1/content"):
    return {"label": label, "value": value, "source": "messages", "path": path}


def record(identifier, output, *, decision="report_draft", outcome="success", refs=()):
    return {
        "id": identifier,
        "node": "compose",
        "decision": decision,
        "outcome": outcome,
        "reason": "대상·근거를 확인했다.",
        "action": {
            "name": "write_report",
            "arguments": {"view_key": "V01", "result_ids": list(refs)},
        },
        "output": output,
        "description": "자료의 한계는 인과관계를 보장하지 않는다는 점이다.",
    }


def output_fields(projection):
    return [field for field in projection["fields"] if field["section"] == "output"]


def input_fields(projection):
    return [field for field in projection["fields"] if field["section"] == "input"]


def test_profiles_cover_exactly_all_current_llm_rows():
    assert set(ROWS) == set(PROFILES)
    assert len(ROWS) == 37


@pytest.mark.parametrize("row_id", ROWS)
def test_every_row_selects_meaningful_fields_and_never_whole_output(row_id):
    definition = ROWS[row_id]
    for call in PROFILES[row_id]["outputs"]:
        original = evidence(call)
        original["call"]["output"]["unrelated"] = "DO NOT SEND"
        before = deepcopy(original)
        selected = project_fields(definition, original)
        fields = output_fields(selected)
        assert fields
        assert "DO NOT SEND" not in json.dumps(fields)
        assert not any(
            field.get("value") == original["call"]["output"] for field in fields
        )
        assert "/evidence/call/output/unrelated" in selected["excluded_paths"]
        assert original == before
        assert situation_text(definition, original)


@pytest.mark.parametrize(
    "row_id,call,paths",
    [
        (
            "N01-O.2/general",
            "Interpretation",
            {
                "request/goal",
                "request/constraints/required",
                "request/constraints/preferred",
                "request/constraints/excluded",
                "reason",
            },
        ),
        ("N02-O.2/general", "Selection", {"name", "reason"}),
        ("N02-O.1/general", "Selection", {"name", "reason"}),
        ("N03-O.3/general", "Decision", {"next"}),
        ("N03-O.4/general", "Decision", {"next", "reason"}),
        ("N05-O.2/general", "Question", {"content"}),
        ("N05-O.1/general", "Question", {"content", "reason"}),
    ],
)
def test_dedicated_checks_have_minimal_explicit_output_fields(row_id, call, paths):
    fields = output_fields(project_fields(ROWS[row_id], evidence(call)))
    assert {
        field["path"].removeprefix("/evidence/call/output/") for field in fields
    } == paths


def test_visualization_check_reads_only_decoded_view_and_audits_hidden_arguments():
    selected = project_fields(ROWS["N02-O.4/general"], evidence("Selection"))
    fields = output_fields(selected)
    assert fields[1]["value"] == "V01"
    assert fields[1]["path"] == "/evidence/call/output/arguments_json"
    assert fields[1]["json_path"] == "/view_key"
    assert (
        "/evidence/call/output/arguments_json#json/filters"
        in selected["excluded_paths"]
    )
    assert "filters" not in json.dumps(fields)


def test_injection_check_explicitly_includes_all_decisions_and_parsed_arguments():
    selected = project_fields(ROWS["N-B.2/general"], evidence("Selection"))
    fields = output_fields(selected)
    assert fields[0]["value"] == "validate_visualization"
    assert fields[1]["value"] == {"view_key": "V01", "filters": {"age": ["60"]}}
    assert fields[1]["json_path"] == ""
    assert fields[2]["value"] == OUTPUTS["Selection"]["reason"]


@pytest.mark.parametrize("name", ["Selection", "Decision", "Verification"])
def test_publication_check_does_not_treat_internal_reasons_as_public_body(name):
    fields = output_fields(project_fields(ROWS["N-B.3/general"], evidence(name)))
    assert len(fields) == 1
    assert fields[0]["status"] == "missing"
    assert "공개용 본문 필드가 없습니다" in fields[0]["reason"]
    assert "value" not in fields[0]


def test_optional_constraints_absence_is_not_described_as_required_failure():
    original = evidence(
        "Interpretation", output={"request": {"goal": "목표"}, "reason": "이유"}
    )
    fields = output_fields(project_fields(ROWS["N01-O.2/general"], original))
    assert fields[0]["value"] == "목표"
    absent = [field for field in fields if field["status"] == "missing"]
    assert len(absent) == 3
    assert all("선택 항목" in field["reason"] for field in absent)
    assert all(
        "사실만으로 내용 누락을 판단하지 않습니다" in field["reason"]
        for field in absent
    )
    assert all(field["path"] == "/evidence/call/output/request" for field in absent)
    del original["call"]["output"]["request"]
    fields = output_fields(project_fields(ROWS["N01-O.2/general"], original))
    assert all("선택 항목" not in field.get("reason", "") for field in fields)


@pytest.mark.parametrize(
    "value,status",
    [(None, "invalid"), (0, "invalid"), (False, "invalid"), ("", "present")],
)
def test_malformed_and_empty_output_values_remain_distinguishable(value, status):
    fields = output_fields(
        project_fields(
            ROWS["N05-O.2/general"], evidence("Question", output={"content": value})
        )
    )
    assert fields[0]["value"] is value
    assert fields[0]["status"] == status


def test_missing_output_and_unknown_nonempty_call_are_not_guessed():
    for row in ROWS.values():
        fields = output_fields(project_fields(row, {}))
        assert fields[0]["status"] == "missing"
        assert fields[0]["path"] == "/evidence"
    with pytest.raises(ValueError, match="모델 호출"):
        project_fields(ROWS["N05-O.2/general"], {"call": {"name": "NewCall"}})
    with pytest.raises(ValueError, match="프로필"):
        project_fields({"row_id": "NEW/general"}, {})


def test_invalid_arguments_remain_visible_with_original_parent_provenance():
    original = evidence(
        "Selection",
        output={
            "name": "validate_visualization",
            "arguments_json": "not JSON",
            "reason": "선택",
        },
    )
    fields = output_fields(project_fields(ROWS["N02-O.4/general"], original))
    assert fields[1]["value"] == "not JSON"
    assert fields[1]["status"] == "invalid"
    assert fields[1]["path"] == "/evidence/call/output/arguments_json"


def test_situation_explains_report_call_without_internal_role_codes():
    text = situation_text(
        ROWS["N04-O.3/report-description"],
        evidence("Verification", role="report_description"),
    )
    assert "뷰별 설명" in text and "검토" in text
    assert "report_description" not in text and "Verification" not in text


def test_report_selection_reason_is_public_response_material():
    selected = project_fields(ROWS["N-B.3/general"], evidence("ReportSelection"))
    fields = output_fields(selected)
    assert fields[0]["value"] == "A동 변화"
    assert fields[0]["path"] == "/evidence/call/output/views/0/reason"


def test_unknown_nested_output_is_audited_without_entering_the_prompt():
    original = evidence("Interpretation")
    original["call"]["output"]["request"]["extra"] = "hidden"
    selected = project_fields(ROWS["N01-O.2/general"], original)
    assert "/evidence/call/output/request/extra" in selected["excluded_paths"]
    assert "hidden" not in json.dumps(selected["fields"])


@pytest.mark.parametrize(
    "check", ["N-O.5", "N-O.2", "N-O.3", "N-O.4", "N-O.9", "N-O.10"]
)
def test_common_checks_keep_new_claims_in_authored_reasons(check):
    original = evidence()
    original["call"]["output"]["reason"] = "정책 시행 때문에 비율이 20% 줄었다."
    fields = output_fields(project_fields(ROWS[check + "/general"], original))
    assert {field["path"] for field in fields} == {
        "/evidence/call/output/content",
        "/evidence/call/output/reason",
    }
    assert fields[1]["value"] == "정책 시행 때문에 비율이 20% 줄었다."
    original = evidence("ReportSelection")
    original["call"]["output"]["views"][0]["reason"] = "정책 때문에 변화했다."
    fields = output_fields(project_fields(ROWS[check + "/general"], original))
    assert fields[0]["value"] == "정책 때문에 변화했다."


@pytest.mark.parametrize("row_id", ROWS)
def test_every_row_keeps_complete_raw_input_and_schema(row_id):
    message = {
        "role": "system",
        "content": "숨겨졌던 업무 지침",
        "extra": {"id": "keep", "path": "/original", "model_usage": {"tokens": 7}},
    }
    schema = {"type": "object", "$defs": {"Original": {"description": "스키마 원문"}}}
    name = next(iter(PROFILES[row_id]["outputs"]))
    original = evidence(
        name,
        inputs=[
            entry("전체 메시지", message),
            {
                "label": "응답 형식",
                "source": "response_schema",
                "path": "/response_schema",
                "value": schema,
            },
            entry("반복 메시지", message),
        ],
    )
    before = deepcopy(original)
    selected = project_fields(ROWS[row_id], original)
    fields = input_fields(selected)
    assert [field["value"] for field in fields] == [message, schema, message]
    assert [field["path"] for field in fields] == [
        f"/evidence/inputs/{i}/value" for i in range(3)
    ]
    assert all(field["status"] == "present" for field in fields)
    assert all(
        not path.startswith("/evidence/inputs") for path in selected["excluded_paths"]
    )
    assert original == before


@pytest.mark.parametrize(
    "source,value",
    [
        ("messages", "text"),
        ("messages", {"content": "no role"}),
        ("messages", {"role": "user"}),
        ("response_schema", []),
        ("state", {"role": "user", "content": "unsent"}),
    ],
)
def test_damaged_or_unsent_input_is_retained_with_invalid_status(source, value):
    original = evidence(
        "Interpretation",
        inputs=[
            {"label": "input", "source": source, "path": "/origin", "value": value}
        ],
    )
    field = next(
        field
        for field in input_fields(project_fields(ROWS["N01-O.2/general"], original))
        if field["path"] == "/evidence/inputs/0/value"
    )
    assert field["status"] == "invalid"
    assert field["value"] == value


def test_whole_message_content_is_not_parsed_or_rewritten():
    message = {"role": "user", "content": '{"broken":', "extra": None}
    field = input_fields(
        project_fields(
            ROWS["N01-O.2/general"],
            evidence("Interpretation", inputs=[entry("whole", message)]),
        )
    )[0]
    assert field["status"] == "present"
    assert field["value"] == message
    assert "json_path" not in field


@pytest.mark.parametrize("location", ["goal", "preferred", "reason"])
def test_inclusion_retains_meaning_across_delivered_interpretation_fields(location):
    meaning = "출처와 해석 한계를 설명한다."
    output = {
        "request": {"goal": "지역 변화 설명"},
        "reason": "사용자의 요청을 정리했다.",
    }
    if location == "goal":
        output["request"]["goal"] += " " + meaning
    elif location == "preferred":
        output["request"]["constraints"] = {"preferred": [meaning]}
    else:
        output["reason"] = meaning
    fields = output_fields(
        project_fields(
            ROWS["N01-O.2/general"], evidence("Interpretation", output=output)
        )
    )
    assert meaning in json.dumps(fields, ensure_ascii=False)
    expected_path = {
        "goal": "/request/goal",
        "preferred": "/request/constraints/preferred",
        "reason": "/reason",
    }[location]
    assert any(
        field["path"] == "/evidence/call/output" + expected_path
        and field["status"] == "present"
        for field in fields
    )


def test_interpretation_response_includes_selected_artifacts_to_check_required_tables():
    output = {
        "content": "요청한 비교 결과입니다.",
        "artifact_ids": ["table-result"],
        "status": "completed",
        "reason": "비교표 제공",
    }
    fields = output_fields(
        project_fields(
            ROWS["N04-O.1/interpretation"],
            evidence("Composition", output=output, role="interpretation"),
        )
    )
    assert any(
        field["path"] == "/evidence/call/output/artifact_ids"
        and field["value"] == ["table-result"]
        for field in fields
    )


@pytest.mark.parametrize("row_id", ["N05-O.2/general", "N05-O.3/general"])
def test_question_required_meaning_is_limited_to_public_question_content(row_id):
    output = {
        "content": "기간을 알려 주세요.",
        "reason": "INTERNAL_ONLY_CANDIDATE_CANARY",
    }
    fields = output_fields(
        project_fields(ROWS[row_id], evidence("Question", output=output))
    )
    assert [field["value"] for field in fields] == [output["content"]]
    assert "INTERNAL_ONLY_CANDIDATE_CANARY" not in json.dumps(fields)
