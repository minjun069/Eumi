"""기본 경로의 입력·근거·기대값·검사 연결에서 누락과 변조를 찾는다."""

import json
import shutil
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval.runner import prepare_state
from eval.schema import case_adapter
from eval.scripts.validate_node_dataset import (
    _load_scenario_files,
    _numeric_reference_review,
    _prompt,
    _semantic_review,
    _shift_month,
    _snapshot_checks,
    _validate_basic_scope,
    _validate_links,
    _validate_process_history,
)
from src.settings import Settings
from src.state import create_state

ROOT = Path(__file__).resolve().parents[2] / "eval/scenarios/nodes"


def _source_provenance_fixture(tmp_path, monkeypatch, captured, checked_out):
    """같은 코드를 수집 시점과 checkout 시점의 바이트 표현으로 준비한다."""
    from eval.scripts import validate_node_dataset as validator

    monkeypatch.setattr(validator, "AI_ROOT", tmp_path)
    root = tmp_path / "dataset"
    (root / "snapshots").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    capture = root / "capture_snapshot.py"
    provider = tmp_path / "src/database.py"
    capture.write_bytes(checked_out)
    provider.write_bytes(checked_out)
    source_hash = sha256(captured).hexdigest()
    snapshot = {
        "datasets": {},
        "provenance": {
            "origin": "configured_service_database_read_only_snapshot",
            "database": "service_database",
            "transaction": {"read_only": "on", "isolation": "repeatable read"},
            "dataset_sha256": {},
            "sources": {},
            "region_query": {"query_result_sha256": sha256(b"[]").hexdigest()},
            "capture_script_sha256": source_hash,
            "service_provider_sha256": source_hash,
        },
    }
    (root / "snapshots/data.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (root / "snapshots/raw-query-results.json").write_text(
        json.dumps({"regions": [], "sources": {}}), encoding="utf-8"
    )
    return root, capture, provider, snapshot


@pytest.mark.parametrize("captured_ending", [b"\n", b"\r\n"])
@pytest.mark.parametrize("checkout_ending", [b"\n", b"\r\n"])
def test_snapshot_source_hash_accepts_git_line_endings_without_rewriting_evidence(
    tmp_path, monkeypatch, captured_ending, checkout_ending
):
    original = b"def query():\n    return 1\n"
    root, capture, provider, snapshot = _source_provenance_fixture(
        tmp_path,
        monkeypatch,
        original.replace(b"\n", captured_ending),
        original.replace(b"\n", checkout_ending),
    )
    files = [capture, provider, *sorted((root / "snapshots").iterdir())]
    before = {path: path.read_bytes() for path in files}
    errors, report = [], {"files_sha256": {}}

    def check(condition, *detail):
        if not condition:
            errors.append(detail)

    assert _snapshot_checks(root, report, check) == snapshot
    assert errors == []
    assert {path: path.read_bytes() for path in files} == before
    for path in (root / "snapshots").iterdir():
        assert (
            report["files_sha256"][path.relative_to(root).as_posix()]
            == sha256(before[path]).hexdigest()
        )


@pytest.mark.parametrize("source", ["capture", "provider"])
@pytest.mark.parametrize(
    "changed",
    [
        b"def query():\n    return 2\n",
        b"def query():\n    return 1 \n",
        b"def query():\n    return 1",
        b"\xef\xbb\xbfdef query():\n    return 1\n",
        b"def query():\r    return 1\r",
        b"def query():\r\r\n    return 1\r\r\n",
    ],
)
def test_snapshot_source_hash_rejects_changes_beyond_git_line_endings(
    tmp_path, monkeypatch, source, changed
):
    original = b"def query():\r\n    return 1\r\n"
    root, capture, provider, snapshot = _source_provenance_fixture(
        tmp_path, monkeypatch, original, original
    )
    (capture if source == "capture" else provider).write_bytes(changed)
    errors = []

    def check(condition, *detail):
        if not condition:
            errors.append(detail)

    assert _snapshot_checks(root, {"files_sha256": {}}, check) == snapshot
    expected = (
        "capture_script_sha256" if source == "capture" else "service_provider_sha256"
    )
    assert errors == [(expected, "snapshot")]


