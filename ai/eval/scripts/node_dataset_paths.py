"""Record complete fixture paths with the production nodes and immutable evidence.

Only the model boundary is scripted. These responses build example histories;
assessment remains the independent quality oracle, including on defect branches.
"""

from __future__ import annotations

import json
from collections import Counter
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, TypedDict
from unittest.mock import patch
from uuid import UUID, uuid5

from langchain_core.messages import AIMessage

from eval.runner import _sources, prepare_state
from eval.schema import case_adapter
from eval.scripts.node_dataset_users import _assessment
from src.agent_nodes import build_nodes, finish, publish_report
from src.execution import accepted_outputs, record
from src.graph import DESTINATIONS, run_node
from src.settings import Settings
from src.state import state_adapter


class CaseUsage(TypedDict):
    scenario_id: str
    step_id: str


class PathStep(TypedDict):
    step_id: str
    case_id: str
    node: str
    role: str
    frame: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    expected_next_nodes: list[str]
    model_outputs: list[dict[str, Any]]
    boundary_before: dict[str, Any]


def digest(value):
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def dump_state(state):
    return state_adapter.dump_python(state_adapter.validate_python(state), mode="json")


def initial_input(state):
    value = dump_state(state)
    return {
        **{key: value[key] for key in ("request", "messages", "results", "response")},
        "event": value["execution"]["event"],
        "execution": value["execution"],
    }


def identity(case):
    """Descriptions and memberships are not execution inputs or judging criteria."""
    return digest({k: v for k, v in case.items() if k not in {"id", "purpose", "tags"}})


def report_stage_state(state, role):
    """Apply only the existing report_flow stage entry contract."""
    before = dump_state(state)
    state = deepcopy(state)
    with deterministic_runtime(digest([before, role, "handoff"])):
        state["results"].append(
            record(
                "report",
                "report_stage",
                "보고서 에이전트 순차 실행",
                action={
                    "name": role + "_agent",
                    "arguments": {
                        "view_key": None,
                        "result_ids": [
                            *[
                                r["id"]
                                for r in state["results"]
                                if r["decision"] in {"report_input", "report_source"}
                            ],
                            *accepted_outputs(state),
                        ],
                    },
                },
            )
        )
    state["execution"].update(status="queued", error=None)
    return state


def published_report_state(state):
    before = dump_state(state)
    state = deepcopy(state)
    with deterministic_runtime(digest([before, "publish"])):
        error = state["execution"]["error"]
        status = publish_report(state)
        state["execution"].update(
            status=status,
            error=error
            or (
                None
                if status == "completed"
                else {"code": "incomplete", "cause": "완성하지 못한 항목은 NULL"}
            ),
        )
    return state


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 12, tzinfo=UTC).astimezone(tz or UTC)


@contextmanager
def deterministic_runtime(seed):
    counter = 0

    def next_id():
        nonlocal counter
        counter += 1
        return uuid5(UUID(int=1), f"{seed}:{counter}")

    with ExitStack() as stack:
        for module in ("execution", "agent_nodes", "graph", "state"):
            stack.enter_context(patch(f"src.{module}.uuid4", side_effect=next_id))
        stack.enter_context(
            patch("langgraph.graph.message.uuid", SimpleNamespace(uuid4=next_id))
        )
        stack.enter_context(patch("src.execution.monotonic", return_value=0.0))
        stack.enter_context(patch("src.gemini.monotonic", return_value=0.0))
        stack.enter_context(patch("src.agent_nodes.datetime", FixedDateTime))
        yield


class ScriptedModel:
    def __init__(self, outputs):
        self.outputs = deepcopy(outputs)
        self.used = 0

    def with_structured_output(self, _schema, **_kwargs):
        return self

    async def ainvoke(self, _messages, _config=None):
        if self.used >= len(self.outputs):
            raise AssertionError("Path exhausted its authored model responses")
        output = self.outputs[self.used]
        self.used += 1
        return {
            "raw": AIMessage(json.dumps(output, ensure_ascii=False)),
            "parsed": output,
        }


