"""읽기 전용으로 확보한 동별 활동 지표를 검토 사본의 자료원으로 연결한다.

실제 SQL 반환값만 변환한다. 평균은 DB의 activity_daily / 24.0 조회 결과를
사용하며 원소수·SQL·수집시점·정의 근거는 activity-evidence.json에 보존한다.
"""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from typing import Literal

from src.tools.data import Column, Dataset, read_dataset

ACTIVITY = "analysis.bh_region_indicator"
EVIDENCE_PATH = Path(__file__).resolve().parent / "snapshots/activity-evidence.json"

# 원지표의 비교 단위와 분모를 보존한다. 서로 다른 지표를 같은 활동량으로
# 취급하지 않으며, 같은 열의 전월 비교는 기존 process_data로 수행한다.
NUMERIC_COLUMNS = {
    "activity_daily": ("일평균 추정 활동량의 24시간대 합", "해당 없음"),
    "h12_evening_day_ratio": ("배율", "09~17시 일평균 활동값의 평균"),
    "h13_commute_ratio": ("배율", "10~16시 일평균 활동값의 평균"),
    "h14_hour_entropy": ("nat", "24시간대 활동값 합계"),
    "h15_weekday_entropy": ("nat", "7요일별 일평균 활동값 합계"),
    "h18_senior_male_share": ("비율", "60세 이상 남녀 활동값 합계"),
    "h19_age_entropy": ("nat", "6개 연령대 활동값 합계"),
    "h20_senior_representation": ("배율", "60세 이상 주민 비율"),
    "h21_male50plus_representation": ("배율", "50세 이상 남성 주민 비율"),
    "h26_weekend_weekday_change_gap": ("%p", "주말·주중 각각의 전월 활동값"),
    "h29_senior_gender_change_gap": ("%p", "60세 이상 남녀 각각의 전월 활동값"),
    "h30_hour_profile_distance": ("거리", "당월·전월 각각의 24시간대 활동값 합계"),
    "h31_weekday_profile_distance": ("거리", "당월·전월 각각의 7요일 활동값 합계"),
    "activity_hourly_mean": ("시간대별 일평균 추정 활동값의 평균", "24시간대"),
}


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _column(
    name: str,
    kind: Literal["string", "number"],
    unit: str,
    denominator: str = "해당 없음",
) -> Column:
    return {
        "name": name,
        "kind": kind,
        "unit": unit,
        "spatial_unit": "행정동",
        "temporal_unit": "월",
        "denominator": denominator,
    }