@pytest.mark.asyncio
async def test_prompt_validation_uses_shared_preparation_without_running_node(
    execution_case, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("입력 검증에서 업무 노드 실행은 허용하지 않는다")

    monkeypatch.setattr("src.graph.run_node", forbidden)
    monkeypatch.setattr("src.agent_nodes.build_nodes", forbidden)
    case, settings = execution_case
    original = deepcopy(case)
    baseline = await _prompt(case, {"datasets": {}}, settings)
    assert baseline["schema"]["title"] == "Decision"
    assert baseline["messages"]
    assert baseline["terminal"] is None
    assert case == original


@pytest.mark.asyncio
async def test_prompt_validation_marks_no_model_without_completing_report(monkeypatch):
    from eval.tests.test_evaluation_runner import report_suite

    def forbidden(*_args, **_kwargs):
        pytest.fail("입력 검증에서 보고서 완료 처리는 허용하지 않는다")

    monkeypatch.setattr("src.agent_nodes.complete_report_stage", forbidden)
    suite = report_suite("node", "compose")
    case = suite["cases"][0]
    case["role"] = "report_selection"
    case["initial"]["execution_error"] = {
        "code": "execution_limit_exceeded",
        "cause": "이미 종료 정리 중",
    }
    before = deepcopy(case)
    result = await _prompt(case, suite, Settings(_env_file=None))
    assert result["messages"] is None
    assert result["terminal"] == "no_model_call"
    assert case == before


@pytest.fixture
def execution_case():
    settings = Settings(_env_file=None)
    request = {"goal": "이미 확보한 점수의 차이를 설명한다."}
    state = create_state(
        request, settings, messages=[], event="user_request", version="fixture-v2"
    )
    state["execution"]["status"] = "running"
    state["execution"]["budget"]["steps"]["used"] = 3
    state["execution"]["error"] = {"code": "fixture_error", "cause": "앞선 호출 오류"}
    return {
        "id": "restore-execution",
        "unit": "node",
        "target": "decide",
        "purpose": "현재 실행 메타데이터를 노드 입력에 보존한다.",
        "role": "request",
        "initial": {
            "request": state["request"],
            "messages": [],
            "event": "user_request",
            "execution": state["execution"],
        },
    }, settings


def test_initial_execution_preserves_metadata_and_copies_each_run(execution_case):
    case, settings = execution_case
    case = case_adapter.validate_python(case)
    original = deepcopy(case)
    expected = deepcopy(case["initial"]["execution"])
    expected["run_id"] = "current-evaluation"
    first = prepare_state(case, settings, "current-evaluation")
    assert first["execution"] == expected
    first["execution"]["budget"]["steps"]["used"] += 1
    second = prepare_state(case, settings, "current-evaluation")
    assert second["execution"] == expected
    assert case == original


@pytest.mark.parametrize(
    "change", ["event", "budget", "execution_error", "unknown_field"]
)
def test_initial_execution_rejects_conflicting_or_unknown_metadata(
    execution_case, change
):
    case, _ = execution_case
    initial = case["initial"]
    if change == "event":
        initial["execution"]["event"] = "analysis_pipeline"
    elif change == "unknown_field":
        initial["execution"]["evaluation_only"] = True
    else:
        initial[change] = (
            deepcopy(initial["execution"]["budget"]) if change == "budget" else None
        )
    with pytest.raises(ValidationError):
        case_adapter.validate_python(case)


def test_legacy_initial_budget_and_error_still_work(execution_case):
    case, settings = execution_case
    initial = case["initial"]
    execution = initial.pop("execution")
    initial["budget"] = deepcopy(execution["budget"])
    initial["execution_error"] = deepcopy(execution["error"])
    state = prepare_state(case_adapter.validate_python(case), settings, "legacy-run")
    assert state["execution"]["status"] == "queued"
    assert state["execution"]["budget"] == execution["budget"]
    assert state["execution"]["error"] == execution["error"]
    assert state["execution"]["run_id"] == "legacy-run"


def test_calendar_query_boundary_can_fall_outside_observed_month_map():
    assert _shift_month("2025-09-01", -2) == "2025-07-01"
    assert _shift_month("2026-02-01", -2) == "2025-12-01"


@pytest.fixture
def history():
    from eval.scripts.node_dataset_users import record
    from src.agent_nodes import process_arguments
    from src.tools.process import process_data
    from src.tools.query import query_data

    snapshot = json.loads((ROOT / "snapshots/data.json").read_text(encoding="utf-8"))
    target, selected = "public.region_result", snapshot["selection"]
    providers = {target: lambda: deepcopy(snapshot["datasets"][target])}
    records = []
    for identity, month in (
        ("q-current", selected["month"]),
        ("q-before", selected["previous_month"]),
    ):
        arguments = {
            "target": target,
            "filters": [
                {"field": "adm_cd10", "operator": "eq", "value": selected["dong_code"]},
                {"field": "period_start", "operator": "eq", "value": month + "-01"},
            ],
        }
        records.append(
            record(identity, "query_data", arguments, query_data(arguments, providers))
        )
    arguments = {
        "input_result_id": "q-current",
        "operations": [
            {
                "operation": "join",
                "right_result_id": "q-before",
                "keys": ["adm_cd10"],
                "how": "inner",
                "fields": {"bh_score": "previous_bh_score"},
            },
            {
                "operation": "calculate",
                "method": "difference",
                "before": "previous_bh_score",
                "after": "bh_score",
                "output": "bh_change",
            },
        ],
        "decimals": 2,
    }
    result = process_data(process_arguments({"results": records}, arguments))
    return records + [record("p-change", "process_data", arguments, result)]


def validate(history, cache=None):
    errors = []

    def check(condition, name, identity, detail=""):
        if not condition:
            errors.append((name, identity, detail))

    _validate_process_history(
        history, "case/initial", check, {} if cache is None else cache
    )
    return errors


def test_real_process_history_and_nested_child_replay(history):
    assert not validate(history)
    assert not validate([{"id": "child", "output": {"results": history}}])


@pytest.mark.parametrize("change", ["row", "output_decimals", "argument_decimals"])
def test_process_replay_rejects_changed_rows_and_rounding_contract(history, change):
    process = next(item for item in history if item["id"] == "p-change")
    if change == "row":
        process["output"]["data"]["rows"][0]["bh_change"] += 1
    elif change == "output_decimals":
        process["output"]["decimals"] = None
    else:
        process["action"]["arguments"].pop("decimals")
    assert any(
        name == "history_process_output_matches_replay"
        for name, _, _ in validate(history)
    )


def test_process_replay_cannot_use_later_results(history):
    process = next(item for item in history if item["id"] == "p-change")
    history.remove(process)
    history.insert(0, process)
    assert any(name == "history_process_replay" for name, _, _ in validate(history))


def test_cached_replay_still_compares_each_authored_output(history):
    cache = {}
    assert not validate(history, cache)
    process = next(item for item in history if item["id"] == "p-change")
    process["output"]["data"]["rows"][0]["bh_change"] += 1
    assert any(
        name == "history_process_output_matches_replay"
        for name, _, _ in validate(history, cache)
    )


@pytest.fixture
def shared_links():
    """한 노드 사례를 두 업무 경로에서 다시 사용하는 연결 자료."""
    case = {
        "id": "shared-case",
        "unit": "node",
        "target": "act",
        "role": "interpretation",
        "initial": {"event": "user_request"},
        "assessment": {"reference": {"scope": "query"}},
    }
    refs = {
        "input_ref": "act.json#/cases/0/initial",
        "expectation_ref": "act.json#/cases/0/assessment",
    }
    scenarios = [
        {
            "id": identity,
            "event": "user_request",
            "steps": [
                {
                    "step_id": "s001",
                    "case_id": case["id"],
                    "node": "act",
                    "role": "interpretation",
                    "expected_next_nodes": ["decide"],
                    "model_outputs": [{"name": "query_data"}],
                    **refs,
                }
            ],
        }
        for identity in ("path-a", "path-b")
    ]
    index = {
        case["id"]: {
            "node": "act",
            "role": "interpretation",
            **refs,
            "usages": [
                {"scenario_id": scenario["id"], "step_id": "s001"}
                for scenario in scenarios
            ],
            "partial_usages": [],
            "aliases": ["original-case"],
            "model_call_counts": [1],
            "model_call_count": 1,
        }
    }
    sidecar = {
        "scenarios": scenarios,
        "partial_groups": [],
        "case_index": index,
        "summary": {
            "complete_scenario_count": 2,
            "unique_node_case_count": 1,
            "path_node_execution_count": 2,
            "preparation_node_execution_count": 0,
            "partial_group_count": 0,
            "partial_only_node_case_count": 0,
            "shared_node_case_count": 1,
            "runtime_only_node_case_count": 0,
            "path_runtime_only_execution_count": 0,
            "by_node": {"act": 1},
            "by_role": {"interpretation": 1},
            "by_event": {"user_request": 1},
            "scenarios_by_event": {"user_request": 2},
        },
    }
    return [{"cases": [case]}], sidecar


def validate_links(suites, sidecar):
    errors, report = [], {}

    def check(condition, name, identity, detail=""):
        if not condition:
            errors.append((name, identity, detail))

    references = _validate_links(suites, sidecar, report, check)
    return errors, references, report


def test_shared_case_links_preserve_each_usage_without_counting_two_cases(shared_links):
    errors, references, report = validate_links(*shared_links)
    assert not errors
    assert len(references["shared-case"]) == 2
    assert report["summary"]["unique_node_case_count"] == 1
    assert report["summary"]["path_node_execution_count"] == 2


def test_parent_preparation_count_is_separate_from_cases_and_path_usages(shared_links):
    suites, sidecar = shared_links
    for path in sidecar["scenarios"]:
        path["entry_transition"] = {
            "kind": "agent_call",
            "parent_steps": [{"node": node} for node in ("interpret", "decide", "act")],
        }
    sidecar["summary"]["preparation_node_execution_count"] = 6

    errors, references, report = validate_links(suites, sidecar)

    assert not errors
    assert len(references["shared-case"]) == 2
    assert report["summary"]["preparation_node_execution_count"] == 6
    assert report["summary"]["unique_node_case_count"] == 1
    assert report["summary"]["path_node_execution_count"] == 2
    assert report["summary"]["by_node"] == {"act": 1}


@pytest.mark.parametrize(
    "change", ["missing_reverse", "unknown_forward", "wrong_pointer"]
)
def test_shared_case_links_reject_one_sided_or_wrong_references(shared_links, change):
    suites, sidecar = shared_links
    entry = sidecar["case_index"]["shared-case"]
    if change == "missing_reverse":
        entry["usages"].pop()
    elif change == "unknown_forward":
        sidecar["scenarios"][0]["steps"][0]["case_id"] = "missing"
    else:
        entry["input_ref"] = "act.json#/cases/0/assessment"
    assert validate_links(suites, sidecar)[0]


def test_shared_case_can_have_multiple_authored_model_call_counts(shared_links):
    suites, sidecar = shared_links
    sidecar["scenarios"][1]["steps"][0]["model_outputs"].append({"accepted": False})
    sidecar["case_index"]["shared-case"].update(
        model_call_counts=[1, 2], model_call_count=None
    )
    assert not validate_links(suites, sidecar)[0]


def test_shared_case_rejects_different_source_transformations(shared_links):
    suites, sidecar = shared_links
    sidecar["scenarios"][1]["provenance"] = {
        "transformation": {"kind": "calendar_shift", "months": 2}
    }
    assert any(
        name == "shared_source_transformation_equal"
        for name, _, _ in validate_links(suites, sidecar)[0]
    )


@pytest.mark.parametrize(
    "counter",
    [
        "complete_scenario_count",
        "unique_node_case_count",
        "path_node_execution_count",
        "preparation_node_execution_count",
    ],
)
def test_shared_case_rejects_inflated_summary_counts(shared_links, counter):
    suites, sidecar = shared_links
    sidecar["summary"][counter] += 1
    assert any(
        name == "summary_recomputed" and identity == counter
        for name, identity, _ in validate_links(suites, sidecar)[0]
    )


def test_coverage_keeps_unique_cases_and_all_path_occurrences(shared_links):
    from eval.scripts.node_dataset_coverage import build_coverage

    suites, sidecar = shared_links
    case = suites[0]["cases"][0]
    case["assessment"].update(
        checks=["N02-O.1", "N02-O.3"],
        expected={
            "schema_version": "node-expectations-v1",
            "items": [
                {
                    "id": "name",
                    "check": "N02-O.1",
                    "path": "/name",
                    "value": "query_data",
                },
                {
                    "id": "query",
                    "check": "N02-O.3",
                    "path": "/arguments_json/target",
                    "value": "source",
                },
            ],
        },
    )
    coverage = build_coverage([case], sidecar)
    row = next(
        row for row in coverage["criterion_rows"] if row["id"] == "N02-O.3/query"
    )
    assert row["case_ids"] == [case["id"]]
    assert row["counts"] == {
        "complete_scenario_count": 2,
        "unique_node_case_count": 1,
        "path_node_execution_count": 2,
    }
    assert len(row["usages"]) == 2


def test_coverage_uses_current_json_rows_and_ignores_markdown_tables(
    tmp_path, monkeypatch
):
    from eval.scripts import node_dataset_coverage

    documents = tmp_path / "eval" / "docs" / "nodes"
    documents.mkdir(parents=True)
    for source in node_dataset_coverage.DOC_ROOT.iterdir():
        if source.suffix in {".md", ".json"}:
            shutil.copyfile(source, documents / source.name)
    definitions = documents / "act.json"
    value = json.loads(definitions.read_text(encoding="utf-8"))
    identifier = value["checks"][0]["검사 ID"]
    for row in value["checks"]:
        if row["검사 ID"] == identifier:
            row["검사 항목"] = "JSON 원본의 수정된 검사 이름"
    definitions.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    markdown = documents / "act.md"
    with markdown.open("a", encoding="utf-8") as stream:
        stream.write("\n## 이전 정의\n\n| N02-O.99 | 평가에 쓰지 않는 표 |\n")
    monkeypatch.setattr(node_dataset_coverage, "AI_ROOT", tmp_path)
    monkeypatch.setattr(node_dataset_coverage, "DOC_ROOT", documents)

    sources, rows, checks = node_dataset_coverage._documents()

    assert "N02-O.99" not in checks
    assert json.loads(checks[identifier]["raw"])["checks"][0]["검사 항목"] == (
        "JSON 원본의 수정된 검사 이름"
    )
    assert checks[identifier]["source"] == "eval/docs/nodes/act.json"
    assert all(check["source"].endswith(".json") for check in checks.values())
    assert len(rows) == 57
    assert all(row["source"].endswith(".json") for row in rows)
    assert next(row for row in rows if row["id"] == "N02-O.3/query")["when"] == {
        "tools": ["query_data"]
    }
    assert len(sources) == 13
    assert all(
        not source["check_ids"] for source in sources if source["path"].endswith(".md")
    )


def test_tags_alone_do_not_map_current_criteria_and_ask_is_out_of_scope(shared_links):
    from eval.scripts.node_dataset_coverage import build_coverage

    suites, sidecar = shared_links
    case = suites[0]["cases"][0]
    case["tags"] = ["covers:act:case-02", "branch:act.name.query_data"]
    coverage = build_coverage([case], sidecar)
    rows = {row["id"]: row for row in coverage["criterion_rows"]}
    assert not any(row["case_ids"] for row in rows.values())
    assert rows["N02-O.1/general"]["status"] == "uncovered"
    assert rows["N05-O.1/general"]["status"] == "out_of_scope"
    assert not any(gap["kind"] == "invalid_reference" for gap in coverage["gaps"])


def test_uncertain_row_selection_is_not_reported_as_mapped(shared_links, monkeypatch):
    from eval.scripts import node_dataset_coverage

    suites, sidecar = shared_links
    case = suites[0]["cases"][0]
    case["assessment"].update(
        checks=["N02-O.1"],
        expected={
            "schema_version": "node-expectations-v1",
            "items": [
                {
                    "id": "name",
                    "check": "N02-O.1",
                    "path": "/name",
                    "value": "query_data",
                }
            ],
        },
    )
    select = node_dataset_coverage.select_rows

    def uncertain(*args, **kwargs):
        result = select(*args, **kwargs)
        result["missing_context"] = ["조건을 확정할 수 없음"]
        return result

    monkeypatch.setattr(node_dataset_coverage, "select_rows", uncertain)
    coverage = node_dataset_coverage.build_coverage([case], sidecar)
    assert not any(row["status"] == "mapped" for row in coverage["criterion_rows"])
    assert any(gap["kind"] == "missing_context" for gap in coverage["gaps"])


def test_internal_review_is_outside_first_call_node_assessment(shared_links):
    from eval.scripts.node_dataset_coverage import build_coverage

    suites, _ = shared_links
    case = suites[0]["cases"][0]
    case.update(target="compose", role="report_selection")
    case["assessment"].update(
        checks=["N04-O.1", "N04-O.3"],
        expected={
            "schema_version": "node-expectations-v1",
            "items": [
                {"id": "review", "check": "N04-O.3", "call": "Verification"},
                {"id": "draft", "check": "N04-O.1", "call": "ReportSelection"},
            ],
        },
    )
    rows = {row["id"]: row for row in build_coverage([case])["criterion_rows"]}
    assert rows["N04-O.1/report-selection"]["status"] == "mapped"
    assert rows["N04-O.1/report-selection"]["expectation_links"][0]["item_pointer"] == (
        "/expected/items/1"
    )
    assert rows["N04-O.3/report-selection"]["status"] == "out_of_scope"


def test_semantic_review_checks_values_without_claiming_prose_judgment(shared_links):
    suites, sidecar = shared_links
    case = suites[0]["cases"][0]
    case["assessment"] = {
        "checks": ["N02-O.1", "N02-O.2"],
        "reference": {"N02-O.1": {"allowed_name": "query_data"}},
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [
                {
                    "id": "name",
                    "check": "N02-O.1",
                    "path": "/name",
                    "value": "query_data",
                },
                {
                    "id": "reason",
                    "check": "N02-O.2",
                    "value": "요청한 자료를 조회한다.",
                },
            ],
        },
    }
    failures = []

    def check(condition, *detail):
        if not condition:
            failures.append(detail)

    report = _semantic_review([case], sidecar, check)
    assert not failures
    assert report["summary"]["structured_verdicts"] == {"통과": 2}
    assert (
        report["cases"][0]["judgment_review_items"][0]["status"]
        == "requires_content_review"
    )
    sidecar["scenarios"][0]["steps"][0]["model_outputs"][0]["name"] = "process_data"
    _semantic_review([case], sidecar, check)
    assert failures[0][0] == "authored_output_matches_structured_expectation"


