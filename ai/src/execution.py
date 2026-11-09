"""Agent의 실행 한도를 적용하고 사용량과 호출 이력을 관리한다."""

import asyncio
from time import monotonic
from uuid import uuid4

from src.exceptions import LimitReached, ToolFailure
from src.state import State


def finalizing(state: State) -> bool:
    error = state["execution"]["error"]
    return bool(error and error["code"] == "execution_limit_exceeded")


def remaining(state: State, resource: str) -> int | float:
    usage = state["execution"]["budget"][resource]
    return max(0, usage["limit"] - usage["used"])


def exhausted(state: State, resource: str) -> LimitReached:
    usage = state["execution"]["budget"][resource]
    return LimitReached(resource, used=usage["used"], limit=usage["limit"])


def require(state: State, resource: str) -> None:
    if remaining(state, resource) <= 0:
        raise exhausted(state, resource)


def consume(state: State, resource: str) -> None:
    require(state, resource)
    state["execution"]["budget"][resource]["used"] += 1


def record(node, decision, reason, *, action=None, output=None, success=True):
    return {
        "id": uuid4().hex,
        "node": node,
        "decision": decision,
        "reason": reason,
        "action": action,
        "output": output,
        "description": decision,
        "outcome": "success" if success else "failure",
    }


def accepted_outputs(state):
    """성공한 호출과 검토를 통과한 보고서 결과를 State에서 찾는다."""
    accepted, rejected = set(), set()
    for item in state["results"]:
        output = item.get("output") or {}
        if item["decision"] == "verification":
            if output.get("accepted") is True:
                accepted.add(output["call_id"])
            elif output.get("accepted") is False:
                rejected.add(output["call_id"])
    outputs = {
        item["id"]: item["output"]
        for item in state["results"]
        if (item["decision"] == "call" or item["id"] in accepted)
        and item["id"] not in rejected
        and item["outcome"] == "success"
        and item.get("output") is not None
        and item["output"].get("valid") is not False
        and item["output"].get("execution", {}).get("status")
        not in {"failed", "cancelled"}
    }
    for output in list(outputs.values()):
        if "results" in output:
            outputs.update(accepted_outputs(output))
    return outputs


def _elapsed(state, resource, started, baseline, final_baseline):
    budget = state["execution"]["budget"]
    elapsed = monotonic() - started
    if resource == "active_seconds":
        # 하위 종료 응답에 쓴 시간은 일반 실행 시간과 중복 집계하지 않는다.
        elapsed -= budget["final_active_seconds"]["used"] - final_baseline
    budget[resource]["used"] = max(
        budget[resource]["used"], baseline + max(0, elapsed)
    )


async def timed(state: State, operation, *, contains_child=False):
    """개별 호출은 잔여 시간으로 제한하고, 중첩 호출 시간은 한 번만 누적한다."""
    resource = "final_active_seconds" if finalizing(state) else "active_seconds"
    require(state, resource)
    budget = state["execution"]["budget"]
    baseline = budget[resource]["used"]
    final_baseline = budget["final_active_seconds"]["used"]
    timeout = remaining(state, resource)
    if contains_child and resource == "active_seconds":
        # 하위의 일반 호출과 종료 호출이 각각 자신의 State 잔여 시간으로 제한된다.
        # 상위 대기 타이머가 먼저 만료되어 하위의 종료 응답·사용량을 잃지 않게 한다.
        timeout = None
    started = monotonic()
    deadline = None
    try:
        async with asyncio.timeout(timeout) as deadline:
            value = await operation()
        if deadline.expired():
            raise exhausted(state, resource)
        return value
    except TimeoutError:
        if deadline is not None and deadline.expired():
            _elapsed(state, resource, started, baseline, final_baseline)
            raise exhausted(state, resource) from None
        raise
    finally:
        _elapsed(state, resource, started, baseline, final_baseline)


async def invoke_model(state: State, operation):
    if finalizing(state):
        consume(state, "final_model_calls")
    return await timed(state, operation)


def _rework_target(state):
    # 새 필드를 도입하기 전의 이력 기반 처리. 여러 호출에 걸친 보완 관계는 미해결이다.
    previous = next(
        (
            item for item in reversed(state["results"])
            if item["node"] == "act" and item["action"] is not None
        ),
        None,
    )
    if previous is None:
        return None
    rejected = any(
        item["decision"] == "verification"
        and (item["output"] or {}).get("call_id") == previous["id"]
        and (item["output"] or {}).get("accepted") is False
        for item in state["results"]
    )
    if (
        previous["outcome"] == "failure"
        or (previous["output"] or {}).get("valid") is False
        or rejected
    ):
        return previous
    return None


def _begin_call(state, node, name, arguments, reason):
    if finalizing(state):
        raise ToolFailure("final_response_tool_forbidden")
    resource = "agent_calls" if name.endswith("_agent") else "tool_calls"
    previous = _rework_target(state) if node == "act" else None
    require(state, resource)
    if previous:
        require(state, "retries")
    consume(state, resource)
    if previous:
        consume(state, "retries")
        state["results"].append(record(
            node, "retry", "실패·부적합 결과 보완",
            output={"call_id": previous["id"]},
        ))
    item = record(
        node, "call", reason,
        action={"name": name, "arguments": arguments},
        output={"code": "call_incomplete"}, success=False,
    )
    state["results"].append(item)
    return item


def _call_error(item, exc):
    item["output"] = {
        "code": getattr(exc, "code", type(exc).__name__),
        "error_type": type(exc).__name__,
        "details": getattr(exc, "details", {}),
        "retryable": getattr(exc, "retryable", False),
    }


async def invoke_work(state, node, name, arguments, reason, operation):
    require(state, "active_seconds")
    item = _begin_call(state, node, name, arguments, reason)

    async def execute():
        item["output"] = await operation()
        item["outcome"] = "success"
        if name.endswith("_agent"):
            # 반환값을 상위 results에 저장한 다음 같은 기록에서 누적 사용량을 반영한다.
            merge_child_budget(state, item["output"])
        return item["output"]

    try:
        await timed(state, execute, contains_child=name.endswith("_agent"))
    except (Exception, asyncio.CancelledError) as exc:
        if item["outcome"] != "success":
            _call_error(item, exc)
        raise
    return item


def invoke_local_tool(state, node, name, arguments, operation):
    """동기 계산도 호출 수·시간·반환값을 State에 남긴다."""
    require(state, "active_seconds")
    item = _begin_call(state, node, name, arguments, "공개 산출물 구성")
    baseline = state["execution"]["budget"]["active_seconds"]["used"]
    final_baseline = state["execution"]["budget"]["final_active_seconds"]["used"]
    started = monotonic()
    try:
        item["output"] = operation()
        item["outcome"] = "success"
    except Exception as exc:
        _call_error(item, exc)
        raise
    finally:
        _elapsed(state, "active_seconds", started, baseline, final_baseline)
    require(state, "active_seconds")
    return item["output"]


def merge_child_budget(parent: State, child: State) -> None:
    """하위 값은 진입 시점의 누적값을 포함한다. 더하지 않고 증가분을 반영한다."""
    for name, usage in parent["execution"]["budget"].items():
        returned = child["execution"]["budget"][name]
        if returned["limit"] != usage["limit"] or returned["used"] < usage["used"]:
            raise ValueError("Child changed the shared execution budget")
        usage["used"] = returned["used"]
