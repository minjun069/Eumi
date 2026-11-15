"""저장된 평가 원본을 선택해서 읽기 위한 경량 경로 목록을 만든다.

실행·채점 원본은 수정하지 않는다. 표준 라이브러리만 사용한다.
"""

import argparse
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULT_ROOTS = (
    PROJECT_ROOT / "eval" / "outputs" / "evaluations",
    PROJECT_ROOT / "eval" / "outputs" / "database-evaluations",
)
CATALOG_PATH = PROJECT_ROOT / "eval" / "outputs" / "evaluation-viewer" / "catalog.json"
ARTIFACTS = {
    "batch.json",
    "suite.json",
    "report.json",
    "case.json",
    "manifest.json",
    "trace.jsonl",
}
NODE_SCENARIOS = Path("eval/scenarios/nodes/scenarios.json")


class LocalFile(TypedDict):
    path: str
    size_bytes: int
    modified_at: str


class ReadIssue(TypedDict):
    severity: str
    path: str
    message: str


class AssessmentEntry(TypedDict):
    path: str
    format: Literal["legacy"]
    id: NotRequired[str]
    batch_id: NotRequired[str]
    suite_id: NotRequired[str]
    report_schema_version: NotRequired[str]
    assessed_at: NotRequired[str]
    status: NotRequired[str]
    method: NotRequired[str]
    judge_model: NotRequired[str | None]


class BatchEntry(TypedDict):
    path: str
    suite_path: str | None
    units: list[str]
    assessments: list[AssessmentEntry]
    id: NotRequired[str]
    suite_id: NotRequired[str]
    status: NotRequired[str]
    started_at: NotRequired[str]
    ended_at: NotRequired[str | None]
    planned_runs: NotRequired[int]
    registered_runs: NotRequired[int]
    node_targets: NotRequired[list[str]]


class LocalResults(TypedDict):
    version: Literal["evaluation-viewer-local-v2"]
    generated_at: str
    roots: list[str]
    batches: list[BatchEntry]
    files: list[LocalFile]
    scenario_index: str | None
    issues: list[ReadIssue]


def _files(root: Path):
    """심볼릭 링크·Windows junction을 따라 다른 폴더를 읽지 않는다."""
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        return

    def unreadable(error):
        raise error

    for directory, folders, names in os.walk(
        root, followlinks=False, onerror=unreadable
    ):
        parent = Path(directory)
        folders[:] = sorted(
            name
            for name in folders
            if not name.startswith(".")
            and not (parent / name).is_symlink()
            and not (parent / name).is_junction()
        )
        for name in sorted(names):
            path = parent / name
            if not path.is_symlink() and path.resolve().is_relative_to(root.resolve()):
                yield path


def _metadata(path: Path, relative: str, issues: list[ReadIssue]) -> dict:
    """묶음·채점 JSON에서 목록용 필드를 읽고 본문은 목록에 넣지 않는다."""
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("Metadata must be an object")
        return document
    except (OSError, UnicodeError, ValueError) as error:
        issues.append(
            {
                "severity": "error",
                "path": relative,
                "message": "조회 목록의 메타데이터를 읽지 못했습니다: "
                + type(error).__name__,
            }
        )
        return {}


def _assessment_entry(
    path: Path, relative: str, issues: list[ReadIssue]
) -> AssessmentEntry:
    entry: AssessmentEntry = {"path": relative, "format": "legacy"}
    document = _metadata(path, relative, issues)
    for name in ("id", "batch_id", "suite_id", "assessed_at", "status", "method"):
        if isinstance(document.get(name), str):
            entry[name] = document[name]
    if isinstance(document.get("schema_version"), str):
        entry["report_schema_version"] = document["schema_version"]
    if "judge_model" in document and (
        document["judge_model"] is None or isinstance(document["judge_model"], str)
    ):
        entry["judge_model"] = document["judge_model"]
    return entry


