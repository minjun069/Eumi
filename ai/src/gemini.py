"""Agent와 OpenAI Responses API 간의 호출·응답 처리를 담당한다."""

from time import monotonic

import httpx
from langchain_core.messages import AIMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_openai import ChatOpenAI
from pydantic import TypeAdapter
from typing_extensions import TypedDict

from src.execution_trace import (
    capture_http_request,
    capture_http_response,
    trace_output,
    trace_span,
)
from src.settings import Settings


class ModelUsage(TypedDict):
    model: str
    tokens: UsageMetadata | dict[str, int]
    elapsed_seconds: float


def create_model(settings: Settings):
    if not settings.api_key or not settings.api_key.get_secret_value().strip():
        raise ValueError("SETTINGS_API_KEY is required")
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=str(settings.base_url),
        use_responses_api=True,
        use_previous_response_id=False,
        store=False,
        timeout=settings.llm_timeout,
        max_retries=0,
        max_tokens=8192,
        http_async_client=httpx.AsyncClient(
            event_hooks={
                "request": [capture_http_request],
                "response": [capture_http_response],
            }
        ),
    )


async def _raw_response(model, adapter, messages, config, *, strict):
    structured = model.with_structured_output(
        adapter.json_schema(),
        method="json_schema",
        strict=strict,
        include_raw=True,
    )
    result = await structured.ainvoke(messages, config)
    response = result["raw"]
    trace_output(build=lambda: {"sdk_response": response.model_dump(mode="json")})
    return response


def _usage(response: AIMessage, started: float) -> ModelUsage:
    return {
        "model": response.response_metadata.get("model_name", "unknown"),
        "tokens": response.usage_metadata or {},
        "elapsed_seconds": round(monotonic() - started, 3),
    }


async def raw_call(
    model, schema, messages, config, *, strict=False
) -> tuple[AIMessage, ModelUsage]:
    """서비스와 같은 요청으로 모델 원문만 반환한다. 업무 결과 검증은 하지 않는다."""
    adapter = TypeAdapter(schema)
    started = monotonic()
    with trace_span(
        "model",
        schema.__name__,
        {
            "messages": [m.model_dump(mode="json") for m in messages],
            "response_schema": adapter.json_schema(),
        },
    ):
        response = await _raw_response(model, adapter, messages, config, strict=strict)
    return response, _usage(response, started)


async def structured_call(model, schema, messages, config, *, strict=False):
    """Validate external JSON at the model boundary; never log credentials."""
    adapter = TypeAdapter(schema)
    started = monotonic()
    with trace_span(
        "model",
        schema.__name__,
        {
            "messages": [m.model_dump(mode="json") for m in messages],
            "response_schema": adapter.json_schema(),
        },
    ):
        response = await _raw_response(model, adapter, messages, config, strict=strict)
        # 원문을 검증해 파서의 JSON 보정으로 기존 검사가 약해지지 않게 한다.
        value = adapter.validate_json(response.text)
        trace_output(
            build=lambda: {
                "sdk_response": response.model_dump(mode="json"),
                "validated": value,
            }
        )
    return value, _usage(response, started)
