"""저장된 실행 경계로 EX 규칙을 검사한다. 업무의 정답 생성 함수는 호출하지 않는다."""

from collections import Counter
from copy import deepcopy
from math import isclose
from typing import Literal

from langchain_core.messages import convert_to_messages
from langgraph.graph.message import add_messages
from pydantic_core import to_jsonable_python
from typing_extensions import TypedDict

from eval.execution.schema import COMMON_CHECKS, REPORT_CHECKS

Verdict = Literal["통과", "실패", "미판정", "비적용"]
ROLES = ("report_selection", "report_description", "report_insight")
FIELDS = ("request", "messages", "results", "response")
COUNTS = ("steps", "tool_calls", "agent_calls", "retries", "final_model_calls")


class ExecutionDetailResult(TypedDict):
    target: str
    verdict: Verdict
    executed: bool
    reason: str
    evidence: list[str]


class ExecutionCheckResult(TypedDict):
    check: str
    verdict: Verdict
    executed: bool
    complete: bool
    reason: str
    details: list[ExecutionDetailResult]


class ExecutionAssessment(TypedDict):
    case_id: str
    run_id: str | None
    repetition: int | None
    checks: list[ExecutionCheckResult]
    verdict: Verdict
    complete: bool
    started: bool
    report_completeness: Literal["complete", "partial", "none"] | None


def _detail(target, verdict, reason, *evidence) -> ExecutionDetailResult:
    return {
        "target": target,
        "verdict": verdict,
        "executed": verdict in {"통과", "실패"},
        "reason": reason,
        "evidence": list(evidence),
    }


def _compare(target, actual, expected, *evidence):
    equal = actual == expected
    return _detail(
        target,
        "통과" if equal else "실패",
        "원본과 일치합니다." if equal else "원본 또는 정해진 연결 조건과 다릅니다.",
        *evidence,
    )


def _aggregate(details):
    values = {item["verdict"] for item in details}
    verdict = (
        "실패"
        if "실패" in values
        else "미판정"
        if "미판정" in values or not values
        else "통과"
        if "통과" in values
        else "비적용"
    )
    return verdict, bool(details) and "미판정" not in values


def _state(value):
    return (
        value
        if isinstance(value, dict) and isinstance(value.get("execution"), dict)
        else None
    )


def _records(state):
    return (state or {}).get("results", [])


def _budget(state):
    return (state or {}).get("execution", {}).get("budget")


def _error(state):
    return (state or {}).get("execution", {}).get("error") or {}


def _limited(state):
    return _error(state).get("code") == "execution_limit_exceeded"


def _messages(value):
    return to_jsonable_python(convert_to_messages(deepcopy(value)))


def _merged(span):
    state = _state(span.get("input", {}).get("state"))
    update = (span.get("output") or {}).get("applied_update")
    if state is None or not isinstance(update, dict):
        return None
    merged = deepcopy(state) | deepcopy(update)
    if "messages" in update:
        merged["messages"] = to_jsonable_python(
            add_messages(
                deepcopy(state.get("messages", [])), deepcopy(update["messages"])
            )
        )
    return merged


def _path(span, suffix=""):
    return f"trace.spans[id={span.get('id')}]" + suffix


def _return_state(span):
    output = span.get("output")
    if not isinstance(output, dict):
        return None
    return _state(output) or _state(output.get("state"))


class _Evidence:
    def __init__(self, report):
        self.report = report or {}
        self.problems = []
        trace = self.report.get("trace")
        if not isinstance(trace, dict):
            trace = {}
            self.problems.append("추적 객체 없음")
        raw_spans = trace.get("spans")
        if not isinstance(raw_spans, list):
            raw_spans = []
            self.problems.append("호출 배열 없음")
        valid = []
        for span in raw_spans:
            if (
                not isinstance(span, dict)
                or not isinstance(span.get("id"), str)
                or not isinstance(span.get("kind"), str)
                or type(span.get("sequence")) not in {int, float}
                or not isinstance(span.get("input"), dict)
            ):
                self.problems.append("호출 경계 구조 오류")
                continue
            if span.get("status") == "unknown":
                self.problems.append("충돌한 호출 경계")
                # 충돌 값으로 통과·실패를 만들지 않는다.
                span = span | {"input": {}, "output": {}}
            valid.append(span)
        self.spans = sorted(
            valid,
            key=lambda span: span.get("sequence", 0),
        )
        identities = Counter(s["id"] for s in valid)
        if len(identities) != len(valid):
            self.problems.append("중복 호출 ID")
            self.spans = [
                s | {"input": {}, "output": {}, "status": "unknown"}
                if identities[s["id"]] > 1
                else s
                for s in self.spans
            ]
        counts = trace.get("counts")
        if not isinstance(counts, dict) or counts != dict(
            Counter(s.get("kind") for s in valid)
        ):
            self.problems.append("호출 개수 기록 불일치")
        coverage = trace.get("coverage")
        if isinstance(coverage, dict) and coverage.get("unfinished_spans") != sum(
            s.get("ended_at") is None for s in valid
        ):
            self.problems.append("미종료 호출 개수 불일치")
        if isinstance(coverage, dict):
            models = [s for s in valid if s.get("kind") == "model"]
            observed = {
                "model_attempts": len(models),
                "model_inputs": sum("messages" in s["input"] for s in models),
                "http_requests": sum("http_request" in s for s in models),
                "http_responses": sum("http_response" in s for s in models),
                "sdk_responses": sum("output" in s for s in models),
                "model_errors": sum(s.get("status") == "error" for s in models),
            }
            if any(coverage.get(name) != count for name, count in observed.items()):
                self.problems.append("모델 경계 수집 개수 불일치")
        self.by_id = {span.get("id"): span for span in self.spans}
        self.root = next(
            (span for span in self.spans if span.get("kind") == "execution"),
            next((s for s in self.spans if s.get("kind") == "evaluation"), None),
        )
        self.initial = (
            _state(self.root.get("input", {}).get("initial_state"))
            if self.root
            else None
        )
        self.final = _state(self.report.get("state"))
        self.nodes = [s for s in self.spans if s.get("kind") == "node"]
        self.roles = [
            s
            for s in self.spans
            if s.get("kind") == "agent" and s.get("input", {}).get("role") in ROLES
        ]
        self.groups = {}
        for node in self.nodes:
            scope = next(
                (
                    s
                    for s in self.ancestors(node)
                    if s.get("kind") in {"agent", "execution", "evaluation"}
                ),
                self.root,
            )
            identity = scope.get("id") if scope else None
            self.groups.setdefault(identity, []).append(node)

    def ancestors(self, span):
        seen = set()
        parent = span.get("parent_id")
        while parent in self.by_id and parent not in seen:
            seen.add(parent)
            item = self.by_id[parent]
            yield item
            parent = item.get("parent_id")

    def children(self, span, kind=None):
        return [
            item
            for item in self.spans
            if (kind is None or item.get("kind") == kind)
            and any(parent is span for parent in self.ancestors(item))
        ]

    def tainted(self):
        trace = self.report.get("trace")
        evidence = self.report.get("evidence")
        trace = trace if isinstance(trace, dict) else {}
        evidence = evidence if isinstance(evidence, dict) else {}
        issues = [trace.get("recovery_issues"), evidence.get("issues")]
        unknown = [s for s in self.spans if s.get("status") == "unknown"]
        return bool(
            any(issues) or self.problems or unknown or evidence.get("complete") is False
        )


