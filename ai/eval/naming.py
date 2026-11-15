"""평가 저장 이름과 한국시간 표기. 업무 실행 ID와 State는 변경하지 않는다."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typing_extensions import TypedDict

from eval.schema import NODES, ROLES, Case

KOREA = timezone(timedelta(hours=9))
BATCH_NAME = re.compile(r"(?:도구|노드|실행|통합)평가_\d{4}-\d{2}-\d{2}_실행[0-9]{2,}")


class BatchNameRecord(TypedDict):
    path: Path
    id: str
    started_at: str
    cases: list[Case]


def korea_timestamp(value: str | None = None) -> str:
    moment = datetime.now(KOREA) if value is None else datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError("평가 시각에 시간대가 필요합니다")
    return moment.astimezone(KOREA).isoformat()


def evaluation_label(cases: list[Case]) -> str:
    groups = {
        "tool": "도구평가",
        "node": "노드평가",
        "selection": "노드평가",
        "agent": "실행평가",
        "workflow": "실행평가",
    }
    labels = {groups[case["unit"]] for case in cases}
    if not labels:
        raise ValueError("평가 이름을 만들 사례가 필요합니다")
    return next(iter(labels)) if len(labels) == 1 else "통합평가"


def batch_prefix(cases: list[Case], started_at: str) -> str:
    return f"{evaluation_label(cases)}_{korea_timestamp(started_at)[:10]}_실행"


def batch_name(cases: list[Case], started_at: str, number: int) -> str:
    return f"{batch_prefix(cases, started_at)}{number:02d}"


def assign_batch_names(records: list[BatchNameRecord]) -> dict[Path, str]:
    """기존 이름은 보존하고 UUID 묶음은 시작시각 순으로 빈 실행 번호를 사용한다."""
    names = {
        item["path"]: item["id"] for item in records if BATCH_NAME.fullmatch(item["id"])
    }
    used = set(names.values())
    for item in sorted(
        records,
        key=lambda item: (
            datetime.fromisoformat(korea_timestamp(item["started_at"])),
            item["id"],
            str(item["path"]),
        ),
    ):
        if item["path"] in names:
            continue
        number = 1
        while (name := batch_name(item["cases"], item["started_at"], number)) in used:
            number += 1
        names[item["path"]] = name
        used.add(name)
    return names


def _stored_batches(parent: Path) -> list[BatchNameRecord]:
    records = []
    for path in parent.iterdir():
        if not path.is_dir() or path.is_symlink() or path.is_junction():
            continue
        try:
            batch = json.loads((path / "batch.json").read_text(encoding="utf-8-sig"))
            suite = json.loads((path / "suite.json").read_text(encoding="utf-8-sig"))
            selected = set(batch["plan"]["case_ids"])
            cases = [case for case in suite["cases"] if case["id"] in selected]
            batch_prefix(cases, batch["started_at"])
            if not isinstance(batch["id"], str):
                continue
        except (OSError, ValueError, TypeError, KeyError):
            continue
        records.append(
            {
                "path": path,
                "id": batch["id"],
                "started_at": batch["started_at"],
                "cases": cases,
            }
        )
    return records


def node_target(cases: list[Case]) -> str | None:
    """노드·작업 선택 묶음은 한 노드만 포함한다. 업무 역할은 묶지 않는다."""
    if not cases or any(case["unit"] not in {"node", "selection"} for case in cases):
        return None
    targets = {case["target"] for case in cases}
    if len(targets) != 1 or not targets <= NODES:
        raise ValueError("노드 평가 묶음은 하나의 노드만 포함해야 합니다")
    return next(iter(targets))


def create_batch_folder(output: Path, cases: list[Case], started_at: str) -> Path:
    parent = output.resolve()
    target = batch_target(cases)
    if target is not None:
        parent /= target
    parent.mkdir(parents=True, exist_ok=True)
    prefix = batch_prefix(cases, started_at)
    names = [path.name for path in parent.iterdir()]
    names.extend(assign_batch_names(_stored_batches(parent)).values())
    numbers = [
        int(name[len(prefix) :])
        for name in names
        if name.startswith(prefix) and name[len(prefix) :].isdigit()
    ]
    number = max(numbers, default=0) + 1
    while True:
        folder = parent / f"{prefix}{number:02d}"
        try:
            folder.mkdir(exist_ok=False)
            return folder
        except FileExistsError:
            number += 1


def batch_target(cases: list[Case]) -> str | None:
    """노드는 노드명, 독립 에이전트 실행은 역할별로 묶는다."""
    if cases and all(case["unit"] == "agent" for case in cases):
        targets = {case["target"] for case in cases}
        if len(targets) != 1 or not targets <= ROLES:
            raise ValueError("에이전트 평가 묶음은 하나의 역할만 포함해야 합니다")
        return next(iter(targets))
    return node_target(cases)


def stored_batch_name(
    root: Path, batch_id: str, started_at: str, cases: list[Case]
) -> str:
    if BATCH_NAME.fullmatch(batch_id):
        return batch_id
    records = [item for item in _stored_batches(root.parent) if item["path"] != root]
    records.append(
        {"path": root, "id": batch_id, "started_at": started_at, "cases": cases}
    )
    return assign_batch_names(records)[root]


def reserve_assessment_id(root: Path, name: str) -> str:
    """외부 출력·동시 채점도 같은 묶음의 순번을 재사용하지 않도록 예약한다."""
    folder = root / "assessments"
    folder.mkdir(parents=True, exist_ok=True)
    prefix = f"{name}_채점"
    pattern = re.compile(rf"\.?{re.escape(prefix)}([0-9]+)(?:\.(?:json|tmp|reserve))?")
    paths = list(folder.iterdir())
    numbers = [
        int(match[1]) for path in paths if (match := pattern.fullmatch(path.name))
    ]
    # UUID 이름으로 남은 과거 채점도 앞선 채점 횟수에 포함한다.
    number = (
        max([len([path for path in paths if path.suffix == ".json"]), *numbers]) + 1
    )
    while True:
        identifier = f"{prefix}{number:02d}"
        try:
            (folder / f".{identifier}.reserve").touch(exist_ok=False)
            return identifier
        except FileExistsError:
            number += 1
