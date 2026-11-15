"""실제 그래프 실행 증거로 채점하고 원본·계획·재판정을 보존한다."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from eval.__main__ import main
from eval.assessment_store import load_assessment
from eval.execution.schema import COMMON_CHECKS
from eval.execution.scoring import score_executions
from eval.runner import run_suite
from eval.scenarios.execution.generate import build_suite
from eval.schema import suite_adapter
from eval.tests.batch_fixtures import read_document
from src.settings import Settings
from tests.helpers import ScriptedModel
from tests.test_reports import ReportModel


def example_suite():
    return {
        "schema_version": "evaluation-suite-v1",
        "id": "execution-scoring",
        "cases": [
            {
                "id": "ready-answer",
                "unit": "agent",
                "target": "request",
                "purpose": "제공된 문맥으로 답하고 단계와 상태를 보존한다.",
                "initial": {
                    "request": {"goal": "제공된 지역 문맥을 설명한다"},
                    "event": "user_request",
                    "messages": [
                        {"type": "human", "content": "제공된 문맥을 설명해줘"}
                    ],
                },
                "assessment": {
                    "required": True,
                    "checks": list(COMMON_CHECKS),
                    "expected": {
                        "schema_version": "execution-expectations-v1",
                        "situation": "normal",
                        "entry": "initial",
                        "environment": "test-model/prepared",
                        "data_size": "one request",
                        "node_path": ["interpret", "decide", "compose"],
                        "execution_status": "completed",
                        "run_status": "returned",
                        "response_kind": "final",
                        "error_code": None,
                    },
                },
            }
        ],
    }


@pytest.fixture
async def executed(tmp_path):
    suite = example_suite()
    replies = [
        {"request": suite["cases"][0]["initial"]["request"], "reason": "요청 확인"},
        {"next": "compose", "reason": "제공된 정보로 응답 가능"},
        {
            "content": "제공된 문맥의 범위에서 설명합니다.",
            "artifact_ids": [],
            "status": "completed",
            "reason": "요청에 응답함",
        },
    ]
    model = ScriptedModel(replies * 2)
    return await run_suite(
        suite, Settings(_env_file=None), tmp_path, model=model, repeat=2
    )


def read(path):
    return load_assessment(path) if path.is_dir() else read_document(path)


def test_execution_input_rejects_cross_scope_and_invalid_goals():
    suite_adapter.validate_python(example_suite())
    suite = example_suite()
    suite["cases"][0]["assessment"]["checks"].append("EX-R1")
    with pytest.raises(ValidationError):
        suite_adapter.validate_python(suite)
    suite = example_suite()
    suite["execution_performance"] = [
        {
            "target": "report",
            "metric": "latency",
            "case_ids": ["ready-answer"],
        }
    ]
    with pytest.raises(ValidationError):
        suite_adapter.validate_python(suite)
    suite["execution_performance"][0].update(target="request", max_rate=0.1)
    with pytest.raises(ValidationError):
        suite_adapter.validate_python(suite)


def test_missing_operational_targets_and_prices_are_allowed_but_not_invented():
    suite = example_suite()
    suite["execution_performance"] = [
        {
            "target": "request",
            "metric": "latency",
            "case_ids": ["ready-answer"],
        }
    ]
    suite_adapter.validate_python(suite)
    suite["execution_prices"] = {
        "version": "test-rates",
        "currency": "USD",
        "models": {"test-model": {"input_per_million": -1, "output_per_million": 0}},
        "tools": {},
    }
    with pytest.raises(ValidationError):
        suite_adapter.validate_python(suite)


def test_role_diagnostics_do_not_expand_ex_expectations_or_operational_goal_scope():
    suite = example_suite()
    suite["cases"][0]["target"] = "interpretation"
    with pytest.raises(ValidationError, match="agent/request"):
        suite_adapter.validate_python(suite)
    suite["cases"][0].pop("assessment")
    suite_adapter.validate_python(suite)
    suite["execution_performance"] = [
        {
            "target": "request",
            "metric": "latency",
            "case_ids": ["ready-answer"],
        }
    ]
    with pytest.raises(ValidationError, match="실행 운영 목표"):
        suite_adapter.validate_python(suite)


@pytest.mark.asyncio
async def test_run_then_score_preserves_evidence_and_separate_reassessments(executed):
    evidence = {p: p.read_bytes() for p in executed.rglob("*") if p.is_file()}
    first = score_executions(executed)
    second = score_executions(executed)
    value = read(first)
    assert first != second
    assert value["schema_version"] == "execution-evaluation-v1"
    assert len(value["runs"]) == 2
    assert all(run["verdict"] == "통과" and run["complete"] for run in value["runs"])
    assert all(run["checks"] for run in value["runs"])
    assert all(p.read_bytes() == original for p, original in evidence.items())
    assert all(item["case_criteria"] == "same" for item in value["provenance"])
    assert value["criteria_sha256"] == read(second)["criteria_sha256"]
    with pytest.raises(FileExistsError):
        score_executions(executed, first)


@pytest.mark.asyncio
async def test_selection_and_cli_do_not_add_undeclared_checks(executed):
    value = read(score_executions(executed, check_ids=["EX-1"]))
    assert all([c["check"] for c in run["checks"]] == ["EX-1"] for run in value["runs"])
    assert main(["score-executions", str(executed), "--check", "EX-R1"]) == 2
    assert main(["score-executions", str(executed), "--case", "missing"]) == 2
    assert main(["score-executions", str(executed)]) == 0


@pytest.mark.asyncio
async def test_original_plan_retains_missing_repetition(executed):
    path = executed / "batch.json"
    batch = read(path)
    batch["plan"]["repeat"] = 3
    batch["planned_runs"] = 3
    path.write_text(json.dumps(batch), encoding="utf-8")
    value = read(score_executions(executed))
    assert len(value["runs"]) == 3
    assert value["runs"][-1]["verdict"] == "미판정"
    assert value["runs"][-1]["complete"] is False


@pytest.mark.asyncio
async def test_criteria_change_is_visible_in_reassessment(executed):
    path = executed / "suite.json"
    suite = read(path)
    original = deepcopy(suite)
    suite["cases"][0]["assessment"]["expected"]["execution_status"] = "partial"
    path.write_text(json.dumps(suite), encoding="utf-8")
    value = read(score_executions(executed))
    assert all(item["case_criteria"] == "changed" for item in value["provenance"])
    assert all(run["verdict"] == "실패" for run in value["runs"])
    assert (
        value["provenance"][0]["original_assessment"]
        == original["cases"][0]["assessment"]
    )


@pytest.mark.asyncio
async def test_output_cannot_fill_a_missing_original_evidence_file(executed):
    original = next(executed.glob("runs/*/report.json"))
    original.unlink()
    with pytest.raises(ValueError, match="runs"):
        score_executions(executed, original)
    assert not original.exists()
    value = read(score_executions(executed))
    assert any(not run["complete"] for run in value["runs"])


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", ["request-context", "request-exhausted"])
async def test_generated_request_cases_run_and_score(tmp_path, case_id):
    suite = build_suite()
    case = next(case for case in suite["cases"] if case["id"] == case_id)
    replies = (
        []
        if case_id == "request-exhausted"
        else [
            {"request": case["initial"]["request"], "reason": "요청 확인"},
            {"next": "compose", "reason": "제공된 정보로 응답 가능"},
            {
                "content": "행정동 월별 집계로 개인 상태를 판정할 수 없습니다.",
                "artifact_ids": [],
                "status": "completed",
                "reason": "제공 범위와 한계 설명",
            },
        ]
    )
    folder = await run_suite(
        suite,
        Settings(_env_file=None),
        tmp_path,
        model=ScriptedModel(replies),
        case_ids=[case_id],
    )
    value = read(score_executions(folder))
    assert value["runs"][0]["verdict"] == "통과", value["runs"][0]["checks"]
    assert value["runs"][0]["complete"]


@pytest.mark.asyncio
async def test_generated_report_reentry_scores_current_usage_and_previous_history(
    tmp_path,
):
    suite = build_suite()
    original = deepcopy(suite)
    folder = await run_suite(
        suite,
        Settings(_env_file=None),
        tmp_path,
        model=ReportModel(),
        case_ids=["report-start", "report-reentry"],
    )
    assert suite == original
    value = read(score_executions(folder))
    assert all(run["verdict"] == "통과" for run in value["runs"]), value["runs"]
    assert all(run["complete"] for run in value["runs"])
    assert [run["report_completeness"] for run in value["runs"]] == [
        "complete",
        "partial",
    ]
    assert value["summary"]["report_completion"] == {
        "numerator": 1,
        "denominator": 2,
        "rate": 0.5,
    }
    reports = [read(path) for path in folder.glob("runs/*/report.json")]
    reentry = next(
        report for report in reports if report["run"]["case_id"] == "report-reentry"
    )
    roles = [
        s["input"]["role"] for s in reentry["trace"]["spans"] if s["kind"] == "agent"
    ]
    assert roles == ["report_description", "report_insight"]
    prior = original["cases"][-1]["initial"]
    assert reentry["state"]["results"][: len(prior["results"])] == prior["results"]
    assert reentry["state"]["execution"]["budget"]["tool_calls"]["used"] == 1


@pytest.fixture
async def six_roles(tmp_path):
    suite = example_suite()
    template = suite["cases"][0]
    examples = {case["id"]: case for case in build_suite()["cases"]}
    suite["cases"] = []
    replies = []
    for role in (
        "request",
        "interpretation",
        "visualization",
        "report_selection",
        "report_description",
        "report_insight",
    ):
        case = deepcopy(template)
        case.update(id=role, target=role)
        if role == "request":
            case["assessment"]["expected"].update(
                node_path=["interpret", "decide", "ask"],
                execution_status="waiting_input",
                response_kind="question",
            )
        else:
            case.pop("assessment")
        suite["cases"].append(case)
        if role.startswith("report_"):
            case["initial"] = deepcopy(examples["report-start"]["initial"])
            case["initial"]["budget"] = deepcopy(
                examples["request-exhausted"]["initial"]["budget"]
            )
            continue
        final = (
            {"content": "어느 지역을 대상으로 하나요?", "reason": "지역 필요"}
            if role == "request"
            else {
                "content": "제공된 문맥의 범위에서 설명합니다.",
                "artifact_ids": [],
                "status": "completed",
                "reason": "요청에 응답함",
            }
        )
        replies.extend(
            [
                {"request": case["initial"]["request"], "reason": "대상 확인 필요"},
                {
                    "next": "ask" if role == "request" else "compose",
                    "reason": "현재 요청에 맞는 반환",
                },
                final,
            ]
        )
    from eval.tests.batch_fixtures import combine_batches

    folders = await run_suite(
        suite, Settings(_env_file=None), tmp_path, model=ScriptedModel(replies)
    )
    return combine_batches(folders, tmp_path / "legacy-mixed")


@pytest.mark.asyncio
async def test_mixed_six_role_batch_scores_ex_scope_and_measures_every_role(six_roles):
    original = {
        path: path.read_bytes() for path in six_roles.rglob("*") if path.is_file()
    }
    result = read(score_executions(six_roles))
    assert all(path.read_bytes() == value for path, value in original.items())
    assert [run["case_id"] for run in result["runs"]] == ["request"]
    assert result["runs"][0]["verdict"] == "통과"
    assert result["summary"]["functional"]["verification"]["required_cases"] == 1
    assert len(result["selection"]["functional_excluded"]) == 5
    assert all(item["reason"] for item in result["selection"]["functional_excluded"])
    runs = result["summary"]["operational"]["runs"]
    assert len(runs) == 6
    assert all(
        run["model_calls"] == (0 if run["target"].startswith("report_") else 3)
        for run in runs
    )
    assert {run["outcome"] for run in runs} == {
        "question",
        "completed",
        "technical_failure",
    }
    assert all(run["elapsed_seconds"] is not None for run in runs)
    assert all(run["input_tokens"] is None for run in runs if run["model_calls"])
    assert all(run["cost"] is None for run in runs)
    assert result["summary"]["report_completion"]["denominator"] == 0


@pytest.mark.asyncio
async def test_diagnostics_only_selection_retains_plan_and_never_creates_ex_checks(
    six_roles,
):
    path = six_roles / "batch.json"
    batch = read(path)
    batch["plan"]["repeat"] = 2
    batch["planned_runs"] = 12
    path.write_text(json.dumps(batch), encoding="utf-8")
    result = read(score_executions(six_roles, case_ids=["interpretation"]))
    assert result["runs"] == []
    assert result["selection"]["selected_case_ids"] == ["interpretation"]
    assert result["selection"]["functional_excluded"][0]["case_id"] == "interpretation"
    functional = result["summary"]["functional"]
    assert functional["verdict"] == "미판정" and functional["complete"] is False
    assert functional["checks"] == []
    assert functional["cases"]["denominator"] == 0
    operational = result["summary"]["operational"]
    assert operational["repetitions"][0]["planned"] == 2
    assert operational["repetitions"][0]["missing_repetitions"] == [2]
    assert operational["verdict"] == "미판정"
    with pytest.raises(ValueError, match="선언하지 않은 검사"):
        score_executions(six_roles, case_ids=["interpretation"], check_ids=["EX-1"])


@pytest.mark.asyncio
async def test_ex_check_filter_retains_other_roles_operational_diagnostics(six_roles):
    result = read(score_executions(six_roles, check_ids=["EX-1"]))
    assert [check["check"] for check in result["runs"][0]["checks"]] == ["EX-1"]
    assert len(result["runs"]) == 1
    assert len(result["summary"]["operational"]["runs"]) == 6
    assert len(result["selection"]["functional_excluded"]) == 5
