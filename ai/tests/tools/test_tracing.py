"""Direct tool evaluation keeps evidence without duplicating agent tool calls."""

from copy import deepcopy
from pathlib import Path

import pytest

from src.exceptions import ToolFailure
from src.execution_trace import TraceRecorder, recording, trace_span
from src.tools.process import process_data
from src.tools.query import query_data
from src.tools.render import render_visualization
from src.tools.tableau import validate_visualization
from tests.helpers import initial


def test_direct_query_records_rejected_input_before_provider_execution(dataset):
    calls = []
    recorder = TraceRecorder()
    bad_request = {"target": "activity", "limit": 0}
    with recording(recorder), pytest.raises(ToolFailure) as raised:
        query_data(bad_request, {"activity": lambda: calls.append(True) or dataset})
    assert raised.value.code == "invalid_input"
    assert calls == []
    assert len(recorder.spans) == 1
    span = recorder.spans[0]
    assert span["name"] == "query_data" and span["kind"] == "tool"
    assert span["input"]["resolved_arguments"] == bad_request
    assert span["status"] == "error" and span["ended_at"]
    assert span["elapsed_seconds"] >= 0
    assert span["error"]["code"] == "invalid_input"
    assert span["error"]["cause"]["validation_errors"]


def test_direct_query_and_render_record_results_and_parent_links(dataset):
    recorder = TraceRecorder()
    with recording(recorder):
        result = query_data({"target": "activity"}, {"activity": lambda: dataset})
        rendered = render_visualization(
            {"data": result["data"], "spec": {"type": "table", "title": "Evidence"}}
        )
    query, provider, render = recorder.spans
    assert query["output"] == result
    assert provider["parent_id"] == query["id"]
    assert render["output"] == rendered
    assert all(s["status"] == "success" and s["ended_at"] for s in recorder.spans)
    result["data"]["rows"].clear()
    assert query["output"]["data"]["rows"]


def test_invalid_provider_result_keeps_raw_output_inside_failed_provider_span(dataset):
    invalid = deepcopy(dataset)
    invalid["rows"][0]["before"] = "not a number"
    recorder = TraceRecorder()
    with recording(recorder), pytest.raises(ToolFailure) as raised:
        query_data({"target": "activity"}, {"activity": lambda: invalid})
    assert raised.value.code == "invalid_data"
    tool, provider = recorder.spans
    assert provider["parent_id"] == tool["id"]
    assert provider["output"] == invalid
    assert provider["status"] == tool["status"] == "error"
    assert provider["error"]["code"] == "invalid_data"
    assert "output" not in tool


def test_direct_processing_error_preserves_operation_and_rejection_details(dataset):
    recorder = TraceRecorder()
    request = {
        "data": dataset,
        "operations": [{"operation": "cast", "field": "missing", "kind": "number"}],
    }
    with recording(recorder), pytest.raises(ToolFailure):
        process_data(request)
    tool, operation = recorder.spans
    assert operation["parent_id"] == tool["id"]
    assert tool["error"]["details"]["operation_index"] == 0
    assert tool["error"]["details"]["requested"] == ["missing"]
    assert tool["error"]["retryable"] is False
    assert tool["input"]["resolved_arguments"] == request


def test_direct_tableau_rejection_is_a_returned_result_without_state_changes():
    state = initial("user_request")
    before = deepcopy(state)
    recorder = TraceRecorder()
    with recording(recorder):
        result = validate_visualization({"view_key": "unregistered"}, state=state)
    span = recorder.spans[0]
    assert span["output"] == result
    assert span["status"] == "success" and result["valid"] is False
    assert span["input"]["state"]["execution"]["event"] == "user_request"
    assert state == before


def test_agent_boundary_keeps_selected_arguments_without_duplicate_tool_spans(dataset):
    recorder = TraceRecorder()
    selected = {
        "input_result_id": "result-123",
        "operations": [
            {"operation": "filter", "conditions": []},
        ],
    }
    actual = {"data": dataset, "operations": selected["operations"]}
    with (
        recording(recorder),
        trace_span(
            "tool",
            "process_data",
            {"selected_arguments": selected, "resolved_arguments": actual},
        ) as outer,
    ):
        result = process_data(actual)
        outer.update(output=result)
    tool_spans = [s for s in recorder.spans if s["kind"] == "tool"]
    assert len(tool_spans) == 1
    assert tool_spans[0]["input"]["selected_arguments"] == selected
    assert tool_spans[0]["output"] == result
    assert recorder.spans[1]["parent_id"] == tool_spans[0]["id"]


def test_unserializable_invalid_input_remains_a_tool_rejection():
    recorder = TraceRecorder()
    with recording(recorder), pytest.raises(ToolFailure) as raised:
        query_data({"target": object()}, {})
    assert raised.value.code == "invalid_input"
    assert recorder.spans[0]["input"]["resolved_arguments"]["target"] == "<object>"


@pytest.mark.parametrize("failure_at", ["creation", "append"])
def test_journal_failure_preserves_tool_return_and_original_error(
    dataset, tmp_path, monkeypatch, caplog, failure_at
):
    journal = tmp_path / "trace.jsonl"
    recorder = TraceRecorder(journal=journal) if failure_at == "append" else None
    original_open = Path.open

    def denied(path, *args, **kwargs):
        if path == journal:
            raise PermissionError("sensitive-filesystem-detail")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    if recorder is None:
        recorder = TraceRecorder(journal=journal)
    original_error = ToolFailure("read_unavailable", retryable=True)

    def fail_provider():
        raise original_error

    with recording(recorder):
        returned = query_data({"target": "activity"}, {"activity": lambda: dataset})
        with pytest.raises(ToolFailure) as raised:
            query_data({"target": "activity"}, {"activity": fail_provider})
    assert raised.value is original_error
    assert recorder.journal is None
    exported = recorder.export()
    calls = [s for s in exported["spans"] if s["kind"] == "tool"]
    assert calls[0]["output"] == returned
    assert calls[0]["status"] == "success"
    assert calls[1]["status"] == "error"
    assert calls[1]["error"]["code"] == "read_unavailable"
    assert exported["coverage"]["unfinished_spans"] == 0
    assert len(caplog.records) == 1
    assert "in-memory trace" in caplog.text
    assert "sensitive-filesystem-detail" not in caplog.text
