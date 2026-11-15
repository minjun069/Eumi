"""중단 기록의 정직한 복구와 실제 실행·준비·취소 경계를 검증한다."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest

from eval.execution.evidence import load_execution_report
from src.execution_trace import TraceRecorder, recording, trace_output, trace_span
from tests.helpers import initial


def saved_journal(tmp_path):
    case = {"id": "case", "unit": "agent", "target": "request"}
    entry = {"run_id": "run", "repetition": 1, "path": "runs/run/report.json"}
    run = {
        "id": "run",
        "suite_id": "suite",
        "case_id": "case",
        "unit": "agent",
        "target": "request",
        "repetition": 1,
        "role": "request",
        "dependencies": "real",
    }
    state = initial()
    state["execution"]["run_id"] = "run"
    state["execution"]["status"] = "completed"
    path = tmp_path / "runs" / "run" / "trace.jsonl"
    recorder = TraceRecorder(journal=path)
    with recording(recorder), trace_span("evaluation", "request", {"run": run}):
        with trace_span("execution", "request", {"initial_state": state}):
            trace_output({"state": state})
        trace_output({"state": state, "output": None})
    rows = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    return case, entry, path, rows


def write_rows(path, rows, suffix=b""):
    path.write_bytes(
        b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in rows)
        + suffix
    )


def load(tmp_path, case, entry, hashes=None):
    return load_execution_report(
        tmp_path,
        entry,
        case,
        "suite",
        hashes if hashes is not None else {},
        observed_at="2026-11-12T15:00:00+09:00",
    )


def test_missing_report_recovers_latest_snapshots_without_counting_events_as_calls(
    tmp_path,
):
    case, entry, path, rows = saved_journal(tmp_path)
    # 동일한 end가 재기록돼도 새 호출이 아니다.
    write_rows(path, [*rows, deepcopy(rows[-1])])
    original = path.read_bytes()
    hashes = {}
    result = load(tmp_path, case, entry, hashes)
    assert result["run"]["status"] == "returned"
    assert result["state"]["execution"]["status"] == "completed"
    assert result["trace"]["counts"] == {"evaluation": 1, "execution": 1}
    assert result["evidence"]["issues"] == []
    assert result["evidence"]["source"] == "trace.jsonl"
    assert result["evidence"]["complete"] is False
    assert hashes == {"runs/run/trace.jsonl": sha256(original).hexdigest()}
    assert path.read_bytes() == original
    assert not (path.parent / "report.json").exists()


def test_truncated_tail_preserves_unfinished_observation_without_fabricating_return(
    tmp_path,
):
    case, entry, path, rows = saved_journal(tmp_path)
    write_rows(path, rows[:2], b'{"event":"update","span":')
    result = load(tmp_path, case, entry)
    assert result["run"]["status"] == "running"
    assert result["run"]["ended_at"] is None
    assert result["run"]["elapsed_seconds"] is None
    assert "state" not in result
    assert result["trace"]["coverage"]["unfinished_spans"] == 2
    evidence = result["evidence"]
    assert evidence["observed_at"] == "2026-11-12T15:00:00+09:00"
    assert evidence["last_observed_at"] == rows[1]["span"]["started_at"]
    assert "잘린 마지막 행" in evidence["issues"][0]


@pytest.mark.parametrize("field,value", [("name", "wrong"), ("input", {})])
def test_conflicting_snapshot_cannot_supply_return_evidence(tmp_path, field, value):
    case, entry, path, rows = saved_journal(tmp_path)
    changed = deepcopy(rows[3])
    changed["span"][field] = value
    write_rows(path, [*rows[:3], changed, *rows[4:]])
    result = load(tmp_path, case, entry)
    assert result["run"]["status"] == "running"
    assert "state" not in result
    assert result["trace"]["spans"][1]["status"] == "unknown"
    assert any("충돌" in reason for reason in result["evidence"]["issues"])


def test_missing_span_start_is_not_treated_as_a_complete_call(tmp_path):
    case, entry, path, rows = saved_journal(tmp_path)
    write_rows(path, [rows[0], *rows[2:]])
    result = load(tmp_path, case, entry)
    assert result["run"]["status"] == "running"
    assert any("시작 기록 누락" in reason for reason in result["evidence"]["issues"])


@pytest.mark.parametrize("damage", ["cycle", "invalid_error", "invalid_elapsed"])
def test_malformed_calls_are_preserved_as_unknown_evidence(tmp_path, damage):
    case, entry, path, rows = saved_journal(tmp_path)
    for row in rows:
        if row["span"]["kind"] != "execution":
            continue
        if damage == "cycle":
            row["span"]["parent_id"] = row["span"]["id"]
        elif damage == "invalid_error":
            row["span"]["error"] = "not-an-error-object"
        else:
            row["span"]["elapsed_seconds"] = float("nan")
    write_rows(path, rows)
    result = load(tmp_path, case, entry)
    assert result["run"]["status"] == "running"
    assert result["evidence"]["issues"]
    assert "state" not in result


def test_cancelled_boundary_does_not_turn_observed_state_into_returned_state(tmp_path):
    case, entry, path, rows = saved_journal(tmp_path)
    boundary = deepcopy(rows[3])
    boundary["span"]["status"] = "error"
    boundary["span"]["error"] = {"type": "CancelledError"}
    boundary["span"]["output"] = {"observed_state": boundary["span"]["output"]["state"]}
    write_rows(path, [*rows[:2], boundary, *rows[4:]])
    result = load(tmp_path, case, entry)
    assert result["run"]["status"] == "cancelled"
    assert result["run"]["ended_at"] is not None
    assert "state" not in result
    assert result["failure"] == {"type": "CancelledError"}
    assert "observed_state" in result["trace"]["spans"][1]["output"]


def test_outer_success_alone_does_not_prove_an_execution_returned(tmp_path):
    case, entry, path, rows = saved_journal(tmp_path)
    write_rows(path, [row for row in rows if row["span"]["kind"] == "evaluation"])
    result = load(tmp_path, case, entry)
    assert result["run"]["status"] == "running"
    assert result["run"]["started_at"] is None
    assert result["evidence"]["entry_observed"] is False
    assert "state" not in result


def test_corrupt_middle_row_is_explicit_even_when_other_calls_are_recoverable(tmp_path):
    case, entry, path, rows = saved_journal(tmp_path)
    write_rows(path, rows)
    original = path.read_bytes()
    path.write_bytes(original.splitlines(keepends=True)[0] + b"broken\n" + original)
    result = load(tmp_path, case, entry)
    assert any("손상된 행" in reason for reason in result["trace"]["recovery_issues"])
    assert len(result["trace"]["spans"]) == 2


def test_registration_identity_mismatch_rejects_journal(tmp_path):
    case, entry, path, rows = saved_journal(tmp_path)
    for row in rows:
        if row["span"]["kind"] == "evaluation":
            row["span"]["input"]["run"]["suite_id"] = "other-suite"
    write_rows(path, rows)
    with pytest.raises(ValueError, match="식별 정보"):
        load(tmp_path, case, entry)


def test_unsafe_registered_path_is_rejected_before_journal_fallback(tmp_path):
    case, entry, _path, _rows = saved_journal(tmp_path)
    with pytest.raises(ValueError, match="상대 경로"):
        load(tmp_path, case, entry | {"path": "../report.json"})


@pytest.mark.asyncio
async def test_real_runner_excludes_graph_preparation_and_prefers_report(
    tmp_path,
    monkeypatch,
):
    from eval import runner
    from eval.tests.test_evaluation_runner import initial as case_initial
    from eval.tests.test_evaluation_runner import suite
    from src.settings import Settings
    from tests.helpers import DONE, ScriptedModel

    original = runner.compile_graph

    def prepare(*args, **kwargs):
        with trace_span("test-preparation", "compile", {}):
            return original(*args, **kwargs)

    monkeypatch.setattr(runner, "compile_graph", prepare)
    case = {
        "id": "case",
        "unit": "agent",
        "target": "request",
        "purpose": "준비와 실행 경계",
        "initial": case_initial(),
    }
    model = ScriptedModel(
        [
            DONE,
            {
                "content": "현재 자료로 답변",
                "artifact_ids": [],
                "status": "completed",
                "reason": "응답 완료",
            },
        ]
    )
    root = await runner.run_suite(
        suite(case), Settings(_env_file=None), tmp_path, model=model
    )
    batch = json.loads((root / "batch.json").read_text(encoding="utf-8"))
    entry = batch["runs"][0]
    hashes = {}
    result = load_execution_report(root, entry, case, batch["suite_id"], hashes)
    spans = result["trace"]["spans"]
    preparation = next(s for s in spans if s["kind"] == "test-preparation")
    boundary = next(s for s in spans if s["kind"] == "execution")
    assert preparation["ended_at"] <= boundary["started_at"]
    assert boundary["output"]["state"] == result["state"]
    assert result["run"]["status"] == "returned"
    assert "evidence" not in result
    assert entry["path"] in hashes
    assert set(hashes) == {entry["path"]}
    assert all(
        sha256((root / name).read_bytes()).hexdigest() == digest
        for name, digest in hashes.items()
    )
