"""모의 모델의 표준 도구 응답 조회. Agent 실행 연결은 미구현 상태다."""

from langchain_core.messages import AIMessage, ToolMessage


def observations(messages):
    names = {
        call["id"]: call["name"]
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    return {
        names[m.tool_call_id]: m
        for m in messages
        if isinstance(m, ToolMessage) and m.tool_call_id in names
    }



def build_agents(models):
    raise NotImplementedError(
        "하위 Agent 호출과 결과 검증 연결을 삭제하여 실험 Agent 구성이 미구현 상태입니다."
    )