def enrich_activity_snapshot(snapshot: dict) -> dict:
    """기존 자료를 보존한 deepcopy에 동별 원지표와 SQL 평균 6행을 추가한다."""
    if ACTIVITY in snapshot["datasets"] or ACTIVITY in snapshot["catalog"]:
        raise ValueError(f"자료원을 덮어쓰지 않습니다: {ACTIVITY}")
    payload = EVIDENCE_PATH.read_bytes()
    evidence = json.loads(payload)
    evidence_hash = sha256(payload).hexdigest()
    queries = evidence["queries"]
    raw = queries["region_indicators"]
    means = queries["activity_hourly_mean"]
    for query in (raw, means):
        if query["query_result_sha256"] != _digest(query["rows"]):
            raise ValueError("활동 자료의 원본 행 해시가 일치하지 않습니다.")
        if query["row_count"] != len(query["rows"]) or query["row_count"] != 6:
            raise ValueError("도곡1동 6개월 활동 자료가 필요합니다.")
    if (
        evidence["transaction"]["read_only"] != "on"
        or means["transaction"]["read_only"] != "on"
        or evidence["transaction"]["database"] != means["transaction"]["database"]
    ):
        raise ValueError("같은 DB에서 읽기 전용으로 확보한 자료가 아닙니다.")
    project = Path(__file__).resolve().parents[4]
    definition_files = (
        "data/pipeline/common/bh_indicators.py",
        "data/pipeline/m3_indicator/batch_bh_region_indicators.py",
    )
    for relative in definition_files:
        if (
            sha256((project / relative).read_bytes()).hexdigest()
            != evidence["source_files"][relative]
        ):
            raise ValueError(
                f"활동 합계 정의가 변경되어 재검토가 필요합니다: {relative}"
            )

    def key(row):
        return row["period_start"], row["adm_cd10"]

    averages = {key(row): row for row in means["rows"]}
    expected_keys = {(f"2025-{month:02d}-01", "1168065500") for month in range(7, 13)}
    if (
        len(averages) != 6
        or set(averages) != expected_keys
        or {key(row) for row in raw["rows"]} != expected_keys
    ):
        raise ValueError("활동 원지표와 SQL 평균의 대상·기간이 일치하지 않습니다.")
    raw_numeric = set(NUMERIC_COLUMNS) - {"activity_hourly_mean"}
    expected_columns = raw_numeric | {"period_start", "adm_cd10", "updated_at"}
    rows = []
    with localcontext() as context:
        context.prec = 50
        for source in raw["rows"]:
            if set(source) != expected_columns:
                raise ValueError("원지표 열이 기존 조회 계약과 다릅니다.")
            average_row = averages[key(source)]
            if any(
                source[field] != average_row[field]
                for field in ("activity_daily", "updated_at")
            ):
                raise ValueError("원지표와 평균 조회 사이에 원자료가 달라졌습니다.")
            total = Decimal(source["activity_daily"])
            average = Decimal(average_row["activity_hourly_mean"])
            scale = Decimal(1).scaleb(average.as_tuple().exponent)
            if average != (total / Decimal(24)).quantize(scale):
                raise ValueError("SQL 평균이 24시간대 합계 정의와 일치하지 않습니다.")
            row = {
                name: float(Decimal(value))
                if name in raw_numeric and value is not None
                else value
                for name, value in source.items()
            }
            row["activity_hourly_mean"] = float(average)
            rows.append(row)

    columns = [
        _column("period_start", "string", "기준월 첫날"),
        _column("adm_cd10", "string", "행정동코드"),
        *[
            _column(name, "number", unit, denominator)
            for name, (unit, denominator) in NUMERIC_COLUMNS.items()
        ],
        _column("updated_at", "string", "분석 수정 시각"),
    ]
    data: Dataset = {
        "reference": {"id": ACTIVITY, "version": "pending"},
        "as_of": max(row["updated_at"] for row in rows),
        "sources": [
            {
                "label": "서비스 DB의 읍면동 행동 원지표·활동 합계",
                "uri": "db://analysis/bh_region_indicator",
            },
            {
                "label": "읽기 전용 원본 조회 SQL·조건·정확소수·수집시점·출처 "
                f"(SHA-256 {evidence_hash})",
                "uri": EVIDENCE_PATH.as_uri(),
            },
            {
                "label": "24시간대 평균의 실제 SQL 조회·정의·Decimal 대조",
                "uri": EVIDENCE_PATH.as_uri() + "#/queries/activity_hourly_mean",
            },
            *[
                {
                    "label": "활동 합계·동별 집계 정의 "
                    f"(SHA-256 {evidence['source_files'][relative]})",
                    "uri": (project / relative).as_uri(),
                }
                for relative in definition_files
            ],
        ],
        "columns": columns,
        "rows": rows,
        "inputs": [
            {
                "id": f"activity-evidence:{name}",
                "version": queries[name]["query_result_sha256"],
            }
            for name in ("region_indicators", "activity_hourly_mean")
        ],
    }
    data["reference"]["version"] = _digest(
        {k: v for k, v in data.items() if k != "reference"}
    )
    result = deepcopy(snapshot)
    result["datasets"][ACTIVITY] = read_dataset(data)
    result["catalog"][ACTIVITY] = (
        "도곡1동(1168065500) 2025년 7~12월의 실제 DB 저장 원지표 6행. "
        "조회 열: period_start, adm_cd10, activity_daily, "
        + ", ".join(name for name in NUMERIC_COLUMNS if name.startswith("h"))
        + ", activity_hourly_mean, updated_at. "
        "activity_daily는 시간대별 일평균 추정 활동값 24개의 합계다. "
        "activity_hourly_mean은 SQL에서 activity_daily/24.0으로 실제 조회한 "
        "24시간대 평균으로 V07에 대응하며 고유 인원수가 아니다. 두 달의 같은 "
        "열을 조회·결합한 뒤 process_data로 차이·변화율을 계산한다. "
        "h18은 60세 이상 활동의 남성 비중, h29는 남성 변화율에서 여성 변화율을 "
        "뺀 %p이고 기여도와 다르다. 지표 정의는 reference.behavior_definitions를 "
        "함께 조회한다. NULL을 0으로 채우지 않으며, 성별 각각 활동량과 시간대·"
        "요일별 원값을 이 지표에서 역산하지 않는다. sources의 증거 JSON에 "
        "SQL·정확소수·수집시점·DB명·원본 해시를 보존했다. as_of는 자료의 최근 "
        "수정시각이며 수집시각·관측월과 구분한다. 원시 이동통신 자료의 수집 "
        "품질은 이번 조회에서 검증하지 않았다."
    )
    return result
