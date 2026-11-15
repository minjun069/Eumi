"""실제 모델 호출의 메시지와 응답 형식을 원문 그대로 평가 입력에 연결한다."""

from copy import deepcopy

from pydantic import JsonValue
from typing_extensions import TypedDict


class InputOrigin(TypedDict):
    label: str
    source: str
    path: str


class SelectedInput(InputOrigin):
    value: JsonValue


class JudgeEvidence(TypedDict):
    node: str
    role: str | None
    call: dict[str, JsonValue]
    inputs: list[SelectedInput]
    missing_inputs: list[str]


ROLE_LABELS = {
    "system": "시스템",
    "developer": "개발자",
    "human": "사용자",
    "user": "사용자",
    "ai": "응답자",
    "assistant": "응답자",
    "tool": "도구",
    "function": "함수",
}


def message_role(message):
    """보관 형식 두 가지의 발화자를 읽되 값이나 본문을 변환하지 않는다."""
    if not isinstance(message, dict):
        return None
    data = message.get("data", message)
    if not isinstance(data, dict):
        return None
    return data.get("role", data.get("type", message.get("type")))


def valid_message(message):
    if not isinstance(message, dict):
        return False
    data = message.get("data", message)
    role = message_role(message)
    return (
        isinstance(data, dict)
        and isinstance(role, str)
        and bool(role.strip())
        and isinstance(data.get("content"), (str, list))
    )


def select_inputs(
    definition, node, call, expectations, reference=None
) -> JudgeEvidence:
    """사례의 답안·선택 경로 대신 저장된 호출 입력 전체를 사용한다."""
    if "rows" in definition:
        raise ValueError("입력 선택 전에 현재 호출의 평가 행을 선택해야 합니다")
    selected: list[SelectedInput] = []
    missing = []
    messages = call.get("messages")
    if not isinstance(messages, list) or not messages:
        missing.append("실제 모델 입력 메시지 목록이 없거나 배열이 아닙니다.")
    else:
        for index, message in enumerate(messages):
            role = message_role(message)
            title = (
                ROLE_LABELS.get(role, "기타 발화자")
                if isinstance(role, str)
                else "발화자 미확인"
            )
            label = f"실행 당시 메시지 {index + 1} · {title}"
            selected.append(
                {
                    "label": label,
                    "source": "messages",
                    "path": f"/messages/{index}",
                    "value": deepcopy(message),
                }
            )
            if not valid_message(message):
                missing.append(
                    f"{label}: 메시지의 발화자·본문 형식을 확인할 수 없습니다."
                )
    schema = call.get("response_schema")
    if schema is not None:
        selected.append(
            {
                "label": "실행 당시 응답 형식",
                "source": "response_schema",
                "path": "/response_schema",
                "value": deepcopy(schema),
            }
        )
        if not isinstance(schema, dict):
            missing.append("실행 당시 응답 형식이 객체가 아닙니다.")
    return {
        "node": node["node"],
        "role": node.get("role"),
        "call": {
            key: deepcopy(call.get(key)) for key in ("id", "name", "path", "output")
        },
        "inputs": selected,
        "missing_inputs": missing,
    }
