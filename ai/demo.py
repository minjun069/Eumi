"""임시 입력·모의 출력을 실제 공통 그래프에 연결해 실행한다."""

import argparse
import asyncio
import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from experiments.fixtures import CASES, Scenario, initial_state, mock_nodes
from src.graph import compile_graph
from src.state import State, state_adapter


async def run_case(
    scenario: Scenario, *, answer: str = "추가 정보", analysis_event: bool = False
) -> State:
    if not answer.strip():
        raise ValueError("A non-empty answer is required")
    nodes, finish = mock_nodes(scenario)
    graph = compile_graph(
        nodes,
        finish=finish,
        analysis_event=analysis_event,
        checkpointer=InMemorySaver(),
    )
    state = initial_state()
    config = {"configurable": {"thread_id": state["execution"]["run_id"]}}
    result = await graph.ainvoke(state, config)
    if result["execution"]["status"] == "waiting_input":
        result = await graph.ainvoke(Command(resume=answer), config)
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


async def main(args):
    report = []
    for scenario in CASES if args.suite else [args.scenario]:
        state = await run_case(
            scenario, answer=args.answer, analysis_event=args.analysis_event
        )
        status = state["execution"]["status"]
        passed = status == CASES[scenario]
        report.append({"scenario": scenario, "passed": passed, "state": state})
        print(f"{scenario}: {status}; passed={passed}")
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
