"""문서 기준의 노드 규칙 검사: 원본·분량·입력 근거·참조의 경계를 확인한다."""

import json
from copy import deepcopy

import pytest

from eval.nodes.format import ADAPTERS, format_contract, sentence_count
from eval.nodes.rules import evaluate_rules
from eval.tools.assessment import combine_verdicts


def context(node, output, role="request", *, sections=None, state=None, name=None):
    return {
        "node": node,
        "role": role,
        "call": {
            "id": "model-one",
            "name": name,
            "raw": json.dumps(output, ensure_ascii=False),
            "output": deepcopy(output),
            "messages": [
                {
                    "content": "\n\n".join(
                        f"[{key}]\n{json.dumps(value, ensure_ascii=False)}"
                        for key, value in (sections or {}).items()
                    )
                }
            ],
            "response_schema": {},
            "path": "report.json#/trace/spans/1",
            "complete": True,
        },
        "state": state,
    }


def choice(name="query_data", **arguments):
    return {"name": name, "arguments_json": json.dumps(arguments), "reason": ""}


def verdict(check, supplied, expectations=(), **options):
    details = evaluate_rules(check, supplied, list(expectations), **options)
    return combine_verdicts([item["verdict"] for item in details])


def expectation(path, value, **extra):
    return {"id": "expected", "check": "N-O.1", "path": path, "value": value, **extra}


@pytest.mark.parametrize(
    ("node", "output"),
    [
        (
            "interpret",
            {"request": {"goal": "비교"}, "reason": ""},
        ),
        ("act", choice(target="registered")),
        ("decide", {"next": "compose", "reason": ""}),
        (
            "compose",
            {"content": "", "artifact_ids": [], "status": "partial", "reason": ""},
        ),
        ("ask", {"content": "", "reason": ""}),
    ],
)
def test_document_formats_allow_only_declared_empty_and_optional_values(node, output):
    assert verdict("N-F.1", context(node, output)) == "통과"


@pytest.mark.parametrize(
    "output",
    [
        {"request": {"goal": " "}, "reason": ""},
        {"request": {"goal": "x", "unexpected": 1}, "reason": ""},
        {
            "request": {"goal": "x", "constraints": None},
            "reason": "",
        },
        {
            "request": {"goal": "x", "constraints": {"required": [1]}},
            "reason": "",
        },
        {"request": {"goal": "x"}, "reason": "", "needs_input": "false"},
        {"request": {"goal": "x"}, "reason": "", "needs_input": 0},
        {"request": {"goal": "x"}, "reason": "", "needs_input": False},
    ],
)
def test_strict_fields_do_not_use_runtime_coercion(output):
    assert verdict("N-F.1", context("interpret", output)) == "실패"


@pytest.mark.parametrize(
    "raw",
    [
        '{"content":"a","reason":"", "content":"b"}',
        '{"content":NaN,"reason":""}',
        '{"content":1e400,"reason":""}',
        '```json\n{"content":"a","reason":""}\n```',
        '{"content":"a","reason":""} trailing',
        "[]",
    ],
)
def test_raw_json_rejects_ambiguous_or_non_json_originals(raw):
    supplied = context("ask", {"content": "valid parsed fallback", "reason": ""})
    supplied["call"]["raw"] = raw
    assert verdict("N-F.1", supplied) == "실패"


def test_raw_evidence_is_independent_of_call_end_and_parsed_value():
    supplied = context("ask", {"content": "질문", "reason": ""})
    supplied["call"]["raw"] = None
    assert verdict("N-F.1", supplied) == "미판정"
    supplied["call"].update(raw='{"content":', complete=False)
    assert verdict("N-F.1", supplied) == "실패"
    supplied["call"]["raw"] = '{"content":"질문","reason":""}'
    assert verdict("N-F.1", supplied) == "통과"


@pytest.mark.parametrize(
    "arguments",
    [
        {"target": "x", "offset": True},
        {"target": "x", "limit": 10_001},
        {"target": "x", "limit": 0},
        {"target": "x", "fields": []},
        {"target": "x", "sort": [{"field": "a", "descending": 1}]},
        {"target": "x", "filters": [{"field": "a", "operator": "eq"}]},
        {"target": "x", "filters": [{"field": "a", "operator": "eq", "value": []}]},
        {"target": "x", "unknown": "x"},
    ],
)
def test_query_argument_contract(arguments):
    assert verdict("N-F.1", context("act", choice(**arguments))) == "실패"


