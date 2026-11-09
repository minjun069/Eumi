"""Exercise real call boundaries, failure retention and observation isolation."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from demo.scenario_demo import run_scenario
from src.agent_nodes import Decision
from src.execution_trace import TraceRecorder, recording, trace_span
from src.gemini import create_model, structured_call
from src.prompting import decide_messages
from src.settings import Settings
from tests.helpers import DONE, ScriptedModel, composition, initial, selection


def test_snapshots_are_detached_and_nested_secrets_redacted(tmp_path):
    recorder = TraceRecorder(secrets=["secret-value"], journal=tmp_path / "trace.jsonl")
    value = {"rows": [{"n": 1}], "api_key": "anything", "text": "x-secret-value-y"}
    with recording(recorder), trace_span("tool", "test", value) as span:
        value["rows"][0]["n"] = 999
        span.update(output=value)
    saved = recorder.spans[0]
    assert saved["input"]["rows"][0]["n"] == 1
    assert saved["output"]["rows"][0]["n"] == 999
    assert saved["input"]["api_key"] == "[REDACTED]"
    assert saved["input"]["text"] == "x-[REDACTED]-y"


@pytest.mark.asyncio
async def test_failed_model_input_survives_without_state_commit(tmp_path):
    def fail(messages):
        raise ConnectionError("untrusted private error")

    report = await run_scenario(
        "S1",
        ScriptedModel([fail]),
        Settings(_env_file=None),
        journal=tmp_path / "trace.jsonl",
    )
    assert report["metrics"]["model_calls"] == 0
    failed = next(s for s in report["trace"]["spans"] if s["kind"] == "model")
    assert failed["status"] == "error"
    assert failed["input"]["messages"][0]["type"] == "system"
    assert failed["error"]["type"] == "ConnectionError"
    assert "untrusted private error" not in json.dumps(report["trace"])


@pytest.mark.asyncio
async def test_node_and_tool_inputs_link_to_model_without_trace_feedback():
    model = ScriptedModel(
        [selection("query_data", {"target": "D3"}), DONE, composition]
    )
    report = await run_scenario("S1", model, Settings(_env_file=None))
    spans = report["trace"]["spans"]
    by_id = {s["id"]: s for s in spans}
    tool = next(s for s in spans if s["kind"] == "tool")
    assert tool["input"]["resolved_arguments"] == {"target": "D3"}
    assert by_id[tool["parent_id"]]["name"] == "act"
    assert next(s for s in spans if s["kind"] == "provider")["output"]["rows"]
    assert all(s["ended_at"] and s["status"] == "success" for s in spans)
    assert all("http_request" not in m[1].content for m in model.inputs)
    assert report["state"]["execution"]["status"] == "completed"


@pytest.mark.asyncio
async def test_concurrent_recorders_and_cancellation_are_isolated():
    async def task(name):
        recorder = TraceRecorder()
        with recording(recorder), trace_span("agent", name, {}) as span:
            await asyncio.sleep(0)
            with trace_span("model", name, {}):
                await asyncio.sleep(0)
            span.update(output={"done": True})
        return recorder

    a, b = await asyncio.gather(task("a"), task("b"))
    assert {s["name"] for s in a.spans} == {"a"}
    assert {s["name"] for s in b.spans} == {"b"}
    recorder = TraceRecorder()
    with pytest.raises(asyncio.CancelledError), recording(recorder):
        with trace_span("model", "cancel", {}):
            raise asyncio.CancelledError()
    assert recorder.spans[0]["error"]["type"] == "CancelledError"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_response", [False, True])
async def test_real_adapter_http_payload_and_failure_trace(monkeypatch, bad_response):
    requests = []
    content = "invalid JSON" if bad_response else json.dumps(DONE)

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "model": "gpt-6-sol",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_test",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": content, "annotations": []}
                        ],
                    }
                ],
            },
        )

    original = httpx.AsyncClient

    class Client(original):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr("src.gemini.httpx.AsyncClient", Client)
    model = create_model(
        Settings(_env_file=None, model="gpt-6-sol", api_key="test-secret")
    )
    trace = TraceRecorder(secrets=["test-secret"])
    messages = decide_messages(initial(), "interpretation")
    try:
        with recording(trace):
            if bad_response:
                with pytest.raises(ValidationError):
                    await structured_call(model, Decision, messages, {})
            else:
                value, _ = await structured_call(model, Decision, messages, {})
                assert value == DONE
    finally:
        await model.http_async_client.aclose()
    assert requests[0]["input"][1]["content"] == messages[1].content
    assert requests[0]["text"]["format"]["type"] == "json_schema"
    span = trace.spans[0]
    assert span["http_request"]["body"] == requests[0]
    assert span["output"]["sdk_response"]["content"][0]["text"] == content
    assert span["status"] == ("error" if bad_response else "success")
    assert "test-secret" not in json.dumps(trace.spans)
