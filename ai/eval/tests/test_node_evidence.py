"""원문·부모 연결·누락·사용량의 경계만 검사하는 작은 실행 증거."""

import json
from copy import deepcopy

import pytest

from eval.nodes.criteria import load_criteria
from eval.nodes.evidence import extract_nodes
from src.execution_trace import execution_manifest
from src.settings import Settings


def span(identity, kind, name, parent=None, **changes):
    return {
        "id": identity,
        "kind": kind,
        "name": name,
        "parent_id": parent,
        "status": "success",
        "ended_at": "2026-11-11T00:00:01+00:00",
        "elapsed_seconds": 1.0,
        "input": {},
    } | changes


def node(
    identity="n", name="decide", parent=None, before=None, records=None, **changes
):
    return span(
        identity,
        "node",
        name,
        parent,
        input={"state": {"results": before or []}},
        output={"applied_update": {"results": records or [], "execution": {}}},
        **changes,
    )


def model(
    identity="m", parent="n", raw='{"next":"compose","reason":"완료"}', **changes
):
    return span(
        identity,
        "model",
        "Decision",
        parent,
        input={
            "messages": [{"type": "human", "content": "실제 요청"}],
            "response_schema": {"type": "object"},
        },
        output={
            "sdk_response": {
                "content": raw,
                "usage_metadata": {"input_tokens": 3, "output_tokens": 2},
            }
        },
        **changes,
    )


def report(*spans):
    return {"run": {"id": "run", "role": "request"}, "trace": {"spans": list(spans)}}


def case(**changes):
    return {
        "id": "case",
        "unit": "node",
        "target": "decide",
        "role": "request",
    } | changes


def test_original_model_review_is_not_replaced_by_runtime_verdict():
    original = {"accepted": True, "reason": "적합"}
    evidence = report(
        node(
            name="compose",
            records=[
                {
                    "id": "review",
                    "decision": "verification",
                    "output": {"accepted": False},
                }
            ],
        ),
        model(raw=json.dumps(original)),
    )
    saved = deepcopy(evidence)
    (result,) = extract_nodes(evidence, case(target="compose"))
    assert result["calls"][0]["output"] == original
    assert result["calls"][0]["path"] == "/trace/spans/1"
    assert result["usage"] == {"input_tokens": 3, "output_tokens": 2}
    assert evidence == saved


@pytest.mark.parametrize("raw", ["not JSON", '{"x": NaN}', '{"x":1,"x":2}'])
def test_malformed_raw_is_kept_and_is_not_a_missing_response(raw):
    (result,) = extract_nodes(report(node(), model(raw=raw)), case())
    call = result["calls"][0]
    assert call["raw"] == raw
    assert call["output"] is None
    assert call["complete"] is True
    assert call["error"]["type"] == "InvalidModelJSON"


def test_nested_nodes_own_only_their_direct_models_and_keep_roles():
    outer = node("outer", "act")
    child_agent = span(
        "agent",
        "agent",
        "interpretation_agent",
        "outer",
        input={"role": "interpretation"},
    )
    child = node("child", "compose", "agent")
    values = extract_nodes(
        report(outer, model("om", "outer"), child_agent, child, model("cm", "child")),
        case(target="act"),
    )
    assert [(n["role"], [c["id"] for c in n["calls"]]) for n in values] == [
        ("request", ["om"]),
        ("interpretation", ["cm"]),
    ]
    assert [n["model_calls"] for n in values] == [1, 1]


@pytest.mark.parametrize(
    "change", ["missing_parent", "cycle", "conflict", "unfinished"]
)
def test_broken_trace_is_not_reported_as_zero_usage_or_complete(change):
    n, m = node(), model()
    spans = [n, m]
    if change == "missing_parent":
        m["parent_id"] = "absent"
    elif change == "cycle":
        n["parent_id"] = "m"
    elif change == "conflict":
        spans.append(m | {"name": "Conflicting"})
    else:
        m["ended_at"] = None
    (result,) = extract_nodes(report(*spans), case())
    assert result["issues"]
    assert result["complete"] is False
    assert result["model_calls"] is None
    assert result["technical_retries"] is None
    assert result["usage"]["input_tokens"] is None


