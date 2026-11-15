"""DB·서비스 호출 없이 고정 원시 행과 독립 계산표로 평가 입력을 만든다."""

import json
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

A, B = "1168066000", "5111061100"
G1, G2, G3 = "EVAL000001", "EVAL000002", "EVAL000003"
OCT, NOV = "2025-10-01", "2025-11-01"
ROOT = Path(__file__).resolve().parent


def fixture():
    """서비스 마이그레이션의 여섯 테이블에 넣을 모든 열을 명시한다."""
    return {
        "public.dim_region": [
            {
                "adm_cd10": A,
                "adm_cd8": "00000001",
                "adm_nm": "합성 평가동 A",
                "sgg_nm": "합성 평가시 A",
                "geom": None,
                "updated_at": "2025-10-01T09:00:00",
            },
            {
                "adm_cd10": B,
                "adm_cd8": "00000002",
                "adm_nm": "합성 평가동 B",
                "sgg_nm": "합성 평가시 B",
                "geom": None,
                "updated_at": "2025-10-01T09:00:00",
            },
        ],
        "public.region_result": [
            {
                "period_start": OCT,
                "adm_cd10": A,
                "bg_score": 30.25,
                "bg_grade": 2,
                "bh_score": 40.5,
                "bh_grade": 3,
                "risk_grade": 3,
                "updated_at": "2025-11-02T09:00:00",
            },
            {
                "period_start": OCT,
                "adm_cd10": B,
                "bg_score": 60.75,
                "bg_grade": 4,
                "bh_score": 20.25,
                "bh_grade": 2,
                "risk_grade": 3,
                "updated_at": "2025-11-02T10:00:00",
            },
            {
                "period_start": NOV,
                "adm_cd10": A,
                "bg_score": 35.5,
                "bg_grade": 3,
                "bh_score": 50.75,
                "bh_grade": 4,
                "risk_grade": 4,
                "updated_at": "2025-12-02T09:00:00",
            },
            {
                "period_start": NOV,
                "adm_cd10": B,
                "bg_score": 65.0,
                "bg_grade": 4,
                "bh_score": 25.0,
                "bh_grade": 2,
                "risk_grade": 4,
                "updated_at": "2025-12-02T10:00:00",
            },
        ],
        "analysis.dim_grid100": [
            {
                "grid_cd": G1,
                "gx": 1000,
                "gy": 1000,
                "updated_at": "2025-10-01T09:00:00",
                "adm_cd10": A,
            },
            {
                "grid_cd": G2,
                "gx": 1100,
                "gy": 1000,
                "updated_at": "2025-10-01T09:00:00",
                "adm_cd10": A,
            },
            {
                "grid_cd": G3,
                "gx": 2000,
                "gy": 2000,
                "updated_at": "2025-10-01T09:00:00",
                "adm_cd10": B,
            },
        ],
        "analysis.bh_region_contribution": [
            {
                "period_start": OCT,
                "adm_cd10": A,
                "indicator_cd": "h12_evening_day_ratio",
                "contribution": 1.25,
                "updated_at": "2025-11-03T09:00:00",
            },
            {
                "period_start": OCT,
                "adm_cd10": A,
                "indicator_cd": "h13_commute_ratio",
                "contribution": -0.5,
                "updated_at": "2025-11-03T10:00:00",
            },
            {
                "period_start": OCT,
                "adm_cd10": B,
                "indicator_cd": "h12_evening_day_ratio",
                "contribution": 2.5,
                "updated_at": "2025-11-03T11:00:00",
            },
            {
                "period_start": NOV,
                "adm_cd10": A,
                "indicator_cd": "h12_evening_day_ratio",
                "contribution": 3.75,
                "updated_at": "2025-12-03T09:00:00",
            },
            {
                "period_start": NOV,
                "adm_cd10": A,
                "indicator_cd": "h13_commute_ratio",
                "contribution": 0.25,
                "updated_at": "2025-12-03T10:00:00",
            },
            {
                "period_start": NOV,
                "adm_cd10": B,
                "indicator_cd": "h12_evening_day_ratio",
                "contribution": -1.25,
                "updated_at": "2025-12-03T11:00:00",
            },
        ],
        "analysis.bh_grid_anomaly": [
            {
                "period_start": OCT,
                "grid_cd": G1,
                "anomaly_score": 12.5,
                "updated_at": "2025-11-04T09:00:00",
            },
            {
                "period_start": OCT,
                "grid_cd": G2,
                "anomaly_score": None,
                "updated_at": "2025-11-04T10:00:00",
            },
            {
                "period_start": OCT,
                "grid_cd": G3,
                "anomaly_score": 27.75,
                "updated_at": "2025-11-04T11:00:00",
            },
            {
                "period_start": NOV,
                "grid_cd": G1,
                "anomaly_score": 30.0,
                "updated_at": "2025-12-04T09:00:00",
            },
            {
                "period_start": NOV,
                "grid_cd": G3,
                "anomaly_score": 15.25,
                "updated_at": "2025-12-04T11:00:00",
            },
        ],
        "analysis.flow_detail": [
            {
                "period_start": OCT,
                "dim_type": "hour",
                "dim_value": "08",
                "grid_cd": G1,
                "flow_sum": 300.0,
                "day_count": 30,
                "updated_at": "2025-11-04T09:00:00",
            },
            {
                "period_start": OCT,
                "dim_type": "hour",
                "dim_value": "08",
                "grid_cd": G2,
                "flow_sum": 620.0,
                "day_count": 31,
                "updated_at": "2025-11-04T10:00:00",
            },
            {
                "period_start": OCT,
                "dim_type": "hour",
                "dim_value": "09",
                "grid_cd": G1,
                "flow_sum": 150.0,
                "day_count": 30,
                "updated_at": "2025-11-04T09:00:00",
            },
            {
                "period_start": OCT,
                "dim_type": "hour",
                "dim_value": "09",
                "grid_cd": G2,
                "flow_sum": 0.0,
                "day_count": 30,
                "updated_at": "2025-11-04T10:00:00",
            },
            {
                "period_start": OCT,
                "dim_type": "weekday",
                "dim_value": "MON",
                "grid_cd": G1,
                "flow_sum": 40.0,
                "day_count": 4,
                "updated_at": "2025-11-04T09:00:00",
            },
            {
                "period_start": OCT,
                "dim_type": "weekday",
                "dim_value": "MON",
                "grid_cd": G2,
                "flow_sum": 60.0,
                "day_count": 4,
                "updated_at": "2025-11-04T10:00:00",
            },
            {
                "period_start": OCT,
                "dim_type": "sex_age",
                "dim_value": "M_60P",
                "grid_cd": G1,
                "flow_sum": 90.0,
                "day_count": 30,
                "updated_at": "2025-11-04T09:00:00",
            },
            {
                "period_start": OCT,
                "dim_type": "sex_age",
                "dim_value": "M_60P",
                "grid_cd": G2,
                "flow_sum": 120.0,
                "day_count": 30,
                "updated_at": "2025-11-04T10:00:00",
            },
            {
                "period_start": OCT,
                "dim_type": "hour",
                "dim_value": "08",
                "grid_cd": G3,
                "flow_sum": 150.0,
                "day_count": 30,
                "updated_at": "2025-11-04T11:00:00",
            },
            {
                "period_start": NOV,
                "dim_type": "hour",
                "dim_value": "08",
                "grid_cd": G1,
                "flow_sum": 60.0,
                "day_count": 30,
                "updated_at": "2025-12-04T09:00:00",
            },
            {
                "period_start": NOV,
                "dim_type": "hour",
                "dim_value": "08",
                "grid_cd": G2,
                "flow_sum": 90.0,
                "day_count": 30,
                "updated_at": "2025-12-04T10:00:00",
            },
            {
                "period_start": NOV,
                "dim_type": "weekday",
                "dim_value": "MON",
                "grid_cd": G1,
                "flow_sum": 40.0,
                "day_count": 0,
                "updated_at": "2025-12-04T11:00:00",
            },
            {
                "period_start": NOV,
                "dim_type": "weekday",
                "dim_value": "MON",
                "grid_cd": G2,
                "flow_sum": 80.0,
                "day_count": 4,
                "updated_at": "2025-12-04T12:00:00",
            },
            {
                "period_start": NOV,
                "dim_type": "sex_age",
                "dim_value": "F_60P",
                "grid_cd": G3,
                "flow_sum": None,
                "day_count": 30,
                "updated_at": "2025-12-04T13:00:00",
            },
        ],
    }


