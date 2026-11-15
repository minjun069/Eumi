"""평가에만 사용하는 하위 호출 대체. 일치하지 않는 호출은 실제 실행하지 않는다."""

from copy import deepcopy

from typing_extensions import TypedDict

from eval.schema import JsonObject, Stub, agent_reply_adapter, argument_key
from src.exceptions import ToolFailure
from src.state import state_adapter


class Call(TypedDict):
    name: str
    arguments: JsonObject


class MatchedCall(Call):
    stub: int


class UnusedStub(TypedDict):
    stub: int
    remaining: int


class FixtureSummary(TypedDict):
    calls: list[MatchedCall]
    unexpected: list[Call]
    unused: list[UnusedStub]


class UnexpectedStubCall(RuntimeError):
    def __init__(self, name, arguments):
        self.code = "unexpected_stub_call"
        self.details = {"name": name, "arguments": arguments}
        super().__init__("No prepared response matches this call")


class StubCalls:
    def __init__(self, stubs: list[Stub]):
        self.stubs = deepcopy(stubs)
        self.signatures = [argument_key(stub["arguments"]) for stub in stubs]
        self.remaining = [stub.get("uses", 1) for stub in stubs]
        self.calls: list[MatchedCall] = []
        self.unexpected: list[Call] = []

    def reply(self, name, arguments):
        signature = argument_key(arguments)
        for index, stub in enumerate(self.stubs):
            if (
                self.remaining[index] > 0
                and stub["name"] == name
                and self.signatures[index] == signature
            ):
                self.remaining[index] -= 1
                self.calls.append(
                    {"name": name, "arguments": deepcopy(arguments), "stub": index}
                )
                if "error" in stub:
                    error = stub["error"]
                    raise ToolFailure(
                        error["code"],
                        details=error.get("details"),
                        retryable=error.get("retryable", False),
                    )
                return deepcopy(stub["output"])
        self.unexpected.append({"name": name, "arguments": deepcopy(arguments)})
        raise UnexpectedStubCall(name, arguments)

    async def tool(self, tool, arguments, config):
        # 호출자가 선택·참조 해석·예산·trace를 기록한다.
        return self.reply(tool.name, arguments)

    async def agent(self, role, state, config):
        value = agent_reply_adapter.validate_python(
            self.reply(role + "_agent", {"goal": state["request"]["goal"]})
        )
        child = deepcopy(state)
        child["results"] = value["results"]
        child["response"] = value["response"]
        child["execution"].update(status=value["status"], error=value["error"])
        # 준비된 하위 응답은 실제 모델 사용량을 만들지 않으며 공유 예산을 보존한다.
        return state_adapter.validate_python(child)

    def renderer(self, arguments):
        return self.reply("render_visualization", arguments)

    def summary(self) -> FixtureSummary:
        return {
            "calls": self.calls,
            "unexpected": self.unexpected,
            "unused": [
                {"stub": index, "remaining": count}
                for index, count in enumerate(self.remaining)
                if count
            ],
        }
