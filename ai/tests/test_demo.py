"""대표 데모의 질문 재개와 결과 저장을 확인한다."""

import json

import pytest

from demo.demo import run_case, save_report
from experiments.fixtures import initial_state
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
