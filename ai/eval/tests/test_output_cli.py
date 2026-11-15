"""실제 실행 증거를 새 명령으로 채점하고 실행·평가 모델의 경계를 확인한다."""

from pathlib import Path

import pytest

from eval.__main__ import main
from eval.assessment_store import load_assessment
from eval.tests.test_execution_scoring import executed  # noqa: F401


def test_cli_scores_saved_agent_without_business_or_judge_model(
    executed,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    def forbidden(*args, **kwargs):
        raise AssertionError("규칙 채점은 업무 모델과 평가 모델을 호출하지 않는다")

    monkeypatch.setattr("src.gemini.create_model", forbidden)
    monkeypatch.setattr("eval.runner.run_suite", forbidden)
    before = {path: path.read_bytes() for path in executed.rglob("*.json")}
    target = tmp_path / "output-quality"
    options = [
        "--case",
        "ready-answer",
        "--check",
        "N-F.1",
        "--row",
        "N-F.1/compose-general",
    ]
    assert (
        main(
            [
                "score-outputs",
                str(executed),
                "--output",
                str(target),
                *options,
            ]
        )
        == 0
    )
    value = load_assessment(target)
    assert value["schema_version"] == "output-evaluation-v1"
    assert value["method"] == "rules" and value["judge_model"] is None
    assert len(value["runs"]) == len(value["assessments"]) == 2
    assert all(item["verdict"] == "통과" for item in value["assessments"])
    assert all(
        [check["check"] for check in item["checks"]] == ["N-F.1"]
        for item in value["assessments"]
    )
    assert all(path.read_bytes() == raw for path, raw in before.items())
    reused = tmp_path / "output-quality-reused"
    assert (
        main(
            [
                "score-outputs",
                str(executed),
                "--output",
                str(reused),
                "--reuse",
                str(target),
                *options,
            ]
        )
        == 0
    )
    assert load_assessment(reused)["assessments"] == value["assessments"]


@pytest.mark.parametrize(
    "options", [["--method", "all"], ["--judge-model", "unexpected"]]
)
def test_cli_requires_explicit_evaluation_model_only_for_all(monkeypatch, options):
    def forbidden(*args, **kwargs):
        raise AssertionError("잘못된 인자는 모델 연결 전에 거부해야 한다")

    monkeypatch.setattr("src.gemini.create_model", forbidden)
    assert main(["score-outputs", "unused", *options]) == 2


def test_cli_uses_separate_judge_configuration(monkeypatch, tmp_path):
    calls = []
    judge = object()

    def create(settings):
        calls.append(settings.model)
        return judge

    async def score(folder, output, **kwargs):
        assert folder == Path("saved-batch")
        assert kwargs["model"] is judge
        assert kwargs["judge_model"] == "quality-judge"
        assert kwargs["method"] == "all"
        assert kwargs["reuse"] == Path("previous-quality")
        return output

    monkeypatch.setattr("src.gemini.create_model", create)
    monkeypatch.setattr("eval.output_scoring.score_outputs", score)
    assert (
        main(
            [
                "score-outputs",
                "saved-batch",
                "--method",
                "all",
                "--judge-model",
                "quality-judge",
                "--reuse",
                "previous-quality",
                "--env-file",
                str(tmp_path / "no-env"),
                "--output",
                str(tmp_path / "quality"),
            ]
        )
        == 0
    )
    assert calls == ["quality-judge"]
