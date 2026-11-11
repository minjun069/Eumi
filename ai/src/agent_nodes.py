"""Agent의 업무 판단과 수행을 담당하는 노드를 정의한다."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from langgraph.graph import END
from langgraph.types import Command
from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, with_config
from typing_extensions import TypedDict

from src.exceptions import DataFailureDetails, LimitReached, ToolFailure
from src.execution import (
    accepted_outputs,
    consume,
    finalizing,
    invoke_local_tool,
    invoke_model,
    invoke_work,
    record,
)
from src.execution_trace import trace_span
from src.gemini import structured_call
from src.graph import compile_graph
from src.prompting import (
    Role,
    ask_messages,
    compose_messages,
    decide_messages,
    interpret_messages,
    report_messages,
    selection_messages,
)
from src.prompting import compact as compact
from src.runtime import run_graph
from src.state import (
    Request,
    Text,
    ViewKey,
    create_child_state,
    report_input,
    report_row_adapter,
)
from src.tool_specs import selection_tools
from src.tools.interface import create_tools
from src.tools.render import render_visualization
from src.tools.tableau_catalog import registered_catalog


@with_config(ConfigDict(extra="forbid"))
class Interpretation(TypedDict):
    request: Request
    reason: str
    needs_input: bool


def selection_schema(definitions):
    """이번 호출에 제공하는 작업 목록으로 응답·원문 검증의 허용값을 맞춘다."""
    names = tuple(item["function"]["name"] for item in definitions) + ("none",)

    @with_config(ConfigDict(extra="forbid"))
    class Selection(TypedDict):
        name: Literal[names]
        arguments_json: Annotated[
            str,
            Field(
                description="선택한 도구 명세에 맞는 인자 객체를 "
                "JSON 문자열로 직렬화한다. "
                "none이면 {}."
            ),
        ]
        reason: str

    return Selection


@with_config(ConfigDict(extra="forbid"))
class Verification(TypedDict):
    accepted: bool
    reason: str


@with_config(ConfigDict(extra="forbid"))
class Decision(TypedDict):
    next: Literal["act", "compose", "ask"]
    reason: str


@with_config(ConfigDict(extra="forbid"))
class Composition(TypedDict):
    content: str
    artifact_ids: list[str]
    status: Literal["completed", "partial", "failed"]
    reason: str


@with_config(ConfigDict(extra="forbid"))
class Question(TypedDict):
    content: str
    reason: str


@with_config(ConfigDict(extra="forbid", strict=True))
class SelectedView(TypedDict):
    view_key: ViewKey
    reason: Text
    evidence_ids: Annotated[list[Text], Field(min_length=1)]


@with_config(ConfigDict(extra="forbid", strict=True))
class ReportSelection(TypedDict):
    views: Annotated[list[SelectedView], Field(max_length=3)]


@with_config(ConfigDict(extra="forbid", strict=True))
class ReportText(TypedDict):
    content: Text


@with_config(ConfigDict(extra="forbid", strict=True))
class ReportArguments(TypedDict):
    view_key: ViewKey | None
    result_ids: list[str]


report_arguments_adapter = TypeAdapter(ReportArguments)


def response(state, kind, content, artifacts=None):
    return {
        "id": str(uuid4()),
        "kind": kind,
        "label": kind,
        "content": content,
        "artifacts": deepcopy(
            artifacts
            if artifacts is not None
            else (state["response"] or {}).get("artifacts", [])
        ),
    }


def select_artifacts(state):
    ids = next(
        item["output"]["artifact_ids"]
        for item in reversed(state["results"])
        if item["decision"] == "composition"
    )
    available = accepted_outputs(state)
    artifacts = (
        deepcopy((state["response"] or {}).get("artifacts", []))
        if finalizing(state)
        else []
    )
    for selected in ids:
        if selected == "previous":
            items = (state["response"] or {}).get("artifacts", [])
        else:
            if selected not in available:
                raise ToolFailure("unverified_artifact")
            output = available[selected]
            if "response" in output:
                items = output["response"]["artifacts"]
            elif "artifact" in output:
                if output["artifact"] is None or output.get("valid") is False:
                    raise ToolFailure("unverified_artifact")
                items = [output["artifact"]]
                if "data" in output:
                    items.append(
                        {
                            "type": "data",
                            "data": {
                                "dataset": output["data"],
                                "spec": output["applied"],
                                "warnings": output["warnings"],
                            },
                        }
                    )
            elif "data" in output:
                table_input = {
                    "data": output["data"],
                    "spec": {
                        "type": "table",
                        "title": "비교 근거·사용 데이터",
                    },
                }
                items = [{"type": "data", "data": {"dataset": output["data"]}}]
                if not finalizing(state):
                    with trace_span(
                        "artifact", "render_comparison_table", table_input
                    ) as span:
                        table = invoke_local_tool(
                            state,
                            "compose",
                            "render_visualization",
                            table_input,
                            lambda table_input=table_input: render_visualization(
                                table_input
                            ),
                        )
                        if span:
                            span.update(output=table)
                    items[0]["data"]["spec"] = table["applied"]
                    items.insert(0, table["artifact"])
            else:
                raise ToolFailure("artifact_not_found")
        for item in items:
            if (
                item["type"] == "tableau"
                and item["data"].get("view_key") not in registered_catalog()["views"]
            ):
                raise ToolFailure("unknown_view")
            if item not in artifacts:
                artifacts.append(deepcopy(item))
    return artifacts


def finish(state):
    last = next(r for r in reversed(state["results"]) if r["decision"] == "composition")
    status = last["output"]["status"]
    return {
        "status": status,
        "error": None
        if status == "completed"
        else {
            "code": "incomplete",
            "cause": last["reason"],
        },
    }


def approved_report_selection(state):
    accepted = accepted_outputs(state)
    return next(
        (
            r
            for r in reversed(state["results"])
            if r["decision"] == "report_selection" and r["id"] in accepted
        ),
        None,
    )


def last_report_draft(state, view_key):
    return next(
        (
            r
            for r in reversed(state["results"])
            if r["decision"] == "report_draft"
            and r["action"]["arguments"]["view_key"] == view_key
        ),
        None,
    )


def report_review(state, item):
    return next(
        (
            r
            for r in reversed(state["results"])
            if r["decision"] == "verification"
            and (r["output"] or {}).get("call_id") == item["id"]
        ),
        None,
    )


def begin_report_call(state, decision, name, view_key, ids, reason):
    state["results"].append(
        record(
            "compose",
            decision,
            reason,
            action={
                "name": name,
                "arguments": report_arguments_adapter.validate_python(
                    {
                        "view_key": view_key,
                        "result_ids": ids,
                    }
                ),
            },
            success=False,
        )
    )


def check_report_text(reviewed, target):
    if target["decision"] != "report_draft":
        return
    lines = target["output"]["content"].strip().splitlines()
    view_key = target["action"]["arguments"]["view_key"]
    valid = (
        len(lines) == 1
        if view_key
        else (len(lines) in {3, 4} and all(line.strip() for line in lines))
    )
    if not valid:
        reviewed["output"]["accepted"] = False
        reviewed["output"]["reason"] += (
            " 설명은 한 단락이어야 한다."
            if view_key
            else " 줄바꿈으로 구분한 3~4개의 비어 있지 않은 문장이 필요하다."
        )
        reviewed["reason"] = reviewed["output"]["reason"]


def report_draft_target(state):
    selected = approved_report_selection(state)
    if not selected:
        return None
    accepted = accepted_outputs(state)
    for view in selected["output"]["views"]:
        draft = last_report_draft(state, view["view_key"])
        if draft and draft["id"] in accepted:
            continue
        if report_draft_exhausted(state, view["view_key"]):
            continue
        return view["view_key"], [selected["id"], *view["evidence_ids"]]
    descriptions = [
        last_report_draft(state, v["view_key"]) for v in selected["output"]["views"]
    ]
    descriptions = [r for r in descriptions if r and r["id"] in accepted]
    draft = last_report_draft(state, None)
    if (
        descriptions
        and not (draft and draft["id"] in accepted)
        and not report_draft_exhausted(state, None)
    ):
        return None, [selected["id"], *(r["id"] for r in descriptions)]
    return None


def report_draft_exhausted(state, view_key):
    # 네 번의 작성(최초 + 수정 3회)이 모두 검토된 항목만 소진이다.
    drafts = [
        r
        for r in state["results"]
        if r["decision"] == "report_draft"
        and r["action"]["arguments"]["view_key"] == view_key
        and r["outcome"] == "success"
    ]
    return len(drafts) >= 4 and report_review(state, drafts[-1]) is not None


def consume_report_retry(state, previous):
    previous_index = next(
        i for i, r in enumerate(state["results"]) if r["id"] == previous["id"]
    )
    # 실행 오류 재처리는 외부 실행 계층에서 이미 1회 집계했다.
    if not any(
        r["decision"] == "report_retry" for r in state["results"][previous_index + 1 :]
    ):
        consume(state, "retries")
    state["results"].append(
        record(
            "compose",
            "retry",
            "해당 작업 재처리",
            output={"call_id": previous["id"]},
        )
    )


def publish_report(state):
    inputs = report_input(state)
    source = next(
        r["output"] for r in state["results"] if r["decision"] == "report_source"
    )
    row = {
        "period_start": inputs["month"] + "-01",
        "adm_cd10": inputs["dongCode"],
        "result_updated_at": source["updated_at"],
        "generated_at": datetime.now(UTC).isoformat(),
        "quick_insight": None,
        **{f"{kind}_{n}": None for n in range(1, 4) for kind in ("graph", "desc")},
    }
    selected = approved_report_selection(state)
    accepted = accepted_outputs(state)
    if selected:
        for n, view in enumerate(selected["output"]["views"], 1):
            row[f"graph_{n}"] = view["view_key"]
            draft = last_report_draft(state, view["view_key"])
            if draft and draft["id"] in accepted:
                row[f"desc_{n}"] = draft["output"]["content"].strip()
        quick = last_report_draft(state, None)
        if quick and quick["id"] in accepted:
            row["quick_insight"] = quick["output"]["content"].strip()
    row = report_row_adapter.validate_python(row)
    filled = [
        row["quick_insight"],
        *(row[f"{k}_{n}"] for n in range(1, 4) for k in ("graph", "desc")),
    ]
    status = "completed" if all(filled) else "partial" if any(filled) else "failed"
    state["results"].append(
        record(
            "compose",
            "report_artifact",
            "검증된 항목과 NULL로 보고서 구성",
            output=row,
        )
    )
    state["results"].append(
        record(
            "compose",
            "composition",
            "검증된 항목만 공개",
            output={
                "content": "행정동 분석 보고서",
                "artifact_ids": [],
                "status": status,
                "reason": "완성하지 못한 항목은 NULL",
            },
        )
    )
    state["response"] = response(
        state,
        "final",
        "행정동 분석 보고서",
        [
            {"type": "analysis_report", "data": deepcopy(row)},
        ],
    )
    return status


def process_arguments(state, arguments):
    """선택 기록의 참조를 현재 State 자료로 연결한다. 원본·선택 인자는 유지한다."""
    actual = deepcopy(arguments)
    available = {
        key: output["data"]
        for key, output in accepted_outputs(state).items()
        if "data" in output
    }

    def resolve(target, reference_key, data_key):
        reference = target.pop(reference_key, None)
        if (
            not isinstance(reference, str)
            or reference not in available
            or data_key in target
        ):
            raise ToolFailure(
                "invalid_data_reference",
                details=DataFailureDetails(
                    requested=reference, available=list(available)
                ),
            )
        target[data_key] = available[reference]

    resolve(actual, "input_result_id", "data")
    # 나머지 형식 검사는 기존 process_adapter가 맡는다.
    operations = actual.get("operations")
    if isinstance(operations, list):
        for index, operation in enumerate(operations):
            if isinstance(operation, dict) and operation.get("operation") == "join":
                try:
                    resolve(operation, "right_result_id", "right")
                except ToolFailure as exc:
                    exc.details["operation_index"] = index
                    raise
    return actual


def build_nodes(
    model,
    providers,
    catalog,
    *,
    role: Role,
):
    async def call(state, schema, messages, config, *, strict=False):
        return await invoke_model(
            state,
            lambda: structured_call(model, schema, messages(), config, strict=strict),
        )

    async def call_report(state, config, schema, stage):
        """호출 인자는 이미 State에 기록되어 있다. 결과도 다음 호출 전에 반영한다."""
        item = state["results"][-1]
        try:
            value, usage = await call(
                state,
                schema,
                lambda: report_messages(state, stage, catalog),
                config,
            )
            item["output"] = value | {"model_usage": usage}
            item["outcome"] = "success"
            return item
        except Exception as exc:
            item["output"] = {"error_type": type(exc).__name__}
            item["outcome"] = "failure"
            raise

    async def verify_report(state, config, stage):
        target = state["results"][-1]
        begin_report_call(
            state,
            "verification",
            "review_report",
            target["action"]["arguments"]["view_key"],
            [target["id"]],
            "작성과 분리된 근거 대조",
        )
        reviewed = await call_report(
            state,
            config=config,
            schema=Verification,
            stage=stage,
        )
        reviewed["output"]["call_id"] = target["id"]
        reviewed["reason"] = reviewed["output"]["reason"]
        check_report_text(reviewed, target)
        return reviewed

    async def select_report_views(state, config):
        if approved_report_selection(state):
            return True
        previous = next(
            (
                r
                for r in reversed(state["results"])
                if r["decision"] == "report_selection"
            ),
            None,
        )
        if previous:
            consume_report_retry(state, previous)
        begin_report_call(
            state,
            "report_selection",
            "select_report_views",
            None,
            list(accepted_outputs(state)),
            "근거가 있는 상세 뷰 선정",
        )
        selection = await call_report(
            state,
            config=config,
            schema=ReportSelection,
            stage="selection",
        )
        available = accepted_outputs(state)
        views = selection["output"]["views"]
        invalid = len({v["view_key"] for v in views}) != len(views) or any(
            len(set(v["evidence_ids"])) != len(v["evidence_ids"])
            or any("data" not in available.get(ref, {}) for ref in v["evidence_ids"])
            for v in views
        )
        if invalid:
            state["results"].append(
                record(
                    "compose",
                    "verification",
                    "뷰 중복 또는 검증되지 않은 근거 참조",
                    output={
                        "call_id": selection["id"],
                        "accepted": False,
                        "reason": "서로 다른 뷰와 검증된 data 기록 ID가 필요하다.",
                    },
                )
            )
            return False
        checked = await verify_report(
            state,
            config=config,
            stage="selection_review",
        )
        return checked["output"]["accepted"]

    async def write_report(state, config):
        while (target := report_draft_target(state)) is not None:
            view_key, refs = target
            previous = last_report_draft(state, view_key)
            review = report_review(state, previous) if previous else None
            # 검토 호출만 실패한 경우 작성문은 보존하고 검토만 다시 한다.
            if previous and previous["outcome"] == "success" and review is None:
                begin_report_call(
                    state,
                    "verification",
                    "review_report",
                    view_key,
                    [previous["id"]],
                    "기존 초안의 검토 재실행",
                )
                checked = await call_report(
                    state,
                    config=config,
                    schema=Verification,
                    stage="review_retry",
                )
                checked["output"]["call_id"] = previous["id"]
                checked["reason"] = checked["output"]["reason"]
                check_report_text(checked, previous)
                continue
            if previous:
                consume_report_retry(state, previous)
                refs.append(previous["id"])
                if review:
                    refs.append(review["id"])
            begin_report_call(
                state,
                "report_draft",
                "write_report",
                view_key,
                refs,
                "보고서 문장 작성",
            )
            await call_report(
                state,
                config=config,
                schema=ReportText,
                stage="draft",
            )
            await verify_report(
                state,
                config=config,
                stage="draft_review",
            )

    async def compose_report(state, config):
        first = len(state["results"])
        if finalizing(state):
            publish_report(state)
        else:
            if not await select_report_views(state, config):
                return Command(
                    update={
                        "results": state["results"][first:],
                        "response": response(
                            state, "intermediate", "뷰 선정 근거를 보완합니다."
                        ),
                    },
                    goto="act",
                )
            await write_report(state, config)
            publish_report(state)
        return Command(
            update={
                "results": state["results"][first:],
                "response": state["response"],
            },
            goto=END,
        )

    async def interpret(state, config):
        value, usage = await call(
            state,
            Interpretation,
            lambda: interpret_messages(state, role),
            config,
        )
        return Command(
            update={
                "request": value["request"],
                "results": [
                    record(
                        "interpret",
                        "interpretation",
                        value["reason"],
                        output=value | {"model_usage": usage},
                    )
                ],
            },
            goto="decide" if value["needs_input"] else "act",
        )

    async def act(state, config):
        if role == "report" and approved_report_selection(state):
            return Command(update={"results": []}, goto="decide")
        tools = {t.name: t for t in create_tools(providers, state=state)}
        definitions = selection_tools(tools, role, state=state)
        # 노드 내부 판단도 같은 State 이력을 읽고, 반환할 때 새 기록만 전달한다.
        first_record = len(state["results"])
        choice, usage = await call(
            state,
            selection_schema(definitions),
            lambda: selection_messages(state, role, catalog, definitions=definitions),
            config,
            strict=True,
        )
        records = state["results"]
        records.append(
            record(
                "act",
                "selection",
                choice["reason"],
                output=choice | {"model_usage": usage},
            )
        )
        name = choice["name"]
        if name == "none":
            return Command(update={"results": records[first_record:]}, goto="decide")
        arguments = {}
        try:
            arguments = json.loads(choice["arguments_json"])
            if not isinstance(arguments, dict):
                arguments = {}
                raise ToolFailure("invalid_input")

            async def execute():
                # invoke_work가 호출 수를 소비한 뒤 이 State에서 하위 실행을 만든다.
                if name.endswith("_agent"):
                    if role != "request" or set(arguments) != {"goal"}:
                        raise ToolFailure("invalid_agent_call")
                    child_role = name.removesuffix("_agent")
                    child = create_child_state(
                        {
                            "goal": arguments["goal"],
                            "constraints": state["request"]["constraints"],
                        },
                        state,
                    )
                    graph = compile_graph(
                        build_nodes(model, providers, catalog, role=child_role),
                        finish=finish,
                    )
                    with trace_span(
                        "agent",
                        name,
                        {
                            "initial_state": child,
                            "catalog": catalog,
                            "role": child_role,
                        },
                    ) as span:
                        result = await run_graph(graph, child, config)
                        if span:
                            span.update(output=result)
                    return {k: result[k] for k in ("response", "results", "execution")}
                if (
                    role in {"interpretation", "report"}
                    and name == "validate_visualization"
                ):
                    raise ToolFailure("tool_not_allowed")
                actual = deepcopy(arguments)
                if name == "process_data":
                    actual = process_arguments(state, arguments)
                with trace_span(
                    "tool",
                    name,
                    {
                        "selected_arguments": arguments,
                        "resolved_arguments": actual,
                        "input_schema": tools[name].args_schema,
                    },
                ) as span:
                    output = await tools[name].ainvoke(actual, config)
                    if span:
                        span.update(output=output)
                return output

            invoked = await invoke_work(
                state, "act", name, arguments, choice["reason"], execute
            )
            output = invoked["output"]
            if name.endswith("_agent"):
                if finalizing(output):
                    limit_record = next(
                        r
                        for r in reversed(output["results"])
                        if r["decision"] == "limit_reached"
                    )["output"]
                    raise LimitReached(
                        limit_record["resource"],
                        used=limit_record["used"],
                        limit=limit_record["limit"],
                    )
            if name == "validate_visualization" and not output["valid"]:
                records.append(
                    record(
                        "act",
                        "verification",
                        "등록된 시각화 조건에 부적합",
                        output={
                            "accepted": False,
                            "call_id": invoked["id"],
                            "issues": output["issues"],
                        },
                    )
                )
                return Command(
                    update={"results": records[first_record:]}, goto="decide"
                )
        except (ToolFailure, ValidationError, json.JSONDecodeError) as exc:
            if any(
                r["decision"] == "call" and r["outcome"] == "failure"
                for r in records[first_record:]
            ):
                return Command(
                    update={"results": records[first_record:]}, goto="decide"
                )
            records.append(
                record(
                    "act",
                    "call_failed",
                    "호출 입력·결과 검증 실패",
                    action={"name": name, "arguments": arguments},
                    success=False,
                    output={
                        "code": getattr(exc, "code", "invalid_input"),
                        "details": getattr(exc, "details", {}),
                        "retryable": getattr(exc, "retryable", False),
                    },
                )
            )
        return Command(update={"results": records[first_record:]}, goto="decide")

    async def decide(state, config):
        if role == "report" and approved_report_selection(state):
            return Command(update={"results": []}, goto="compose")
        value, usage = await call(
            state, Decision, lambda: decide_messages(state, role, catalog), config
        )
        target = value["next"]
        if role != "request" and target == "ask":
            target = "compose"
        return Command(
            update={
                "results": [
                    record(
                        "decide",
                        "decision",
                        value["reason"],
                        output=value | {"model_usage": usage},
                    )
                ]
            },
            goto=target,
        )

    async def compose(state, config):
        if role == "report":
            return await compose_report(state, config)
        first_record = len(state["results"])
        value, usage = await call(
            state,
            Composition,
            lambda: compose_messages(state, role),
            config,
        )
        state["results"].append(
            record(
                "compose",
                "composition",
                value["reason"],
                output=value | {"model_usage": usage},
            )
        )
        with trace_span(
            "artifact",
            "select_artifacts",
            {
                "selected_ids": value["artifact_ids"],
                "available_results": accepted_outputs(state),
                "previous_response": state["response"],
            },
        ) as span:
            artifacts = select_artifacts(state)
            if span:
                span.update(output=artifacts)
        return Command(
            update={
                "results": state["results"][first_record:],
                "response": response(state, "final", value["content"], artifacts),
            },
            goto=END,
        )

    async def ask(state, config):
        value, usage = await call(
            state, Question, lambda: ask_messages(state, role), config
        )
        return Command(
            update={
                "results": [
                    record(
                        "ask",
                        "question",
                        value["reason"],
                        output=value | {"model_usage": usage},
                    )
                ],
                "response": response(state, "question", value["content"]),
            },
            goto="wait",
        )

    return {
        "interpret": interpret,
        "act": act,
        "decide": decide,
        "compose": compose,
        "ask": ask,
    }
