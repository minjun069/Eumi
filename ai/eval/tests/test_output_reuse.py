"""다른 근거·기준의 품질 판정을 재사용하지 않는지 확인한다."""

import json

import pytest

from eval.assessment_store import load_assessment, write_assessment
from eval.output_reuse import find_reused, load_reuse
from eval.tests.assessment_fixtures import report


@pytest.fixture
def saved(tmp_path):
    value = report()
    value.update(
        schema_version="output-evaluation-v1",
        status="completed",
        evaluator_sha256={"nodes/assessment.py": "code"},
    )
    value.pop("nodes")
    value["summary"] = {"verdict": "통과", "complete": True}
    for item in value["assessments"]:
        item.update(
            id=item["node_id"] + ":same-call-id",
            call_id="same-call-id",
            call_index=1,
            complete=True,
            verdict="통과",
        )
    path = tmp_path / "quality"
    write_assessment(path, value, source_batch=tmp_path)
    conditions = {
        name: value[name]
        for name in (
            "batch_id",
            "method",
            "judge_model",
            "criteria_sha256",
            "evidence_sha256",
            "evaluator_sha256",
        )
    }
    return path, value, conditions


def test_quality_json_preserves_identity_and_original_judge_prompt(saved):
    path, value, conditions = saved
    assert load_assessment(path) == value
    before = path.read_bytes()
    pool = load_reuse(path, **conditions)
    assert pool["compatible"] and not pool["reasons"]
    result = find_reused(pool, "case-a", 1, "node-1", "same-call-id")
    assert result == value["assessments"][0]
    result["checks"].clear()
    assert find_reused(pool, "case-a", 1, "node-1", "same-call-id")["checks"]
    assert before == path.read_bytes()


@pytest.mark.parametrize(
    "condition",
    [
        "batch_id",
        "method",
        "judge_model",
        "criteria_sha256",
        "evidence_sha256",
        "evaluator_sha256",
    ],
)
def test_changed_execution_or_evaluator_conditions_require_fresh_judgment(
    saved, condition
):
    path, _, conditions = saved
    conditions[condition] = (
        {"changed": "digest"}
        if isinstance(conditions[condition], dict)
        else "different"
    )
    pool = load_reuse(path, **conditions)
    assert not pool["compatible"]
    assert any(condition in reason for reason in pool["reasons"])
    assert find_reused(pool, "case-a", 1, "node-1", "same-call-id") is None


def test_incomplete_and_other_calls_are_never_reused(saved):
    path, _, conditions = saved
    pool = load_reuse(path, **conditions)
    assert find_reused(pool, "case-a", 1, "node-1", "other-call") is None
    assert find_reused(pool, "case-a", 2, "node-1", "same-call-id") is None
    item = pool["assessments"][0]
    item.update(complete=False, verdict="실패")
    assert find_reused(pool, "case-a", 1, "node-1", "same-call-id") is None
    item.update(complete=True, verdict="미판정")
    assert find_reused(pool, "case-a", 1, "node-1", "same-call-id") is None
    item.update(verdict="실패")
    assert find_reused(pool, "case-a", 1, "node-1", "same-call-id")["verdict"] == "실패"


def test_cancelled_or_non_quality_reports_cannot_supply_reusable_verdicts(
    saved, tmp_path
):
    _, value, conditions = saved
    path = tmp_path / "old.json"
    value["status"] = "cancelled"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert not load_reuse(path, **conditions)["compatible"]
    value["schema_version"] = "node-evaluation-v1"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="--reuse"):
        load_reuse(path, **conditions)


def test_unidentified_judge_cannot_be_treated_as_the_same_model(saved, tmp_path):
    _, value, conditions = saved
    value.update(method="all", judge_model=None)
    conditions.update(method="all", judge_model=None)
    path = tmp_path / "anonymous.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    pool = load_reuse(path, **conditions)
    assert not pool["compatible"]
    assert any("모델 식별자" in reason for reason in pool["reasons"])
    assert find_reused(pool, "case-a", 1, "node-1", "same-call-id") is None


@pytest.mark.parametrize(
    ("field", "invalid"),
    [("call_id", []), ("node_id", ""), ("repetition", True), ("repetition", 0)],
)
def test_invalid_reuse_identity_is_rejected(saved, tmp_path, field, invalid):
    _, value, conditions = saved
    value["assessments"][0][field] = invalid
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="식별자"):
        load_reuse(path, **conditions)
