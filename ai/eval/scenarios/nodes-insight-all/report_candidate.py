"""실제 활동 집계·원지표로 세 동의 보고서 평가 경로를 구성한다.

작성한 모델 응답을 기존 노드와 실제 query_data·process_data에 연결한다.
원본 데이터셋과 운영 코드는 변경하지 않으며 품질 판정은 별도 평가 대상이다.
"""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from activity_evidence import ACTIVITY
from reference_evidence import DEFINITIONS
from report_profiles import (
    regional_numbers,
    regional_plan,
    regional_requirements,
    regional_texts,
    regional_view_requirements,
)

from eval.scripts.node_dataset_basic_reports import (
    ROLE_NAMES,
    _entry,
    _evidence,
    _query_arguments,
    basic_report_profiles,
)
from eval.scripts.node_dataset_paths import PathRecorder, dump_state, report_stage_state
from eval.scripts.node_dataset_report_paths import _template
from eval.scripts.node_dataset_reports import (
    CONTRIBUTION,
    DESCRIPTION,
    GRID,
    INSIGHT,
    REGION,
    SELECTION,
)
from src.agent_nodes import approved_report_selection, last_report_draft
from src.execution import accepted_outputs
from src.state import report_input

KEYS = ("EmbedDetailV07", "EmbedDetailV02", "EmbedDetailV08")
PROVIDERS = (ACTIVITY, REGION, CONTRIBUTION, GRID, DEFINITIONS)
CRITERIA_PATH = Path(__file__).with_name("report-quality-criteria.json")
CRITERIA_BYTES = CRITERIA_PATH.read_bytes()
QUALITY_CRITERIA = json.loads(CRITERIA_BYTES)
LIMITS = (
    "활동 평균은 24개 시간대 일평균 활동값의 평균이며 고유 주민 수가 아니다. "
    "고령층 남성 비중과 남녀 변화율 격차는 상대적 구성 지표이며 여성의 "
    "절대 증감을 제공하지 않는다. 여성 감소와 여성 유지·남성 증가의 해석은 "
    "조건부이며 확인된 원인이 아니다. 동 단위 성별 차이를 특정 격자의 "
    "성별 감소로 옮기지 않는다. 기여도는 지표를 도시·월 중앙값으로 바꾼 "
    "점수 차이이지 점수 변화의 가산 분해가 아니다. V08은 현재 월 분포이며 "
    "8~12월 순위와 월간 증감은 같은 격자의 과거 조회를 보완 근거로 대조한 "
    "결과다. 순위는 자기보다 높은 격자 수에 1을 더한 경쟁순위로 계산한다. "
    "격자 점수의 상승을 실제 외출·왕래 감소나 고립자 밀집으로 확정하지 "
    "않으며 주거지 여부와 현장 정보는 앞으로 확인할 대상이다."
)


def _data_records(state):
    accepted = accepted_outputs(state)
    return [
        record
        for record in state["results"]
        if record["id"] in accepted
        and isinstance(record.get("output"), dict)
        and "data" in record["output"]
    ]


def _derived(state, column):
    return next(
        record
        for record in reversed(_data_records(state))
        if column in {item["name"] for item in record["output"]["data"]["columns"]}
    )


def _number_pattern(value):
    rendered = format(value, ",.6f").rstrip("0").rstrip(".")
    core = rendered.replace(".", r"\.").replace(",", ",?")
    number = rf"\+?({core}0*)" if "." in rendered else rf"\+?({core}(?:\.0+)?)"
    return rf"(?s)^.*?(?<![\d.+-]){number}(?![\d.]).*$"


def _facts(state):
    records = _evidence(state)
    contributions = _derived(state, "contribution_change")["output"]["data"]["rows"]
    grid_history = deepcopy(records[GRID]["output"]["data"]["rows"])
    grid_months = sorted({row["period_start"] for row in grid_history})
    grid_sets = {
        month: {row["grid_cd"] for row in grid_history if row["period_start"] == month}
        for month in grid_months
    }
    assert all(keys == grid_sets[grid_months[0]] for keys in grid_sets.values())
    assert all(row["anomaly_score"] is not None for row in grid_history)
    assert all(
        len(keys) == sum(row["period_start"] == month for row in grid_history)
        for month, keys in grid_sets.items()
    )
    grid_ranks = {
        month: {
            row["grid_cd"]: 1
            + sum(
                other["anomaly_score"] > row["anomaly_score"]
                for other in grid_history
                if other["period_start"] == month
            )
            for row in grid_history
            if row["period_start"] == month
        }
        for month in grid_months
    }
    current_grids = sorted(
        [row for row in grid_history if row["period_start"] == "2025-12-01"],
        key=lambda row: row["anomaly_score"],
        reverse=True,
    )
    return {
        "monthly_scores": {
            row["period_start"]: deepcopy(row)
            for row in records[REGION]["output"]["data"]["rows"]
        },
        "monthly_activity": {
            row["period_start"]: deepcopy(row)
            for row in records[ACTIVITY]["output"]["data"]["rows"]
        },
        "activity_current": deepcopy(
            _derived(state, "activity_percent_change")["output"]["data"]["rows"][0]
        ),
        "activity_rank_low_first": 1
        + sum(
            row["activity_hourly_mean"]
            < _derived(state, "activity_percent_change")["output"]["data"]["rows"][0][
                "activity_hourly_mean"
            ]
            for row in records[ACTIVITY]["output"]["data"]["rows"]
        ),
        "score_current": deepcopy(
            _derived(state, "score_change")["output"]["data"]["rows"][0]
        ),
        "grid_rows": current_grids,
        "grid_history": grid_history,
        "grid_ranks": grid_ranks,
        "grid_rank_definition": "1 + 같은 동·월에서 자기보다 점수가 높은 격자 수",
        "grid_rows_per_month": {month: len(keys) for month, keys in grid_sets.items()},
        "grid_changes": deepcopy(
            _derived(state, "grid_score_change")["output"]["data"]["rows"]
        ),
        "contributions": {row["indicator_cd"]: deepcopy(row) for row in contributions},
        "definitions": {
            row["indicator_cd"]: deepcopy(row)
            for row in records[DEFINITIONS]["output"]["data"]["rows"]
        },
        "source_rows": {
            target: deepcopy(record["output"]["data"]["rows"])
            for target, record in records.items()
        },
        "computed_records": {
            record["id"]: deepcopy(record["output"]["data"])
            for record in _data_records(state)
            if record.get("action", {}).get("name") == "process_data"
        },
    }