def test_query_nullable_scalar_and_empty_condition_arrays_are_valid():
    output = choice(
        target="x",
        filters=[{"field": "a", "operator": "is_null", "value": None}],
        sort=[],
    )
    assert verdict("N-F.1", context("act", output)) == "통과"


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation": "calculate",
            "method": "difference",
            "before": "a",
            "after": "b",
            "output": "c",
        },
        {
            "operation": "aggregate",
            "method": "mean",
            "field": "a",
            "output": "b",
            "group_by": [],
        },
        {
            "operation": "join",
            "right_result_id": "",
            "keys": ["id"],
            "how": "left",
            "fields": {"a": "b"},
        },
        {"operation": "filter", "conditions": []},
        {"operation": "cast", "field": "a", "kind": "number"},
        {"operation": "sort", "by": [{"field": "a", "descending": False}]},
    ],
)
def test_each_process_operation_matches_evaluation_reference_arguments(operation):
    output = choice("process_data", input_result_id="", operations=[operation])
    assert verdict("N-F.1", context("act", output)) == "통과"
    operation = deepcopy(operation)
    operation["extra"] = True
    assert (
        verdict(
            "N-F.1",
            context(
                "act",
                choice("process_data", input_result_id="r", operations=[operation]),
            ),
        )
        == "실패"
    )


def test_process_requires_references_not_embedded_data_and_nonempty_operations():
    for args in (
        {"data": {}, "operations": []},
        {"input_result_id": "r", "operations": []},
    ):
        assert (
            verdict("N-F.1", context("act", choice("process_data", **args))) == "실패"
        )


def test_action_selection_requires_a_real_allowed_call():
    for output in (choice("none"), choice("none", target="x")):
        assert verdict("N-F.1", context("act", output)) == "실패"
        assert verdict("N02-B.2", context("act", output)) == "실패"


def visual(profile="monthly_detail"):
    return {"views": {"view": {"input_profile": profile}}}


def test_visual_profile_is_bound_to_saved_input_and_does_not_use_current_registry(
    monkeypatch,
):
    monkeypatch.setattr(
        "src.tools.tableau_catalog.registered_catalog",
        lambda: pytest.fail("live catalog read"),
    )
    output = choice(
        "validate_visualization",
        view_key="view",
        parameters={
            "p_detail_adm": "행정동",
            "p_start": "2026-01-01",
            "p_end": "2026-02-01",
        },
    )
    supplied = context("act", output, sections={"시각화 목록과 입력 조건": visual()})
    assert verdict("N-F.1", supplied) == "통과"
    assert verdict("N-F.1", context("act", output)) == "미판정"
    assert (
        verdict("N-F.1", context("act", output), reference={"visualization": visual()})
        == "통과"
    )
    args = json.loads(output["arguments_json"])
    args["parameters"]["p_start"] = "2026-02-30"
    supplied["call"]["raw"] = json.dumps(choice("validate_visualization", **args))
    assert verdict("N-F.1", supplied) == "실패"
    args["parameters"]["p_start"] = "2026-01-01"
    args["filters"] = {"읍면동": ["동"]}
    supplied["call"]["raw"] = json.dumps(choice("validate_visualization", **args))
    assert verdict("N-F.1", supplied) == "실패"


def test_selection_format_leaves_zero_and_duplicate_views_to_content_checks():
    view = {"view_key": "EmbedDetailV01", "reason": "근거", "evidence_ids": ["r"]}
    for views in ([], [view], [view, view, view]):
        assert (
            verdict("N-F.1", context("compose", {"views": views}, "report_selection"))
            == "통과"
        )
    assert (
        verdict("N-F.1", context("compose", {"views": [view] * 4}, "report_selection"))
        == "실패"
    )
    view["evidence_ids"] = []
    assert (
        verdict("N-F.1", context("compose", {"views": [view]}, "report_selection"))
        == "실패"
    )