def _batch_entry(
    folder: Path,
    sources: dict[str, Path],
    project_root: Path,
    issues: list[ReadIssue],
) -> BatchEntry:
    relative = (folder / "batch.json").relative_to(project_root).as_posix()
    suite = (folder / "suite.json").relative_to(project_root).as_posix()
    entry: BatchEntry = {
        "path": relative,
        "suite_path": suite if suite in sources else None,
        "units": [],
        "node_targets": [],
        "assessments": [],
    }
    document = _metadata(folder / "batch.json", relative, issues)
    for name in ("id", "suite_id", "status", "started_at"):
        if isinstance(document.get(name), str):
            entry[name] = document[name]
    if "ended_at" in document and (
        document["ended_at"] is None or isinstance(document["ended_at"], str)
    ):
        entry["ended_at"] = document["ended_at"]
    if type(document.get("planned_runs")) is int:
        entry["planned_runs"] = document["planned_runs"]
    if isinstance(document.get("runs"), list):
        entry["registered_runs"] = len(document["runs"])
        entry["units"] = sorted(
            {
                run["unit"]
                for run in document["runs"]
                if isinstance(run, dict) and isinstance(run.get("unit"), str)
            }
        )
        entry["node_targets"] = sorted(
            {
                run["target"]
                for run in document["runs"]
                if isinstance(run, dict)
                and run.get("unit") == "node"
                and isinstance(run.get("target"), str)
            }
        )
    for name, path in sorted(sources.items()):
        assessment_root = folder / "assessments"
        legacy = path.parent == assessment_root and path.suffix.lower() == ".json"
        if legacy:
            entry["assessments"].append(_assessment_entry(path, name, issues))
    return entry


def build_catalog(
    roots: tuple[Path, ...] = RESULT_ROOTS,
    destination: Path = CATALOG_PATH,
    *,
    project_root: Path = PROJECT_ROOT,
) -> LocalResults:
    """원본 사본 없이 파일 통계·최소 메타데이터만 원자적으로 저장한다."""
    project_root = project_root.resolve()
    sources: dict[str, Path] = {}
    issues: list[ReadIssue] = []
    labels = []
    batch_folders: set[Path] = set()
    for root in roots:
        root = root.absolute()
        label = root.relative_to(project_root).as_posix()
        labels.append(label)
        paths = list(_files(root))
        batches = {path.parent for path in paths if path.name == "batch.json"}
        batch_folders.update(batches)
        for path in paths:
            if not any(parent in batches for parent in path.parents):
                continue
            if path.name in ARTIFACTS or (
                path.suffix.lower() == ".json" and path.parent.name == "assessments"
            ):
                sources[path.relative_to(project_root).as_posix()] = path
    index = project_root / NODE_SCENARIOS
    scenario_index = None
    if (
        index.is_file()
        and index.resolve().is_relative_to(project_root)
        and not any(
            path.is_symlink() or path.is_junction()
            for path in (index, *index.parents)
            if path == project_root or project_root in path.parents
        )
    ):
        scenario_index = NODE_SCENARIOS.as_posix()
        sources[scenario_index] = index
    files: list[LocalFile] = []
    for relative, path in sorted(sources.items()):
        try:
            stat = path.stat()
            files.append(
                {
                    "path": relative,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, UTC
                    ).isoformat(),
                }
            )
        except OSError as error:
            issues.append(
                {
                    "severity": "error",
                    "path": relative,
                    "message": "조회 목록의 파일 정보를 읽지 못했습니다: "
                    + type(error).__name__,
                }
            )
    result: LocalResults = {
        "version": "evaluation-viewer-local-v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "roots": labels,
        "batches": [
            _batch_entry(folder, sources, project_root, issues)
            for folder in sorted(batch_folders)
        ],
        "files": files,
        "scenario_index": scenario_index,
        "issues": issues,
    }
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(payload + "\n")
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return result


def refresh_for(batch_folder: Path) -> None:
    """기본 결과 폴더의 저장 완료 뒤 조회 자료를 갱신한다. 평가 성공 여부와 분리한다."""
    try:
        folder = batch_folder.resolve()
        if not any(folder.is_relative_to(root.resolve()) for root in RESULT_ROOTS):
            return
        build_catalog()
    except (OSError, ValueError) as error:
        logging.getLogger(__name__).warning(
            "평가 원본은 저장됐으나 뷰어 자동 조회 자료를 갱신하지 못했습니다 (%s). "
            "python -m eval.viewers.catalog로 다시 생성할 수 있습니다.",
            type(error).__name__,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = build_catalog()
    print(
        f"{CATALOG_PATH}\n{len(result['files'])} files; "
        f"{len(result['issues'])} read issues"
    )


if __name__ == "__main__":
    main()
