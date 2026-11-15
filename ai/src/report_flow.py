"""한 동의 보고서 에이전트를 순차 실행한다. 저장·동별 재처리는 API가 맡는다."""

from src.agent_nodes import build_nodes, finish, publish_report
from src.execution import accepted_outputs, finalizing, record
from src.execution_trace import trace_acall
from src.graph import compile_graph
from src.prompting import REPORT_ROLES
from src.runtime import execution_config
from src.state import state_adapter


def completed_stage(state, role):
    """정상 부분 완료도 종료다. 오류 종료에는 이 기록이 없어 그 단계만 재처리한다."""
    return any(
        item["decision"] == "composition"
        and (item["action"] or {}).get("name") == role + "_agent"
        for item in state["results"]
    )


async def run_report_flow(
    state,
    *,
    model,
    providers,
    catalog,
    config=None,
    publish=None,
):
    """동 State를 그대로 전달한다. 새 예산·하위 State·별도 산출물 캐시는 없다."""
    state = state_adapter.validate_python(state)
    for role in REPORT_ROLES:
        if finalizing(state):
            break
        if completed_stage(state, role):
            continue
        state["results"].append(
            record(
                "report",
                "report_stage",
                "보고서 에이전트 순차 실행",
                action={
                    "name": role + "_agent",
                    "arguments": {
                        "view_key": None,
                        "result_ids": [
                            *[
                                r["id"]
                                for r in state["results"]
                                if r["decision"] in {"report_input", "report_source"}
                            ],
                            *accepted_outputs(state),
                        ],
                    },
                },
            )
        )
        state["execution"].update(status="queued", error=None)
        graph = compile_graph(
            build_nodes(
                model,
                providers,
                catalog,
                role=role,
            ),
            finish=finish,
            publish=publish,
        )
        state = state_adapter.validate_python(
            await trace_acall(
                "agent",
                role + "_agent",
                {"initial_state": state, "role": role},
                lambda graph=graph, state=state: graph.ainvoke(
                    state,
                    execution_config(state["execution"]["run_id"], config),
                ),
            )
        )
        if not completed_stage(state, role):
            break
    # 오류·한도에서도 검증된 항목은 저장 대상으로 남긴다. 기존 오류는 유지한다.
    error = state["execution"]["error"]
    status = publish_report(state)
    state["execution"]["status"] = status
    state["execution"]["error"] = error or (
        None
        if status == "completed"
        else {"code": "incomplete", "cause": "완성하지 못한 항목은 NULL"}
    )
    return state
