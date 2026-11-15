"""저장된 원본 추적을 노드별로 연결한다. 업무 상태를 복원하거나 변경하지 않는다."""

import json
from copy import deepcopy
from math import isfinite
from typing import Any, NotRequired

from typing_extensions import TypedDict

from eval.nodes.criteria import select_rows
from eval.nodes.schema import (
    CaseScopeEvidence,
    case_expectations,
    case_matches,
    expectation_matches,
    requested_checks,
)

NODES = {"interpret", "act", "decide", "compose", "ask"}
ROLES = {
    "request",
    "interpretation",
    "visualization",
    "report_selection",
    "report_description",
    "report_insight",
}
TECHNICAL_ERRORS = {
    "TimeoutError",
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionRefusedError",
    "APITimeoutError",
    "APIConnectionError",
    "RateLimitError",
    "InternalServerError",
    "CancelledError",
    "LimitReached",
    "RuntimeError",
    "OSError",
}
TECHNICAL_CODES = {
    "execution_limit_exceeded",
    "timeout",
    "connection_error",
    "connection_failed",
    "provider_timeout",
    "provider_unavailable",
    "service_unavailable",
}
CALL_KINDS = ("model", "tool", "agent")
# call_report의 작업 이름과 structured_call에 전달하는 실제 응답 형식 이름.
REPORT_MODELS = {
    "select_report_views": "ReportSelection",
    "write_report": "ReportText",
    "review_report": "Verification",
}


class RetryCounts(TypedDict):
    model: int | None
    tool: int | None
    agent: int | None


class TokenUsage(TypedDict):
    input_tokens: int | None
    output_tokens: int | None


class MissingTokenCalls(TypedDict):
    input_tokens: int | None
    output_tokens: int | None


class ObservedUsage(TypedDict):
    usage: TokenUsage
    usage_missing_calls: MissingTokenCalls
    model_calls: int | None
    technical_retries: int | None
    technical_retries_by_kind: RetryCounts


class ModelEvidence(TypedDict):
    id: str
    name: str
    messages: list
    response_schema: dict | None
    raw: str | None
    output: Any
    path: str
    error: dict | None
    complete: bool
    usage: dict[str, int | None]
    status: str
    elapsed_seconds: float | None
    issues: list[str]
    index: NotRequired[int]
    ended: bool
    connected: bool


class NodeEvidence(TypedDict):
    id: str
    run_id: str | None
    case_id: str
    repetition: int
    node: str
    role: str | None
    occurrence: int
    counted: bool
    state: dict
    calls: list[ModelEvidence]
    spans: list[dict]
    status: str
    error: dict | None
    elapsed_seconds: float | None
    issues: list[str]
    complete: bool
    technical_failure: bool | None
    usage: dict[str, int | None]
    model_calls: int | None
    technical_retries: int | None
    technical_retries_by_kind: RetryCounts
    unfinished: bool
    observed_usage: ObservedUsage | None
    paths: dict[str, str]


def _number(value):
    try:
        return type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError:
        return False


def _raw(response):
    if not isinstance(response, dict):
        return None
    if isinstance(response.get("text"), str):
        return response["text"]
    content = response.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            item["text"]
            for item in content
            if isinstance(item, dict)
            and isinstance(item.get("text"), str)
            and item.get("type") in {"text", "output_text"}
        ]
        return "".join(parts) if parts else None
    return None


def _constant(value):
    raise ValueError(f"유한하지 않은 JSON 값: {value}")


def _float(value):
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError(f"유한하지 않은 JSON 값: {value}")
    return parsed


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"중복된 JSON 키: {key}")
        result[key] = value
    return result


