"""실제 도구 인터페이스로 조회 → 가공 → 네 가지 렌더링을 실행한다."""

import argparse
import json
from pathlib import Path

from experiments.tool_fixtures import activity, boundaries
from src.tools.interface import create_tools


def run_demo(output: Path) -> dict:
    tools = {tool.name: tool for tool in create_tools({"synthetic_activity": activity})}
    queried = tools["query_data"].invoke({"target": "synthetic_activity"})
    processed = tools["process_data"].invoke(
        {
            "data": queried["data"],
            "operations": [
                {
                    "operation": "calculate",
                    "method": "percent_change",
                    "before": "before",
                    "after": "after",
                    "output": "change",
                }
            ],
            "decimals": 1,
        }
    )
    data = processed["data"]
    rendered = {}
    for kind in ("table", "bar", "line", "map"):
        spec = {"type": kind, "title": "합성 자료: 가상 지역별 활동지수 변화율"}
        if kind in {"bar", "line"}:
            spec.update(x="region", y="change", unit="%")
        elif kind == "map":
            spec.update(
                region="region",
                value="change",
                unit="%",
                code_system="synthetic_code",
                boundaries=boundaries(),
            )
        rendered[kind] = tools["render_visualization"].invoke(
            {"data": data, "spec": spec}
        )
    output.mkdir(parents=True, exist_ok=True)
    for kind, result in rendered.items():
        (output / f"{kind}.html").write_text(
            result["artifact"]["data"]["content"], encoding="utf-8"
        )
    report = {"query": queried, "process": processed, "render": rendered}
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/tool-demo"))
    args = parser.parse_args()
    report = run_demo(args.output)
    print(f"Created {len(report['render'])} artifacts in {args.output.resolve()}")
