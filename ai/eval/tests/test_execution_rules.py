"""실제 업무 실행 증거와 의도적인 경계 결함으로 실행 채점기를 확인한다."""

import asyncio
from copy import deepcopy

import pytest
from langchain_core.runnables import RunnableLambda

from eval.execution.rules import assess_execution
from eval.execution.schema import COMMON_CHECKS, REPORT_CHECKS
from eval.runner import run_suite
from eval.tests.test_evaluation_runner import initial, report_suite, reports, suite
from src.settings import Settings
from tests.helpers import DONE, ScriptedModel, selection
from tests.test_reports import ReportModel


def assessed(case, checks, **expected):
    return case | {
        "assessment": {
            "checks": list(checks),
            "expected": {
                "schema_version": "execution-expectations-v1",
                "situation": "normal",
                "entry": "initial",
                **expected,
            },
        },
    }


def request_case(**changes):
    return assessed(
        {
            "id": "request",
            "unit": "agent",
            "target": "request",
            "purpose": "요청의 전달 경계를 확인한다.",
            "initial": initial(),
            **changes,
        },
        COMMON_CHECKS,
    )


def checks(result):
    return {item["check"]: item for item in result["checks"]}


def verdicts(result):
    return {key: value["verdict"] for key, value in checks(result).items()}


def nodes(report):
    return [span for span in report["trace"]["spans"] if span["kind"] == "node"]


def roles(report):
    return [
        span
        for span in report["trace"]["spans"]
        if span["kind"] == "agent" and span["input"]["role"].startswith("report_")
    ]


@pytest.fixture
async def request_run(tmp_path):
    case = request_case()
    model = ScriptedModel(
        [
            DONE,
            {
                "content": "완료",
                "artifact_ids": [],
                "status": "completed",
                "reason": "충분",
            },
        ]
    )
    folder = await run_suite(
        suite(case),
        Settings(_env_file=None),
        tmp_path,
        model=model,
    )
    return case, reports(folder)[0]


@pytest.fixture
async def report_run(tmp_path):
    value = report_suite()
    case = assessed(value["cases"][0], COMMON_CHECKS + REPORT_CHECKS)
    value["cases"] = [case]
    folder = await run_suite(
        value,
        Settings(_env_file=None, max_steps=100),
        tmp_path,
        model=ReportModel(),
    )
    return case, reports(folder)[0]


async def test_request_actual_boundaries_pass(request_run):
    case, report = request_run
    result = assess_execution(case, report)
    assert verdicts(result) == {
        "EX-1": "통과",
        "EX-2": "통과",
        "EX-3": "통과",
        "EX-4": "비적용",
        "EX-5": "통과",
    }, result
    assert result["complete"] and result["started"]


async def test_report_actual_roles_and_approved_artifacts_pass(report_run):
    case, report = report_run
    result = assess_execution(case, report)
    assert result["verdict"] == "통과", result
    assert result["complete"]
    assert result["report_completeness"] == "complete"
    assert checks(result)["EX-R3"]["verdict"] == "비적용"


@pytest.mark.parametrize("field", ["request", "results", "response", "messages"])
async def test_modified_next_state_is_delivery_failure(request_run, field):
    case, report = request_run
    changed = deepcopy(report)
    target = nodes(changed)[1]["input"]["state"]
    if field == "request":
        target[field]["goal"] = "다른 호출의 요청"
    elif field == "results":
        target[field] = []
    elif field == "response":
        target[field] = {"content": "다른 응답"}
    else:
        target[field].append({"type": "human", "content": "추가 질문", "id": "other"})
    result = assess_execution(case, changed)
    assert checks(result)["EX-2"]["verdict"] == "실패"


async def test_changed_destination_is_transition_failure(request_run):
    case, report = request_run
    changed = deepcopy(report)
    nodes(changed)[0]["output"]["goto"] = "ask"
    result = assess_execution(case, changed)
    assert checks(result)["EX-1"]["verdict"] == "실패"


