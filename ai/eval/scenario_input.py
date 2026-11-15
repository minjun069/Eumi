"""저장된 시나리오의 진입 상태를 실제 에이전트 실행 입력으로 읽는다."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import Literal

from pydantic import TypeAdapter
from typing_extensions import TypedDict

from eval.execution.schema import COMMON_CHECKS, REPORT_CHECKS
from eval.schema import ROLES, Identifier, InitialInput, Suite, suite_adapter
from src.prompting import Role
from src.state import State, state_adapter

ScenarioUnit = Literal["agent", "workflow"]
EntryState = Literal["start_state", "entry_transition.before_state"]


class ScenarioSelection(TypedDict):
    scenario_id: str
    scenario_file: str
    unit: ScenarioUnit
    target: str
    entry_state: EntryState
    providers: list[str]


class LoadedScenarios(TypedDict):
    suite: Suite
    source_files_sha256: dict[str, str]
    selection: list[ScenarioSelection]


class ScenarioFile(TypedDict):
    id: Identifier
    title: str
    file: str


def _inside(root: Path, reference: str) -> Path:
    if (
        not isinstance(reference, str)
        or not reference
        or PureWindowsPath(reference).drive
        or ":" in reference
    ):
        raise ValueError(f"Invalid dataset path: {reference}")
    relative = Path(reference)
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root):
        raise ValueError(f"Path is outside the dataset: {reference}")
    return path


def _initial(state: State) -> InitialInput:
    return {
        "request": deepcopy(state["request"]),
        "messages": deepcopy(state["messages"]),
        "results": deepcopy(state["results"]),
        "response": deepcopy(state["response"]),
        "execution": deepcopy(state["execution"]),
        "event": state["execution"]["event"],
    }


def _entry(body: dict, unit: ScenarioUnit) -> tuple[State, EntryState]:
    """미래 결과는 읽지 않고 현재 진입 상태와 첫 노드 경계만 대조한다."""
    steps = body.get("steps")
    if body.get("scope") != "agent" or not isinstance(steps, list) or not steps:
        raise ValueError("Scenario requires agent scope and nonempty steps")
    first = steps[0]
    role = body["agent_role"]
    if (
        not isinstance(first, dict)
        or first.get("role") != role
        or first.get("frame") != "root"
        or first.get("node")
        != ("decide" if role.startswith("report_") else "interpret")
    ):
        raise ValueError("Scenario first node does not match its agent role")
    state = state_adapter.validate_python(body.get("start_state"))
    first_state = state_adapter.validate_python(first.get("before_state"))
    if state != first_state or body.get("event") != state["execution"]["event"]:
        raise ValueError("Scenario start_state, first node and event must agree")
    expected_event = (
        "analysis_pipeline" if role.startswith("report_") else "user_request"
    )
    if state["execution"]["event"] != expected_event:
        raise ValueError("Scenario event does not match its agent role")
    if unit == "agent":
        return state, "start_state"
    entry = body.get("entry_transition", {})
    if (
        role != "report_selection"
        or not isinstance(entry, dict)
        or entry.get("kind") != "report_handoff"
    ):
        raise ValueError("Workflow requires a report_selection entry transition")
    if state_adapter.validate_python(entry.get("after_state")) != state:
        raise ValueError("Report entry transition must end at start_state")
    before = state_adapter.validate_python(entry.get("before_state"))
    if before["execution"]["event"] != "analysis_pipeline" or any(
        record["decision"] == "report_stage" for record in before["results"]
    ):
        raise ValueError("Workflow input must precede the first report stage")
    if (
        any(before[key] != state[key] for key in ("request", "messages", "response"))
        or state["results"][:-1] != before["results"]
        or not state["results"]
        or state["results"][-1]["decision"] != "report_stage"
        or (state["results"][-1].get("action") or {}).get("name")
        != "report_selection_agent"
        or any(
            before["execution"][key] != state["execution"][key]
            for key in ("run_id", "event", "version", "budget")
        )
    ):
        raise ValueError("Report entry transition must preserve its input")
    return before, "entry_transition.before_state"


def load_scenario_suite(
    path: Path,
    *,
    unit: ScenarioUnit = "agent",
    target: Role | Literal["report"] | None = None,
    case_ids: list[str] | None = None,
) -> LoadedScenarios:
    """선택한 최초 상태와 자료원만 Suite로 변환하고 원본 파일은 변경하지 않는다.

    노드 사례에서는 자료원 선언만 읽는다. 작성한 미래 답변·평가 기준·하위
    반환 고정값은 업무 입력으로 옮기지 않는다. 파일 해시와 선택 범위는
    실행 관측 정보이며 State에 추가하지 않는다.
    """
    if unit not in {"agent", "workflow"}:
        raise ValueError("Scenario unit must be agent or workflow")
    if target is not None and target not in (ROLES if unit == "agent" else {"report"}):
        raise ValueError(f"Unknown {unit} target: {target}")
    path = Path(path).resolve()
    root = path.parent
    hashes: dict[str, str] = {}
    cache: dict[Path, tuple[dict, str]] = {}

    def read(source: Path, *, evidence: bool = True) -> dict:
        if source not in cache:
            raw = source.read_bytes()
            document = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(document, dict):
                raise ValueError(f"Expected a JSON object: {source.name}")
            cache[source] = document, sha256(raw).hexdigest()
        document, digest = cache[source]
        if evidence:
            hashes[source.relative_to(root).as_posix()] = digest
        return document

    index = read(path)
    if index.get("schema_version") != "node-scenarios-v4":
        raise ValueError("Expected a node-scenarios-v4 index")
    entries = TypeAdapter(list[ScenarioFile]).validate_python(index.get("scenarios"))
    known = {entry["id"] for entry in entries}
    if len(known) != len(entries):
        raise ValueError("Duplicate scenario IDs")
    if case_ids is not None:
        if not case_ids or len(set(case_ids)) != len(case_ids):
            raise ValueError("Scenario case IDs must be nonempty and unique")
        if set(case_ids) - known:
            raise ValueError(f"Unknown scenario IDs: {sorted(set(case_ids) - known)}")
        entries = [entry for entry in entries if entry["id"] in case_ids]

    selected = []
    for entry in entries:
        source = _inside(root, entry["file"])
        body = read(source, evidence=False)
        role = body.get("agent_role")
        matches = (
            role == "report_selection"
            if unit == "workflow"
            else target is None or role == target
        )
        if not matches:
            if case_ids is not None:
                raise ValueError(f"Scenario does not match unit/target: {entry['id']}")
            continue
        if any(body.get(key) != entry[key] for key in ("id", "title")):
            raise ValueError(f"Scenario identity does not match index: {entry['id']}")
        if not isinstance(role, str) or role not in ROLES:
            raise ValueError(f"Unknown scenario agent role: {role}")
        read(source)
        selected.append((entry, body))
    if not selected:
        raise ValueError("No scenarios match the selection")

    snapshot_path = _inside(root, index.get("source_snapshot"))
    snapshot = read(snapshot_path)
    snapshot_key = snapshot_path.relative_to(root).as_posix()
    if hashes[snapshot_key] != index.get("source_snapshot_sha256"):
        raise ValueError("Scenario source snapshot SHA256 does not match")
    datasets, catalog = snapshot.get("datasets", {}), snapshot.get("catalog", {})
    if not isinstance(datasets, dict) or not isinstance(catalog, dict):
        raise ValueError("Scenario snapshot requires datasets and catalog objects")

    cases, selections = [], []
    for entry, body in selected:
        state, entry_state = _entry(body, unit)
        providers = set()
        for step in body["steps"]:
            if not isinstance(step, dict):
                raise ValueError("Scenario steps must be objects")
            reference = step.get("input_ref", "")
            match = (
                re.fullmatch(r"([^#]+)#/cases/(0|[1-9][0-9]*)/initial", reference)
                if isinstance(reference, str)
                else None
            )
            if match is None:
                raise ValueError(f"Invalid scenario node input reference: {reference}")
            node_suite = read(_inside(root, match[1]))
            node_cases = node_suite.get("cases")
            node_datasets = node_suite.get("datasets", {})
            offset = int(match[2])
            if (
                node_suite.get("schema_version") != "evaluation-suite-v1"
                or node_suite.get("data_source", "prepared") != "prepared"
                or not isinstance(node_cases, list)
                or not isinstance(node_datasets, dict)
                or offset >= len(node_cases)
            ):
                raise ValueError(f"Missing referenced node case: {reference}")
            node_case = node_cases[offset]
            if (
                not isinstance(node_case, dict)
                or node_case.get("id") != step.get("case_id")
                or node_case.get("unit") != "node"
                or node_case.get("target") != step.get("node")
                or node_case.get("role") != step.get("role")
            ):
                raise ValueError(f"Node case identity does not match step: {reference}")
            names = node_case.get("providers", list(node_datasets))
            if (
                not isinstance(names, list)
                or any(not isinstance(name, str) or not name for name in names)
                or len(names) != len(set(names))
                or set(names) - datasets.keys()
                or set(names) - node_datasets.keys()
            ):
                raise ValueError(f"Invalid or missing scenario provider: {reference}")
            providers.update(names)
        effective_target = "report" if unit == "workflow" else body["agent_role"]
        case = {
            "id": entry["id"],
            "unit": unit,
            "target": effective_target,
            "purpose": entry["title"],
            "initial": _initial(state),
            "providers": sorted(providers),
            "dependencies": "real",
        }
        if effective_target in {"request", "report"}:
            case["assessment"] = {
                "required": True,
                "checks": list(COMMON_CHECKS)
                + (list(REPORT_CHECKS) if unit == "workflow" else []),
                "expected": {
                    "schema_version": "execution-expectations-v1",
                    "situation": "normal",
                    "entry": "initial",
                },
            }
        cases.append(case)
        selections.append(
            ScenarioSelection(
                scenario_id=entry["id"],
                scenario_file=_inside(root, entry["file"]).relative_to(root).as_posix(),
                unit=unit,
                target=effective_target,
                entry_state=entry_state,
                providers=sorted(providers),
            )
        )
    used = {name for case in cases for name in case["providers"]}
    suite = suite_adapter.validate_python(
        {
            "schema_version": "evaluation-suite-v1",
            "id": f"node-scenarios-{unit}-v1",
            "data_source": "prepared",
            "datasets": {name: deepcopy(datasets[name]) for name in sorted(used)},
            "catalog": {
                name: deepcopy(catalog[name])
                for name in sorted(used)
                if name in catalog
            },
            "cases": cases,
        }
    )
    return LoadedScenarios(
        suite=suite, source_files_sha256=hashes, selection=selections
    )
