"""Build shared independent node cases and complete current-execution paths."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from eval.schema import suite_adapter
from eval.scripts.node_dataset_basic_reports import build_basic_report_paths
from eval.scripts.node_dataset_basic_users import build_basic_user_paths
from eval.scripts.node_dataset_coverage import build_coverage
from eval.scripts.node_dataset_paths import PathRecorder, assemble_paths, validate_paths
from eval.scripts.node_dataset_storage import SCHEMA_VERSION, write_scenarios

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "eval/scenarios/nodes"
NODES = ("interpret", "act", "decide", "compose", "ask")


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


async def build_paths(snapshot):
    recorder = PathRecorder(snapshot)
    await build_basic_user_paths(snapshot, recorder)
    await build_basic_report_paths(snapshot, recorder)
    return recorder


def build_dataset(destination: Path = DESTINATION) -> dict:
    snapshot_path = destination / "snapshots/data.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    recorder = asyncio.run(build_paths(snapshot))
    cases, sidecar = assemble_paths([], [], recorder)
    sidecar.update(
        schema_version=SCHEMA_VERSION,
        dataset_scope="basic-agent-paths",
        archived_dataset="../nodes-extended-v2/archive.md",
        source_snapshot="snapshots/data.json",
        source_snapshot_sha256=sha256(snapshot_path.read_bytes()).hexdigest(),
        input_contract=(
            "evaluation-suite-v1: independent initial input, separate assessment"
        ),
        history_contract=(
            "Agent entry-to-return paths regenerated through current production "
            "nodes with authored model responses and immutable DB evidence. "
            "Not a production model trace."
        ),
        flow_contract=(
            "Every scenarios entry starts at start_state and ends at terminal. "
            "Nested child calls are expanded inside their parent agent scenario. "
            "Standalone specialist scenarios start from the child State produced "
            "by an actual request-agent call. Their entry_transition records the "
            "three preparatory parent nodes and the actual child return; those "
            "parent nodes are excluded from evaluated steps and node cases. "
            "Report roles are separate agent scenarios with approved upstream "
            "terminal State carried into the next entry. No partial groups."
        ),
        model_output_contract=(
            "step.model_outputs are scripted normal responses "
            "authored for each input's required work and available evidence. "
            "case.assessment stores expected behavior separately from model input. "
            "Agreement with scripted outputs alone does not establish that a "
            "decision is appropriate for the request."
        ),
        runtime_sources={
            str(p.relative_to(ROOT)).replace("\\", "/"): sha256(
                p.read_bytes()
            ).hexdigest()
            for p in [
                ROOT / "src/agent_nodes.py",
                ROOT / "src/graph.py",
                ROOT / "src/state.py",
                ROOT / "src/report_flow.py",
                ROOT / "src/execution.py",
                ROOT / "src/prompting.py",
                ROOT / "src/tool_specs.py",
                ROOT / "src/tools/tableau_catalog.json",
                ROOT / "eval/schema.py",
                ROOT / "eval/runner.py",
                ROOT / "eval/scripts/build_node_dataset.py",
                ROOT / "eval/scripts/node_dataset_paths.py",
                ROOT / "eval/scripts/node_dataset_storage.py",
                ROOT / "eval/scripts/node_dataset_basic_users.py",
                ROOT / "eval/scripts/node_dataset_basic_reports.py",
                ROOT / "eval/scripts/node_dataset_user_paths.py",
                ROOT / "eval/scripts/node_dataset_report_paths.py",
                ROOT / "eval/scripts/node_dataset_users.py",
                ROOT / "eval/scripts/node_dataset_reports.py",
            ]
        },
    )
    suites = {}
    for node in NODES:
        node_cases = [case for case in cases if case["target"] == node]
        used = set()
        for position, case in enumerate(node_cases):
            used.update(case.get("providers", snapshot["datasets"]))
            sidecar["case_index"][case["id"]].update(
                input_ref=f"{node}.json#/cases/{position}/initial",
                expectation_ref=f"{node}.json#/cases/{position}/assessment",
            )
        suite = {
            "schema_version": "evaluation-suite-v1",
            "id": f"node-basic-{node}-v1",
            "data_source": "prepared",
            "datasets": {
                k: deepcopy(v) for k, v in snapshot["datasets"].items() if k in used
            },
            "catalog": {
                k: deepcopy(v) for k, v in snapshot["catalog"].items() if k in used
            },
            "cases": node_cases,
        }
        suite_adapter.validate_python(suite)
        suites[node] = suite
    for group in [*sidecar["scenarios"], *sidecar["partial_groups"]]:
        for step in group["steps"]:
            entry = sidecar["case_index"][step["case_id"]]
            for key in ("input_ref", "expectation_ref", "node", "role"):
                step[key] = entry[key]
    errors = validate_paths(sidecar, cases)
    if errors:
        raise ValueError(json.dumps(errors[:20], ensure_ascii=False))
    coverage = build_coverage(cases, sidecar)
    for node, suite in suites.items():
        write_json(destination / f"{node}.json", suite)
    write_scenarios(destination / "scenarios.json", sidecar)
    write_json(destination / "coverage.json", coverage)
    return {**sidecar["summary"], "coverage": coverage["summary"]}


if __name__ == "__main__":
    print(json.dumps(build_dataset(), ensure_ascii=False, indent=2))