def _fields(before, after, label, left, right, *, prefix=False):
    if before is None or after is None:
        return [_detail(label, "미판정", "경계 전후 상태가 없습니다.", left, right)]
    details = []
    for field in FIELDS:
        if field not in before or field not in after:
            details.append(
                _detail(
                    f"{label}.{field}",
                    "미판정",
                    "전달 필드 증거가 없습니다.",
                    left,
                    right,
                )
            )
            continue
        expected, actual = before[field], after[field]
        if field == "messages":
            expected, actual = _messages(expected), _messages(actual)
            for old, new in zip(expected, actual, strict=False):
                if old.get("id") is None:
                    # 최초 진입 때 reducer가 부여한 ID는 새로운 업무 내용이 아니다.
                    new["id"] = None
        if field == "results" and prefix:
            actual = actual[: len(expected)]
        details.append(
            _compare(
                f"{label}.{field}",
                actual,
                expected,
                f"{left}.{field}",
                f"{right}.{field}",
            )
        )
    old_execution, new_execution = before.get("execution"), after.get("execution")
    if isinstance(old_execution, dict) and isinstance(new_execution, dict):
        preserved = ("run_id", "event", "version")
        if not prefix:
            preserved += ("status", "error")
        for field in preserved:
            if field in old_execution and field in new_execution:
                details.append(
                    _compare(
                        f"{label}.execution.{field}",
                        new_execution[field],
                        old_execution[field],
                        f"{left}.execution.{field}",
                        f"{right}.execution.{field}",
                    )
                )
            else:
                details.append(
                    _detail(
                        f"{label}.execution.{field}",
                        "미판정",
                        "실행 정보의 경계 원본이 없습니다.",
                        left,
                        right,
                    )
                )
    return details


def _budgets(before, after, label, left, right, *, exact=True):
    old, new = _budget(before), _budget(after)
    if not isinstance(old, dict) or not isinstance(new, dict):
        return [_detail(label, "미판정", "공유 예산 원본이 없습니다.", left, right)]
    details = []
    for name in sorted(set(old) | set(new)):
        a, b = old.get(name), new.get(name)
        if not isinstance(a, dict) or not isinstance(b, dict):
            details.append(
                _detail(
                    f"{label}.{name}",
                    "실패",
                    "자원 예산이 누락됐습니다.",
                    left,
                    right,
                )
            )
            continue
        if any(
            type(value.get(key)) not in {int, float}
            for value in (a, b)
            for key in ("limit", "used")
        ):
            details.append(
                _detail(
                    f"{label}.{name}",
                    "미판정",
                    "예산 수치를 해석할 수 없습니다.",
                    left,
                    right,
                )
            )
            continue
        valid = a["limit"] == b["limit"] and (
            isclose(a["used"], b["used"], abs_tol=1e-8)
            if exact
            else b["used"] >= a["used"]
        )
        details.append(
            _detail(
                f"{label}.{name}",
                "통과" if valid else "실패",
                "공유 한도와 누적량을 유지했습니다."
                if valid
                else "공유 한도 또는 누적량을 변경·초기화·중복 반영했습니다.",
                left,
                right,
            )
        )
    return details


