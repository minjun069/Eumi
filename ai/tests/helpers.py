from copy import deepcopy

from langchain_core.messages import AIMessage


class ScriptedModel:
    """Standard tool-call messages; script position follows checkpointed history."""

    def __init__(self, *calls):
        self.script = calls
        self.invocations = 0

    def bind_tools(self, tools, **kwargs):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        self.invocations += 1
        index = sum(isinstance(message, AIMessage) for message in messages)
        name, arguments = self.script[min(index, len(self.script) - 1)]
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": deepcopy(arguments),
                    "id": f"call-{index}",
                    "type": "tool_call",
                }
            ],
        )


def finish(content="Done", results=None, partial=False):
    return "submit_result", {
        "content": content,
        "results": results or [],
        "references": [],
        "partial": partial,
    }


async def accept(state, result):
    return []
