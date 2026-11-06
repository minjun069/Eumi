"""명세 S1~S3의 D1~D3 가상 자료와 입력. 실행 로직은 포함하지 않는다."""

from src.tools.data import Dataset

CATALOG = {
    "D1": "A/B/C동 2025·2026년 8→9월 활동지수. region, year, august, september.",
    "D2": "활동지수의 기준·비교 범위·해석 한계. definition, limitation.",
    "D3": "2026-09-30 A~E동 가구 구성. region, elderly_single, total_households. "
    "전체 가구 대비 65세 이상 1인 가구 비율. 위험 순위가 아님.",
}


def dataset(target, columns, rows) -> Dataset:
    return {
        "reference": {"id": target, "version": "scenario-v1"},
        "as_of": "2026-09-30",
        "sources": [
            {
                "label": f"시연용 예시 데이터: 가상 자료 {target}",
                "uri": f"fixture://scenarios/{target}/scenario-v1",
            }
        ],
        "columns": [
            {
                "name": name,
                "kind": kind,
                "unit": unit,
                "spatial_unit": "동",
                "temporal_unit": "월",
                "denominator": "동별 2025년 1월 활동량"
                if target == "D1"
                else "전체 가구",
            }
            for name, kind, unit in columns
        ],
        "rows": rows,
    }


def activity():
    return dataset(
        "D1",
        [
            ("region", "string", "동"),
            ("year", "integer", "년"),
            ("august", "number", "index"),
            ("september", "number", "index"),
        ],
        [
            {"region": region, "year": year, "august": august, "september": september}
            for region, year, august, september in [
                ("A동", 2026, 120, 108),
                ("B동", 2026, 100, 92),
                ("C동", 2026, 80, 72),
                ("A동", 2025, 110, 99),
                ("B동", 2025, 100, 92),
                ("C동", 2025, 90, 81),
            ]
        ],
    )


def definitions():
    return dataset(
        "D2",
        [
            ("definition", "string", "설명"),
            ("limitation", "string", "설명"),
        ],
        [
            {
                "definition": "각 동의 2025년 1월 활동량을 100으로 환산. "
                "8→9월 변화율=(9월-8월)/8월×100. 전년 동월 대비와 다름.",
                "limitation": "고립 위험 점수가 아니며 동 간 절대 활동량 비교 불가. "
                "한 해 비교로 계절성·원인 확정 불가. 지역·집단 관측에 한정.",
            }
        ],
    )


def households():
    return dataset(
        "D3",
        [
            ("region", "string", "동"),
            ("elderly_single", "integer", "가구"),
            ("total_households", "integer", "가구"),
        ],
        [
            {"region": region, "elderly_single": elderly, "total_households": total}
            for region, elderly, total in [
                ("A동", 1250, 10000),
                ("B동", 768, 8000),
                ("C동", 1728, 12000),
                ("D동", 639, 9000),
                ("E동", 1232, 11000),
            ]
        ],
    )


PROVIDERS = {"D1": activity, "D2": definitions, "D3": households}
S1 = (
    "A동 2026년 9월 활동지수를 D1·D2로 해석한다. "
    "전월 변화율·인접 B/C동·전년도 동일 기간의 변화율을 비교하고 "
    "지표 정의·한계·출처와 비교표를 제공한다."
)
S2 = "2026년 9월 말 기준으로 동별 고령 1인 가구 비율을 높은 순서대로 그래프로 보여줘."
S3 = "이 그래프에서 A동은 어떻게 읽으면 돼? 고립 위험이 두 번째로 높다는 뜻이야?"
SCREEN = (
    "현재 화면: A~E동, D3, 2026-09-30. 가로 막대, 비율 내림차순, "
    "0~20%, 소수점 첫째 자리, 동일 파란색. 시연용 예시 데이터."
)
