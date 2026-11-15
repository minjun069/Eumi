"""합성 저장 파일로 재채점의 계획·증거 연결·원본 보존을 검증한다."""

import json
from copy import deepcopy
from datetime import datetime
from hashlib import sha256

import pytest

from eval.assessment_store import load_assessment
from eval.tests.batch_fixtures import read_document
from eval.tools.scoring import score_batch

STAMP = "2026-11-10T00:00:00+00:00"


def _case(case_id="case-one", target="query_data"):
    return {
        "id": case_id,
        "unit": "tool",
        "target": target,
        "purpose": "합성 증거 연결 검사",
        "arguments": {},
        "assessment": {
            "checks": ["T-O.1"],
            "required": True,
            "reference": {"id": "independent-fixture"},
            "expected": {
                "schema_version": "tool-expectations-v1",
                "items": [{"check": "T-O.1", "path": "/output/value", "value": 7}],
            },
        },
    }


def _report(case, run_id="run-one", repetition=1):
    return {
        "schema_version": "evaluation-run-v1",
        "run": {
            "id": run_id,
            "suite_id": "synthetic-suite",
            "case_id": case["id"],
            "unit": case["unit"],
            "target": case["target"],
            "role": None,
            "dependencies": "real",
            "repetition": repetition,
            "status": "returned",
            "started_at": STAMP,
            "ended_at": STAMP,
            "elapsed_seconds": 0.25,
        },
        "output": {"value": 7},
        "failure": None,
        "trace": {
            "spans": [
                {
                    "id": f"{run_id}-call",
                    "parent_id": None,
                    "sequence": 1,
                    "kind": "tool",
                    "name": case["target"],
                    "status": "success",
                    "started_at": STAMP,
                    "ended_at": STAMP,
                    "elapsed_seconds": 0.25,
                }
            ]
        },
        "assessment": {
            "executed": False,
            "verdict": "미판정",
            "checks": ["T-O.1"],
            "reason": "실행 증거만 저장함",
        },
        "fixtures": {"calls": [], "unused": [], "unexpected": []},
        "journal_saved": False,
    }


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _read(path):
    return load_assessment(path) if path.is_dir() else read_document(path)


def _saved(tmp_path, *, repeat=1, cases=None, reports=None):
    cases = cases or [_case()]
    reports = [_report(cases[0])] if reports is None else reports
    suite = {
        "schema_version": "evaluation-suite-v1",
        "id": "synthetic-suite",
        "cases": cases,
    }
    batch = {
        "schema_version": "evaluation-batch-v1",
        "id": "synthetic-batch",
        "suite_id": suite["id"],
        "status": "returned",
        "started_at": STAMP,
        "ended_at": STAMP,
        "planned_runs": len(cases) * repeat,
        "plan": {"case_ids": [case["id"] for case in cases], "repeat": repeat},
        "runs": [],
    }
    for report in reports:
        run = report["run"]
        path = f"runs/{run['id']}/report.json"
        batch["runs"].append(
            {
                "case_id": run["case_id"],
                "run_id": run["id"],
                "unit": run["unit"],
                "target": run["target"],
                "repetition": run["repetition"],
                "status": run["status"],
                "path": path,
            }
        )
        _write(tmp_path / path, report)
    _write(tmp_path / "suite.json", suite)
    _write(tmp_path / "batch.json", batch)
    return tmp_path, suite, batch


def test_reassessment_writes_independent_artifacts_and_preserves_source_bytes(tmp_path):
    folder, _, _ = _saved(tmp_path)
    originals = {path: path.read_bytes() for path in folder.rglob("*.json")}

    first_path = score_batch(folder)
    second_path = score_batch(folder)

    first, second = _read(first_path), _read(second_path)
    assert first_path.parent == folder / "assessments"
    assert first_path != second_path
    assert first["id"] != second["id"]
    assert first["schema_version"] == "tool-evaluation-v1"
    assert first["runs"][0]["verdict"] == "통과"
    assert first["tools"][0]["functional"]["numerator"] == 1
    assert first["tools"][0]["functional"]["denominator"] == 1
    assert first["criteria_sha256"] == second["criteria_sha256"]
    assert (
        datetime.fromisoformat(first["assessed_at"]).utcoffset().total_seconds()
        == 32400
    )
    assert first["id"] == "도구평가_2026-11-10_실행01_채점01"
    assert second["id"] == "도구평가_2026-11-10_실행01_채점02"
    for path, raw in originals.items():
        assert path.read_bytes() == raw
        relative = path.relative_to(folder).as_posix()
        assert first["evidence_sha256"][relative] == sha256(raw).hexdigest()
    assert set(first["evaluator_sha256"]) == {
        "tools/assessment.py",
        "tools/metrics.py",
        "tools/scoring.py",
        "schema.py",
        "database.py",
        "naming.py",
        "batch_store.py",
        "assessment_store.py",
        "provenance.py",
    }


