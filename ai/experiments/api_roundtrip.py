"""실제 모델·HTTP 왕복 검사. DB는 PostgreSQL 또는 명시한 임시 JSON 파일."""

import argparse
import asyncio
import json
import os
import socket
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import uvicorn
from fastapi import FastAPI, Response
from langchain_core.messages import HumanMessage
from pydantic import TypeAdapter

from api import Notification, create_app
from src.database import (
    Database,
    MessageRow,
    QuestionFinished,
    QuestionNotFound,
    UnmappedResponse,
)
from src.database import (
    question_id as state_question_id,
)
from src.gemini import create_model
from src.settings import Settings
from src.state import create_state

SAMPLE_QUESTION = (
    "2025년 12월 서울특별시 강남구 전체 읍면동의 종합 위험도 지도를 보여 주세요. "
    "개별 읍면동 필터는 적용하지 마세요. 수치 조회·원인 해석은 요청하지 않습니다. "
    "등록된 Tableau 지도와 적용한 지역·월 안내를 반환해 주세요. "
    "외부 화면을 실제 열어 보았다고 표현하지 마세요."
)


class StoredMessage(MessageRow):
    conversation_id: UUID
    question_id: int | None
    details: str | None
    created_at: str


stored_messages = TypeAdapter(list[StoredMessage])


