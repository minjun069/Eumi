"""경량 목록의 메타데이터 제한·실행 본문 미열람·저장 연동을 검증한다."""

import json
from pathlib import Path

import pytest

from eval.assessment_store import load_assessment
from eval.batch_store import save_result
from eval.viewers import catalog as viewer_catalog


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def score(identifier: str) -> dict:
    return {
        "schema_version": "tool-evaluation-v1",
        "id": identifier,
        "criteria": {},
        "runs": [],
        "tools": [],
    }


def catalog(tmp_path, roots):
    destination = tmp_path / "catalog.json"
    result = viewer_catalog.build_catalog(
        tuple(roots), destination, project_root=tmp_path
    )
    assert json.loads(destination.read_text(encoding="utf-8")) == result
    return result


def test_catalog_lists_metadata_across_roots_without_copying_or_changing_sources(
    tmp_path,
):
    roots = tuple(
        tmp_path / "outputs" / name for name in ("evaluations", "database-evaluations")
    )
    expected = {}
    for index, root in enumerate(roots):
        folder = root / "group" / f"batch-{index}"
        for name, text in {
            "batch.json": json.dumps(
                {
                    "id": f"batch-{index}",
                    "suite_id": "suite",
                    "status": "returned",
                    "started_at": "2026-11-13T10:00:00+09:00",
                    "ended_at": None,
                    "planned_runs": 2,
                    "runs": [
                        {"unit": "node", "raw": "DO NOT COPY"},
                        {"unit": "selection"},
                        {"unit": "node"},
                    ],
                    "failure": {"details": "DO NOT COPY"},
                }
            ),
            "suite.json": '{"input":"DO NOT COPY"}',
            "runs/run/report.json": '{"output":"DO NOT COPY"}',
            "runs/run/trace.jsonl": '{"span":"DO NOT COPY"}\ninvalid-line\n',
            "assessments/score.json": '{"judge":"DO NOT COPY"}',
        }.items():
            path = folder / name
            write(path, text)
            expected[path.relative_to(tmp_path).as_posix()] = path.stat().st_size
        write(folder / "unrelated.json", '{"not":"evidence"}')
        write(folder / ".temporary/batch.json", '{"id":"unfinished"}')
    write(tmp_path / "outputs/pytest-temp/batch.json", "{}")
    originals = {
        path: path.read_bytes()
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
    }
    result = catalog(tmp_path, roots)
    assert result["version"] == "evaluation-viewer-local-v2"
    assert {item["path"]: item["size_bytes"] for item in result["files"]} == expected
    assert all(
        set(item) == {"path", "size_bytes", "modified_at"} for item in result["files"]
    )
    assert len(result["batches"]) == 2
    for batch in result["batches"]:
        assert batch["path"].endswith("/batch.json")
        assert batch["suite_path"].endswith("/suite.json")
        assert batch["planned_runs"] == 2
        assert batch["registered_runs"] == 3
        assert batch["units"] == ["node", "selection"]
        assert batch["node_targets"] == []
        assert batch["ended_at"] is None
        assert set(batch["assessments"][0]) == {"path", "format"}
        assert batch["assessments"][0]["format"] == "legacy"
    assert "DO NOT COPY" not in json.dumps(result)
    assert all(path.read_bytes() == content for path, content in originals.items())


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        (
            [
                {"unit": "node", "target": "interpret"},
                {"unit": "node", "target": "compose"},
                {"unit": "node", "target": "interpret"},
                {"unit": "agent", "target": "request"},
                {"unit": "selection", "target": "act"},
                {"target": "ask"},
                {"unit": "node", "target": None},
                {"unit": "node", "target": ["decide"]},
                {"unit": "node"},
                None,
            ],
            ["compose", "interpret"],
        ),
        ([], []),
        (None, []),
    ],
)
def test_node_targets_use_only_registered_node_run_targets(tmp_path, runs, expected):
    root = tmp_path / "eval/outputs/evaluations"
    batch = root / "misleading-name"
    write(
        batch / "batch.json",
        json.dumps({"id": "act", "target": "ask", "runs": runs}),
    )
    write(batch / "suite.json", '{"target":"decide"}')

    result = catalog(tmp_path, [root])

    assert result["batches"][0]["node_targets"] == expected
    assert result["issues"] == []


