"""시나리오 분리 저장의 내용 보존과 깨진 파일 연결을 검사한다."""

import json
from copy import deepcopy

import pytest

from eval.scripts.node_dataset_storage import (
    SCHEMA_VERSION,
    load_scenarios,
    write_scenarios,
)


@pytest.fixture
def sidecar():
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {"complete_scenario_count": 2},
        "case_index": {"shared": {"usages": [{"scenario_id": "basic-none"}]}},
        "scenarios": [
            {
                "id": identity,
                "title": title,
                "start_state": {"results": [], "response": None},
                "steps": [
                    {"case_id": "shared", "input_ref": "act.json#/cases/0/initial"}
                ],
                "terminal": {"status": "completed"},
            }
            for identity, title in (
                ("basic-none", "이전 대화 없음"),
                ("basic-new_topic", "새 주제"),
            )
        ],
    }


def test_split_storage_preserves_content_and_loads_each_body(tmp_path, sidecar):
    original = deepcopy(sidecar)
    index_path = tmp_path / "scenarios.json"
    write_scenarios(index_path, sidecar)
    assert sidecar == original
    assert load_scenarios(index_path) == original
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["case_index"] == original["case_index"]
    assert all(set(entry) == {"id", "title", "file"} for entry in index["scenarios"])
    assert index["scenarios"][1]["file"] == "scenarios/basic-new-topic.json"
    body_path = tmp_path / index["scenarios"][1]["file"]
    changed = deepcopy(original["scenarios"][1])
    changed["terminal"]["status"] = "partial"
    body_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    loaded = load_scenarios(index_path)
    assert loaded["scenarios"][0] == original["scenarios"][0]
    assert loaded["scenarios"][1] == changed


def test_missing_scenario_file_is_not_silently_omitted(tmp_path, sidecar):
    index_path = tmp_path / "scenarios.json"
    write_scenarios(index_path, sidecar)
    (tmp_path / "scenarios/basic-none.json").unlink()
    with pytest.raises(FileNotFoundError):
        load_scenarios(index_path)


def test_swapped_scenario_body_is_rejected(tmp_path, sidecar):
    index_path = tmp_path / "scenarios.json"
    write_scenarios(index_path, sidecar)
    (tmp_path / "scenarios/basic-none.json").write_text(
        json.dumps(sidecar["scenarios"][1], ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="identity does not match"):
        load_scenarios(index_path)


def test_filename_normalization_cannot_overwrite_another_scenario(tmp_path, sidecar):
    sidecar["scenarios"][0]["id"] = "basic-new-topic"
    with pytest.raises(ValueError, match="unique files"):
        write_scenarios(tmp_path / "scenarios.json", sidecar)
    assert not list(tmp_path.rglob("*.json"))