def _dogok_texts(state):
    facts = _facts(state)
    activity = facts["activity_current"]
    monthly = facts["monthly_activity"]
    first, second = facts["grid_rows"][:2]
    changed = facts["grid_changes"][0]
    decline = abs(activity["activity_percent_change"])
    descriptions = {
        KEYS[0]: (
            f"12월 평균 활동규모는 {activity['activity_hourly_mean']:,.2f}로, "
            f"11월보다 {decline:.2f}% 줄었으며 최근 6개월 중 두 번째로 낮았습니다. "
            f"다만 8월에 {monthly['2025-08-01']['activity_hourly_mean']:,.2f}까지 "
            "낮아졌다가 9월에 "
            f"{monthly['2025-09-01']['activity_hourly_mean']:,.2f}으로 "
            "회복했던 흐름을 함께 보면, 도곡1동은 활동이 계속 줄어온 지역보다는 "
            "등락 속에서 최근 지역 이용이 다시 줄어든 상황으로 해석할 수 있습니다."
        ),
        KEYS[1]: (
            "12월 점수를 가장 크게 설명하는 두 항목은 고령층 남녀의 활동 변화율 "
            "차이와 남성 비중이며, 원지표에서도 60세 이상 남성의 활동 변화율이 "
            f"여성보다 {activity['h29_senior_gender_change_gap']:.2f}%p 높았습니다. "
            "여성의 실제 활동이 줄었다면, 고령 여성이 일상적인 생활공간을 이용하고 "
            "이웃과 마주칠 기회가 좁아졌을 가능성에 주목할 필요가 있습니다. "
            "반대로 여성 활동은 유지되고 남성 활동만 늘었다면, 이번 구성 변화는 "
            "남성의 지역 이용이 확대된 상황으로 해석합니다."
        ),
        KEYS[2]: (
            f"12월 현재 점수가 가장 높은 격자는 {first['grid_cd']}"
            f"({first['anomaly_score']:.2f}점)와 {second['grid_cd']}"
            f"({second['anomaly_score']:.2f}점)입니다. "
            "같은 격자의 과거 월별 자료를 추가로 대조하면 두 곳은 8~12월 내내 "
            f"동 안에서 상위 5위였던 반면, {changed['grid_cd']}은 전월보다 "
            f"{changed['grid_score_change']:.2f}점 올라 상승폭이 가장 컸고 순위도 "
            f"{facts['grid_ranks']['2025-11-01'][changed['grid_cd']]}위에서 "
            f"{facts['grid_ranks']['2025-12-01'][changed['grid_cd']]}위로 바뀌어 "
            "이번 달 새롭게 두드러진 변화를 보여줍니다. "
            f"최근 생활 변화를 확인할 출발점으로 {changed['grid_cd']}의 주거지 여부를 "
            "먼저 확인하고, 주거지에 해당한다면 해당 구역의 11~12월 외출·왕래 "
            "감소에 관한 현장 정보를 우선 대조해보세요."
        ),
    }
    reasons = {
        KEYS[0]: (
            "7~12월 활동 평균과 전월 변화율로 현재 수준을 최근 6개월 안에 "
            "위치시킨다. 12월이 두 번째로 낮다는 점과 8월 감소 뒤 9월 회복을 "
            "함께 비교해 지속적인 하락과 등락 후 최근 이용 감소를 구분한다. "
            "현재 상황의 시간적 맥락을 설명하는 역할이며 별도 행동 권고를 "
            "억지로 붙이지 않는다. 확보하지 않은 시간대·요일별 위축이나 주민 "
            "관계 약화는 설명 범위에 포함하지 않는다."
        ),
        KEYS[1]: (
            "12월 점수 기여도가 가장 큰 고령층 남녀 변화율 차이와 남성 비중을 "
            "보여주고 같은 동·월의 실제 성별 원지표를 보완 근거로 연결한다. "
            "남성 변화율이 여성보다 2.58%p 높은 상대적 차이에서 여성의 절대 "
            "감소를 확정하지 않는다. 여성 활동 감소라면 생활공간 이용·이웃과 "
            "마주칠 기회 축소 가능성으로, 여성 유지·남성 증가라면 남성 지역 "
            "이용 확대로 해석을 나눈다. 이 두 조건을 구분하려면 성별 절대 "
            "활동값 확인이 필요하지만 현재 원자료 없이 조건부 해석을 제공한다. "
            "같은 성별 자료에서 파생한 지표들을 독립된 원인으로 세지 않는다."
        ),
        KEYS[2]: (
            "12월 격자 분포에서 현재 높은 두 곳을 확인하고, 선정 단계부터 "
            "8~12월 같은 105개 격자의 과거 점수·순위와 11~12월 증감 비교를 "
            "보완 근거로 연결한다. 순위는 같은 동·월에서 자신보다 높은 격자 수 "
            "+1인 경쟁순위다. 다사588429·다사587430의 지속 상위 5위와 "
            "다사588431의 최대 상승 4.72점·40→8위를 구분해 최근 변화 확인의 "
            "출발점을 제안한다. V08이 과거 추이를 직접 표시한다고 설명하지 "
            "않으며 과거 자료를 별도로 대조한 결과라고 밝힌다. 다사588431의 "
            "주거지 여부를 먼저 확인하고 주거지라면 11~12월 외출·왕래 감소 "
            "관련 현장 정보를 대조한다. 고령 여성의 변화가 이 격자에 집중됐거나 "
            "실제 외출 감소·고립자 밀집이 확인됐다고 확장하지 않는다."
        ),
    }
    insight = "\n".join(
        [
            (
                f"도곡1동의 12월 활동규모는 전월보다 {decline:.2f}% 줄어 최근 6개월 중 "
                "두 번째로 낮았으며, 이전의 감소와 회복을 거친 뒤 지역 이용이 다시 "
                "줄어든 상황입니다."
            ),
            (
                "동 전체의 고령층에서는 활동 구성이 남성 쪽으로 기울었으며, 여성의 "
                "실제 활동 감소가 확인된다면 여성의 일상적인 만남과 생활공간 이용 "
                "기회가 좁아졌을 가능성에 주목할 필요가 있습니다."
            ),
            (
                "다사588429·다사587430은 계속 상위권이었던 곳이고, 다사588431은 "
                "이번 달 상승폭이 가장 크면서 새로 상위권에 진입했으므로 최근 "
                "변화를 확인할 후보로 먼저 검토할 수 있습니다."
            ),
            (
                "다사588431이 주거지에 해당한다면, 해당 구역의 11~12월 외출·왕래 "
                "감소에 관한 현장 정보를 우선 확인해보세요."
            ),
        ]
    )
    return descriptions, reasons, insight


