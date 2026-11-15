"""검토용 사본에 정적 판독한 행동 지표 정의를 추가한다.

파이프라인을 import하거나 실행하지 않는다. 원본 스냅샷의 자료·카탈로그와
State 계약은 유지하며, 반환한 사본에만 prepared 자료원 한 개를 추가한다.
"""

from __future__ import annotations

import ast
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

from src.tools.data import Dataset, read_dataset

DEFINITIONS = "reference.behavior_definitions"
METHOD = "contribution_method"
CONTRIBUTION = "analysis.bh_region_contribution"

# 판독한 산식이 바뀌면 정의를 다시 검토한다. 원본 코드는 실행하지 않는다.
_SOURCE_HASHES = {
    "data/pipeline/common/bh_indicators.py": (
        "3b42f939a177b111f6341ba2c2d865f2e162088c61dcd5e9a78430c36e2b813a"
    ),
    "data/pipeline/m3_indicator/batch_bh_region_indicators.py": (
        "fd4c2064fda00699461ad924def3539874c630cc9a6dbbee2766822a58e581f1"
    ),
    "data/pipeline/m4_analysis/batch_bh_contribution.py": (
        "9637db798c1d95ba9de10e9036fd7e5ee2f85fdb60a6ccdc443b0b6104139901"
    ),
}


class DefinitionRow(TypedDict):
    indicator_cd: str
    label: str
    definition: str
    interpretation_limit: str


