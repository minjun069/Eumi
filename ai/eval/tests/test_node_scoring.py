"""실제 시나리오 실행 → 저장 증거 → 분리된 규칙·LLM 평가 연결을 검증한다."""

import asyncio
import json
import re
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from eval.__main__ import main
from eval.assessment_store import load_assessment
from eval.nodes.criteria import load_criteria, select_rows
from eval.nodes.evidence import extract_nodes
from eval.nodes.scoring import _run_result, score_nodes
from eval.runner import run_suite
from eval.tests.batch_fixtures import read_document
from src.settings import Settings
from tests.helpers import ScriptedModel


class Judge:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def with_structured_output(self, schema, **kwargs):
        return self

    async def ainvoke(self, messages, config):
        self.calls.append(messages)
        if self.error:
            raise self.error
        payload = messages[1].content
        comparison = re.findall(r"^\[(입력 \d+)\]", payload, re.MULTILINE)[:1]
        return {
            "raw": AIMessage(
                content=json.dumps(
                    {
                        "details": [
                            {
                                "id": item,
                                "verdict": "통과",
                                "reason": "실행 당시 입력과 출력을 검사 기준으로 대조",
                                "evidence": ["출력 1", *comparison],
                            }
                            for item in re.findall(
                                r"^\[(항목 \d+)\]$", payload, re.MULTILINE
                            )
                        ],
                        "reason": "시험용 평가 모델 응답",
                    }
                ),
                response_metadata={"model_name": "test-judge"},
                usage_metadata={
                    "input_tokens": 13,
                    "output_tokens": 7,
                    "total_tokens": 20,
                },
            )
        }


def make_suite():
    checks = [
        d for d in load_criteria()["checks"].values() if "interpret" in d["nodes"]
    ]
    items = []
    for definition in checks:
        if definition["id"] == "N-F.1":
            continue
        item = {
            "id": definition["id"],
            "check": definition["id"],
            "value": "요청의 지역 확인",
        }
        row = select_rows(
            definition,
            {"node": "interpret", "role": "interpretation"},
            {"name": "Interpretation"},
        )["rows"][0]
        if row["applicability"] != "항상":
            item.update(
                applicable=False, reason="시험 입력에 자료 참조·외부 지시가 없음"
            )
        items.append(item)
    return {
        "schema_version": "evaluation-suite-v1",
        "id": "node-evaluator-test",
        "cases": [
            {
                "id": "interpret-test",
                "unit": "node",
                "target": "interpret",
                "role": "interpretation",
                "purpose": "시나리오 실행과 독립 채점 연결 시험",
                "initial": {
                    "request": {"goal": "지역 확인"},
                    "event": "analysis_pipeline",
                    "messages": [{"type": "human", "content": "지역 확인", "id": "m1"}],
                },
                "assessment": {
                    "required": True,
                    "checks": [d["id"] for d in checks],
                    "expected": {
                        "schema_version": "node-expectations-v1",
                        "items": items,
                    },
                },
            }
        ],
    }


async def run_saved(tmp_path, *, repeat=1, unit="node"):
    suite = make_suite()
    if unit == "selection":
        suite["cases"][0].update(unit="selection", target="act")
        suite["cases"][0]["assessment"] = {"checks": ["N-F.1"]}
        outputs = [
            {
                "name": "query_data",
                "arguments_json": json.dumps({"target": "analysis_result"}),
                "reason": "판단에서 지정한 자료 조회",
            }
        ]
    else:
        outputs = [
            {
                "request": {"goal": "지역 확인", "constraints": {}},
                "reason": "요청의 지역 확인",
            }
        ] * repeat
    model = ScriptedModel(outputs)
    folder = await run_suite(
        suite, Settings(_env_file=None), tmp_path, model=model, repeat=repeat
    )
    return folder, model


def read(path):
    return load_assessment(path) if path.is_dir() else read_document(path)


def stored_bytes(folder):
    return {
        path.relative_to(folder): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
    }