def _dogok_view_requirements(view_key):
    criteria = {
        KEYS[0]: {
            "required_meanings": [
                (
                    "12월 평균·전월 감소율과 최근 6개월 중 두 번째로 낮다는 위치를 "
                    "실제 7~12월 자료로 설명한다."
                ),
                (
                    "8월 감소 뒤 9월 회복을 함께 읽고 지속 하락이 아니라 등락 뒤 "
                    "최근 지역 이용이 다시 감소한 상황으로 해석한다."
                ),
                (
                    "지역 이용의 시간적 맥락을 설명하는 뷰이므로 별도 현장 "
                    "행동이나 주민 관계 가설을 강제하지 않는다."
                ),
                (
                    "활동 평균의 정의를 보존하고 고유 주민 수·고령층 절대 "
                    "활동·특정 시간대 변화로 바꾸지 않는다."
                ),
            ],
            "failure_examples": [
                "12월 감소율만 제시해 최근 6개월의 위치와 이전 회복을 빠뜨린다.",
                "6개월 내내 활동이 줄었다고 쓴다.",
                (
                    "근거 없는 주민 관계 약화 가설이나 일반적인 발굴 권고로 시간 "
                    "비교를 대신한다."
                ),
            ],
        },
        KEYS[1]: {
            "required_meanings": [
                (
                    "당월 기여도 상위 두 항목과 실제 고령층 남녀 변화율 격차를 "
                    "구분하고 기여도와 원지표를 연결한다."
                ),
                (
                    "여성 활동 감소가 실제 확인된다면 여성 생활공간 이용과 이웃을 "
                    "만날 기회가 좁아졌을 가능성으로 해석한다."
                ),
                (
                    "반대로 여성 유지·남성 증가 조건이라면 남성의 지역 이용 확대로 "
                    "해석한다. 조건에 따라 상황 해석 자체가 달라져야 한다."
                ),
                (
                    "현재 확보한 상대적 차이만으로 여성의 절대 활동 감소를 "
                    "확정하지 않는다. 같은 자료에서 나온 성별 비중과 변화율 차이를 "
                    "독립된 원인으로 세지 않는다."
                ),
                (
                    "성별 절대 활동값은 현재 미확보이며 후속 확인 대상이다. "
                    "상세값을 기다리거나 모든 해석을 보류하지 않고 조건부 해석을 "
                    "제시한다."
                ),
            ],
            "failure_examples": [
                (
                    "성별 차이가 있다는 말과 확인 권고만 쓰고 두 조건의 다른 "
                    "해석을 생략한다."
                ),
                "여성 활동 감소나 남성 절대 증가를 현재 확인한 사실로 쓴다.",
                "2.58%p를 남성 비중 변화량이나 h29의 월간 차이로 쓴다.",
                "성별 원지표만 설명해 기여도 차트와의 연결을 빠뜨린다.",
            ],
        },
        KEYS[2]: {
            "required_meanings": [
                (
                    "12월 점수가 가장 높은 두 격자와 점수를 정확히 연결하고, 같은 "
                    "격자의 월별 자료를 비교해 8~12월 내내 동 안에서 상위 5위 "
                    "이내였음을 확인한다."
                ),
                (
                    "동일한 105개 격자의 11~12월 점수 차이를 비교해 다사588431이 "
                    "4.72점으로 가장 큰 상승폭을 보인 유일한 격자이며, 경쟁 순위는 "
                    "40위에서 8위로 바뀌었음을 설명한다."
                ),
                (
                    "계속 높은 수준을 유지한 곳과 이번 달 새롭게 두드러진 곳을 "
                    "구별하고, 최근 생활 변화를 확인할 출발점으로 다사588431을 "
                    "제안한다."
                ),
                (
                    "V08은 현재 분포를 보여주며 과거 순위와 증감은 추가로 대조한 "
                    "보완 자료임을 밝힌다. 순위는 자신보다 점수가 높은 격자 수에 "
                    "1을 더한 값이며 밀집 순위와 혼용하지 않는다."
                ),
                (
                    "주거지 여부를 먼저 확인하고, 주거지인 경우 11~12월 외출·왕래 "
                    "감소와 관련된 현장 정보를 우선 대조한다. 실제 외출 감소와 "
                    "주거지 여부, 고립자의 존재는 확인되지 않았다."
                ),
                (
                    "동 단위 고령층 성별 지표를 다사588431의 여성 감소와 연결하지 "
                    "않는다."
                ),
            ],
            "failure_examples": [
                (
                    "현재 높은 두 격자만 제시하고 계속 상위권이었던 곳과 최근 "
                    "상승폭이 가장 큰 곳의 차이를 놓친다."
                ),
                "과거 자료 없이 현재 분포만으로 새롭게 상승했다고 설명한다.",
                (
                    "실제 월별 근거가 있는데도 현재 분포라는 이유만으로 모든 시점 "
                    "비교를 금지한다."
                ),
                "다사588431을 고령 여성 감소나 고립자 밀집이 확인된 곳으로 쓴다.",
                (
                    "주거지 여부를 확인해야 한다는 조건을 지우고 개인 방문 대상을 "
                    "확정한다."
                ),
            ],
        },
    }
    return {
        **deepcopy(criteria[view_key]),
        "allowed_variation": (
            "각 뷰는 최대 3문장 안에서 같은 의미의 표현과 순서를 허용한다. "
            "시간적 맥락, 조건에 따른 상반된 해석, 지속된 신호와 최근 변화의 "
            "구분이라는 각 역할을 보존한다. 보고서 전체에서 필요한 후속 확인은 "
            "구체적으로 제시하되 모든 뷰에 같은 행동·주의문·생활 가설을 강제하지 "
            "않는다."
        ),
    }