def _node_transitions(evidence, expected):
    details = []
    allowed = {
        "interpret": {"decide"},
        "act": {"decide"},
        "decide": {"act", "compose", "ask"},
        "compose": {"decide", "__end__"},
        "ask": {"wait"},
    }
    for scope_id, nodes in evidence.groups.items():
        scope = evidence.by_id.get(scope_id, {})
        initial = _state(scope.get("input", {}).get("initial_state"))
        first = nodes[0]
        event = (initial or {}).get("execution", {}).get("event")
        if event not in {"user_request", "analysis_pipeline"}:
            details.append(_detail(_path(first), "미판정", "시작 이벤트가 없습니다."))
        else:
            details.append(
                _compare(
                    _path(first, ".entry"),
                    first["name"],
                    "decide" if event == "analysis_pipeline" else "interpret",
                    _path(scope, ".input.initial_state.execution.event"),
                    _path(first),
                )
            )
        for index, node in enumerate(nodes):
            output = node.get("output") or {}
            after = _merged(node)
            actual = nodes[index + 1]["name"] if index + 1 < len(nodes) else "__end__"
            if node["name"] == "wait":
                waiting = (evidence.final or {}).get("execution", {}).get("status")
                valid = actual == "__end__" and waiting == "waiting_input"
                details.append(
                    _detail(
                        _path(node),
                        "통과" if valid else "미판정",
                        "질문을 반환해 이번 호출을 종료했습니다."
                        if valid
                        else "질문 반환 또는 종료 증거가 부족합니다.",
                        _path(node),
                        "state.execution",
                    )
                )
                continue
            if "goto" not in output or after is None:
                details.append(
                    _detail(
                        _path(node),
                        "미판정",
                        "노드의 반영 결과·경로가 없습니다.",
                        _path(node),
                    )
                )
                continue
            destination = output["goto"]
            forced = bool(_error(after)) and destination in {"compose", "__end__"}
            if not forced:
                if node["name"] == "decide":
                    records = (output.get("node_update") or {}).get("results", [])
                    decision = next(
                        (
                            r.get("output")
                            for r in reversed(records)
                            if r.get("decision") == "decision"
                        ),
                        None,
                    )
                    if not isinstance(decision, dict) or "next" not in decision:
                        details.append(
                            _detail(
                                _path(node, ".decision"),
                                "미판정",
                                "진행 판단의 반환 방향 원본이 없습니다.",
                                _path(node),
                            )
                        )
                    else:
                        direction = decision["next"]
                        role = scope.get("input", {}).get("role")
                        if role and role != "request" and direction == "ask":
                            direction = "compose"
                        details.append(
                            _compare(
                                _path(node, ".decision"),
                                destination,
                                direction,
                                _path(node, ".output.node_update.results"),
                                _path(node, ".output.goto"),
                            )
                        )
                details.append(
                    _detail(
                        _path(node, ".allowed"),
                        "통과"
                        if destination in allowed.get(node["name"], set())
                        else "실패",
                        "명세의 노드 전이를 대조했습니다.",
                        _path(node, ".output.goto"),
                    )
                )
                kind = (after.get("response") or {}).get("kind")
                if node["name"] in {"compose", "ask"}:
                    required = {
                        "final": "__end__",
                        "intermediate": "decide",
                        "question": "wait",
                    }
                    details.append(
                        _compare(
                            _path(node, ".response_kind"),
                            destination,
                            required.get(kind),
                            _path(node, ".output.applied_update.response"),
                        )
                    )
            if actual == "__end__" and destination != "__end__":
                if evidence.report.get("run", {}).get("status") in {
                    "cancelled",
                    "error",
                    "running",
                }:
                    details.append(
                        _detail(
                            _path(node, ".next"),
                            "비적용",
                            "강제 중단 이후의 진입은 EX-4에서 확인합니다.",
                            _path(node),
                        )
                    )
                    continue
            details.append(
                _compare(
                    _path(node, ".next"),
                    actual,
                    destination,
                    _path(node, ".output.goto"),
                    _path(nodes[index + 1])
                    if index + 1 < len(nodes)
                    else _path(scope, ".output"),
                )
            )
    if "node_path" in expected:
        visible = [
            s["name"]
            for s in evidence.nodes
            if s["name"] != "wait"
            and not any(
                p.get("kind") == "agent" and p not in evidence.roles
                for p in evidence.ancestors(s)
            )
        ]
        details.append(
            _compare(
                "expected.node_path",
                visible,
                expected["node_path"],
                "trace.spans",
            )
        )
    return details


def _node_delivery(evidence):
    details = []
    for scope_id, nodes in evidence.groups.items():
        scope = evidence.by_id.get(scope_id, {})
        before = _state(scope.get("input", {}).get("initial_state"))
        left = _path(scope, ".input.initial_state")
        for node in nodes:
            actual = _state(node.get("input", {}).get("state"))
            details.extend(
                _fields(
                    before,
                    actual,
                    _path(node),
                    left,
                    _path(node, ".input.state"),
                )
            )
            before, left = _merged(node), _path(node, ".output.applied_update")
        if nodes[-1]["name"] != "wait" and _return_state(scope) is not None:
            details.extend(
                _fields(
                    before,
                    _return_state(scope),
                    _path(scope, ".return"),
                    left,
                    _path(scope, ".output"),
                )
            )
    before, left = evidence.initial, _path(evidence.root or {}, ".input.initial_state")
    for role in evidence.roles:
        actual = _state(role.get("input", {}).get("initial_state"))
        details.extend(
            _fields(
                before,
                actual,
                _path(role, ".role_entry"),
                left,
                _path(role, ".input.initial_state"),
                prefix=True,
            )
        )
        if before is not None and actual is not None:
            additions = _records(actual)[len(_records(before)) :]
            valid = (
                len(additions) == 1 and additions[0].get("decision") == "report_stage"
            )
            details.append(
                _detail(
                    _path(role, ".stage_record"),
                    "통과" if valid else "실패",
                    "역할 전환에서 진입 기록만 추가했는지 확인했습니다.",
                    _path(role, ".input.initial_state.results"),
                )
            )
        before, left = _return_state(role), _path(role, ".output")
    if evidence.roles and before is not None and evidence.final is not None:
        after = evidence.final
        for field in ("request", "messages", "results"):
            expected = before.get(field)
            actual = after.get(field)
            if field == "results" and isinstance(actual, list):
                actual = actual[: len(expected)]
            if field == "messages":
                actual, expected = _messages(actual), _messages(expected)
            details.append(
                _compare(
                    f"report.assembly.{field}",
                    actual,
                    expected,
                    f"{left}.{field}",
                    f"state.{field}",
                )
            )
    return details