def test_external_outputs_and_default_outputs_share_reassessment_numbers(tmp_path):
    folder, _, _ = _saved(tmp_path / "batch")
    first = _read(score_batch(folder, tmp_path / "first"))
    second = _read(score_batch(folder, tmp_path / "second"))
    third_path = score_batch(folder)
    third = _read(third_path)

    assert first["id"].endswith("_채점01")
    assert second["id"].endswith("_채점02")
    assert third["id"].endswith("_채점03")
    assert third_path.name == third["id"] + ".json" and third_path.is_file()
    assert first["batch_id"] == second["batch_id"] == third["batch_id"]


def test_missing_registered_evidence_is_distinct_from_unregistered_repetition(tmp_path):
    case = _case()
    reports = [_report(case), _report(case, "run-two", 2)]
    folder, _, _ = _saved(tmp_path, repeat=3, reports=reports)
    (folder / "runs/run-two/report.json").unlink()

    value = _read(score_batch(folder))

    passed, missing, unstarted = value["runs"]
    assert passed["verdict"] == "통과"
    assert missing["run_id"] == "run-two"
    assert "등록은 있으나" in missing["reason"]
    assert unstarted["run_id"] is None
    assert "등록되지" in unstarted["reason"]
    for assessment in (missing, unstarted):
        assert assessment["verdict"] == "미판정"
        assert assessment["executed"] is False
        assert assessment["checks"][0]["reason"] == assessment["reason"]
    functional = value["tools"][0]["functional"]
    assert functional["numerator"] == 0
    assert functional["denominator"] == 1
    assert functional["incomplete_cases"] == 1


def test_missing_plan_is_not_reconstructed_from_registered_runs(tmp_path):
    folder, _, batch = _saved(tmp_path)
    del batch["plan"]
    _write(folder / "batch.json", batch)
    with pytest.raises(ValueError, match="계획 없음"):
        score_batch(folder)
    assert not (folder / "assessments").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda batch: batch["plan"].update(case_ids=[]),
        lambda batch: batch["plan"].update(case_ids=["case-one", "case-one"]),
        lambda batch: batch["plan"].update(case_ids=["unknown"]),
        lambda batch: batch["plan"].update(repeat=True),
        lambda batch: batch["plan"].update(repeat=0),
        lambda batch: batch.update(planned_runs=2),
        lambda batch: batch.update(suite_id="other"),
        lambda batch: batch["runs"][0].update(repetition=2),
        lambda batch: batch["runs"][0].update(case_id="unknown"),
        lambda batch: batch["runs"][0].update(target="process_data"),
        lambda batch: batch["runs"][0].update(unit="node"),
    ],
)
def test_invalid_plan_and_batch_identity_are_rejected(tmp_path, change):
    folder, _, batch = _saved(tmp_path)
    change(batch)
    _write(folder / "batch.json", batch)
    with pytest.raises(ValueError):
        score_batch(folder)


def test_suite_is_validated_before_assessing(tmp_path):
    folder, suite, _ = _saved(tmp_path)
    suite["cases"].append(deepcopy(suite["cases"][0]))
    _write(folder / "suite.json", suite)
    with pytest.raises(ValueError, match="Duplicate case IDs"):
        score_batch(folder)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other"),
        ("suite_id", "other"),
        ("case_id", "other"),
        ("unit", "node"),
        ("target", "process_data"),
        ("repetition", 2),
        ("role", "request"),
        ("dependencies", "stub"),
    ],
)
def test_report_identity_must_match_plan_case_and_batch_entry(tmp_path, field, value):
    folder, _, _ = _saved(tmp_path)
    path = folder / "runs/run-one/report.json"
    report = _read(path)
    report["run"][field] = value
    _write(path, report)
    with pytest.raises(ValueError, match="식별 정보"):
        score_batch(folder)


def test_conflicting_state_run_id_is_rejected(tmp_path):
    folder, _, _ = _saved(tmp_path)
    path = folder / "runs/run-one/report.json"
    report = _read(path)
    report["state"] = {"execution": {"run_id": "other"}}
    _write(path, report)
    with pytest.raises(ValueError, match="State"):
        score_batch(folder)


@pytest.mark.parametrize("same_id", [True, False])
def test_duplicate_run_ids_and_repetition_slots_are_rejected(tmp_path, same_id):
    folder, _, batch = _saved(tmp_path, repeat=2)
    duplicate = deepcopy(batch["runs"][0])
    if same_id:
        duplicate["repetition"] = 2
    else:
        duplicate["run_id"] = "run-two"
        duplicate["path"] = "runs/run-two/report.json"
    batch["runs"].append(duplicate)
    _write(folder / "batch.json", batch)
    with pytest.raises(ValueError, match="중복"):
        score_batch(folder)