def source_rows(raw):
    """사전에 작성한 그룹 계산표와 격자 소속 표를 반환한다."""
    flow_values = [
        (OCT, A, "hour", "08", 30.0, "2025-11-04T10:00:00"),
        (OCT, A, "hour", "09", 5.0, "2025-11-04T10:00:00"),
        (OCT, A, "sex_age", "M_60P", 7.0, "2025-11-04T10:00:00"),
        (OCT, A, "weekday", "MON", 25.0, "2025-11-04T10:00:00"),
        (OCT, B, "hour", "08", 5.0, "2025-11-04T11:00:00"),
        (NOV, A, "hour", "08", 5.0, "2025-12-04T10:00:00"),
        (NOV, A, "weekday", "MON", None, "2025-12-04T12:00:00"),
        (NOV, B, "sex_age", "F_60P", None, "2025-12-04T13:00:00"),
    ]
    flow_fields = (
        "period_start",
        "adm_cd10",
        "dim_type",
        "dim_value",
        "activity_daily",
        "updated_at",
    )
    flow = [dict(zip(flow_fields, values, strict=True)) for values in flow_values]
    # 기준값 30/5/7/25/5/5/null/null을 원시 행의 십진수 산식으로 재확인한다.
    membership = {
        row["grid_cd"]: row["adm_cd10"] for row in raw["analysis.dim_grid100"]
    }
    for expected in flow:
        selected = [
            row
            for row in raw["analysis.flow_detail"]
            if (
                row["period_start"],
                membership[row["grid_cd"]],
                row["dim_type"],
                row["dim_value"],
            )
            == tuple(expected[key] for key in flow_fields[:4])
        ]
        actual = (
            None
            if any(row["day_count"] <= 0 or row["flow_sum"] is None for row in selected)
            else float(
                sum(
                    Decimal(str(row["flow_sum"])) / Decimal(row["day_count"])
                    for row in selected
                )
            )
        )
        assert actual == expected["activity_daily"]
        assert max(row["updated_at"] for row in selected) == expected["updated_at"]
    anomaly = [
        {
            "period_start": OCT,
            "adm_cd10": A,
            "grid_cd": G1,
            "anomaly_score": 12.5,
            "updated_at": "2025-11-04T09:00:00",
        },
        {
            "period_start": OCT,
            "adm_cd10": A,
            "grid_cd": G2,
            "anomaly_score": None,
            "updated_at": "2025-11-04T10:00:00",
        },
        {
            "period_start": OCT,
            "adm_cd10": B,
            "grid_cd": G3,
            "anomaly_score": 27.75,
            "updated_at": "2025-11-04T11:00:00",
        },
        {
            "period_start": NOV,
            "adm_cd10": A,
            "grid_cd": G1,
            "anomaly_score": 30.0,
            "updated_at": "2025-12-04T09:00:00",
        },
        {
            "period_start": NOV,
            "adm_cd10": B,
            "grid_cd": G3,
            "anomaly_score": 15.25,
            "updated_at": "2025-12-04T11:00:00",
        },
    ]
    return {
        "public.region_result": deepcopy(raw["public.region_result"]),
        "analysis.bh_region_contribution": deepcopy(
            raw["analysis.bh_region_contribution"]
        ),
        "analysis.bh_grid_anomaly": anomaly,
        "analysis.flow_detail": flow,
    }