def _shared_budget(evidence, case):
    details = []
    supplied = case.get("initial", {})
    supplied_budget = supplied.get("budget") or supplied.get("execution", {}).get(
        "budget"
    )
    if supplied_budget is not None:
        details.extend(
            _budgets(
                {"execution": {"budget": supplied_budget}},
                evidence.initial,
                "reentry.supplied_budget",
                "case.initial",
                "execution.input.initial_state",
            )
        )
    for scope_id, nodes in evidence.groups.items():
        scope = evidence.by_id.get(scope_id, {})
        before = _state(scope.get("input", {}).get("initial_state"))
        left = _path(scope, ".input.initial_state.execution.budget")
        for node in nodes:
            entered = _state(node.get("input", {}).get("state"))
            details.extend(
                _budgets(
                    before,
                    entered,
                    _path(node, ".entry_budget"),
                    left,
                    _path(node, ".input.state.execution.budget"),
                )
            )
            after = _merged(node)
            if after is not None:
                details.extend(
                    _budgets(
                        entered,
                        after,
                        _path(node, ".cumulative"),
                        _path(node, ".input.state"),
                        _path(node, ".output.applied_update"),
                        exact=False,
                    )
                )
            elif node["name"] != "wait":
                details.append(
                    _detail(
                        _path(node),
                        "미판정",
                        "완료된 노드 예산이 없습니다.",
                        _path(node),
                    )
                )
            before, left = after, _path(node, ".output.applied_update.execution.budget")
        returned = _return_state(scope)
        if returned is not None and nodes[-1]["name"] != "wait":
            details.extend(
                _budgets(
                    before,
                    returned,
                    _path(scope, ".return_budget"),
                    left,
                    _path(scope, ".output.execution.budget"),
                )
            )
    before = evidence.initial
    for role in evidence.roles:
        entered = _state(role.get("input", {}).get("initial_state"))
        details.extend(
            _budgets(
                before,
                entered,
                _path(role, ".role_budget"),
                "previous_role.output.execution.budget",
                _path(role, ".input.initial_state.execution.budget"),
            )
        )
        before = _return_state(role)
    if evidence.roles and evidence.final is not None:
        details.extend(
            _budgets(
                before,
                evidence.final,
                "report.assembly_budget",
                _path(evidence.roles[-1], ".output.execution.budget"),
                "state.execution.budget",
            )
        )
    for child in (
        s
        for s in evidence.spans
        if s.get("kind") == "agent" and s not in evidence.roles
    ):
        parent = next(
            (s for s in evidence.ancestors(child) if s.get("kind") == "node"),
            None,
        )
        if parent is None:
            details.append(
                _detail(
                    _path(child),
                    "미판정",
                    "하위 호출의 상위 노드가 없습니다.",
                )
            )
            continue
        entered = _state(child.get("input", {}).get("initial_state"))
        parent_before = _state(parent.get("input", {}).get("state"))
        returned, parent_after = _return_state(child), _merged(parent)
        details.extend(
            _budgets(
                parent_before,
                entered,
                _path(child, ".shared"),
                _path(parent, ".input.state"),
                _path(child, ".input.initial_state"),
                exact=False,
            )
        )
        if all(
            _budget(value)
            for value in (
                entered,
                returned,
                parent_after,
                parent_before,
            )
        ):
            new_records = _records(parent_after)[len(_records(parent_before)) :]
            retries = sum(item.get("decision") == "retry" for item in new_records)
            for resource in COUNTS:
                increase = {
                    "steps": 1,
                    "agent_calls": 1,
                    "retries": retries,
                }.get(resource, 0)
                details.append(
                    _compare(
                        _path(child, f".entry.{resource}"),
                        _budget(entered)[resource]["used"],
                        _budget(parent_before)[resource]["used"] + increase,
                        _path(parent, ".input.state.execution.budget"),
                        _path(child, ".input.initial_state.execution.budget"),
                    )
                )
                details.append(
                    _compare(
                        _path(child, f".merge.{resource}"),
                        _budget(parent_after)[resource],
                        _budget(returned)[resource],
                        _path(child, ".output.execution.budget"),
                        _path(parent, ".output.applied_update.execution.budget"),
                    )
                )
        else:
            details.append(
                _detail(
                    _path(child, ".merge"),
                    "미판정",
                    "하위 누적 예산 반영의 원본이 부족합니다.",
                    _path(child),
                    _path(parent),
                )
            )
    if evidence.initial is not None and evidence.final is not None:
        details.extend(
            _budgets(
                evidence.initial,
                evidence.final,
                "run.budget",
                "execution.input.initial_state",
                "state",
                exact=False,
            )
        )
    return details