def _model(span, path):
    inputs = span.get("input") if isinstance(span.get("input"), dict) else {}
    output = span.get("output") if isinstance(span.get("output"), dict) else {}
    response = output.get("sdk_response")
    raw = _raw(response)
    issues = []
    error = deepcopy(span.get("error"))
    value = None
    if raw is not None:
        try:
            value = json.loads(
                raw,
                parse_constant=_constant,
                parse_float=_float,
                object_pairs_hook=_pairs,
            )
        except (ValueError, TypeError) as exc:
            error = {
                "type": "InvalidModelJSON",
                "message": str(exc),
                "trace_error": error,
            }
    else:
        issues.append("모델 원문 응답이 없습니다.")
    messages = inputs.get("messages")
    if not isinstance(messages, list):
        messages = []
        issues.append("실제 모델 입력 메시지가 없습니다.")
    metadata = response.get("usage_metadata") if isinstance(response, dict) else None
    tokens = {}
    for key in ("input_tokens", "output_tokens"):
        token = metadata.get(key) if isinstance(metadata, dict) else None
        tokens[key] = token if type(token) is int and token >= 0 else None
    return ModelEvidence(
        id=span["id"],
        name=str(span.get("name", "")),
        messages=deepcopy(messages),
        response_schema=deepcopy(inputs.get("response_schema")),
        raw=raw,
        output=value,
        path=path,
        error=error,
        complete=bool(span.get("ended_at")) and raw is not None,
        usage=tokens,
        status=str(span.get("status", "unknown")),
        elapsed_seconds=span.get("elapsed_seconds")
        if _number(span.get("elapsed_seconds"))
        else None,
        issues=issues,
        ended=bool(span.get("ended_at")),
        connected=True,
    )


def _prompt_role(calls):
    labels = {
        "행정동 보고서의 시각화 선정·근거 확보 역할이다.": "report_selection",
        "현재 역할은 시각화 설명 에이전트다.": "report_description",
        "현재 역할은 퀵 인사이트 에이전트다.": "report_insight",
        "현재 역할은 사용자 요청 처리 Agent다.": "request",
        "현재 역할은 데이터 분석 결과 해석 Agent다.": "interpretation",
        "현재 역할은 데이터 시각화 Agent다.": "visualization",
    }
    found = set()
    for call in calls:
        for message in call["messages"]:
            if not isinstance(message, dict) or message.get("type") != "system":
                continue
            text = message.get("content")
            if isinstance(text, str):
                found.update(role for phrase, role in labels.items() if phrase in text)
    return next(iter(found)) if len(found) == 1 else None


def _technical(error):
    if not isinstance(error, dict):
        return None
    if error.get("type", error.get("error_type")) in TECHNICAL_ERRORS:
        return True
    if error.get("code") in TECHNICAL_CODES:
        return True
    if error.get("type", error.get("error_type")) in {
        "ValidationError",
        "JSONDecodeError",
        "InvalidModelJSON",
    }:
        return False
    if error.get("code") in {"invalid_input", "invalid_data_reference"}:
        return False
    return _technical(error.get("cause"))


def _records(span):
    inputs = span.get("input", {})
    before = inputs.get("state", {}) if isinstance(inputs, dict) else {}
    output = span.get("output", {})
    applied = output.get("applied_update", {}) if isinstance(output, dict) else {}
    records = applied.get("results", [])
    old = {r.get("id") for r in before.get("results", []) if isinstance(r, dict)}
    return [r for r in records if isinstance(r, dict)], old, applied


def _failure(span, calls, intact):
    if not intact or not span.get("ended_at"):
        return None
    records, old, applied = _records(span)
    failed = [
        r
        for r in records
        if r.get("id") not in old and r.get("decision") == "execution_failed"
    ]
    error = (applied.get("execution") or {}).get("error")
    if isinstance(error, dict) and error.get("code") == "execution_limit_exceeded":
        return True
    if failed or span.get("status") == "error":
        values = []
        for call in calls:
            value = _technical(call.get("error"))
            # 원문이 없는 검증 오류를 내용 결함으로 확정하지 않는다.
            values.append(None if value is False and call["raw"] is None else value)
        reasons = [r.get("output") for r in failed] + [span.get("error")]
        values.extend(True for item in reasons if _technical(item) is True)
        if True in values:
            return True
        if False in values:
            return False
        return None
    return False if span.get("status") == "success" else None


def _retry_kind(record, owned):
    action = record.get("action") if isinstance(record, dict) else None
    name = action.get("name") if isinstance(action, dict) else None
    if not isinstance(name, str):
        return None
    kinds = {
        item["kind"]
        for item in owned
        if item.get("kind") in CALL_KINDS
        and (
            item.get("name") == name
            or (
                item["kind"] == "model"
                and name in REPORT_MODELS
                and item.get("name") == REPORT_MODELS.get(name)
            )
        )
    }
    return next(iter(kinds)) if len(kinds) == 1 else None


