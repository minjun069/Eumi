"""공통 그래프에 공급할 임시 입력·모의 노드 출력.

업무 노드가 미구현이므로 현재는 노드 출력을 대체한다.
실제 업무 노드 연결 후에는 모델·외부 도구의 입출력 경계만 대체한다.
그래프 구성과 실행은 demo.py 및 테스트가 src.graph를 사용해 수행한다.
"""

from collections.abc import Callable
from copy import deepcopy
from typing import Literal, get_args
from uuid import uuid4

from langgraph.graph import END
from langgraph.types import Command

from src.graph import Completion, Nodes
from src.settings import Settings
from src.state import ExecutionEvent, ResultItem, State, create_state

Scenario = Literal[
    "complete", "continue", "intermediate", "question", "partial", "failure"
]
CASES = {
    "complete": "completed",
    "continue": "completed",
    "intermediate": "completed",
    "question": "completed",
    "partial": "partial",
    "failure": "failed",
}


def initial_state(event: ExecutionEvent = "user_request") -> State:
    return create_state(
        {"goal": "공통 그래프 연결·상태 처리·질문 재개 확인"},
        Settings(_env_file=None),
        messages=[],
        version="graph-fixture",
        event=event,
    )


def _record(node: str, decision: str, **details) -> ResultItem:
    return {
        "id": str(uuid4()),
        "node": node,
        "decision": decision,
        "reason": "실행 흐름 검증용 임시 출력",
        "action": None,
        "output": None,
        "description": decision,
        "outcome": "success",
        **details,
    }


def _publish(state: State, node: str, kind: str, content: str, next_node: str):
    response = {
        "id": str(uuid4()),
        "kind": kind,
        "label": "임시 실행",
        "content": content,
        "artifacts": deepcopy((state["response"] or {}).get("artifacts", [])),
    }
    return Command(
        update={
            "response": response,
            "results": [_record(node, content, output={"response": response})],
        },
        goto=next_node,
    )


def mock_nodes(
    scenario: Scenario = "complete",
) -> tuple[Nodes, Callable[[State], Completion]]:
    """시나리오별 모의 노드와 종료 판단을 제공한다. 그래프는 만들지 않는다."""
    if scenario not in get_args(Scenario):
        raise ValueError(f"Unknown temporary scenario: {scenario}")

    # 임시 업무 노드
    def interpret(state: State):
        # 답변은 messages에 보존한다. 요청 재해석은 후속 모델 연결 시 구현한다.
        resumed = any(r["node"] == "ask" for r in state["results"])
        next_node = "decide" if resumed else "act"
        return Command(
            update={
                "results": [_record("interpret", "요청 확인", output=state["request"])]
            },
            goto=next_node,
        )

    def act(state: State):
        call = _record(
            "act",
            "임시 호출",
            action={"name": "temporary_call", "arguments": {}},
            output={"temporary": True, "error": "temporary_failure"}
            if scenario == "failure"
            else {"temporary": True, "available": True},
            outcome="failure" if scenario == "failure" else "success",
        )
        records = [
            _record("act", "임시 작업 선택"),
            call,
            _record(
                "act",
                "임시 결과 검증",
                output={
                    "target": call["id"],
                    "criterion": "임시 결과 확보 여부",
                    "accepted": scenario != "failure",
                },
            ),
        ]
        return Command(update={"results": records}, goto="decide")

    def decide(state: State):
        history = state["results"]
        next_node = "compose"
        if scenario == "question" and not any(r["node"] == "ask" for r in history):
            next_node = "ask"
        elif (
            scenario == "continue"
            and sum(r["decision"] == "임시 호출" for r in history) < 2
        ):
            next_node = "act"
        return Command(
            update={"results": [_record("decide", f"다음 단계: {next_node}")]},
            goto=next_node,
        )

    def compose(state: State):
        intermediate = scenario == "intermediate" and not any(
            r["node"] == "compose" for r in state["results"]
        )
        return _publish(
            state,
            "compose",
            "intermediate" if intermediate else "final",
            "임시 중간 결과. 다음 작업을 계속합니다."
            if intermediate
            else f"임시 실행 종료: {scenario}. 실제 분석 결과가 아닙니다.",
            "act" if intermediate else END,
        )

    def ask(state: State):
        return _publish(
            state, "ask", "question", "임시 질문: 추가 정보를 입력해 주세요.", "wait"
        )

    def finish(state: State) -> Completion:
        failed = scenario == "failure"
        return {
            "status": CASES[scenario],
            "error": {"code": "temporary_failure", "cause": "임시 실패 시나리오"}
            if failed
            else None,
        }

    return (
        {
            "interpret": interpret,
            "act": act,
            "decide": decide,
            "compose": compose,
            "ask": ask,
        },
        finish,
    )
