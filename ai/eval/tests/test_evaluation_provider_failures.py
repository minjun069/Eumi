"""JSON 자료 공급 오류가 실제 조회·추적·독립 채점까지 전달되는지 확인한다."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from eval.assessment_store import load_assessment
from eval.runner import load_suite, run_suite
from eval.tests.batch_fixtures import read_document
from eval.tools.scoring import score_batch
from src.execution import record
from src.settings import Settings
from tests.helpers import ScriptedModel, selection

ERRORS = {
    "PermissionError": ("permission_denied", False),
    "TimeoutError": ("read_unavailable", True),
    "ConnectionError": ("read_unavailable", True),
}


def _dataset(name):
    return {
        "reference": {"id": name, "version": "fixture-v1"},
        "as_of": "2026-10",
        "sources": [{"label": "합성 평가 자료", "uri": f"fixture://{name}"}],
        "columns": [
            {
                "name": "value",
                "kind": "integer",
                "unit": "명",
                "spatial_unit": "행정동",
                "temporal_unit": "월",
                "denominator": "전체",
            }
        ],
        "rows": [{"value": 7}],
    }


def _assessment(*items):
    return {
        "required": True,
        "checks": list(dict.fromkeys(check for check, _, _ in items)),
        "reference": {"id": "independent-provider-failure-contract"},
        "expected": {
            "schema_version": "tool-expectations-v1",
            "items": [
                {"check": check, "path": path, "value": value}
                for check, path, value in items
            ],
        },
    }


def _expected_failure(error):
    code, retryable = ERRORS[error]
    return _assessment(
        ("T-I.1", "/observations/provider_calls", 1),
        ("T-O.1", "/output", None),
        ("T-O.2", "/run/status", "error"),
        ("T-O.2", "/failure/type", "ToolFailure"),
        ("T-O.2", "/failure/code", code),
        ("T-O.2", "/failure/retryable", retryable),
        ("T-O.2", "/failure/cause/type", error),
    )


def _expected_success(rows=1):
    return _assessment(
        ("T-I.1", "/observations/provider_calls", 1),
        ("T-O.1", "/output/returned", rows),
        ("T-O.1", "/output/data/rows", [{"value": 7}] if rows else []),
        ("T-O.2", "/run/status", "returned"),
        ("T-O.2", "/failure", None),
    )


def _case(case_id="query", target="alpha", **changes):
    return {
        "id": case_id,
        "unit": "tool",
        "target": "query_data",
        "purpose": "자료 공급 오류와 정상 조회를 구분한다.",
        "arguments": {"target": target},
        "assessment": _expected_success(),
    } | changes


def _suite(*cases):
    return {
        "schema_version": "evaluation-suite-v1",
        "id": "provider-failure-tests",
        "datasets": {name: _dataset(name) for name in ("alpha", "beta")},
        "cases": list(cases),
    }


def _read(path):
    return load_assessment(path) if path.is_dir() else read_document(path)


def _load_json(tmp_path, value):
    source = tmp_path / "suite.json"
    source.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return load_suite(source), source


async def _execute(tmp_path, value, *, repeat=1, model=None):
    prepared, source = _load_json(tmp_path, value)
    folder = await run_suite(
        prepared,
        Settings(_env_file=None),
        tmp_path / "runs",
        repeat=repeat,
        source_path=source,
        model=model,
    )
    batch = _read(folder / "batch.json")
    reports = [_read(folder / item["path"]) for item in batch["runs"]]
    scored = _read(score_batch(folder))
    return folder, reports, scored


def _provider_trace(report):
    return [span for span in report["trace"]["spans"] if span["kind"] == "provider"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", list(ERRORS))
async def test_json_provider_failure_runs_real_query_and_passes_expected_rejection(
    tmp_path, error
):
    case = _case(
        provider_failures={"alpha": error}, assessment=_expected_failure(error)
    )
    folder, reports, scored = await _execute(tmp_path, _suite(case))
    (report,) = reports
    code, retryable = ERRORS[error]
    assert report["run"]["status"] == "error"
    assert report["output"] is None
    assert report["failure"]["type"] == "ToolFailure"
    assert report["failure"]["code"] == code
    assert report["failure"]["retryable"] is retryable
    assert report["failure"]["cause"]["type"] == error

    (tool,) = [s for s in report["trace"]["spans"] if s["kind"] == "tool"]
    (provider,) = _provider_trace(report)
    assert tool["name"] == "query_data"
    assert tool["input"]["resolved_arguments"] == {"target": "alpha"}
    assert provider["name"] == "alpha" and provider["parent_id"] == tool["id"]
    assert provider["input"]["query"] == {"target": "alpha"}
    assert provider["error"]["type"] == error
    assert tool["error"]["code"] == code
    assert tool["error"]["cause"]["type"] == error
    assert all(s["status"] == "error" and s["ended_at"] for s in (tool, provider))
    assert all("output" not in s for s in (tool, provider))
    assert report["fixtures"] == {"calls": [], "unused": [], "unexpected": []}
    assert scored["runs"][0]["verdict"] == "통과"
    assert scored["tools"][0]["functional"]["rate"] == 1
    assert scored["tools"][0]["latency"]["error"]["sample_count"] == 1
    assert _read(folder / "suite.json")["cases"][0]["provider_failures"] == {
        "alpha": error
    }


@pytest.mark.asyncio
async def test_empty_success_and_read_failure_have_distinct_evidence_and_both_can_pass(
    tmp_path,
):
    value = _suite(
        _case(
            "empty",
            arguments={
                "target": "alpha",
                "filters": [{"field": "value", "operator": "gt", "value": 99}],
            },
            assessment=_expected_success(0),
        ),
        _case(
            "unavailable",
            provider_failures={"alpha": "TimeoutError"},
            assessment=_expected_failure("TimeoutError"),
        ),
    )
    _, (empty, failed), scored = await _execute(tmp_path, value)
    assert empty["output"]["total"] == empty["output"]["returned"] == 0
    assert empty["failure"] is None
    assert _provider_trace(empty)[0]["output"]["rows"] == [{"value": 7}]
    assert failed["output"] is None and failed["failure"]["code"] == "read_unavailable"
    assert [item["verdict"] for item in scored["runs"]] == ["통과", "통과"]
    latency = scored["tools"][0]["latency"]
    assert latency["normal"]["sample_count"] == latency["error"]["sample_count"] == 1


@pytest.mark.asyncio
async def test_two_provider_errors_and_normal_cases_are_isolated_across_repetitions(
    tmp_path,
):
    failures = {"alpha": "PermissionError", "beta": "ConnectionError"}
    value = _suite(
        _case(
            "alpha-fails",
            provider_failures=failures,
            assessment=_expected_failure("PermissionError"),
        ),
        _case(
            "beta-fails",
            target="beta",
            provider_failures=failures,
            assessment=_expected_failure("ConnectionError"),
        ),
        _case("alpha-normal"),
        _case("beta-normal", target="beta"),
    )
    original = deepcopy(value)
    _, reports, scored = await _execute(tmp_path, value, repeat=2)
    assert value == original
    assert len({r["run"]["id"] for r in reports}) == 8
    for result in reports:
        case_id = result["run"]["case_id"]
        target = "alpha" if case_id.startswith("alpha") else "beta"
        (provider,) = _provider_trace(result)
        assert provider["name"] == target
        if case_id.endswith("fails"):
            assert provider["error"]["type"] == failures[target]
            assert result["failure"]["cause"]["type"] == failures[target]
        else:
            assert result["failure"] is None
            assert result["output"]["returned"] == 1
            assert provider["output"]["reference"]["id"] == target
    assert all(item["verdict"] == "통과" for item in scored["runs"])
    functional = scored["tools"][0]["functional"]
    assert functional["numerator"] == functional["denominator"] == 4
    assert functional["complete"]


@pytest.mark.asyncio
async def test_unrequested_provider_failure_has_no_effect_on_another_source(tmp_path):
    case = _case(target="beta", provider_failures={"alpha": "PermissionError"})
    _, (result,), scored = await _execute(tmp_path, _suite(case))
    assert result["failure"] is None
    assert result["output"]["data"]["inputs"] == [
        {"id": "beta", "version": "fixture-v1"}
    ]
    assert [s["name"] for s in _provider_trace(result)] == ["beta"]
    assert scored["runs"][0]["verdict"] == "통과"


@pytest.mark.asyncio
async def test_input_rejection_occurs_before_configured_provider_failure(tmp_path):
    case = _case(
        arguments={"target": "alpha", "limit": 0},
        provider_failures={"alpha": "PermissionError"},
        assessment=_assessment(
            ("T-I.1", "/observations/provider_calls", 0),
            ("T-O.1", "/output", None),
            ("T-O.2", "/failure/code", "invalid_input"),
        ),
    )
    _, (report,), scored = await _execute(tmp_path, _suite(case))
    assert _provider_trace(report) == []
    assert report["failure"]["code"] == "invalid_input"
    assert report["failure"]["cause"]["type"] == "ValidationError"
    assert scored["runs"][0]["verdict"] == "통과"


@pytest.mark.parametrize(
    "failures",
    [
        {"alpha": "ValueError"},
        {"alpha": "permissionerror"},
        {"alpha": "TIMEOUTERROR"},
        {"alpha": None},
        {"alpha": 1},
        {"alpha": {"type": "PermissionError"}},
        None,
        "PermissionError",
        ["alpha"],
        [{"alpha": "PermissionError"}],
    ],
)
def test_json_rejects_unknown_error_names_and_malformed_provider_failure_maps(
    tmp_path, failures
):
    with pytest.raises(ValidationError):
        _load_json(tmp_path, _suite(_case(provider_failures=failures)))


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_failures": {"unregistered": "PermissionError"}},
        {"providers": ["alpha"], "provider_failures": {"beta": "TimeoutError"}},
        {"providers": [], "provider_failures": {"alpha": "ConnectionError"}},
    ],
)
def test_json_failure_keys_must_name_providers_available_to_the_case(tmp_path, changes):
    with pytest.raises(ValidationError):
        _load_json(tmp_path, _suite(_case(**changes)))


@pytest.mark.parametrize("providers", [None, ["alpha", "beta"]])
def test_omitted_provider_selection_allows_all_registered_failure_targets(
    tmp_path, providers
):
    case = _case(provider_failures={"alpha": "PermissionError", "beta": "TimeoutError"})
    if providers is not None:
        case["providers"] = providers
    loaded, _ = _load_json(tmp_path, _suite(case))
    assert loaded["cases"][0]["provider_failures"] == case["provider_failures"]


def _initial():
    return {
        "request": {"goal": "합성 자료를 조회한다."},
        "event": "analysis_pipeline",
        "messages": [],
    }


def _workflow_initial():
    return _initial() | {
        "results": [
            record(
                "report",
                "report_input",
                "합성 보고서 입력",
                output={
                    "requestId": "provider-test",
                    "month": "2025-12",
                    "dongCodes": ["1168066000"],
                    "dongCode": "1168066000",
                },
            ),
            record(
                "report",
                "report_source",
                "합성 자료 시점",
                output={
                    "updated_at": "2025-12-15T00:00:00",
                },
            ),
        ]
    }


@pytest.mark.parametrize(
    "unit,target",
    [
        ("node", "act"),
        ("selection", "act"),
        ("agent", "interpretation"),
        ("workflow", "report"),
    ],
)
def test_provider_failure_configuration_is_available_to_every_source_using_unit(
    tmp_path, unit, target
):
    case = {
        "id": "with-source-config",
        "unit": unit,
        "target": target,
        "purpose": "실행 단위의 자료원 설정을 검사한다.",
        "initial": _workflow_initial() if unit == "workflow" else _initial(),
        "provider_failures": {"alpha": "PermissionError"},
    }
    if unit in {"node", "selection"}:
        case["role"] = "interpretation"
    loaded, _ = _load_json(tmp_path, _suite(case))
    assert loaded["cases"][0]["provider_failures"] == {"alpha": "PermissionError"}


@pytest.mark.asyncio
async def test_node_output_collection_invokes_neither_stub_nor_configured_provider(
    tmp_path,
):
    returned = {"returned": 77}
    case = {
        "id": "stubbed-query",
        "unit": "node",
        "target": "act",
        "role": "interpretation",
        "purpose": "대체 도구의 실제 자료원 미호출 확인",
        "initial": _initial(),
        "dependencies": "stub",
        "provider_failures": {"alpha": "PermissionError"},
        "stubs": [
            {"name": "query_data", "arguments": {"target": "alpha"}, "output": returned}
        ],
    }
    model = ScriptedModel([selection("query_data", {"target": "alpha"})])
    _, (report,), scored = await _execute(tmp_path, _suite(case), model=model)
    assert report["failure"] is None
    assert report["run"]["status"] == "returned"
    assert _provider_trace(report) == []
    called = [item for item in report["state"]["results"] if item["decision"] == "call"]
    assert called == []
    assert report["fixtures"]["calls"] == []
    assert json.loads(report["output"]["raw"])["name"] == "query_data"
    assert scored["tools"] == []