def _stop_path(evidence):
    details = []
    if evidence.root is None or evidence.initial is None:
        return [
            _detail(
                "stop",
                "미판정",
                "중단 조건을 확인할 실행 진입 증거가 없습니다.",
            )
        ]
    run_status = evidence.report.get("run", {}).get("status")
    stops = []
    if _limited(evidence.initial):
        stops.append((None, evidence.initial))
    for node in evidence.nodes:
        after = _merged(node)
        if (
            after
            and _error(after)
            and any(
                r.get("decision") in {"limit_reached", "execution_failed"}
                for r in _records(after)[
                    len(_records(node.get("input", {}).get("state"))) :
                ]
            )
        ):
            stops.append((node, after))
    if not stops and run_status not in {"cancelled", "error", "running"}:
        return [
            _detail(
                "stop",
                "비적용",
                "이번 실행의 한도·취소·미처리 오류가 없습니다.",
                "run.status",
            )
        ]
    if run_status == "running":
        details.append(
            _detail(
                "stop",
                "미판정",
                "관측 종료 시 실행이 끝나지 않았습니다.",
                "run.status",
            )
        )
    for stopped, state in stops:
        limited = _limited(state)
        scope = (
            next(
                (s for s in evidence.ancestors(stopped) if s.get("kind") == "agent"),
                None,
            )
            if stopped
            else None
        )
        handled_child = (
            scope is not None and scope not in evidence.roles and not limited
        )
        boundary = stopped.get("sequence", 0) if stopped else -1
        following = [
            s
            for s in evidence.nodes
            if s.get("sequence", 0) > boundary
            and (
                stopped is None or not any(p is stopped for p in evidence.ancestors(s))
            )
        ]
        if handled_child:
            following = [
                s
                for s in following
                if any(parent is scope for parent in evidence.ancestors(s))
            ]
            returned = _return_state(scope)
            if returned is None:
                details.append(
                    _detail(
                        _path(scope, ".stopped_return"),
                        "미판정",
                        "중단한 하위 호출의 반환 원본이 없습니다.",
                        _path(scope),
                    )
                )
            else:
                details.append(
                    _compare(
                        _path(scope, ".stop_error"),
                        _error(returned),
                        _error(state),
                        _path(stopped, ".output"),
                        _path(scope, ".output"),
                    )
                )
        for node in following:
            allowed = (
                limited
                and node["name"] == "compose"
                and _limited(node.get("input", {}).get("state"))
            )
            details.append(
                _detail(
                    _path(node, ".after_stop"),
                    "통과" if allowed else "실패",
                    "중단 이후 일반 노드 진입 여부를 확인했습니다.",
                    _path(node),
                )
            )
            if allowed:
                forbidden = [
                    s
                    for s in evidence.children(node)
                    if s.get("kind") in {"tool", "agent"}
                ]
                details.append(
                    _detail(
                        _path(node, ".final_tools"),
                        "실패" if forbidden else "통과",
                        "종료 응답의 도구·하위 실행·렌더링 여부를 확인했습니다.",
                        _path(node),
                    )
                )
        if limited:
            budget = _budget(evidence.final)
            if budget is None:
                details.append(
                    _detail(
                        "stop.final_budget",
                        "미판정",
                        "공유 종료 예산의 최종 기록이 없습니다.",
                    )
                )
            else:
                for name, cap in (
                    ("final_model_calls", 1),
                    ("final_active_seconds", 30),
                ):
                    usage = budget.get(name, {})
                    limit, used = usage.get("limit"), usage.get("used")
                    valid = limit == cap and type(used) in {int, float} and used <= cap
                    details.append(
                        _detail(
                            f"stop.{name}",
                            "통과" if valid else "실패",
                            "이전·하위 소비량을 포함한 종료 예산을 확인했습니다.",
                            "state.execution.budget",
                        )
                    )
    global_stops = [
        (node, state)
        for node, state in stops
        if node is None
        or _limited(state)
        or not any(
            s.get("kind") == "agent" and s not in evidence.roles
            for s in evidence.ancestors(node)
        )
    ]
    if global_stops:
        details.append(
            _compare(
                "stop.error",
                _error(evidence.final).get("code"),
                _error(global_stops[0][1]).get("code"),
                "state.execution.error",
            )
        )
        status = (evidence.final or {}).get("execution", {}).get("status")
        details.append(
            _detail(
                "stop.status",
                "통과" if status in {"partial", "failed", "cancelled"} else "실패",
                "중단 원인을 정상 완료로 바꾸지 않았는지 확인했습니다.",
                "state.execution.status",
            )
        )
    if any(_limited(state) for _, state in stops):
        final_nodes = [
            node
            for node in evidence.nodes
            if _limited(node.get("input", {}).get("state"))
        ]
        calls = {
            span["id"]: span
            for node in final_nodes
            for span in evidence.children(node, "model")
        }
        initial_budget = _budget(evidence.initial) or {}
        previous = initial_budget.get("final_model_calls", {}).get("used")
        if type(previous) in {int, float}:
            details.append(
                _detail(
                    "stop.model_attempts",
                    "통과" if previous + len(calls) <= 1 else "실패",
                    "이전 소비량을 포함한 실제 종료 모델 호출은 최대 1회입니다.",
                    "execution.input.initial_state.execution.budget",
                    "trace.spans",
                )
            )
            final_budget = _budget(evidence.final) or {}
            recorded = final_budget.get("final_model_calls", {}).get("used")
            details.append(
                _compare(
                    "stop.recorded_model_attempts",
                    recorded,
                    previous + len(calls),
                    "state.execution.budget.final_model_calls",
                    "trace.spans",
                )
            )
    if run_status in {"cancelled", "error"}:
        failed = [
            s
            for s in evidence.spans
            if s.get("kind") == "node" and s.get("status") in {"cancelled", "error"}
        ]
        if failed:
            first = failed[0]
            later = [
                s
                for s in evidence.nodes
                if s.get("sequence", 0) > first.get("sequence", 0)
                and s not in evidence.children(first)
            ]
            details.append(
                _detail(
                    "stop.exception",
                    "실패" if later else "통과",
                    "취소·미처리 오류 뒤 일반 노드 실행 여부를 확인했습니다.",
                    _path(first),
                    "run.status",
                )
            )
        else:
            details.append(
                _detail(
                    "stop.exception",
                    "미판정",
                    "오류·취소 발생 경계가 없어 후속 진입 차단을 확인할 수 없습니다.",
                    "run.status",
                )
            )
    return details