def default_assessment(node, role, outputs, label):
    if not outputs:
        return {
            "required": False,
            "checks": [],
            "reference": {
                "runtime_only": (
                    "이 입력에서는 모델 호출 없이 승인 산출물의 단계 종료를 구성한다."
                )
            },
            "expected": {"schema_version": "node-expectations-v1", "items": []},
        }
    output = outputs[0]
    ref = {"expected_behavior": label, "allowed_scope": "현재 요청과 제공된 근거 범위"}
    exact = {}
    if node == "interpret":
        ref["request"] = output["request"]
    elif node == "act":
        arguments = json.loads(output["arguments_json"])
        ref.update(selected_name=output["name"], expected_arguments=arguments)
        exact["N02-O.1"] = {"path": "/name", "value": output["name"]}
        exact["N02-O.3"] = {
            "path": "/arguments_json",
            "value": output["arguments_json"],
        }
    elif node == "decide":
        exact["N03-O.3"] = {"path": "/next", "value": output["next"]}
        ref["next"] = output["next"]
    elif node == "compose" and not role.startswith("report_"):
        ref.update(expected_content=output["content"], status=output["status"])
    result = _assessment(node, ref, exact, artifacts=output.get("artifact_ids", []))
    result["required"] = True
    return result


class PathRecorder:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.settings = Settings(
            _env_file=None,
            max_steps=200,
            max_tool_calls=100,
            max_agent_calls=20,
            max_tool_retries=20,
            runtime_timeout=3600,
            langfuse_enabled=False,
        )
        self.cases = []
        self.scenarios = []
        self.current = None
        self._pending = None
        self._active = []

    def initial_state(self, initial):
        with deterministic_runtime("initial"):
            return prepare_state({"initial": initial}, self.settings, str(UUID(int=1)))

    def begin(self, identity, title, event, family, axes=None, source_groups=None):
        self.current = {
            "id": identity,
            "title": title,
            "event": event,
            "family": family,
            "axes": deepcopy(axes or {}),
            "source_groups": source_groups or [],
            "steps": [],
            "boundaries": [],
            "events": [],
            "history_provenance": (
                "작성한 모델 응답으로 실제 노드를 실행해 구성한 기준 이력"
            ),
        }
        self._pending = None
        self._active = []

    async def step(
        self,
        node,
        role,
        state,
        outputs,
        template=None,
        label="",
        frame="root",
        child_plan=None,
        provider_failures=None,
    ):
        before = dump_state(state)
        if "start_state" not in self.current:
            self.current["start_state"] = deepcopy(before)
        steps = self.current["steps"]
        step_id = f"s{len(steps) + 1:03d}"
        previous = next((s for s in reversed(steps) if s["frame"] == frame), None)
        if self._pending:
            boundary = self._pending
            self._pending = None
        elif previous is None and self._active and self._active[-1]["frame"] != frame:
            boundary = {"kind": "call", "from_step": self._active[-1]["step_id"]}
        else:
            boundary = {
                "kind": "next" if previous else "entry",
                "from_step": previous["step_id"] if previous else None,
            }
            if previous and any(
                s.get("boundary_before", {}).get("from_step") == previous["step_id"]
                and s["boundary_before"]["kind"] == "call"
                for s in steps
            ):
                boundary["kind"] = "return"
        step = {
            "step_id": step_id,
            "node": node,
            "role": role,
            "frame": frame,
            "before_state": before,
            "boundary_before": boundary,
            "model_outputs": deepcopy(outputs),
        }
        steps.append(step)
        self._active.append(step)
        case = deepcopy(template or {})
        case.update(
            id="path-" + node + "-" + digest([before, role, label])[:16],
            unit="node",
            target=node,
            role=role,
            initial=initial_input(state),
            purpose=label or f"{role} {node} 전체 경로의 독립 노드 평가",
        )
        case["tags"] = [
            t
            for t in case.get("tags", [])
            if not t.startswith(("scenario:", "step:", "variant:", "family:"))
        ]
        case["tags"] += ["complete-path", f"family:{self.current['family']}"]
        case.pop("stubs", None)
        case.pop("dependencies", None)
        if provider_failures:
            case["provider_failures"] = deepcopy(provider_failures)
        if not outputs:
            case["assessment"] = default_assessment(node, role, outputs, label)
            case["tags"].append("runtime-only")
        elif "assessment" not in case:
            case["assessment"] = default_assessment(node, role, outputs, label)
        providers, catalog = _sources(case, self.snapshot, self.settings)
        child_finals = []

        async def child_runner(child_role, child_state, _config):
            if child_plan is None:
                raise AssertionError("Full path must expand its delegated child")
            value = await child_plan(child_role, child_state)
            child_finals.append(dump_state(value))
            return value

        model = ScriptedModel(outputs)
        nodes = build_nodes(
            model,
            providers,
            catalog,
            role=role,
            agent_runner=child_runner if child_plan else None,
        )
        seed = digest([before, role, node, outputs])
        with deterministic_runtime(seed):
            after, goto = await run_node(
                node, nodes[node], deepcopy(state), finish=finish
            )
        if model.used != len(outputs):
            raise AssertionError(
                f"{self.current['id']} {step_id}: unused model responses"
            )
        if after["results"] and after["results"][-1]["decision"] == "execution_failed":
            raise AssertionError(
                f"{self.current['id']} {step_id}: {after['results'][-1]}"
            )
        if child_finals:
            selection = outputs[0]
            child = child_finals[-1]
            case["dependencies"] = "stub"
            case["stubs"] = [
                {
                    "name": selection["name"],
                    "arguments": json.loads(selection["arguments_json"]),
                    "output": {
                        "response": child["response"],
                        "results": child["results"],
                        "status": child["execution"]["status"],
                        "error": child["execution"]["error"],
                    },
                }
            ]
        case_adapter.validate_python(case)
        # The final identity includes every input, dependency and independent oracle.
        case["id"] = f"path-{node}-{identity(case)[:20]}"
        step.update(
            case_id=case["id"],
            after_state=dump_state(after),
            expected_next_nodes=[goto],
        )
        self.cases.append(case)
        self._active.pop()
        return after

    def report_stage(self, state, role):
        before = dump_state(state)
        self.current.setdefault("start_state", deepcopy(before))
        state = report_stage_state(state, role)
        event = {
            "id": f"b{len(self.current['boundaries']) + 1:03d}",
            "kind": "report_handoff",
            "role": role,
            "before_state": before,
            "after_state": dump_state(state),
        }
        self.current["boundaries"].append(event)
        self._pending = {
            "kind": "report_handoff",
            "boundary_id": event["id"],
            "from_step": self.current["steps"][-1]["step_id"]
            if self.current["steps"]
            else None,
        }
        return state

    def publish_report(self, state):
        before = dump_state(state)
        state = published_report_state(state)
        self.current["boundaries"].append(
            {
                "id": f"b{len(self.current['boundaries']) + 1:03d}",
                "kind": "publish_report",
                "before_state": before,
                "after_state": dump_state(state),
            }
        )
        return state

    def end(self, state, terminal=None):
        actual = state["execution"]["status"]
        if terminal is not None and actual != terminal:
            raise AssertionError(f"{self.current['id']}: {actual} != {terminal}")
        self.current["terminal"] = {"status": actual, "state": dump_state(state)}
        self.scenarios.append(self.current)
        self.current = None


