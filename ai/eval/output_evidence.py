"""실제 최종 반환물과 채택된 작성 호출을 연결한다. 업무 상태는 바꾸지 않는다."""

import json
from collections import Counter
from copy import deepcopy
from typing import Any, Literal

from typing_extensions import TypedDict

from eval.nodes.evidence import NodeEvidence, extract_nodes
from src.agent_nodes import approved_report_selection, last_report_draft
from src.execution import accepted_outputs
from src.state import state_adapter

LinkStatus = Literal["matched", "mismatch", "missing"]
OutputKind = Literal[
    "response", "artifacts", "report_selection", "report_description", "report_insight"
]


class OutputConnection(TypedDict):
    id: str
    status: LinkStatus
    reason: str
    paths: list[str]


class OutputComponent(TypedDict):
    id: str
    role: str
    kind: OutputKind
    paths: list[str]
    value: Any
    result_id: str | None
    node: NodeEvidence | None
    link_status: LinkStatus
    issues: list[str]


class ExcludedCall(TypedDict):
    node_id: str
    call_id: str
    reason: str


class FinalOutputEvidence(TypedDict):
    status: Literal["returned", "not_returned", "unknown"]
    response: dict | None
    components: list[OutputComponent]
    nodes: list[NodeEvidence]
    excluded_calls: list[ExcludedCall]
    issues: list[str]
    connection_checks: list[OutputConnection]


def _value(record):
    output = record.get("output")
    if not isinstance(output, dict):
        return None
    return {key: value for key, value in output.items() if key != "model_usage"}


def _span(node):
    return next((span for span in node["spans"] if span["id"] == node["id"]), {})


def _new_records(node):
    previous = node["state"].get("results", [])
    output = _span(node).get("output")
    if not isinstance(previous, list) or not isinstance(output, dict):
        return []
    before = {
        record["id"]: record
        for record in previous
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }
    after = output.get("applied_update")
    if not isinstance(after, dict) or not isinstance(after.get("results"), list):
        return []
    return [
        record
        for record in after.get("results", [])
        if isinstance(record, dict)
        and isinstance(record.get("id"), str)
        and record != before.get(record["id"])
    ]


def _pending_record(call):
    """보고서 모델에 실제 전달한 마지막 작성 기록의 ID·역할 인자를 읽는다."""
    for message in reversed(call["messages"]):
        if not isinstance(message, dict):
            continue
        data = message.get("data", message)
        if not isinstance(data, dict) or not isinstance(data.get("content"), str):
            continue
        try:
            payload = json.loads(data["content"])
        except ValueError:
            continue
        records = payload.get("results") if isinstance(payload, dict) else None
        if isinstance(records, list) and records and isinstance(records[-1], dict):
            return records[-1]
    return {}


def _writer(record, role, nodes):
    """기록 ID의 작성 노드에서 실제 입력·원문이 일치하는 호출만 선택한다."""
    name = {
        "composition": "Composition",
        "report_selection": "ReportSelection",
        "report_draft": "ReportText",
    }[record["decision"]]
    owners = [
        node
        for node in nodes
        if node["node"] == "compose"
        and node["role"] == role
        and any(item.get("id") == record["id"] for item in _new_records(node))
    ]
    if len(owners) != 1:
        return None, "missing", "작성 기록의 원본 노드를 하나로 연결할 수 없습니다."
    node = owners[0]
    records = [
        item
        for item in _new_records(node)
        if item.get("decision") == record["decision"]
        and item.get("outcome") == "success"
    ]
    original = next((item for item in records if item.get("id") == record["id"]), None)
    if original != record:
        return None, "mismatch", "반환 상태의 작성 기록이 원본 노드 기록과 다릅니다."
    calls = [call for call in node["calls"] if call["name"] == name]
    call = None
    if name != "Composition":
        matching = [
            model
            for model in calls
            if model["output"] == _value(record)
            and all(
                _pending_record(model).get(key) == record[key]
                for key in ("id", "decision", "action")
            )
        ]
        if len(matching) == 1:
            call = matching[0]
    else:
        matching = [model for model in calls if model["output"] == _value(record)]
        same_records = [item for item in records if _value(item) == _value(record)]
        if len(matching) == len(same_records) == 1:
            call = matching[0]
    if call is None:
        return (
            None,
            "missing",
            "작성 기록과 같은 원문의 모델 호출을 특정할 수 없습니다.",
        )
    if (
        not node["complete"]
        or not call["complete"]
        or not call["connected"]
        or call["status"] != "success"
        or not call["messages"]
    ):
        return (
            None,
            "missing",
            "작성 호출의 종료·연결 또는 실제 입력 증거가 부족합니다.",
        )
    selected = deepcopy(node)
    selected["calls"] = [deepcopy(call)]
    return selected, "matched", "최종 채택 기록을 실제 작성 호출 원문에 연결했습니다."