def columns(target):
    specs = {
        "public.region_result": [
            ("period_start", "string", "기준월 첫날"),
            ("adm_cd10", "string", "행정동코드"),
            ("bg_score", "number", "배경 점수"),
            ("bg_grade", "integer", "단계(1~5)"),
            ("bh_score", "number", "행동 점수"),
            ("bh_grade", "integer", "단계(1~5)"),
            ("risk_grade", "integer", "단계(1~5)"),
            ("updated_at", "string", "분석 수정 시각(한국 시간)"),
        ],
        "analysis.bh_region_contribution": [
            ("period_start", "string", "기준월 첫날"),
            ("adm_cd10", "string", "행정동코드"),
            ("indicator_cd", "string", "행동 지표 코드"),
            ("contribution", "number", "행동 점수"),
            ("updated_at", "string", "분석 수정 시각"),
        ],
        "analysis.bh_grid_anomaly": [
            ("period_start", "string", "기준월 첫날"),
            ("adm_cd10", "string", "행정동코드"),
            ("grid_cd", "string", "격자코드"),
            ("anomaly_score", "number", "행동 이상 점수"),
            ("updated_at", "string", "분석 수정 시각"),
        ],
        "analysis.flow_detail": [
            ("period_start", "string", "기준월 첫날"),
            ("adm_cd10", "string", "행정동코드"),
            ("dim_type", "string", "구분"),
            ("dim_value", "string", "구분값"),
            ("activity_daily", "number", "일평균 추정 활동량"),
            ("updated_at", "string", "분석 수정 시각"),
        ],
    }
    return [
        {
            "name": name,
            "kind": kind,
            "unit": unit,
            "spatial_unit": "100m 격자"
            if target == "analysis.bh_grid_anomaly"
            else "행정동",
            "temporal_unit": "월",
            "denominator": "해당 없음",
        }
        for name, kind, unit in specs[target]
    ]