async def test_run_rules_llm_are_separate_and_preserve_original_evidence(tmp_path):
    folder, service_model = await run_saved(tmp_path)
    originals = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    inputs = deepcopy(service_model.inputs)

    rules = read(await score_nodes(folder))
    assert rules["method"] == "rules"
    assert rules["assessments"][0]["checks"][0]["verdict"] == "통과"
    assert rules["runs"][0]["verdict"] == "미판정"
    assert rules["judge_trace"]["spans"][0]["kind"] == "evaluation"
    assert not any(s["kind"] == "model" for s in rules["judge_trace"]["spans"])

    judge = Judge()
    full = read(await score_nodes(folder, method="all", model=judge))
    assert full["judge_model"] is None
    assert full["runs"][0]["verdict"] == "통과"
    assert full["nodes"][0]["functional"]["cases"]["rate"] == 1
    assert full["nodes"][0]["operational"]["model_calls"]["mean"] == 1
    assert len(judge.calls) > 0
    assert sum(s["kind"] == "model" for s in full["judge_trace"]["spans"]) == len(
        judge.calls
    )
    assert service_model.inputs == inputs
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    assert full["provenance"][0]["case_criteria"] == "same"
    assert all(
        v["status"] == "same" for v in full["provenance"][0]["documents"].values()
    )
    assert "node-expectations-v1" not in str(service_model.inputs)


async def test_missing_repeat_is_incomplete_and_not_counted_as_completed_case(tmp_path):
    folder, _ = await run_saved(tmp_path, repeat=2)
    batch = read(folder / "batch.json")
    missing = folder / batch["runs"][1]["path"]
    missing.unlink()
    scored = read(await score_nodes(folder, method="all", model=Judge()))
    assert [r["verdict"] for r in scored["runs"]] == ["통과", "미판정"]
    cases = scored["nodes"][0]["functional"]["cases"]
    assert cases["denominator"] == 0
    assert cases["undetermined"] == 1


async def test_scoring_changed_expectation_records_original_and_new_criteria(tmp_path):
    folder, _ = await run_saved(tmp_path)
    first = await score_nodes(folder)
    before = stored_bytes(first)
    suite = read(folder / "suite.json")
    suite["cases"][0]["assessment"]["expected"]["items"][0]["reason"] = "바뀐 시험 근거"
    (folder / "suite.json").write_text(json.dumps(suite), encoding="utf-8")
    second = read(await score_nodes(folder))
    assert second["provenance"][0]["case_criteria"] == "changed"
    assert stored_bytes(first) == before


async def test_rescoring_legacy_answers_preserves_llm_prompt_and_item_mapping(tmp_path):
    folder, _ = await run_saved(tmp_path)
    suite = read(folder / "suite.json")
    suite["cases"][0]["assessment"] = {
        "required": True,
        "checks": ["N01-O.2"],
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [{"id": "preserved-item", "check": "N01-O.2"}],
        },
    }
    (folder / "suite.json").write_text(json.dumps(suite), encoding="utf-8")
    judge = Judge()
    first = read(await score_nodes(folder, method="all", model=judge))
    oracle = "SAVED_ORACLE_MUST_NOT_REACH_JUDGE"
    assessment = suite["cases"][0]["assessment"]
    assessment["expected"]["items"][0].update(
        value=oracle,
        path="/" + oracle,
        match="equal",
        pattern=oracle,
        extract="text",
        applicable=False,
        reason=oracle,
        tolerance={"absolute": 999},
    )
    assessment.update(
        reference={"N01-O.2": oracle},
        tolerance={"N01-O.2": {"absolute": 999}},
    )
    (folder / "suite.json").write_text(json.dumps(suite), encoding="utf-8")
    second = read(await score_nodes(folder, method="all", model=judge))
    assert first["runs"][0]["verdict"] == second["runs"][0]["verdict"] == "통과"
    assert len(judge.calls) == 2 and judge.calls[0] == judge.calls[1]
    assert oracle not in "\n".join(message.content for message in judge.calls[1])
    first_check = first["assessments"][0]["checks"][0]
    second_check = second["assessments"][0]["checks"][0]
    assert (
        first_check["calls"][0]["judge"]["prompt"]
        == second_check["calls"][0]["judge"]["prompt"]
    )
    assert [item["id"] for item in second_check["details"]] == ["preserved-item"]
    assert all(
        path.startswith("/evidence/") for path in second_check["details"][0]["evidence"]
    )


