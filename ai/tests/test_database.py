"""실제 PostgreSQL 경계의 SQL·커밋 순서 검사. 실제 DB 통합 검증과 구분한다."""

import sqlite3
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from api import create_report_states
from experiments.api_roundtrip import FileDatabase
from src.agent_nodes import publish_report
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
    assert state["results"] == []
    assert all(value["used"] == 0 for value in state["execution"]["budget"].values())
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


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_error", [False, True])
async def test_report_uses_original_analysis_timestamp_and_nulls(
    monkeypatch, commit_error
):
    from datetime import date, datetime

    db, committed = database(
        monkeypatch,
        {
            "period_start": date(2025, 12, 1),
            "adm_cd10": "1168066000",
            "updated_at": datetime(2025, 12, 15, 1, 2, 3, 123456),
        },
    )
    state = create_report_states(
        {"requestId": "db-test", "month": "2025-12", "dongCodes": ["1168066000"]},
        db.settings,
    )[0]
    await db.prepare_report(state)
    assert committed
    publish_report(state)
    writer, saved_commits = database(monkeypatch, None, commit_error=commit_error)
    if commit_error:
        with pytest.raises(ConnectionError):
            await writer.save_report(state)
        assert not saved_commits
    else:
        await writer.save_report(state)
        assert saved_commits
    sql, params = writer.calls[0]
    assert "ON CONFLICT (period_start, adm_cd10) DO UPDATE" in sql
    assert params[:3] == ("2025-12-01", "1168066000", "2025-12-15T01:02:03.123456")
    assert params[4:] == (None,) * 7
    assert "1168066000" not in sql


@pytest.mark.asyncio
async def test_report_insert_and_update_without_removed_columns(monkeypatch):
    """현행 컬럼의 SQLite로 SQL을 검사한다. PostgreSQL 연동 시험은 아니다."""
    writer, committed = database(monkeypatch, None)
    state = create_report_states(
        {"requestId": "db-schema", "month": "2025-12", "dongCodes": ["1168066000"]},
        writer.settings,
    )[0]
    row = {
        "period_start": "2025-12-01",
        "adm_cd10": "1168066000",
        "result_updated_at": "2025-12-15T01:02:03.123456",
        "generated_at": "2025-12-16T01:02:03",
        "quick_insight": "관측 범위 안의 요약",
        **{f"graph_{n}": f"EmbedDetailV0{n}" for n in range(1, 4)},
        **{f"desc_{n}": f"뷰 {n}의 설명" for n in range(1, 4)},
    }
    state["response"] = {
        "id": "report",
        "kind": "final",
        "label": "보고서",
        "content": "완성한 보고서 저장",
        "artifacts": [{"type": "analysis_report", "data": row}],
    }
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("ATTACH DATABASE ':memory:' AS public")
        # V20261110_02 이후 삭제된 summary_lines·report가 없는 저장 컬럼 집합.
        connection.execute(
            "CREATE TABLE public.region_insight_report ("
            "period_start TEXT NOT NULL, adm_cd10 TEXT NOT NULL, "
            "result_updated_at TEXT NOT NULL, generated_at TEXT NOT NULL, "
            "quick_insight TEXT NOT NULL, "
            "graph_1 TEXT NOT NULL, desc_1 TEXT NOT NULL, "
            "graph_2 TEXT NOT NULL, desc_2 TEXT NOT NULL, "
            "graph_3 TEXT NOT NULL, desc_3 TEXT NOT NULL, "
            "PRIMARY KEY (period_start, adm_cd10))"
        )
        for text in ("첫 보고서", "갱신한 보고서의 '인용문'"):
            row["quick_insight"] = text
            await writer.save_report(state)
            sql, params = writer.calls[-1]
            connection.execute(sql.replace("%s", "?"), params)
            stored = connection.execute(
                "SELECT * FROM public.region_insight_report"
            ).fetchall()
            assert len(stored) == 1
            assert dict(stored[0]) == row
    assert committed == [True, True]
