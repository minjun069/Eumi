"""Agent의 업무 판단과 수행을 담당하는 노드를 정의한다."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from langchain_core.messages import BaseMessage
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
from src.execution_trace import trace_acall, trace_call
from src.gemini import structured_call
from src.graph import compile_graph
from src.prompting import (
    REPORT_ROLES,
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
    ResultItem,
    State,
    Text,
    ViewKey,
    create_child_state,
    report_input,
    report_row_adapter,
    state_adapter,
)
from src.tool_specs import selection_tools
from src.tools.interface import create_tools
from src.tools.render import render_adapter, render_visualization
from src.tools.tableau_catalog import registered_catalog


@with_config(ConfigDict(extra="forbid"))
class Interpretation(TypedDict):
    request: Request
    reason: str


def selection_schema(definitions):
    """이번 호출에 제공하는 작업 목록으로 응답·원문 검증의 허용값을 맞춘다."""
    names = tuple(item["function"]["name"] for item in definitions)

    @with_config(ConfigDict(extra="forbid"))
    class Selection(TypedDict):
        name: Literal[names]
        arguments_json: Annotated[
            str,
            Field(
                description="선택한 도구 명세에 맞는 인자 객체를 "
                "JSON 문자열로 직렬화한다."
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


ReportStage = Literal[
    "selection", "selection_review", "draft", "draft_review", "review_retry"
]


class NoModelCall(ValueError):
    """현재 단계는 새 모델 응답 없이 서비스가 마무리하는 상태다."""


class ModelCall(TypedDict):
    schema: type
    messages: list[BaseMessage]
    strict: bool
    stage: ReportStage | None


class ReportCallPlan(TypedDict):
    stage: ReportStage
    decision: str
    name: str
    arguments: ReportArguments
    reason: str
    retry: ResultItem | None


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


def select_artifacts(state, *, renderer=None):
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
                    table = trace_call(
                        "artifact",
                        "render_comparison_table",
                        table_input,
                        lambda table_input=table_input: invoke_local_tool(
                            state,
                            "compose",
                            "render_visualization",
                            table_input,
                            lambda table_input=table_input: trace_call(
                                "tool",
                                "render_visualization",
                                {
                                    "selected_arguments": table_input,
                                    "resolved_arguments": table_input,
                                    "input_schema": render_adapter.json_schema(),
                                },
                                lambda: (renderer or render_visualization)(table_input),
                            ),
                        ),
                    )
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


def report_draft_target(state, role):
    selected = approved_report_selection(state)
    if not selected:
        return None
    accepted = accepted_outputs(state)
    if role == "report_description":
        for view in selected["output"]["views"]:
            draft = last_report_draft(state, view["view_key"])
            if draft and draft["id"] in accepted:
                continue
            if report_draft_exhausted(state, view["view_key"]):
                continue
            return view["view_key"], list(
                dict.fromkeys(
                    [
                        selected["id"],
                        *view["evidence_ids"],
                        *report_additional_evidence(state, role),
                    ]
                )
            )
        return None
    if role != "report_insight":
        return None
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
        return None, list(
            dict.fromkeys(
                [
                    selected["id"],
                    *(r["id"] for r in descriptions),
                    *report_additional_evidence(state, role),
                ]
            )
        )
    return None


def report_additional_evidence(state, role):
    """이번 역할에서 확보한 근거만 추가한다. 앞 단계의 근거 목록은 유지한다."""
    start = next(
        (
            i
            for i, item in enumerate(state["results"])
            if item["decision"] == "report_stage"
            and item["action"]["name"] == role + "_agent"
        ),
        0,
    )
    available = accepted_outputs(state)
    return [
        item["id"]
        for item in state["results"][start:]
        if item["id"] in available and "data" in available[item["id"]]
    ]


def complete_report_stage(state, role):
    """역할의 검증된 산출물만 반환한다. 보고서 조립·저장은 실행 흐름이 맡는다."""
    selected = approved_report_selection(state)
    accepted = accepted_outputs(state)
    views = selected["output"]["views"] if selected else []
    if role == "report_selection":
        contents = [f"{v['view_key']}: {v['reason']}" for v in views]
        complete = selected is not None and len(views) == 3
    elif role == "report_description":
        drafts = [last_report_draft(state, v["view_key"]) for v in views]
        contents = [r["output"]["content"] for r in drafts if r and r["id"] in accepted]
        complete = bool(views) and len(contents) == len(views)
    else:
        draft = last_report_draft(state, None)
        contents = (
            [draft["output"]["content"]] if draft and draft["id"] in accepted else []
        )
        complete = bool(contents)
    status = "completed" if complete else "partial"
    content = "\n".join(contents) or "검증된 산출물이 없어 미완성으로 남깁니다."
    reason = "검증된 자기 산출물만 반환하며 미완성 항목을 보존합니다."
    state["results"].append(
        record(
            "compose",
            "composition",
            reason,
            action={
                "name": role + "_agent",
                "arguments": {"view_key": None, "result_ids": list(accepted)},
            },
            output={
                "content": content,
                "artifact_ids": [],
                "status": status,
                "reason": reason,
            },
        )
    )
    state["response"] = response(state, "final", content)


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
    later = state["results"][previous_index + 1 :]
    retry_index = next(
        (i for i, r in enumerate(later) if r["decision"] == "report_retry"), None
    )
    # 검토 오류 재처리가 끝난 뒤의 내용 수정에는 외부 재처리 집계를 재사용하지 않는다.
    recovered = retry_index is not None and any(
        r["outcome"] == "success"
        and r["decision"] in {"verification", "retry"}
        and (r["output"] or {}).get("call_id") == previous["id"]
        for r in later[retry_index + 1 :]
    )
    if retry_index is None or recovered:
        consume(state, "retries")
    state["results"].append(
        record(
            "compose",
            "retry",
            "해당 작업 재처리",
            output={"call_id": previous["id"]},
        )
    )


def _report_call_plan(state: State, role: Role, stage=None) -> ReportCallPlan:
    """현재 기록만으로 다음 보고서 호출의 대상과 입력을 정한다."""
    if role not in REPORT_ROLES:
        raise ValueError("보고서 호출에는 보고서 역할이 필요합니다.")
    if finalizing(state):
        raise NoModelCall("종료 정리 단계에는 보고서 모델 호출이 없습니다.")
    previous = None
    view_key = None
    refs = []
    if role == "report_selection":
        if approved_report_selection(state):
            raise NoModelCall("선정이 이미 승인되어 새 모델 호출이 없습니다.")
        previous = next(
            (
                r
                for r in reversed(state["results"])
                if r["decision"] == "report_selection"
            ),
            None,
        )
        next_stage = (
            "selection_review"
            if previous
            and previous["outcome"] == "success"
            and not report_review(state, previous)
            else "selection"
        )
    else:
        target = report_draft_target(state, role)
        if target is None:
            selected = approved_report_selection(state)
            quick = last_report_draft(state, None)
            if selected and (
                role == "report_description"
                or not selected["output"]["views"]
                or (quick and quick["id"] in accepted_outputs(state))
                or report_draft_exhausted(state, None)
            ):
                raise NoModelCall("현재 역할에서 남은 보고서 모델 호출이 없습니다.")
            raise ValueError("현재 State에 작성·검토할 보고서 대상이 없습니다.")
        view_key, refs = target
        previous = last_report_draft(state, view_key)
        next_stage = (
            "review_retry"
            if previous
            and previous["outcome"] == "success"
            and not report_review(state, previous)
            else "draft"
        )
    stage = stage or next_stage
    if stage == "draft_review" and next_stage == "review_retry":
        pass  # 기존 초안의 최초 검토도 동일 대상에서 독립적으로 준비할 수 있다.
    elif stage != next_stage:
        raise ValueError("지정한 보고서 호출에 필요한 기존 대상이 준비되지 않았습니다.")
    if stage in {"selection_review", "draft_review", "review_retry"}:
        return {
            "stage": stage,
            "decision": "verification",
            "name": "review_report",
            "arguments": {"view_key": view_key, "result_ids": [previous["id"]]},
            "reason": (
                "기존 선정의 검토 재실행"
                if stage == "selection_review"
                else "기존 초안의 검토 재실행"
                if stage == "review_retry"
                else "작성과 분리된 근거 대조"
            ),
            "retry": None,
        }
    if stage == "selection":
        refs = list(accepted_outputs(state))
    elif previous:
        refs.append(previous["id"])
        review = report_review(state, previous)
        if review:
            refs.append(review["id"])
    return {
        "stage": stage,
        "decision": "report_selection" if stage == "selection" else "report_draft",
        "name": "select_report_views" if stage == "selection" else "write_report",
        "arguments": {"view_key": view_key, "result_ids": refs},
        "reason": "근거가 있는 상세 뷰 선정"
        if stage == "selection"
        else "보고서 문장 작성",
        "retry": previous,
    }


def _begin_planned_report_call(state: State, plan: ReportCallPlan):
    if plan["retry"]:
        consume_report_retry(state, plan["retry"])
    begin_report_call(
        state,
        plan["decision"],
        plan["name"],
        plan["arguments"]["view_key"],
        plan["arguments"]["result_ids"],
        plan["reason"],
    )


def _pending_report_stage(state: State, role: Role, stage) -> ReportStage | None:
    if not state["results"]:
        return None
    item = state["results"][-1]
    if (
        item["node"] != "compose"
        or item["outcome"] != "failure"
        or item["output"] is not None
    ):
        return None
    action = item["action"] or {}
    if action.get("name") not in {
        "select_report_views",
        "write_report",
        "review_report",
    }:
        return None
    args = report_arguments_adapter.validate_python(action.get("arguments"))
    if (
        action["name"] == "select_report_views"
        and item["decision"] == "report_selection"
    ):
        actual = "selection"
    elif action["name"] == "write_report" and item["decision"] == "report_draft":
        actual = "draft"
    elif action["name"] == "review_report" and item["decision"] == "verification":
        targets = [r for r in state["results"][:-1] if r["id"] in args["result_ids"]]
        if len(targets) != 1 or targets[0]["outcome"] != "success":
            raise ValueError("보고서 검토에 필요한 기존 성공 기록이 없습니다.")
        target = targets[0]
        if target["action"]["arguments"]["view_key"] != args["view_key"]:
            raise ValueError("보고서 검토 대상과 view_key가 다릅니다.")
        if target["decision"] == "report_selection":
            actual = "selection_review"
        elif target["decision"] == "report_draft":
            actual = (
                "review_retry"
                if item["reason"] == "기존 초안의 검토 재실행"
                else "draft_review"
            )
        else:
            raise ValueError("보고서 검토 대상은 기존 선정 또는 초안이어야 합니다.")
    else:
        raise ValueError("보고서 호출 기록의 작업과 판단이 일치하지 않습니다.")
    if stage and stage != actual:
        raise ValueError("준비된 보고서 호출과 지정한 호출 단계가 다릅니다.")
    if (actual in {"selection", "selection_review"}) != (role == "report_selection"):
        raise ValueError("보고서 호출 단계와 역할이 다릅니다.")
    if role == "report_description" and args["view_key"] is None:
        raise ValueError("설명 작성·검토에는 기존 뷰 대상이 필요합니다.")
    if role == "report_insight" and args["view_key"] is not None:
        raise ValueError("인사이트 작성·검토는 전체 보고서를 대상으로 합니다.")
    return actual


def prepare_report_call(
    state: State, role: Role, stage: ReportStage | None = None
) -> tuple[State, ReportStage]:
    """원본을 바꾸지 않고 기존 기록에서 보고서 모델 입력 한 건을 준비한다."""
    if role not in REPORT_ROLES:
        raise ValueError("보고서 호출에는 보고서 역할이 필요합니다.")
    if finalizing(state):
        raise NoModelCall("종료 정리 단계에는 보고서 모델 호출이 없습니다.")
    prepared = deepcopy(state)
    pending = _pending_report_stage(prepared, role, stage)
    if pending:
        return prepared, pending
    plan = _report_call_plan(prepared, role, stage)
    _begin_planned_report_call(prepared, plan)
    return prepared, plan["stage"]


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


def prepare_model_call(
    node: str,
    state: State,
    *,
    role: Role,
    catalog=None,
    tools=None,
    report_stage: ReportStage | None = None,
    definitions=None,
) -> ModelCall:
    """서비스가 사용하는 응답 명세와 실제 메시지만 구성한다. 모델은 호출하지 않는다."""
    stage = None
    if report_stage is not None and (node != "compose" or role not in REPORT_ROLES):
        raise ValueError("보고서 호출 단계는 보고서 역할의 compose에서만 지정합니다.")
    if node == "interpret":
        schema, messages = Interpretation, interpret_messages(state, role)
    elif node == "act":
        if definitions is None:
            if tools is None:
                raise ValueError(
                    "작업 선택 입력에는 현재 호출 가능한 도구 명세가 필요합니다."
                )
            definitions = selection_tools(tools, role, state=state)
        schema = selection_schema(definitions)
        messages = selection_messages(state, role, catalog, definitions=definitions)
    elif node == "decide":
        schema, messages = Decision, decide_messages(state, role, catalog)
    elif node == "compose" and role in REPORT_ROLES:
        prepared, stage = prepare_report_call(state, role, report_stage)
        schema = (
            ReportSelection
            if stage == "selection"
            else ReportText
            if stage == "draft"
            else Verification
        )
        messages = report_messages(prepared, stage, catalog, role=role)
    elif node == "compose":
        schema, messages = Composition, compose_messages(state, role)
    elif node == "ask":
        schema, messages = Question, ask_messages(state, role)
    else:
        raise ValueError(f"모델 호출이 없는 노드입니다: {node}")
    return {
        "schema": schema,
        "messages": messages,
        "strict": node == "act",
        "stage": stage,
    }


async def _structured_model_call(model, prepared: ModelCall, config):
    return await structured_call(
        model,
        prepared["schema"],
        prepared["messages"],
        config,
        strict=prepared["strict"],
    )


async def select_work(model, tools, catalog, state, config=None, *, role: Role):
    """실제 작업 선택을 기록해 반환한다. 선택한 도구·에이전트는 호출하지 않는다."""
    definitions = selection_tools(tools, role, state=state)
    choice, usage = await invoke_model(
        state,
        lambda: _structured_model_call(
            model,
            prepare_model_call(
                "act", state, role=role, catalog=catalog, definitions=definitions
            ),
            config,
        ),
    )
    state["results"].append(
        record(
            "act",
            "selection",
            choice["reason"],
            output=choice | {"model_usage": usage},
        )
    )
    return choice


def build_nodes(
    model,
    providers,
    catalog,
    *,
    role: Role,
    tool_runner=None,
    agent_runner=None,
    renderer=None,
):
    async def call(state, node, config, *, stage=None):
        return await invoke_model(
            state,
            lambda: _structured_model_call(
                model,
                prepare_model_call(
                    node, state, role=role, catalog=catalog, report_stage=stage
                ),
                config,
            ),
        )

    async def call_report(state, config, stage):
        """호출 인자는 이미 State에 기록되어 있다. 결과도 다음 호출 전에 반영한다."""
        item = state["results"][-1]
        try:
            value, usage = await call(state, "compose", config, stage=stage)
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
            stage=stage,
        )
        reviewed["output"]["call_id"] = target["id"]
        reviewed["reason"] = reviewed["output"]["reason"]
        check_report_text(reviewed, target)
        return reviewed

    async def select_report_views(state, config):
        if approved_report_selection(state):
            return True
        plan = _report_call_plan(state, role)
        _begin_planned_report_call(state, plan)
        if plan["stage"] == "selection_review":
            # 선정문은 보존하고 실패한 검토 호출만 다시 실행한다.
            checked = await call_report(
                state,
                config=config,
                stage="selection_review",
            )
            checked["output"]["call_id"] = plan["arguments"]["result_ids"][0]
            checked["reason"] = checked["output"]["reason"]
            return checked["output"]["accepted"]
        selection = await call_report(
            state,
            config=config,
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
        while (target := report_draft_target(state, role)) is not None:
            view_key, _ = target
            previous = last_report_draft(state, view_key)
            plan = _report_call_plan(state, role)
            _begin_planned_report_call(state, plan)
            # 검토 호출만 실패한 경우 작성문은 보존하고 검토만 다시 한다.
            if plan["stage"] == "review_retry":
                checked = await call_report(
                    state,
                    config=config,
                    stage="review_retry",
                )
                checked["output"]["call_id"] = previous["id"]
                checked["reason"] = checked["output"]["reason"]
                check_report_text(checked, previous)
                if not checked["output"]["accepted"]:
                    if report_draft_exhausted(state, view_key):
                        continue
                    return False
                continue
            await call_report(
                state,
                config=config,
                stage="draft",
            )
            checked = await verify_report(
                state,
                config=config,
                stage="draft_review",
            )
            if not checked["output"]["accepted"]:
                if report_draft_exhausted(state, view_key):
                    continue
                # 추가 작업과 바로 재작성을 구분하는 판단을 같은 역할의 decide가 한다.
                return False
        return True

    async def compose_report(state, config):
        first = len(state["results"])
        if finalizing(state):
            complete_report_stage(state, role)
        else:
            ready = (
                await select_report_views(state, config)
                if role == "report_selection"
                else await write_report(state, config)
            )
            if not ready:
                return Command(
                    update={
                        "results": state["results"][first:],
                        "response": response(
                            state,
                            "intermediate",
                            "검토 사유를 작업 진행 판단에 전달합니다.",
                        ),
                    },
                    goto="decide",
                )
            complete_report_stage(state, role)
        return Command(
            update={
                "results": state["results"][first:],
                "response": state["response"],
            },
            goto=END,
        )

    async def interpret(state, config):
        value, usage = await call(state, "interpret", config)
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
            goto="decide",
        )

    async def act(state, config):
        tools = {t.name: t for t in create_tools(providers, state=state)}
        # 노드 내부 판단도 같은 State 이력을 읽고, 반환할 때 새 기록만 전달한다.
        first_record = len(state["results"])
        choice = await select_work(model, tools, catalog, state, config, role=role)
        records = state["results"]
        name = choice["name"]
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

                    async def execute_child():
                        if agent_runner is not None:
                            return state_adapter.validate_python(
                                await agent_runner(child_role, child, config)
                            )
                        graph = compile_graph(
                            build_nodes(
                                model,
                                providers,
                                catalog,
                                role=child_role,
                                tool_runner=tool_runner,
                                agent_runner=agent_runner,
                                renderer=renderer,
                            ),
                            finish=finish,
                        )
                        return await run_graph(graph, child, config)

                    result = await trace_acall(
                        "agent",
                        name,
                        {
                            "initial_state": child,
                            "catalog": catalog,
                            "role": child_role,
                        },
                        execute_child,
                    )
                    return {k: result[k] for k in ("response", "results", "execution")}
                if (
                    role == "interpretation" or role in REPORT_ROLES
                ) and name == "validate_visualization":
                    raise ToolFailure("tool_not_allowed")
                actual = deepcopy(arguments)
                if name == "process_data":
                    actual = process_arguments(state, arguments)
                return await trace_acall(
                    "tool",
                    name,
                    {
                        "selected_arguments": arguments,
                        "resolved_arguments": actual,
                        "input_schema": tools[name].args_schema,
                    },
                    lambda: (
                        tool_runner(tools[name], actual, config)
                        if tool_runner is not None
                        else tools[name].ainvoke(actual, config)
                    ),
                )

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
        value, usage = await call(state, "decide", config)
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
        if role in REPORT_ROLES:
            return await compose_report(state, config)
        first_record = len(state["results"])
        value, usage = await call(state, "compose", config)
        state["results"].append(
            record(
                "compose",
                "composition",
                value["reason"],
                output=value | {"model_usage": usage},
            )
        )
        artifacts = trace_call(
            "artifact",
            "select_artifacts",
            {
                "selected_ids": value["artifact_ids"],
                "available_results": accepted_outputs(state),
                "previous_response": state["response"],
            },
            lambda: select_artifacts(state, renderer=renderer),
        )
        return Command(
            update={
                "results": state["results"][first_record:],
                "response": response(state, "final", value["content"], artifacts),
            },
            goto=END,
        )

    async def ask(state, config):
        value, usage = await call(state, "ask", config)
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