# common/bh_indicators.py: indicators, entropy, js_distance, ratio。
# h20/h21: m3_indicator/batch_bh_region_indicators.py: region_indicators, resident。
_MEANINGS = {
    "h12_evening_day_ratio": (
        "18~21시 4개 시간대 일평균 활동값의 평균을 09~17시 9개 값의 평균으로 나눈다. "
        "값이 클수록 낮에 비해 저녁 활동의 상대적 수준이 높다.",
        "비율의 변화만으로 저녁 활동의 절대 증가·감소를 알 수 없다. 낮 활동의 변화도 "
        "비율에 영향을 준다.",
    ),
    "h13_commute_ratio": (
        "07·08·09·17·18·19시 6개 시간대 일평균 활동값의 평균을 10~16시 7개 값의 "
        "평균으로 나눈다. "
        "값이 클수록 비교 낮 시간보다 출퇴근 시간대에 활동이 상대적으로 집중된다.",
        "해당 시간의 활동을 실제 직장인·학생이나 통근 목적의 이동으로 식별한 값은 "
        "아니다.",
    ),
    "h14_hour_entropy": (
        "24개 시간대 일평균 활동값을 합계로 나눈 비중 p에 대해 -Σ p·ln(p)를 계산한다. "
        "0인 비중의 항은 0이며, 값이 클수록 시간대별 활동이 고르게 분포한다.",
        "균등도는 활동 총량이나 사회적 관계의 질이 아니다. 값이 낮아져도 어느 시간대가 "
        "줄었는지는 원값이 필요하다.",
    ),
    "h15_weekday_entropy": (
        "월~일 7개 요일별 일평균 활동값의 비중 p에 대해 -Σ p·ln(p)를 계산한다. "
        "0인 비중의 항은 0이며, 값이 클수록 요일별 활동이 고르게 분포한다.",
        "요일별 일평균의 구성이다. 특정 주의 반복 변화나 월간 누적 방문 비중으로 "
        "해석하지 않는다.",
    ),
    "h18_senior_male_share": (
        "60세 이상 남성 활동값을 60세 이상 남성과 여성의 활동값 합계로 나눈다. "
        "값이 클수록 관측된 60세 이상 활동에서 남성 비중이 높다.",
        "주민의 남성 비율이 아니다. 남성 활동 증가와 여성 활동 감소 모두 "
        "비중을 높일 수 있어 절대 변화는 구별해야 한다.",
    ),
    "h19_age_entropy": (
        "성·연령 12개 활동값에서 남녀를 같은 연령끼리 합쳐 10·20·30·40·50대·60세 이상 "
        "6개 집단을 만든 뒤, "
        "연령별 비중 p의 -Σ p·ln(p)를 계산한다. 값이 클수록 여러 연령에 활동이 고르게 "
        "분포한다.",
        "원지표가 낮으면 특정 연령에 더 집중된 구성이다. 기여도의 증감만으로 원지표의 "
        "증감이나 특정 연령 활동 감소를 정할 수 없다.",
    ),
    "h20_senior_representation": (
        "(60세 이상 남녀 활동 합계 / 성·연령 12개 집단 활동 합계)를 "
        "(같은 달 60세 이상 주민 수 / 전체 주민 수)로 나눈다. "
        "1보다 작으면 주민 구성에 비해 관측 활동에서 60세 이상 비중이 낮다.",
        "활동은 장소 기준이며 방문자가 포함된다. 같은 주민의 외출률이 아니고, 다른 "
        "연령의 유입 증가에 의한 비중 변화도 가능하다.",
    ),
    "h21_male50plus_representation": (
        "(50대 남성 및 60세 이상 남성 활동 합계 / 성·연령 12개 집단 활동 합계)를 "
        "(같은 달 50세 이상 남성 주민 수 / 전체 주민 수)로 나눈다. "
        "1보다 작으면 주민 구성에 비해 관측 활동에서 50세 이상 남성 비중이 낮다.",
        "주민 구성과 장소 기반 활동 구성의 상대 비교다. 개인의 외출·직업·고립 상태나 "
        "동일인의 변화를 직접 측정하지 않는다.",
    ),
    "h26_weekend_weekday_change_gap": (
        "주말은 토·일 일평균의 평균, 주중은 월~금 일평균의 평균으로 정한다. "
        "100×[(당월 주말/전월 주말-1)-(당월 주중/전월 주중-1)]이다. "
        "음수이면 주말 변화율이 주중보다 낮고 양수이면 높다.",
        "음수만으로 주말 활동 감소를 확정할 수 없다. 모두 증가하되 주말 증가율이 더 "
        "낮을 수도 있다. 월별 요일 수를 곱한 누적값이 아니다.",
    ),
    "h29_senior_gender_change_gap": (
        "100×[(당월 60세 이상 남성 활동/전월 60세 이상 남성 활동-1)"
        "-(당월 60세 이상 여성 활동/전월 60세 이상 여성 활동-1)]이다. "
        "남성 변화율에서 여성 변화율을 뺀 값이며 음수이면 남성 변화율이 더 낮다.",
        "음수는 남성의 더 큰 감소뿐 아니라 더 작은 증가일 수도 있다. 기여도가 양수라는 "
        "사실은 이 원지표의 부호나 감소한 성별을 알려주지 않는다.",
    ),
    "h30_hour_profile_distance": (
        "당월과 전월의 24개 시간대 활동 비중 p,q 및 중간 분포 m=(p+q)/2를 구해 "
        "sqrt((KL₂(p||m)+KL₂(q||m))/2)를 계산한다. 0~1의 Jensen-Shannon 거리로, 클수록 "
        "시간대 구성이 달라졌다.",
        "전체 활동의 증가·감소와 별개인 분포 변화다. 시간대 구성이 같으면 "
        "규모가 달라도 0이 될 수 있다.",
    ),
    "h31_weekday_profile_distance": (
        "당월과 전월의 7개 요일별 일평균 활동 비중 p,q 및 m=(p+q)/2에 대해 "
        "sqrt((KL₂(p||m)+KL₂(q||m))/2)를 계산한다. 0~1의 Jensen-Shannon 거리로, 클수록 "
        "요일 구성이 달라졌다.",
        "요일 구성의 변화이며 특정 요일의 절대 감소나 장기 계절성을 의미하지 않는다. "
        "시간대 집계와 합쳐 교차 집단을 만들 수 없다.",
    ),
}


