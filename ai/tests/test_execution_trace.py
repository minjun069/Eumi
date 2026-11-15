"""Exercise real call boundaries, failure retention and observation isolation."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from demo.scenario_demo import run_scenario
from src.agent_nodes import Decision
from src.execution_trace import (
    TraceRecorder,
    execution_manifest,
    recording,
    trace_acall,
    trace_call,
    trace_output,
    trace_span,
)
from src.gemini import create_model, structured_call
from src.prompting import decide_messages
from src.settings import Settings
from tests.helpers import DONE, ScriptedModel, composition, initial, selection


@pytest.mark.asyncio
async def test_call_wrappers_snapshot_before_mutation_and_preserve_result_identity():
    value = {"rows": [1]}
    recorder = TraceRecorder()
    calls = []

    def mutate():
        calls.append("sync")
        value["rows"].append(2)
        return value

    async def invoke():
        calls.append("async")
        await asyncio.sleep(0)
        return trace_call("tool", "mutate", value, mutate)

    with recording(recorder):
        result = await trace_acall("agent", "invoke", value, invoke)
    assert result is value
    assert calls == ["async", "sync"]
    parent, child = recorder.spans
    assert parent["input"] == child["input"] == {"rows": [1]}
    assert parent["output"] == child["output"] == {"rows": [1, 2]}
    assert child["parent_id"] == parent["id"]
    value["rows"].clear()
    assert parent["output"] == {"rows": [1, 2]}


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("private"), asyncio.CancelledError()])
async def test_call_wrapper_propagates_original_error_once_and_restores_parent(error):
    recorder = TraceRecorder()
    calls = 0

    async def fail():
        nonlocal calls
        calls += 1
        raise error

    with recording(recorder), trace_span("agent", "parent", {}):
        with pytest.raises(type(error)) as caught:
            await trace_acall("tool", "fail", {}, fail)
        trace_output({"caught": True})
    assert caught.value is error
    assert calls == 1
    parent, child = recorder.spans
    assert parent["output"] == {"caught": True}
    assert parent["status"] == "success"
    assert child["status"] == "error"
    assert child["error"]["type"] == type(error).__name__


def test_disabled_trace_does_not_evaluate_output_builders():
    def unexpected(*args):
        pytest.fail("disabled trace evaluated an output builder")

    value = object()
    assert trace_call("tool", "disabled", {}, lambda: value, output=unexpected) is value
    trace_output(build=unexpected)


def test_trace_output_treats_a_returned_callable_as_data():
    def unexpected():
        pytest.fail("logging executed the returned value")

    recorder = TraceRecorder()
    with recording(recorder), trace_span("provider", "invalid", {}):
        trace_output(unexpected)
    assert recorder.spans[0]["output"] == "<function>"


def test_shared_writer_redacts_without_mutating_and_can_require_evidence(
    tmp_path, monkeypatch
):
    settings = Settings(
        _env_file=None, api_key="model-secret", langfuse_public_key="telemetry-secret"
    )
    recorder = TraceRecorder.from_settings(settings)
    value = {"text": "model-secret telemetry-secret", "authorization": "Bearer token"}
    path = tmp_path / "evidence.json"
    assert recorder.write_json(path, value)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "text": "[REDACTED] [REDACTED]",
        "authorization": "[REDACTED]",
    }
    assert value["text"] == "model-secret telemetry-secret"

    def fail_replace(*args):
        raise OSError("private-location")

    monkeypatch.setattr(type(path), "replace", fail_replace)
    assert recorder.write_json(path, {"text": "replacement"}) is False
    assert json.loads(path.read_text(encoding="utf-8"))["text"] == (
        "[REDACTED] [REDACTED]"
    )
    with pytest.raises(OSError):
        recorder.write_json(path, {}, strict=True)


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


def test_manifest_tracks_current_code_and_criteria_without_reading_secrets(
    tmp_path, monkeypatch
):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr("src.execution_trace.subprocess.run", unavailable)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text("version = 1", encoding="utf-8")
    (tmp_path / "eval" / "docs").mkdir(parents=True)
    criteria = tmp_path / "eval" / "docs" / "tools.md"
    criteria.write_text("first criteria", encoding="utf-8")
    node_criteria_dir = tmp_path / "eval" / "docs" / "nodes"
    originals = node_criteria_dir / "originals"
    originals.mkdir(parents=True)
    node_criteria = node_criteria_dir / "compose.json"
    node_criteria.write_text('{"version": 1}', encoding="utf-8")
    original = originals / "compose.md"
    original.write_text("migration reference", encoding="utf-8")
    (tmp_path / ".env").write_text("private-env-value", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        api_key="private-api-key",
        base_url="https://private-user:private-password@example.com/v1?token=private-query",
        backend_token="private-backend-token",
    )
    before = execution_manifest(settings, root=tmp_path)
    assert before["git"] == {"revision": None, "dirty": None}
    assert set(before["files_sha256"]) == {
        "src/example.py",
        "eval/docs/tools.md",
        "eval/docs/nodes/compose.json",
    }
    assert before["settings"]["base_url"] == "https://example.com/v1"
    assert "private-" not in json.dumps(before)
    original.write_text("updated migration reference", encoding="utf-8")
    assert (
        execution_manifest(settings, root=tmp_path)["content_sha256"]
        == before["content_sha256"]
    )
    node_criteria.write_text('{"version": 2}', encoding="utf-8")
    updated_node_criteria = execution_manifest(settings, root=tmp_path)
    assert updated_node_criteria["content_sha256"] != before["content_sha256"]
    criteria.write_text("updated criteria", encoding="utf-8")
    after = execution_manifest(settings, root=tmp_path)
    assert updated_node_criteria["content_sha256"] != after["content_sha256"]
    assert (
        before["files_sha256"]["src/example.py"]
        == after["files_sha256"]["src/example.py"]
    )
    (tmp_path / "src" / "example.py").write_text("version = 2", encoding="utf-8")
    assert (
        execution_manifest(settings, root=tmp_path)["content_sha256"]
        != after["content_sha256"]
    )


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
        [
            {"next": "act", "reason": "비율 계산에 사용할 가구 자료 필요"},
            selection("query_data", {"target": "D3"}),
            DONE,
            composition,
        ]
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
    assert requests[0]["text"]["format"]["strict"] is False
    assert "tools" not in requests[0] and "tool_choice" not in requests[0]
    span = trace.spans[0]
    assert span["http_request"]["body"] == requests[0]
    assert span["output"]["sdk_response"]["content"][0]["text"] == content
    assert span["status"] == ("error" if bad_response else "success")
    assert "test-secret" not in json.dumps(trace.spans)