def test_tokens_missing_is_distinct_from_observed_zero():
    m = model()
    m["output"]["sdk_response"]["usage_metadata"] = {"input_tokens": 0}
    (result,) = extract_nodes(report(node(), m), case())
    assert result["usage"] == {"input_tokens": 0, "output_tokens": None}


def test_selection_is_retained_without_counting_as_node_execution():
    root = span("eval", "evaluation", "act", input={"initial_state": {"results": []}})
    (result,) = extract_nodes(
        report(root, model(parent="eval")), case(unit="selection", target="act")
    )
    assert result["node"] == "act"
    assert result["counted"] is False
    assert result["model_calls"] == 1


def test_missing_node_has_unjudged_placeholder_but_graph_has_no_invented_nodes():
    (result,) = extract_nodes(report(), case())
    assert result["complete"] is False and result["issues"]
    assert result["technical_retries"] is None
    assert extract_nodes(report(), case(unit="agent", target="request")) == []


def test_caught_runtime_error_and_model_format_error_are_distinguished():
    failed = {
        "id": "failed",
        "decision": "execution_failed",
        "output": {"error_type": "ConnectionError"},
    }
    m = model()
    m.update(status="error", error={"type": "ConnectionError"})
    m.pop("output")
    (result,) = extract_nodes(report(node(records=[failed]), m), case())
    assert result["status"] == "success"
    assert result["technical_failure"] is True
    failed["output"]["error_type"] = "ValidationError"
    m = model(raw="invalid JSON", status="error", error={"type": "ValidationError"})
    (result,) = extract_nodes(report(node(records=[failed]), m), case())
    assert result["technical_failure"] is False


def test_retry_requires_linked_technical_failure_and_actual_same_call():
    action = {"name": "query_data", "arguments": {"target": "a"}}
    previous = {
        "id": "old",
        "decision": "call",
        "action": action,
        "outcome": "failure",
        "output": {"error_type": "TimeoutError"},
    }
    retry = {"id": "retry", "decision": "retry", "output": {"call_id": "old"}}
    called = {
        "id": "new",
        "decision": "call",
        "action": action,
        "outcome": "success",
        "output": {},
    }
    (result,) = extract_nodes(
        report(node(before=[previous], records=[previous, retry, called])), case()
    )
    assert result["technical_retries"] == 1
    previous.update(outcome="success", output={"valid": False})
    (result,) = extract_nodes(
        report(node(before=[previous], records=[previous, retry, called])), case()
    )
    assert result["technical_retries"] == 0
    previous.update(outcome="failure", output={})
    (result,) = extract_nodes(
        report(node(before=[previous], records=[previous, retry, called])), case()
    )
    assert result["technical_retries"] is None


def test_manifest_captures_nested_node_criteria_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.execution_trace.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(OSError()),
    )
    criteria = tmp_path / "eval" / "docs" / "nodes" / "common.md"
    criteria.parent.mkdir(parents=True)
    criteria.write_text("first", encoding="utf-8")
    settings = Settings(_env_file=None)
    first = execution_manifest(settings, root=tmp_path)
    assert "eval/docs/nodes/common.md" in first["files_sha256"]
    criteria.write_text("second", encoding="utf-8")
    assert (
        execution_manifest(settings, root=tmp_path)["content_sha256"]
        != first["content_sha256"]
    )


def retry_records(name, *, decision="call", error=None):
    action = {"name": name, "arguments": {}}
    previous = {
        "id": "old",
        "decision": decision,
        "action": action,
        "outcome": "failure",
        "output": {"error_type": "TimeoutError"} if error is None else error,
    }
    retry = {"id": "retry", "decision": "retry", "output": {"call_id": "old"}}
    called = {
        "id": "new",
        "decision": decision,
        "action": action,
        "outcome": "success",
        "output": {},
    }
    return previous, retry, called


