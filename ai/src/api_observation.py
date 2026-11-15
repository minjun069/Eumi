"""API 실행 경계의 관측 형식·요청 연결·파일 저장. 업무 판단은 호출자가 전달한다."""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from time import monotonic
from uuid import uuid4

from typing_extensions import TypedDict

from report_html import build_report
from src.execution_trace import (
    TraceRecorder,
    TraceSpan,
    execution_manifest,
    recording,
    trace_output,
    trace_span,
    utc_now,
)
from src.state import report_input, state_adapter

logger = logging.getLogger(__name__)
_request_observation: ContextVar[tuple[TraceSpan, Path] | None] = ContextVar(
    "api_request_observation", default=None
)
_deployment_observation: ContextVar = ContextVar(
    "api_deployment_observation", default=None
)


class RequestOrigin(TypedDict):
    span_id: str
    received_at: str
    trace_file: str


def request_origin() -> RequestOrigin | None:
    observation = _request_observation.get()
    if observation is None:
        return None
    span, folder = observation
    return {
        "span_id": span.entry["id"],
        "received_at": span.entry["started_at"],
        "trace_file": str((folder / "trace.jsonl").resolve()),
    }


def observe_admission(outcome, **details):
    observation = _request_observation.get()
    if observation is not None:
        span, _ = observation
        span.update(output={"outcome": outcome, **details})


def save_request_trace(recorder, folder):
    """HTTP/요청 묶음 관측은 업무 State가 없는 별도 파일로 보존한다."""
    recorder.write_json(folder / "request.json", {"trace": recorder.export()})


def deployment_manifest(settings):
    try:
        return execution_manifest(settings)
    except OSError as exc:
        logger.warning("Deployment diagnostic unavailable type=%s", type(exc).__name__)
        return {"error_type": type(exc).__name__}


class RequestTraceMiddleware:
    """접수 거절과 취소를 포함해 실제 ASGI 요청·응답 경계를 관측한다."""

    def __init__(self, app, settings, manifest, report_path):
        self.app, self.settings, self.manifest = app, settings, manifest
        self.report_path = report_path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (
            scope["path"] == self.report_path
            or scope["path"].startswith("/internal/agent/runs")
        ):
            return await self.app(scope, receive, send)
        received_at, received_clock = utc_now(), monotonic()
        folder = self.settings.output_dir / "requests" / str(uuid4())
        deployment_token = _deployment_observation.set(self.manifest)
        recorder = execution_recorder(self.settings, folder)
        body = bytearray()
        response_bytes = 0
        try:
            with (
                recording(recorder),
                trace_span(
                    "http",
                    "api.request",
                    {"method": scope["method"], "path": scope["path"]},
                ) as span,
            ):
                span.started = received_clock
                span.update(started_at=received_at)
                token = _request_observation.set((span, folder))

                async def observed_receive():
                    message = await receive()
                    if message["type"] == "http.request":
                        body.extend(message.get("body", b""))
                        if not message.get("more_body", False):
                            try:
                                parsed = json.loads(body) if body else None
                            except (ValueError, UnicodeDecodeError):
                                parsed = None
                            span.update(
                                http_request={
                                    "method": scope["method"],
                                    "path": scope["path"],
                                    "body": parsed,
                                    "body_bytes": len(body),
                                }
                            )
                    return message

                async def observed_send(message):
                    nonlocal response_bytes
                    if message["type"] == "http.response.start":
                        span.update(
                            output={
                                **span.entry.get("output", {}),
                                "status_code": message["status"],
                            }
                        )
                    elif message["type"] == "http.response.body":
                        response_bytes += len(message.get("body", b""))
                        if not message.get("more_body", False):
                            span.update(
                                output={
                                    **span.entry.get("output", {}),
                                    "body_bytes": response_bytes,
                                    "body_empty": response_bytes == 0,
                                }
                            )
                    await send(message)

                try:
                    await self.app(scope, observed_receive, observed_send)
                finally:
                    _request_observation.reset(token)
        finally:
            save_request_trace(recorder, folder)
            _deployment_observation.reset(deployment_token)


def execution_recorder(settings, folder):
    recorder = TraceRecorder.from_settings(settings, journal=folder / "trace.jsonl")
    manifest = dict(_deployment_observation.get() or deployment_manifest(settings))
    manifest["request"] = request_origin()
    recorder.write_json(folder / "manifest.json", manifest)
    return recorder


def save_execution_report(state, recorder, folder, failure=None):
    # 관측 파일은 업무 State나 재개 저장소를 대체하지 않는다.
    report = {
        "state": state_adapter.dump_python(state, mode="json"),
        "trace": recorder.export(),
        "failure": failure,
    }
    path = folder / "report.json"
    if not recorder.write_json(path, report):
        return
    try:
        build_report([path], folder / "report.html")
    except OSError:
        logger.warning("Execution diagnostic write failed")


@contextmanager
def trace_notification(path, payload, *, attempt, timeout):
    with trace_span("http", "notification", payload) as span:
        if span:
            span.update(
                http_request={
                    "method": "POST",
                    "path": path,
                    "body": payload,
                    "attempt": attempt,
                    "timeout_seconds": timeout,
                    "authentication": "Bearer",
                }
            )
        yield


def observe_notification(response, *, accepted):
    trace_output(
        {
            "status_code": response.status_code,
            "body_bytes": len(response.content),
            "body_empty": not response.content,
            "accepted": accepted,
        }
    )


@contextmanager
def report_batch_trace(settings, states):
    token = _deployment_observation.set(
        _deployment_observation.get() or deployment_manifest(settings)
    )
    folder = settings.output_dir / "batches" / str(uuid4())
    recorder = execution_recorder(settings, folder)
    try:
        with (
            recording(recorder),
            trace_span(
                "agent",
                "api.report_request",
                {
                    "request": request_origin(),
                    "reports": [
                        {"run_id": s["execution"]["run_id"], **report_input(s)}
                        for s in states
                    ],
                    "concurrency": settings.report_concurrency,
                },
            ) as span,
        ):
            yield span
    finally:
        save_request_trace(recorder, folder)
        _deployment_observation.reset(token)


def observe_report_results(span, states, saved):
    """저장 판정은 실행기가 전달하고 관측 모듈은 표시할 값만 조립한다."""
    span.update(
        output={
            **span.entry.get("output", {}),
            "reports": [
                {
                    "run_id": state["execution"]["run_id"],
                    "status": state["execution"]["status"],
                    "saved": committed,
                }
                for state, committed in zip(states, saved, strict=True)
            ],
        }
    )


def observe_report_completion(span, *, notification_attempted):
    origin = _request_observation.get()
    span.update(
        output={
            "completion_observed_at": utc_now(),
            "request_elapsed_seconds": (
                monotonic() - origin[0].started if origin else None
            ),
            "processing_elapsed_seconds": monotonic() - span.started,
            "notification_attempted": notification_attempted,
        }
    )