def _retries(span, intact, owned, *, observed=False) -> tuple[int | None, RetryCounts]:
    """이력으로 연결되고 실제 추가 호출까지 있는 기술적 재시도만 센다."""
    unknown: RetryCounts = dict.fromkeys(CALL_KINDS)
    if not intact or (not observed and not span.get("ended_at")):
        return None, unknown
    inputs = span.get("input")
    state = inputs.get("state") if isinstance(inputs, dict) else None
    if not isinstance(state, dict) or not isinstance(state.get("results"), list):
        return None, unknown
    output = span.get("output")
    if (
        not isinstance(output, dict)
        or not isinstance(output.get("applied_update"), dict)
        or not isinstance(output["applied_update"].get("results"), list)
    ):
        return None, unknown
    records, old, _ = _records(span)
    by_id = {r.get("id"): r for r in records}
    count = 0
    kinds: RetryCounts = dict.fromkeys(CALL_KINDS, 0)

    def add(record, technical):
        nonlocal count
        kind = _retry_kind(record, owned)
        if technical is None:
            count = None
        elif technical and count is not None:
            count += 1
        if technical is False:
            return
        affected = (kind,) if kind else CALL_KINDS
        for key in affected:
            if technical is None or kind is None:
                kinds[key] = None
            elif kinds[key] is not None:
                kinds[key] += 1

    for index, item in enumerate(records):
        if item.get("id") in old or item.get("decision") != "retry":
            continue
        previous = by_id.get((item.get("output") or {}).get("call_id"))
        if previous is None:
            add(None, None)
            continue
        if previous.get("outcome") == "success":
            continue  # 내용 부적합 뒤 재작성은 기술적 재시도가 아니다.
        technical = _technical(previous.get("output"))
        if technical is None:
            add(previous, None)
            continue
        following = next((r for r in records[index + 1 :] if r.get("action")), None)
        if following is None:
            add(previous, None)
            continue
        if technical and following.get("action") == previous.get("action"):
            add(following, True)
    # 검토 호출만 실패한 경우에는 retry 기록 없이 같은 검토를 다시 호출한다.
    for index, item in enumerate(records):
        if item.get("id") in old or item.get("decision") != "verification":
            continue
        action = item.get("action")
        if not action:
            continue  # 코드가 생성한 검증 기록은 모델 호출이 아니다.
        prior = next(
            (
                r
                for r in reversed(records[:index])
                if r.get("decision") == "verification" and r.get("action") == action
            ),
            None,
        )
        if prior and prior.get("outcome") == "failure":
            technical = _technical(prior.get("output"))
            add(item, technical)
    return count, kinds


def _observed_usage(span, calls, owned, connected) -> ObservedUsage:
    """미종료 시점까지 받은 토큰과 누락 호출 수를 최종 합계와 구분한다."""
    usage, missing = {}, {}
    for key in ("input_tokens", "output_tokens"):
        values = [call["usage"][key] for call in calls]
        measured = [value for value in values if value is not None]
        usage[key] = sum(measured) if connected and (measured or not calls) else None
        missing[key] = len(values) - len(measured) if connected else None
    retries, kinds = _retries(span, connected, owned, observed=True)
    return {
        "usage": usage,
        "usage_missing_calls": missing,
        "model_calls": len(calls) if connected else None,
        "technical_retries": retries,
        "technical_retries_by_kind": kinds,
    }