def test_numeric_source_check_rejects_same_wrong_value_in_oracle_and_authored_reply(
    shared_links,
):
    suites, sidecar = shared_links
    case = suites[0]["cases"][0]
    case.update(target="compose", role="interpretation")
    case["assessment"] = {
        "checks": ["N-O.1"],
        "reference": {
            "N-O.1": {
                "target": {"dong_code": "a", "months": ["2025-11", "2025-12"]},
                "observations": {"difference": 3},
            }
        },
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [
                {
                    "id": "number",
                    "check": "N-O.1",
                    "path": "/content",
                    "pattern": r"([+-]?\d+)",
                    "extract": "number",
                    "value": 3,
                }
            ],
        },
    }
    for path in sidecar["scenarios"]:
        path["steps"][0]["model_outputs"] = [{"content": "차이는 3점이다."}]
    snapshot = {
        "datasets": {
            "public.region_result": {
                "rows": [
                    {"adm_cd10": "a", "period_start": "2025-11-01", "bh_score": 20},
                    {"adm_cd10": "a", "period_start": "2025-12-01", "bh_score": 22},
                ]
            }
        }
    }
    failures = []

    def check(condition, *detail):
        if not condition:
            failures.append(detail)

    report = _semantic_review([case], sidecar, check, snapshot)
    assert report["summary"]["structured_verdicts"] == {"통과": 2}
    assert report["summary"]["numeric_source_statuses"] == {"mismatch": 1}
    assert failures[0][0] == "numeric_expectation_matches_source"
    case["assessment"]["expected"]["items"][0]["value"] = 2
    for path in sidecar["scenarios"]:
        path["steps"][0]["model_outputs"] = [{"content": "차이는 2점이다."}]
    failures.clear()
    report = _semantic_review([case], sidecar, check, snapshot)
    assert report["summary"]["structured_verdicts"] == {"통과": 2}
    assert report["summary"]["numeric_source_statuses"] == {"mismatch": 1}
    facts = report["cases"][0]["numeric_source_comparisons"][0]["reference_facts"]
    assert facts[0]["path"] == "/reference/N-O.1/observations/difference"
    assert not facts[0]["matches"]