def _dogok_requirements(role):
    if role == INSIGHT:
        required = [
            (
                "승인된 설명의 전월 대비 감소, 최근 6개월 중 낮은 수준, 과거 감소 "
                "후 회복을 연결해 등락 속에서 최근 지역 이용이 다시 줄어든 상황을 "
                "요약한다."
            ),
            (
                "동 전체 고령층의 활동 구성이 남성 쪽으로 바뀐 것을 상대적 관계로 "
                "표현한다. 여성의 절대 활동 감소가 확인될 경우 생활공간 이용과 "
                "만남의 기회가 줄었을 가능성이 있다는 조건을 보존한다."
            ),
            (
                "계속 상위권이었던 두 격자와 이번 달 상승폭이 가장 크고 새롭게 "
                "상위권에 진입한 다사588431을 구별해 최근 변화를 확인할 후보로 "
                "제시한다."
            ),
            (
                "다사588431이 주거지에 해당한다는 조건과 11~12월 외출·왕래 감소에 "
                "관한 현장 정보 대조를 승인 범위 안에서 요약한다."
            ),
        ]
        allowed = (
            "항목당 한 문장, 총 3~4개 문장으로 요약하며 모든 숫자와 해석 분기를 "
            "반복하지 않아도 된다. 다만 선택한 가설의 조건을 지우거나 동 전체의 "
            "성별 차이를 특정 격자에 적용하지 않는다. 새로운 현장 사실이나 행동을 "
            "추가하지 않는다."
        )
    else:
        required = [
            (
                "V07은 최근 6개월 중 현재 수준과 감소 후 회복을, V02는 기여도와 "
                "원지표의 연결 및 조건에 따른 해석 차이를, V08은 계속 상위권이었던 "
                "곳과 최근 상승폭이 가장 큰 곳을 설명하도록 선정한다."
            ),
            (
                "선정 단계부터 V07에는 7~12월 활동 근거를, V02에는 성별 "
                "원지표·기여도·정의를, V08에는 12월 분포와 같은 격자의 8~12월 "
                "순위·11~12월 증감을 확인할 보완 근거를 연결한다."
            ),
            (
                "격자 순위가 경쟁 순위의 정의를 따르고 월별 관측 범위가 일치하는지 "
                "확인하며, V08의 표시값과 과거 자료를 추가로 대조한 결과를 "
                "구분한다."
            ),
            (
                "최근 변화를 확인하기 위한 다사588431의 후보 선정, 주거지 여부 "
                "확인, 조건부 현장 정보 대조를 설명 범위에 포함한다."
            ),
            (
                "어느 뷰에도 기존 이용자 관리, 추상적인 발굴 강화, 불필요한 "
                "주의문을 강제하지 않는다. 확보한 자료가 지지하는 해석과 구분해야 "
                "할 조건을 우선한다."
            ),
        ]
        allowed = (
            "확보한 근거에 맞는 동등한 뷰 조합과 표현을 허용한다. 각 뷰가 같은 "
            "형식의 가설과 행동을 반복할 필요는 없으며 선정 이유에 모든 수치를 "
            "본문처럼 재진술할 필요도 없다."
        )
    return {
        "required_meanings": required,
        "allowed_variation": allowed,
        "failure_examples": [
            (
                "수치나 일반적인 주의문만 제시해 시점 비교, 조건에 따른 해석, 공간 "
                "변화의 차이를 놓친다."
            ),
            (
                "관측에 맞는 해석을 만들지 않고 모든 뷰에 비슷한 운영·지원 조치를 "
                "붙인다."
            ),
            (
                "계속 높은 곳과 새롭게 변한 곳을 구분하지 않고 현재 순위만으로 "
                "후보를 정한다."
            ),
            (
                "여성의 절대 활동 감소, 격자별 성별 변화, 현장에서의 고립 상태를 "
                "근거 없이 확정한다."
            ),
        ],
        "role_scope": role,
    }


