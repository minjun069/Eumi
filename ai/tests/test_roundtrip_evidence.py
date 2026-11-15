"""왕복 증거는 HTTP 실패·인증 불일치·재조회 실패도 원본 그대로 보존한다."""

import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Response
from pydantic import SecretStr

from experiments import api_roundtrip
from experiments import evidence as evidence_module
from experiments.api_roundtrip import roundtrip
from experiments.evidence import (
    NotificationEvidence,
    database_read,
    observed_post,
    roundtrip_evidence,
)
from src.settings import Settings
from tests.helpers import DONE, ScriptedModel


def test_saved_evidence_scrubs_credentials_without_changing_observed_values(tmp_path):
    settings = Settings(_env_file=None, api_key=SecretStr("private-db-marker"))
    with roundtrip_evidence(
        tmp_path,
        storage="temporary_json",
        storage_reference="fixture.json",
        settings=settings,
    ) as (evidence, path):
        with database_read(evidence, "public.ai_message") as observation:
            observation["rows"] = [{"content": "observed private-db-marker value"}]
        assert observation["rows"][0]["content"] == "observed private-db-marker value"
    assert observation["rows"][0]["content"] == "observed private-db-marker value"
    raw = path.read_text("utf-8")
    assert "private-db-marker" not in raw
    stored = json.loads(raw)
    assert stored["database_reads"][0]["rows"] == [
        {"content": "observed [REDACTED] value"}
    ]


def test_evidence_write_failure_preserves_original_error(monkeypatch, tmp_path, caplog):
    write_error = OSError("private storage path")

    def fail_write(*args, **kwargs):
        raise write_error

    monkeypatch.setattr(evidence_module.TraceRecorder, "write_json", fail_write)
    original = httpx.ConnectError("private endpoint")
    with pytest.raises(httpx.ConnectError) as caught:
        with roundtrip_evidence(
            tmp_path, storage="temporary_json", storage_reference="fixture.json"
        ):
            raise original
    assert caught.value is original
    assert "error_type=OSError" in caplog.text
    assert "private storage path" not in caplog.text
    assert "private endpoint" not in caplog.text

    with pytest.raises(OSError) as caught:
        with roundtrip_evidence(
            tmp_path, storage="temporary_json", storage_reference="fixture.json"
        ) as (evidence, _):
            evidence["passed"] = True
    assert caught.value is write_error