@pytest.fixture
def numeric_score_case(shared_links):
    suites, _ = shared_links
    case = suites[0]["cases"][0]
    case.update(target="compose", role="interpretation")
    case["assessment"] = {
        "checks": ["N-O.1"],
        "reference": {
            "N-O.1": {
                "target": {"dong_code": "1168065500", "months": ["2025-12"]},
                "observations": {"after": 53.06},
            }
        },
        "expected": {
            "schema_version": "node-expectations-v1",
            "items": [
                {
                    "id": "number",
                    "check": "N-O.1",
                    "path": "/content",
                    "pattern": r"([+-]?\d+(?:\.\d+)?)",
                    "extract": "number",
                    "value": 53.06,
                }
            ],
        },
    }
    return case


@pytest.mark.parametrize(
    ("code", "months", "observations", "value", "measurement", "row_count"),
    [
        (
            "1168065500",
            ["2025-12"],
            {"after": 53.06},
            53.06,
            "current_bh_score",
            1,
        ),
        (
            "1168065500",
            ["2025-11", "2025-12"],
            {"before": 47.82, "after": 53.06, "difference": 5.24},
            5.24,
            "month_to_month_bh_score_difference",
            2,
        ),
        (
            "1168063000",
            ["2025-11", "2025-12"],
            {"before": 58.56, "after": 54.31, "difference": -4.25},
            -4.25,
            "month_to_month_bh_score_difference",
            2,
        ),
    ],
)
def test_numeric_source_distinguishes_current_point_from_signed_comparison(
    numeric_score_case, code, months, observations, value, measurement, row_count
):
    case = numeric_score_case
    case["assessment"]["reference"]["N-O.1"].update(
        target={"dong_code": code, "months": months}, observations=observations
    )
    case["assessment"]["expected"]["items"][0]["value"] = value
    snapshot = json.loads((ROOT / "snapshots/data.json").read_text(encoding="utf-8"))

    (result,) = _numeric_reference_review(case, snapshot)

    assert result["status"] == "verified"
    assert result["measurement"] == measurement
    assert result["source_value"] == str(value)
    assert len(result["source_refs"]) == row_count
    assert len(result["reference_facts"]) == len(observations)
    assert all(fact["matches"] for fact in result["reference_facts"])