async def test_judge_error_is_unjudged_and_does_not_increase_service_failure_rate(
    tmp_path,
):
    folder, _ = await run_saved(tmp_path)
    scored = read(await score_nodes(folder, method="all", model=Judge(TimeoutError())))
    assert scored["runs"][0]["verdict"] == "미판정"
    assert scored["nodes"][0]["operational"]["failure_rate"]["rate"] == 0
    assert any(
        s.get("error", {}).get("type") == "TimeoutError"
        for s in scored["judge_trace"]["spans"]
    )


async def test_cancellation_saves_partial_judge_record_and_propagates(tmp_path):
    folder, _ = await run_saved(tmp_path)
    destination = folder / "cancelled"
    with pytest.raises(asyncio.CancelledError):
        await score_nodes(
            folder, destination, method="all", model=Judge(asyncio.CancelledError())
        )
    saved = read(destination)
    assert saved["status"] == "cancelled"
    assert saved["nodes"][0]["functional"]["complete"] is False
    assert saved["assessments"][0]["checks"][0]["verdict"] == "통과"
    assert saved["runs"][0]["complete"] is False
    calls = [
        call
        for check in saved["assessments"][0]["checks"]
        for call in check["calls"]
        if "judge" in call
    ]
    assert len(calls) == 1
    judge = calls[0]["judge"]
    assert judge["error"] == {"type": "CancelledError"}
    assert judge["prompt"]["criteria"]
    assert judge["response"] is judge["raw_response"] is judge["model_usage"] is None
    assert judge["executed"]
    assert all(detail["verdict"] == "미판정" for detail in judge["details"])


async def test_selection_does_not_increase_node_execution_metrics(tmp_path):
    folder, _ = await run_saved(tmp_path, unit="selection")
    scored = read(await score_nodes(folder))
    assert scored["nodes"] == []
    assert scored["assessments"][0]["counted"] is False


async def test_no_existing_evidence_or_assessment_can_be_overwritten(tmp_path):
    folder, _ = await run_saved(tmp_path)
    destination = folder / "suite.json"
    before = destination.read_bytes()
    judge = Judge()
    with pytest.raises(FileExistsError):
        await score_nodes(folder, destination, method="all", model=judge)
    assert destination.read_bytes() == before
    assert judge.calls == []


async def test_single_node_scope_excludes_other_expected_occurrences(tmp_path):
    folder, _ = await run_saved(tmp_path)
    suite = read(folder / "suite.json")
    items = suite["cases"][0]["assessment"]["expected"]["items"]
    original = next(item for item in items if item.get("applicable") is not False)
    items.append(
        {**original, "id": "second-interpret", "node": "interpret", "occurrence": 2}
    )
    (folder / "suite.json").write_text(json.dumps(suite), encoding="utf-8")
    scored = read(await score_nodes(folder, method="all", model=Judge()))
    assert scored["runs"][0]["verdict"] == "통과"
    assert scored["runs"][0]["unmatched_expectations"] == []
    assert scored["nodes"][0]["functional"]["complete"] is True


def test_agent_run_keeps_missing_explicit_occurrence_unknown():
    case = make_suite()["cases"][0]
    case.update(unit="agent", target="interpretation")
    case["assessment"]["checks"] = ["N01-O.2"]
    case["assessment"]["expected"]["items"] = [
        {
            "id": "missing-second",
            "check": "N01-O.2",
            "node": "interpret",
            "occurrence": 2,
        },
    ]
    observed = {
        "node": "interpret",
        "role": "interpretation",
        "occurrence": 1,
        "calls": [{"name": "Interpretation"}],
    }
    result = _run_result(case, 1, None, [], [observed], load_criteria())
    assert result["verdict"] == "미판정"
    assert result["unmatched_expectations"] == ["missing-second"]


