"""합성 자료 조회와 변화율 계산. 표의 산출물 저장 연결은 삭제했다."""

from langchain_core.tools import tool
from pydantic import JsonValue

from src.exceptions import ToolFailure
from src.state import Reference

DATA = {"A": (120.0, 108.0), "B": (100.0, 92.0), "C": (80.0, 72.0)}
SOURCE: Reference = {
    "label": "시연용 활동지수",
    "uri": "fixture://activity/synthetic-v1",
}


@tool
def lookup_metrics(region: str) -> dict[str, JsonValue]:
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