async def test_failure_and_missing_evidence_are_both_preserved(request_run):
    case, report = request_run
    changed = deepcopy(report)
    nodes(changed)[0]["output"]["goto"] = "ask"
    del nodes(changed)[1]["output"]
    result = assess_execution(case, changed)
    assert checks(result)["EX-1"]["verdict"] == "실패"
    assert not checks(result)["EX-1"]["complete"]
    assert not result["complete"]


async def test_budget_reset_is_not_accepted(request_run):
    case, report = request_run
    changed = deepcopy(report)
    nodes(changed)[1]["input"]["state"]["execution"]["budget"]["steps"]["used"] = 0
    assert checks(assess_execution(case, changed))["EX-3"]["verdict"] == "실패"


async def test_caller_state_mismatch_is_not_accepted(request_run):
    case, report = request_run
    changed = deepcopy(report)
    changed["state"]["response"]["content"] = "이전 요청의 응답"
    assert checks(assess_execution(case, changed))["EX-5"]["verdict"] == "실패"


async def test_question_returns_instead_of_waiting_for_user(tmp_path):
    case = request_case()
    case["initial"]["event"] = "user_request"
    model = ScriptedModel(
        [
            {"request": case["initial"]["request"], "reason": "지역 필요"},
            {"next": "ask", "reason": "지역 필요"},
            {"content": "어느 지역인가요?", "reason": "지역 확인"},
        ]
    )
    folder = await run_suite(
        suite(case),
        Settings(_env_file=None),
        tmp_path,
        model=model,
    )
    result = assess_execution(case, reports(folder)[0])
    assert result["verdict"] == "통과", result
    assert result["complete"]


async def test_report_role_reversal_and_budget_change_fail(report_run):
    case, report = report_run
    changed = deepcopy(report)
    stage = roles(changed)[1]
    stage["input"]["role"] = "report_selection"
    stage["input"]["initial_state"]["execution"]["budget"]["agent_calls"]["used"] += 1
    result = checks(assess_execution(case, changed))
    assert result["EX-R1"]["verdict"] == "실패"
    assert result["EX-3"]["verdict"] == "실패"


async def test_report_target_and_approval_reference_change_fail(report_run):
    case, report = report_run
    changed = deepcopy(report)
    entered = roles(changed)[1]["input"]["initial_state"]
    inputs = next(r for r in entered["results"] if r["decision"] == "report_input")
    inputs["output"]["dongCode"] = "1111111111"
    stage = next(
        r for r in reversed(entered["results"]) if r["decision"] == "report_stage"
    )
    stage["action"]["arguments"]["result_ids"] = ["unapproved-draft"]
    result = checks(assess_execution(case, changed))
    assert result["EX-R2"]["verdict"] == "실패"


@pytest.mark.parametrize("field", ["graph_1", "desc_1", "quick_insight"])
async def test_report_fields_compare_to_role_output_not_own_artifact(report_run, field):
    case, report = report_run
    changed = deepcopy(report)
    changed["state"]["response"]["artifacts"][0]["data"][field] = "잘못 연결한 항목"
    result = checks(assess_execution(case, changed))
    assert result["EX-R4"]["verdict"] == "실패"


async def test_partial_report_is_valid_but_not_complete(tmp_path):
    value = report_suite()
    case = assessed(value["cases"][0], COMMON_CHECKS + REPORT_CHECKS)
    value["cases"] = [case]
    model = ReportModel(reject={"EmbedDetailV01": 10})
    folder = await run_suite(
        value,
        Settings(_env_file=None, max_steps=100),
        tmp_path,
        model=model,
    )
    report = reports(folder)[0]
    result = assess_execution(case, report)
    assert result["report_completeness"] == "partial"
    assert checks(result)["EX-R4"]["verdict"] == "통과", result
    assert checks(result)["EX-R5"]["verdict"] == "통과", result
    changed = deepcopy(report)
    composition = next(
        r
        for r in reversed(changed["state"]["results"])
        if r["decision"] == "composition" and not r["action"]
    )
    composition["output"]["status"] = "completed"
    assert checks(assess_execution(case, changed))["EX-R5"]["verdict"] == "실패"