@pytest.mark.parametrize("expected_value", [53.06, 54.06])
def test_numeric_source_current_point_rejects_wrong_reference_even_when_oracle_agrees(
    numeric_score_case, expected_value
):
    case = numeric_score_case
    case["assessment"]["reference"]["N-O.1"]["observations"]["after"] = 54.06
    case["assessment"]["expected"]["items"][0]["value"] = expected_value
    snapshot = json.loads((ROOT / "snapshots/data.json").read_text(encoding="utf-8"))

    (result,) = _numeric_reference_review(case, snapshot)

    assert result["status"] == "mismatch"
    assert result["source_value"] == "53.06"
    (fact,) = result["reference_facts"]
    assert fact["path"] == "/reference/N-O.1/observations/after"
    assert fact["matches"] is False


@pytest.mark.parametrize("months", [["2025-11", "2025-12"], ["2025-07"]])
def test_numeric_source_does_not_guess_ambiguous_or_missing_current_point(
    numeric_score_case, months
):
    numeric_score_case["assessment"]["reference"]["N-O.1"]["target"]["months"] = months
    snapshot = json.loads((ROOT / "snapshots/data.json").read_text(encoding="utf-8"))

    (result,) = _numeric_reference_review(numeric_score_case, snapshot)

    assert result["status"] == "requires_content_review"
    assert result["source_value"] is None
    assert result["source_refs"] == []


