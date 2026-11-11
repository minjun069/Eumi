"""실제 HTTP 어댑터의 선택 형식과 도구 입력 검증 경계를 확인한다."""

import json

import httpx
import pytest

from experiments.scenario_fixtures import CATALOG, PROVIDERS
from src.agent_nodes import build_nodes
from src.gemini import create_model
from src.settings import Settings
from tests.helpers import initial


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments,valid",
    [
        (json.dumps({"target": "D3", "limit": 1}), True),
        ("{", False),
        ("[]", False),
        (json.dumps({"target": "D3", "limit": 0}), False),
    ],
)
async def test_strict_selection_transport_preserves_tool_validation(
    monkeypatch, all_tableau_views, arguments, valid
):
    requests = []
    provider_calls = []
    choice = {
        "name": "query_data",
        "arguments_json": arguments,
        "reason": "등록된 자료를 조회한다.",
    }

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_selection",
                "object": "response",
                "created_at": 1,
                "model": "gpt-6-sol",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_selection",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(choice),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    original_client = httpx.AsyncClient

    class Client(original_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handle), **kwargs)

    def provider():
        provider_calls.append("D3")
        return PROVIDERS["D3"]()

    monkeypatch.setattr("src.gemini.httpx.AsyncClient", Client)
    model = create_model(Settings(_env_file=None, api_key="test-secret"))
    state = initial()
    act = build_nodes(model, {"D3": provider}, CATALOG, role="interpretation")["act"]
    try:
        command = await act(state, {})
    finally:
        await model.http_async_client.aclose()

    assert len(requests) == 1
    body = requests[0]
    assert "tools" not in body and "tool_choice" not in body
    response_format = body["text"]["format"]
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    schema = response_format["schema"]
    assert set(schema["required"]) == {"name", "arguments_json", "reason"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["arguments_json"]["type"] == "string"
    definitions = json.JSONDecoder().raw_decode(
        body["input"][0]["content"].split("[도구 명세]\n", 1)[1]
    )[0]
    assert {item["function"]["name"] for item in definitions} == {
        "query_data",
        "process_data",
    }
    assert "[도구 명세]" not in body["input"][1]["content"]
    records = command.update["results"]
    assert command.goto == "decide"
    assert records[0]["decision"] == "selection"
    assert records[0]["output"]["arguments_json"] == arguments
    if valid:
        assert provider_calls == ["D3"]
        called = next(item for item in records if item["decision"] == "call")
        assert called["outcome"] == "success"
        assert called["output"]["returned"] == 1
        assert called["output"]["data"]["rows"] == PROVIDERS["D3"]()["rows"][:1]
    else:
        assert not provider_calls
        assert any(item["outcome"] == "failure" for item in records)