def enrich_snapshot(snapshot: dict) -> dict:
    """원본을 보존하고 12개 지표와 기여도 방법의 13행 자료원을 사본에 추가한다.

    as_of는 기여도 스냅샷과의 결합을 위한 prepared-fixture 기준시점이다.
    코드 작성일·원자료 관측일·정의 확인일로 사용하지 않는다.
    """
    result = deepcopy(snapshot)
    if DEFINITIONS in result["datasets"] or DEFINITIONS in result["catalog"]:
        raise ValueError(f"자료원을 덮어쓰지 않습니다: {DEFINITIONS}")
    project = Path(__file__).resolve().parents[4]
    sources = []
    labels = None
    for relative, expected_hash in _SOURCE_HASHES.items():
        path = project / relative
        payload = path.read_bytes()
        actual_hash = sha256(payload).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"정의 원본이 변경되어 재검토가 필요합니다: {relative}")
        sources.append(
            {
                "label": f"정적 판독한 파이프라인 원본: {relative}",
                "uri": f"{path.as_uri()}#sha256={actual_hash}",
            }
        )
        if relative.endswith("common/bh_indicators.py"):
            tree = ast.parse(payload.decode("utf-8-sig"))
            assignment = next(
                node
                for node in tree.body
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "LABELS"
                    for target in node.targets
                )
            )
            labels = ast.literal_eval(assignment.value)
    if labels is None or set(labels) != set(_MEANINGS):
        raise ValueError("12개 지표 코드와 LABELS의 대응을 확인할 수 없습니다.")

    rows: list[DefinitionRow] = []
    common_limit = (
        " 이 행은 원지표 정의이며 실제 관측값을 추가하지 않는다. 기여도는 별도의 "
        "contribution_method 행에 따른 점수 차이이므로 원지표값과 구별한다. "
        "분모가 0 이하이거나 전월 자료가 필요한 계산에 전월이 없으면 미산출이며 0으로 "
        "바꾸지 않는다."
    )
    for code, (definition, limit) in _MEANINGS.items():
        label, unit = labels[code]
        rows.append(
            {
                "indicator_cd": code,
                "label": label,
                "definition": f"{definition} 단위: {unit}.",
                "interpretation_limit": limit + common_limit,
            }
        )
    rows.append(
        {
            "indicator_cd": METHOD,
            "label": "행동 지표 기여도 산출 방법",
            "definition": (
                "지표 j의 기여도는 원래 12개 지표로 계산한 B에서, 지표 j만 같은 "
                "도시·같은 달의 "
                "분석 결과가 있는 읍면동들의 해당 지표 중앙값으로 바꿔 계산한 B를 뺀 "
                "값이다. "
                "나머지 11개 지표는 유지하며 같은 읍면동 모델의 행동점수 "
                "B=-score_samples×100을 쓴다. "
                "양수는 해당 항목을 중앙값으로 바꾸면 모델 점수가 낮아짐을, 음수는 "
                "높아짐을 뜻한다. 단위: 점."
            ),
            "interpretation_limit": (
                "양·음은 원지표가 중앙값보다 크거나 작다는 뜻이 아니다. 한 항목씩 "
                "치환한 모델 설명값이며 "
                "인과 효과·개인의 고립 확률·활동 증감 방향이 아니다. 12개 값은 점수나 "
                "월간 점수 변화의 "
                "가산 분해가 아니므로 합계 또는 특정 항목의 비중을 점수 상승 설명률로 "
                "쓰지 않는다. "
                "월별 중앙값도 달라질 수 있으므로 기여도 증감만으로 원지표 증감을 "
                "정하지 않는다."
            ),
        }
    )

    contribution = result["datasets"][CONTRIBUTION]
    key_column = deepcopy(
        next(c for c in contribution["columns"] if c["name"] == "indicator_cd")
    )
    columns = [key_column] + [
        {
            "name": name,
            "kind": "string",
            "unit": unit,
            "spatial_unit": "지표 정의",
            "temporal_unit": "정적 정의",
            "denominator": "해당 없음",
        }
        for name, unit in [
            ("label", "지표 한글 이름"),
            ("definition", "지표·기여도 산식 설명"),
            ("interpretation_limit", "해석 범위"),
        ]
    ]
    data: Dataset = {
        "reference": {"id": DEFINITIONS, "version": "pending"},
        "as_of": contribution["as_of"],
        "sources": sources,
        "columns": columns,
        "rows": rows,
        "inputs": [deepcopy(contribution["reference"])],
    }
    version_payload = {key: value for key, value in data.items() if key != "reference"}
    data["reference"]["version"] = sha256(
        json.dumps(
            version_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    result["datasets"][DEFINITIONS] = read_dataset(data)
    result["catalog"][DEFINITIONS] = (
        "검토 사본의 prepared 참고자료: 원본 파이프라인을 실행하지 않고 "
        "LABELS와 산식을 정적으로 판독한 "
        "행동 지표 12개 및 contribution_method 1개, 총 13행이다. 조회 열은 "
        "indicator_cd, label, "
        "definition, interpretation_limit(모두 string)이다. 정의는 실제 활동 원값을 "
        "제공하지 않는다. "
        "indicator_cd로 지표 기여도와 연결하며 원지표 부호·활동 방향과 기여도 부호를 "
        "구별한다. "
        "as_of는 기여도 스냅샷과 맞춘 prepared-fixture 기준이며 코드 작성일이나 2025년 "
        "관측일이 아니다. "
        "sources의 원본 파일 URI·SHA-256과 reference.version으로 판독 출처와 사본 "
        "버전을 추적한다."
    )
    return result