@pytest.fixture
def basic_scope():
    scenarios = []
    for role in ("request", "interpretation", "visualization"):
        for condition in ("none", "new_topic", "revision", "clarification_complete"):
            scenarios.append(
                {
                    "id": role + condition,
                    "scope": "agent",
                    "agent_role": role,
                    "event": "user_request",
                    "conversation_condition": condition,
                    "start_state": {
                        "messages": [1] if condition == "none" else [1, 2, 3],
                        "results": [],
                        "response": None,
                    },
                    "steps": [],
                }
            )
            if role != "request":
                scenario = scenarios[-1]
                scenario["entry_transition"] = {
                    "kind": "agent_call",
                    "parent_role": "request",
                    "parent_start_state": deepcopy(scenario["start_state"]),
                    "parent_steps": [
                        {
                            "step_id": f"s{index:03d}",
                            "node": node,
                            "role": "request",
                        }
                        for index, node in enumerate(("interpret", "decide", "act"), 1)
                    ],
                    "call_step_id": "s003",
                    "after_state": deepcopy(scenario["start_state"]),
                    "parent_return_record_id": "parent-call",
                }
    for role in ("report_selection", "report_description", "report_insight"):
        for code in ("a", "b", "c"):
            scenarios.append(
                {
                    "id": role + code,
                    "scope": "agent",
                    "agent_role": role,
                    "event": "analysis_pipeline",
                    "region_code": code,
                    "region_name": code + "동",
                    "steps": [],
                }
            )
    return {
        "dataset_scope": "basic-agent-paths",
        "partial_groups": [],
        "scenarios": scenarios,
    }, {
        "regions": [
            {"adm_cd10": code, "adm_nm": code + "동"} for code in ("a", "b", "c")
        ]
    }


