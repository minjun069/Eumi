"""Agent와 OpenAI Responses API 간의 호출·응답 처리를 담당한다."""

from time import monotonic

import httpx
from langchain_openai import ChatOpenAI
from pydantic import TypeAdapter

from src.execution_trace import capture_http_request, capture_http_response, trace_span
from src.settings import Settings


def create_model(settings: Settings):
    if not settings.api_key or not settings.api_key.get_secret_value().strip():
        raise ValueError("SETTINGS_API_KEY is required")
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url="https://api.openai.com/v1",
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


async def structured_call(model, schema, messages, config, *, tools=None):
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
    ) as span:
        # RunnableBinding에 with_structured_output을 바로 호출하면 도구 설정이
        # 사라진다. 바인딩한 전송 설정을 출력 설정과 같은 호출에 적용한다.
        # 도구 실행은 선택 JSON을 기록한 뒤 기존 업무 노드가 수행한다.
        bindings = (
            model.bind_tools(tools, tool_choice="none", strict=False).kwargs
            if tools
            else {}
        )
        structured = model.with_structured_output(
            adapter.json_schema(),
            method="json_schema",
            strict=False,
            include_raw=True,
            **bindings,
        )
        result = await structured.ainvoke(messages, config)
        response = result["raw"]
        if span:
            span.update(output={"sdk_response": response.model_dump(mode="json")})
        # 원문을 검증해 파서의 JSON 보정으로 기존 검사가 약해지지 않게 한다.
        value = adapter.validate_json(response.text)
        if span:
            span.update(
                output={
                    "sdk_response": response.model_dump(mode="json"),
                    "validated": value,
                }
            )
    return value, {
        "model": response.response_metadata.get("model_name", "unknown"),
        "tokens": response.usage_metadata or {},
        "elapsed_seconds": round(monotonic() - started, 3),
    }