@pytest.mark.parametrize("stage", [None, "selection_review"])
def test_report_single_call_scope_excludes_draft_expectations(stage):
    case = {
        "id": "review",
        "unit": "node",
        "target": "compose",
        "role": "report_selection",
        "assessment": {
            "checks": ["N04-O.1", "N04-O.3"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {"id": "draft", "check": "N04-O.1", "call": "ReportSelection"},
                    {"id": "review", "check": "N04-O.3", "call": "Verification"},
                ],
            },
        },
    }
    if stage is not None:
        case["model_call"] = stage
    observed = {
        "node": "compose",
        "role": "report_selection",
        "occurrence": 1,
        "calls": [{"name": "Verification", "index": 1}],
    }
    assessment = {
        "node_id": "n",
        "verdict": "통과",
        "complete": True,
        "checks": [{"check": "N04-O.3"}],
    }
    result = _run_result(case, 1, None, [assessment], [observed], load_criteria())
    assert result["verdict"] == "통과"
    assert result["unmatched_expectations"] == []


def test_missing_declared_check_without_expectation_cannot_pass_agent_run():
    case = make_suite()["cases"][0]
    case.update(unit="agent", target="interpretation")
    case["assessment"] = {"checks": ["N-F.1", "N04-O.1"]}
    assessment = {
        "node_id": "n",
        "verdict": "통과",
        "complete": True,
        "checks": [{"check": "N-F.1"}],
    }
    result = _run_result(case, 1, None, [assessment], [], load_criteria())
    assert result["verdict"] == "미판정"
    assert not result["complete"]
    assert result["unmatched_checks"] == ["N04-O.1"]


def test_missing_nonapplicable_expectation_still_needs_actual_call_evidence():
    case = make_suite()["cases"][0]
    case.update(unit="agent", target="interpretation")
    case["assessment"] = {
        "checks": ["N-O.1"],
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [
                {"id": "seen", "check": "N-O.1", "node": "act", "occurrence": 1},
                {
                    "id": "missing-na",
                    "check": "N-O.1",
                    "node": "act",
                    "occurrence": 2,
                    "applicable": False,
                    "reason": "숫자가 없는 상황을 계획함",
                },
            ],
        },
    }
    observed = {
        "node": "act",
        "role": "interpretation",
        "occurrence": 1,
        "calls": [{"name": "Selection"}],
    }
    assessment = {
        "node_id": "n",
        "verdict": "통과",
        "complete": True,
        "checks": [{"check": "N-O.1"}],
    }
    result = _run_result(case, 1, None, [assessment], [observed], load_criteria())
    assert result["verdict"] == "미판정"
    assert not result["complete"]
    assert result["unmatched_expectations"] == ["missing-na"]


def test_default_report_schema_survives_when_no_requested_check_targets_it():
    case = {
        "id": "review-only",
        "unit": "node",
        "target": "compose",
        "role": "report_selection",
        "assessment": {
            "checks": ["N04-O.1"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {"id": "draft", "check": "N04-O.1", "call": "ReportSelection"},
                ],
            },
        },
    }
    report = {
        "trace": {
            "spans": [
                {
                    "id": "n",
                    "kind": "node",
                    "name": "compose",
                    "input": {
                        "role": "report_selection",
                        "evaluation_scope": "model_output",
                    },
                },
                {
                    "id": "m",
                    "parent_id": "n",
                    "kind": "model",
                    "name": "Verification",
                    "input": {"messages": []},
                    "output": {
                        "sdk_response": {"text": '{"accepted":true,"reason":"적합"}'}
                    },
                },
            ]
        }
    }
    scope = []
    catalog = load_criteria()
    nodes = extract_nodes(report, case, catalog=catalog, scope=scope)
    assert nodes == []
    assert scope[0]["calls"][0]["name"] == "Verification"
    result = _run_result(case, 1, None, [], nodes, catalog, scope=scope)
    assert result["verdict"] == "미판정"
    assert result["unmatched_expectations"] == []
    assert result["node_ids"] == []
    assert result["reason"] == "선택한 모델 호출에 평가할 요청 검사가 없습니다."


