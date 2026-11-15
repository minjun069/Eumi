"""노드별 저장으로 실행 순서·입력·취소 증거가 달라지지 않는지 검증한다."""

import asyncio
import json
from copy import deepcopy

import pytest
from langchain_core.runnables import RunnableLambda

from eval.runner import run_suite
from eval.schema import suite_adapter
from eval.tests.test_evaluation_runner import node_case, read_json, reports, suite
from src.settings import Settings
from tests.helpers import DONE, ScriptedModel


async def test_interleaved_nodes_keep_call_order_and_independent_plans(tmp_path):
    value = suite(
        node_case("decide", id="first"),
        node_case("interpret"),
        node_case("decide", id="last"),
    )
    original = deepcopy(value)
    interpretation = {"request": {"goal": "지역별 활동을 확인한다."}, "reason": "요청"}
    model = ScriptedModel([DONE, DONE, interpretation, interpretation, DONE, DONE])
    folders = await run_suite(
        value, Settings(_env_file=None), tmp_path, model=model, repeat=2
    )
    assert [path.parent.name for path in folders] == ["decide", "interpret"]
    assert model.schemas == ["Decision"] * 2 + ["Interpretation"] * 2 + ["Decision"] * 2
    assert value == original
    ids = set()
    for path, expected in zip(folders, [["first", "last"], ["interpret"]], strict=True):
        batch = read_json(path / "batch.json")
        assert batch["plan"] == {"case_ids": expected, "repeat": 2}
        assert batch["planned_runs"] == len(batch["runs"]) == len(expected) * 2
        assert batch["status"] == "returned"
        expected_suite = json.loads(
            suite_adapter.dump_json(suite_adapter.validate_python(original))
        )
        assert read_json(path / "suite.json") == expected_suite
        assert {run["target"] for run in batch["runs"]} == {path.parent.name}
        for report in reports(path):
            assert report["run"]["case_id"] in expected
            assert report["run"]["id"] not in ids
            ids.add(report["run"]["id"])
            assert report["trace"]["spans"]
    assert len(ids) == 6


async def test_cancellation_preserves_finished_and_unstarted_node_plans(tmp_path):
    entered = asyncio.Event()

    class WaitingModel(ScriptedModel):
        def with_structured_output(self, schema, **kwargs):
            if schema["title"] != "Interpretation":
                return super().with_structured_output(schema, **kwargs)

            async def wait(_messages, config):
                entered.set()
                await asyncio.Future()

            return RunnableLambda(wait)

    task = asyncio.create_task(
        run_suite(
            suite(node_case("decide"), node_case("interpret"), node_case("compose")),
            Settings(_env_file=None),
            tmp_path,
            model=WaitingModel([DONE]),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    batches = {
        path.parent.parent.name: read_json(path)
        for path in tmp_path.rglob("batch.json")
    }
    assert set(batches) == {"decide", "interpret", "compose"}
    assert batches["decide"]["status"] == "returned"
    assert batches["interpret"]["status"] == batches["compose"]["status"] == "cancelled"
    assert batches["interpret"]["runs"][0]["status"] == "cancelled"
    assert batches["compose"]["runs"] == []
    assert all(
        batch["planned_runs"] == 1 and batch["ended_at"] for batch in batches.values()
    )
