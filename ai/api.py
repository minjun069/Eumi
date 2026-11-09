"""AI 실행 접수, State 기반 실행, DB 커밋 후 POST 알림."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from functools import partial
from time import monotonic
from typing import Annotated, NotRequired
from uuid import UUID, uuid4

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

from report_html import build_report
from src.agent_nodes import build_nodes, finish, publish_report
from src.database import (
    Database,
    DatabaseUnavailable,
    QuestionFinished,
    QuestionNotFound,
    question_id,
)
from src.exceptions import LimitReached
from src.execution import consume, finalizing, record
from src.execution_trace import TraceRecorder, recording, trace_span
from src.gemini import create_model
from src.graph import compile_graph
from src.monitoring import (
    create_monitoring,
    record_execution,
    shutdown_monitoring,
    trace_execution,
)
from src.runtime import execution_config
from src.settings import Settings
from src.state import (
    DongCode,
    DongCodes,
    Month,
    Text,
    create_state,
    report_artifact,
    report_input,
    report_input_adapter,
    state_adapter,
)

logger = logging.getLogger(__name__)
REPORT_PATH = "/internal/insight-reports/runs"
PositiveId = Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]


@with_config(ConfigDict(extra="forbid"))
class Notification(TypedDict):
    conversationId: UUID
    messageId: PositiveId


@with_config(ConfigDict(extra="forbid"))
class ScreenContext(TypedDict):
    dongCode: NotRequired[DongCode]
    month: NotRequired[Month]


@with_config(ConfigDict(extra="forbid"))
class RunRequest(Notification):
    context: NotRequired[ScreenContext]


@with_config(ConfigDict(extra="forbid", strict=True))
class ReportRequest(TypedDict):
    requestId: Text
    month: Month
    dongCodes: DongCodes


report_request_adapter = TypeAdapter(ReportRequest)
notification_adapter = TypeAdapter(Notification)
run_request_adapter = TypeAdapter(RunRequest)


async def notify(client, settings, state, path, payload):
    """커밋한 결과의 전송만 최대 두 번 시도한다. 4xx·잘못된 204는 재시도하지 않는다."""
    for _ in range(2):
        item = record(
            "transport",
            "notification",
            path,
            action={"name": "POST", "arguments": payload},
            success=False,
        )
        state["results"].append(item)
        try:
            with trace_span("http", "notification", payload) as span:
                async with asyncio.timeout(settings.notification_timeout):
                    result = await client.post(
                        str(settings.backend_url).rstrip("/") + path,
                        json=payload,
                        headers={
                            "Authorization": "Bearer "
                            + settings.backend_token.get_secret_value()
                        },
                    )
                if span:
                    span.update(output={"status_code": result.status_code})
                if result.status_code == 204 and not result.content:
                    item["outcome"] = "success"
                    return True
                if result.status_code < 500:
                    break
        except (httpx.TransportError, TimeoutError):
            pass
    logger.warning(
        "Backend notification failed path=%s run_id=%s",
        path,
        state["execution"]["run_id"],
    )
    return False


async def notify_message(state, message_id, *, client, settings):
    return await notify(
        client,
        settings,
        state,
        "/api/internal/agent/notifications",
        {
            "conversationId": state["execution"]["run_id"],
            "messageId": message_id,
        },
    )


async def commit_response(state, *, database, client, settings):
    async with asyncio.timeout(3):
        with trace_span("database", "save_response", {"state": state}) as span:
            message_id = await database.save_response(state)
            if span:
                span.update(output={"message_id": message_id, "committed": True})
    await notify_message(state, message_id, client=client, settings=settings)


async def publish_progress(state, name, *, database, client, settings):
    if name is not None:
        label = {
            "interpret": "질문 이해",
            "act": "자료 조회·작업 실행",
            "decide": "진행 판단",
            "compose": "답변 작성",
            "ask": "추가 질문 작성",
        }[name]
        state["response"] = {
            "id": str(uuid4()),
            "kind": "progress",
            "label": label,
            "content": label,
            "artifacts": (state["response"] or {}).get("artifacts", []),
        }
    state["execution"]["status"] = "running"
    await commit_response(state, database=database, client=client, settings=settings)


def execution_recorder(settings, folder):
    secrets = [
        value.get_secret_value()
        for value in (
            settings.api_key,
            settings.database_url,
            settings.langfuse_secret_key,
            settings.backend_token,
        )
        if value
    ]
    return TraceRecorder(secrets=secrets, journal=folder / "trace.jsonl")


def save_execution_report(state, recorder, folder, failure=None):
    # 관측 파일은 업무 State나 재개 저장소를 대체하지 않는다.
    report = recorder.snapshot(
        {
            "state": state_adapter.dump_python(state, mode="json"),
            "trace": recorder.export(),
            "failure": failure,
        }
    )
    path = folder / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    build_report([path], folder / "report.html")


async def execute(state, *, database, model, client, settings, monitoring):
    started = monotonic()
    run_id = state["execution"]["run_id"]
    folder = settings.output_dir / run_id / str(uuid4())
    recorder = execution_recorder(settings, folder)
    failure = None
    with recording(recorder):
        try:
            graph = compile_graph(
                build_nodes(
                    model, database.providers, database.catalog, role="request"
                ),
                finish=finish,
                checkpointer=InMemorySaver(),
                publish=partial(
                    publish_progress,
                    database=database,
                    client=client,
                    settings=settings,
                ),
            )
            with trace_execution(monitoring, state["execution"]) as (
                config,
                observation,
            ):
                budget = state["execution"]["budget"]
                budget["active_seconds"]["used"] += monotonic() - started
                seconds = sum(
                    budget[k]["limit"] - budget[k]["used"]
                    for k in ("active_seconds", "final_active_seconds")
                )
                # 최종 커밋에 3초를 남긴다. DB 읽기 시간은 접수 시 사용량에 반영한다.
                async with asyncio.timeout(max(0, seconds - 3)):
                    with trace_span(
                        "agent", "api.run", {"initial_state": state}
                    ) as span:
                        async for value in graph.astream(
                            state,
                            execution_config(run_id, config),
                            stream_mode="values",
                        ):
                            state.update(
                                state_adapter.validate_python(
                                    {
                                        k: v
                                        for k, v in value.items()
                                        if k != "__interrupt__"
                                    }
                                )
                            )
                        if span:
                            span.update(output=state)
                record_execution(observation, state)
        except asyncio.CancelledError:
            state["execution"]["status"] = "cancelled"
        except Exception as exc:
            failure = {"error_type": type(exc).__name__}
            state["execution"].update(
                status="failed",
                error={
                    "code": "deadline_exceeded"
                    if isinstance(exc, TimeoutError)
                    else "runtime_error",
                    "cause": "실행을 완료하지 못했습니다.",
                },
            )
        finally:
            try:
                # 끝 행 커밋 뒤의 전송 실패는 질문 상태를 되돌리지 않는다.
                await commit_response(
                    state, database=database, client=client, settings=settings
                )
            except psycopg.errors.UniqueViolation:
                pass
            except Exception as exc:
                failure = {"error_type": type(exc).__name__}
                logger.warning(
                    "AI save failed run_id=%s type=%s", run_id, type(exc).__name__
                )
            save_execution_report(state, recorder, folder, failure)


def start_month(month: str) -> str:
    year, number = map(int, month.split("-"))
    year, offset = divmod(year * 12 + number - 1 - 5, 12)
    return f"{year:04d}-{offset + 1:02d}"


def create_report_states(body, settings):
    body = report_request_adapter.validate_python(body)
    states = []
    for code in body["dongCodes"]:
        state = create_state(
            {
                "goal": f"{body['month']} {code} 행정동 분석 보고서 생성",
                "constraints": {
                    "required": [
                        f"추세 기간: {start_month(body['month'])}~{body['month']}",
                        "서로 다른 상세 뷰 3개, 검증된 설명과 퀵 인사이트 작성",
                    ]
                },
            },
            settings,
            messages=[],
            version=settings.version,
            event="analysis_pipeline",
        )
        state["results"].append(
            record(
                "report",
                "report_input",
                "보고서 생성 요청 접수",
                output=report_input_adapter.validate_python({**body, "dongCode": code}),
            )
        )
        states.append(state)
    return states


def report_source(state):
    return next(
        (
            r["output"]
            for r in reversed(state["results"])
            if r["decision"] == "report_source"
        ),
        None,
    )


def report_saved(state):
    return any(
        r["decision"] == "report_save" and r["outcome"] == "success"
        for r in state["results"]
    )


async def execute_report(state, *, database, model):
    if not report_source(state):
        state["execution"]["status"] = "failed"
        state["execution"]["error"] = {
            "code": "result_not_found",
            "cause": "대상 분석 결과 없음",
        }
        return state
    providers, catalog = database.report_sources()
    graph = compile_graph(
        build_nodes(model, providers, catalog, role="report"), finish=finish
    )
    # 재처리도 동일 State·이력·누적 한도로 공통 그래프를 실행한다.
    state = state_adapter.validate_python(
        await graph.ainvoke(
            state,
            execution_config(state["execution"]["run_id"]),
        )
    )
    return state


def retry_report(state):
    return (
        not finalizing(state)
        and any(r["decision"] == "execution_failed" for r in state["results"])
        and not any(r["decision"] == "report_retry" for r in state["results"])
    )


async def save_report(state, *, database):
    # DB 저장은 공개 산출물만 읽는다. 실패 후 같은 산출물로 두 번 추가 시도한다.
    while sum(r["decision"] == "report_save" for r in state["results"]) < 3:
        if report_saved(state):
            return
        if any(r["decision"] == "report_save" for r in state["results"]):
            try:
                consume(state, "retries")
            except LimitReached:
                break
        item = record("report", "report_save", "보고서 DB 직접 저장", success=False)
        state["results"].append(item)
        try:
            with trace_span("database", "save_report", {"state": state}) as span:
                await database.save_report(state)
                if span:
                    span.update(output={"committed": True})
            item["outcome"] = "success"
            return
        except Exception as exc:
            item["output"] = {"error_type": type(exc).__name__}
    state["execution"]["status"] = "failed"
    state["execution"]["error"] = {
        "code": "report_save_failed",
        "cause": "보고서 저장 실패",
    }


async def execute_reports(states, *, database, model, client=None, semaphore=None):
    # 관측 객체만 별도로 보관한다. 재처리도 같은 동의 기록기에 이어 쓴다.
    recorders = {
        state["execution"]["run_id"]: execution_recorder(
            database.settings,
            database.settings.output_dir / state["execution"]["run_id"],
        )
        for state in states
    }

    async def finish_one(state):
        if report_source(state):
            try:
                report_artifact(state)
            except StopIteration:
                status = publish_report(state)
                state["execution"]["status"] = status
            if not report_saved(state):
                await save_report(state, database=database)
        inputs = report_input(state)
        logger.info(
            "Report finished requestId=%s month=%s dongCode=%s status=%s",
            inputs["requestId"],
            inputs["month"],
            inputs["dongCode"],
            state["execution"]["status"],
        )

    async def run_one(state):
        with (
            recording(recorders[state["execution"]["run_id"]]),
            trace_span("agent", "api.report", {"initial_state": state}) as span,
        ):
            try:
                if not any(r["decision"] == "report_source" for r in state["results"]):
                    await database.prepare_report(state)
                state.update(
                    await execute_report(state, database=database, model=model)
                )
            except Exception as exc:
                state["results"].append(
                    record(
                        "report",
                        "execution_failed",
                        "동별 실행 오류",
                        success=False,
                        output={"error_type": type(exc).__name__},
                    )
                )
                state["execution"]["status"] = "failed"
            if not retry_report(state):
                await finish_one(state)
            span.update(output=state)
            return state

    async def limited(state):
        async with semaphore:
            return await run_one(state)

    semaphore = semaphore or asyncio.Semaphore(database.settings.report_concurrency)
    failure = None
    try:
        # 목록에는 동별 State 자체만 둔다. 별도 보고서 캐시·요청 복사본은 두지 않는다.
        states[:] = await asyncio.gather(*(limited(state) for state in states))
        for state in states:
            if retry_report(state):
                try:
                    consume(state, "retries")
                except LimitReached:
                    with recording(recorders[state["execution"]["run_id"]]):
                        await finish_one(state)
                    continue
                state["results"].append(
                    record("report", "report_retry", "실패한 단계 1회 재처리")
                )
                state["execution"].update(status="queued", error=None)
        retry_indices = [
            i
            for i, state in enumerate(states)
            if state["execution"]["status"] == "queued"
        ]
        retried = await asyncio.gather(*(limited(states[i]) for i in retry_indices))
        for i, state in zip(retry_indices, retried, strict=True):
            states[i] = state
    except BaseException as exc:
        failure = {"error_type": type(exc).__name__}
        raise
    finally:
        if client is not None:
            inputs = report_input(states[0])
            await notify(
                client,
                database.settings,
                states[0],
                "/api/internal/analysis/insight-report-completions",
                {
                    "requestId": inputs["requestId"],
                    "month": inputs["month"],
                    "savedCount": sum(report_saved(s) for s in states),
                    "failedDongCodes": [
                        report_input(s)["dongCode"]
                        for s in states
                        if not report_saved(s)
                    ],
                },
            )
        for state in states:
            run_id = state["execution"]["run_id"]
            try:
                save_execution_report(
                    state,
                    recorders[run_id],
                    database.settings.output_dir / run_id,
                    failure,
                )
            except OSError:
                logger.warning("Report diagnostic write failed run_id=%s", run_id)

    return states


def create_app(settings=None, *, database=None, model=None):
    settings = settings or Settings()
    database = database if database is not None else Database(settings)

    @asynccontextmanager
    async def lifespan(app):
        if (
            not settings.backend_url
            or not settings.backend_token
            or not settings.backend_token.get_secret_value().strip()
        ):
            raise ValueError(
                "SETTINGS_BACKEND_URL and SETTINGS_BACKEND_TOKEN are required"
            )
        owned_model = model is None
        app.state.model = model if model is not None else create_model(settings)
        app.state.monitoring = create_monitoring(settings)
        # State 원본과 실행 Task만 연결한다. 별도 요청·결과 캐시는 두지 않는다.
        app.state.tasks = {}
        app.state.report_tasks = set()
        app.state.report_semaphore = asyncio.Semaphore(settings.report_concurrency)
        async with httpx.AsyncClient(timeout=settings.notification_timeout) as client:
            app.state.client = client
            try:
                yield
            finally:
                runs = list(app.state.tasks.values())
                tasks = [task for _, task in runs] + list(app.state.report_tasks)
                for state, task in runs:
                    if (
                        state["execution"]["status"] in {"queued", "running"}
                        and not task.cancelling()
                    ):
                        task.cancel()
                for task in app.state.report_tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await shutdown_monitoring(app.state.monitoring)
                if owned_model:
                    await app.state.model.http_async_client.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return Response(status_code=400)

    @app.get("/health")
    async def health():
        return {"status": "UP"}

    def reports_finished(task):
        app.state.report_tasks.discard(task)
        if not task.cancelled() and task.exception():
            logger.error(
                "Report runtime failed type=%s", type(task.exception()).__name__
            )

    @app.post(REPORT_PATH, status_code=202, response_class=Response)
    async def start_reports(body: ReportRequest):
        task = asyncio.create_task(
            execute_reports(
                create_report_states(body, settings),
                database=database,
                model=app.state.model,
                client=app.state.client,
                semaphore=app.state.report_semaphore,
            )
        )
        app.state.report_tasks.add(task)
        task.add_done_callback(reports_finished)
        return Response(status_code=202)

    def finished(run_id, task):
        if run_id in app.state.tasks and app.state.tasks[run_id][1] is task:
            app.state.tasks.pop(run_id)
        if not task.cancelled() and task.exception():
            logger.error(
                "AI background task failed run_id=%s type=%s",
                run_id,
                type(task.exception()).__name__,
            )

    @app.post("/internal/agent/runs", status_code=202, response_class=Response)
    async def start(body: RunRequest):
        started = monotonic()
        run_id = str(body["conversationId"])
        if run_id in app.state.tasks:
            active, _ = app.state.tasks[run_id]
            if question_id(active) == body["messageId"]:
                return Response(status_code=202)
            raise HTTPException(409, "Conversation is already running")
        state = create_state(
            {"goal": "저장된 질문 조회"},
            settings,
            messages=[],
            version=settings.version,
            event="user_request",
        )
        state["execution"]["run_id"] = run_id
        state["results"].append(
            record(
                "transport",
                "run_request",
                "대화 실행 요청",
                action={
                    "name": "INT-01",
                    "arguments": run_request_adapter.dump_python(body, mode="json"),
                },
            )
        )
        app.state.tasks[run_id] = (state, asyncio.current_task())
        try:
            inputs = state["results"][0]["action"]["arguments"]
            async with asyncio.timeout(
                min(settings.database_timeout, settings.runtime_timeout)
            ):
                loaded = await database.load_question(
                    UUID(inputs["conversationId"]), inputs["messageId"]
                )
            loaded["results"] = state["results"] + loaded["results"]
            state.update(state_adapter.validate_python(loaded))
            context = inputs.get("context", {})
            if context:
                state["request"]["constraints"]["preferred"].append(
                    "화면 문맥: " + json.dumps(context, ensure_ascii=False)
                )
            state["execution"]["budget"]["active_seconds"]["used"] += (
                monotonic() - started
            )
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
            app.state.tasks[run_id] = (state, task)
            task.add_done_callback(lambda task: finished(run_id, task))
        except QuestionNotFound:
            app.state.tasks.pop(run_id, None)
            raise HTTPException(400, "Question not found") from None
        except QuestionFinished:
            app.state.tasks.pop(run_id, None)
            return Response(status_code=202)
        except asyncio.CancelledError:
            state["execution"]["status"] = "cancelled"
            try:
                await commit_response(
                    state, database=database, client=app.state.client, settings=settings
                )
            finally:
                app.state.tasks.pop(run_id, None)
            return Response(status_code=202)
        except (DatabaseUnavailable, psycopg.Error, TimeoutError):
            app.state.tasks.pop(run_id, None)
            raise HTTPException(503, "Database unavailable") from None
        except BaseException:
            app.state.tasks.pop(run_id, None)
            raise
        return Response(status_code=202)

    @app.post(
        "/internal/agent/runs/{conversation_id}/cancel",
        status_code=202,
        response_class=Response,
    )
    async def cancel(conversation_id: UUID):
        running = app.state.tasks.get(str(conversation_id))
        if running:
            state, task = running
            if (
                state["execution"]["status"] in {"queued", "running"}
                and not task.cancelling()
            ):
                task.cancel()
                await asyncio.sleep(0)
                # coroutine 진입 전에 취소된 Task는 execute의 finally를 실행하지 않는다.
                if task.cancelled():
                    state["execution"]["status"] = "cancelled"
                    finalizer = asyncio.create_task(
                        commit_response(
                            state,
                            database=database,
                            client=app.state.client,
                            settings=settings,
                        )
                    )
                    app.state.tasks[str(conversation_id)] = (state, finalizer)
                    finalizer.add_done_callback(partial(finished, str(conversation_id)))
        return Response(status_code=202)

    return app