@pytest.mark.parametrize(
    ("name", "kind", "trace_name", "decision"),
    [
        ("query_data", "tool", "query_data", "call"),
        ("interpretation_agent", "agent", "interpretation_agent", "call"),
        ("write_report", "model", "ReportText", "report_draft"),
    ],
)
def test_technical_retry_kind_uses_the_direct_call_trace(
    name, kind, trace_name, decision
):
    previous, retry, called = retry_records(name, decision=decision)
    direct = span("attempt", kind, trace_name, "n")
    (result,) = extract_nodes(
        report(node(before=[previous], records=[previous, retry, called]), direct),
        case(),
    )
    assert result["technical_retries"] == 1
    assert result["technical_retries_by_kind"] == {
        key: int(key == kind) for key in ("model", "tool", "agent")
    }


def test_retry_total_does_not_invent_missing_call_kinds():
    previous, retry, called = retry_records("unidentified")
    (result,) = extract_nodes(
        report(node(before=[previous], records=[previous, retry, called])), case()
    )
    assert result["technical_retries"] == 1
    assert result["technical_retries_by_kind"] == {
        "model": None,
        "tool": None,
        "agent": None,
    }


def test_unknown_error_only_invalidates_the_identified_retry_kind():
    previous, retry, called = retry_records("query_data", error={"code": "unknown"})
    (result,) = extract_nodes(
        report(
            node(before=[previous], records=[previous, retry, called]),
            span("attempt", "tool", "query_data", "n"),
        ),
        case(),
    )
    assert result["technical_retries"] is None
    assert result["technical_retries_by_kind"] == {
        "model": 0,
        "tool": None,
        "agent": 0,
    }


def test_review_retry_counts_model_failure_but_not_content_rework():
    previous, _, called = retry_records("review_report", decision="verification")
    direct = model() | {"name": "Verification"}
    evidence = report(node(before=[previous], records=[previous, called]), direct)
    (result,) = extract_nodes(evidence, case())
    assert result["technical_retries_by_kind"] == {"model": 1, "tool": 0, "agent": 0}
    previous.update(outcome="success", output={"accepted": False})
    (result,) = extract_nodes(
        report(node(before=[previous], records=[previous, called]), direct), case()
    )
    assert result["technical_retries_by_kind"] == {"model": 0, "tool": 0, "agent": 0}


def test_child_retry_kind_is_not_counted_for_the_parent_node():
    previous, retry, called = retry_records("write_report", decision="report_draft")
    parent = node("outer", "act")
    child = node(
        "child",
        "compose",
        "agent",
        before=[previous],
        records=[previous, retry, called],
    )
    values = extract_nodes(
        report(
            parent,
            span("agent", "agent", "interpretation_agent", "outer"),
            child,
            model(parent="child") | {"name": "ReportText"},
        ),
        case(target="act"),
    )
    assert values[0]["technical_retries_by_kind"] == {"model": 0, "tool": 0, "agent": 0}
    assert values[1]["technical_retries_by_kind"] == {"model": 1, "tool": 0, "agent": 0}


def test_unfinished_usage_keeps_received_tokens_and_missing_calls_separately():
    pending = model("waiting", ended_at=None, status="running")
    pending.pop("output")
    unfinished = node(ended_at=None, status="running")
    unfinished.pop("output")
    (result,) = extract_nodes(report(unfinished, model(), pending), case())
    assert result["usage"] == {"input_tokens": None, "output_tokens": None}
    assert result["model_calls"] is None
    assert result["unfinished"] is True
    assert result["observed_usage"] == {
        "usage": {"input_tokens": 3, "output_tokens": 2},
        "usage_missing_calls": {"input_tokens": 1, "output_tokens": 1},
        "model_calls": 2,
        "technical_retries": None,
        "technical_retries_by_kind": {"model": None, "tool": None, "agent": None},
    }