def extract_output_evidence(
    report: dict | None, case: dict, repetition: int = 1
) -> FinalOutputEvidence:
    """반환 경계와 승인 결과를 대조하고 채택된 compose 호출만 품질 평가에 제공한다.

    연결 상태는 관측 정보다. 새 EX 검사나 내용 판정을 만들지 않는다. 원본이
    없거나 최종 내용과 다르면 그 호출의 판정을 최종 출력에 적용하지 않는다.
    """
    result = FinalOutputEvidence(
        status="unknown",
        response=None,
        components=[],
        nodes=[],
        excluded_calls=[],
        issues=[],
        connection_checks=[],
    )

    def connection(identity, status, reason, paths):
        result["connection_checks"].append(
            OutputConnection(id=identity, status=status, reason=reason, paths=paths)
        )
        if status != "matched":
            result["issues"].append(reason)

    if not report:
        connection("return", "missing", "실행 결과와 최종 반환 증거가 없습니다.", [])
        return result
    run = report.get("run") if isinstance(report.get("run"), dict) else {}
    if run.get("status") != "returned":
        result["status"] = "not_returned" if run.get("status") else "unknown"
        connection(
            "return", "missing", "호출자에게 반환하지 않은 실행입니다.", ["/run/status"]
        )
        return result
    trace = report.get("trace") if isinstance(report.get("trace"), dict) else {}
    spans = trace.get("spans", [])
    if not isinstance(spans, list):
        spans = []
    boundaries = [
        (index, span)
        for index, span in enumerate(spans)
        if isinstance(span, dict) and span.get("kind") == "execution"
    ]
    if len(boundaries) != 1:
        connection(
            "return",
            "missing",
            "최종 실행 반환 경계를 하나로 확인할 수 없습니다.",
            ["/trace/spans"],
        )
        return result
    boundary_index, boundary = boundaries[0]
    boundary_path = f"/trace/spans/{boundary_index}/output/state"
    output = boundary.get("output")
    returned = output.get("state") if isinstance(output, dict) else None
    if (
        boundary.get("status") != "success"
        or not boundary.get("ended_at")
        or not isinstance(returned, dict)
    ):
        connection(
            "return",
            "missing",
            "완료된 경계의 실제 반환 상태가 없습니다.",
            [boundary_path],
        )
        return result
    try:
        state_adapter.validate_python(returned)
    except ValueError:
        connection(
            "return",
            "missing",
            "최종 반환 상태의 형식을 확인할 수 없습니다.",
            [boundary_path],
        )
        return result
    if report.get("state") != returned:
        connection(
            "return",
            "mismatch",
            "저장된 최종 상태가 반환 경계의 상태와 다릅니다.",
            ["/state", boundary_path],
        )
        return result
    result["status"] = "returned"
    result["response"] = deepcopy(returned.get("response"))
    connection(
        "return",
        "matched",
        "실제 반환 상태와 저장된 최종 상태가 같습니다.",
        ["/state", boundary_path],
    )
    response = result["response"] or {}
    if response.get("kind") != "final":
        connection(
            "response",
            "missing",
            "compose의 최종 응답이 아닙니다. "
            "질문·진행 응답은 이 품질 대상에 포함하지 않습니다.",
            ["/state/response/kind"],
        )
        return result
    records = returned["results"]
    if any(count > 1 for count in Counter(item["id"] for item in records).values()):
        connection(
            "records",
            "missing",
            "최종 기록 ID가 중복되어 채택 원본을 특정할 수 없습니다.",
            ["/state/results"],
        )
        return result
    try:
        nodes = extract_nodes(report, case, repetition)
    except (KeyError, TypeError, ValueError, AttributeError):
        connection(
            "trace",
            "missing",
            "손상된 추적에서 작성 호출을 연결할 수 없습니다.",
            ["/trace/spans"],
        )
        return result
    source_paths = {
        record["id"]: f"/state/results/{index}" for index, record in enumerate(records)
    }

    def component(identity, role, kind, actual, expected, record, paths):
        node, status, reason = (
            None,
            "missing",
            "최종 출력에 연결할 승인된 작성 기록이 없습니다.",
        )
        if record is not None:
            node, status, reason = _writer(record, role, nodes)
            paths = [*paths, source_paths[record["id"]]]
        if actual != expected:
            node, status, reason = (
                None,
                "mismatch",
                "실제 반환 내용이 채택된 작성 결과와 다릅니다.",
            )
        issues = [] if status == "matched" else [reason]
        value = OutputComponent(
            id=identity,
            role=role,
            kind=kind,
            paths=paths,
            value=deepcopy(actual),
            result_id=record["id"] if record else None,
            node=node,
            link_status=status,
            issues=issues,
        )
        result["components"].append(value)
        connection(identity, status, reason, paths)
        return value

    target = case.get("target")
    workflow = case.get("unit") == "workflow" and target == "report"
    if not workflow and target in {"request", "interpretation", "visualization"}:
        record = next(
            (
                item
                for item in reversed(records)
                if item["decision"] == "composition"
                and item["action"] is None
                and item["outcome"] == "success"
            ),
            None,
        )
        selected = component(
            "response",
            target,
            "response",
            response.get("content"),
            ((record or {}).get("output") or {}).get("content"),
            record,
            ["/state/response/content"],
        )
        # 모델은 ID를 선택하며 실제 산출물은 compose 후처리에서 구성된다.
        node = selected["node"]
        if node:
            emitted = (
                (_span(node).get("output") or {}).get("applied_update") or {}
            ).get("response") or {}
            actual, expected = response.get("artifacts"), emitted.get("artifacts")
            status = "matched" if actual == expected else "mismatch"
            reason = (
                "compose가 반환한 공개 산출물이 최종 반환에 보존됐습니다."
                if status == "matched"
                else "최종 공개 산출물이 compose 반환물과 다릅니다."
            )
            paths = [
                "/state/response/artifacts",
                node["paths"]["node"] + "/output/applied_update/response/artifacts",
            ]
        else:
            actual, status, reason, paths = (
                response.get("artifacts"),
                "missing",
                "공개 산출물의 compose 반환 원본을 확인할 수 없습니다.",
                ["/state/response/artifacts"],
            )
        result["components"].append(
            OutputComponent(
                id="artifacts",
                role=target,
                kind="artifacts",
                paths=paths,
                value=deepcopy(actual),
                result_id=record["id"] if record else None,
                node=None,
                link_status=status,
                issues=[] if status == "matched" else [reason],
            )
        )
        connection("artifacts", status, reason, paths)
    elif workflow or target in {
        "report_selection",
        "report_description",
        "report_insight",
    }:
        try:
            _report_components(returned, workflow, target, component, connection)
        except (KeyError, TypeError, ValueError, AttributeError):
            connection(
                "report.records",
                "missing",
                "보고서 승인 기록과 반환 구성품의 연결 형식이 불완전합니다.",
                ["/state/results", "/state/response/artifacts"],
            )
            for part in result["components"]:
                part["node"] = None
                part["link_status"] = "missing"
                part["issues"].append("보고서 원본 기록 연결이 불완전합니다.")
    else:
        connection(
            "scope",
            "missing",
            "지원하는 에이전트·보고서 최종 출력이 아닙니다.",
            ["/run/target"],
        )

    selected_nodes = {}
    for part in result["components"]:
        if part["node"] is None or part["link_status"] != "matched":
            continue
        node = part["node"]
        if node["id"] not in selected_nodes:
            selected_nodes[node["id"]] = deepcopy(node)
        else:
            known = {call["id"] for call in selected_nodes[node["id"]]["calls"]}
            selected_nodes[node["id"]]["calls"].extend(
                deepcopy(call) for call in node["calls"] if call["id"] not in known
            )
    result["nodes"] = list(selected_nodes.values())
    for node in result["nodes"]:
        node["calls"].sort(key=lambda call: call["index"])
    selected_calls = {call["id"] for node in result["nodes"] for call in node["calls"]}
    result["excluded_calls"] = [
        ExcludedCall(
            node_id=node["id"],
            call_id=call["id"],
            reason="검토 호출은 최종 작성물이 아닙니다."
            if call["name"] == "Verification"
            else "최종 채택 내용에 연결되지 않은 작성·내부 호출입니다.",
        )
        for node in nodes
        if node["node"] == "compose"
        for call in node["calls"]
        if call["id"] not in selected_calls
    ]
    result["issues"] = list(dict.fromkeys(result["issues"]))
    return result