def assemble_paths(legacy_cases, partial_groups, recorder):
    """Intern cases, preserve old aliases, and build both directions of membership."""
    by_fingerprint, aliases, by_id = {}, {}, {}
    for case in [*legacy_cases, *recorder.cases]:
        fingerprint = identity(case)
        existing = by_fingerprint.get(fingerprint)
        if existing is None:
            existing = deepcopy(case)
            by_fingerprint[fingerprint] = existing
            by_id[existing["id"]] = existing
        else:
            existing["tags"] = sorted(
                set(existing.get("tags", [])) | set(case.get("tags", []))
            )
        aliases[case["id"]] = existing["id"]
    cases = list(by_id.values())
    index = {
        c["id"]: {
            "node": c["target"],
            "role": c["role"],
            "usages": [],
            "partial_usages": [],
            "aliases": [],
        }
        for c in cases
    }
    for old, canonical in aliases.items():
        if old != canonical:
            index[canonical]["aliases"].append(old)
    scenarios = deepcopy(recorder.scenarios)
    partials = deepcopy(partial_groups)
    for path in scenarios:
        for step in path["steps"]:
            step["case_id"] = aliases[step["case_id"]]
            index[step["case_id"]]["usages"].append(
                {"scenario_id": path["id"], "step_id": step["step_id"]}
            )
    for group in partials:
        group["scope"] = "partial_node_group"
        for number, step in enumerate(group["steps"], 1):
            step["old_case_id"] = step["case_id"]
            step["case_id"] = aliases[step["case_id"]]
            step["step_id"] = f"p{number:03d}"
            step.pop("next_case_ids", None)
            index[step["case_id"]]["partial_usages"].append(
                {"group_id": group["id"], "step_id": step["step_id"]}
            )
    for case in cases:
        counts = sorted(
            {
                len(s["model_outputs"])
                for p in scenarios
                for s in p["steps"]
                if s["case_id"] == case["id"]
            }
        )
        if counts:
            index[case["id"]]["model_call_counts"] = counts
            index[case["id"]]["model_call_count"] = (
                counts[0] if len(counts) == 1 else None
            )
        # Membership is authoritative in case_index; tags remain convenient filters.
        case["tags"] = sorted(
            {
                t
                for t in case.get("tags", [])
                if not t.startswith(("scenario:", "step:"))
            }
            | {"scenario:" + u["scenario_id"] for u in index[case["id"]]["usages"]}
            | {
                "partial-group:" + u["group_id"]
                for u in index[case["id"]]["partial_usages"]
            }
        )
    summary = {
        "complete_scenario_count": len(scenarios),
        "unique_node_case_count": len(cases),
        "path_node_execution_count": sum(len(p["steps"]) for p in scenarios),
        "preparation_node_execution_count": sum(
            len(p.get("entry_transition", {}).get("parent_steps", []))
            for p in scenarios
        ),
        "partial_group_count": len(partials),
        "partial_only_node_case_count": sum(not x["usages"] for x in index.values()),
        "shared_node_case_count": sum(len(x["usages"]) > 1 for x in index.values()),
        "runtime_only_node_case_count": sum(
            x.get("model_call_counts") == [0] for x in index.values()
        ),
        "path_runtime_only_execution_count": sum(
            not s["model_outputs"] for p in scenarios for s in p["steps"]
        ),
        "by_node": dict(Counter(c["target"] for c in cases)),
        "by_role": dict(Counter(c["role"] for c in cases)),
        "by_event": dict(Counter(c["initial"]["event"] for c in cases)),
        "scenarios_by_event": dict(Counter(p["event"] for p in scenarios)),
    }
    return cases, {
        "schema_version": "node-scenarios-v2",
        "summary": summary,
        "scenarios": scenarios,
        "partial_groups": partials,
        "case_index": index,
    }