def test_cli_requires_explicit_judge_model_before_any_model_call():
    assert main(["score-nodes", "unused", "--method", "all"]) == 2
    assert main(["score-nodes", "unused", "--judge-model", "forbidden"]) == 2


def test_suite_rejects_duplicate_expectation_ids_and_wrong_scope():
    from eval.schema import suite_adapter

    suite = make_suite()
    items = suite["cases"][0]["assessment"]["expected"]["items"]
    items.append(deepcopy(items[0]))
    with pytest.raises(ValueError, match="중복"):
        suite_adapter.validate_python(suite)
    items.pop()
    items[-1]["node"] = "ask"
    with pytest.raises(ValueError, match="범위"):
        suite_adapter.validate_python(suite)


def test_suite_can_select_one_check_without_removing_other_expectation_data():
    from eval.schema import suite_adapter

    suite = make_suite()
    suite["cases"][0]["assessment"]["checks"] = ["N-F.1"]
    normalized = suite_adapter.validate_python(suite)
    assert (
        normalized["cases"][0]["assessment"]["expected"]
        == suite["cases"][0]["assessment"]["expected"]
    )


async def test_selected_check_only_calls_its_judge_and_preserves_source(tmp_path):
    folder, service = await run_saved(tmp_path)
    source = (folder / "suite.json").read_bytes()
    model = Judge()
    scored = read(
        await score_nodes(
            folder,
            method="all",
            model=model,
            check_ids=["N01-O.2"],
            row_ids=["N01-O.2/general"],
            case_ids=["interpret-test"],
        )
    )
    assert len(model.calls) == 1
    assert len(service.inputs) == 1
    assert (folder / "suite.json").read_bytes() == source
    assert [c["check"] for c in scored["assessments"][0]["checks"]] == ["N01-O.2"]
    assert scored["selection"]["case_ids"] == ["interpret-test"]
    assert scored["selection"]["decisions"][0]["row_ids"] == ["N01-O.2/general"]


async def test_saved_json_keeps_repetitions_call_identity_and_original_judgments(
    tmp_path,
):
    folder, _ = await run_saved(tmp_path, repeat=2)
    judge = Judge()
    judge.model_name = "inferred-model"
    destination = await score_nodes(
        folder,
        method="all",
        model=judge,
        judge_model="chosen-evaluator",
        row_ids=["N01-O.2/general"],
    )
    assert destination.parent == folder / "assessments"
    assert destination.is_file()
    restored = read(destination)
    assert restored == json.loads(destination.read_text(encoding="utf-8"))
    assert restored["method"] == "all"
    assert restored["judge_model"] == "chosen-evaluator"
    stored = restored["assessments"]
    assert [record["repetition"] for record in stored] == [1, 2]
    assert all(record["case_id"] == "interpret-test" for record in stored)
    assert len({record["run_id"] for record in stored}) == 2
    for record in stored:
        call = record["checks"][0]["calls"][0]
        assert call["name"] == "Interpretation"
        assert call["row_id"] == "N01-O.2/general"
        original = call["judge"]["response"]
        assert original["details"][0]["id"] == "항목 1"
        assert json.loads(call["judge"]["raw_response"]["content"]) == original
        assert call["judge"]["model_usage"]["tokens"]["total_tokens"] == 20
        assert call["judge"]["details"][0]["id"] == "N01-O.2"
        prompt = call["judge"]["prompt"]
        assert prompt["criteria"]
        assert call["index"] == 1


@pytest.mark.parametrize("attribute", ["model_name", "model"])
async def test_direct_python_call_records_only_explicit_model_name(tmp_path, attribute):
    folder, _ = await run_saved(tmp_path)
    judge = Judge()
    setattr(judge, attribute, "configured-evaluator")
    scored = read(
        await score_nodes(
            folder, method="all", model=judge, row_ids=["N01-O.2/general"]
        )
    )
    assert scored["judge_model"] == "configured-evaluator"


