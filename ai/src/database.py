"""공유 DB의 질문을 State로 읽고 AI 응답을 커밋한다."""

import json
from datetime import date, datetime
from decimal import Decimal
from functools import partial
from hashlib import sha256
from typing import Annotated, Literal, NotRequired
from uuid import UUID

import psycopg
from langchain_core.messages import AIMessage, HumanMessage
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

from src.execution import record
from src.settings import Settings
from src.state import (
    Artifact,
    DongCode,
    State,
    create_state,
    report_artifact,
    report_input,
    response_adapter,
)
from src.tools.data import read_dataset


class DatabaseUnavailable(Exception):
    """연결 또는 미확정 DB 계약으로 실행할 수 없다."""


class QuestionNotFound(Exception):
    pass


class QuestionFinished(Exception):
    pass


class UnmappedResponse(Exception):
    """공개 응답으로 저장할 수 없는 실행 상태."""


class MessageRow(TypedDict):
    message_id: int
    role: Literal["Member", "AI"]
    status: Literal["질문", "진행", "완료", "실패", "취소"]
    content: str | None
    artifacts: NotRequired[Annotated[list[Artifact] | None, Field(default=None)]]


@with_config(ConfigDict(extra="forbid", strict=True))
class ReportSource(TypedDict):
    period_start: str
    adm_cd10: DongCode
    updated_at: str


report_source_adapter = TypeAdapter(ReportSource)
message_rows = TypeAdapter(list[MessageRow])


def record_report_source(state, row):
    state["results"].append(
        record(
            "report",
            "report_source",
            "대상 분석 결과 확인",
            output=report_source_adapter.validate_python(
                {
                    k: v.isoformat() if isinstance(v, (date, datetime)) else v
                    for k, v in row.items()
                }
            )
            if row
            else None,
            success=row is not None,
        )
    )


def question_id(state: State) -> int:
    """DB 질문 ID는 초기화 때 실제 사용자 메시지의 ID로 보존한다."""
    request = next(
        (r for r in state["results"] if r["decision"] == "run_request"), None
    )
    if request:
        return request["action"]["arguments"]["messageId"]
    return int(
        next(m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)).id
    )


def response_row(state):
    """내부 실행 상태를 대화 행으로 변환한다. 되묻기도 이번 질문의 끝 행이다."""
    status, response = state["execution"]["status"], state["response"]
    mapping = {
        "running": "진행",
        "waiting_input": "완료",
        "completed": "완료",
        "partial": "완료",
        "failed": "실패",
        "cancelled": "취소",
    }
    if status not in mapping or (
        response is None and status not in {"failed", "cancelled"}
    ):
        raise UnmappedResponse(status)
    response = response or {}
    return {
        "status": mapping[status],
        "content": (
            response.get("label") if status == "running" else response.get("content")
        )
        if status not in {"failed", "cancelled"}
        else None,
        "details": response.get("content") if status == "running" else None,
        "artifacts": response.get("artifacts") or None,
    }