def test_report_review_is_selected_by_call_schema_not_draft_role():
    supplied = context(
        "compose", {"accepted": True, "reason": ""}, "report_description", name="model"
    )
    supplied["call"]["response_schema"] = {"title": "Verification"}
    assert verdict("N-F.1", supplied) == "통과"
    supplied["call"]["raw"] = '{"accepted":"true","reason":""}'
    assert verdict("N-F.1", supplied) == "실패"


def test_report_schema_without_role_does_not_guess_text_length_contract():
    supplied = context("compose", {"views": []}, None, name="ReportSelection")
    assert verdict("N-F.1", supplied) == "통과"
    supplied["call"]["name"] = "ReportText"
    supplied["call"]["raw"] = '{"content":"본문이다."}'
    details = evaluate_rules(
        "N-F.1", supplied, [], reference={"format": {"completed": True}}
    )
    assert details[1]["verdict"] == "통과"
    assert details[-1]["verdict"] == "미판정"


def test_actual_catalog_can_be_read_from_serialized_message_data():
    supplied = context(
        "act",
        choice(target="registered"),
        sections={"조회 가능한 자료 목록": {"registered": {}}},
    )
    supplied["call"]["messages"] = [
        {"type": "system", "data": supplied["call"]["messages"][0]}
    ]
    assert verdict("N-B.1", supplied) == "통과"


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("점수는 3.14다. 자료는 유지됐다.", 2),
        ("1. 증가했다.", 1),
        ("증가했다?! 유지 여부는 미확인이다.", 2),
        ("출처는 https://example.com/a.b 이다.", 1),
        ("Dr. Kim의 설명이다.", 1),
        ("'증가했나?'라고 물었다.", 1),
        ("한 문장이다.두 문장이다.", 2),
        ("종결 부호 없는 한 문장", 1),
    ],
)
def test_sentence_boundaries_exclude_decimal_url_and_list_punctuation(text, count):
    assert sentence_count(text) == count


@pytest.mark.parametrize(
    ("role", "content", "expected"),
    [
        ("report_description", "첫 설명이다. 수치는 3.14다. 끝이다.", "통과"),
        ("report_description", "첫 설명이다.\n줄을 이어 쓴다.", "통과"),
        ("report_description", "첫 설명이다.\n\n다른 단락이다.", "실패"),
        ("report_description", "하나다. 둘이다. 셋이다. 넷이다.", "실패"),
        ("report_insight", "1. 첫째다.\n2. 둘째다.\n3. 셋째다.", "통과"),
        ("report_insight", "첫째다. 둘째다.\n셋째다.\n넷째다.", "실패"),
        ("report_insight", "첫째다.\n둘째다.", "실패"),
    ],
)
def test_report_completed_text_lengths(role, content, expected):
    supplied = context("compose", {"content": content}, role)
    assert (
        verdict("N-F.1", supplied, reference={"format": {"completed": True}})
        == expected
    )


def test_missing_completion_criterion_is_not_guessed_from_text_or_model_review():
    supplied = context("compose", {"content": "자료가 부족하다."}, "report_insight")
    assert verdict("N-F.1", supplied) == "미판정"
    details = evaluate_rules(
        "N-F.1", supplied, [], reference={"format": {"completed": False}}
    )
    assert details[-1]["verdict"] == "비적용"
    assert combine_verdicts([item["verdict"] for item in details]) == "통과"


def test_numeric_capture_tolerance_and_reference_are_required_without_mutation():
    supplied = context("compose", {"content": "비율은 12.34%다."})
    items = [expectation("/content", 12.3, pattern=r"(\d+\.\d+)%", extract="number")]
    before = deepcopy((supplied, items))
    assert verdict("N-O.1", supplied, items) == "미판정"
    assert (
        verdict("N-O.1", supplied, items, reference={"source": "independent"}) == "실패"
    )
    assert (
        verdict(
            "N-O.1",
            supplied,
            items,
            reference={"source": "independent"},
            tolerance={"absolute": 0.05},
        )
        == "통과"
    )
    assert (supplied, items) == before


