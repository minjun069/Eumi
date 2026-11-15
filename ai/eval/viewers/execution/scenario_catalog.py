"""현행 시나리오의 설명·기준 도식만 뷰어용으로 읽어 묶는다.

Eumi/ai에서 ``python -m eval.viewers.execution.scenario_catalog``.
실행 입력·결과와 업무 State는 변경하지 않는다.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "eval" / "scenarios" / "nodes"
DESTINATION = Path(__file__).with_name("scenarios.js")


class DiagramStep(TypedDict):
    node: str
    role: str
    frame: str
    action: str | None


class Scenario(TypedDict):
    id: str
    title: str
    role: str
    file: str
    sha256: str
    description: str
    upstream: str | None
    steps: list[DiagramStep]


class ScenarioCatalog(TypedDict):
    index_file: str
    index_sha256: str
    scenarios: list[Scenario]


def build_catalog(dataset: Path = DATASET) -> ScenarioCatalog:
    """색인의 직접 참조만 읽고 노드 순서와 역할 간 명시 연결을 보존한다."""
    dataset = dataset.resolve()
    index_path = dataset / "scenarios.json"
    raw_index = index_path.read_bytes()
    index = json.loads(raw_index.decode("utf-8-sig"))
    if index.get("schema_version") != "node-scenarios-v4":
        raise ValueError("Expected a node-scenarios-v4 index")
    scenarios: list[Scenario] = []
    for entry in index["scenarios"]:
        source = (dataset / entry["file"]).resolve()
        if not source.is_relative_to(dataset):
            raise ValueError("Scenario source must be inside its dataset")
        raw = source.read_bytes()
        body = json.loads(raw.decode("utf-8-sig"))
        if any(body[key] != entry[key] for key in ("id", "title")):
            raise ValueError("Scenario identity differs from its index")
        if body.get("scope") != "agent" or not body.get("steps"):
            raise ValueError("Expected a complete agent scenario")
        steps: list[DiagramStep] = []
        for step in body["steps"]:
            outputs = step.get("model_outputs", [])
            action = (
                outputs[0].get("name") if outputs and step["node"] == "act" else None
            )
            steps.append(
                DiagramStep(
                    node=step["node"],
                    role=step["role"],
                    frame=step["frame"],
                    action=action,
                )
            )
        scenarios.append(
            Scenario(
                id=body["id"],
                title=body["title"],
                role=body["agent_role"],
                file=entry["file"],
                sha256=sha256(raw).hexdigest(),
                description=body.get("task_rationale", {}).get("user_requirement")
                or body.get("start_state", {}).get("request", {}).get("goal", ""),
                upstream=body.get("upstream_scenario_id"),
                steps=steps,
            )
        )
    identifiers = {item["id"] for item in scenarios}
    if len(identifiers) != len(scenarios):
        raise ValueError("Duplicate scenario IDs")
    if any(item["upstream"] not in identifiers | {None} for item in scenarios):
        raise ValueError("Unknown upstream scenario")
    return ScenarioCatalog(
        index_file=index_path.name,
        index_sha256=sha256(raw_index).hexdigest(),
        scenarios=scenarios,
    )


def javascript(catalog: ScenarioCatalog) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    payload = (
        payload.replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return (
        "/* Generated dataset descriptions and reference diagrams. Do not edit. */\n"
        "(function(root,value){if(typeof module==='object'&&module.exports)"
        "module.exports=value;else root.ExecutionScenarioCatalog=value;})("
        "typeof globalThis==='object'?globalThis:this," + payload + ");\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="저장한 조회 자료와 원본의 일치만 확인"
    )
    args = parser.parse_args()
    content = javascript(build_catalog())
    if args.check:
        if (
            not DESTINATION.is_file()
            or DESTINATION.read_text(encoding="utf-8") != content
        ):
            raise SystemExit("Scenario catalog is stale; regenerate it first.")
        print("Scenario catalog matches the dataset.")
    else:
        DESTINATION.write_text(content, encoding="utf-8", newline="\n")
        print(DESTINATION)


if __name__ == "__main__":
    main()