@pytest.mark.parametrize("model_name", ["", " ", 3, {}])
async def test_invalid_explicit_model_identity_is_rejected_before_judge(
    tmp_path, model_name
):
    judge = Judge()
    with pytest.raises(ValueError, match="모델 식별자"):
        await score_nodes(tmp_path, method="all", model=judge, judge_model=model_name)
    assert judge.calls == []


async def test_nonmatching_row_excludes_case_without_judge_or_metrics(tmp_path):
    folder, _ = await run_saved(tmp_path)
    judge = Judge()
    scored = read(
        await score_nodes(
            folder, method="all", model=judge, row_ids=["N-F.1/compose-description"]
        )
    )
    assert judge.calls == []
    assert scored["assessments"] == scored["nodes"] == scored["runs"] == []
    assert scored["selection"]["case_ids"] == []
    assert all(d["status"] == "excluded" for d in scored["selection"]["decisions"])


async def test_repetitions_excluded_by_actual_tool_do_not_become_missing(tmp_path):
    suite = make_suite()
    case = suite["cases"][0]
    case.update(target="act")
    case["assessment"] = {"checks": ["N-F.1"], "required": True}
    responses = [
        {"name": tool, "arguments_json": "{}", "reason": "요청 처리"}
        for tool in ("query_data", "validate_visualization")
    ]
    folder = await run_suite(
        suite,
        Settings(_env_file=None),
        tmp_path,
        model=ScriptedModel(responses),
        repeat=2,
    )
    scored = read(await score_nodes(folder, row_ids=["N-F.1/act-other"]))
    assert [run["repetition"] for run in scored["runs"]] == [1]
    node = scored["nodes"][0]
    assert node["runs"] == 1
    summary = node["functional"]["cases"]["items"][0]
    assert summary["excluded_repetitions"] == [2]
    assert summary["missing_repetitions"] == []
    assert summary["missing_expectations"] == []
    assert node["operational"]["model_calls"]["sample_count"] == 1


async def test_unknown_filter_rejected_before_judge(tmp_path):
    folder, _ = await run_saved(tmp_path)
    judge = Judge()
    with pytest.raises(ValueError, match="없는 ID"):
        await score_nodes(folder, method="all", model=judge, row_ids=["missing"])
    assert judge.calls == []


async def test_filtered_cancellation_keeps_all_selected_repetitions_pending(tmp_path):
    folder, _ = await run_saved(tmp_path, repeat=2)
    destination = folder / "selected-cancelled"
    judge = Judge(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await score_nodes(
            folder,
            destination,
            method="all",
            model=judge,
            row_ids=["N01-O.2/general"],
        )
    saved = read(destination)
    assert len(judge.calls) == 1
    assert [run["repetition"] for run in saved["runs"]] == [1, 2]
    assert all(run["verdict"] == "미판정" for run in saved["runs"])
    summary = saved["nodes"][0]["functional"]["cases"]
    assert summary["denominator"] == 0
    assert summary["items"][0]["incomplete_repetitions"] == [1, 2]
    assert summary["items"][0]["excluded_repetitions"] == []
    assert len(saved["selection"]["run_cases"]) == 2


def test_cli_forwards_case_check_and_row_filters(monkeypatch, capsys):
    calls = []

    async def score(*args, **kwargs):
        calls.append(kwargs)
        return "selected.json"

    monkeypatch.setattr("eval.nodes.scoring.score_nodes", score)
    assert (
        main(
            [
                "score-nodes",
                "saved-batch",
                "--case",
                "one",
                "--check",
                "N-F.1",
                "--row",
                "N-F.1/interpret",
            ]
        )
        == 0
    )
    assert calls[0]["case_ids"] == ["one"]
    assert calls[0]["check_ids"] == ["N-F.1"]
    assert calls[0]["row_ids"] == ["N-F.1/interpret"]
    assert "selected.json" in capsys.readouterr().out