@pytest.mark.parametrize("change", [None, "condition", "region", "partial", "failure"])
def test_basic_scope_requires_exact_normal_role_context_region_combinations(
    basic_scope, change
):
    sidecar, snapshot = basic_scope
    if change == "condition":
        sidecar["scenarios"][1]["conversation_condition"] = "none"
    elif change == "region":
        sidecar["scenarios"][-1]["region_code"] = "b"
    elif change == "partial":
        sidecar["partial_groups"] = [{"id": "old"}]
    elif change == "failure":
        sidecar["scenarios"][0]["steps"] = [
            {"step_id": "s001", "model_outputs": [{"status": "failed"}]}
        ]
    failures = []

    def check(condition, *detail):
        if not condition:
            failures.append(detail)

    _validate_basic_scope(sidecar, snapshot, check)
    assert bool(failures) == (change is not None)


@pytest.mark.parametrize(
    ("change", "expected_check"),
    [
        ("missing_parent", "basic_specialist_delegated_entry"),
        ("wrong_parent_role", "basic_specialist_delegated_entry"),
        ("wrong_preparation_role", "basic_parent_preparation_scope"),
        ("missing_preparation", "basic_parent_preparation_scope"),
        ("wrong_call_step", "basic_parent_preparation_scope"),
        ("case_id", "basic_parent_preparation_scope"),
        ("input_ref", "basic_parent_preparation_scope"),
        ("expectation_ref", "basic_parent_preparation_scope"),
        ("preparation_in_state", "basic_preparation_metadata_outside_state"),
        ("preparation_in_results", "basic_preparation_metadata_outside_state"),
        ("parent_history_in_child", "basic_user_empty_agent_history"),
        ("delegated_request", "basic_request_top_level_entry"),
    ],
)
def test_basic_scope_distinguishes_parent_preparation_from_evaluated_child_paths(
    basic_scope, change, expected_check
):
    sidecar, snapshot = basic_scope
    child = sidecar["scenarios"][4]
    entry = child["entry_transition"]
    if change == "missing_parent":
        child.pop("entry_transition")
    elif change == "wrong_parent_role":
        entry["parent_role"] = "visualization"
    elif change == "wrong_preparation_role":
        entry["parent_steps"][0]["role"] = "interpretation"
    elif change == "missing_preparation":
        entry["parent_steps"].pop(0)
    elif change == "wrong_call_step":
        entry["call_step_id"] = "s002"
    elif change in {"case_id", "input_ref", "expectation_ref"}:
        entry["parent_steps"][0][change] = "must-not-be-evaluated"
    elif change == "preparation_in_state":
        child["start_state"]["parent_steps"] = deepcopy(entry["parent_steps"])
    elif change == "preparation_in_results":
        child["steps"] = [
            {
                "step_id": "s001",
                "before_state": {
                    "results": [{"output": {"parent_steps": entry["parent_steps"]}}]
                },
            }
        ]
    elif change == "parent_history_in_child":
        child["start_state"]["results"] = [{"decision": "interpretation"}]
    else:
        sidecar["scenarios"][0]["entry_transition"] = deepcopy(entry)
    failures = []

    def check(condition, name, *_):
        if not condition:
            failures.append(name)

    _validate_basic_scope(sidecar, snapshot, check)

    assert expected_check in failures


