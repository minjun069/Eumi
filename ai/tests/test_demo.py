"""대표 데모의 질문 재개와 결과 저장을 확인한다."""

import json

import pytest

from demo.demo import run_case, save_report
from experiments.fixtures import CASES, initial_state
from src.state import state_adapter


@pytest.mark.asyncio
async def test_demo_resumes_and_saves(tmp_path):
    scenario = "question"
    state = await run_case(scenario, initial_state(), answer="추가 정보")
    assert state["execution"]["status"] == "completed"
    save_report([{"scenario": scenario, "state": state}], tmp_path)
    saved = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert saved[0]["state"] == state_adapter.dump_python(state, mode="json")
    assert (tmp_path / "report.html").is_file()


@pytest.mark.parametrize("event", ["user_request", "analysis_pipeline"])
@pytest.mark.parametrize("scenario", CASES)
@pytest.mark.asyncio
async def test_demo_scenarios_decide_before_each_work_and_after_reinterpretation(
    event, scenario
):
    state = await run_case(scenario, initial_state(event), answer="추가 정보")
    assert state["execution"]["status"] == CASES[scenario]
    records = state["results"]
    assert records[0]["node"] == ("interpret" if event == "user_request" else "decide")
    for index, item in enumerate(records):
        if item["node"] == "interpret":
            assert records[index + 1]["node"] == "decide"
        if item["decision"] == "임시 작업 선택":
            assert records[index - 1]["node"] == "decide"