def test_numeric_capture_checks_every_match_and_preserves_json_types():
    supplied = context("compose", {"content": "값은 1,000과 2,000이다.", "value": True})
    items = [
        expectation("/content", [1000, 2000], pattern=r"(\d,\d{3})", extract="number")
    ]
    assert verdict("N-O.1", supplied, items, reference="독립 원자료") == "통과"
    items[0]["value"] = [1000]
    assert verdict("N-O.1", supplied, items, reference="독립 원자료") == "실패"
    assert (
        verdict("N-O.1", supplied, [expectation("/value", 1)], reference="자료")
        == "실패"
    )


def test_input_selection_must_exist_and_output_alone_is_not_independent_grounding():
    supplied = context("compose", {"value": 2}, state={"results": []})
    item = expectation("/value", 2, inputs=[{"source": "state", "path": "/absent"}])
    assert verdict("N-O.1", supplied, [item], reference="자료") == "미판정"
    item["inputs"] = [{"source": "output", "path": "/value"}]
    assert verdict("N-O.1", supplied, [item]) == "미판정"
    item["inputs"] = [{"source": "state", "path": "/results"}]
    assert verdict("N-O.1", supplied, [item]) == "미판정"
    supplied["call"]["messages"] = [{"role": "user", "content": "입력 수치는 2"}]
    item["inputs"] = [{"source": "messages", "path": "/0/content"}]
    assert verdict("N-O.1", supplied, [item]) == "통과"


def test_source_reference_comparison_detects_missing_and_incorrect_citations():
    supplied = context("compose", {"content": "출처: 원자료-v2"})
    item = expectation("/content", "원자료-v2", pattern=r"출처: (\S+)")
    assert verdict("N-O.8", supplied, [item], reference={"version": "v2"}) == "통과"
    item["value"] = "원자료-v3"
    assert verdict("N-O.8", supplied, [item], reference={"version": "v3"}) == "실패"
    item["path"] = "/missing"
    assert verdict("N-O.8", supplied, [item], reference={"version": "v3"}) == "실패"


def test_registered_source_scope_uses_actual_prompt_not_a_current_catalog():
    supplied = context(
        "act",
        choice(target="registered"),
        sections={"조회 가능한 자료 목록": {"registered": {}}},
    )
    assert verdict("N-B.1", supplied) == "통과"
    supplied["call"]["raw"] = json.dumps(choice(target="invented"))
    assert verdict("N-B.1", supplied) == "실패"
    supplied["call"]["messages"] = []
    assert verdict("N-B.1", supplied) == "미판정"


def test_call_scope_checks_role_and_actual_bound_names_separately():
    supplied = context(
        "act", choice("visualization_agent", goal="표현"), "interpretation"
    )
    supplied["call"]["response_schema"] = {
        "properties": {"name": {"enum": ["visualization_agent"]}}
    }
    assert verdict("N02-B.2", supplied) == "실패"
    supplied["role"] = "request"
    assert verdict("N02-B.2", supplied) == "통과"
    supplied["call"]["response_schema"]["properties"]["name"]["enum"] = ["query_data"]
    assert verdict("N02-B.2", supplied) == "실패"


def result(identity="r", *, columns=("id", "a", "b"), outcome="success", valid=True):
    return {
        "id": identity,
        "decision": "call",
        "outcome": outcome,
        "output": {
            "valid": valid,
            "data": {"columns": [{"name": key} for key in columns]},
        },
    }


def test_call_arguments_use_json_subpaths_and_preserve_original_string_comparisons():
    output = choice(target="registered")
    supplied = context("act", output)
    item = expectation("/arguments_json/target", "registered")
    assert verdict("N02-O.3", supplied, [item], reference="요청 대상") == "통과"
    item.update(path="/arguments_json", value=output["arguments_json"])
    assert verdict("N02-O.3", supplied, [item], reference="요청 인자") == "통과"


