"""채점기가 공유하는 실행 증거 읽기와 새 채점 결과 저장."""

import json
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, NotRequired

from pydantic import ConfigDict, Field, JsonValue, TypeAdapter, with_config
from typing_extensions import TypedDict

from eval.assessment_store import write_assessment
from eval.naming import reserve_assessment_id, stored_batch_name
from eval.schema import Identifier, PositiveInt, Unit, suite_adapter
from src.execution_trace import TraceRecorder

Text = Annotated[str, Field(min_length=1)]
RunStatus = Literal["running", "returned", "error", "cancelled"]
NonnegativeInt = Annotated[int, Field(ge=0, strict=True)]


@with_config(ConfigDict(extra="forbid"))
class ScoringPlan(TypedDict):
    case_ids: list[Identifier]
    repeat: PositiveInt


@with_config(ConfigDict(extra="forbid"))
class StoredRun(TypedDict):
    case_id: Identifier
    run_id: Text
    unit: Unit
    target: Text
    repetition: PositiveInt
    status: RunStatus
    path: Text


@with_config(ConfigDict(extra="forbid"))
class StoredBatch(TypedDict):
    schema_version: Literal["evaluation-batch-v1"]
    id: Text
    suite_id: Identifier
    status: RunStatus
    started_at: Text
    ended_at: str | None
    planned_runs: NonnegativeInt
    runs: list[StoredRun]
    plan: ScoringPlan
    failure: NotRequired[dict[str, JsonValue]]


class StoredRunInfo(TypedDict):
    id: Text
    suite_id: Identifier
    case_id: Identifier
    repetition: PositiveInt
    unit: Unit
    target: Text
    role: str | None
    dependencies: Literal["real", "stub"]
    status: RunStatus
    started_at: Text
    ended_at: str | None
    elapsed_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None


class StoredReport(TypedDict):
    schema_version: Literal["evaluation-run-v1"]
    run: StoredRunInfo
    output: JsonValue
    failure: dict[str, JsonValue] | None
    trace: dict[str, JsonValue]
    assessment: dict[str, JsonValue]
    fixtures: dict[str, JsonValue]
    journal_saved: bool


batch_adapter = TypeAdapter(StoredBatch)
report_adapter = TypeAdapter(StoredReport)


def _reject_links(path: Path) -> None:
    """파일뿐 아니라 상위 폴더의 심볼릭 링크와 Windows junction도 거부한다."""
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError(f"평가 파일 경로에 링크를 사용할 수 없습니다: {part.name}")


def _inside(root: Path, relative: str) -> Path:
    windows = PureWindowsPath(relative)
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or windows.drive
        or windows.root
        or "\\" in relative
        or any(part in (".", "..") or ":" in part for part in relative.split("/"))
        or any(not part for part in relative.split("/"))
    ):
        raise ValueError("평가 증거 경로는 폴더 내부의 상대 경로여야 합니다")
    path = root.joinpath(*parts)
    _reject_links(path)
    if not path.resolve().is_relative_to(root):
        raise ValueError("평가 증거 경로가 결과 폴더를 벗어납니다")
    return path


def _read(path: Path, *, root=None, hashes=None) -> tuple[dict, str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: JSON 객체가 필요합니다")
    return value, sha256(raw).hexdigest()


def _report(root, entry, case, suite_id, hashes):
    path = _inside(root, entry["path"])
    if entry["path"] != f"runs/{entry['run_id']}/report.json":
        raise ValueError("실행 ID와 report.json 경로가 일치하지 않습니다")
    if not path.exists():
        return None
    value, digest = _read(path, root=root, hashes=hashes)
    report_adapter.validate_python(value)
    run = value["run"]
    expected = {
        "id": entry["run_id"],
        "suite_id": suite_id,
        "case_id": case["id"],
        "unit": case["unit"],
        "target": case["target"],
        "repetition": entry["repetition"],
        "role": case["target"] if case["unit"] == "agent" else case.get("role"),
        "dependencies": case.get("dependencies", "real"),
    }
    if any(run[key] != expected_value for key, expected_value in expected.items()):
        raise ValueError("사례·묶음 등록과 저장된 실행 결과의 식별 정보가 다릅니다")
    state = value.get("state")
    if state is not None:
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("execution"), dict)
            or state["execution"].get("run_id") != run["id"]
        ):
            raise ValueError("실행 결과와 State의 실행 ID가 다릅니다")
    hashes[entry["path"]] = digest
    return value


