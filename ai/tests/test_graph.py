import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.exceptions import ToolFailure
from src.graph import Agent, compile_graph
from src.settings import Settings
from src.state import create_state
from tests.helpers import ScriptedModel, accept, finish


def graph(model, *, tools=(), validate=accept, children=None, name="test"):
    return Agent(
        name=name,
        model=model,
        prompt="Temporary test agent.",
        tools=tools,
        validate=validate,
        children=children or {},
    )


def initial(**settings):
    return create_state({"goal": "Explain"}, Settings(_env_file=None, **settings))


@pytest.mark.asyncio
async def test_native_tool_validation_and_result_verification():
    calls = []

    @tool
    def lookup(region: str) -> dict:
        """Return a synthetic observation."""
        calls.append(region)
        return {"value": 12}

    async def validate(state, result):
        assert any(
            isinstance(m, ToolMessage) and "12" in m.content
            for m in state["execution"]["model_messages"]
        )
        return [] if result["content"] == "12" else ["Use observed value 12"]

    model = ScriptedModel(
        ("lookup", {}), ("lookup", {"region": "A"}), finish("wrong"), finish("12")
    )
    result = await compile_graph(
        graph(model, tools=[lookup], validate=validate)
    ).ainvoke(initial())
    assert calls == ["A"]
    assert result["response"]["content"] == "12"
    assert model.invocations == 4


@pytest.mark.asyncio
async def test_disallowed_tool_is_not_executed():
    result = await compile_graph(
        graph(ScriptedModel(("unknown", {}), finish()))
    ).ainvoke(initial())
    assert any(
        isinstance(m, ToolMessage) and m.status == "error"
        for m in result["execution"]["model_messages"]
    )


@pytest.mark.asyncio
async def test_verification_failure_is_bounded():
    async def reject(state, result):
        return ["Missing evidence"]

    result = await compile_graph(
        graph(ScriptedModel(finish()), validate=reject)
    ).ainvoke(initial(max_steps=2))
    assert result["execution"]["error"]["code"] == "steps_limit"


@pytest.mark.asyncio
async def test_child_interrupt_resumes_without_repeating_lookup_or_parent_model():
    calls = []

    @tool
    def lookup() -> int:
        """Read a synthetic value."""
        calls.append(1)
        return 12

    child_model = ScriptedModel(
        ("lookup", {}), ("ask_user", {"question": "Which region?"}), finish("12")
    )
    child = graph(child_model, tools=[lookup], name="analysis")
    parent_model = ScriptedModel(("analysis", {"goal": "Explain"}), finish())
    parent = compile_graph(
        graph(parent_model, children={"analysis": child}), checkpointer=InMemorySaver()
    )
    state = initial()
    config = {"configurable": {"thread_id": state["execution"]["run_id"]}}
    paused = await parent.ainvoke(state, config)
    assert paused["__interrupt__"][0].value["question"] == "Which region?"
    saved = parent.get_state(config, subgraphs=True)
    assert (
        sum(
            isinstance(m, HumanMessage)
            for m in saved.values["execution"]["model_messages"]
        )
        == 2
    )
    history = saved.values["execution"]["model_messages"]
    scope = history[-1].additional_kwargs["scope"]
    messages = [m for m in history if m.additional_kwargs["scope"] == scope]
    assert messages
    assert messages[0].additional_kwargs["agent_path"] == ["analysis"]
    result = await parent.ainvoke(Command(resume="A"), config)
    assert result["response"]["content"] == "Done"
    assert calls == [1]
    assert child_model.invocations == 3
    assert parent_model.invocations == 2
    assert result["execution"]["budget"]["agent_calls"]["used"] == 1
    assert result["execution"]["budget"]["tool_calls"]["used"] == 1


@pytest.mark.asyncio
async def test_child_failure_keeps_verified_grandchild_output():
    artifact = {
        "type": "analysis_interpretation",
        "data": {"region": "A", "before": 100, "after": 112, "change": 12},
    }
    leaf = graph(ScriptedModel(finish(results=[artifact])), name="leaf")

    async def fail(state, result):
        raise RuntimeError("private error")

    middle = graph(
        ScriptedModel(("leaf", {"goal": "Read"}), finish()),
        children={"leaf": leaf},
        validate=fail,
    )
    parent = graph(
        ScriptedModel(("middle", {"goal": "Read"}), finish(partial=True)),
        children={"middle": middle},
    )
    result = await compile_graph(parent).ainvoke(initial())
    assert result["execution"]["status"] == "partial"
    assert result["results"][0]["data"] == artifact["data"]
    assert "private error" not in json.dumps(
        [str(m) for m in result["execution"]["model_messages"]]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("safe, expected", [(True, 2), (False, 1)])
async def test_retry_requires_safe_read_and_retryable_error(safe, expected):
    calls = []

    @tool
    def lookup() -> int:
        """Read synthetic data."""
        calls.append(1)
        if len(calls) == 1:
            raise ToolFailure("unavailable", retryable=True)
        return 12

    lookup.metadata = {"retry_safe": safe}
    result = await compile_graph(
        graph(ScriptedModel(("lookup", {}), finish()), tools=[lookup])
    ).ainvoke(initial())
    assert len(calls) == expected
    assert result["execution"]["budget"]["retries"]["used"] == expected - 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"content": " "},
        {"results": [{"type": "visualization", "data": {}, "unexpected": True}]},
        {"references": [{"label": "source"}]},
    ],
)
async def test_invalid_submissions_are_rejected_before_business_validation(bad):
    seen = []

    async def validate(state, result):
        seen.append(result)
        return []

    name, args = finish()
    model = ScriptedModel((name, args | bad), finish("Corrected"))
    output = await compile_graph(graph(model, validate=validate)).ainvoke(initial())
    assert output["response"]["content"] == "Corrected"
    assert len(seen) == 1
    assert any(
        isinstance(m, ToolMessage) and m.status == "error"
        for m in output["execution"]["model_messages"]
    )


@pytest.mark.asyncio
async def test_child_schema_and_validation_share_the_typed_request():
    child_model = ScriptedModel(finish())
    parent_model = ScriptedModel(
        ("child", {"goal": "Explain", "constraints": {"unexpected": True}}),
        ("child", {"goal": "Explain"}),
        finish(),
    )
    parent = compile_graph(graph(parent_model, children={"child": graph(child_model)}))
    schema = convert_to_openai_tool(parent_model.tools[0])["function"]["parameters"]
    assert schema["required"] == ["goal"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["constraints"]["additionalProperties"] is False
    assert (
        "runtime"
        not in convert_to_openai_tool(parent_model.tools[-1])["function"]["parameters"][
            "properties"
        ]
    )
    output = await parent.ainvoke(initial())
    assert output["response"]["content"] == "Done"
    assert output["execution"]["budget"]["agent_calls"]["used"] == 1
    assert child_model.invocations == 1