def conversation_state(rows, conversation_id, settings):
    """DB/파일 경계가 읽은 실제 대화로 새 실행을 만든다."""
    rows = message_rows.validate_python(rows)
    question = rows[-1]
    messages = []
    for row in rows:
        if row["content"]:
            kind = HumanMessage if row["role"] == "Member" else AIMessage
            messages.append(kind(row["content"], id=str(row["message_id"])))
    state = create_state(
        {"goal": question["content"]},
        settings,
        messages=messages,
        version=settings.version,
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


# Dataset의 기존 열·행 계약으로 제공한다. 요청별 조회 결과를 캐시하지 않는다.
REPORT_SOURCES = {
    "analysis.bh_region_contribution": (
        "SELECT period_start, adm_cd10, indicator_cd, contribution, updated_at "
        "FROM analysis.bh_region_contribution "
        "ORDER BY period_start, adm_cd10, indicator_cd",
        "V02: 동·월·지표별 행동 점수 기여도. contribution은 점수 단위이며 "
        "전월 차이는 process_data로 계산한다. 배경 취약성 기여도가 아니다.",
        "행정동",
        [
            ("period_start", "string", "기준월 첫날"),
            ("adm_cd10", "string", "행정동코드"),
            ("indicator_cd", "string", "행동 지표 코드"),
            ("contribution", "number", "행동 점수"),
            ("updated_at", "string", "분석 수정 시각"),
        ],
    ),
    "analysis.flow_detail": (
        "SELECT f.period_start, g.adm_cd10, f.dim_type, f.dim_value, "
        "CASE WHEN bool_and(f.day_count > 0 AND f.flow_sum IS NOT NULL) "
        "THEN sum(f.flow_sum / nullif(f.day_count, 0)) END AS activity_daily, "
        "max(f.updated_at) AS updated_at "
        "FROM analysis.flow_detail f JOIN analysis.dim_grid100 g USING (grid_cd) "
        "GROUP BY f.period_start, g.adm_cd10, f.dim_type, f.dim_value "
        "ORDER BY f.period_start, g.adm_cd10, f.dim_type, f.dim_value",
        "V03·04·05·07: 격자별 flow_sum/day_count를 동·월·구분값별 합산한다. "
        "결과는 일평균 추정 활동량이다. "
        "파이프라인 common/bh_indicators.py의 load_means와 동별 합산에 대응한다. "
        "dim_type은 hour/weekday/sex_age다. "
        "값은 00~23/MON~SUN/M_10~F_60P다. "
        "V07은 hour의 24개 시간대 활동값 평균이며 합계와 다르다. "
        "0 이하 분모는 NULL로 보존한다. 누락 구분값이나 격자를 0으로 간주하지 않는다. "
        "전월 대비·월별 평균은 process_data로 계산한다.",
        "행정동",
        [
            ("period_start", "string", "기준월 첫날"),
            ("adm_cd10", "string", "행정동코드"),
            ("dim_type", "string", "구분"),
            ("dim_value", "string", "구분값"),
            ("activity_daily", "number", "일평균 추정 활동량"),
            ("updated_at", "string", "분석 수정 시각"),
        ],
    ),
    "analysis.bh_grid_anomaly": (
        "SELECT a.period_start, g.adm_cd10, a.grid_cd, a.anomaly_score, a.updated_at "
        "FROM analysis.bh_grid_anomaly a JOIN analysis.dim_grid100 g USING (grid_cd) "
        "ORDER BY a.period_start, g.adm_cd10, a.grid_cd",
        "V08: 동·월 내 격자별 행동 이상 점수. NULL은 미산출이며 0이 아니다. "
        "개수·분포 계산은 process_data로 수행한다. "
        "행이 없는 격자는 이 자료만으로 세지 않는다.",
        "100m 격자",
        [
            ("period_start", "string", "기준월 첫날"),
            ("adm_cd10", "string", "행정동코드"),
            ("grid_cd", "string", "격자코드"),
            ("anomaly_score", "number", "행동 이상 점수"),
            ("updated_at", "string", "분석 수정 시각"),
        ],
    ),
}


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
        return self._read_dataset(
            "public.region_result",
            "SELECT period_start, adm_cd10, bg_score, bg_grade, "
            "bh_score, bh_grade, risk_grade, updated_at "
            "FROM public.region_result ORDER BY period_start, adm_cd10",
            "파이프라인 읍면동 월별 분석 결과",
            [
                ("period_start", "string", "기준월 첫날"),
                ("adm_cd10", "string", "행정동코드"),
                ("bg_score", "number", "배경 점수"),
                ("bg_grade", "integer", "단계(1~5)"),
                ("bh_score", "number", "행동 점수"),
                ("bh_grade", "integer", "단계(1~5)"),
                ("risk_grade", "integer", "단계(1~5)"),
                ("updated_at", "string", "분석 수정 시각(한국 시간)"),
            ],
        )

    def _read_dataset(self, name, sql, description, columns, spatial="행정동"):
        if not self.settings.database_url:
            raise DatabaseUnavailable("SETTINGS_DATABASE_URL is required")
        with psycopg.connect(
            self.settings.database_url.get_secret_value(),
            row_factory=dict_row,
            connect_timeout=self.settings.database_timeout,
            options=f"-c statement_timeout={self.settings.database_timeout * 1000}",
        ) as connection:
            rows = connection.execute(sql).fetchall()
        rows = [
            {
                k: v.isoformat()
                if isinstance(v, (date, datetime))
                else float(v)
                if isinstance(v, Decimal)
                else v
                for k, v in row.items()
            }
            for row in rows
        ]
        return read_dataset(
            {
                "reference": {
                    "id": name,
                    "version": sha256(
                        json.dumps(rows, sort_keys=True).encode()
                    ).hexdigest(),
                },
                "as_of": max((row["updated_at"] for row in rows), default="empty"),
                "sources": [
                    {"label": description, "uri": "db://" + name.replace(".", "/")}
                ],
                "columns": [
                    {
                        "name": key,
                        "kind": kind,
                        "unit": unit,
                        "spatial_unit": spatial,
                        "temporal_unit": "월",
                        "denominator": "해당 없음",
                    }
                    for key, kind, unit in columns
                ],
                "rows": rows,
            }
        )

    def report_dataset(self, name):
        sql, description, spatial, columns = REPORT_SOURCES[name]
        return self._read_dataset(name, sql, description, columns, spatial)

    def report_sources(self):
        # partial에는 배포 설정·등록 자료명만 묶고 실행별 자료는 포함하지 않는다.
        providers = {"public.region_result": self.region_results}
        providers.update(
            {name: partial(self.report_dataset, name) for name in REPORT_SOURCES}
        )
        catalog = dict(self.catalog)
        catalog["public.region_result"] += (
            " V01은 해당 동의 월별 bh_score 추이를 설명할 수 있다. "
            "도시 중앙 50% 범위는 계산된 근거가 없으면 설명하지 않는다. "
            "V06의 요인별 기여도는 현재 공급 자료에 없다. "
            "배경 점수로 기여도를 추측하지 않는다."
        )
        catalog.update(
            {
                name: info[1]
                + " 조회 가능한 열(이 목록만 사용): "
                + ", ".join(f"{key} ({kind}, {unit})" for key, kind, unit in info[3])
                + ". 설명의 산식에 등장하는 이름도 이 목록에 없으면 조회할 수 없다."
                for name, info in REPORT_SOURCES.items()
            }
        )
        return providers, catalog

    async def connect(self):
        if not self.settings.database_url:
            raise DatabaseUnavailable("SETTINGS_DATABASE_URL is required")
        return await psycopg.AsyncConnection.connect(
            self.settings.database_url.get_secret_value(),
            row_factory=dict_row,
            connect_timeout=self.settings.database_timeout,
            options=f"-c statement_timeout={self.settings.database_timeout * 1000}",
        )

    async def prepare_report(self, state):
        """요청 동·월의 분석 결과를 확인한다. 기존 보고서와 시점을 비교하지 않는다."""
        inputs = report_input(state)
        async with await self.connect() as connection:
            cursor = await connection.execute(
                "SELECT r.period_start, r.adm_cd10, r.updated_at "
                "FROM public.region_result r "
                "WHERE r.period_start = %s AND r.adm_cd10 = %s",
                (inputs["month"] + "-01", inputs["dongCode"]),
            )
            row = await cursor.fetchone()
        record_report_source(state, row)

    async def save_report(self, state):
        """State의 공개 보고서를 직접 UPSERT하고 커밋 후 반환한다."""
        row = report_artifact(state)
        async with await self.connect() as connection:
            await connection.execute(
                "INSERT INTO public.region_insight_report "
                "(period_start, adm_cd10, result_updated_at, generated_at, "
                "quick_insight, graph_1, desc_1, graph_2, desc_2, graph_3, desc_3) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (period_start, adm_cd10) DO UPDATE SET "
                "result_updated_at=EXCLUDED.result_updated_at, "
                "generated_at=EXCLUDED.generated_at, "
                "quick_insight=EXCLUDED.quick_insight, "
                "graph_1=EXCLUDED.graph_1, desc_1=EXCLUDED.desc_1, "
                "graph_2=EXCLUDED.graph_2, desc_2=EXCLUDED.desc_2, "
                "graph_3=EXCLUDED.graph_3, desc_3=EXCLUDED.desc_3, "
                "summary_lines=NULL, report=NULL",
                tuple(
                    row[k]
                    for k in (
                        "period_start",
                        "adm_cd10",
                        "result_updated_at",
                        "generated_at",
                        "quick_insight",
                        "graph_1",
                        "desc_1",
                        "graph_2",
                        "desc_2",
                        "graph_3",
                        "desc_3",
                    )
                ),
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
        return conversation_state(rows, conversation_id, self.settings)

    async def save_response(self, state: State) -> int:
        row = response_row(state)
        async with await self.connect() as connection:
            cursor = await connection.execute(
                "INSERT INTO public.ai_message "
                "(conversation_id, question_id, role, status, "
                "content, details, artifacts) "
                "VALUES (%s, %s, 'AI', %s, %s, %s, %s) RETURNING message_id",
                (
                    UUID(state["execution"]["run_id"]),
                    question_id(state),
                    row["status"],
                    row["content"],
                    row["details"],
                    Jsonb(row["artifacts"]) if row["artifacts"] else None,
                ),
            )
            saved_id = (await cursor.fetchone())["message_id"]
        # async connection context가 정상 종료되어 커밋된 뒤에만 ID를 반환한다.
        return saved_id
