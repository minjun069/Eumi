"""공유 DB의 질문을 State로 읽고 AI 응답을 커밋한다."""

import json
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal, NotRequired
from uuid import UUID

import psycopg
from langchain_core.messages import AIMessage, HumanMessage
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field, TypeAdapter
from typing_extensions import TypedDict

from src.settings import Settings
from src.state import Artifact, State, create_state, response_adapter
from src.tools.data import read_dataset


class DatabaseUnavailable(Exception):
    """연결 또는 미확정 DB 계약으로 실행할 수 없다."""


class QuestionNotFound(Exception):
    pass


class QuestionFinished(Exception):
    pass


class UnmappedResponse(Exception):
    """질문 대기·부분 완료의 DB 표현은 아직 확정되지 않았다."""


class MessageRow(TypedDict):
    message_id: int
    role: Literal["Member", "AI"]
    status: Literal["질문", "진행", "완료", "실패", "취소"]
    content: str | None
    artifacts: NotRequired[Annotated[list[Artifact] | None, Field(default=None)]]


message_rows = TypeAdapter(list[MessageRow])


def question_id(state: State) -> int:
    """DB 질문 ID는 초기화 때 실제 사용자 메시지의 ID로 보존한다."""
    message = next(
        m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)
    )
    return int(message.id)


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        # 자료 공급자는 배포 구성이다. 조회 결과는 도구가 results에 기록한다.
        self.providers = {"public.region_result": self.region_results}
        self.catalog = {
            "public.region_result": "실제 DB의 읍면동 월별 분석 결과. "
            "period_start(월 첫날), "
            "adm_cd10(행정동코드), bg_score/bg_grade(배경 점수/단계), "
            "bh_score/bh_grade(행동 점수/단계), risk_grade(종합 단계), "
            "updated_at(분석 수정 시각). 단계는 1~5이며 5가 가장 높다. "
            "점수 산식·원인·개인 위험은 이 자료만으로 확인할 수 없다. "
            "월·지역 필터로 대상과 비교 자료를 조회한다.",
        }

    def region_results(self):
        """도구의 executor에서 조회하며 결과를 캐시하지 않는다."""
        if not self.settings.database_url:
            raise DatabaseUnavailable("SETTINGS_DATABASE_URL is required")
        with psycopg.connect(
            self.settings.database_url.get_secret_value(),
            row_factory=dict_row,
            connect_timeout=self.settings.database_timeout,
            options=f"-c statement_timeout={self.settings.database_timeout * 1000}",
        ) as connection:
            rows = connection.execute(
                "SELECT period_start, adm_cd10, bg_score, bg_grade, "
                "bh_score, bh_grade, risk_grade, updated_at "
                "FROM public.region_result ORDER BY period_start, adm_cd10"
            ).fetchall()
        rows = [
            {
                key: value.isoformat()
                if isinstance(value, (date, datetime))
                else float(value)
                if isinstance(value, Decimal)
                else value
                for key, value in row.items()
            }
            for row in rows
        ]
        version = sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        return read_dataset(
            {
                "reference": {"id": "public.region_result", "version": version},
                "as_of": max((row["updated_at"] for row in rows), default="empty"),
                "sources": [
                    {
                        "label": "파이프라인 읍면동 월별 분석 결과",
                        "uri": "db://public/region_result",
                    }
                ],
                "columns": [
                    {
                        "name": name,
                        "kind": kind,
                        "unit": unit,
                        "spatial_unit": "행정동",
                        "temporal_unit": "월",
                        "denominator": "해당 없음",
                    }
                    for name, kind, unit in [
                        ("period_start", "string", "기준월 첫날"),
                        ("adm_cd10", "string", "행정동코드"),
                        ("bg_score", "number", "배경 점수"),
                        ("bg_grade", "integer", "단계(1~5)"),
                        ("bh_score", "number", "행동 점수"),
                        ("bh_grade", "integer", "단계(1~5)"),
                        ("risk_grade", "integer", "단계(1~5)"),
                        ("updated_at", "string", "분석 수정 시각(한국 시간)"),
                    ]
                ],
                "rows": rows,
            }
        )

    async def connect(self):
        if not self.settings.database_url:
            raise DatabaseUnavailable("SETTINGS_DATABASE_URL is required")
        return await psycopg.AsyncConnection.connect(
            self.settings.database_url.get_secret_value(),
            row_factory=dict_row,
            connect_timeout=self.settings.database_timeout,
            options=f"-c statement_timeout={self.settings.database_timeout * 1000}",
        )

    async def load_question(self, conversation_id: UUID, requested_id: int) -> State:
        async with await self.connect() as connection:
            cursor = await connection.execute(
                "SELECT message_id, role, status, content, details, artifacts "
                "FROM public.ai_message WHERE conversation_id = %s "
                "AND message_id <= %s ORDER BY message_id",
                (conversation_id, requested_id),
            )
            rows = await cursor.fetchall()
            if not rows or rows[-1]["message_id"] != requested_id:
                raise QuestionNotFound
            question = rows[-1]
            if question["role"] != "Member" or question["status"] != "질문":
                raise QuestionNotFound
            cursor = await connection.execute(
                "SELECT 1 FROM public.ai_message WHERE conversation_id = %s "
                "AND question_id = %s AND status IN ('완료', '실패', '취소') LIMIT 1",
                (conversation_id, requested_id),
            )
            if await cursor.fetchone():
                raise QuestionFinished
        rows = message_rows.validate_python(rows)
        question = rows[-1]
        messages = []
        for row in rows:
            if row["content"]:
                kind = HumanMessage if row["role"] == "Member" else AIMessage
                messages.append(kind(row["content"], id=str(row["message_id"])))
        state = create_state(
            {"goal": question["content"]},
            self.settings,
            messages=messages,
            version=self.settings.version,
            event="user_request",
        )
        state["execution"]["run_id"] = str(conversation_id)
        previous = next(
            (
                row
                for row in reversed(rows[:-1])
                if row["role"] == "AI" and row["status"] == "완료"
            ),
            None,
        )
        if previous:
            state["response"] = response_adapter.validate_python(
                {
                    "id": str(previous["message_id"]),
                    "kind": "final",
                    "label": "final",
                    "content": previous["content"] or "",
                    "artifacts": previous["artifacts"] or [],
                }
            )
        return state

    async def save_response(self, state: State) -> int:
        response = state["response"]
        status = state["execution"]["status"]
        mapping = {"completed": "완료", "failed": "실패", "cancelled": "취소"}
        if status not in mapping or response is None:
            raise UnmappedResponse(status)
        async with await self.connect() as connection:
            cursor = await connection.execute(
                "INSERT INTO public.ai_message "
                "(conversation_id, question_id, role, status, "
                "content, details, artifacts) "
                "VALUES (%s, %s, 'AI', %s, %s, %s, %s) RETURNING message_id",
                (
                    UUID(state["execution"]["run_id"]),
                    question_id(state),
                    mapping[status],
                    response["content"] if status == "completed" else None,
                    None,
                    Jsonb(response["artifacts"]) if response["artifacts"] else None,
                ),
            )
            saved_id = (await cursor.fetchone())["message_id"]
        # async connection context가 정상 종료되어 커밋된 뒤에만 ID를 반환한다.
        return saved_id
