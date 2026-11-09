"""임시 HTTP 호출자·알림 수신기로 실제 API와 업무 노드의 왕복을 검사한다."""

import json
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from experiments.scenario_fixtures import CATALOG, PROVIDERS
from src.database import (
    Database,
    QuestionFinished,
    QuestionNotFound,
    question_id,
    response_row,
)
from src.state import create_state, state_adapter


def section(messages, title):
    value = messages[1].content.split(f"[{title}]\n", 1)[1]
    return json.JSONDecoder().raw_decode(value)[0]


class OfflineModel:
    """모델 응답만 대체한다. 노드·도구·State 갱신은 공통 코드를 실행한다."""

    def bind_tools(self, tools, **kwargs):
        self.kwargs = {}
        return self

    def with_structured_output(self, schema, **kwargs):
        async def invoke(messages, config):
            title = schema["title"]
            if title == "Interpretation":
                value = {
                    "request": {"goal": "시연용 D3 가구 자료를 조회하고 비교표로 설명"},
                    "reason": "시연 입력 확인",
                    "needs_input": False,
                }
            elif title == "Selection":
                value = {
                    "name": "query_data",
                    "arguments_json": '{"target":"D3"}',
                    "reason": "시연 자료 조회",
                }
            elif title == "Decision":
                value = {"next": "compose", "reason": "자료 조회 완료"}
            elif title == "Composition":
                records = section(messages, "작업 결과와 검증 이력")
                call = next(r for r in reversed(records) if r["decision"] == "call")
                value = {
                    "content": "시연용 예시 데이터의 가구 비교표입니다. "
                    "실제 통계가 아닙니다.",
                    "artifact_ids": [call["id"]],
                    "status": "completed",
                    "reason": "검증된 조회 자료",
                }
            else:
                raise ValueError(f"Unexpected offline model step: {title}")
            return {"raw": AIMessage(json.dumps(value, ensure_ascii=False))}

        return RunnableLambda(invoke)


class MemoryDatabase(Database):
    """실험용 합성 DB 경계. PostgreSQL 저장 성공을 뜻하지 않는다."""

    def __init__(self, settings):
        super().__init__(settings)
        self.providers, self.catalog = PROVIDERS, CATALOG
        self.conversation_id = uuid4()
        self.question = 101
        self.saved = []

    async def load_question(self, conversation_id, requested_id):
        if conversation_id != self.conversation_id or requested_id != self.question:
            raise QuestionNotFound
        if any(response_row(s)["status"] != "진행" for s in self.saved):
            raise QuestionFinished
        goal = "시연용 D3 가구 자료를 조회하고 비교표로 설명해 주세요."
        state = create_state(
            {"goal": goal},
            self.settings,
            messages=[HumanMessage(goal, id=str(self.question))],
            version=self.settings.version,
            event="user_request",
        )
        state["execution"]["run_id"] = str(conversation_id)
        return state

    async def save_response(self, state):
        response_row(state)
        assert question_id(state) == self.question
        saved = state_adapter.dump_python(state, mode="json")
        self.saved.append(saved)
        return 101 + len(self.saved)