def extract_nodes(
    report: dict,
    case: dict,
    repetition: int = 1,
    *,
    catalog=None,
    scope: list[CaseScopeEvidence] | None = None,
    row_ids=None,
) -> list[NodeEvidence]:
    """노드와 직접 모델 호출을 원본 JSON 위치로 연결한다. 파손은 판정 증거로 남긴다."""
    run = report.get("run") if isinstance(report.get("run"), dict) else {}
    trace = report.get("trace") if isinstance(report.get("trace"), dict) else {}
    raw_spans = trace.get("spans")
    issues = []
    if not isinstance(raw_spans, list):
        raw_spans = []
        issues.append("실행 추적 목록이 없습니다.")
    indexed, paths, connection_issues = {}, {}, {}
    for index, span in enumerate(raw_spans):
        if (
            not isinstance(span, dict)
            or not isinstance(span.get("id"), str)
            or not span["id"]
        ):
            issues.append(f"/trace/spans/{index}: 유효한 추적 ID가 없습니다.")
            continue
        key = span["id"]
        if key in indexed:
            if indexed[key] != span:
                issues.append(f"{key}: 동일 추적 ID의 내용이 충돌합니다.")
                connection_issues.setdefault(key, []).append(issues[-1])
            continue
        indexed[key], paths[key] = span, f"/trace/spans/{index}"

    def ancestors(span):
        chain, seen = [], {span["id"]}
        parent = span.get("parent_id")
        while parent is not None:
            if not isinstance(parent, str) or parent not in indexed or parent in seen:
                issues.append(f"{span['id']}: 부모 추적이 없거나 순환합니다.")
                connection_issues.setdefault(span["id"], []).append(issues[-1])
                break
            seen.add(parent)
            chain.append(indexed[parent])
            parent = indexed[parent].get("parent_id")
        return chain

    chains = {key: ancestors(span) for key, span in indexed.items()}
    nodes = [
        s
        for s in indexed.values()
        if s.get("kind") == "node" and s.get("name") in NODES
    ]
    selection = case.get("unit") == "selection"
    if not selection:
        for key, span in indexed.items():
            if span.get("kind") == "model" and not any(
                p.get("kind") == "node" and p.get("name") in NODES for p in chains[key]
            ):
                issues.append(f"{key}: 모델 호출의 담당 노드를 찾을 수 없습니다.")
    if selection and not nodes:
        nodes = [
            next(
                (s for s in indexed.values() if s.get("kind") == "evaluation"),
                {
                    "id": f"missing:{run.get('id', case.get('id'))}:selection",
                    "name": "act",
                    "status": "unknown",
                    "input": {"state": case.get("initial", {})},
                },
            )
        ]
    elif not nodes and case.get("unit") == "node":
        nodes = [
            {
                "id": f"missing:{run.get('id', case.get('id'))}:{case['target']}",
                "name": case["target"],
                "status": "unknown",
                "input": {"state": case.get("initial", {})},
            }
        ]
        issues.append("예정한 노드의 실행 추적이 없습니다.")
    result, occurrences = [], {}
    for span in nodes:
        node_id = span["id"]
        node = "act" if selection else span["name"]
        owned = []
        for child in indexed.values():
            chain = chains[child["id"]]
            nearest = next(
                (
                    p
                    for p in chain
                    if p.get("kind") == "node" and p.get("name") in NODES
                ),
                None,
            )
            if (nearest and nearest["id"] == node_id) or (
                selection and not nearest and child.get("kind") == "model"
            ):
                owned.append(child)
        calls = [_model(s, paths[s["id"]]) for s in owned if s.get("kind") == "model"]
        for index, call in enumerate(calls, 1):
            call["index"] = index
            call["issues"].extend(
                issue
                for identity in (call["id"], node_id)
                for issue in connection_issues.get(identity, [])
            )
            call["connected"] = not any(
                connection_issues.get(identity) for identity in (call["id"], node_id)
            )
        inputs = span.get("input") if isinstance(span.get("input"), dict) else {}
        role = inputs.get("role") if inputs.get("role") in ROLES else None
        role = role or next(
            (
                p.get("input", {}).get("role")
                for p in chains.get(node_id, [])
                if p.get("kind") == "agent"
                and isinstance(p.get("input"), dict)
                and p["input"].get("role") in ROLES
            ),
            None,
        )
        if role is None:
            role = next(
                (
                    p.get("name", "").removesuffix("_agent")
                    for p in chains.get(node_id, [])
                    if p.get("kind") == "agent"
                    and p.get("name", "").removesuffix("_agent") in ROLES
                ),
                None,
            )
        if role is None:
            role = _prompt_role(calls)
        if role is None:
            role = run.get("role") or case.get("role")
            if case.get("unit") == "agent":
                role = case.get("target")
        if role not in ROLES:
            role = None
        key = node, role
        occurrences[key] = occurrences.get(key, 0) + 1
        local_issues = list(dict.fromkeys(issues))
        if role is None:
            local_issues.append("실행 역할을 식별할 수 없습니다.")
        if not span.get("ended_at"):
            local_issues.append("노드 호출의 종료 증거가 없습니다.")
        if any(not s.get("ended_at") for s in owned):
            local_issues.append("종료되지 않은 하위 추적이 있습니다.")
        output = span.get("output")
        applied = output.get("applied_update") if isinstance(output, dict) else None
        model_scope = inputs.get("evaluation_scope") == "model_output"
        if not selection and not model_scope:
            if not isinstance(applied, dict):
                local_issues.append("노드 결과를 반영한 상태 갱신이 없습니다.")
            elif not isinstance(applied.get("results"), list):
                local_issues.append("노드 결과의 작업 이력 목록이 없습니다.")
        state = inputs.get("state", inputs.get("initial_state", {}))
        if not isinstance(state, dict) or not (
            {"state", "initial_state"} & inputs.keys()
        ):
            state = {}
            if not model_scope:
                local_issues.append("노드 실행 당시 상태가 없습니다.")
        elif not model_scope and not isinstance(state.get("results"), list):
            local_issues.append("노드 입력의 작업 이력 목록이 없습니다.")
        intact = not local_issues
        unfinished = not span.get("ended_at") or any(
            not item.get("ended_at") for item in owned
        )
        retries, retry_kinds = _retries(span, intact, owned)
        usage = {
            key: sum(c["usage"][key] for c in calls)
            if intact and all(c["usage"][key] is not None for c in calls)
            else None
            for key in ("input_tokens", "output_tokens")
        }
        result.append(
            NodeEvidence(
                id=node_id,
                run_id=run.get("id"),
                case_id=case["id"],
                repetition=repetition,
                node=node,
                role=role,
                occurrence=occurrences[key],
                counted=not selection,
                state=deepcopy(state),
                calls=calls,
                spans=deepcopy(
                    [
                        s
                        for s in raw_spans
                        if isinstance(s, dict)
                        and s.get("id") in {node_id, *(o["id"] for o in owned)}
                    ]
                ),
                status=str(span.get("status", "unknown")),
                error=deepcopy(span.get("error")),
                elapsed_seconds=span.get("elapsed_seconds")
                if _number(span.get("elapsed_seconds"))
                else None,
                issues=local_issues,
                complete=intact,
                technical_failure=_failure(span, calls, intact),
                usage=usage,
                model_calls=len(calls) if intact else None,
                technical_retries=retries,
                technical_retries_by_kind=retry_kinds,
                unfinished=unfinished,
                observed_usage=_observed_usage(span, calls, owned, not issues)
                if unfinished
                else None,
                paths={
                    "node": paths.get(node_id, "/trace/spans"),
                    "state": paths.get(node_id, "/trace/spans") + "/input/state",
                },
            )
        )
    if scope is not None and case.get("unit") in {"node", "selection"}:
        # 판정 대상이 없어도 실제 첫 호출의 종류를 잃지 않도록 범위 근거만 보존한다.
        scope.extend(
            {
                key: deepcopy(node[key])
                for key in ("case_id", "repetition", "node", "role", "occurrence")
            }
            | {
                "calls": [
                    {key: call[key] for key in ("id", "name", "index", "path")}
                    for call in node["calls"]
                    if call["index"] == 1
                ]
            }
            for node in result
            if case_matches(case, node)
        )
    return (
        select_nodes(result, case, catalog, row_ids=row_ids)
        if catalog is not None
        else result
    )


def select_nodes(nodes, case, catalog, *, row_ids=None):
    """요청한 검사와 기대 범위의 원문만 남기고 원래 발생·호출 순서는 보존한다."""
    requested = requested_checks(case, nodes, row_ids=row_ids)
    items = case_expectations(case, nodes, row_ids=row_ids)
    selected = []
    for node in nodes:
        if not case_matches(case, node):
            continue
        scopes = []
        for identifier in requested:
            definition = catalog["checks"].get(identifier)
            if definition is None or node["node"] not in definition["nodes"]:
                continue
            check_items = [item for item in items if item["check"] == identifier]
            if not check_items:
                scopes.append((definition, {}))
            else:
                scopes.extend(
                    (definition, item)
                    for item in check_items
                    if expectation_matches(item, node)
                )
        if not scopes:
            continue
        original_calls = node["calls"]

        def selected_call(call, position, scopes=scopes, node=node):
            if not case_matches(case, node, call, position, nodes=nodes):
                return False
            for definition, item in scopes:
                if not expectation_matches(item, node, call, position):
                    continue
                selection = select_rows(definition, node, call, row_ids=row_ids)
                if (
                    any(
                        expectation_matches(
                            item, node, call, position, row_id=row["row_id"]
                        )
                        for row in selection["rows"]
                    )
                    or selection["missing_context"]
                    or (
                        row_ids is None
                        and "row_id" not in item
                        and (
                            "call" in item
                            or "call_index" in item
                            or item.get("applicable") is False
                        )
                    )
                ):
                    return True
            return False

        node["calls"] = [
            call
            for position, call in enumerate(node["calls"], 1)
            if selected_call(call, position)
        ]
        if (
            original_calls
            and not node["calls"]
            and (row_ids is not None or any("row_id" in item for _, item in scopes))
        ):
            continue
        if (
            case.get("unit") not in {"node", "selection"}
            and original_calls
            and not node["calls"]
            and not any("call" in item or "call_index" in item for _, item in scopes)
        ):
            continue
        _selected_usage(node, original_calls)
        selected.append(node)
    return selected


