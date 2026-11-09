"""설정의 실제 반영과 State의 검증·격리·직렬화 보존을 확인한다."""

from copy import deepcopy

import pytest
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from src.settings import Settings
from src.state import create_state, state_adapter


def test_state_initialization_and_restore_do_not_share_mutable_values():
    request = {"goal": "설명", "constraints": {"required": ["출처"]}}
    messages = [HumanMessage("질문", id="user")]
    first = create_state(
        request,
        Settings(_env_file=None),
        messages=messages,
        version="test",
        event="user_request",
    )
    other = create_state(
        request,
        Settings(_env_file=None),
        messages=messages,
        version="test",
        event="user_request",
    )
    restored = state_adapter.validate_json(state_adapter.dump_json(first))
    first["request"]["constraints"]["required"].append("변경")
    first["messages"][0].content = "변경"
    first["execution"]["budget"]["steps"]["used"] = 1
    assert other["request"] == restored["request"]
    assert (
        other["request"]["constraints"]["required"]
        == request["constraints"]["required"]
    )
    assert other["messages"][0].content == restored["messages"][0].content == "질문"
    assert restored["messages"][0].id == "user"
    assert other["execution"]["budget"]["steps"]["used"] == 0
    assert other["execution"]["run_id"] != first["execution"]["run_id"]
    for change in (
        {"request": {"goal": " "}},
        {"info": {}},
        {"results": [{"output": object()}]},
    ):
        with pytest.raises(ValidationError):
            state_adapter.validate_python(deepcopy(other) | change)


def test_environment_limits_reach_state_and_invalid_values_are_rejected(monkeypatch):
    monkeypatch.setenv("SETTINGS_MAX_STEPS", "3")
    settings = Settings(_env_file=None)
    state = create_state(
        {"goal": "설명"}, settings, messages=[], version="test", event="user_request"
    )
    assert state["execution"]["budget"]["steps"] == {"used": 0, "limit": 3}
    monkeypatch.setenv("SETTINGS_MAX_STEPS", "invalid")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
