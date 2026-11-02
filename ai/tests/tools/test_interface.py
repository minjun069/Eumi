import json
from copy import deepcopy

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from src.exceptions import ToolFailure
from src.state import result_item_adapter
from src.tools.interface import create_tools
from tool_demo import run_demo


def test_native_tool_call_message_schemas_and_state_record(dataset):
    tools = create_tools({"activity": lambda: dataset})
    assert [tool.name for tool in tools] == [
        "query_data",
        "process_data",
        "render_visualization",
        "validate_visualization",
    ]
    for tool in tools:
        schema = convert_to_openai_tool(tool)
        parameters = schema["function"]["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        assert parameters["required"]
        json.dumps(schema, allow_nan=False)
    call = {
        "id": "call-1",
        "name": "query_data",
        "type": "tool_call",
        "args": {"target": "activity"},
    }
    message = tools[0].invoke(call)
    assert isinstance(message, ToolMessage) and message.tool_call_id == "call-1"
    output = json.loads(message.content)
    record = result_item_adapter.validate_python(
        {
            "id": "result-1",
            "node": "act",
            "decision": "query",
            "reason": "수치 확보",
            "action": {"name": call["name"], "arguments": call["args"]},
            "output": output,
            "description": "합성 자료 조회",
            "outcome": "success",
        }
    )
    assert record["output"]["data"]["inputs"] == [dataset["reference"]]


def test_boundary_validation_is_not_bypassed_by_tool_wrapper(dataset):
    registry = {"activity": lambda: dataset}
    tool = create_tools(registry)[0]
    registry.clear()
    assert tool.invoke({"target": "activity"})["returned"] == 3
    for args in (
        {"target": "activity", "limit": "2"},
        {"target": "activity", "sql": "select 1"},
    ):
        with pytest.raises(ToolFailure):
            tool.invoke(args)


def test_complete_tool_pipeline_and_saved_artifacts(tmp_path):
    report = run_demo(tmp_path)
    saved = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert saved == report
    assert [row["change"] for row in report["process"]["data"]["rows"]] == [
        -10,
        -8,
        -10,
    ]
    for kind, result in report["render"].items():
        content = (tmp_path / f"{kind}.html").read_text(encoding="utf-8")
        assert content == result["artifact"]["data"]["content"]
        assert "-10.0" in content and "-8.0" in content
        assert "fixture://activity/v1" in content
        assert result["data_reference"] == report["process"]["data"]["reference"]


def test_tool_outputs_are_isolated(dataset):
    original = deepcopy(dataset)
    tool = create_tools({"activity": lambda: dataset})[0]
    first = tool.invoke({"target": "activity"})
    first["data"]["rows"][0]["before"] = -99
    second = tool.invoke({"target": "activity"})
    assert second["data"]["rows"][0]["before"] == 120
    assert dataset == original


@pytest.mark.asyncio
async def test_async_native_tool_call(dataset):
    tool = create_tools({"activity": lambda: dataset})[0]
    output = await tool.ainvoke({"target": "activity", "limit": 1})
    assert output["returned"] == 1
    assert output["data"]["rows"][0]["region"] == "A"
