"""Agent 실행 과정의 상세 입출력과 오류를 로컬에 기록한다."""

import json
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, NotRequired
from uuid import uuid4

from pydantic import SecretStr, ValidationError
from pydantic_core import to_jsonable_python
from typing_extensions import TypedDict


class SpanRecord(TypedDict):
    id: str
    parent_id: str | None
    sequence: int
    kind: str
    name: str
    started_at: str
    ended_at: str | None
    elapsed_seconds: float | None
    status: str
    input: Any
    output: NotRequired[Any]
    error: NotRequired[dict]
    http_request: NotRequired[dict]
    http_response: NotRequired[dict]


_recorder: ContextVar = ContextVar("execution_recorder", default=None)
_span: ContextVar = ContextVar("execution_span", default=None)
SECRET_FIELDS = {
    "api_key",
    "authorization",
    "x-api-key",
    "x-goog-api-key",
    "langfuse_public_key",
    "langfuse_secret_key",
    "cookie",
    "set-cookie",
}


def utc_now():
    return datetime.now(UTC).isoformat()


def safe_settings(settings):
    """Exclude credentials before serialization, including the public telemetry key."""
    return settings.model_dump(mode="json", exclude=SECRET_FIELDS)


def error_info(exc):
    info = {
        "type": type(exc).__name__,
        "code": getattr(exc, "code", None),
        "http_status": getattr(exc, "status_code", None),
    }
    if isinstance(exc, ValidationError):
        info["validation_errors"] = exc.errors(include_url=False, include_context=False)
    if exc.__cause__ is not None and exc.__cause__ is not exc:
        info["cause"] = error_info(exc.__cause__)
    # Provider exception strings may echo authentication headers. The sanitized
    # HTTP response and structured validation errors supply diagnostic detail.
    return info


class TraceRecorder:
    def __init__(self, *, secrets=(), journal: Path | None = None):
        self.spans: list[SpanRecord] = []
        self.secrets = tuple(s for s in secrets if s)
        self.journal = journal
        if journal:
            journal.parent.mkdir(parents=True, exist_ok=True)
            journal.write_text("", encoding="utf-8")

    def snapshot(self, value):
        def scrub(item):
            if isinstance(item, SecretStr):
                return "[REDACTED]"
            if isinstance(item, dict):
                return {
                    str(k): "[REDACTED]"
                    if str(k).lower() in SECRET_FIELDS
                    else scrub(v)
                    for k, v in item.items()
                }
            if isinstance(item, (list, tuple)):
                return [scrub(v) for v in item]
            if isinstance(item, str):
                for secret in self.secrets:
                    item = item.replace(secret, "[REDACTED]")
                return item
            return item

        # A detached JSON snapshot, including message metadata and full artifacts.
        return scrub(to_jsonable_python(scrub(value)))

    def persist(self, event, entry):
        if self.journal:
            with self.journal.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps({"event": event, "span": entry}, ensure_ascii=False)
                    + "\n"
                )
                stream.flush()

    def export(self):
        counts = Counter(s["kind"] for s in self.spans)
        models = [s for s in self.spans if s["kind"] == "model"]
        return {
            "version": "local-execution-trace-v1",
            "scope": (
                "호출 직전 입력·반환값·노드 갱신의 로컬 스냅샷. "
                "State와 모델 컨텍스트에 재주입하지 않음."
            ),
            "limitations": [
                "인증키·인증 헤더·쿠키는 제외 또는 [REDACTED] 처리한다.",
                "모델 내부 계산·비공개 추론과 공급자 서버 내부 설정은 관측할 수 없다.",
                "HTTP 본문은 SDK 송수신 JSON이다. TLS·압축 바이트는 기록하지 않는다.",
                "미지정 공급자 기본값은 추정하지 않는다. 반환된 메타데이터를 보존한다.",
                "외부 예외 문자열 제외. 오류 종류·코드·HTTP 응답·검증 상세를 기록한다.",
            ],
            "counts": dict(counts),
            "coverage": {
                "model_attempts": len(models),
                "model_inputs": sum("messages" in s["input"] for s in models),
                "http_requests": sum("http_request" in s for s in models),
                "http_responses": sum("http_response" in s for s in models),
                "sdk_responses": sum("output" in s for s in models),
                "model_errors": sum(s["status"] == "error" for s in models),
                "unfinished_spans": sum(s["ended_at"] is None for s in self.spans),
            },
            "spans": self.spans,
        }


@contextmanager
def recording(recorder):
    token = _recorder.set(recorder)
    parent = _span.set(None)
    try:
        yield recorder
    finally:
        _span.reset(parent)
        _recorder.reset(token)


class TraceSpan:
    def __init__(self, recorder, kind, name, inputs):
        self.recorder = recorder
        parent = _span.get()
        self.entry: SpanRecord = {
            "id": uuid4().hex,
            "parent_id": parent.entry["id"] if parent else None,
            "sequence": len(recorder.spans) + 1,
            "kind": kind,
            "name": name,
            "started_at": utc_now(),
            "ended_at": None,
            "elapsed_seconds": None,
            "status": "running",
            "input": recorder.snapshot(inputs),
        }
        self.started = monotonic()
        recorder.spans.append(self.entry)
        recorder.persist("start", self.entry)

    def update(self, **values):
        self.entry.update(self.recorder.snapshot(values))
        self.recorder.persist("update", self.entry)

    def finish(self, error=None):
        self.entry.update(
            ended_at=utc_now(),
            elapsed_seconds=round(monotonic() - self.started, 6),
            status=(
                "interrupted"
                if type(error).__name__ == "GraphInterrupt"
                else "error"
                if error
                else "success"
            ),
        )
        if error:
            self.entry["error"] = self.recorder.snapshot(error_info(error))
        self.recorder.persist("end", self.entry)


@contextmanager
def trace_span(kind, name, inputs):
    recorder = _recorder.get()
    if recorder is None:
        yield None
        return
    span = TraceSpan(recorder, kind, name, inputs)
    token = _span.set(span)
    try:
        yield span
    except BaseException as exc:
        span.finish(exc)
        raise
    else:
        span.finish()
    finally:
        _span.reset(token)


async def capture_http_request(request):
    span = _span.get()
    if span is not None and span.entry["kind"] == "model":
        span.update(
            http_request={
                "method": request.method,
                "endpoint": f"{request.url.scheme}://{request.url.host}{request.url.path}",
                "content_type": request.headers.get("content-type"),
                "body": json.loads(request.content),
                "body_text": request.content.decode("utf-8"),
            }
        )


async def capture_http_response(response):
    span = _span.get()
    if span is not None and span.entry["kind"] == "model":
        await response.aread()
        try:
            body = response.json()
        except ValueError:
            body = response.text
        span.update(
            http_response={
                "status_code": response.status_code,
                "headers": {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() in {"content-type", "x-request-id", "date"}
                },
                "body": body,
                "body_text": response.text,
            }
        )