def _final_return(evidence, expected, report_workflow):
    details = []
    root = evidence.root or {}
    returned = _return_state(root)
    status = evidence.report.get("run", {}).get("status")
    if (
        root.get("status") != "success"
        or root.get("ended_at") is None
        or status != "returned"
    ):
        details.append(
            _detail(
                "return.boundary",
                "미판정",
                "호출자 반환 경계의 완료 기록이 없습니다.",
                _path(root),
                "run.status",
            )
        )
    if returned is None:
        details.append(
            _detail(
                "return",
                "미판정",
                "실제 호출자 반환 상태를 확보하지 못했습니다.",
                _path(root, ".output"),
                "run.status",
            )
        )
    else:
        details.extend(
            _fields(
                returned,
                evidence.final,
                "return",
                _path(root, ".output.state"),
                "state",
            )
        )
        details.append(
            _compare(
                "return.execution",
                (evidence.final or {}).get("execution"),
                returned.get("execution"),
                _path(root, ".output.state.execution"),
                "state.execution",
            )
        )
    if not report_workflow and evidence.root:
        nodes = evidence.groups.get(evidence.root["id"], [])
        nodes = [s for s in nodes if s["name"] != "wait"]
        if nodes and returned is not None:
            last = _merged(nodes[-1])
            details.extend(
                _fields(
                    last,
                    returned,
                    "final_node",
                    _path(nodes[-1], ".output.applied_update"),
                    _path(root, ".output.state"),
                )
            )
            if last:
                details.append(
                    _compare(
                        "final_node.execution",
                        returned.get("execution"),
                        last.get("execution"),
                        _path(nodes[-1]),
                        _path(root),
                    )
                )
    if report_workflow and returned is not None:
        artifacts = [
            r for r in _records(returned) if r.get("decision") == "report_artifact"
        ]
        actual = [
            a.get("data")
            for a in (returned.get("response") or {}).get("artifacts", [])
            if a.get("type") == "analysis_report"
        ]
        if artifacts:
            details.append(
                _compare(
                    "return.analysis_report",
                    actual,
                    [artifacts[-1].get("output")],
                    _path(root, ".output.state.results"),
                    "state.response.artifacts",
                )
            )
        else:
            details.append(
                _detail(
                    "return.analysis_report",
                    "미판정",
                    "보고서 조립 결과 원본이 없습니다.",
                )
            )
    if returned:
        kind = (returned.get("response") or {}).get("kind")
        execution_status = returned.get("execution", {}).get("status")
        if kind == "question":
            details.append(
                _compare(
                    "return.question",
                    execution_status,
                    "waiting_input",
                    _path(root),
                )
            )
            details.append(
                _compare(
                    "return.question_ended",
                    status,
                    "returned",
                    "run.status",
                )
            )
        if execution_status in {"queued", "running"} and status == "returned":
            details.append(
                _detail(
                    "return.terminal",
                    "실패",
                    "반환했지만 실행 상태가 종료되지 않았습니다.",
                    "state.execution.status",
                    "run.status",
                )
            )
    comparisons = {
        "run_status": status,
        "execution_status": (evidence.final or {}).get("execution", {}).get("status"),
        "response_kind": ((evidence.final or {}).get("response") or {}).get("kind"),
        "error_code": _error(evidence.final).get("code"),
    }
    for key, value in comparisons.items():
        if key in expected:
            details.append(
                _compare(
                    f"expected.{key}",
                    value,
                    expected[key],
                    "run",
                    "state",
                )
            )
    return details


def _role_name(span):
    return span.get("input", {}).get("role")


def _completed(state):
    return {
        (item.get("action") or {}).get("name", "").removesuffix("_agent")
        for item in _records(state)
        if item.get("decision") == "composition" and item.get("outcome") == "success"
    } & set(ROLES)


def _role_order(evidence, expected):
    details = []
    roles = [_role_name(role) for role in evidence.roles]
    prior = _completed(evidence.initial)
    previous_index, previous = -1, None
    first_pending = next((role for role in ROLES if role not in prior), None)
    for role in evidence.roles:
        name = _role_name(role)
        index = ROLES.index(name)
        valid = index > previous_index and name not in prior
        if previous_index == -1:
            valid = valid and name == first_pending
        if previous_index >= 0:
            valid = valid and index == previous_index + 1
        details.append(
            _detail(
                _path(role, ".order"),
                "통과" if valid else "실패",
                "선정→설명→인사이트 순서와 완료 역할 재호출 여부를 확인했습니다.",
                _path(role),
            )
        )
        if previous is not None:
            finished = _completed(_return_state(previous))
            details.append(
                _detail(
                    _path(role, ".predecessor"),
                    "통과" if ROLES[previous_index] in finished else "실패",
                    "앞 역할이 종료한 뒤 후속 역할에 진입했는지 확인했습니다.",
                    _path(previous, ".output"),
                    _path(role),
                )
            )
        previous_index, previous = index, role
    if not roles and len(prior) == len(ROLES):
        details.append(
            _detail(
                "roles",
                "통과",
                "이미 종료한 모든 역할을 보존했습니다.",
                "execution.input.initial_state.results",
            )
        )
    if evidence.roles and evidence.report.get("run", {}).get("status") == "returned":
        last = evidence.roles[-1]
        returned = _return_state(last)
        completed = _completed(returned)
        if _role_name(last) in completed and not _limited(returned):
            details.append(
                _detail(
                    "roles.continuation",
                    "통과" if set(ROLES) <= completed else "실패",
                    "종료한 역할 뒤 수행할 후속 역할을 빠뜨리지 않았는지 확인했습니다.",
                    _path(last, ".output.results"),
                    "trace.spans",
                )
            )
    if "role_path" in expected:
        details.append(
            _compare(
                "expected.role_path",
                roles,
                expected["role_path"],
                "trace.spans",
            )
        )
    return details


def _approved(state):
    """승인 참조를 읽는다. 업무의 승인 선택·보고서 생성 함수는 재사용하지 않는다."""
    records = _records(state)
    accepted = {
        (item.get("output") or {}).get("call_id")
        for item in records
        if item.get("decision") == "verification"
        and (item.get("output") or {}).get("accepted") is True
    }
    rejected = {
        (item.get("output") or {}).get("call_id")
        for item in records
        if item.get("decision") == "verification"
        and (item.get("output") or {}).get("accepted") is False
    }
    return {
        item["id"]: item
        for item in records
        if item.get("id") in accepted - rejected
        and item.get("outcome") == "success"
        and isinstance(item.get("output"), dict)
    }


def _report_identity(state):
    return next(
        (
            item.get("output")
            for item in _records(state)
            if item.get("decision") == "report_input"
        ),
        None,
    )


