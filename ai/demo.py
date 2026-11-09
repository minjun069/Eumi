"""임시 입력·모의 출력을 실제 공통 그래프에 연결해 실행한다."""

import argparse
import asyncio
import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from experiments.fixtures import CASES, Scenario, initial_state, mock_nodes
from report_html import build_report
from src.execution_trace import TraceRecorder, recording
from src.graph import compile_graph
from src.monitoring import (
    create_monitoring,
    record_execution,
    shutdown_monitoring,
    trace_execution,
)
from src.runtime import resume_graph, run_graph
from src.settings import Settings
from src.state import State, state_adapter


async def run_case(
    scenario: Scenario,
    state: State,
    *,
    answer: str = "추가 정보",
    monitoring=None,
) -> State:
    if not answer.strip():
        raise ValueError("A non-empty answer is required")
    nodes, finish = mock_nodes(scenario)
    graph = compile_graph(
        nodes,
        finish=finish,
        checkpointer=InMemorySaver(),
    )
    with trace_execution(monitoring, state["execution"]) as (config, observation):
        result = await run_graph(graph, state, config)
        record_execution(observation, result)
    if result["execution"]["status"] == "waiting_input":
        with trace_execution(monitoring, result["execution"], phase="resume") as (
            config,
            observation,
        ):
            result = await resume_graph(
                graph, result["execution"]["run_id"], result["response"]["id"], answer, config
            )
            record_execution(observation, result)
    return state_adapter.validate_python(result)


def save_report(report, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    serialized = [
        case | {"state": state_adapter.dump_python(case["state"], mode="json")}
        for case in report
    ]
    (output / "report.json").write_text(
        json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    build_report([output / "report.json"], output / "report.html")


async def main(args):
    monitoring = create_monitoring(Settings())
    try:
        return await run_suite(args, monitoring)
    finally:
        await shutdown_monitoring(monitoring)


async def run_suite(args, monitoring):
    report = []
    for scenario in CASES if args.suite else [args.scenario]:
        recorder = TraceRecorder(
            journal=args.output / scenario / "trace.jsonl" if args.output else None
        )
        with recording(recorder):
            state = await run_case(
                scenario,
                initial_state(
                    "analysis_pipeline" if args.analysis_event else "user_request"
                ),
                answer=args.answer,
                monitoring=monitoring,
            )
        status = state["execution"]["status"]
        passed = status == CASES[scenario]
        report.append(
            {
                "scenario": scenario,
                "passed": passed,
                "state": state,
                "trace": recorder.export(),
            }
        )
        print(
            f"{scenario}: {status}; passed={passed}; "
            f"run_id={state['execution']['run_id']}"
        )
    if args.output:
        await asyncio.to_thread(save_report, report, args.output)
    return 0 if all(case["passed"] for case in report) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=CASES, default="complete")
    parser.add_argument("--suite", action="store_true")
    parser.add_argument("--answer", default="추가 정보")
    parser.add_argument("--analysis-event", action="store_true")
    parser.add_argument("--output", type=Path)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
