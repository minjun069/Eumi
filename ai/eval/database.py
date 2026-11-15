"""평가 전용 DB의 시험 원본 준비와 실행 전 일치 검사.

테이블 생성·변경은 공통 Flyway migration이 맡는다. 여기서는 서비스가 읽는
여섯 테이블에만 완전한 행을 적재하며 기존 자료를 삭제하거나 갱신하지 않는다.
"""

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from re import fullmatch
from typing import Annotated, Literal

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    TypeAdapter,
)
from typing_extensions import TypedDict

from src.settings import Settings


def _date(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("date must use YYYY-MM-DD")
    return value


def _timestamp(value: str) -> str:
    if not fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", value):
        raise ValueError("timestamp must use local ISO datetime without timezone")
    datetime.fromisoformat(value)
    return value


def _numeric(precision: int, scale: int):
    def check(value: int | float) -> int | float:
        decimal = Decimal(str(value))
        if not decimal.is_finite() or abs(decimal) >= 10 ** (precision - scale):
            raise ValueError("number exceeds PostgreSQL numeric precision")
        if decimal != decimal.quantize(Decimal(1).scaleb(-scale)):
            raise ValueError("number exceeds PostgreSQL numeric scale")
        return value

    return AfterValidator(check)


Code10 = Annotated[str, Field(strict=True, max_length=10)]
Day = Annotated[str, Field(strict=True), AfterValidator(_date)]
Timestamp = Annotated[str, Field(strict=True), AfterValidator(_timestamp)]
SmallInt = Annotated[int, Field(strict=True, ge=-32768, le=32767)]
Integer = Annotated[int, Field(strict=True, ge=-2147483648, le=2147483647)]
Score = Annotated[StrictInt | StrictFloat, _numeric(7, 2)]
Contribution = Annotated[StrictInt | StrictFloat, _numeric(10, 6)]
Flow = Annotated[StrictInt | StrictFloat, _numeric(16, 4)]


class Region(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    adm_cd10: Code10
    adm_cd8: Annotated[str, Field(max_length=8)] | None
    adm_nm: Annotated[str, Field(max_length=30)]
    sgg_nm: Annotated[str, Field(max_length=20)]
    geom: str | None
    updated_at: Timestamp | None


class RegionResult(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    period_start: Day
    adm_cd10: Code10
    bg_score: Score
    bg_grade: SmallInt
    bh_score: Score
    bh_grade: SmallInt
    risk_grade: SmallInt
    updated_at: Timestamp


class Grid(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    grid_cd: Code10
    gx: Integer
    gy: Integer
    updated_at: Timestamp
    adm_cd10: Code10


class RegionContribution(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    period_start: Day
    adm_cd10: Code10
    indicator_cd: Annotated[str, Field(max_length=50)]
    contribution: Contribution
    updated_at: Timestamp


class GridAnomaly(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    period_start: Day
    grid_cd: Code10
    anomaly_score: Score | None
    updated_at: Timestamp


class FlowDetail(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    period_start: Day
    dim_type: Literal["hour", "weekday", "sex_age"]
    dim_value: Code10
    grid_cd: Code10
    flow_sum: Flow | None
    day_count: SmallInt | None
    updated_at: Timestamp


class DatabaseIdentity(TypedDict):
    host: str
    port: str
    dbname: str


class PreparationResult(TypedDict):
    status: Literal["prepared", "unchanged"]
    rows: dict[str, int]


# 순서는 외래 키 의존 순서다. SQL 식별자는 이 정의에서만 가져온다.
_ROW_TYPES = {
    "public.dim_region": Region,
    "public.region_result": RegionResult,
    "analysis.dim_grid100": Grid,
    "analysis.bh_region_contribution": RegionContribution,
    "analysis.bh_grid_anomaly": GridAnomaly,
    "analysis.flow_detail": FlowDetail,
}
TABLES = tuple(_ROW_TYPES)
_COLUMNS = {table: tuple(row.__annotations__) for table, row in _ROW_TYPES.items()}
_ADAPTERS = {table: TypeAdapter(list[row]) for table, row in _ROW_TYPES.items()}


def validate_fixture(fixture: dict) -> None:
    """SQL 호출 없이 허용 테이블과 완전한 행의 입력 자료형을 검사한다."""
    if not isinstance(fixture, dict):
        raise ValueError("database_fixture must be an object")
    if set(fixture) - set(TABLES):
        raise ValueError("database_fixture contains an unsupported table")
    for table, rows in fixture.items():
        _ADAPTERS[table].validate_python(rows, strict=True)


def database_identity(settings: Settings) -> DatabaseIdentity:
    """비밀값을 제외한 평가 DB 주소. DB 이름 제한은 접속 전에 검사한다."""
    if not settings.database_url:
        raise ValueError("database evaluation requires SETTINGS_DATABASE_URL")
    try:
        values = conninfo_to_dict(settings.database_url.get_secret_value())
    except psycopg.Error:
        raise ValueError("invalid evaluation database connection settings") from None
    name = values.get("dbname", "")
    if name != "eumi_eval" and not name.startswith("eumi_eval_"):
        raise ValueError("database name must be eumi_eval or start with eumi_eval_")
    return {
        "host": values.get("host") or values.get("hostaddr") or "",
        "port": values.get("port", "5432"),
        "dbname": name,
    }


def _connect(settings: Settings):
    identity = database_identity(settings)
    connection = psycopg.connect(
        settings.database_url.get_secret_value(),
        row_factory=dict_row,
        connect_timeout=settings.database_timeout,
        options=f"-c statement_timeout={settings.database_timeout * 1000}",
    )
    # 환경 변수·서비스 설정이 암묵적으로 다른 DB를 선택하지 못하게 확인한다.
    if connection.info.dbname != identity["dbname"]:
        connection.close()
        raise ValueError("connected database differs from evaluation database")
    return connection


def _table_identifier(table: str):
    return sql.Identifier(*table.split("."))


def _read_tables(connection) -> dict[str, list[dict]]:
    result = {}
    for table in TABLES:
        result[table] = connection.execute(
            sql.SQL("SELECT {} FROM {}").format(
                sql.SQL(", ").join(map(sql.Identifier, _COLUMNS[table])),
                _table_identifier(table),
            )
        ).fetchall()
    return result


def _cell(column: str, value):
    if value is None:
        return None
    if column == "period_start":
        return value if isinstance(value, date) else date.fromisoformat(value)
    if column == "updated_at":
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value))
    return value


def _rows(table: str, rows: list[dict]) -> Counter:
    # 자료의 물리적 조회 순서는 기대 원본의 일부가 아니며 중복 개수는 보존한다.
    return Counter(
        tuple(_cell(column, row[column]) for column in _COLUMNS[table]) for row in rows
    )


def _matches(actual: dict, fixture: dict) -> bool:
    return all(
        _rows(table, actual[table]) == _rows(table, fixture.get(table, []))
        for table in TABLES
    )


def verify_fixture(settings: Settings, fixture: dict) -> None:
    """6개 테이블 전체를 같은 읽기 전용 스냅샷으로 비교한다."""
    validate_fixture(fixture)
    with _connect(settings) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        if not _matches(_read_tables(connection), fixture):
            raise ValueError("evaluation database differs from database_fixture")


def prepare_database(settings: Settings, fixture: dict) -> PreparationResult:
    """빈 평가 DB에 한 트랜잭션으로 적재한다. 같은 원본이면 변경하지 않는다."""
    validate_fixture(fixture)
    counts = {table: len(fixture.get(table, [])) for table in TABLES}
    with _connect(settings) as connection:
        connection.execute(
            sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(
                sql.SQL(", ").join(map(_table_identifier, TABLES))
            )
        )
        actual = _read_tables(connection)
        if _matches(actual, fixture):
            return {"status": "unchanged", "rows": counts}
        if any(actual.values()):
            raise ValueError(
                "evaluation tables must be empty or match database_fixture"
            )
        for table in TABLES:
            columns = _COLUMNS[table]
            statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                _table_identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            )
            for row in fixture.get(table, []):
                connection.execute(
                    statement, tuple(_cell(column, row[column]) for column in columns)
                )
        if not _matches(_read_tables(connection), fixture):
            raise ValueError("inserted evaluation data differs from database_fixture")
    return {"status": "prepared", "rows": counts}