def _selected_usage(node, original_calls):
    """선택한 모델 경계의 운영 관측만 남긴다. 부모 노드의 후처리는 제외한다."""
    calls = node["calls"]
    connected = bool(calls) and all(call["connected"] for call in calls)
    ended = connected and all(call["ended"] for call in calls)
    failures = [
        False
        if call["raw"] is not None
        else True
        if _technical(call["error"]) is True
        else None
        for call in calls
    ]
    failure = (
        (True if True in failures else None if None in failures else False)
        if ended
        else None
    )
    finished = ended and failure is not None
    node["complete"] = finished
    node["unfinished"] = bool(calls) and any(not call["ended"] for call in calls)
    node["technical_failure"] = failure
    node["status"] = (
        "running"
        if node["unfinished"]
        else "error"
        if failure is True
        else "success"
        if finished
        else "unknown"
    )
    node["error"] = next(
        (call["error"] for call in calls if call["raw"] is None and call["error"]), None
    )
    elapsed = [call["elapsed_seconds"] for call in calls]
    node["elapsed_seconds"] = (
        sum(elapsed) if ended and all(value is not None for value in elapsed) else None
    )
    node["usage"] = {
        key: sum(call["usage"][key] for call in calls)
        if ended and all(call["usage"][key] is not None for call in calls)
        else None
        for key in ("input_tokens", "output_tokens")
    }
    node["model_calls"] = len(calls) if ended else None
    node_span = next(
        (span for span in node["spans"] if span.get("id") == node["id"]), {}
    )
    standalone = node_span.get("input", {}).get("evaluation_scope") == "model_output"
    retries = (
        (
            0
            if standalone and len(calls) == 1
            else node["technical_retries_by_kind"]["model"]
            if len(calls) == len(original_calls)
            else None
        )
        if ended
        else None
    )
    node["technical_retries"] = retries
    node["technical_retries_by_kind"] = {"model": retries, "tool": None, "agent": None}
    node["observed_usage"] = None
    if node["unfinished"]:
        node["observed_usage"] = {
            "usage": {},
            "usage_missing_calls": {},
            "model_calls": len(calls) if connected else None,
            "technical_retries": None,
            "technical_retries_by_kind": dict.fromkeys(CALL_KINDS),
        }
        for key in ("input_tokens", "output_tokens"):
            values = [call["usage"][key] for call in calls]
            measured = [value for value in values if value is not None]
            node["observed_usage"]["usage"][key] = (
                sum(measured) if connected and measured else None
            )
            node["observed_usage"]["usage_missing_calls"][key] = (
                len(values) - len(measured) if connected else None
            )
