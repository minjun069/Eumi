"""실제 노드를 검증할 때 모델 응답만 대체하는 공통 준비 코드."""

import json
from copy import deepcopy

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from src.settings import Settings
from src.state import create_state

DONE = {"next": "compose", "reason": "완료"}


def initial(event="analysis_pipeline"):
    return create_state(
        {"goal": "지역별 비율 비교", "constraints": {"required": ["출처 명시"]}},
        Settings(_env_file=None),
        messages=[HumanMessage('사용자 원문\n"비율을 알려줘"')],
        version="test",
        event=event,
    )


def section(messages, title):
    text = messages[1].content.split(f"[{title}]\n", 1)[1]
    return json.JSONDecoder().raw_decode(text)[0]


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.inputs = []
        self.schemas = []
        self.tool_definitions = []
        self.response_schemas = []

    def bind_tools(self, tools, **kwargs):
        self.tool_definitions.append(deepcopy(tools))
        self.kwargs = {}
        return self

    def with_structured_output(self, schema, **kwargs):
        self.response_schemas.append(deepcopy(schema))

        async def invoke(messages, config):
            self.schemas.append(schema["title"])
            self.inputs.append(messages)
            reply = next(self.replies)
            if callable(reply):
                reply = reply(messages)
            return {"raw": AIMessage(json.dumps(reply, ensure_ascii=False))}

        return RunnableLambda(invoke)


def selection(name, args):
    return {"name": name, "arguments_json": json.dumps(args), "reason": "작업 선택"}


def composition(messages):
    results = section(messages, "작업 결과와 검증 이력")
    call = next(
        r
        for r in reversed(results)
        if r["decision"] == "call"
        and r["node"] == "act"
        and r["outcome"] == "success"
        and r["output"].get("valid") is not False
    )
    return {
        "content": "시연용 예시 데이터로 계산한 결과입니다.",
        "artifact_ids": [call["id"]],
        "status": "completed",
        "reason": "검증된 계산 결과",
    }