def version(rows):
    # DB 공급자의 공개된 행 스냅샷 직렬화 규칙. 입력은 위 독립 정답 행이다.
    return sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def make_case(
    case_id, purpose, arguments, source, expected, *, total=None, next_offset=None
):
    target = arguments["target"]
    metadata = columns(target)
    fields = arguments.get("fields", [col["name"] for col in metadata])
    as_of = max(row["updated_at"] for row in source)
    projected = [{name: row[name] for name in fields} for row in expected]
    applied = {
        "target": target,
        "version": version(source),
        "as_of": as_of,
        "fields": fields,
        "filters": [],
        "sort": [],
        "offset": 0,
        "limit": 100,
    } | arguments
    items = [
        ("T-I.1", "/observations/provider_calls", 1),
        ("T-I.1", "/output/applied", applied),
        ("T-O.1", "/output/data/rows", projected),
        (
            "T-O.1",
            "/output/data/columns",
            [next(c for c in metadata if c["name"] == name) for name in fields],
        ),
        ("T-O.1", "/output/total", len(expected) if total is None else total),
        ("T-O.1", "/output/returned", len(expected)),
        ("T-O.1", "/output/next_offset", next_offset),
        ("T-O.2", "/run/status", "returned"),
        ("T-O.2", "/failure", None),
        ("T-O.5", "/output/data/inputs", [{"id": target, "version": version(source)}]),
        ("T-O.5", "/output/data/as_of", as_of),
        ("T-O.5", "/output/data/sources/0/uri", "db://" + target.replace(".", "/")),
    ]
    return {
        "id": case_id,
        "unit": "tool",
        "target": "query_data",
        "purpose": purpose,
        "arguments": arguments,
        "assessment": {
            "required": True,
            "checks": ["T-I.1", "T-O.1", "T-O.2", "T-O.5"],
            "reference": {
                "fixture": "service-query.json#/database_fixture",
                "calculation": (
                    "generate_service_query.py: 고정 행·격자 소속·별도 그룹 계산표"
                ),
                "source": target,
                "source_version": version(source),
            },
            "expected": {
                "schema_version": "tool-expectations-v1",
                "items": [
                    {"check": check, "path": path, "value": value}
                    for check, path, value in items
                ],
            },
        },
    }


def build_suite():
    raw = fixture()
    sources = source_rows(raw)
    region = sources["public.region_result"]
    contribution = sources["analysis.bh_region_contribution"]
    flow = sources["analysis.flow_detail"]
    anomaly = sources["analysis.bh_grid_anomaly"]
    cases = [
        make_case(
            "DB-T01-01",
            "동·월별 분석 결과와 실제 DB 자료 참조를 조회한다.",
            {"target": "public.region_result"},
            region,
            region,
        ),
        make_case(
            "DB-T01-02",
            "10월 평가동 A의 지표 기여도를 내림차순으로 선택한다.",
            {
                "target": "analysis.bh_region_contribution",
                "filters": [
                    {"field": "period_start", "operator": "eq", "value": OCT},
                    {"field": "adm_cd10", "operator": "eq", "value": A},
                ],
                "sort": [{"field": "contribution", "descending": True}],
                "fields": ["indicator_cd", "contribution"],
            },
            contribution,
            contribution[:2],
        ),
        make_case(
            "DB-T01-03",
            "격자 소속을 결합해 동·월·구분별 일평균 활동량과 결측을 조회한다.",
            {"target": "analysis.flow_detail"},
            flow,
            flow,
        ),
        make_case(
            "DB-T01-04",
            "행정동이 원시 행에 없는 격자 이상 점수에 소속 동을 결합한다.",
            {"target": "analysis.bh_grid_anomaly"},
            anomaly,
            anomaly,
        ),
        make_case(
            "DB-T01-05",
            "적재하지 않은 월은 오류 없이 정상 0건으로 반환한다.",
            {
                "target": "public.region_result",
                "filters": [
                    {"field": "period_start", "operator": "eq", "value": "2026-01-01"}
                ],
            },
            region,
            [],
        ),
        make_case(
            "DB-T01-06",
            "11월 두 동을 행동 점수 내림차순으로 정렬하고 지정 열만 반환한다.",
            {
                "target": "public.region_result",
                "filters": [{"field": "period_start", "operator": "eq", "value": NOV}],
                "sort": [{"field": "bh_score", "descending": True}],
                "fields": ["adm_cd10", "bh_score", "risk_grade"],
            },
            region,
            [region[2], region[3]],
        ),
        make_case(
            "DB-T01-07",
            "배경 점수 내림차순의 첫 두 행과 다음 페이지 위치를 반환한다.",
            {
                "target": "public.region_result",
                "sort": [{"field": "bg_score", "descending": True}],
                "fields": ["adm_cd10", "period_start", "bg_score"],
                "limit": 2,
            },
            region,
            [region[3], region[1]],
            total=4,
            next_offset=2,
        ),
        make_case(
            "DB-T01-08",
            "독립 스냅샷 버전으로 같은 정렬의 다음 페이지를 조회한다.",
            {
                "target": "public.region_result",
                "version": version(region),
                "sort": [{"field": "bg_score", "descending": True}],
                "fields": ["adm_cd10", "period_start", "bg_score"],
                "offset": 2,
                "limit": 2,
            },
            region,
            [region[2], region[0]],
            total=4,
        ),
    ]
    return {
        "schema_version": "evaluation-suite-v1",
        "id": "database-service-query-v1",
        "data_source": "database",
        "database_fixture": raw,
        "cases": cases,
    }


if __name__ == "__main__":
    path = ROOT / "service-query.json"
    path.write_text(
        json.dumps(build_suite(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(path)