def _dogok_number_requirements(facts, role, view_key):
    activity = facts["activity_current"]
    activity_change = round(abs(activity["activity_percent_change"]), 2)
    if role == INSIGHT:
        return [("activity_decline", activity_change)]
    if role != DESCRIPTION:
        return []
    if view_key == KEYS[0]:
        return [
            ("activity_current", round(activity["activity_hourly_mean"], 2)),
            ("activity_decline", activity_change),
            (
                "activity_august",
                round(
                    facts["monthly_activity"]["2025-08-01"]["activity_hourly_mean"], 2
                ),
            ),
            (
                "activity_september",
                round(
                    facts["monthly_activity"]["2025-09-01"]["activity_hourly_mean"], 2
                ),
            ),
        ]
    if view_key == KEYS[1]:
        return [
            ("gender_change_gap", round(activity["h29_senior_gender_change_gap"], 2))
        ]
    changed = facts["grid_changes"][0]
    return [
        ("grid_first", facts["grid_rows"][0]["anomaly_score"]),
        ("grid_second", facts["grid_rows"][1]["anomaly_score"]),
        ("grid_largest_change", changed["grid_score_change"]),
        ("grid_previous_rank", facts["grid_ranks"]["2025-11-01"][changed["grid_cd"]]),
        ("grid_current_rank", facts["grid_ranks"]["2025-12-01"][changed["grid_cd"]]),
    ]


def selected_keys(state):
    code = report_input(state)["dongCode"]
    return KEYS if code == "1168065500" else regional_plan(code)["keys"]


def _texts(state):
    if report_input(state)["dongCode"] == "1168065500":
        return _dogok_texts(state)
    return regional_texts(_facts(state))


def view_requirements(view_key, code="1168065500"):
    if code == "1168065500":
        return _dogok_view_requirements(view_key)
    return regional_view_requirements(code, view_key)


def _requirements(role, code="1168065500"):
    if code == "1168065500":
        return _dogok_requirements(role)
    return regional_requirements(code, role)


def number_requirements(facts, role, view_key):
    if facts["activity_current"]["adm_cd10"] == "1168065500":
        return _dogok_number_requirements(facts, role, view_key)
    return regional_numbers(facts, role, view_key)


def _assessment(state, profile, node, role, outputs, condition):
    template = _template({}, state, profile, node, role, condition, output=outputs[0])
    template["providers"] = list(PROVIDERS)
    template["tags"] += ["basic-agent", "conversation:none", "insight-review-candidate"]
    assessment = template["assessment"]
    for check, reference in assessment["reference"].items():
        reference["limitations"] = LIMITS
        reference["evidence_basis"]["limitations"] = LIMITS
        reference["quality_criteria_source"] = {
            "path": CRITERIA_PATH.name,
            "sha256": sha256(CRITERIA_BYTES).hexdigest(),
        }
        criteria = [
            item
            for item in QUALITY_CRITERIA["role_requirements"].get(role, [])
            if item["check"] == check
        ] + [
            item for item in QUALITY_CRITERIA["claim_checks"] if item["check"] == check
        ]
        if check == "N04-O.3":
            criteria += QUALITY_CRITERIA["role_requirements"]["report_review"]
        if criteria:
            reference["quality_criteria"] = deepcopy(criteria)
        if check == "N04-O.1":
            reference["analysis_chain"] = deepcopy(QUALITY_CRITERIA["analysis_chain"])
            reference["evidence_sufficiency"] = deepcopy(
                QUALITY_CRITERIA["benchmark_evidence_sufficiency"]
            )
    if node == "act":
        for check in ("N02-O.3", "N02-B.2", "N-B.1"):
            assessment["reference"][check].update(
                expected_arguments=json.loads(outputs[0]["arguments_json"]),
                allowed_variation=(
                    "대상·기간·자료·연산 의미가 같은 인자 표현을 허용한다."
                ),
            )
    if node != "compose":
        return template
    facts = _facts(state)
    requirements = (
        view_requirements(selected_keys(state)[0], profile["code"])
        if role == DESCRIPTION
        else _requirements(role, profile["code"])
    )
    requirements["role_scope"] = role
    for check in (
        "N04-O.1",
        "N04-B.1",
        "N-O.2",
        "N-O.3",
        "N-O.4",
        "N-O.5",
        "N-O.10",
        "N04-O.3",
    ):
        assessment["reference"][check].update(deepcopy(requirements))
        assessment["reference"][check]["independent_observations"] = deepcopy(facts)
    if role in (DESCRIPTION, INSIGHT):
        assessment["expected"]["items"] = [
            item for item in assessment["expected"]["items"] if item["check"] != "N-O.1"
        ]
        assessment["reference"]["N-O.1"]["independent_observations"] = deepcopy(facts)
        for label, value in number_requirements(facts, role, selected_keys(state)[0]):
            assessment["expected"]["items"].append(
                {
                    "id": f"N-O.1-{label}",
                    "check": "N-O.1",
                    "node": "compose",
                    "role": role,
                    "call": "ReportText",
                    "call_index": 1,
                    "path": "/content",
                    "pattern": _number_pattern(value),
                    "extract": "number",
                    "value": value,
                    "tolerance": {"absolute": 0.005},
                }
            )
    return template


