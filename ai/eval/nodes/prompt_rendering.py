"""호출 입력 원문과 검사 대상 출력을 표시하고 인용 표식을 원본에 연결한다."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, NotRequired

from typing_extensions import TypedDict

if TYPE_CHECKING:
    from eval.nodes.prompt_fields import PromptField


class EvidenceLabel(TypedDict):
    path: str
    kind: Literal["input", "output"]
    missing_path: NotRequired[str]
    json_path: NotRequired[str]


class RenderedPrompt(TypedDict):
    text: str
    evidence_labels: dict[str, EvidenceLabel]
    expectation_ids: dict[str, str]


NAMES = {
    "content": "본문",
    "reason": "이유",
    "request": "요청",
    "goal": "목표",
    "constraints": "작업 조건",
    "required": "필수 조건",
    "preferred": "선호 조건",
    "excluded": "제외 조건",
    "information_required": "추가 정보 필요 여부",
    "question": "질문",
    "name": "이름",
    "arguments": "작업 인자",
    "arguments_json": "작업 인자",
    "next": "다음 작업",
    "status": "완료 상태",
    "artifact_ids": "공개할 산출물 식별자",
    "views": "선정한 시각화",
    "view_key": "대상 시각화",
    "evidence_ids": "근거 자료 식별자",
    "result_ids": "참조한 작업 기록",
    "input_result_id": "가공할 자료 기록",
    "right_result_id": "결합할 오른쪽 자료 기록",
    "retry_of": "다시 검토한 이전 기록",
    "selected_ids": "선택한 산출물 기록",
    "accepted": "검토 통과 여부",
    "call_id": "검토 대상 기록",
    "id": "식별자",
    "decision": "작업 내용",
    "action": "수행한 작업",
    "output": "작업 결과",
    "outcome": "처리 결과",
    "description": "설명",
    "results": "작업 기록",
    "data": "자료",
    "rows": "자료의 행",
    "columns": "자료의 열",
    "type": "유형",
    "role": "발화자",
    "source": "출처",
    "path": "위치",
    "reference": "기준 자료",
    "version": "버전",
    "unit": "단위",
    "error": "오류",
    "code": "오류 종류",
    "message": "메시지",
    "details": "상세 내용",
    "valid": "유효 여부",
    "execution": "실행 조건",
    "absolute": "절대 허용 오차",
    "relative": "상대 허용 오차",
    "alternatives": "허용한 대안",
    "value": "값",
    "$ref": "원문에 담긴 참조 값",
}
WORDS = {
    "report_draft": "보고서 초안 작성",
    "report_selection": "보고서 시각화 선정",
    "verification": "산출물 검토",
    "call": "작업 호출",
    "success": "성공",
    "failure": "실패",
    "completed": "완료",
    "partial": "부분 완료",
    "failed": "실패",
    "cancelled": "취소",
    "human": "사용자",
    "user": "사용자",
    "ai": "응답자",
    "assistant": "응답자",
    "system": "시스템 지침",
    "act": "작업 수행",
    "compose": "응답 작성",
    "ask": "사용자에게 질문",
    "query_data": "자료 조회",
    "process_data": "자료 가공",
    "visualize_data": "자료 시각화",
    "interpretation_agent": "자료 해석 담당 에이전트",
    "visualization_agent": "시각화 담당 에이전트",
    "report_selection_agent": "보고서 시각화 선정 담당 에이전트",
    "report_description_agent": "보고서 설명 담당 에이전트",
    "report_insight_agent": "보고서 인사이트 담당 에이전트",
    "write_report": "보고서 작성",
    "review_report": "보고서 검토",
    "select_report_views": "보고서 시각화 선정",
}


def _tokens(pointer):
    return [
        token.replace("~1", "/").replace("~0", "~") for token in pointer.split("/")[1:]
    ]


def _read(payload, pointer):
    value = payload
    for token in _tokens(pointer):
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdecimal() and int(token) < len(value):
            value = value[int(token)]
        else:
            return False, None
    return True, value


def _existing(payload, pointer):
    while pointer and not _read(payload, pointer)[0]:
        pointer = pointer.rpartition("/")[0]
    return pointer


def render_prompt(payload: dict, *, fields: list[PromptField]) -> RenderedPrompt:
    """입력은 JSON 원문 전체로, 출력은 선택한 값으로 표시한다."""
    labels: dict[str, EvidenceLabel] = {}
    expectation_ids = {}
    counts = {"input": 0, "output": 0}
    sections = {"실행 당시 입력": [], "평가 대상 출력": [], "이유": [], "판정 항목": []}

    def register(field):
        kind, path = field["section"], field["path"]
        counts[kind] += 1
        prefix = "입력" if kind == "input" else "출력"
        alias = f"{prefix} {counts[kind]}"
        existing = _existing(payload, path)
        label: EvidenceLabel = {"path": existing, "kind": kind}
        if field.get("missing_path") or existing != path:
            label["missing_path"] = field.get("missing_path") or path
        if field.get("json_path") is not None:
            label["json_path"] = field["json_path"]
        labels[alias] = label
        return alias

    def render_value(value, *, depth=1, key=None, semantic=False):
        indent = "  " * depth
        if value is None:
            return [indent + "명시된 빈 값(null)"]
        if isinstance(value, bool):
            return [indent + ("참(불리언)" if value else "거짓(불리언)")]
        if isinstance(value, (int, float)):
            return [indent + str(value)]
        if isinstance(value, str):
            if value == "":
                return [indent + "빈 문자열(0자)"]
            if not value.strip():
                return [indent + f"공백 문자열({len(value)}자)"]
            if semantic:
                value = WORDS.get(value, value)
            if "\n" not in value:
                return [indent + "“" + value + "”"]
            return [
                indent + "원문:",
                *[indent + "  " + line for line in value.split("\n")],
            ]
        if isinstance(value, list):
            if not value:
                return [indent + "빈 목록(0개)"]
            lines = []
            for index, item in enumerate(value):
                lines.append(indent + f"{index + 1}번째 항목:")
                lines.extend(render_value(item, depth=depth + 1, key=key))
            return lines
        if isinstance(value, dict):
            if not value:
                return [indent + "빈 객체(항목 없음)"]
            lines = []
            dialogue = ("role" in value and "content" in value) or (
                "type" in value and "data" in value
            )
            for name, item in value.items():
                lines.append(indent + NAMES.get(name, name) + ":")
                lines.extend(
                    render_value(
                        item,
                        depth=depth + 1,
                        key=name,
                        semantic=(key == "action" and name == "name")
                        or (dialogue and name in {"role", "type"}),
                    )
                )
            return lines
        return [indent + str(value)]

    for field in fields:
        alias = register(field)
        section = "실행 당시 입력" if field["section"] == "input" else "평가 대상 출력"
        if field["section"] == "output" and (
            field["path"].endswith("/reason")
            or (field.get("json_path") or "").endswith("/reason")
        ):
            section = "이유"
        lines = [f"[{alias}] {field['label']}"]
        if field["status"] == "missing":
            lines.append("  해당 필드가 제공되지 않았습니다.")
        elif "value" in field:
            if field["section"] == "input":
                lines.extend(
                    [
                        "```json",
                        json.dumps(field["value"], ensure_ascii=False, indent=2),
                        "```",
                    ]
                )
            else:
                tokens = _tokens(field.get("json_path") or field["path"])
                key = tokens[-1] if tokens else None
                lines.extend(
                    render_value(
                        field["value"],
                        key=key,
                        semantic=tokens[:3] == ["evidence", "call", "output"]
                        and len(tokens) == 4
                        and key in {"next", "status", "name"},
                    )
                )
        else:
            lines.append("  선택한 값을 확보하지 못했습니다.")
        if field.get("reason"):
            lines.append("  확인 상태:")
            lines.extend(render_value(field["reason"]))
        sections[section].append("\n".join(lines))

    assessment = payload.get("assessment") or {}
    for index, item in enumerate(assessment.get("expectations") or []):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            heading = f"항목 {index + 1}"
            expectation_ids[heading] = item["id"]
            sections["판정 항목"].append(f"[{heading}]")
    blocks = []
    for title in ("실행 당시 입력", "평가 대상 출력"):
        content = list(sections[title])
        if title == "평가 대상 출력" and sections["이유"]:
            content.append("[이유]\n" + "\n\n".join(sections["이유"]))
        if content:
            blocks.append(f"[{title}]\n" + "\n\n".join(content))
    if sections["판정 항목"]:
        blocks.append("[판정 항목]\n" + "\n".join(sections["판정 항목"]))
    return {
        "text": "\n\n".join(blocks) or "표시할 평가 자료가 없습니다.",
        "evidence_labels": labels,
        "expectation_ids": expectation_ids,
    }