def test_only_batch_and_assessment_are_opened_for_metadata(tmp_path, monkeypatch):
    root = tmp_path / "eval/outputs/evaluations"
    batch = root / "batch"
    write(batch / "batch.json", '{"id":"batch"}')
    hidden = [
        batch / name
        for name in (
            "suite.json",
            "runs/run/report.json",
            "runs/run/case.json",
            "runs/run/manifest.json",
            "runs/run/trace.jsonl",
        )
    ] + [tmp_path / viewer_catalog.NODE_SCENARIOS]
    for path in hidden:
        write(path, "DO NOT READ" * 100)
    assessment = batch / "assessments/score.json"
    metadata = {
        "schema_version": "node-evaluation-v1",
        "id": "score",
        "batch_id": "batch",
        "suite_id": "suite",
        "assessed_at": "2026-11-13T11:00:00+09:00",
        "status": "completed",
        "method": "all",
        "judge_model": "judge",
        "assessments": [{"calls": "DO NOT COPY"}],
    }
    write(assessment, json.dumps(metadata))
    original_open = Path.open
    opened = []

    def guarded_open(path, *args, **kwargs):
        assert path not in hidden, f"원문을 미리 읽음: {path}"
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = catalog(tmp_path, [root])
    assert batch / "batch.json" in opened and assessment in opened
    assert len(result["files"]) == len(hidden) + 2
    assert result["batches"][0]["assessments"] == [
        {
            "path": assessment.relative_to(tmp_path).as_posix(),
            "format": "legacy",
            "report_schema_version": "node-evaluation-v1",
            **{
                key: metadata[key]
                for key in (
                    "id",
                    "batch_id",
                    "suite_id",
                    "assessed_at",
                    "status",
                    "method",
                    "judge_model",
                )
            },
        }
    ]
    assert "DO NOT" not in json.dumps(result)
    assert result["scenario_index"] == viewer_catalog.NODE_SCENARIOS.as_posix()
    assert result["issues"] == []


def test_large_original_only_changes_size_metadata(tmp_path):
    root = tmp_path / "eval/outputs/evaluations"
    write(root / "batch/batch.json", '{"id":"batch"}')
    original = root / "batch/runs/run/trace.jsonl"
    write(original, "raw trace payload\n" * 100_000)
    result = catalog(tmp_path, [root])
    assert len((tmp_path / "catalog.json").read_bytes()) < 2_000
    record = next(item for item in result["files"] if item["path"].endswith("jsonl"))
    assert record["size_bytes"] == original.stat().st_size


def test_bad_metadata_preserves_paths_and_reports_only_metadata_errors(tmp_path):
    root = tmp_path / "eval/outputs/evaluations"
    write(root / "batch/batch.json", "{invalid")
    write(root / "batch/assessments/bad.json", "[]")
    write(root / "batch/runs/run/report.json", "{invalid raw output")
    result = catalog(tmp_path, [root])
    assert len(result["files"]) == 3
    assert len(result["issues"]) == 2
    assert {issue["path"].split("/")[-1] for issue in result["issues"]} == {
        "batch.json",
        "bad.json",
    }
    assert result["batches"][0]["units"] == []
    assert result["batches"][0]["node_targets"] == []
    assert result["batches"][0]["suite_path"] is None


def test_unfinished_temporary_json_is_not_listed_as_a_saved_assessment(tmp_path):
    root = tmp_path / "eval/outputs/evaluations"
    write(root / "batch/batch.json", '{"id":"batch"}')
    write(root / "batch/assessments/pending.tmp", "incomplete")
    result = catalog(tmp_path, [root])
    assert len(result["files"]) == 1
    assert result["batches"][0]["assessments"] == []
    assert result["issues"] == []


