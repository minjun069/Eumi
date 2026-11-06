"""AI 실행 접수, State 기반 실행, DB 커밋 후 POST 알림."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Response
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

from report_html import build_report
from src.agent_nodes import build_nodes, finish
from src.database import (
    Database,
    DatabaseUnavailable,
    QuestionFinished,
    QuestionNotFound,
    question_id,
)
from src.execution_trace import TraceRecorder, recording, trace_span
from src.gemini import create_model
from src.graph import compile_graph
from src.monitoring import (
    create_monitoring,
    record_execution,
    shutdown_monitoring,
    trace_execution,
)
from src.runtime import run_graph
from src.settings import Settings
from src.state import state_adapter

logger = logging.getLogger(__name__)
PositiveId = Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]


@with_config(ConfigDict(extra="forbid"))
class RunRequest(TypedDict):
    conversation_id: UUID
    question_id: PositiveId


@with_config(ConfigDict(extra="forbid"))
class Notification(RunRequest):
    message_id: PositiveId


notification_adapter = TypeAdapter(Notification)


async def notify(client, settings, state, message_id):
    payload = notification_adapter.dump_python(
        notification_adapter.validate_python(
            {
                "conversation_id": state["execution"]["run_id"],
                "question_id": question_id(state),
                "message_id": message_id,
            }
        ),
        mode="json",
    )
    with trace_span("http", "notification", payload) as span:
        result = await client.post(str(settings.notification_url), json=payload)
        if span:
            span.update(output={"status_code": result.status_code})
        if result.status_code != 204 or result.content:
            raise ValueError("Notification must acknowledge with empty HTTP 204")


async def execute(state, *, database, model, client, settings, monitoring):
    run_id = state["execution"]["run_id"]
    folder = settings.output_dir / run_id / str(uuid4())
    secrets = [
        value.get_secret_value()
        for value in (
            settings.api_key,
            settings.database_url,
            settings.langfuse_secret_key,
        )
        if value
    ]
    recorder = TraceRecorder(secrets=secrets, journal=folder / "trace.jsonl")
    failure = None
    with recording(recorder):
        try:
            graph = compile_graph(
                build_nodes(
                    model, database.providers, database.catalog, role="request"
                ),
                finish=finish,
                checkpointer=InMemorySaver(),
            )
            with trace_execution(monitoring, state["execution"]) as (
                config,
                observation,
            ):
                with trace_span("agent", "api.run", {"initial_state": state}) as span:
                    state = await run_graph(graph, state, config)
                    if span:
                        span.update(output=state)
                record_execution(observation, state)
            with trace_span("database", "save_response", {"state": state}) as span:
                message_id = await database.save_response(state)
                if span:
                    span.update(output={"message_id": message_id, "committed": True})
            await notify(client, settings, state, message_id)
        except asyncio.CancelledError:
            failure = {"error_type": "CancelledError"}
            raise
        except Exception as exc:
            failure = {"error_type": type(exc).__name__}
            logger.warning(
                "AI transport failed run_id=%s type=%s", run_id, type(exc).__name__
            )
        finally:
            report = {
                "state": state_adapter.dump_python(state, mode="json"),
                "trace": recorder.export(),
                "failure": failure,
            }
            # 관측 파일은 업무 State나 재개 저장소를 대체하지 않는다.
            path = folder / "report.json"
            path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            build_report([path], folder / "report.html")


def create_app(settings=None, *, database=None, model=None):
    settings = settings or Settings()
    database = database if database is not None else Database(settings)

    @asynccontextmanager
    async def lifespan(app):
        owned_model = model is None
        app.state.model = model if model is not None else create_model(settings)
        app.state.monitoring = create_monitoring(settings)
        # 진행 중인 Task 핸들만 보관한다. 요청·결과의 원본은 각 실행 State다.
        app.state.tasks = {}
        async with httpx.AsyncClient(timeout=settings.notification_timeout) as client:
            app.state.client = client
            try:
                yield
            finally:
                tasks = list(app.state.tasks.values())
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await shutdown_monitoring(app.state.monitoring)
                if owned_model:
                    await app.state.model.http_async_client.aclose()

    app = FastAPI(lifespan=lifespan)

    def finished(run_id, task):
        app.state.tasks.pop(run_id, None)
        if not task.cancelled() and task.exception():
            logger.error(
                "AI background task failed run_id=%s type=%s",
                run_id,
                type(task.exception()).__name__,
            )

    @app.post("/internal/agent/runs", status_code=202, response_class=Response)
    async def start(body: RunRequest):
        if settings.notification_url is None:
            raise HTTPException(503, "Notification URL is not configured")
        run_id = str(body["conversation_id"])
        if run_id in app.state.tasks:
            raise HTTPException(409, "Conversation is already running")
        # await 중 같은 대화가 접수되지 않도록 준비 단계도 Task로 예약한다.
        app.state.tasks[run_id] = asyncio.current_task()
        try:
            state = await database.load_question(
                body["conversation_id"], body["question_id"]
            )
            state = state_adapter.validate_python(state)
            task = asyncio.create_task(
                execute(
                    state,
                    database=database,
                    model=app.state.model,
                    client=app.state.client,
                    settings=settings,
                    monitoring=app.state.monitoring,
                )
            )
            app.state.tasks[run_id] = task
            task.add_done_callback(lambda task: finished(run_id, task))
        except QuestionNotFound:
            app.state.tasks.pop(run_id, None)
            raise HTTPException(404, "Question not found") from None
        except QuestionFinished:
            app.state.tasks.pop(run_id, None)
            raise HTTPException(409, "Question already finished") from None
        except (DatabaseUnavailable, psycopg.Error):
            app.state.tasks.pop(run_id, None)
            raise HTTPException(503, "Database unavailable") from None
        except BaseException:
            app.state.tasks.pop(run_id, None)
            raise
        return Response(status_code=202)

    return app
