"""보고서 연결 검증용 합성 자료. 실제 지역 통계나 분석 결과가 아니다."""

from src.database import REPORT_SOURCES
from src.tools.data import read_dataset


def datasets(body):
    year, month = map(int, body["month"].split("-"))
    rows = {name: [] for name in ("public.region_result", *REPORT_SOURCES)}
    for offset in range(6):
        y, m = divmod(year * 12 + month - 1 - 5 + offset, 12)
        for code in body["dongCodes"]:
            base = {
                "period_start": f"{y:04d}-{m + 1:02d}-01",
                "adm_cd10": code,
                "updated_at": f"{y:04d}-{m + 1:02d}-15T00:00:00",
            }
            rows["public.region_result"].append(
                base
                | {
                    "bg_score": 40.0,
                    "bg_grade": 2,
                    "bh_score": 30.0 + offset,
                    "bh_grade": 2,
                    "risk_grade": 2,
                }
            )
            rows["analysis.bh_region_contribution"].extend(
                base | {"indicator_cd": key, "contribution": value}
                for key, value in (("SAMPLE_A", 10.0 + offset), ("SAMPLE_B", 20.0))
            )
            rows["analysis.bh_grid_anomaly"].extend(
                base
                | {"grid_cd": f"SAMPLE_{i}", "anomaly_score": 0.1 * i + offset / 100}
                for i in range(1, 5)
            )
            rows["analysis.flow_detail"].extend(
                base
                | {
                    "dim_type": "weekday",
                    "dim_value": day,
                    "activity_daily": float(100 + i * 10 - offset * 2),
                }
                for i, day in enumerate(
                    ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
                )
            )
    columns = {name: info[3] for name, info in REPORT_SOURCES.items()} | {
        "public.region_result": [
            ("period_start", "string", "기준월 첫날"),
            ("adm_cd10", "string", "행정동코드"),
            ("bg_score", "number", "배경 점수"),
            ("bg_grade", "integer", "단계(1~5)"),
            ("bh_score", "number", "행동 점수"),
            ("bh_grade", "integer", "단계(1~5)"),
            ("risk_grade", "integer", "단계(1~5)"),
            ("updated_at", "string", "분석 수정 시각"),
        ]
    }
    return {
        name: read_dataset(
            {
                "reference": {"id": name, "version": "synthetic-report-v1"},
                "as_of": body["month"] + "-15",
                "sources": [
                    {
                        "label": "연결 검증용 합성 자료; 실제 통계 아님",
                        "uri": f"fixture://reports/{name}",
                    }
                ],
                "columns": [
                    {
                        "name": key,
                        "kind": kind,
                        "unit": unit,
                        "spatial_unit": "100m 격자"
                        if name.endswith("anomaly")
                        else "행정동",
                        "temporal_unit": "월",
                        "denominator": "해당 없음",
                    }
                    for key, kind, unit in columns[name]
                ],
                "rows": values,
            }
        )
        for name, values in rows.items()
    }