class FileDatabase(Database):
    """단일 프로세스 왕복 실험용. 질문·응답 원본을 파일에서 읽고 저장한다."""

    def __init__(self, settings, path: Path):
        super().__init__(settings)
        self.path = path
        self.providers, self.catalog = {}, {}

    def read(self):
        return stored_messages.validate_json(self.path.read_bytes())

    def write(self, rows):
        payload = stored_messages.dump_json(
            stored_messages.validate_python(rows), indent=2
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)

    def seed(self, conversation_id, question_id, content):
        if self.path.exists():
            raise FileExistsError("Use a new path; existing experiment is preserved")
        self.write(
            [
                {
                    "conversation_id": conversation_id,
                    "message_id": question_id,
                    "question_id": None,
                    "role": "Member",
                    "status": "질문",
                    "content": content,
                    "details": None,
                    "artifacts": None,
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ]
        )

    async def load_question(self, conversation_id, requested_id):
        rows = self.read()
        question = next(
            (
                r
                for r in rows
                if r["conversation_id"] == conversation_id
                and r["message_id"] == requested_id
                and r["role"] == "Member"
                and r["status"] == "질문"
            ),
            None,
        )
        if not question:
            raise QuestionNotFound
        if any(
            r["conversation_id"] == conversation_id
            and r["question_id"] == requested_id
            and r["status"] in {"완료", "실패", "취소"}
            for r in rows
        ):
            raise QuestionFinished
        state = create_state(
            {"goal": question["content"]},
            self.settings,
            messages=[HumanMessage(question["content"], id=str(requested_id))],
            version=self.settings.version,
            event="user_request",
        )
        state["execution"]["run_id"] = str(conversation_id)
        return state

    async def save_response(self, state):
        status, response = state["execution"]["status"], state["response"]
        mapping = {"completed": "완료", "failed": "실패", "cancelled": "취소"}
        if status not in mapping or response is None:
            raise UnmappedResponse(status)
        conversation_id = UUID(state["execution"]["run_id"])
        question_id = state_question_id(state)
        await self.load_question(conversation_id, question_id)
        rows = self.read()
        saved_id = max(r["message_id"] for r in rows) + 1
        rows.append(
            {
                "conversation_id": conversation_id,
                "message_id": saved_id,
                "question_id": question_id,
                "role": "AI",
                "status": mapping[status],
                "content": response["content"] if status == "completed" else None,
                "details": None,
                "artifacts": response["artifacts"] or None,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        self.write(rows)
        return saved_id


@asynccontextmanager
async def serve(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", access_log=False)
        )
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("HTTP server stopped before startup")
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=15)


async def roundtrip(
    output: Path,
    *,
    conversation_id: UUID,
    question_id: int,
    file_db: Path | None = None,
    question=SAMPLE_QUESTION,
    model_name="gpt-5.6-luna",
):
    settings = Settings(
        output_dir=output,
        model=model_name,
        langfuse_enabled=False,
        max_steps=16,
        max_tool_calls=4,
        max_agent_calls=1,
        max_tool_retries=0,
        runtime_timeout=150,
        llm_timeout=30,
    )
    database = FileDatabase(settings, file_db) if file_db else Database(settings)
    if file_db:
        database.seed(conversation_id, question_id, question)
    # DB 환경이 없으면 모델 호출·HTTP 성공 판정 전에 중단한다.
    await database.load_question(conversation_id, question_id)
    received = []
    receiver = FastAPI()

    @receiver.post("/notifications", response_class=Response, status_code=204)
    async def receive(body: Notification):
        assert body["conversation_id"] == conversation_id
        assert body["question_id"] == question_id
        # 새 연결·파일 재읽기로 저장 후 알림임을 확인한다.
        if file_db:
            row = next(
                (
                    r
                    for r in FileDatabase(settings, file_db).read()
                    if r["conversation_id"] == body["conversation_id"]
                    and r["message_id"] == body["message_id"]
                ),
                None,
            )
        else:
            async with await database.connect() as connection:
                cursor = await connection.execute(
                    "SELECT question_id, role, status FROM public.ai_message "
                    "WHERE conversation_id = %s AND message_id = %s",
                    (body["conversation_id"], body["message_id"]),
                )
                row = await cursor.fetchone()
        assert row and row["question_id"] == question_id and row["role"] == "AI"
        assert row["status"] in {"완료", "실패", "취소"}
        received.append(
            {k: str(v) if isinstance(v, UUID) else v for k, v in body.items()}
        )
        return Response(status_code=204)

    async with serve(receiver) as callback:
        settings.notification_url = f"{callback}/notifications"
        model = create_model(settings).model_copy(
            update={
                "reasoning_effort": "low",
                "max_tokens": 2048,
            }
        )
        app = create_app(settings, database=database, model=model)
        live_seen = False
        try:
            async with serve(app) as url, httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{url}/internal/agent/runs",
                    json={
                        "conversation_id": str(conversation_id),
                        "question_id": question_id,
                    },
                )
                if response.status_code != 202 or response.content:
                    raise RuntimeError(f"접수 실패: HTTP {response.status_code}")
                print("HTTP 202 accepted", flush=True)
                tasks = list(app.state.tasks.values())
                while any(not task.done() for task in tasks):
                    for journal in (output / str(conversation_id)).glob(
                        "*/trace.jsonl"
                    ):
                        if (
                            journal.stat().st_size
                            and not (journal.parent / "report.json").exists()
                        ):
                            live_seen = True
                    await asyncio.sleep(0.2)
                await asyncio.gather(*tasks)
        finally:
            await model.http_async_client.aclose()
    reports = sorted(
        (output / str(conversation_id)).glob("*/report.json"),
        key=lambda path: path.stat().st_mtime,
    )
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    spans = report["trace"]["spans"]
    models = [s for s in spans if s["kind"] == "model"]
    saves = [s for s in spans if s["kind"] == "database" and s["status"] == "success"]
    notifications = [
        s for s in spans if s["name"] == "notification" and s["status"] == "success"
    ]
    stored_before_notification = bool(
        saves
        and notifications
        and saves[-1]["ended_at"] <= notifications[0]["started_at"]
    )
    model_http_verified = bool(models) and all(
        s.get("http_request", {}).get("body", {}).get("model") == model_name
        and s.get("http_response", {}).get("status_code") == 200
        for s in models
    )
    summary = {
        "passed": bool(received)
        and report["failure"] is None
        and report["state"]["execution"]["status"] == "completed"
        and live_seen
        and stored_before_notification
        and model_http_verified,
        "model": model_name,
        "model_calls": len(models),
        "model_http_verified": model_http_verified,
        "database": "temporary JSON file" if file_db else "postgresql",
        "accepted_http": response.status_code,
        "notification_http": 204 if notifications else None,
        "live_trace_observed": live_seen,
        "stored_before_notification": stored_before_notification,
        "artifacts": len((report["state"]["response"] or {}).get("artifacts", [])),
        "received": received,
        "status": report["state"]["execution"]["status"],
        "failure": report["failure"],
        "report": str(reports[-1].resolve()),
    }
    (output / "roundtrip.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conversation-id", type=UUID)
    parser.add_argument("--question-id", type=int)
    parser.add_argument("--file-db", type=Path, help="새 임시 메시지 JSON 파일")
    parser.add_argument("--question", default=SAMPLE_QUESTION)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--output", type=Path, default=Path("outputs/api-roundtrip-db"))
    args = parser.parse_args()
    if not args.file_db and (not args.conversation_id or not args.question_id):
        parser.error("PostgreSQL mode requires --conversation-id and --question-id")
    try:
        result = asyncio.run(
            roundtrip(
                args.output,
                conversation_id=args.conversation_id or uuid4(),
                question_id=args.question_id or 101,
                file_db=args.file_db,
                question=args.question,
                model_name=args.model,
            )
        )
    except Exception as exc:
        # DSN·외부 오류 원문을 콘솔에 노출하지 않는다.
        print(json.dumps({"passed": False, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
