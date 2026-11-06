"""실제 PostgreSQL 경계의 SQL·커밋 순서 검사. 실제 DB 통합 검증과 구분한다."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from experiments.api_roundtrip import FileDatabase
from src.database import Database, QuestionFinished, QuestionNotFound, question_id
from src.settings import Settings
from src.state import create_state


def database(monkeypatch, rows, terminal=None, *, commit_error=False):
    db = Database(Settings(_env_file=None))
    reads = [rows, terminal]
    committed = []

    async def execute(sql, params):
        db.calls.append((sql, params))
        value = reads.pop(0)
        return AsyncMock(
            fetchall=AsyncMock(return_value=value),
            fetchone=AsyncMock(return_value=value),
        )

    @asynccontextmanager
    async def transaction():
        yield AsyncMock(execute=execute)
        if commit_error:
            raise ConnectionError("commit failed")
        committed.append(True)

    db.calls = []
    monkeypatch.setattr(db, "connect", AsyncMock(side_effect=transaction))
    return db, committed


@pytest.mark.asyncio
async def test_question_load_preserves_actual_ids_and_previous_artifacts(monkeypatch):
    rows = [
        {"message_id": 1, "role": "Member", "status": "질문", "content": "첫 질문"},
        {
            "message_id": 2,
            "role": "AI",
            "status": "완료",
            "content": "첫 답변",
            "artifacts": [{"type": "tableau", "data": {"view_key": "existing"}}],
        },
        {
            "message_id": 3,
            "role": "Member",
            "status": "질문",
            "content": "그 차트 설명",
        },
    ]
    db, committed = database(monkeypatch, rows)
    conversation = uuid4()
    state = await db.load_question(conversation, 3)
    assert committed
    assert state["execution"]["run_id"] == str(conversation)
    assert question_id(state) == 3
    assert [m.id for m in state["messages"]] == ["1", "2", "3"]
    assert state["response"]["artifacts"] == rows[1]["artifacts"]
    assert state["request"]["goal"] == "그 차트 설명"
    assert db.calls[0][1] == (conversation, 3)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows, terminal, error",
    [
        ([], None, QuestionNotFound),
        ([{"message_id": 2}], None, QuestionNotFound),
        ([{"message_id": 3, "role": "AI", "status": "완료"}], None, QuestionNotFound),
        (
            [{"message_id": 3, "role": "Member", "status": "질문"}],
            {"exists": 1},
            QuestionFinished,
        ),
    ],
)
async def test_question_ownership_and_terminal_guard(
    monkeypatch, rows, terminal, error
):
    db, _ = database(monkeypatch, rows, terminal)
    with pytest.raises(error):
        await db.load_question(uuid4(), 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_error", [False, True])
async def test_result_id_is_returned_only_after_commit(monkeypatch, commit_error):
    db, committed = database(
        monkeypatch, {"message_id": 102}, commit_error=commit_error
    )
    state = create_state(
        {"goal": "질문"},
        db.settings,
        messages=[HumanMessage("질문", id="101")],
        version="test",
        event="user_request",
    )
    state["execution"]["status"] = "completed"
    state["response"] = {
        "id": "result",
        "kind": "final",
        "label": "결과",
        "content": "DB 입력 ' 인용부호",
        "artifacts": [],
    }
    if commit_error:
        with pytest.raises(ConnectionError):
            await db.save_response(state)
        assert not committed
    else:
        assert await db.save_response(state) == 102
        assert committed
    sql, params = db.calls[0]
    assert "RETURNING message_id" in sql
    assert state["response"]["content"] not in sql
    assert params[1] == 101 and params[3] == state["response"]["content"]


@pytest.mark.asyncio
async def test_file_boundary_persists_question_and_result_without_memory_state(
    tmp_path,
):
    config = Settings(_env_file=None)
    path = tmp_path / "messages.json"
    db = FileDatabase(config, path)
    conversation = uuid4()
    db.seed(conversation, 101, "지도 요청")
    with pytest.raises(FileExistsError):
        db.seed(conversation, 101, "기존 자료 덮어쓰기 금지")
    state = await FileDatabase(config, path).load_question(conversation, 101)
    assert state["messages"][0].content == "지도 요청"
    assert question_id(state) == 101
    state["execution"]["status"] = "completed"
    state["response"] = {
        "id": "reply",
        "kind": "final",
        "label": "결과",
        "content": "지도입니다.",
        "artifacts": [{"type": "tableau", "data": {"view_key": "existing"}}],
    }
    saved = await db.save_response(state)
    row = FileDatabase(config, path).read()[-1]
    assert row["message_id"] == saved == 102
    assert row["conversation_id"] == conversation and row["question_id"] == 101
    assert row["artifacts"] == state["response"]["artifacts"]
    with pytest.raises(QuestionFinished):
        await FileDatabase(config, path).load_question(conversation, 101)
    with pytest.raises(QuestionNotFound):
        await db.load_question(uuid4(), 101)