def _split_scenarios(tmp_path, basic_scope):
    from eval.scripts.node_dataset_storage import write_scenarios

    sidecar, _ = basic_scope
    for scenario in sidecar["scenarios"]:
        scenario["title"] = scenario["id"]
    index_path = tmp_path / "scenarios.json"
    write_scenarios(index_path, sidecar)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return index_path, index, sidecar


def test_split_scenario_validation_hashes_all_twenty_one_bodies(tmp_path, basic_scope):
    index_path, index, original = _split_scenarios(tmp_path, basic_scope)
    report, errors = {"files_sha256": {}}, []

    def check(condition, *detail):
        if not condition:
            errors.append(detail)

    restored = _load_scenario_files(index_path, index, report, check)
    assert not errors
    assert index["schema_version"] == "node-scenarios-v4"
    assert restored["scenarios"] == original["scenarios"]
    assert len(report["files_sha256"]) == 21
    for entry in index["scenarios"]:
        assert (
            report["files_sha256"][entry["file"]]
            == sha256((tmp_path / entry["file"]).read_bytes()).hexdigest()
        )


@pytest.mark.parametrize("change", ["missing_file", "wrong_id"])
def test_split_scenario_validation_records_loader_failures(
    tmp_path, basic_scope, change
):
    index_path, index, _ = _split_scenarios(tmp_path, basic_scope)
    body_path = tmp_path / index["scenarios"][0]["file"]
    if change == "missing_file":
        body_path.unlink()
    else:
        body = json.loads(body_path.read_text(encoding="utf-8"))
        body["id"] = "wrong-scenario-id"
        body_path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    report, errors = {"files_sha256": {}}, []

    def check(condition, *detail):
        if not condition:
            errors.append(detail)

    assert _load_scenario_files(index_path, index, report, check) is None
    assert errors[0][0] == "scenario_files_loaded"
    assert errors[0][1] == "scenarios.json"
    assert errors[0][2]
