"""왕복 검증기의 HTTP 수신·재조회 증거를 수집하고 독립 파일로 보존한다."""

import json
import logging
from contextlib import contextmanager
from typing import Any, Literal, NotRequired
from uuid import uuid4

import httpx
from pydantic import TypeAdapter
from typing_extensions import TypedDict

from src.execution_trace import TraceRecorder, utc_now

logger = logging.getLogger(__name__)


class HTTPResponseEvidence(TypedDict):
    status_code: int
    body: str
    body_bytes: int


class HTTPExchangeEvidence(TypedDict):
    started_at: str
    ended_at: str | None
    method: str
    path: str
    request_body: Any
    response: HTTPResponseEvidence | None
    error_type: str | None
    authorization_scheme: NotRequired[str | None]
    authorization_matches: NotRequired[bool]


class DatabaseReadEvidence(TypedDict):
    target: str
    started_at: str
    observed_at: str | None
    rows: list[dict[str, Any]] | None
    error_type: str | None


class RoundtripEvidence(TypedDict):
    id: str
    started_at: str
    ended_at: str | None
    storage: Literal["temporary_json", "postgresql"]
    storage_reference: str
    api_exchanges: list[HTTPExchangeEvidence]
    notifications: list[HTTPExchangeEvidence]
    database_reads: list[DatabaseReadEvidence]
    report_paths: list[str]
    passed: bool | None
    error_type: str | None


evidence_adapter = TypeAdapter(RoundtripEvidence)


@contextmanager
def roundtrip_evidence(output, *, storage, storage_reference, settings=None):
    """실험 증거를 업무 상태와 분리하고 실패·재실행 기록도 보존한다."""
    evidence: RoundtripEvidence = {
        "id": uuid4().hex,
        "started_at": utc_now(),
        "ended_at": None,
        "storage": storage,
        "storage_reference": storage_reference,
        "api_exchanges": [],
        "notifications": [],
        "database_reads": [],
        "report_paths": [],
        "passed": None,
        "error_type": None,
    }
    path = output / "roundtrips" / evidence["id"] / "evidence.json"
    failed = False
    try:
        yield evidence, path
    except BaseException as exc:
        failed = True
        evidence.update(passed=False, error_type=type(exc).__name__)
        raise
    finally:
        evidence["ended_at"] = utc_now()
        recorder = (
            TraceRecorder.from_settings(settings)
            if settings is not None
            else TraceRecorder()
        )
        try:
            recorder.write_json(
                path, evidence_adapter.validate_python(evidence), strict=True
            )
        except OSError as exc:
            logger.warning(
                "Roundtrip evidence write failed id=%s error_type=%s",
                evidence["id"],
                type(exc).__name__,
            )
            if not failed:
                raise


def http_exchange(method, path, body):
    return HTTPExchangeEvidence(
        started_at=utc_now(),
        ended_at=None,
        method=method,
        path=path,
        request_body=body,
        response=None,
        error_type=None,
    )


async def observed_post(client, url, body, evidence):
    exchange = http_exchange("POST", httpx.URL(url).path, body)
    evidence["api_exchanges"].append(exchange)
    try:
        response = await client.post(url, json=body)
        exchange["response"] = {
            "status_code": response.status_code,
            "body": response.text,
            "body_bytes": len(response.content),
        }
        return response
    except BaseException as exc:
        exchange["error_type"] = type(exc).__name__
        raise
    finally:
        exchange["ended_at"] = utc_now()


@contextmanager
def database_read(evidence, target):
    observation: DatabaseReadEvidence = {
        "target": target,
        "started_at": utc_now(),
        "observed_at": None,
        "rows": None,
        "error_type": None,
    }
    evidence["database_reads"].append(observation)
    try:
        yield observation
    except BaseException as exc:
        observation["error_type"] = type(exc).__name__
        raise
    finally:
        observation["observed_at"] = utc_now()


class NotificationEvidence:
    """로컬 수신기의 실제 ASGI 요청·응답만 관측하며 인증값은 저장하지 않는다."""

    def __init__(self, app, *, settings, evidence):
        self.app = app
        self.settings = settings
        self.evidence = evidence

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        exchange = http_exchange(scope["method"], scope["path"], None)
        authorization = (
            dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        )
        exchange["authorization_scheme"] = (
            "Bearer" if authorization.startswith("Bearer ") else None
        )
        exchange["authorization_matches"] = authorization == (
            "Bearer " + self.settings.backend_token.get_secret_value()
        )
        self.evidence["notifications"].append(exchange)
        request_body, response_body = bytearray(), bytearray()

        async def observed_receive():
            message = await receive()
            if message["type"] == "http.request":
                request_body.extend(message.get("body", b""))
            return message

        async def observed_send(message):
            if message["type"] == "http.response.start":
                exchange["response"] = {
                    "status_code": message["status"],
                    "body": "",
                    "body_bytes": 0,
                }
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, observed_receive, observed_send)
        except BaseException as exc:
            exchange["error_type"] = type(exc).__name__
            raise
        finally:
            try:
                exchange["request_body"] = json.loads(request_body)
            except (ValueError, UnicodeDecodeError):
                exchange["request_body"] = request_body.decode(errors="replace")
            if exchange["response"] is not None:
                exchange["response"].update(
                    body=response_body.decode(errors="replace"),
                    body_bytes=len(response_body),
                )
            exchange["ended_at"] = utc_now()