def test_process_reference_and_sequential_columns_reject_failed_or_lost_inputs():
    operations = [
        {
            "operation": "aggregate",
            "method": "sum",
            "field": "a",
            "group_by": ["id"],
            "output": "total",
        },
        {
            "operation": "calculate",
            "method": "difference",
            "before": "a",
            "after": "total",
            "output": "change",
        },
    ]
    supplied = context(
        "act",
        choice("process_data", input_result_id="r", operations=operations),
        sections={"작업 결과와 검증 이력": [result()]},
    )
    item = expectation("/arguments_json/input_result_id", "r")
    assert verdict("N02-O.3", supplied, [item], reference="기준 자료") == "실패"
    operations[1]["before"] = "total"
    supplied["call"]["raw"] = json.dumps(
        choice("process_data", input_result_id="r", operations=operations)
    )
    assert verdict("N02-O.3", supplied, [item], reference="기준 자료") == "통과"
    supplied["call"]["messages"] = context(
        "act", {}, sections={"작업 결과와 검증 이력": [result(outcome="failure")]}
    )["call"]["messages"]
    assert verdict("N02-O.3", supplied, [item], reference="기준 자료") == "실패"
    supplied["call"]["messages"] = []
    assert verdict("N02-O.3", supplied, [item], reference="기준 자료") == "미판정"


@pytest.mark.parametrize(
    ("outcome", "argument_verdict"), [("success", "통과"), ("failure", "실패")]
)
def test_process_validity_leaves_allowed_result_scope_to_data_boundary(
    outcome, argument_verdict
):
    supplied = context(
        "act",
        choice(
            "process_data",
            input_result_id="r",
            operations=[
                {
                    "operation": "aggregate",
                    "method": "sum",
                    "field": "a",
                    "output": "total",
                    "group_by": [],
                }
            ],
        ),
        sections={
            "작업 결과와 검증 이력": [result(outcome=outcome)],
            "가공 가능한 결과 ID와 열": {},
        },
    )
    item = expectation("/arguments_json/input_result_id", "r")
    assert verdict("N-B.1", supplied) == "실패"
    assert (
        verdict("N02-O.3", supplied, [item], reference="요청한 가공 입력")
        == argument_verdict
    )


def test_artifact_list_ignores_order_but_checks_omission_and_invalid_result():
    supplied = context(
        "compose",
        {"artifact_ids": ["new", "previous"]},
        sections={
            "작업 결과와 검증 이력": [result("new")],
            "기존 공개 산출물": [{"type": "tableau"}],
        },
    )
    item = expectation("/artifact_ids", ["previous", "new"])
    assert verdict("N04-O.2", supplied, [item], reference="계속 제공할 목록") == "통과"
    supplied["call"]["raw"] = json.dumps({"artifact_ids": ["previous"]})
    assert verdict("N04-O.2", supplied, [item], reference="계속 제공할 목록") == "실패"
    supplied["call"]["raw"] = json.dumps({"artifact_ids": ["new", "previous"]})
    supplied["call"]["messages"] = context(
        "compose",
        {},
        sections={
            "작업 결과와 검증 이력": [result("new", valid=False)],
            "기존 공개 산출물": [{"type": "tableau"}],
        },
    )["call"]["messages"]
    assert verdict("N04-O.2", supplied, [item], reference="계속 제공할 목록") == "실패"


def test_valid_artifacts_alone_do_not_establish_coverage_without_required_list():
    supplied = context(
        "compose",
        {"artifact_ids": ["new"]},
        sections={"작업 결과와 검증 이력": [result("new")]},
    )
    assert verdict("N04-O.2", supplied) == "미판정"


def test_superseded_artifact_is_excluded_by_independent_expected_selection():
    supplied = context(
        "compose",
        {"artifact_ids": ["old", "new"]},
        sections={
            "작업 결과와 검증 이력": [result("old"), result("new")],
        },
    )
    assert (
        verdict(
            "N04-O.2",
            supplied,
            [expectation("/artifact_ids", ["new"])],
            reference={"superseded": ["old"]},
        )
        == "실패"
    )


def test_malformed_input_metadata_is_unknown_instead_of_an_execution_error():
    record = result("new")
    record["output"]["execution"] = "unavailable"
    supplied = context(
        "compose",
        {"artifact_ids": ["new"]},
        sections={"작업 결과와 검증 이력": [record]},
    )
    assert (
        verdict(
            "N04-O.2",
            supplied,
            [expectation("/artifact_ids", ["new"])],
            reference="유지할 결과",
        )
        == "미판정"
    )


