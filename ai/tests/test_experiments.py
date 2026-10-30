from html.parser import HTMLParser

import pytest

from demo import CASES, run_case, save_report


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario, expected", CASES.items())
async def test_experiment_scenarios(scenario, expected, tmp_path):
    state = await run_case(scenario)
    assert state["execution"]["status"] == expected
    if expected == "completed":
        assert len(state["results"]) == 2
        analysis, table = state["results"]
        assert analysis["data"] == {
            "region": "A",
            "before": 120,
            "after": 108,
            "change": -10,
        }
        assert table["data"]["rows"] == [["A", 120, 108, -10]]
        assert "고립 위험" in state["response"]["content"]
    if scenario == "rework":
        assert state["execution"]["attempts"]["steps"] == 11
    if scenario == "failure":
        assert state["execution"]["error"]["code"] == "retries_limit"
        assert state["execution"]["attempts"]["tool_calls"] == 3
    if scenario == "empty":
        assert state["execution"]["error"] is None
        assert state["results"] == []
    if scenario == "limit":
        assert len(state["results"]) == 1
        assert state["results"][0]["type"] == "analysis_interpretation"


@pytest.mark.asyncio
async def test_answer_changes_both_specialists():
    state = await run_case("ask", answer="B")
    assert state["results"][0]["data"]["change"] == -8.0
    assert state["results"][1]["data"]["rows"] == [["B", 100, 92, -8.0]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent, kind",
    [("analysis", "analysis_interpretation"), ("visualization", "visualization")],
)
async def test_specialist_can_run_as_root(agent, kind):
    state = await run_case("normal", agent=agent)
    assert state["execution"]["status"] == "completed"
    assert [item["type"] for item in state["results"]] == [kind]


class Cells(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cell = False
        self.values = []

    def handle_starttag(self, tag, attrs):
        self.in_cell = tag == "td"

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_cell = False

    def handle_data(self, data):
        if self.in_cell:
            self.values.append(data)


@pytest.mark.asyncio
async def test_generated_html_has_verified_values(tmp_path):
    state = await run_case("normal")
    save_report([{"scenario": "normal", "state": state}], tmp_path)
    parser = Cells()
    parser.feed((tmp_path / "normal-1.html").read_text(encoding="utf-8"))
    assert parser.values == ["A", "120.0", "108.0", "-10.0"]
    assert (tmp_path / "report.json").is_file()