def test_unfinished_retry_observation_does_not_become_a_final_total():
    previous, retry, called = retry_records("query_data")
    (result,) = extract_nodes(
        report(
            node(
                before=[previous],
                records=[previous, retry, called],
                ended_at=None,
                status="running",
            ),
            span("attempt", "tool", "query_data", "n", ended_at=None, status="running"),
        ),
        case(),
    )
    assert result["technical_retries"] is None
    assert result["observed_usage"]["technical_retries"] == 1
    assert result["observed_usage"]["technical_retries_by_kind"] == {
        "model": 0,
        "tool": 1,
        "agent": 0,
    }


def test_model_output_node_uses_recorded_role_without_state_update():
    recorded = span(
        "n",
        "node",
        "decide",
        input={"role": "visualization", "evaluation_scope": "model_output"},
    )
    (value,) = extract_nodes(report(recorded, model()), case(role="visualization"))
    assert value["role"] == "visualization"
    assert value["complete"]
    assert not value["issues"]
    assert value["state"] == {}


def test_requested_scope_filters_other_nodes_and_keeps_original_call_index():
    catalog = load_criteria()
    first = node("first", "compose") | {
        "input": {"role": "report_insight", "state": {"results": []}}
    }
    second = node("second", "compose") | {
        "input": {"role": "report_insight", "state": {"results": []}}
    }
    spans = [first, model("first-call", "first"), second]
    spans.extend(
        model(f"call-{index}", "second") | {"name": "Verification"}
        for index in (1, 2, 3)
    )
    selected_case = case(
        unit="workflow",
        target="report",
        assessment={
            "checks": ["N-F.1"],
            "expected": {
                "schema_version": "node-expectations-v1",
                "items": [
                    {
                        "id": "review",
                        "check": "N-F.1",
                        "node": "compose",
                        "role": "report_insight",
                        "occurrence": 2,
                        "call": "Verification",
                        "call_index": 3,
                    },
                ],
            },
        },
    )
    (value,) = extract_nodes(report(*spans), selected_case, catalog=catalog)
    assert value["id"] == "second"
    assert value["occurrence"] == 2
    assert [(call["id"], call["index"]) for call in value["calls"]] == [("call-3", 3)]


def test_single_node_case_does_not_extract_child_node_assessments():
    selected_case = case(target="act", assessment={"checks": ["N-F.1"]})
    values = extract_nodes(
        report(
            node("outer", "act"),
            model("outer-call", "outer"),
            span("agent", "agent", "interpretation_agent", "outer"),
            node("child", "compose", "agent"),
            model("child-call", "child"),
        ),
        selected_case,
        catalog=load_criteria(),
    )
    assert [value["id"] for value in values] == ["outer"]


def test_selection_uses_actual_node_span_when_model_output_runner_records_one():
    evidence = report(
        span("evaluation", "evaluation", "act"),
        span(
            "n",
            "node",
            "act",
            "evaluation",
            input={"role": "request", "evaluation_scope": "model_output"},
        ),
        model(),
    )
    (value,) = extract_nodes(evidence, case(unit="selection", target="act"))
    assert value["id"] == "n"
    assert not value["counted"]
    assert [call["id"] for call in value["calls"]] == ["m"]


def test_row_filter_excludes_known_mismatch_without_deleting_raw_report():
    original = report(node(), model())
    saved = deepcopy(original)
    values = extract_nodes(
        original,
        case(assessment={"checks": ["N-F.1"]}),
        catalog=load_criteria(),
        row_ids=["N-F.1/interpret"],
    )
    assert values == []
    assert original == saved


def test_row_filter_preserves_missing_tool_evidence_for_unjudged_result():
    original = report(node(name="act"), model())
    original["trace"]["spans"][1]["name"] = "Selection"
    original["trace"]["spans"][1]["output"] = {}
    (value,) = extract_nodes(
        original,
        case(target="act", assessment={"checks": ["N-F.1"]}),
        catalog=load_criteria(),
        row_ids=["N-F.1/act-visualization"],
    )
    assert value["calls"][0]["raw"] is None
    assert value["calls"][0]["index"] == 1