def test_untransmitted_state_does_not_establish_available_results_or_previous():
    supplied = context(
        "compose",
        {"artifact_ids": ["new", "previous"]},
        state={
            "results": [result("new")],
            "response": {"artifacts": [{"type": "tableau"}]},
        },
    )
    items = [expectation("/artifact_ids", ["new", "previous"])]
    assert verdict("N04-O.2", supplied, items, reference="필수 목록") == "미판정"
    assert verdict("N-B.1", supplied) == "미판정"


def test_schema_contract_records_constraints_without_changing_output_verdict():
    supplied = context(
        "interpret",
        {
            "request": {"goal": "대상 비교"},
            "reason": "",
        },
    )
    actual = ADAPTERS["interpret"].json_schema()
    actual["additionalProperties"] = True
    actual["$defs"]["Request"]["properties"]["goal"]["minLength"] = 2
    supplied["call"]["response_schema"] = actual
    before = deepcopy(supplied)
    contract = format_contract(supplied)
    assert contract["structural_equal"] is False
    assert "/additionalProperties" in contract["differences"]
    assert "/properties/request/properties/goal/minLength" in contract["differences"]
    assert contract["actual_response_schema"] == actual
    assert contract["evaluation_response_schema"] == ADAPTERS["interpret"].json_schema()
    assert verdict("N-F.1", supplied) == "통과"
    contract["actual_response_schema"]["title"] = "변경"
    assert supplied == before


def test_schema_contract_resolves_renamed_defs_and_ignores_annotations():
    supplied = context("interpret", {})
    actual = ADAPTERS["interpret"].json_schema()
    actual["title"] = "런타임 이름"
    actual["description"] = "설명"
    actual["$defs"]["RuntimeRequest"] = actual["$defs"].pop("Request")
    actual["properties"]["request"]["$ref"] = "#/$defs/RuntimeRequest"
    actual["required"].reverse()
    supplied["call"]["response_schema"] = actual
    contract = format_contract(supplied)
    assert contract["structural_equal"] is True
    assert contract["differences"] == []


@pytest.mark.parametrize(
    "schema",
    [
        None,
        {},
        "invalid",
        {"properties": []},
        {"type": "unknown"},
        {"type": "string", "minLength": "1"},
        {"$ref": "https://example.test/schema"},
        {"$ref": "#/$defs/self", "$defs": {"self": {"$ref": "#/$defs/self"}}},
    ],
)
def test_schema_contract_missing_or_unresolvable_schema_remains_unknown(schema):
    supplied = context("ask", {"content": "", "reason": ""})
    supplied["call"]["response_schema"] = schema
    contract = format_contract(supplied)
    assert contract["structural_equal"] is None
    assert contract["differences"]
    assert verdict("N-F.1", supplied) == "통과"


def test_visual_values_use_selected_dependency_snapshot_only_for_its_parameter():
    catalog = visual("custom")
    catalog["input_profiles"] = {
        "custom": {
            "parameters": {"city": {"data_type": "string", "allowed": ["a", "b"]}},
            "filters": {"district": {"depends_on": "city"}},
            "date_orders": [],
        }
    }
    catalog["selected"] = {
        "view": {
            "parameters": {"city": "a"},
            "filters": {"district": {"allowed": ["d"]}},
        }
    }
    supplied = context(
        "act",
        choice(
            "validate_visualization",
            view_key="view",
            parameters={"city": "a"},
            filters={"district": ["d"]},
        ),
        sections={"시각화 목록과 입력 조건": catalog},
    )
    item = expectation("/arguments_json/parameters/city", "a")
    assert verdict("N02-O.3", supplied, [item], reference="표시 조건") == "통과"
    supplied["call"]["raw"] = json.dumps(
        choice(
            "validate_visualization",
            view_key="view",
            parameters={"city": "b"},
            filters={"district": ["d"]},
        )
    )
    item["value"] = "b"
    assert verdict("N02-O.3", supplied, [item], reference="표시 조건") == "미판정"
