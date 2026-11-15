"""에이전트별 저장·채점에서 실제 호출 순서와 운영 측정 범위를 확인한다."""

from copy import deepcopy

from eval.assessment_store import load_assessment
from eval.execution.scoring import score_executions
from eval.runner import run_suite
from eval.tests.batch_fixtures import read_document
from eval.tests.test_execution_scoring import example_suite
from src.settings import Settings
from tests.helpers import ScriptedModel


async def test_agent_runs_and_assessments_are_isolated_without_reordering(tmp_path):
    suite = example_suite()
    request = suite["cases"][0]
    other = deepcopy(request)
    other.update(id="interpretation", target="interpretation")
    other.pop("assessment")
    last = deepcopy(request)
    last["id"] = "last-request"
    suite["cases"].extend([other, last])
    original = deepcopy(suite)
    replies = [
        {"request": request["initial"]["request"], "reason": "요청 확인"},
        {"next": "compose", "reason": "준비된 문맥"},
        {
            "content": "준비된 문맥 설명",
            "artifact_ids": [],
            "status": "completed",
            "reason": "설명",
        },
    ]
    model = ScriptedModel(replies * 6)
    folders = await run_suite(
        suite, Settings(_env_file=None), tmp_path, model=model, repeat=2
    )
    assert [folder.parent.name for folder in folders] == ["request", "interpretation"]
    assert suite == original
    assert model.schemas == ["Interpretation", "Decision", "Composition"] * 6
    all_ids = []
    for folder, expected in zip(
        folders, [[request["id"], last["id"]], [other["id"]]], strict=True
    ):
        batch = read_document(folder / "batch.json")
        assert batch["plan"] == {"case_ids": expected, "repeat": 2}
        assert batch["planned_runs"] == len(batch["runs"]) == len(expected) * 2
        assert {run["target"] for run in batch["runs"]} == {folder.parent.name}
        all_ids.extend(run["run_id"] for run in batch["runs"])
        score = load_assessment(score_executions(folder))
        assert {run["target"] for run in score["summary"]["operational"]["runs"]} == {
            folder.parent.name
        }
        assert score["selection"]["selected_case_ids"] == expected
        if folder.parent.name == "interpretation":
            assert score["runs"] == []
    assert len(set(all_ids)) == len(all_ids) == 6