def _role_inputs(evidence):
    details = []
    identity = _report_identity(evidence.initial)
    previous = evidence.initial
    for role in evidence.roles:
        entered = _state(role.get("input", {}).get("initial_state"))
        if identity is None or entered is None:
            details.append(
                _detail(
                    _path(role),
                    "미판정",
                    "작성 진입 대상 또는 역할 입력이 없습니다.",
                )
            )
            previous = _return_state(role)
            continue
        details.append(
            _compare(
                _path(role, ".identity"),
                _report_identity(entered),
                identity,
                "execution.input.initial_state.results",
                _path(role, ".input.initial_state.results"),
            )
        )
        stage = next(
            (
                r
                for r in reversed(_records(entered))
                if r.get("decision") == "report_stage"
            ),
            None,
        )
        if stage is None or previous is None:
            details.append(
                _detail(
                    _path(role, ".references"),
                    "미판정",
                    "역할 진입 참조 또는 앞 역할 반환 원본이 없습니다.",
                )
            )
        else:
            details.append(
                _compare(
                    _path(role, ".stage_identity"),
                    (stage.get("action") or {}).get("name"),
                    _role_name(role) + "_agent",
                    _path(role, ".input.initial_state.results"),
                )
            )
            references = (
                (stage.get("action") or {})
                .get(
                    "arguments",
                    {},
                )
                .get("result_ids", [])
            )
            approved = _approved(previous)
            required = set(approved)
            for record in approved.values():
                for view in record.get("output", {}).get("views", []):
                    required.update(view.get("evidence_ids", []))
                # 초안의 수정 문맥(실패 초안·검토)은 이력으로 보존한다(EX-2).
                # 다음 역할의 승인 산출물 참조로 다시 지정할 대상은 아니다.
            allowed = required | {
                r.get("id")
                for r in _records(previous)
                if r.get("decision") in {"report_input", "report_source"}
                or (
                    r.get("decision") == "call"
                    and r.get("outcome") == "success"
                    and (r.get("output") or {}).get("valid") is not False
                )
            }
            valid = required <= set(references) <= allowed
            details.append(
                _detail(
                    _path(role, ".references"),
                    "통과" if valid else "실패",
                    "승인된 앞 역할 산출물·근거 참조의 누락·교체 여부를 확인했습니다.",
                    _path(role, ".input.initial_state.results"),
                )
            )
            entered_by_id = {r.get("id"): r for r in _records(entered)}
            original_by_id = {r.get("id"): r for r in _records(previous)}
            for identity_id in sorted(required):
                details.append(
                    _compare(
                        _path(role, f".reference[{identity_id}]"),
                        entered_by_id.get(identity_id),
                        original_by_id.get(identity_id),
                        _path(role, ".input.initial_state.results"),
                    )
                )
        previous = _return_state(role)
    return details


def _role_reentry(evidence):
    initial = evidence.initial
    if initial is None:
        return [
            _detail("reentry", "미판정", "재진입 여부를 확인할 초기 상태가 없습니다.")
        ]
    errors = [r for r in _records(initial) if r.get("decision") == "execution_failed"]
    if not errors and not _error(initial):
        return [
            _detail(
                "reentry",
                "비적용",
                "실행 오류가 기록된 상태로 재진입하지 않았습니다.",
            )
        ]
    if _limited(initial):
        return [
            _detail(
                "reentry",
                "비적용",
                "공유 한도 소진의 후속 경로는 EX-4에서 확인합니다.",
            )
        ]
    completed = _completed(initial)
    pending = next((role for role in ROLES if role not in completed), None)
    if pending is None:
        return [
            _compare(
                "reentry.role",
                [_role_name(s) for s in evidence.roles],
                [],
                "execution.input.initial_state.results",
                "trace.spans",
            )
        ]
    if not evidence.roles:
        return [
            _detail(
                "reentry.role",
                "미판정",
                "재진입한 역할의 실제 진입 증거가 없습니다.",
            )
        ]
    return [
        _compare(
            "reentry.role",
            _role_name(evidence.roles[0]),
            pending,
            "execution.input.initial_state.results",
            _path(evidence.roles[0]),
        )
    ]


def _report_row(state):
    response = (state or {}).get("response")
    if not isinstance(response, dict) or not isinstance(
        response.get("artifacts"), list
    ):
        return None
    rows = [
        a.get("data")
        for a in response["artifacts"]
        if isinstance(a, dict) and a.get("type") == "analysis_report"
    ]
    return rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else None


def _report_items(evidence):
    state = evidence.final
    row = _report_row(state)
    if row is None or state is None:
        return [
            _detail(
                "report.items",
                "미판정",
                "최종 보고서를 확보하지 못했습니다.",
                "state.response.artifacts",
            )
        ]
    # 역할 반환 원본이 최종 상태에서 변조돼도 동일한 값으로 정답을 만들지 않는다.
    source = _return_state(evidence.roles[-1]) if evidence.roles else evidence.initial
    source_path = (
        _path(evidence.roles[-1], ".output.results")
        if evidence.roles
        else _path(evidence.root or {}, ".input.initial_state.results")
    )
    if source is None:
        return [
            _detail(
                "report.items",
                "미판정",
                "보고서 조립 이전의 역할 반환 원본이 없습니다.",
            )
        ]
    approved = _approved(source)
    selected = next(
        (
            r
            for r in reversed(_records(source))
            if r.get("decision") == "report_selection" and r.get("id") in approved
        ),
        None,
    )
    views = (selected or {}).get("output", {}).get("views", [])
    details = []
    if len(views) > 3:
        details.append(
            _detail(
                "report.selection",
                "실패",
                "승인 선정이 최대 3개 범위를 초과합니다.",
                source_path,
            )
        )
    for number in range(1, 4):
        view = views[number - 1] if len(views) >= number else None
        key = view.get("view_key") if view else None
        draft = (
            next(
                (
                    r
                    for r in reversed(_records(source))
                    if r.get("decision") == "report_draft"
                    and (r.get("action") or {}).get("arguments", {}).get("view_key")
                    == key
                ),
                None,
            )
            if key
            else None
        )
        content = (
            draft["output"].get("content")
            if draft and draft.get("id") in approved
            else None
        )
        if isinstance(content, str):
            content = content.strip()
        for field, value in (
            (f"graph_{number}", key),
            (f"desc_{number}", content),
        ):
            details.append(
                _compare(
                    f"report.{field}",
                    row.get(field, "<missing>"),
                    value,
                    source_path,
                    f"state.response.artifacts.analysis_report.{field}",
                )
            )
    quick = next(
        (
            r
            for r in reversed(_records(source))
            if r.get("decision") == "report_draft"
            and (r.get("action") or {}).get("arguments", {}).get("view_key") is None
        ),
        None,
    )
    content = (
        quick["output"].get("content")
        if selected and quick and quick.get("id") in approved
        else None
    )
    if isinstance(content, str):
        content = content.strip()
    details.append(
        _compare(
            "report.quick_insight",
            row.get("quick_insight", "<missing>"),
            content,
            source_path,
            "state.response.artifacts.analysis_report.quick_insight",
        )
    )
    identity = _report_identity(evidence.initial)
    if identity:
        for key, value in (
            ("adm_cd10", identity.get("dongCode")),
            ("period_start", identity.get("month", "") + "-01"),
        ):
            details.append(
                _compare(
                    f"report.{key}",
                    row.get(key),
                    value,
                    "execution.input.initial_state.results",
                    "state.response.artifacts",
                )
            )
    return details


