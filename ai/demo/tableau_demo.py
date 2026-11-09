"""실제 모델·업무 노드·Tableau 검증 도구로 자연어 시각화 요청을 실행한다."""

import argparse
import asyncio
import json
from pathlib import Path

from langchain_core.messages import HumanMessage

from src.agent_nodes import build_nodes, finish
from src.gemini import create_model
from src.graph import compile_graph
from src.runtime import run_graph
from src.settings import Settings
from src.state import create_state, state_adapter


async def run_visualization(goal, model, settings):
    state = create_state(
        {"goal": goal},
        settings,
        messages=[HumanMessage(goal)],
        version="tableau-public-v1",
        event="user_request",
    )
    graph = compile_graph(
        build_nodes(model, {}, [], role="request"),
        finish=finish,
    )
    return await run_graph(graph, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--model", help="OpenAI 모델 ID. 생략하면 Settings의 모델 사용")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = Settings(
        runtime_timeout=args.timeout,
        **({"model": args.model} if args.model else {}),
    )

    async def execute():
        model = create_model(settings)
        try:
            return await run_visualization(args.goal, model, settings)
        finally:
            await model.http_async_client.aclose()

    state = asyncio.run(execute())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(state_adapter.dump_json(state, indent=2))
    print(
        json.dumps(
            {"response": state["response"], "execution": state["execution"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
