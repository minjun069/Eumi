"""데모가 임시 구성으로 실제 공통 그래프를 실행하는지 확인한다."""

import json
from copy import deepcopy

import pytest
from langchain_core.messages import HumanMessage

import demo
from experiments.fixtures import CASES
from src.graph import compile_graph
from src.state import state_adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,expected", CASES.items())
async def test_demo_runs_shared_graph(monkeypatch, scenario, expected):
    calls = []

    def compile_shared(*args, **kwargs):
        calls.append((args, kwargs))
        return compile_graph(*args, **kwargs)

    monkeypatch.setattr(demo, "compile_graph", compile_shared)
    state = await demo.run_case(scenario, answer="Answer from demo")
    assert len(calls) == 1
    assert state["execution"]["status"] == expected
    assert state["response"]["kind"] == "final"
    assert state["results"][0]["node"] == "interpret"
    answers = [m.content for m in state["messages"] if isinstance(m, HumanMessage)]
    assert answers == (["Answer from demo"] if scenario == "question" else [])


@pytest.mark.asyncio
async def test_demo_event_entry_and_report(tmp_path):
    state = await demo.run_case("question", analysis_event=True)
    assert state["results"][0]["node"] == "act"
    original = deepcopy(state)
    demo.save_report([{"scenario": "question", "state": state}], tmp_path)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report[0]["state"] == state_adapter.dump_python(state, mode="json")
    assert state == original


@pytest.mark.asyncio
async def test_demo_rejects_empty_answer():
    with pytest.raises(ValueError, match="non-empty"):
        await demo.run_case("question", answer=" ")
