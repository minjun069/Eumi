"""Deterministic synthetic data, arithmetic, and an actual HTML table."""

import json
from html import escape

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from src.exceptions import ToolFailure
from src.state import (
    Artifact,
    artifact_adapter,
    current_call,
    merge_results,
    update_call,
)

DATA = {"A": (120.0, 108.0), "B": (100.0, 92.0), "C": (80.0, 72.0)}
SOURCE = {"label": "시연용 활동지수", "uri": "fixture://activity/synthetic-v1"}


@tool
def lookup_metrics(region: str) -> dict:
    """Read synthetic August/September activity indices for region A, B, or C."""
    if region == "FAIL":
        raise ToolFailure("read_unavailable", retryable=True)
    if region not in DATA:
        return {"rows": [], "source": SOURCE}
    before, after = DATA[region]
    return {
        "region": region,
        "before": before,
        "after": after,
        "source": SOURCE,
        "period": "2026-08/2026-09",
        "unit": "index",
        "synthetic": True,
    }


lookup_metrics.metadata = {"retry_safe": True}


@tool
def calculate_change(before: float, after: float) -> float:
    """Calculate percentage change as (after - before) / before * 100."""
    if before == 0:
        raise ToolFailure("zero_denominator")
    return round((after - before) / before * 100, 1)


@tool
def render_table(
    region: str,
    before: float,
    after: float,
    change: float,
    runtime: ToolRuntime,
) -> Command:
    """Render an HTML table; register the exact artifact for result verification."""
    columns = ["지역", "2026-08 활동지수", "2026-09 활동지수", "변화율(%)"]
    rows = [[region, before, after, change]]
    html = '<!doctype html><html lang="ko"><meta charset="utf-8">'
    html += "<title>활동지수 비교</title>"
    html += (
        "<h1>활동지수 비교</h1><p>시연용 예시 데이터 · 고립 위험 점수가 아닙니다.</p>"
    )
    html += '<table border="1"><thead><tr>'
    html += "".join(f"<th>{escape(c)}</th>" for c in columns) + "</tr></thead><tbody>"
    html += "<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in rows[0]) + "</tr>"
    html += "</tbody></table><p>출처: fixture://activity/synthetic-v1</p></html>"
    artifact = artifact_adapter.validate_python(
        Artifact(
            type="visualization",
            data={"format": "html", "html": html, "columns": columns, "rows": rows},
            sources=[SOURCE],
            issues=["시연용 예시 데이터"],
        )
    )
    return Command(
        update=update_call(
            runtime.state,
            results=merge_results(current_call(runtime.state)["results"], [artifact]),
        )
        | {
            "messages": [
                ToolMessage(
                    json.dumps({"rendered": True, "rows": rows}, ensure_ascii=False),
                    artifact=artifact,
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )
