"""Use real LangGraph/Langfuse callbacks; replace only the network exporter."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from demo import demo
from experiments.fixtures import initial_state, mock_nodes
from src import monitoring
from src.graph import compile_graph
from src.settings import Settings


@pytest.fixture(scope="module")
def sdk():
    exporter = InMemorySpanExporter()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("LANGFUSE_MEDIA_UPLOAD_ENABLED", "false")
        client = Langfuse(
            public_key="pk-lf-offline-test",
            secret_key="sk-lf-offline-test",
            base_url="http://127.0.0.1:1",
            tracer_provider=TracerProvider(),
            span_exporter=exporter,
            mask_otel_spans=monitoring.mask_spans,
        )
        yield client, exporter
        client.shutdown()


def spans_for(sdk, run_id):
    client, exporter = sdk
    client.flush()
    trace_id = int(Langfuse.create_trace_id(seed=run_id), 16)
    return [s for s in exporter.get_finished_spans() if s.context.trace_id == trace_id]


def metadata(span, key):
    value = span.attributes.get(f"langfuse.observation.metadata.{key}")
    return json.loads(value) if value is not None else None


def test_disabled_never_constructs_sdk(monkeypatch):
    constructor = Mock()
    monkeypatch.setattr(monitoring, "Langfuse", constructor)
    assert monitoring.create_monitoring(Settings(_env_file=None)) is None
    execution = initial_state()["execution"]
    with monitoring.trace_execution(None, execution) as (config, span):
        assert config == {"configurable": {"thread_id": execution["run_id"]}}
        assert span is None
    constructor.assert_not_called()


def test_monitoring_requires_credentials_when_enabled():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, LANGFUSE_ENABLED=True)


def test_environment_and_client_configuration(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-do-not-log")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "test")
    monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "0.25")
    settings = Settings(_env_file=None)
    assert "sk-lf-do-not-log" not in repr(settings)
    constructor = Mock()
    monkeypatch.setattr(monitoring, "Langfuse", constructor)
    assert monitoring.create_monitoring(settings) is constructor.return_value
    args = constructor.call_args.kwargs
    assert args["base_url"] == "http://localhost:3000/"
    assert args["sample_rate"] == 0.25
    assert args["environment"] == "test"
    assert args["mask_otel_spans"] is monitoring.mask_spans
    for name, expected in (("langfuse", True), ("openai", False)):
        span = SimpleNamespace(instrumentation_scope=SimpleNamespace(name=name))
        assert args["should_export_span"](span) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,expected,level",
    [
        ("partial", "partial", "WARNING"),
        ("question", "completed", "DEFAULT"),
    ],
)
async def test_real_graph_status_and_resume(sdk, scenario, expected, level):
    state = await demo.run_case(scenario, initial_state(), monitoring=sdk[0])
    spans = spans_for(sdk, state["execution"]["run_id"])
    roots = [s for s in spans if s.name.startswith("eumi.agent.")]
    assert len(roots) == (2 if scenario == "question" else 1)
    final = next(s for s in roots if metadata(s, "status") == expected)
    assert final.attributes["langfuse.observation.level"] == level
    assert metadata(final, "result_count") == len(state["results"])
    assert metadata(final, "version") == "graph-fixture"
    assert metadata(final, "failure_count") == (1 if scenario == "failure" else 0)
    assert metadata(final, "error_code") == (
        "temporary_failure" if scenario == "failure" else None
    )
    assert all(
        s.attributes["session.id"] == state["execution"]["run_id"] for s in roots
    )
    graphs = [s for s in spans if s.name == "eumi.graph"]
    assert {s.parent.span_id for s in graphs} == {s.context.span_id for s in roots}
    assert {s.attributes.get("session.id") for s in graphs} == {
        state["execution"]["run_id"]
    }
    assert {"act", "decide", "compose"} <= {s.name for s in spans}
    if scenario == "question":
        waiting = next(s for s in roots if metadata(s, "status") == "waiting_input")
        assert waiting.end_time <= final.start_time
        assert all(
            s.attributes.get("langfuse.observation.level") != "ERROR" for s in spans
        )
    serialized = " ".join(s.to_json() for s in spans)
    assert "실행 흐름 검증용 임시 출력" not in serialized
    assert "추가 정보" not in serialized
    assert all("langfuse.observation.input" not in s.attributes for s in spans)
    assert all("langfuse.observation.output" not in s.attributes for s in spans)


@pytest.mark.asyncio
async def test_model_usage_tools_and_payload_masking(sdk):
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="PRIVATE_MODEL_ANSWER",
                usage_metadata={
                    "input_tokens": 12,
                    "output_tokens": 4,
                    "total_tokens": 16,
                },
                response_metadata={"model_name": "offline-test-model"},
            )
        ]
    )

    @tool
    def lookup(query: str) -> str:
        """Return a synthetic lookup result."""
        return "PRIVATE_TOOL_RESULT"

    nodes, finish = mock_nodes()
    original_act = nodes["act"]

    async def act(state, config):
        await model.ainvoke("PRIVATE_PROMPT", config)
        await lookup.ainvoke({"query": "PRIVATE_QUERY"}, config)
        return original_act(state)

    nodes["act"] = act
    graph = compile_graph(nodes, finish=finish)
    state = initial_state()
    original = deepcopy(state)
    with monitoring.trace_execution(sdk[0], state["execution"]) as (config, span):
        result = await graph.ainvoke(state, config)
        monitoring.record_execution(span, result)
    assert state == original
    spans = spans_for(sdk, state["execution"]["run_id"])
    generation = next(
        s
        for s in spans
        if s.attributes.get("langfuse.observation.type") == "generation"
    )
    usage = json.loads(generation.attributes["langfuse.observation.usage_details"])
    assert usage["input"] == 12
    assert usage["output"] == 4
    assert any(s.name == "lookup" for s in spans)
    assert "PRIVATE_" not in " ".join(s.to_json() for s in spans)


@pytest.mark.asyncio
async def test_failure_is_recorded_without_private_message(sdk):
    nodes, finish = mock_nodes()

    def broken(state):
        raise RuntimeError("PRIVATE_EXCEPTION_MESSAGE")

    nodes["act"] = broken
    graph = compile_graph(nodes, finish=finish)
    state = initial_state()
    with monitoring.trace_execution(sdk[0], state["execution"]) as (config, span):
        result = await graph.ainvoke(state, config)
        monitoring.record_execution(span, result)
    assert result["execution"]["status"] == "failed"
    spans = spans_for(sdk, state["execution"]["run_id"])
    root = next(s for s in spans if s.name == "eumi.agent.start")
    assert metadata(root, "status") == "failed"
    assert root.attributes["langfuse.observation.level"] == "ERROR"
    assert "PRIVATE_EXCEPTION_MESSAGE" not in " ".join(s.to_json() for s in spans)


@pytest.mark.asyncio
async def test_concurrent_runs_are_isolated(sdk):
    states = await asyncio.gather(
        *[
            demo.run_case(case, initial_state(), monitoring=sdk[0])
            for case in ("question", "failure")
        ]
    )
    assert states[0]["execution"]["run_id"] != states[1]["execution"]["run_id"]
    for state in states:
        spans = spans_for(sdk, state["execution"]["run_id"])
        roots = [s for s in spans if s.name.startswith("eumi.agent.")]
        assert {metadata(s, "run_id") for s in roots} == {state["execution"]["run_id"]}
        assert state["execution"]["status"] in {metadata(s, "status") for s in roots}


def test_cancellation_is_not_swallowed(sdk):
    state = initial_state()
    with pytest.raises(asyncio.CancelledError):
        with monitoring.trace_execution(sdk[0], state["execution"]):
            raise asyncio.CancelledError()
    root = next(
        s
        for s in spans_for(sdk, state["execution"]["run_id"])
        if s.name == "eumi.agent.start"
    )
    assert metadata(root, "status") == "cancelled"


@pytest.mark.asyncio
async def test_monitoring_failure_does_not_repeat_or_fail_graph(caplog):
    client = Mock()
    client.start_observation.side_effect = OSError("PRIVATE_CONNECTION_DETAILS")
    state = await demo.run_case("complete", initial_state(), monitoring=client)
    assert state["execution"]["status"] == "completed"
    assert sum(r["action"] is not None for r in state["results"]) == 1
    assert "PRIVATE_CONNECTION_DETAILS" not in caplog.text
    client.shutdown.side_effect = OSError("PRIVATE_CONNECTION_DETAILS")
    await monitoring.shutdown_monitoring(client)
    client.shutdown.assert_called_once()
    assert "PRIVATE_CONNECTION_DETAILS" not in caplog.text
