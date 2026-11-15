"""한국 날짜 경계·동시 저장·이전 실행의 순번 충돌과 원본 보존을 확인한다."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest

from eval import assessment_store, batch_store
from eval.naming import (
    assign_batch_names,
    create_batch_folder,
    reserve_assessment_id,
)
from eval.runner import run_suite
from eval.tests.test_evaluation_runner import node_case, read_json, suite, tool_case
from eval.tests.test_evaluation_scoring import _saved
from src.settings import Settings


async def test_selected_cases_and_korean_start_day_define_saved_batch(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "eval.runner.korea_timestamp", lambda: "2026-11-13T00:01:00+09:00"
    )
    value = suite(tool_case(), node_case())
    first = await run_suite(value, Settings(_env_file=None), tmp_path, unit="tool")
    second = await run_suite(value, Settings(_env_file=None), tmp_path, unit="tool")

    assert first.name == "도구평가_2026-11-13_실행01"
    assert second.name == "도구평가_2026-11-13_실행02"
    stored = read_json(first / "batch.json")
    assert stored["id"] == first.name
    assert stored["started_at"] == "2026-11-13T00:01:00+09:00"
    report = read_json(first / stored["runs"][0]["path"])
    assert report["run"]["id"] == stored["runs"][0]["run_id"]
    assert (
        datetime.fromisoformat(report["run"]["started_at"]).utcoffset().total_seconds()
        == 0
    )


@pytest.mark.parametrize(
    "units,label",
    [
        (["tool"], "도구평가"),
        (["node", "selection"], "노드평가"),
        (["agent", "workflow"], "실행평가"),
        (["tool", "node"], "통합평가"),
    ],
)
def test_folder_creation_uses_korean_date_and_preserves_parallel_batches(
    tmp_path, units, label
):
    cases = [{"unit": unit, "target": "act"} for unit in units]
    barrier = Barrier(4)

    def create(_):
        barrier.wait()
        return create_batch_folder(tmp_path, cases, "2026-11-12T15:01:00+00:00")

    with ThreadPoolExecutor(max_workers=4) as pool:
        folders = list(pool.map(create, range(4)))
    assert {folder.name for folder in folders} == {
        f"{label}_2026-11-13_실행{number:02d}" for number in range(1, 5)
    }
    assert all(folder.is_dir() for folder in folders)
    parent = tmp_path / "act" if label == "노드평가" else tmp_path
    assert all(folder.parent == parent for folder in folders)


def test_node_numbering_is_independent_and_rejects_mixed_node_batch(tmp_path):
    started = "2026-11-13T12:00:00+09:00"
    first = create_batch_folder(tmp_path, [node_case("interpret")], started)
    second = create_batch_folder(tmp_path, [node_case("act")], started)
    third = create_batch_folder(tmp_path, [node_case("interpret")], started)
    assert first.name == second.name == "노드평가_2026-11-13_실행01"
    assert third.name == "노드평가_2026-11-13_실행02"
    with pytest.raises(ValueError, match="하나의 노드"):
        create_batch_folder(
            tmp_path, [node_case("interpret"), node_case("act")], started
        )


def test_legacy_names_are_stable_and_new_batches_do_not_reuse_their_numbers(tmp_path):
    older, _, batch = _saved(tmp_path / "legacy-a")
    later, _, _ = _saved(tmp_path / "legacy-b")
    records = [
        {
            "path": later,
            "id": "old-b",
            "started_at": "2026-11-10T01:00:00+00:00",
            "cases": [tool_case()],
        },
        {
            "path": older,
            "id": "old-a",
            "started_at": batch["started_at"],
            "cases": [tool_case()],
        },
    ]
    first = assign_batch_names(records)
    assert first == assign_batch_names(list(reversed(records)))
    assert first[older] == "도구평가_2026-11-10_실행01"
    assert first[later] == "도구평가_2026-11-10_실행02"
    assert (
        create_batch_folder(tmp_path, [tool_case()], batch["started_at"]).name
        == "도구평가_2026-11-10_실행03"
    )


def test_parallel_reassessment_reserves_unique_numbers_even_without_output_files(
    tmp_path,
):
    barrier = Barrier(4)

    def reserve(_):
        barrier.wait()
        return reserve_assessment_id(tmp_path, "노드평가_2026-11-13_실행01")

    with ThreadPoolExecutor(max_workers=4) as pool:
        names = list(pool.map(reserve, range(4)))
    assert set(names) == {
        f"노드평가_2026-11-13_실행01_채점{number:02d}" for number in range(1, 5)
    }
    assert not list((tmp_path / "assessments").glob("*.json"))


def test_output_created_after_preflight_is_not_overwritten(tmp_path, monkeypatch):
    destination = tmp_path / "chosen"
    original = assessment_store.write_assessment

    def competing_write(target, result, *, source_batch):
        target.mkdir()
        (target / "keep.json").write_text('{"saved": "first"}', encoding="utf-8")
        original(target, result, source_batch=source_batch)

    monkeypatch.setattr(batch_store, "write_assessment", competing_write)
    with pytest.raises(FileExistsError):
        batch_store.save_result(
            tmp_path,
            {"id": "second", "schema_version": "node-evaluation-v1", "criteria": {}},
            destination,
        )
    assert json.loads((destination / "keep.json").read_text(encoding="utf-8")) == {
        "saved": "first"
    }
    assert not (destination / "manifest.json").exists()


def test_existing_assessment_directory_reserves_its_number(tmp_path):
    name = "노드평가_2026-11-13_실행01"
    (tmp_path / "assessments" / f"{name}_채점04").mkdir(parents=True)
    assert reserve_assessment_id(tmp_path, name) == f"{name}_채점05"