def _validate_child_entry(check, parent, child, role, key):
    """Check the actual create_child_state boundary, after call consumption."""
    check(parent.get("role") == "request", "child_parent_role", key)
    check(parent.get("node") == "act", "child_parent_call", key)
    choices = parent.get("model_outputs", [])
    if len(choices) != 1:
        check(False, "child_parent_selection", key)
        return
    choice = choices[0]
    try:
        args = json.loads(choice["arguments_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        check(False, "child_parent_arguments", key)
        return
    before = parent["before_state"]
    check(
        choice.get("name") == role + "_agent"
        and isinstance(args, dict)
        and set(args) == {"goal"}
        and child["request"]["goal"] == args.get("goal"),
        "child_target_goal",
        key,
    )
    check(
        child["messages"] == before["messages"]
        and not child["results"]
        and child["response"] is None,
        "child_initial_state",
        key,
    )
    check(
        child["request"]["constraints"] == before["request"]["constraints"],
        "child_constraints",
        key,
    )
    inherited = deepcopy(before["execution"]["budget"])
    inherited["steps"]["used"] += 1
    inherited["agent_calls"]["used"] += 1
    check(child["execution"]["budget"] == inherited, "child_inherited_budget", key)
    for field in ("event", "version", "error"):
        check(
            child["execution"][field] == before["execution"][field],
            "child_inherited_" + field,
            key,
        )
    check(child["execution"]["status"] == "queued", "child_queued_entry", key)
    check(
        child["execution"]["run_id"] != before["execution"]["run_id"],
        "child_new_run_id",
        key,
    )


def _validate_child_return(check, parent, terminal, role, key, record_id=None):
    """The parent owns one call output and adopts the returned cumulative usage."""
    before, after = parent["before_state"], parent["after_state"]
    calls = [
        r
        for r in after["results"][len(before["results"]) :]
        if r["decision"] == "call"
        and (r.get("action") or {}).get("name") == role + "_agent"
    ]
    check(len(calls) == 1, "child_return_record", key)
    if len(calls) != 1:
        return
    call = calls[0]
    check(call["outcome"] == "success", "child_return_success", key)
    if record_id is not None:
        check(call["id"] == record_id, "child_return_record_id", key)
    check(
        call["output"]
        == {k: terminal[k] for k in ("response", "results", "execution")},
        "child_return_state",
        key,
    )
    choices = parent.get("model_outputs", [])
    if len(choices) == 1:
        selected = [
            r
            for r in after["results"][len(before["results"]) :]
            if r["decision"] == "selection"
        ]
        check(
            len(selected) == 1
            and all(
                (selected[0]["output"] or {}).get(k) == v for k, v in choices[0].items()
            ),
            "child_parent_selection_record",
            key,
        )
        try:
            arguments = json.loads(choices[0]["arguments_json"])
        except (KeyError, TypeError, json.JSONDecodeError):
            arguments = None
        check(
            call["action"]["arguments"] == arguments,
            "child_return_arguments",
            key,
        )
    check(
        after["execution"]["budget"] == terminal["execution"]["budget"],
        "child_return_budget",
        key,
    )
    check(
        after["messages"] == before["messages"]
        and after["request"] == before["request"]
        and after["response"] == before["response"],
        "child_return_parent_context",
        key,
    )
    for field in ("run_id", "event", "version"):
        check(
            after["execution"][field] == before["execution"][field],
            "child_return_parent_" + field,
            key,
        )


def _validate_agent_preparation(check, path):
    """Preparation runs request nodes but is outside the child evaluation path."""
    key = path["id"]
    entry = path.get("entry_transition", {})
    check(
        entry.get("kind") == "agent_call"
        and entry.get("parent_role") == "request"
        and entry.get("after_state") == path["start_state"],
        "agent_call_entry",
        key,
    )
    steps = entry.get("parent_steps", [])
    check(
        [s.get("node") for s in steps] == ["interpret", "decide", "act"],
        "parent_preparation_nodes",
        key,
    )
    if len(steps) != 3 or not entry.get("parent_start_state"):
        check(False, "parent_preparation_present", key)
        return
    check(
        len({s["step_id"] for s in steps}) == 3,
        "parent_preparation_unique_steps",
        key,
    )
    previous = None
    for step, node, target in zip(
        steps, ("interpret", "decide", "act"), ("decide", "act", "decide"), strict=True
    ):
        item_key = key + "/preparation/" + step["step_id"]
        before, after = step["before_state"], step["after_state"]
        check(
            not {"case_id", "input_ref", "expectation_ref"}.intersection(step),
            "parent_preparation_excludes_evaluation",
            item_key,
        )
        check(
            step.get("role") == "request" and step.get("frame") == "root",
            "parent_preparation_role",
            item_key,
        )
        check(
            before
            == (previous["after_state"] if previous else entry["parent_start_state"]),
            "parent_preparation_continuity",
            item_key,
        )
        check(
            step["boundary_before"]
            == {
                "kind": "next" if previous else "entry",
                "from_step": previous["step_id"] if previous else None,
            },
            "parent_preparation_boundary",
            item_key,
        )
        check(
            step["expected_next_nodes"] == [target],
            "parent_preparation_route",
            item_key,
        )
        check(
            after["results"][: len(before["results"])] == before["results"],
            "parent_preparation_history",
            item_key,
        )
        added = after["results"][len(before["results"]) :]
        check(
            all(r["node"] == node for r in added),
            "parent_preparation_record_ownership",
            item_key,
        )
        check(
            before["messages"] == after["messages"]
            and before["response"] == after["response"],
            "parent_preparation_context",
            item_key,
        )
        check(
            after["execution"]["status"] == "running",
            "parent_preparation_running",
            item_key,
        )
        for field in ("run_id", "event", "version", "error"):
            check(
                before["execution"][field] == after["execution"][field],
                "parent_preparation_" + field,
                item_key,
            )
        choices = step.get("model_outputs", [])
        check(len(choices) == 1, "parent_preparation_model_output", item_key)
        if node in {"interpret", "decide"} and len(choices) == 1:
            value = choices[0]
            decision = "interpretation" if node == "interpret" else "decision"
            check(
                len(added) == 1
                and added[0]["decision"] == decision
                and all(
                    (added[0]["output"] or {}).get(k) == v for k, v in value.items()
                ),
                "parent_preparation_model_record",
                item_key,
            )
            if node == "interpret":
                check(
                    after["request"] == value.get("request"),
                    "parent_preparation_request",
                    item_key,
                )
            else:
                check(
                    value.get("next") == "act", "parent_preparation_decision", item_key
                )
            budget = deepcopy(before["execution"]["budget"])
            budget["steps"]["used"] += 1
            check(
                after["execution"]["budget"] == budget,
                "parent_preparation_budget",
                item_key,
            )
        if node != "interpret":
            check(
                before["request"] == after["request"],
                "parent_preparation_request_scope",
                item_key,
            )
        previous = step
    parent = steps[-1]
    check(
        entry.get("call_step_id") == parent["step_id"],
        "parent_preparation_call_step",
        key,
    )
    check(
        bool(entry.get("parent_return_record_id")), "parent_preparation_return_id", key
    )
    _validate_child_entry(check, parent, path["start_state"], path["agent_role"], key)
    _validate_child_return(
        check,
        parent,
        path["terminal"]["state"],
        path["agent_role"],
        key,
        entry.get("parent_return_record_id"),
    )


def validate_paths(sidecar, cases):
    """Reject broken state continuity, missing calls/returns and ambiguous counts."""
    errors = []

    def check(ok, name, identity=""):
        if not ok:
            errors.append({"check": name, "identity": identity})

    by_id = {c["id"]: c for c in cases}
    index = sidecar["case_index"]
    usages, partial = {k: [] for k in by_id}, {k: [] for k in by_id}
    check(len(by_id) == len(cases), "unique_case_ids")
    for collection in ("scenarios", "partial_groups"):
        check(
            len({p["id"] for p in sidecar[collection]}) == len(sidecar[collection]),
            "unique_" + collection + "_ids",
        )
    fingerprints = [identity(c) for c in cases]
    check(len(set(fingerprints)) == len(cases), "duplicate_node_case")
    for path in sidecar["scenarios"]:
        steps = path["steps"]
        ids = {s["step_id"]: s for s in steps}
        check(len(ids) == len(steps), "unique_step_ids", path["id"])
        check(bool(steps), "nonempty_path", path["id"])
        boundaries = {b["id"]: b for b in path.get("boundaries", [])}
        check(
            len(boundaries) == len(path.get("boundaries", [])),
            "unique_boundary_ids",
            path["id"],
        )
        for event in boundaries.values():
            if event["kind"] == "report_handoff":
                check(
                    sum(
                        s["boundary_before"].get("boundary_id") == event["id"]
                        and s["boundary_before"]["kind"] == "report_handoff"
                        for s in steps
                    )
                    == 1,
                    "report_handoff_used_once",
                    path["id"] + "/" + event["id"],
                )
                check(
                    dump_state(report_stage_state(event["before_state"], event["role"]))
                    == event["after_state"],
                    "report_handoff_transition",
                    path["id"] + "/" + event["id"],
                )
            elif event["kind"] == "publish_report":
                check(
                    dump_state(published_report_state(event["before_state"]))
                    == event["after_state"],
                    "report_publish_transition",
                    path["id"] + "/" + event["id"],
                )
            else:
                check(False, "unknown_report_boundary", path["id"])
        if path.get("scope") == "agent":
            check(
                all(
                    s["role"] == path["agent_role"]
                    for s in steps
                    if s["frame"] == "root"
                ),
                "agent_role_boundary",
                path["id"],
            )
            check(not boundaries, "agent_boundary_excludes_workflow", path["id"])
            check(
                path["terminal"]["status"] == "completed",
                "basic_path_completed",
                path["id"],
            )
            if path["agent_role"] in {"interpretation", "visualization"}:
                _validate_agent_preparation(check, path)
            if path["event"] == "analysis_pipeline":
                entry = path.get("entry_transition", {})
                check(
                    entry.get("kind") == "report_handoff"
                    and entry.get("after_state") == path["start_state"],
                    "report_agent_entry",
                    path["id"],
                )
                if entry.get("before_state"):
                    check(
                        dump_state(
                            report_stage_state(
                                entry["before_state"], path["agent_role"]
                            )
                        )
                        == path["start_state"],
                        "report_agent_entry_transition",
                        path["id"],
                    )
                upstream_id = path.get("upstream_scenario_id")
                if upstream_id:
                    upstream = next(
                        (p for p in sidecar["scenarios"] if p["id"] == upstream_id),
                        None,
                    )
                    check(upstream is not None, "report_upstream_present", path["id"])
                    if upstream:
                        roles = {
                            "report_description": "report_selection",
                            "report_insight": "report_description",
                        }
                        check(
                            upstream["terminal"]["state"] == entry.get("before_state")
                            and upstream["agent_role"] == roles.get(path["agent_role"])
                            and upstream["region_code"] == path["region_code"],
                            "report_upstream_state",
                            path["id"],
                        )
                else:
                    check(
                        path["agent_role"] == "report_selection",
                        "report_upstream_required",
                        path["id"],
                    )
        elif path["event"] == "analysis_pipeline":
            check(
                [
                    b["role"]
                    for b in boundaries.values()
                    if b["kind"] == "report_handoff"
                ]
                == ["report_selection", "report_description", "report_insight"],
                "report_role_sequence",
                path["id"],
            )
            check(
                sum(b["kind"] == "publish_report" for b in boundaries.values()) == 1,
                "report_published_once",
                path["id"],
            )
        latest = {}
        for step in steps:
            key = step["case_id"]
            if key not in by_id:
                check(False, "missing_case", key)
                continue
            usages[key].append({"scenario_id": path["id"], "step_id": step["step_id"]})
            check(
                initial_input(step["before_state"]) == by_id[key]["initial"],
                "case_state_projection",
                key,
            )
            check(
                (step["node"], step["role"])
                == (by_id[key]["target"], by_id[key]["role"]),
                "case_node_role",
                key,
            )
            check(
                set(step["expected_next_nodes"]) <= set(DESTINATIONS[step["node"]]),
                "runtime_route",
                key,
            )
            boundary = step["boundary_before"]
            before = step["before_state"]
            after = step["after_state"]
            own_records = after["results"][len(before["results"]) :]
            child_entries = [
                s
                for s in steps
                if s["boundary_before"]["kind"] == "call"
                and s["boundary_before"].get("from_step") == step["step_id"]
            ]
            child_deltas = Counter()
            for child_entry in child_entries:
                child_steps = [s for s in steps if s["frame"] == child_entry["frame"]]
                child_before = child_entry["before_state"]["execution"]["budget"]
                child_after = child_steps[-1]["after_state"]["execution"]["budget"]
                child_deltas.update(
                    {
                        name: child_after[name]["used"] - value["used"]
                        for name, value in child_before.items()
                    }
                )
            if path.get("scope") == "agent":
                direct_calls = [r for r in own_records if r["decision"] == "call"]
                increments = {
                    "steps": 1,
                    "tool_calls": sum(
                        not (r.get("action") or {}).get("name", "").endswith("_agent")
                        for r in direct_calls
                    ),
                    "agent_calls": sum(
                        (r.get("action") or {}).get("name", "").endswith("_agent")
                        for r in direct_calls
                    ),
                    "retries": sum(r["decision"] == "retry" for r in own_records),
                }
                for name, usage in before["execution"]["budget"].items():
                    returned = after["execution"]["budget"][name]
                    check(
                        returned["limit"] == usage["limit"]
                        and returned["used"] >= usage["used"],
                        "budget_preserved",
                        key + "/" + name,
                    )
                    if name in increments:
                        check(
                            returned["used"]
                            == usage["used"] + increments[name] + child_deltas[name],
                            "budget_execution_count",
                            key + "/" + name,
                        )
                check(
                    all(r["outcome"] == "success" for r in own_records),
                    "basic_path_successful_records",
                    key,
                )
                check(
                    not any(
                        r["decision"] == "verification"
                        and (r.get("output") or {}).get("accepted") is False
                        for r in own_records
                    ),
                    "basic_path_approved_results",
                    key,
                )
            check(
                after["results"][: len(before["results"])] == before["results"],
                "history_prefix_preserved",
                key,
            )
            check(
                all(
                    r["node"] == step["node"]
                    for r in after["results"][len(before["results"]) :]
                ),
                "node_record_ownership",
                key,
            )
            if step["node"] != "interpret":
                check(before["request"] == after["request"], "request_write_scope", key)
            check(
                before["execution"]["event"]
                == after["execution"]["event"]
                == path["event"],
                "event_preserved",
                key,
            )
            previous = latest.get(step["frame"])
            if boundary["kind"] in {"next", "return"}:
                check(
                    previous is not None
                    and previous["step_id"] == boundary["from_step"],
                    "preceding_step",
                    key,
                )
                if previous:
                    check(before == previous["after_state"], "continuous_state", key)
                    check(previous["role"] == step["role"], "frame_role_preserved", key)
                    check(
                        step["node"] in previous["expected_next_nodes"],
                        "continuous_route",
                        key,
                    )
            elif boundary["kind"] == "entry":
                check(
                    previous is None and before == path["start_state"],
                    "initial_state",
                    key,
                )
                check(
                    step["node"]
                    == ("interpret" if path["event"] == "user_request" else "decide"),
                    "entry_node",
                    key,
                )
            elif boundary["kind"] == "report_handoff":
                event = boundaries.get(boundary.get("boundary_id"), {})
                expected_before = (
                    previous["after_state"] if previous else path["start_state"]
                )
                check(
                    event.get("before_state") == expected_before
                    and event.get("after_state") == before,
                    "report_state_handoff",
                    key,
                )
                check(
                    step["node"] == "decide" and event.get("role") == step["role"],
                    "report_entry",
                    key,
                )
                if previous:
                    check(
                        previous["expected_next_nodes"] == ["__end__"],
                        "report_previous_ended",
                        key,
                    )
            elif boundary["kind"] == "call":
                parent = ids.get(boundary.get("from_step"), {})
                check(
                    previous is None and step["frame"] != "root",
                    "child_frame_entry",
                    key,
                )
                check(parent.get("node") == "act", "child_parent_call", key)
                if parent:
                    _validate_child_entry(check, parent, before, step["role"], key)
                    check(
                        step["node"]
                        == (
                            "interpret" if path["event"] == "user_request" else "decide"
                        ),
                        "child_entry",
                        key,
                    )
            else:
                check(False, "unknown_boundary", key)
            latest[step["frame"]] = step
        for frame, last in latest.items():
            check(
                last["expected_next_nodes"] in [["__end__"], ["wait"]],
                "terminated_frame",
                path["id"] + "/" + frame,
            )
            if frame != "root":
                first = next(s for s in steps if s["frame"] == frame)
                parent = ids.get(first["boundary_before"].get("from_step"))
                check(
                    parent is not None, "child_parent_present", path["id"] + "/" + frame
                )
                if parent is None:
                    continue
                _validate_child_return(
                    check, parent, last["after_state"], first["role"], path["id"]
                )
        for parent in steps:
            if parent["node"] != "act" or not parent["model_outputs"]:
                continue
            choice = parent["model_outputs"][0]
            if not choice.get("name", "").endswith("_agent"):
                continue
            children = [
                s
                for s in steps
                if s["boundary_before"]["kind"] == "call"
                and s["boundary_before"].get("from_step") == parent["step_id"]
            ]
            calls = parent["after_state"]["results"][
                len(parent["before_state"]["results"]) :
            ]
            entered = any(
                r["decision"] == "call"
                and (r.get("action") or {}).get("name") == choice["name"]
                and isinstance(r.get("output"), dict)
                and "execution" in r["output"]
                for r in calls
            )
            check(
                len(children) == (1 if entered else 0),
                "delegated_child_path_present",
                path["id"] + "/" + parent["step_id"],
            )
        check("root" in latest, "root_frame_present", path["id"])
        if "root" in latest:
            expected = latest["root"]["after_state"]
            publishes = [
                b for b in boundaries.values() if b["kind"] == "publish_report"
            ]
            if publishes:
                check(
                    publishes[-1]["before_state"] == expected,
                    "publish_input",
                    path["id"],
                )
                expected = publishes[-1]["after_state"]
            check(expected == path["terminal"]["state"], "terminal_state", path["id"])
            check(
                path["terminal"]["status"] == expected["execution"]["status"],
                "terminal_status",
                path["id"],
            )
    for group in sidecar["partial_groups"]:
        check(
            len({s["step_id"] for s in group["steps"]}) == len(group["steps"]),
            "unique_partial_step_ids",
            group["id"],
        )
        for step in group["steps"]:
            if step["case_id"] in partial:
                partial[step["case_id"]].append(
                    {"group_id": group["id"], "step_id": step["step_id"]}
                )
            else:
                check(False, "missing_partial_case", step["case_id"])
    check(set(index) == set(by_id), "case_index_keys")
    for key, value in index.items():
        check(value["usages"] == usages.get(key), "reverse_path_usage", key)
        check(value["partial_usages"] == partial.get(key), "reverse_partial_usage", key)
        counts = sorted(
            {
                len(s["model_outputs"])
                for p in sidecar["scenarios"]
                for s in p["steps"]
                if s["case_id"] == key
            }
        )
        if counts:
            check(value.get("model_call_counts") == counts, "model_call_counts", key)
            check(
                value.get("model_call_count")
                == (counts[0] if len(counts) == 1 else None),
                "model_call_count",
                key,
            )
            families = {
                "family:" + p["family"]
                for p in sidecar["scenarios"]
                if any(s["case_id"] == key for s in p["steps"])
            }
            if key in by_id and not partial.get(key):
                check(
                    {t for t in by_id[key].get("tags", []) if t.startswith("family:")}
                    == families,
                    "case_family_membership",
                    key,
                )
    summary = sidecar["summary"]
    expected = {
        "complete_scenario_count": len(sidecar["scenarios"]),
        "unique_node_case_count": len(cases),
        "path_node_execution_count": sum(map(len, usages.values())),
        "preparation_node_execution_count": sum(
            len(p.get("entry_transition", {}).get("parent_steps", []))
            for p in sidecar["scenarios"]
        ),
        "partial_group_count": len(sidecar["partial_groups"]),
        "partial_only_node_case_count": sum(not u for u in usages.values()),
        "shared_node_case_count": sum(len(u) > 1 for u in usages.values()),
        "runtime_only_node_case_count": sum(
            bool(usages[c["id"]])
            and all(
                not s["model_outputs"]
                for p in sidecar["scenarios"]
                for s in p["steps"]
                if s["case_id"] == c["id"]
            )
            for c in cases
        ),
        "path_runtime_only_execution_count": sum(
            not s["model_outputs"] for p in sidecar["scenarios"] for s in p["steps"]
        ),
        "by_node": dict(Counter(c["target"] for c in cases)),
        "by_role": dict(Counter(c["role"] for c in cases)),
        "by_event": dict(Counter(c["initial"]["event"] for c in cases)),
        "scenarios_by_event": dict(Counter(p["event"] for p in sidecar["scenarios"])),
    }
    for key, value in expected.items():
        check(summary.get(key) == value, "summary_" + key)
    return errors
