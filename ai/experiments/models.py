"""Offline model doubles emit native AIMessage tool calls; real mode uses ChatOpenAI."""

import json

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from experiments.agents import observations
from experiments.tools import SOURCE
from src.settings import Settings


class DemoModel:
    def __init__(self, role, scenario, region):
        self.role, self.scenario, self.region = role, scenario, region

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        observed = observations(messages)
        context = json.loads(messages[0].content.rsplit("\n", 1)[-1])
        region = context["request"].get("subject", {}).get("region", self.region)
        if "ask_user" in observed:
            region = observed["ask_user"].content
        name, args = self.choose(observed, region)
        index = sum(isinstance(m, AIMessage) for m in messages)
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": args,
                    "id": f"{self.role}-{index}",
                    "type": "tool_call",
                }
            ],
        )

    @staticmethod
    def finish(content, results=None, partial=False):
        return "submit_result", {
            "content": content,
            "results": results or [],
            "references": [SOURCE],
            "partial": partial,
        }

    def choose(self, observed, region):
        if self.role == "request_handler":
            for child in ("analysis", "visualization"):
                if child not in observed:
                    return child, {
                        "goal": "활동지수 설명과 표",
                        "subject": {}
                        if child == "analysis" and self.scenario in {"ask", "cancel"}
                        else {"region": region},
                    }
                message = observed[child]
                if message.status == "error" or json.loads(message.content)["partial"]:
                    return self.finish(
                        "요청의 일부를 처리하지 못했습니다.", partial=True
                    )
                if child == "analysis":
                    region = json.loads(message.content)["results"][0]["data"]["region"]
            return self.finish(
                "관측된 활동지수 변화와 표입니다. 고립 위험 증가를 단정할 수 없습니다. "
                "시연용 예시 데이터입니다."
            )
        if (
            self.scenario in {"ask", "cancel"}
            and self.role == "analysis"
            and "ask_user" not in observed
        ):
            return "ask_user", {
                "question": "어느 가상 지역을 비교할까요? A/B/C 중 선택해주세요."
            }
        if "lookup_metrics" not in observed:
            return "lookup_metrics", {"region": region}
        lookup = observed["lookup_metrics"]
        if lookup.status == "error":
            return self.finish("자료 조회에 실패했습니다.", partial=True)
        data = json.loads(lookup.content)
        if "before" not in data:
            return self.finish("해당 지역의 자료가 없습니다.", partial=True)
        if "calculate_change" not in observed:
            return "calculate_change", {
                "before": data["before"],
                "after": data["after"],
            }
        change = json.loads(observed["calculate_change"].content)
        values = {
            "region": data["region"],
            "before": data["before"],
            "after": data["after"],
            "change": change,
        }
        if self.role == "analysis":
            if self.scenario == "rework" and "submit_result" not in observed:
                values["change"] = (
                    99.0  # Deliberate defect: the validator must reject it.
                )
            return self.finish(
                f"활동지수 변화율은 {change}%입니다. "
                "고립 위험 증가를 단정할 수 없습니다. 시연용 예시 데이터입니다.",
                [
                    {
                        "type": "analysis_interpretation",
                        "data": values,
                        "sources": [SOURCE],
                        "issues": ["시연용 예시 데이터"],
                    }
                ],
            )
        if "render_table" not in observed:
            return "render_table", values
        return self.finish("활동지수 비교 표입니다. 시연용 예시 데이터입니다.")


def build_models(settings: Settings, *, real=False, scenario="normal", region="A"):
    roles = ("analysis", "visualization", "request_handler")
    if not real:
        return {name: DemoModel(name, scenario, region) for name in roles}
    if settings.api_key is None:
        raise ValueError(
            "Set SETTINGS_API_KEY and SETTINGS_MODEL in ai/.env for real mode"
        )
    model = ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        max_retries=0,
        timeout=settings.llm_timeout,
    )
    return dict.fromkeys(roles, model)