async def _build_region_report(snapshot, recorder, profile):
    "한 지역의 세 역할을 실제 노드와 같은 State로 순차 실행한다."
    state = _entry(recorder, profile)
    upstream_id = None
    plan = None if profile["code"] == "1168065500" else regional_plan(profile["code"])
    keys = KEYS if plan is None else plan["keys"]

    async def step(node, role, current, outputs, reason):
        return await recorder.step(
            node,
            role,
            current,
            outputs,
            template=_assessment(current, profile, node, role, outputs, reason),
            label=reason,
        )

    async def decide(role, current, target, reason):
        evidence_ids = [record["id"] for record in _data_records(current)]
        result = await step(
            "decide", role, current, [{"next": target, "reason": reason}], reason
        )
        recorder.current.setdefault("decision_basis", []).append(
            {
                "step_id": recorder.current["steps"][-1]["step_id"],
                "evidence_ids": evidence_ids,
                "reason": reason,
            }
        )
        return result

    async def tool(current, name, arguments, reason):
        current = await decide(SELECTION, current, "act", reason)
        before = len(current["results"])
        result = await step(
            "act",
            SELECTION,
            current,
            [
                {
                    "name": name,
                    "arguments_json": json.dumps(arguments, ensure_ascii=False),
                    "reason": reason,
                }
            ],
            reason,
        )
        calls = [
            record
            for record in result["results"][before:]
            if record["decision"] == "call"
        ]
        if len(calls) != 1 or calls[0]["outcome"] != "success":
            raise AssertionError(
                f"Expected successful actual tool call: {reason}: {calls}"
            )
        return result, calls[0]

    async def process(current, source_id, operations, reason):
        return await tool(
            current,
            "process_data",
            {"input_result_id": source_id, "operations": operations, "decimals": 6},
            reason,
        )

    def month_filter(month):
        return {
            "operation": "filter",
            "conditions": [
                {"field": "period_start", "operator": "eq", "value": month + "-01"}
            ],
        }

    for role in (SELECTION, DESCRIPTION, INSIGHT):
        identity = f"candidate-{role}-{profile['code']}"
        before = dump_state(state)
        state = report_stage_state(state, role)
        recorder.begin(
            identity,
            f"{profile['name']} {profile['month']} {ROLE_NAMES[role]}"
            " 인사이트 개선 후보",
            "analysis_pipeline",
            "insight-review-report",
            axes={"selected_view_count": 3, "current_event": "normal"},
        )
        recorder.current.update(
            scope="agent",
            agent_role=role,
            region_code=profile["code"],
            region_name=profile["name"],
            conversation_condition="none",
            upstream_scenario_id=upstream_id,
            entry_transition={
                "kind": "report_handoff",
                "before_state": before,
                "after_state": dump_state(state),
            },
        )
        if role == SELECTION:
            for target, reason in (
                (
                    ACTIVITY,
                    (
                        "7~12월 활동 평균과 성별 원지표를 조회해 현재 활동의 6개월 "
                        "내 위치와 이전 회복, 성별 상대 차이를 확인한다."
                    ),
                ),
                (
                    REGION,
                    (
                        "지역 점수 추이를 비교 후보로 확인하되 실제 활동 추세와 "
                        "같은 지표로 해석하지 않는다."
                    ),
                ),
                (
                    CONTRIBUTION,
                    (
                        "현재 점수 기여도 상위 항목을 전월과 비교하고 실제 성별 "
                        "원지표와 연결해 조건별로 해석한다."
                    ),
                ),
                (
                    GRID,
                    (
                        "8~12월 같은 동의 격자 점수를 조회해 현재 높은 곳의 지속 "
                        "여부와 최근 가장 크게 변한 곳을 구분한다."
                    ),
                ),
            ):
                if plan is not None:
                    reason = plan["query_reasons"][target]
                arguments = _query_arguments(
                    state, REGION if target == ACTIVITY else target
                )
                arguments["target"] = target
                if target == GRID:
                    arguments["filters"] = [
                        {
                            "field": "adm_cd10",
                            "operator": "eq",
                            "value": profile["code"],
                        },
                        {
                            "field": "period_start",
                            "operator": "ge",
                            "value": "2025-08-01",
                        },
                        {
                            "field": "period_start",
                            "operator": "le",
                            "value": "2025-12-01",
                        },
                    ]
                    arguments["sort"] = [
                        {"field": "period_start", "descending": False},
                        {"field": "anomaly_score", "descending": True},
                        {"field": "grid_cd", "descending": False},
                    ]
                state, _ = await tool(state, "query_data", arguments, reason)
            state, definitions = await tool(
                state,
                "query_data",
                {"target": DEFINITIONS, "limit": 100},
                (
                    "활동 원지표와 점수 기여도의 뜻·단위·계산 "
                    "방법을 조회해 가능한 해석의 범위를 구분한다."
                ),
            )
            records = _evidence(state)
            for target, fields, calculations, reason in (
                (
                    ACTIVITY,
                    {
                        "activity_hourly_mean": "previous_activity_hourly_mean",
                        "h18_senior_male_share": "previous_senior_male_share",
                    },
                    [
                        {
                            "operation": "calculate",
                            "method": "difference",
                            "before": "previous_activity_hourly_mean",
                            "after": "activity_hourly_mean",
                            "output": "activity_change",
                        },
                        {
                            "operation": "calculate",
                            "method": "percent_change",
                            "before": "previous_activity_hourly_mean",
                            "after": "activity_hourly_mean",
                            "output": "activity_percent_change",
                        },
                    ],
                    (
                        "실제 SQL 평균의 전월 차이·변화율을 "
                        "계산하고 원지표의 남성 비중을 같은 동·월끼리 "
                        "비교한다. 활동 변화는 6개월 시계열의 현재 위치로, "
                        "성별 차이는 여성 감소와 여성 유지·남성 증가라는 "
                        "조건에 따른 서로 다른 해석의 근거로 사용한다."
                    ),
                ),
                (
                    REGION,
                    {"bh_score": "previous_score"},
                    [
                        {
                            "operation": "calculate",
                            "method": "difference",
                            "before": "previous_score",
                            "after": "bh_score",
                            "output": "score_change",
                        }
                    ],
                    (
                        "행동 점수의 전월 차이를 계산하고 조회된 월별 "
                        "순서와 함께 재상승의 성격을 판단한다. 이 점수만으로 "
                        "생활상 결론을 만들지 않는다. 최종 설명의 핵심은 "
                        "실제 활동의 추세와 조건별 해석, 격자의 월간 변화다."
                    ),
                ),
                (
                    CONTRIBUTION,
                    {"contribution": "previous_contribution"},
                    [
                        {
                            "operation": "calculate",
                            "method": "difference",
                            "before": "previous_contribution",
                            "after": "contribution",
                            "output": "contribution_change",
                        },
                        {
                            "operation": "join",
                            "right_result_id": definitions["id"],
                            "keys": ["indicator_cd"],
                            "how": "inner",
                            "fields": {
                                "label": "label",
                                "definition": "definition",
                                "interpretation_limit": "interpretation_limit",
                            },
                        },
                    ],
                    (
                        "동일 행동 지표의 기여도를 전월과 비교하고 "
                        "정의를 결합해 원지표와 점수 설명의 관계를 "
                        "구분한다. 같은 성별 자료에서 나온 상위 두 항목을 "
                        "독립 원인으로 세지 않고 상대적 차이의 서로 다른 "
                        "가능한 설명을 구분한다."
                    ),
                ),
            ):
                if plan is not None:
                    reason = plan["process_reasons"][target]
                state, previous = await process(
                    state,
                    records[target]["id"],
                    [month_filter("2025-11")],
                    (
                        "조회 결과에서 전월 행을 분리해 동일 대상의 "
                        "월간 비교 근거를 준비한다."
                    ),
                )
                state, _ = await process(
                    state,
                    records[target]["id"],
                    [
                        month_filter("2025-12"),
                        {
                            "operation": "join",
                            "right_result_id": previous["id"],
                            "keys": ["adm_cd10", "indicator_cd"]
                            if target == CONTRIBUTION
                            else ["adm_cd10"],
                            "how": "inner",
                            "fields": fields,
                        },
                        *calculations,
                    ],
                    reason,
                )
            state, _ = await process(
                state,
                records[ACTIVITY]["id"],
                [
                    {
                        "operation": "sort",
                        "by": [{"field": "activity_hourly_mean", "descending": False}],
                    }
                ],
                (
                    "6개월 활동 평균을 낮은 순으로 대조해 12월의 위치를 확인하고 "
                    "원래 월 순서의 감소·회복과 함께 해석한다."
                ),
            )
            state, grid_previous = await process(
                state,
                records[GRID]["id"],
                [month_filter("2025-11")],
                "같은 동의 11월 격자 자료를 분리해 12월과 동일 격자끼리 비교한다.",
            )
            state, _ = await process(
                state,
                records[GRID]["id"],
                [
                    month_filter("2025-12"),
                    {
                        "operation": "join",
                        "right_result_id": grid_previous["id"],
                        "keys": ["adm_cd10", "grid_cd"],
                        "how": "inner",
                        "fields": {"anomaly_score": "previous_grid_score"},
                    },
                    {
                        "operation": "calculate",
                        "method": "difference",
                        "before": "previous_grid_score",
                        "after": "anomaly_score",
                        "output": "grid_score_change",
                    },
                    {
                        "operation": "sort",
                        "by": [{"field": "grid_score_change", "descending": True}],
                    },
                ],
                (
                    "같은 동에서 관측된 동일 격자의 11~12월 차이를 구해 "
                    "상승폭을 비교한다. "
                    "월별 순위는 각 달에서 자기보다 높은 격자 수에 1을 더한 "
                    "경쟁순위로 읽어 공동순위 뒤 번호를 건너뛴다."
                ),
            )
            descriptions, reasons, insight = _texts(state)
            all_records = _data_records(state)

            def connected_ids(targets, records, all_records):
                included = {records[target]["id"] for target in targets}
                for record in all_records:
                    action = record.get("action") or {}
                    if (
                        action.get("name") == "process_data"
                        and action["arguments"]["input_result_id"] in included
                    ):
                        included.add(record["id"])
                return [
                    record["id"] for record in all_records if record["id"] in included
                ]

            views = [
                {
                    "view_key": key,
                    "reason": reasons[key],
                    "evidence_ids": connected_ids(targets, records, all_records),
                }
                for key, targets in zip(
                    keys,
                    plan["targets"]
                    if plan is not None
                    else (
                        (ACTIVITY,),
                        (ACTIVITY, CONTRIBUTION, DEFINITIONS),
                        (GRID,),
                    ),
                    strict=True,
                )
            ]
            outputs = [
                {"views": views},
                {
                    "accepted": True,
                    "reason": (
                        "세 뷰의 역할을 6개월 추세 맥락, 성별 변화의 조건별 해석, "
                        "지속 상위권과 최근 최대 상승의 구분으로 정했다. V08에는 "
                        "현재 분포와 같은 격자의 과거 월별 점수·경쟁순위·증감을 "
                        "선정부터 연결했다. 지역 이용이 계속 줄었다거나 여성 감소가 "
                        "확인됐다고 쓰지 않으며, 최근 변화 확인의 후보를 "
                        "다사588431로 좁히는 이유와 주거지 확인 조건이 있다. "
                        "각 뷰에 동일한 행동이나 주의문을 강제하지 않는다."
                    ),
                },
            ]
            reason = (
                "7~12월 활동의 현재 위치와 이전 감소·회복, 고령층 남녀 상대 "
                "차이를 구분할 실제 조건, 현재 높은 격자와 최근 가장 크게 "
                "오른 격자의 차이가 이번 보고서의 핵심이다. 각 뷰에 해당 "
                "관측과 비교 근거를 연결하고 V08에는 현재 표시 범위를 보완하는 "
                "과거 월별 비교를 명시한다. 최근 변화 확인은 다사588431의 "
                "주거지 여부를 먼저 확인한 뒤 현장 정보와 대조하도록 범위를 정한다."
            )
            if plan is not None:
                outputs[1]["reason"] = plan["selection_review"]
                reason = plan["selection_reason"]
        elif role == DESCRIPTION:
            selected = approved_report_selection(state)
            if not selected:
                raise AssertionError("Approved selection required")
            descriptions, reasons, insight = _texts(state)
            review_reasons = {
                KEYS[0]: (
                    "12월 평균과 감소율, 최근 6개월 중 두 번째로 낮다는 위치가 "
                    "자료와 일치한다. 8월 감소 뒤 9월 회복을 함께 읽어 지속적인 "
                    "하락과 등락 후 최근 이용 감소를 구분했다. 두 문장이며 "
                    "시간 비교가 해석을 제공하므로 불필요한 행동을 요구하지 않는다."
                ),
                KEYS[1]: (
                    "상위 두 기여 항목과 실제 남녀 변화율 격차를 구분했다. "
                    "여성 감소라면 생활공간·만남 기회 축소 가능성, 여성 유지·"
                    "남성 증가라면 남성 이용 확대로 서로 다른 해석을 제시했다. "
                    "각 조건은 미확인이며 여성 절대 감소나 특정 격자의 성별 "
                    "변화로 확장하지 않았다. 세 문장이다."
                ),
                KEYS[2]: (
                    "현재 가장 높은 두 격자는 8~12월 내내 상위 5위이고, "
                    "다사588431은 같은 105개 격자 중 유일한 최대 상승 4.72점과 "
                    "경쟁순위 40→8위를 보였다. 과거 자료를 추가 대조한 결과임을 "
                    "명시해 V08의 현재 표시 범위와 구분했다. 최근 변화 확인 "
                    "목적에 맞게 이 격자의 주거지 여부를 먼저 확인하고 조건부로 "
                    "11~12월 외출·왕래 현장 정보를 대조하도록 했다. 세 문장이다."
                ),
            }
            if plan is not None:
                review_reasons = plan["description_reviews"]
            outputs = [
                output
                for view in selected["output"]["views"]
                for output in (
                    {"content": descriptions[view["view_key"]]},
                    {"accepted": True, "reason": review_reasons[view["view_key"]]},
                )
            ]
            reason = (
                "각 뷰가 맡은 시간 비교·조건별 해석·공간 변화의 차이를 "
                "승인 근거 안에서 작성한다. 모든 뷰에 행동을 덧붙이지 않고 "
                "최근 변화 후보를 선택하는 V08에서 주거지 조건과 현장 확인을 "
                "구체화한다. 사용자 최종 문안을 유지하며 최대 세 문장을 지킨다."
            )
            if plan is not None:
                reason = plan["description_reason"]
        else:
            selected = approved_report_selection(state)
            if not selected:
                raise AssertionError("Approved selection required")
            drafts = [
                last_report_draft(state, view["view_key"])
                for view in selected["output"]["views"]
            ]
            accepted = accepted_outputs(state)
            if not all(draft and draft["id"] in accepted for draft in drafts):
                raise AssertionError("Approved descriptions required")
            descriptions, reasons, insight = _texts(state)
            outputs = [
                {"content": insight},
                {
                    "accepted": True,
                    "reason": (
                        "네 문장이 승인 설명의 등락 뒤 최근 이용 감소, 여성 "
                        "활동 감소가 확인될 경우의 생활상 의미, 지속 상위 두 "
                        "격자와 새롭게 변한 다사588431의 차이를 보존한다. "
                        "주거지 조건과 11~12월 현장 정보 확인은 승인된 범위다. "
                        "동 전체 성별 변화를 이 격자의 여성 감소로 합치지 않고 "
                        "요약에서 새로운 현장 사실이나 조치를 추가하지 않았다."
                    ),
                },
            ]
            reason = (
                "승인 설명의 시간적 맥락·성별 조건부 해석·지속 신호와 신규 "
                "변화의 차이를 네 문장으로 요약한다. 최근 생활 변화를 확인할 "
                "다사588431 후보와 주거지 확인 조건을 유지하고 근거에 없는 "
                "발굴 방식·운영 조치나 개인 상태를 추가하지 않는다."
            )
            if plan is not None:
                outputs[1]["reason"] = plan["insight_review"]
                reason = plan["insight_reason"]
        state = await decide(role, state, "compose", reason)
        state = await step("compose", role, state, outputs, reason)
        recorder.end(state, terminal="completed")
        upstream_id = identity


async def build_report_candidate(snapshot: dict, recorder: PathRecorder) -> None:
    "세 지역의 선정·설명·인사이트 경로를 각 지역의 실제 근거로 구성한다."
    for profile in basic_report_profiles(snapshot):
        await _build_region_report(snapshot, recorder, profile)