def _report_components(state, workflow, target, component, connection):
    accepted = accepted_outputs(state)
    selected = approved_report_selection(state)
    views = selected["output"]["views"] if selected else []
    response = state["response"]
    if workflow:
        reports = [
            (index, item)
            for index, item in enumerate(response["artifacts"])
            if item["type"] == "analysis_report"
        ]
        if len(reports) != 1:
            connection(
                "report",
                "missing",
                "최종 보고서 산출물을 하나로 확인할 수 없습니다.",
                ["/state/response/artifacts"],
            )
            return
        index, artifact = reports[0]
        row = artifact["data"]
        base = f"/state/response/artifacts/{index}/data"
        actual_views = [row.get(f"graph_{n}") for n in range(1, 4)]
        expected_views = [view["view_key"] for view in views]
        if any(value is not None for value in actual_views) or selected:
            component(
                "report.selection",
                "report_selection",
                "report_selection",
                actual_views,
                expected_views + [None] * (3 - len(expected_views)),
                selected,
                [f"{base}/graph_{n}" for n in range(1, 4)],
            )
        for number in range(1, 4):
            view = views[number - 1]["view_key"] if number <= len(views) else None
            draft = last_report_draft(state, view) if view else None
            draft = draft if draft and draft["id"] in accepted else None
            actual = row.get(f"desc_{number}")
            if actual is not None or draft:
                expected = draft["output"]["content"].strip() if draft else None
                component(
                    f"report.description.{number}",
                    "report_description",
                    "report_description",
                    {"view_key": row.get(f"graph_{number}"), "content": actual},
                    {"view_key": view, "content": expected},
                    draft,
                    [f"{base}/graph_{number}", f"{base}/desc_{number}"],
                )
        quick = last_report_draft(state, None)
        quick = quick if selected and quick and quick["id"] in accepted else None
        if row.get("quick_insight") is not None or quick:
            component(
                "report.insight",
                "report_insight",
                "report_insight",
                row.get("quick_insight"),
                quick["output"]["content"].strip() if quick else None,
                quick,
                [f"{base}/quick_insight"],
            )
        return
    if target == "report_selection":
        chosen = [selected] if selected else []
        expected = "\n".join(f"{view['view_key']}: {view['reason']}" for view in views)
    elif target == "report_description":
        chosen = [last_report_draft(state, view["view_key"]) for view in views]
        chosen = [draft for draft in chosen if draft and draft["id"] in accepted]
        expected = "\n".join(draft["output"]["content"] for draft in chosen)
    else:
        quick = last_report_draft(state, None)
        chosen = [quick] if quick and quick["id"] in accepted else []
        expected = "\n".join(draft["output"]["content"] for draft in chosen)
    expected = expected or "검증된 산출물이 없어 미완성으로 남깁니다."
    matched = response["content"] == expected
    connection(
        "report.response",
        "matched" if matched else "mismatch",
        "승인된 자기 산출물과 역할 반환 본문을 대조했습니다.",
        ["/state/response/content", "/state/results"],
    )
    for index, record in enumerate(chosen, 1):
        value = (
            record["output"]["views"]
            if target == "report_selection"
            else record["output"]["content"]
        )
        component(
            f"{target}.{index}",
            target,
            target,
            value if matched else response["content"],
            value,
            record,
            ["/state/response/content"],
        )
    if not chosen:
        connection(
            "report.content",
            "missing",
            "반환된 승인 작성물이 없어 compose 원문 품질을 판정할 수 없습니다.",
            ["/state/response/content"],
        )