@pytest.mark.asyncio
async def test_receiver_evidence_captures_actual_validation_and_auth(tmp_path):
    settings = Settings(_env_file=None, backend_token=SecretStr("private-token"))
    app = FastAPI()

    @app.post("/notification")
    async def receive(body: dict):
        return Response(status_code=204)

    with roundtrip_evidence(
        tmp_path, storage="temporary_json", storage_reference="fixture.json"
    ) as (evidence, path):
        receiver = NotificationEvidence(app, settings=settings, evidence=evidence)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=receiver), base_url="http://test"
        ) as client:
            response = await client.post(
                "/notification",
                json={"messageId": 7},
                headers={"Authorization": "Bearer private-token"},
            )
            assert response.status_code == 204
            rejected = await client.post(
                "/notification",
                json=["invalid payload"],
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert rejected.status_code == 422
    raw = path.read_text("utf-8")
    assert "private-token" not in raw and "wrong-token" not in raw
    observed = json.loads(raw)["notifications"]
    assert observed[0]["request_body"] == {"messageId": 7}
    assert observed[0]["authorization_matches"] is True
    assert observed[0]["response"] == {"status_code": 204, "body": "", "body_bytes": 0}
    assert observed[1]["authorization_matches"] is False
    assert observed[1]["response"]["status_code"] == 422
    assert observed[1]["response"]["body_bytes"] == len(rejected.content)
    assert json.loads(observed[1]["response"]["body"]) == rejected.json()
    assert all(item["started_at"] <= item["ended_at"] for item in observed)


@pytest.mark.asyncio
async def test_api_transport_and_database_failure_evidence(tmp_path):
    def unavailable(request):
        raise httpx.ConnectError("secret endpoint must not be logged", request=request)

    with (
        pytest.raises(httpx.ConnectError),
        roundtrip_evidence(
            tmp_path, storage="postgresql", storage_reference="public.ai_message"
        ) as (evidence, path),
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(unavailable)
        ) as client:
            await observed_post(client, "http://test/runs", {"messageId": 7}, evidence)
    stored = json.loads(path.read_text("utf-8"))
    assert stored["passed"] is False
    assert stored["error_type"] == "ConnectError"
    assert stored["api_exchanges"][0]["response"] is None
    assert stored["api_exchanges"][0]["error_type"] == "ConnectError"
    assert "secret endpoint" not in path.read_text("utf-8")

    with (
        pytest.raises(PermissionError),
        roundtrip_evidence(
            tmp_path, storage="postgresql", storage_reference="public.ai_message"
        ) as (evidence, path),
    ):
        with database_read(evidence, "public.ai_message"):
            raise PermissionError("private database details")
    readback = json.loads(path.read_text("utf-8"))["database_reads"][0]
    assert readback["rows"] is None
    assert readback["error_type"] == "PermissionError"
    assert readback["observed_at"] is not None
    assert len(list(tmp_path.glob("roundtrips/*/evidence.json"))) == 2


@pytest.mark.asyncio
async def test_api_roundtrip_setup_failure_is_preserved(tmp_path):
    database = tmp_path / "existing.json"
    database.write_text("[]", encoding="utf-8")
    with pytest.raises(FileExistsError):
        await roundtrip(
            tmp_path / "runs",
            conversation_id=uuid4(),
            question_id=101,
            file_db=database,
        )
    path = next((tmp_path / "runs").glob("roundtrips/*/evidence.json"))
    evidence = json.loads(path.read_text("utf-8"))
    assert evidence["error_type"] == "FileExistsError"
    assert evidence["storage"] == "temporary_json"
    assert evidence["storage_reference"] == str(database.resolve())
    assert evidence["api_exchanges"] == []


@pytest.mark.asyncio
async def test_api_roundtrip_records_independent_message_values(monkeypatch, tmp_path):
    conversation_id = uuid4()
    historical = tmp_path / "runs" / str(conversation_id) / "old" / "report.json"
    historical.parent.mkdir(parents=True)
    historical.write_text("historical output is not this execution", encoding="utf-8")
    model = ScriptedModel(
        [
            {
                "request": {"goal": "서비스 안내"},
                "reason": "자료 조회가 필요 없는 안내",
            },
            DONE,
            {
                "content": "지역 분석 결과를 설명합니다.",
                "artifact_ids": [],
                "status": "completed",
                "reason": "안내 완료",
            },
        ]
    )
    model.model_copy = lambda **kwargs: model
    model.http_async_client = httpx.AsyncClient()
    monkeypatch.setattr(api_roundtrip, "create_model", lambda settings: model)
    result = await roundtrip(
        tmp_path / "runs",
        conversation_id=conversation_id,
        question_id=101,
        file_db=tmp_path / "messages.json",
        question="서비스를 안내해 주세요.",
    )
    path = next((tmp_path / "runs").glob("roundtrips/*/evidence.json"))
    evidence = json.loads(path.read_text("utf-8"))
    assert result["evidence"] == str(path.resolve())
    assert result["status"] == "completed"
    assert evidence["report_paths"] == [result["report"]]
    assert str(historical.resolve()) not in evidence["report_paths"]
    assert evidence["api_exchanges"][0]["response"]["status_code"] == 202
    assert len(evidence["database_reads"]) == len(evidence["notifications"]) >= 1
    for observation, notification in zip(
        evidence["database_reads"], evidence["notifications"], strict=True
    ):
        row = observation["rows"][0]
        assert row["message_id"] == notification["request_body"]["messageId"]
        assert row["question_id"] == 101
        assert row["content"]
        assert observation["observed_at"] <= notification["ended_at"]
        assert notification["response"]["status_code"] == 204
    assert evidence["database_reads"][-1]["rows"][0]["status"] == "완료"


@pytest.mark.asyncio
async def test_acknowledged_without_new_execution_does_not_reuse_old_report(
    monkeypatch, tmp_path
):
    conversation_id = uuid4()
    historical = tmp_path / "runs" / str(conversation_id) / "old" / "report.json"
    historical.parent.mkdir(parents=True)
    historical.write_text("historical output is not this execution", encoding="utf-8")
    app = FastAPI()
    app.state.tasks = {}

    @app.post("/internal/agent/runs")
    async def already_finished():
        return Response(status_code=202)

    model = ScriptedModel([])
    model.model_copy = lambda **kwargs: model
    model.http_async_client = httpx.AsyncClient()
    monkeypatch.setattr(api_roundtrip, "create_model", lambda settings: model)
    monkeypatch.setattr(api_roundtrip, "create_app", lambda *args, **kwargs: app)
    with pytest.raises(RuntimeError, match="새 실행 기록 없음"):
        await roundtrip(
            tmp_path / "runs",
            conversation_id=conversation_id,
            question_id=101,
            file_db=tmp_path / "messages.json",
        )
    path = next((tmp_path / "runs").glob("roundtrips/*/evidence.json"))
    evidence = json.loads(path.read_text("utf-8"))
    assert evidence["passed"] is False
    assert evidence["api_exchanges"][0]["response"]["status_code"] == 202
    assert evidence["report_paths"] == []
    assert not (tmp_path / "runs" / "roundtrip.json").exists()