def _completeness(evidence):
    row = _report_row(evidence.final)
    fields = (
        "quick_insight",
        *(f"{kind}_{number}" for number in range(1, 4) for kind in ("graph", "desc")),
    )
    if row is None or any(field not in row for field in fields):
        return None
    filled = [
        isinstance(row[field], str) and bool(row[field].strip()) for field in fields
    ]
    return "complete" if all(filled) else "partial" if any(filled) else "none"


def _report_status(evidence, expected):
    complete = _completeness(evidence)
    if complete is None:
        return [
            _detail(
                "report.completeness",
                "미판정",
                "완성 범위를 확인할 항목이 없습니다.",
                "state.response.artifacts",
            )
        ]
    composition = next(
        (
            r
            for r in reversed(_records(evidence.final))
            if r.get("decision") == "composition" and not r.get("action")
        ),
        None,
    )
    if composition is None:
        details = [
            _detail(
                "report.completeness",
                "미판정",
                "보고서 조립 상태 기록이 없습니다.",
                "state.results",
            )
        ]
    else:
        details = [
            _compare(
                "report.completeness",
                (composition.get("output") or {}).get("status"),
                {"complete": "completed", "partial": "partial", "none": "failed"}[
                    complete
                ],
                "state.results.composition",
                "state.response.artifacts",
            )
        ]
    if "report_completeness" in expected:
        details.append(
            _compare(
                "expected.report_completeness",
                complete,
                expected["report_completeness"],
                "state.response.artifacts",
            )
        )
    return details


def assess_execution(
    case: dict,
    report: dict | None,
    *,
    checks: list[str] | None = None,
) -> ExecutionAssessment:
    """선언된 검사만 판정하며 실패와 미확인 경계를 함께 보존한다."""
    evidence = _Evidence(report)
    selected = list(
        dict.fromkeys(
            checks
            if checks is not None
            else case.get("assessment", {}).get("checks", []),
        )
    )
    expected = case.get("assessment", {}).get("expected", {})
    report_workflow = case.get("unit") == "workflow" and case.get("target") == "report"
    handlers = {
        "EX-1": lambda: _node_transitions(evidence, expected),
        "EX-2": lambda: _node_delivery(evidence),
        "EX-3": lambda: _shared_budget(evidence, case),
        "EX-4": lambda: _stop_path(evidence),
        "EX-5": lambda: _final_return(evidence, expected, report_workflow),
        "EX-R1": lambda: _role_order(evidence, expected),
        "EX-R2": lambda: _role_inputs(evidence),
        "EX-R3": lambda: _role_reentry(evidence),
        "EX-R4": lambda: _report_items(evidence),
        "EX-R5": lambda: _report_status(evidence, expected),
    }
    assessments = []
    for check in selected:
        if report is None:
            details = [_detail(check, "미판정", "예정 실행의 증거가 없습니다.")]
        elif check not in {*COMMON_CHECKS, *REPORT_CHECKS}:
            details = [_detail(check, "미판정", "지원하지 않는 실행 검사입니다.")]
        elif check in REPORT_CHECKS and not report_workflow:
            details = [_detail(check, "비적용", "동·월 보고서 작성에만 적용합니다.")]
        else:
            try:
                details = handlers[check]()
            except (AttributeError, KeyError, TypeError, ValueError, IndexError) as exc:
                details = [
                    _detail(
                        check,
                        "미판정",
                        f"경계 증거를 해석할 수 없습니다: {type(exc).__name__}",
                        "trace.spans",
                    )
                ]
            if not details:
                details = [
                    _detail(
                        check,
                        "미판정",
                        "적용 경계를 확인할 실행 증거가 없습니다.",
                    )
                ]
            if evidence.tainted():
                details.append(
                    _detail(
                        check + ".evidence",
                        "미판정",
                        "추적의 손상·충돌·누락으로 전체 경계를 확인하지 못했습니다.",
                        "evidence.issues",
                        "trace.recovery_issues",
                    )
                )
        verdict, complete = _aggregate(details)
        assessments.append(
            {
                "check": check,
                "verdict": verdict,
                "executed": any(d["executed"] for d in details),
                "complete": complete,
                "reason": "각 경계의 세부 판정과 증거를 참조합니다.",
                "details": details,
            }
        )
    verdict, complete = _aggregate(assessments)
    run = (report or {}).get("run", {})
    return {
        "case_id": case.get("id", ""),
        "run_id": run.get("id"),
        "repetition": run.get("repetition"),
        "checks": assessments,
        "verdict": verdict,
        "complete": complete and all(item["complete"] for item in assessments),
        "started": evidence.root is not None and evidence.initial is not None,
        "report_completeness": _completeness(evidence) if report_workflow else None,
    }
