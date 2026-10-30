"""Run reproducible synthetic experiments, or explicitly select a real model."""

import argparse
import asyncio
import json
from pathlib import Path

from experiments.agents import build_agents
from experiments.models import build_models
from experiments.prompts import VERSION
from src.runtime import AgentRuntime
from src.settings import Settings
from src.state import Request

CASES = {
    "normal": "completed",
    "ask": "completed",
    "rework": "completed",
    "empty": "partial",
    "failure": "partial",
    "limit": "partial",
    "cancel": "cancelled",
}


async def run_case(scenario, *, real=False, answer="A", agent="request_handler"):
    settings = Settings(max_steps=4) if scenario == "limit" else Settings()
    region = {"empty": "NONE", "failure": "FAIL"}.get(scenario, "A")
    models = build_models(settings, real=real, scenario=scenario, region=region)
    app = AgentRuntime(build_agents(models), settings)
    request = Request(
        goal="가상 지역의 활동지수 변화를 설명하고 표로 보여주세요.",
        subject={} if scenario in {"ask", "cancel"} else {"region": region},
    )
    state = await app.start(
        agent, request, instruction_version=VERSION, data_versions={"analysis": VERSION}
    )
    if state["execution"]["status"] == "waiting_input":
        execution = state["execution"]
        if scenario == "cancel":
            state = await app.cancel(execution["run_id"])
        else:
            state = await app.resume(
                execution["run_id"],
                pending_id=execution["pending"]["id"],
                expected_input_version=execution["input_version"],
                content=answer,
                data_versions=execution["data_versions"],
            )
    return state


async def main(args):
    if args.real and args.suite:
        raise ValueError("--suite is deterministic; select one --real scenario instead")
    report = []
    for scenario in CASES if args.suite else [args.scenario]:
        state = await run_case(
            scenario, real=args.real, answer=args.answer, agent=args.agent
        )
        status = state["execution"]["status"]
        passed = status == CASES[scenario]
        report.append(
            {
                "scenario": scenario,
                "mode": "real" if args.real else "scripted",
                "expected_status": CASES[scenario],
                "passed": passed,
                "state": state,
            }
        )
        print(
            f"{scenario}: {status}; expected={CASES[scenario]}; passed={passed}; "
            f"usage={state['execution']['attempts']}"
        )
    await asyncio.to_thread(save_report, report, Path(args.output))
    return 0 if all(case["passed"] for case in report) else 1


def save_report(report, output):
    output.mkdir(parents=True, exist_ok=True)
    for case in report:
        for index, artifact in enumerate(case["state"]["results"]):
            if artifact["data"].get("format") == "html":
                (output / f"{case['scenario']}-{index}.html").write_text(
                    artifact["data"]["html"], encoding="utf-8"
                )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=CASES, default="normal")
    parser.add_argument("--suite", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--answer", default="A")
    parser.add_argument(
        "--agent",
        choices=["request_handler", "analysis", "visualization"],
        default="request_handler",
    )
    parser.add_argument("--output", default="outputs/experiment")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