async def test_limit_stops_work_and_shares_final_budget(tmp_path):
    case = request_case()
    model = ScriptedModel(
        [
            DONE,
            {
                "content": "한도 종료",
                "artifact_ids": [],
                "status": "partial",
                "reason": "한도",
            },
        ]
    )
    folder = await run_suite(
        suite(case),
        Settings(_env_file=None, max_steps=1),
        tmp_path,
        model=model,
    )
    report = reports(folder)[0]
    result = assess_execution(case, report)
    assert checks(result)["EX-4"]["verdict"] == "통과", result
    changed = deepcopy(report)
    changed["state"]["execution"]["budget"]["final_model_calls"]["used"] = 2
    assert checks(assess_execution(case, changed))["EX-4"]["verdict"] == "실패"


async def test_cancelled_node_is_not_treated_as_completed_return(tmp_path):
    entered = asyncio.Event()

    class WaitingModel:
        def with_structured_output(self, schema, **kwargs):
            async def wait(_messages, config):
                entered.set()
                await asyncio.Event().wait()

            return RunnableLambda(wait)

    case = request_case()
    task = asyncio.create_task(
        run_suite(
            suite(case),
            Settings(_env_file=None),
            tmp_path,
            model=WaitingModel(),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    folder = next(tmp_path.rglob("batch.json")).parent
    result = checks(assess_execution(case, reports(folder)[0]))
    assert result["EX-3"]["verdict"] == "미판정"
    assert result["EX-5"]["verdict"] == "미판정"
    assert result["EX-4"]["verdict"] == "통과", result


async def test_child_cumulative_budget_is_not_added_again(tmp_path):
    child = {
        "response": {
            "id": "child",
            "kind": "final",
            "label": "결과",
            "content": "해석",
            "artifacts": [],
        },
        "results": [],
        "status": "completed",
        "error": None,
    }
    case = request_case(
        dependencies="stub",
        stubs=[
            {
                "name": "interpretation_agent",
                "arguments": {"goal": "해석"},
                "output": child,
            }
        ],
    )
    model = ScriptedModel(
        [
            {"next": "act", "reason": "해석 필요"},
            selection("interpretation_agent", {"goal": "해석"}),
            DONE,
            {
                "content": "통합",
                "artifact_ids": [],
                "status": "completed",
                "reason": "충분",
            },
        ]
    )
    folder = await run_suite(
        suite(case),
        Settings(_env_file=None),
        tmp_path,
        model=model,
    )
    report = reports(folder)[0]
    assert checks(assess_execution(case, report))["EX-3"]["verdict"] == "통과"
    changed = deepcopy(report)
    parent = next(s for s in nodes(changed) if s["name"] == "act")
    parent["output"]["applied_update"]["execution"]["budget"]["steps"]["used"] *= 2
    assert checks(assess_execution(case, changed))["EX-3"]["verdict"] == "실패"


def test_missing_run_and_undeclared_checks_cannot_pass():
    assert assess_execution(request_case(), None)["verdict"] == "미판정"
    assert assess_execution({"id": "missing"}, {})["verdict"] == "미판정"


async def test_corrupt_journal_does_not_erase_known_failure(request_run):
    case, report = request_run
    changed = deepcopy(report)
    nodes(changed)[0]["output"]["goto"] = "ask"
    changed["trace"]["recovery_issues"] = ["truncated event"]
    result = checks(assess_execution(case, changed))
    assert result["EX-1"]["verdict"] == "실패"
    assert not result["EX-1"]["complete"]


async def test_return_without_finished_boundary_cannot_pass(request_run):
    case, report = request_run
    changed = deepcopy(report)
    root = next(s for s in changed["trace"]["spans"] if s["kind"] == "execution")
    root["ended_at"] = None
    root["status"] = "running"
    assert checks(assess_execution(case, changed))["EX-5"]["verdict"] == "미판정"


async def test_initial_message_ids_are_added_only_when_missing(tmp_path):
    case = request_case()
    case["initial"]["messages"][0]["id"] = None
    model = ScriptedModel(
        [
            DONE,
            {
                "content": "완료",
                "artifact_ids": [],
                "status": "completed",
                "reason": "충분",
            },
        ]
    )
    folder = await run_suite(
        suite(case),
        Settings(_env_file=None),
        tmp_path,
        model=model,
    )
    report = reports(folder)[0]
    assert checks(assess_execution(case, report))["EX-2"]["verdict"] == "통과"
    changed = deepcopy(report)
    nodes(changed)[1]["input"]["state"]["messages"][0]["id"] = "changed"
    assert checks(assess_execution(case, changed))["EX-2"]["verdict"] == "실패"


async def test_handled_child_error_allows_parent_partial_response(tmp_path):
    def unavailable(_):
        raise ConnectionError("child unavailable")

    case = request_case()
    model = ScriptedModel(
        [
            {"next": "act", "reason": "해석 필요"},
            selection("interpretation_agent", {"goal": "자료 확인"}),
            unavailable,
            DONE,
            {
                "content": "확인 범위",
                "artifact_ids": [],
                "status": "partial",
                "reason": "하위 오류",
            },
        ]
    )
    folder = await run_suite(
        suite(case),
        Settings(_env_file=None),
        tmp_path,
        model=model,
    )
    result = assess_execution(case, reports(folder)[0])
    assert result["verdict"] == "통과", result
    assert checks(result)["EX-4"]["verdict"] == "통과"


async def test_reentry_keeps_completed_roles_history_and_shared_budget(tmp_path):
    value = report_suite()
    case = assessed(value["cases"][0], COMMON_CHECKS + REPORT_CHECKS)
    value["cases"] = [case]
    settings = Settings(_env_file=None, max_steps=100)
    first_folder = await run_suite(
        value,
        settings,
        tmp_path / "first",
        model=ReportModel(fail_once="EmbedDetailV01"),
    )
    first = reports(first_folder)[0]["state"]
    case["initial"] = {
        "request": first["request"],
        "messages": first["messages"],
        "event": first["execution"]["event"],
        "execution": first["execution"],
        "results": first["results"],
        "response": first["response"],
    }
    case["assessment"]["expected"]["entry"] = "reentry"
    second_folder = await run_suite(
        value,
        settings,
        tmp_path / "second",
        model=ReportModel(),
    )
    report = reports(second_folder)[0]
    result = assess_execution(case, report)
    assert result["verdict"] == "통과", result
    assert checks(result)["EX-R3"]["verdict"] == "통과"
    changed = deepcopy(report)
    roles(changed)[0]["input"]["role"] = "report_selection"
    assert checks(assess_execution(case, changed))["EX-R3"]["verdict"] == "실패"


@pytest.mark.parametrize(
    "trace",
    [
        None,
        {"spans": {}},
        {"spans": [None]},
        {"spans": [{"id": "bad", "kind": [], "sequence": "wrong", "input": []}]},
    ],
)
def test_malformed_trace_returns_unjudged_instead_of_crashing(trace):
    result = assess_execution(request_case(), {"trace": trace})
    assert result["verdict"] == "미판정"
    assert not result["complete"]


async def test_removed_span_invalidates_trace_completeness(request_run):
    case, report = request_run
    changed = deepcopy(report)
    changed["trace"]["spans"].remove(nodes(changed)[0])
    result = assess_execution(case, changed)
    assert not result["complete"]
    assert all(not check["complete"] for check in result["checks"])