@pytest.mark.parametrize(
    "path",
    [
        "../report.json",
        "/tmp/report.json",
        "C:/private/report.json",
        "C:report.json",
        "\\\\server\\share\\report.json",
        "runs/../report.json",
        "runs\\run-one\\report.json",
        "runs/run-other/report.json",
        "runs/run-one/other.json",
        "runs/run-one/report.json:stream",
        "runs//run-one/report.json",
    ],
)
def test_report_references_cannot_escape_or_select_another_artifact(tmp_path, path):
    folder, _, batch = _saved(tmp_path)
    batch["runs"][0]["path"] = path
    _write(folder / "batch.json", batch)
    with pytest.raises(ValueError):
        score_batch(folder)


def test_symlinked_evidence_is_rejected(tmp_path):
    folder, _, _ = _saved(tmp_path / "batch")
    report = folder / "runs/run-one/report.json"
    external = tmp_path / "external.json"
    external.write_bytes(report.read_bytes())
    report.unlink()
    try:
        report.symlink_to(external)
    except OSError:
        pytest.skip("이 환경은 심볼릭 링크 생성을 허용하지 않습니다")
    with pytest.raises(ValueError, match="링크"):
        score_batch(folder)


def test_existing_outputs_and_incomplete_directories_are_never_overwritten(tmp_path):
    folder, _, _ = _saved(tmp_path)
    source = folder / "suite.json"
    original = source.read_bytes()
    with pytest.raises(FileExistsError):
        score_batch(folder, source)
    assert source.read_bytes() == original
    output = folder / "chosen"
    output.mkdir()
    temporary = output / ".manifest.tmp"
    temporary.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        score_batch(folder, output)
    assert temporary.read_text(encoding="utf-8") == "keep"
    assert not (output / "manifest.json").exists()


def test_selected_plan_controls_scope_and_unsupported_tool_stays_unjudged(tmp_path):
    selected = _case(target="render_visualization")
    omitted = _case("omitted")
    folder, suite, batch = _saved(tmp_path, cases=[selected])
    suite["cases"].append(omitted)
    _write(folder / "suite.json", suite)

    value = _read(score_batch(folder))

    assert len(value["runs"]) == batch["planned_runs"] == 1
    assert value["runs"][0]["verdict"] == "미판정"
    assert value["runs"][0]["executed"] is False
    assert value["tools"] == []


def test_criteria_changes_are_fingerprinted_without_reexecuting(tmp_path):
    folder, suite, batch = _saved(tmp_path)
    suite["cases"][0]["assessment"]["tolerance"] = {"absolute": 0.0}
    _write(folder / "suite.json", suite)
    original_cases = deepcopy(suite["cases"])
    first_path = score_batch(folder)
    original_bytes = {
        path: path.read_bytes() for path in first_path.rglob("*") if path.is_file()
    }
    first = _read(first_path)
    suite["cases"][0]["assessment"]["expected"]["items"][0]["value"] = 8
    suite["cases"][0]["assessment"]["reference"] = {"id": "revised-fixture"}
    suite["cases"][0]["assessment"]["tolerance"] = {"absolute": 0.25}
    _write(folder / "suite.json", suite)
    second = _read(score_batch(folder))
    assert {
        path: path.read_bytes() for path in first_path.rglob("*") if path.is_file()
    } == original_bytes
    assert _read(first_path)["criteria"] == {
        "suite_id": suite["id"],
        "data_source": "prepared",
        "cases": original_cases,
        "performance": [],
        "plan": batch["plan"],
    }
    assert second["criteria"]["cases"] == suite["cases"]
    assert any("실행 전에 준비한 기준" in item for item in first["limitations"])
    assert first["criteria_sha256"] != second["criteria_sha256"]
    assert first["runs"][0]["verdict"] == "통과"
    assert second["runs"][0]["verdict"] == "실패"
    path = "runs/run-one/report.json"
    assert first["evidence_sha256"][path] == second["evidence_sha256"][path]


def test_stale_batch_status_does_not_replace_saved_result_or_create_failure(tmp_path):
    folder, _, batch = _saved(tmp_path)
    batch["runs"][0]["status"] = "running"
    batch.update(status="running", ended_at=None)
    _write(folder / "batch.json", batch)
    assert _read(score_batch(folder))["runs"][0]["verdict"] == "통과"


def test_secret_named_fields_are_redacted_in_independent_assessment(tmp_path):
    folder, suite, _ = _saved(tmp_path)
    item = suite["cases"][0]["assessment"]["expected"]["items"][0]
    item.update(path="/output", value={"api_key": "must-not-leak"})
    report_path = folder / "runs/run-one/report.json"
    report = _read(report_path)
    report["output"] = {"api_key": "must-not-leak"}
    _write(report_path, report)
    _write(folder / "suite.json", suite)
    destination = score_batch(folder)
    assert all(
        "must-not-leak" not in path.read_text(encoding="utf-8")
        for path in destination.rglob("*.json")
    )
    check = _read(destination)["runs"][0]["checks"][0]
    assert check["actual"]["api_key"] == "[REDACTED]"