def test_stat_failure_is_reported_without_losing_other_files(tmp_path, monkeypatch):
    root = tmp_path / "eval/outputs/evaluations"
    write(root / "batch/batch.json", '{"id":"batch"}')
    inaccessible = root / "batch/suite.json"
    write(inaccessible, "unreadable")
    original_stat = Path.stat

    def denied(path, *, follow_symlinks=True):
        if path == inaccessible and follow_symlinks:
            raise PermissionError("test")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", denied)
    result = catalog(tmp_path, [root])
    assert len(result["files"]) == 1
    assert result["issues"][0]["path"].endswith("suite.json")


def test_failed_catalog_replace_preserves_previous_snapshot(tmp_path, monkeypatch):
    destination = tmp_path / "catalog.json"
    write(destination, "previous-complete-snapshot")

    def denied(*args):
        raise PermissionError("test")

    monkeypatch.setattr(viewer_catalog.os, "replace", denied)
    with pytest.raises(PermissionError):
        viewer_catalog.build_catalog((), destination, project_root=tmp_path)
    assert destination.read_text(encoding="utf-8") == "previous-complete-snapshot"
    assert not list(tmp_path.glob("*.tmp"))


def test_successful_score_save_refreshes_catalog_and_unrelated_roots_do_not(
    tmp_path,
    monkeypatch,
):
    folder = tmp_path / "eval/outputs/evaluations/batch"
    monkeypatch.setattr(viewer_catalog, "RESULT_ROOTS", (folder.parent,))
    refreshed = []
    monkeypatch.setattr(viewer_catalog, "build_catalog", lambda: refreshed.append(True))
    destination = save_result(folder, score("score"))
    assert load_assessment(destination)["id"] == "score"
    assert refreshed == [True]
    save_result(tmp_path / "tests", score("unrelated"))
    assert refreshed == [True]


def test_viewer_write_failure_does_not_fail_or_modify_a_saved_assessment(
    tmp_path,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(viewer_catalog, "RESULT_ROOTS", (tmp_path,))

    def denied():
        raise PermissionError("test")

    monkeypatch.setattr(viewer_catalog, "build_catalog", denied)
    destination = save_result(tmp_path / "batch", score("score"))
    assert load_assessment(destination)["id"] == "score"
    assert "평가 원본은 저장됐으나" in caplog.text


@pytest.mark.parametrize(
    "source",
    [
        "{invalid",
        '{"scenarios":[{"file":"scenarios/missing.json"}]}',
        '{"scenarios":[{"file":"../outside.json"}]}',
    ],
)
def test_scenario_references_are_deferred_until_selection(tmp_path, source):
    index = tmp_path / viewer_catalog.NODE_SCENARIOS
    write(index, source)
    write(index.parent / "scenarios/private.json", "not an index input")
    write(index.parent.parent / "outside.json", "not an index input")
    result = catalog(tmp_path, [])
    assert result["scenario_index"] == viewer_catalog.NODE_SCENARIOS.as_posix()
    assert [item["path"] for item in result["files"]] == [result["scenario_index"]]
    assert result["issues"] == []
    assert index.read_text(encoding="utf-8") == source


def test_catalog_ignores_linked_result_directories(tmp_path, monkeypatch):
    root = tmp_path / "eval/outputs/evaluations"
    linked = root / "linked"
    write(linked / "batch.json", '{"id":"must-not-read"}')
    write(root / "normal/batch.json", '{"id":"normal"}')
    original_junction = Path.is_junction
    monkeypatch.setattr(
        Path, "is_junction", lambda path: path == linked or original_junction(path)
    )
    result = catalog(tmp_path, [root])
    assert len(result["batches"]) == 1
    assert result["batches"][0]["id"] == "normal"
