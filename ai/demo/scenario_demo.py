"""OpenAI와 실제 공통 그래프·도구로 S1~S3를 실행하고 상세 HTML을 저장한다."""

import argparse
import asyncio
from copy import deepcopy
from pathlib import Path
from time import monotonic

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from experiments.scenario_checks import evaluate
from experiments.scenario_fixtures import CATALOG, PROVIDERS, S1, S2, S3, SCREEN
from report_html import build_report
from src.agent_nodes import build_nodes, finish
from src.execution_trace import TraceRecorder, recording, safe_settings, trace_acall
from src.gemini import create_model
from src.graph import compile_graph
from src.monitoring import (
    create_monitoring,
    record_execution,
    shutdown_monitoring,
    trace_execution,
)
from src.runtime import resume_graph, run_graph
from src.settings import Settings
from src.state import create_state, state_adapter


def metrics(state):
    values = {
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_calls": state["execution"]["budget"]["tool_calls"]["used"],
        "agent_calls": state["execution"]["budget"]["agent_calls"]["used"],
        "verification_failures": 0,
    }

    def walk(records):
        for item in records:
            output = item["output"] or {}
            if usage := output.get("model_usage"):
                values["model_calls"] += 1
                for key in ("input_tokens", "output_tokens"):
                    values[key] += usage["tokens"].get(key, 0)
            if item["decision"] == "verification" and not output["accepted"]:
                values["verification_failures"] += 1
            walk(output.get("results", []))

    walk(state["results"])
    return values


async def run_scenario(
    name, model, settings, monitoring=None, previous=None, answer=None, *, journal=None
):
    recorder = TraceRecorder.from_settings(settings, journal=journal)
    with recording(recorder):
        case = await _run_scenario(name, model, settings, monitoring, previous, answer)
    case["trace"] = recorder.export()
    return case


async def _run_scenario(
    name, model, settings, monitoring=None, previous=None, answer=None
):
    event = "analysis_pipeline" if name == "S1" else "user_request"
    goal = {"S1": S1, "S2": S2, "S3": S3}[name]
    messages = [SystemMessage("시연용 예시 데이터. " + SCREEN)]
    if previous:
        messages.extend(previous["messages"])
    if event == "user_request":
        messages.append(HumanMessage(goal))
    state = create_state(
        {"goal": goal},
        settings,
        messages=messages,
        version="gemini-scenarios-v1",
        event=event,
    )
    if previous:
        state["response"] = deepcopy(previous["response"])
    graph = compile_graph(
        build_nodes(
            model,
            PROVIDERS,
            CATALOG,
            role=(
                "interpretation"
                if state["execution"]["event"] == "analysis_pipeline"
                else "request"
            ),
        ),
        finish=finish,
        checkpointer=InMemorySaver(),
    )
    started = monotonic()
    with trace_execution(monitoring, state["execution"]) as (config, observation):
        state = await trace_acall(
            "agent",
            "scenario." + name,
            {
                "initial_state": state,
                "settings": safe_settings(settings),
                "catalog": CATALOG,
                "previous_run_id": previous["execution"]["run_id"]
                if previous
                else None,
            },
            lambda: run_graph(graph, state, config),
        )
        record_execution(observation, state)
    if state["execution"]["status"] == "waiting_input" and answer:
        with trace_execution(monitoring, state["execution"], phase="resume") as (
            config,
            observation,
        ):
            state = await trace_acall(
                "agent",
                "scenario.resume",
                {"resume": answer, "checkpoint_state": state},
                lambda: resume_graph(
                    graph,
                    state["execution"]["run_id"],
                    state["response"]["id"],
                    answer,
                    config,
                ),
            )
            record_execution(observation, state)
    failure = state["execution"]["error"]
    return {
        "scenario": name,
        "model": settings.model,
        "failure": failure,
        "elapsed_seconds": round(monotonic() - started, 2),
        "metrics": metrics(state),
        "state": state_adapter.validate_python(state),
    }


def save_case(case, destination):
    destination.mkdir(parents=True, exist_ok=True)
    state = case["state"]
    serialized = case | {"state": state_adapter.dump_python(state, mode="json")}
    TraceRecorder().write_json(destination / "report.json", serialized, strict=True)
    reply = state["response"] or {"content": "응답 없음", "artifacts": []}
    (destination / "answer.txt").write_text(reply["content"], encoding="utf-8")
    for index, artifact in enumerate(reply["artifacts"]):
        if artifact["data"].get("mime_type") == "text/html":
            (destination / f"artifact-{index}.html").write_text(
                artifact["data"]["content"], encoding="utf-8"
            )


async def main(args):
    settings = Settings(
        _env_file=args.env_file,
        **({"model": args.model} if args.model else {}),
        llm_timeout=60,
        runtime_timeout=600,
        max_steps=80,
        max_tool_calls=16,
        max_agent_calls=4,
    )
    model = create_model(settings)
    monitoring = create_monitoring(settings)
    summaries, previous = [], None
    try:
        for name in ["S1", "S2", "S3"] if args.suite else [args.scenario]:
            if name == "S3" and previous is None:
                raise ValueError("S3 requires S2 context; use --suite")
            print(f"{name}: started ({settings.model})", flush=True)
            try:
                case = await run_scenario(
                    name,
                    model,
                    settings,
                    monitoring,
                    previous if name == "S3" else None,
                    journal=args.output / name / "trace.jsonl",
                )
                case["evaluation"] = evaluate(name, case["state"], previous)
                save_case(case, args.output / name)
                status = case["state"]["execution"]["status"]
                summaries.append(
                    {k: v for k, v in case.items() if k not in {"state", "trace"}}
                    | {"status": status, "trace_counts": case["trace"]["counts"]}
                )
                if name == "S2":
                    previous = case["state"]
                print(
                    f"{name}: {status}; evaluation={case['evaluation']['passed']}; "
                    f"{case['metrics']}; {case['elapsed_seconds']}s",
                    flush=True,
                )
                if case["failure"]:
                    break
            except Exception as exc:
                # Provider errors can echo request content. Store only type/status.
                summaries.append(
                    {
                        "scenario": name,
                        "model": settings.model,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "http_status": getattr(exc, "status_code", None),
                    }
                )
                print(f"{name}: failed ({type(exc).__name__})", flush=True)
                break
    finally:
        args.output.mkdir(parents=True, exist_ok=True)
        TraceRecorder.from_settings(settings).write_json(
            args.output / "summary.json", summaries, strict=True
        )
        if list(args.output.rglob("report.json")):
            build_report([args.output], args.output / "report.html")
        await shutdown_monitoring(monitoring)
        await model.http_async_client.aclose()
    return (
        0
        if summaries
        and all(
            s["status"] == "completed" and s.get("evaluation", {}).get("passed", False)
            for s in summaries
        )
        else 1
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", action="store_true")
    parser.add_argument("--model", help="OpenAI 모델 ID. 생략하면 Settings의 모델 사용")
    parser.add_argument("--scenario", choices=["S1", "S2"], default="S1")
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env"
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/gemini-scenarios"))
    raise SystemExit(asyncio.run(main(parser.parse_args())))
