"""시나리오 본문은 파일별로 저장하고 공통 색인에서 읽는다."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypedDict

SCHEMA_VERSION = "node-scenarios-v4"


class ScenarioFile(TypedDict):
    id: str
    title: str
    file: str


def scenario_file(identity: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", identity):
        raise ValueError(f"Invalid scenario ID: {identity}")
    return f"scenarios/{identity.replace('_', '-')}.json"


def _entries(scenarios: list[dict]) -> list[ScenarioFile]:
    entries: list[ScenarioFile] = [
        {"id": item["id"], "title": item["title"], "file": scenario_file(item["id"])}
        for item in scenarios
    ]
    if len({entry["file"] for entry in entries}) != len(entries):
        raise ValueError("Scenario IDs must resolve to unique files")
    return entries


def _write(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_scenarios(index_path: Path, sidecar: dict) -> None:
    """기존 시나리오 객체를 변경하지 않고 본문과 공통 색인으로 나눈다."""
    index_path = Path(index_path)
    entries = _entries(sidecar["scenarios"])
    (index_path.parent / "scenarios").mkdir(parents=True, exist_ok=True)
    for entry, scenario in zip(entries, sidecar["scenarios"], strict=True):
        _write(index_path.parent / entry["file"], scenario)
    _write(
        index_path,
        {**sidecar, "schema_version": SCHEMA_VERSION, "scenarios": entries},
    )


def load_scenarios(index_path: Path) -> dict:
    """색인의 순서대로 본문을 읽어 경로 검사에 사용하는 메모리 구조로 복원한다.

    본문 안의 노드 입력·기대 결과 참조는 색인과 같은 데이터셋 루트 기준이다.
    """
    index_path = Path(index_path)
    index = json.loads(index_path.read_text(encoding="utf-8-sig"))
    if index.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Expected {SCHEMA_VERSION}: {index_path}")
    entries = index["scenarios"]
    expected = _entries(entries)
    scenarios = []
    for entry, canonical in zip(entries, expected, strict=True):
        if entry != canonical:
            raise ValueError(f"Invalid scenario file entry: {entry['id']}")
        path = (index_path.parent / entry["file"]).resolve()
        if not path.is_relative_to(index_path.parent.resolve()):
            raise ValueError(f"Scenario file is outside the dataset: {entry['file']}")
        scenario = json.loads(path.read_text(encoding="utf-8-sig"))
        if any(scenario[key] != entry[key] for key in ("id", "title")):
            raise ValueError(
                f"Scenario identity does not match its index: {entry['file']}"
            )
        scenarios.append(scenario)
    return {**index, "scenarios": scenarios}
