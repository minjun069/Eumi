"""completed 응답만으로 시나리오 실행을 합격시키지 않는다."""

import pytest

from experiments.scenario_checks import evaluate
from src.settings import Settings
from src.state import create_state


@pytest.mark.parametrize("name", ["S1", "S2", "S3"])
def test_completion_text_without_execution_evidence_fails(name):
    state = create_state(
        {"goal": "시연"},
        Settings(_env_file=None),
        messages=[],
        version="test",
        event="user_request",
    )
    state["execution"]["status"] = "completed"
    state["response"] = {
        "id": "answer",
        "kind": "final",
        "label": "final",
        "content": '계산과 차트 생성 완료. {"type":"bar","data":[14.4,12.5]}',
        "artifacts": [],
    }
    evaluation = evaluate(name, state)
    assert evaluation["checks"]["completed"] is True
    assert evaluation["passed"] is False


def test_s3_requires_an_existing_real_chart():
    state = create_state(
        {"goal": "차트 설명"},
        Settings(_env_file=None),
        messages=[],
        version="test",
        event="user_request",
    )
    state["execution"]["status"] = "completed"
    chart = {"type": "chart", "data": {"mime_type": "text/html", "content": "<svg/>"}}
    state["response"] = {
        "id": "r",
        "kind": "final",
        "label": "final",
        "content": "설명",
        "artifacts": [chart],
    }
    prior = {"response": {"artifacts": [chart]}}
    assert evaluate("S3", state, prior)["checks"]["selected_chart_preserved"]
    # 선택 차트를 없애면 새 응답에 차트가 있어도 유지했다고 판정하지 않는다.
    assert not evaluate("S3", state)["checks"]["selected_chart_preserved"]