def load_batch(folder: Path):
    """저장 계획과 증거 경로의 공통 검증. 업무 실행을 호출하지 않는다."""
    root = Path(folder).absolute()
    _reject_links(root)
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("평가할 결과 폴더가 필요합니다")
    hashes = {}
    suite_value, suite_hash = _read(
        _inside(root, "suite.json"), root=root, hashes=hashes
    )
    suite = suite_adapter.validate_python(suite_value)
    batch_value, batch_hash = _read(_inside(root, "batch.json"))
    if "plan" not in batch_value:
        raise ValueError("평가 계획 없음: case_ids와 repeat가 저장된 묶음이 필요합니다")
    batch = batch_adapter.validate_python(batch_value)
    if batch["suite_id"] != suite["id"]:
        raise ValueError("묶음과 입력 자료의 suite_id가 다릅니다")
    plan = batch["plan"]
    case_ids = plan["case_ids"]
    if not case_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError("평가 계획의 사례 ID는 하나 이상이며 중복될 수 없습니다")
    all_cases = {case["id"]: case for case in suite["cases"]}
    if set(case_ids) - all_cases.keys():
        raise ValueError("평가 계획에 입력 자료에 없는 사례가 있습니다")
    cases = [all_cases[case_id] for case_id in case_ids]
    if batch["planned_runs"] != len(cases) * plan["repeat"]:
        raise ValueError("예정 실행 수와 평가 계획이 일치하지 않습니다")

    entries = {}
    run_ids = set()
    for entry in batch["runs"]:
        key = (entry["case_id"], entry["repetition"])
        if entry["run_id"] in run_ids or key in entries:
            raise ValueError("실행 ID 또는 사례·반복 등록이 중복되었습니다")
        if entry["case_id"] not in case_ids or entry["repetition"] > plan["repeat"]:
            raise ValueError("등록된 실행이 평가 계획에 포함되지 않습니다")
        case = all_cases[entry["case_id"]]
        if any(entry[field] != case[field] for field in ("unit", "target")):
            raise ValueError("등록된 실행과 입력 사례의 평가 대상이 다릅니다")
        run_ids.add(entry["run_id"])
        entries[key] = entry

    hashes.update({"suite.json": suite_hash, "batch.json": batch_hash})
    return root, suite, batch, cases, entries, hashes


def result_destination(
    root: Path, evaluation_id: str, output: Path | None = None
) -> Path:
    destination = (
        Path(output).absolute()
        if output is not None
        else root / "assessments" / f"{evaluation_id}.json"
    )
    _reject_links(destination)
    if destination.exists():
        raise FileExistsError("평가 결과는 기존 파일·폴더를 덮어쓸 수 없습니다")
    if destination.resolve().is_relative_to(root / "runs"):
        raise ValueError("평가 결과를 실행 원본의 runs 폴더에 저장할 수 없습니다")
    return destination


def prepare_result(root, batch, cases, output: Path | None = None) -> tuple[str, Path]:
    if output is not None:
        result_destination(root, "pending", output)
    _reject_links(root / "assessments")
    name = stored_batch_name(root, batch["id"], batch["started_at"], cases)
    identifier = reserve_assessment_id(root, name)
    return identifier, result_destination(root, identifier, output)


def save_result(root: Path, result: dict, output: Path | None = None) -> Path:
    destination = result_destination(root, result["id"], output)
    write_assessment(destination, TraceRecorder().snapshot(result), source_batch=root)
    from eval.viewers.catalog import refresh_for

    refresh_for(root)
    return destination
