import pytest
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from src.settings import Settings
from src.state import create_state, request_adapter, result_adapter, state_adapter


def test_defaults_are_preserved_without_sharing_mutable_values():
    request = request_adapter.validate_python({"goal": "Explain"})
    other = request_adapter.validate_python({"goal": "Explain"})
    request["constraints"]["required"].append("source")
    assert other == {
        "goal": "Explain",
        "subject": {},
        "constraints": {"required": [], "preferred": [], "excluded": []},
    }
    result = result_adapter.validate_python(
        {
            "content": "Done",
            "results": [{"type": "visualization", "data": {"rows": [[1]]}}],
        }
    )
    assert result["results"][0]["sources"] == []
    assert result["results"][0]["issues"] == []
    assert result["references"] == []
    assert result["partial"] is False
    result["content"] = " "
    with pytest.raises(ValidationError):
        result_adapter.validate_python(result)


def test_state_validates_nested_data_and_preserves_message_objects():
    state = create_state(
        {"goal": "Explain", "subject": {"years": [2025, 2026]}},
        Settings(_env_file=None),
        info={"values": [1, 2]},
    )
    state["messages"] = [HumanMessage("Explain", id="user-1")]
    checked = state_adapter.validate_python(state)
    assert isinstance(checked["messages"][0], HumanMessage)
    assert checked["messages"][0].id == "user-1"
    state["request"]["subject"]["years"].append(2027)
    assert checked["request"]["subject"]["years"] == [2025, 2026]
    with pytest.raises(ValidationError):
        state_adapter.validate_python(state | {"info": {"value": object()}})
    with pytest.raises(ValidationError):
        state_adapter.validate_python(state | {"request": {"goal": " "}})
