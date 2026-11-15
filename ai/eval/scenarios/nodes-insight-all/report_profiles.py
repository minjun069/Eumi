"""대치4동·효자1동의 실제 관측에 따른 보고서 작성·평가 자료.

도곡1동의 사용자 승인 문안은 report_candidate.py에서 별도로 보존한다.
이 모듈은 기존 모델 응답과 assessment에 넣을 고정 사례를 제공하며
서비스의 State·모델 응답·도구 계약을 추가하지 않는다.
"""

from __future__ import annotations

from copy import deepcopy

from activity_evidence import ACTIVITY
from reference_evidence import DEFINITIONS

from eval.scripts.node_dataset_reports import (
    CONTRIBUTION,
    DESCRIPTION,
    GRID,
    INSIGHT,
    REGION,
)

DAECHI, HYOJA = "1168063000", "5111062000"
V01, V02, V07, V08 = (f"EmbedDetailV{number:02d}" for number in (1, 2, 7, 8))
KEYS = {DAECHI: (V07, V01, V08), HYOJA: (V07, V02, V08)}
MEANINGS = {
    DAECHI: {
        V07: [
            (
                "12월이 실제 7~12월 활동 평균 중 최저이며 10월 "
                "감소·11월 반등 뒤 더 낮아진 이용 축소라고 해석한다."
            ),
            (
                "활동의 시간 맥락으로 해석을 제공하며 별도 행동이나 주민 "
                "관계 가설을 강제하지 않는다."
            ),
        ],
        V01: [
            (
                "동일 기간 점수 하락과 실제 활동 감소를 연결해 기준 "
                "행동과의 차이 완화와 이용 회복을 구분한다."
            ),
            (
                "행동 점수만으로 생활 회복을 확정하지 않고 실제 활동을 "
                "선정에서 보완 근거로 연결한다."
            ),
        ],
        V08: [
            (
                "같은 72개 격자 중 67개 하락과 다사607452의 "
                "유일한 최대 상승·현재 최고를 대조한다."
            ),
            (
                "이 격자가 8~12월 내내 상위 6위임을 실제 월별 비교로 "
                "확인해 지속적인 차이로 읽는다."
            ),
            (
                "주거지라면 8~12월 제보·의뢰로 반복된 어려움과 최근 "
                "변화를 구분하도록 제안한다."
            ),
        ],
    },
    HYOJA: {
        V07: [
            (
                "12월 소폭 증가를 9월 이후 두 달 감소와 연결해 감소 "
                "중단과 이전 수준 회복을 구분한다."
            ),
            (
                "현재 평균이 9월보다 낮다는 실제 비교를 보존하며 대폭 "
                "회복이나 지속 감소로 바꾸지 않는다."
            ),
        ],
        V02: [
            ("요일 구성 거리의 원값 감소와 같은 지표의 양→음 기여도 전환을 연결한다."),
            "주말 변화율이 주중보다 낮은 폭의 축소를 원지표의 뜻과 단위대로 읽는다.",
            (
                "활동규모가 소폭 늘었지만 낮은 수준임을 함께 읽어 이용 "
                "확대보다 요일별 변동 완화로 판단하며 성별 기여도를 "
                "주원인으로 강조하지 않는다."
            ),
        ],
        V08: [
            ("현재 최고 라사203860과 유일한 최대 상승 라사202860을 구분한다."),
            (
                "라사202860의 9월 1위·11월 공동 12위·12월 "
                "3위를 비교해 처음 등장한 곳과 다시 두드러진 곳을 "
                "구분한다."
            ),
            (
                "현재 화면과 과거 보완 비교를 구분하며 주거지라면 9월과 "
                "11~12월 외출·왕래 현장 정보를 대조하도록 제안한다."
            ),
        ],
    },
}


def regional_plan(code):
    if code == DAECHI:
        targets = ((ACTIVITY,), (REGION, ACTIVITY, DEFINITIONS), (GRID,))
        context = (
            "대치4동의 12월 활동은 6개월 최저로 줄었지만 행동 "
            "점수는 내려갔다. 이전 반등이 이어지지 않은 이용 축소와 "
            "점수 완화를 구분한다. 현재 기여도가 큰 연령 구성 "
            "원지표의 변화는 작아 특정 연령의 감소를 만들지 않고 "
            "V01을 선택한다. 대부분 격자가 하락한 가운데 지속적으로 "
            "높고 반대로 오른 다사607452를 구분한다."
        )
        query = {
            ACTIVITY: (
                "대치4동의 7~12월 활동과 원지표를 조회해 11월 반등 "
                "이후 이용 규모와 이전 변동 범위를 확인한다."
            ),
            REGION: (
                "월별 행동 점수와 실제 활동의 방향이 같은지 비교할 자료를 조회한다."
            ),
            CONTRIBUTION: (
                "현재 기여도가 큰 지표와 전월 값을 원지표에 대조해 이번 "
                "보고서에서 설명할 가치가 있는 축을 고른다."
            ),
            GRID: (
                "8~12월 같은 격자를 조회해 동 전체 완화 속에서도 "
                "지속적으로 높거나 반대로 오른 구역을 구분한다."
            ),
        }
        process = {
            ACTIVITY: (
                "실제 활동의 전월 차이·변화율을 이전 범위와 대조해 11월 "
                "반등이 이어졌는지 판단한다."
            ),
            REGION: (
                "점수의 전월 차이를 계산해 실제 이용 축소와 점수 완화가 "
                "함께 나타나는지 확인한다."
            ),
            CONTRIBUTION: (
                "기여도 차이와 정의를 원지표에 대조하고 작은 연령 구성 "
                "변화로 특정 연령의 절대 감소를 만들지 않는다."
            ),
        }
    elif code == HYOJA:
        targets = ((ACTIVITY,), (ACTIVITY, CONTRIBUTION, REGION, DEFINITIONS), (GRID,))
        context = (
            "효자1동의 활동은 소폭 늘었지만 9월 수준에 미치지 "
            "못한다. 감소 중단과 이전 규모 회복을 구분하고 요일 구성 "
            "거리·주말주중 격차의 실제 원값과 기여도 변화를 연결해 "
            "낮은 이용 수준에서 요일별 변동이 잦아든 상황을 읽는다. "
            "현재 최고 라사203860과 최대 상승 라사202860을 "
            "구분하고 후자의 9월 1위 이력을 연결해 재부각으로 "
            "해석한다."
        )
        query = {
            ACTIVITY: (
                "효자1동의 활동과 요일 구성 원지표를 조회해 최근 소폭 "
                "증가가 이전 감소를 얼마나 되돌렸는지 확인한다."
            ),
            REGION: "월별 점수 완화가 실제 이용 확대와 함께 나타났는지 구분한다.",
            CONTRIBUTION: (
                "현재 양의 기여도 순위만 보지 않고 전월보다 완화된 요일 "
                "구성·주말주중 항목을 실제 원지표와 비교한다."
            ),
            GRID: (
                "현재 높은 곳과 최근 상승한 곳, 이전에도 높았던 곳을 "
                "구분할 같은 격자의 월별 자료를 조회한다."
            ),
        }
        process = {
            ACTIVITY: (
                "활동 평균의 전월 차이·변화율을 계산해 소폭 증가와 9월 "
                "이후 감소를 함께 읽는다."
            ),
            REGION: (
                "점수 전월 차이를 활동의 소폭 증가 및 요일 구성 변화 "
                "완화와 함께 읽을 근거로 계산한다."
            ),
            CONTRIBUTION: (
                "요일 구성 거리와 주말주중 격차의 기여도 차이·정의를 "
                "결합해 실제 원지표에 대조하고 작은 성별 기여도를 "
                "주원인으로 강조하지 않는다."
            ),
        }
    else:
        raise ValueError(code)
    return {
        "keys": KEYS[code],
        "targets": targets,
        "query_reasons": query,
        "process_reasons": process,
        "selection_reason": context
        + (
            " 각 뷰에 실제 근거와 보완 비교 범위를 연결하며 후보 "
            "격자의 주거지 조건과 확인할 기간을 정한다."
        ),
        "selection_review": context
        + (
            " 관측과 선정 목적이 맞으며 없는 성별 절대 감소나 현장 "
            "사실을 요구하지 않는다."
        ),
        "description_reviews": {
            key: " ".join(MEANINGS[code][key])
            + " 해당 초안이 승인 근거와 범위를 보존한다."
            for key in KEYS[code]
        },
        "description_reason": (
            "각 뷰의 지역별 상황판단을 승인된 근거 안에서 최대 세 "
            "문장으로 작성한다. 다른 지역의 가설을 가져오지 않고 "
            "필요한 현장 확인은 조건부로 제안한다."
        ),
        "insight_review": (
            "승인 설명의 시간 맥락·지표 관계·후보 격자 구분을 네 "
            "문장에 보존했다. 주거지 조건과 확인 기간을 유지하고 새 "
            "원인·현장 사실·개인 상태를 추가하지 않았다."
        ),
        "insight_reason": (
            "이 지역의 승인 설명에서 중요한 상황판단과 조건부 확인 "
            "대상을 네 문장으로 요약한다. 점수와 실제 이용, 현재 "
            "수준과 최근 변화의 차이를 보존한다."
        ),
    }


def regional_texts(facts):
    activity, monthly, score = (
        facts[key] for key in ("activity_current", "monthly_activity", "score_current")
    )
    changed, highest = facts["grid_changes"][0], facts["grid_rows"][0]
    changes = facts["grid_changes"]
    falling = sum(row["grid_score_change"] < 0 for row in changes)
    code = activity["adm_cd10"]
    if code == DAECHI:
        decline = abs(activity["activity_percent_change"])
        descriptions = {
            V07: (
                "12월 평균 활동규모는 "
                f"{activity['activity_hourly_mean']:,.2f}"
                "로 11월보다 "
                f"{decline:.2f}"
                "% 줄어 최근 6개월 중 가장 낮았습니다. 10월 "
                f"{monthly['2025-10-01']['activity_hourly_mean']:,.2f}"
                "에서 11월 "
                f"{activity['previous_activity_hourly_mean']:,.2f}"
                "로 회복했다가 그보다 더 낮아져, 최근의 이용 회복이 "
                "이어지지 않고 기존 등락 범위 아래로 지역 이용이 축소된 "
                "상황입니다."
            ),
            V01: (
                "행동 이상 점수는 11월 "
                f"{score['previous_score']:.2f}"
                "점에서 12월 "
                f"{score['bh_score']:.2f}"
                "점으로 "
                f"{abs(score['score_change']):.2f}"
                "점 낮아졌지만, 같은 기간 실제 활동규모도 "
                f"{decline:.2f}"
                "% 줄었습니다. 12월은 지역 이용이 회복된 달보다 "
                "이용규모가 축소된 가운데 기준 행동에서 벗어나는 정도도 "
                "줄어든 달로 해석할 수 있습니다."
            ),
            V08: (
                "동 안의 "
                f"{len(changes)}"
                "개 격자 중 "
                f"{falling}"
                "개의 점수는 내려갔지만, "
                f"{changed['grid_cd']}"
                "는 "
                f"{changed['grid_score_change']:.2f}"
                "점으로 가장 큰 상승폭을 보이며 "
                f"{changed['anomaly_score']:.2f}"
                "점으로 현재 점수도 가장 높았습니다. 같은 격자의 "
                "8~12월 자료를 추가로 대조하면 내내 상위 6위 "
                "이내였으므로, 동 전체의 점수 완화 속에서도 계속 "
                "두드러지는 구역으로 읽을 수 있습니다. 이 격자가 "
                "주거지인지 먼저 확인하고, 주거지라면 8~12월 "
                "제보·의뢰에 같은 어려움이 반복되는지, 최근 달라진 내용이 "
                "있는지 확인해보세요."
            ),
        }
        reasons = {
            V07: (
                "7~12월 활동 평균으로 12월 최저와 10월 감소·11월 "
                "반등 뒤 더 낮아진 흐름을 설명한다. 주민 관계 약화나 "
                "특정 성별 감소를 덧붙이지 않는다."
            ),
            V01: (
                "같은 동·월의 점수와 실제 활동을 함께 읽어 점수 완화와 "
                "이용 축소가 동반된 상황을 해석한다. V01에 활동 자료를 "
                "보완 연결하고 도시 중앙 범위는 비교하지 않는다."
            ),
            V08: (
                "현재 최고이자 최대 상승인 다사607452를 72개 중 "
                "67개 하락과 대조한다. 8~12월 같은 격자의 지속 "
                "상위권을 보완해, 주거지라면 해당 기간의 제보·의뢰에서 "
                "같은 어려움의 반복 여부와 최근 변화 유무를 확인하도록 제안한다. 과거 "
                "비교와 현재 화면을 구분한다."
            ),
        }
        insight = "\n".join(
            [
                (
                    "대치4동의 12월 활동규모는 "
                    f"{decline:.2f}"
                    "% 감소해 최근 6개월 최저로 내려갔으며, 11월의 반등이 "
                    "이어지지 않고 이전 등락 범위 아래로 이용이 축소됐습니다."
                ),
                (
                    "행동 이상 점수는 "
                    f"{abs(score['score_change']):.2f}"
                    "점 낮아졌지만, 실제 이용 회복보다 이용규모 축소와 기준 "
                    "행동과의 차이 완화가 함께 나타난 달입니다."
                ),
                (
                    f"{len(changes)}"
                    "개 중 "
                    f"{falling}"
                    "개 격자의 점수가 내려간 가운데 "
                    f"{changed['grid_cd']}"
                    "는 계속 높은 위치를 유지하며 이번 달 가장 크게 올라, "
                    "지속되는 차이를 확인할 후보입니다."
                ),
                (
                    f"{changed['grid_cd']}가 주거지라면 "
                    + "8~12월 제보·의뢰에 같은 어려움이 반복되는지, "
                    + "최근 달라진 내용이 있는지 확인해보세요."
                ),
            ]
        )
    elif code == HYOJA:
        previous, current = (monthly[month] for month in ("2025-11-01", "2025-12-01"))
        weekday = facts["contributions"]["h31_weekday_profile_distance"]
        prior_rank = facts["grid_ranks"]["2025-11-01"][changed["grid_cd"]]
        rank = facts["grid_ranks"]["2025-12-01"][changed["grid_cd"]]
        september_grid = next(
            row
            for row in facts["grid_history"]
            if row["grid_cd"] == changed["grid_cd"]
            and row["period_start"] == "2025-09-01"
        )
        descriptions = {
            V07: (
                "12월 평균 활동규모는 "
                f"{activity['activity_hourly_mean']:,.2f}"
                "으로 전월 "
                f"{activity['previous_activity_hourly_mean']:,.2f}"
                "보다 "
                f"{activity['activity_percent_change']:.2f}"
                "% 늘었습니다. 9월 "
                f"{monthly['2025-09-01']['activity_hourly_mean']:,.2f}"
                " 이후 두 달 이어진 감소는 멈췄지만 9월 수준에는 미치지 "
                "못해, 이용이 확장되기보다 축소된 수준에 머문 달로 읽을 "
                "수 있습니다."
            ),
            V02: (
                "요일별 활동 구성이 전월과 얼마나 달라졌는지를 나타내는 "
                "지표의 기여도는 "
                f"{weekday['previous_contribution']:.2f}"
                "점에서 "
                f"{weekday['contribution']:.2f}"
                "점으로 바뀌었습니다. 실제 지표값도 "
                f"{previous['h31_weekday_profile_distance']:.6f}"
                "에서 "
                f"{current['h31_weekday_profile_distance']:.6f}"
                "로 작아졌고, 주말 변화율이 주중보다 낮은 폭도 "
                f"{abs(previous['h26_weekend_weekday_change_gap']):.2f}"
                "%p에서 "
                f"{abs(current['h26_weekend_weekday_change_gap']):.2f}"
                "%p로 줄었습니다. 전체 활동은 소폭 증가에 그쳐, 12월은 "
                "이용규모의 뚜렷한 확대보다는 요일별 "
                "이용 패턴의 변동이 잦아든 달로 해석할 수 있습니다."
            ),
            V08: (
                "현재 점수가 가장 높은 곳은 "
                f"{highest['grid_cd']}"
                "("
                f"{highest['anomaly_score']:.2f}"
                "점)이지만, 전월 대비 상승폭은 "
                f"{changed['grid_cd']}"
                "("
                f"{changed['anomaly_score']:.2f}"
                "점)이 "
                f"{changed['grid_score_change']:.2f}"
                "점으로 가장 컸습니다. 같은 격자의 과거 자료를 대조하면 "
                f"{changed['grid_cd']}"
                "은 9월에도 "
                f"{september_grid['anomaly_score']:.2f}"
                "점으로 1위였고 이번 달 공동 "
                f"{prior_rank}"
                "위에서 "
                f"{rank}"
                "위로 올라, 처음 등장한 곳보다 이전에 높았던 구역이 다시 "
                "두드러진 흐름입니다. 이 격자가 주거지라면 9월과 "
                "11~12월의 외출·왕래에 관한 현장 정보를 비교해 같은 "
                "변화가 반복되는지 먼저 확인해보세요."
            ),
        }
        reasons = {
            V07: (
                "활동의 소폭 증가를 9월 이후 두 달 감소와 비교해 감소 "
                "중단과 이전 규모 회복을 구분한다. 특정 성별 절대 변화나 "
                "모임 참여 감소는 사실로 만들지 않는다."
            ),
            V02: (
                "요일 구성 거리와 주말·주중 격차의 기여도 및 원지표를 "
                "연결하고 활동의 소폭 증가도 보완해 규모 확대보다 요일별 "
                "변동 완화를 해석한다. 작은 양의 성별 기여도를 주원인으로 "
                "강조하거나 기여도를 가산 원인으로 해석하지 않는다."
            ),
            V08: (
                "현재 최고 라사203860과 최대 상승 라사202860을 "
                "구분한다. 후자의 9월 1위·11월 공동 12위·12월 "
                "3위를 보완해 새 출현보다 재부각으로 해석한다. 주거지라면 "
                "9월과 11~12월 외출·왕래 현장 정보를 비교하며 실제 "
                "반복 변화는 확인 대상으로 남긴다."
            ),
        }
        insight = "\n".join(
            [
                (
                    "효자1동의 12월 활동규모는 "
                    f"{activity['activity_percent_change']:.2f}"
                    "% 늘어 두 달간의 감소는 멈췄지만, 9월 수준에는 못 "
                    "미쳐 낮아진 이용규모에 머물렀습니다."
                ),
                (
                    "요일 구성의 전월 차이와 주말·주중 변화율 격차가 작아져, "
                    "이용 확대보다는 요일별 이용 패턴의 변동이 잦아든 상황으로 "
                    "읽을 수 있습니다."
                ),
                (
                    "현재 점수는 "
                    f"{highest['grid_cd']}"
                    "이 가장 높지만 상승폭은 "
                    f"{changed['grid_cd']}"
                    "이 가장 크며, 후자는 9월에도 1위였던 곳이 다시 "
                    "두드러졌습니다."
                ),
                (
                    f"{changed['grid_cd']}이 주거지라면 "
                    + "9월과 11~12월의 외출·왕래에 관한 현장 정보를 대조해 "
                    + "같은 변화가 반복되는지 확인해보세요."
                ),
            ]
        )
    else:
        raise ValueError(code)
    return descriptions, reasons, insight


def regional_view_requirements(code, view_key):
    return {
        "required_meanings": deepcopy(MEANINGS[code][view_key]),
        "allowed_variation": (
            "최대 세 문장에서 동등한 표현을 허용한다. 이 지역의 관측 "
            "관계를 보존하고 모든 뷰에 행동을 붙이지 않는다. 현장 "
            "확인은 이미 확인된 사실과 구분한다."
        ),
        "failure_examples": [
            "숫자·주의문만 나열해 해당 뷰의 상황 해석을 생략한다.",
            "도곡1동의 성별·새 상승 격자 해석을 다른 지역에 그대로 적용한다.",
            "동 집계를 특정 격자·주민의 절대 활동 감소나 고립 상태로 바꾼다.",
        ],
    }


def regional_requirements(code, role):
    if role == INSIGHT:
        required = (
            [
                "6개월 최저 활동과 11월 반등이 이어지지 않은 이용 축소를 요약한다.",
                "점수 완화를 실제 이용 회복과 구분한다.",
                (
                    "대부분 격자가 하락한 가운데 다사607452가 계속 높고 "
                    "가장 크게 오른 차이를 보존한다."
                ),
                "주거지 조건과 8~12월 제보·의뢰의 반복·최근 변화 비교를 보존한다.",
            ]
            if code == DAECHI
            else [
                "소폭 증가로 감소는 멈췄지만 9월 수준에는 못 미친다는 판단을 보존한다.",
                "이용 확대보다 요일별 이용 패턴의 변동이 잦아든 상황을 요약한다.",
                "현재 최고와 최근 최대 상승을 구분하고 라사202860의 재부각을 보존한다.",
                "주거지 조건과 9월·11~12월 외출·왕래 현장 정보 비교를 보존한다.",
            ]
        )
    else:
        required = [meaning for key in KEYS[code] for meaning in MEANINGS[code][key]]
    return {
        "required_meanings": required,
        "allowed_variation": (
            "선정은 지역별 관측과 보완 근거의 범위를 정하며 동등한 "
            "조합을 허용한다. 요약은 승인된 핵심 해석과 조건부 확인 "
            "대상을 3~4개 한 문장으로 보존하되 모든 숫자를 반복할 "
            "필요는 없다."
        ),
        "failure_examples": [
            "점수 하락을 실제 이용 회복으로 바꾼다.",
            "현재 높은 곳·최근 상승한 곳·과거에도 높았던 곳을 구분하지 않는다.",
            "승인 설명에 없는 원인·현장 사실·운영 조치를 요약에 추가한다.",
        ],
        "role_scope": role,
    }


def regional_numbers(facts, role, view_key):
    a = facts["activity_current"]
    code = a["adm_cd10"]
    if role == INSIGHT:
        values = [("activity_change", round(abs(a["activity_percent_change"]), 2))]
        if code == DAECHI:
            values.append(
                ("score_change", round(abs(facts["score_current"]["score_change"]), 2))
            )
        return values
    if role != DESCRIPTION:
        return []
    if view_key == V07:
        month = "2025-10-01" if code == DAECHI else "2025-09-01"
        return [
            ("activity_current", round(a["activity_hourly_mean"], 2)),
            ("activity_previous", round(a["previous_activity_hourly_mean"], 2)),
            ("activity_change", round(abs(a["activity_percent_change"]), 2)),
            (
                "activity_context",
                round(facts["monthly_activity"][month]["activity_hourly_mean"], 2),
            ),
        ]
    if view_key == V01:
        s = facts["score_current"]
        return [
            ("score_previous", s["previous_score"]),
            ("score_current", s["bh_score"]),
            ("score_change", round(abs(s["score_change"]), 2)),
            ("activity_change", round(abs(a["activity_percent_change"]), 2)),
        ]
    if view_key == V02:
        r = facts["contributions"]["h31_weekday_profile_distance"]
        p, c = (facts["monthly_activity"][m] for m in ("2025-11-01", "2025-12-01"))
        return [
            ("weekday_contribution_previous", round(r["previous_contribution"], 2)),
            ("weekday_contribution_current", round(r["contribution"], 2)),
            ("weekday_distance_previous", p["h31_weekday_profile_distance"]),
            ("weekday_distance_current", c["h31_weekday_profile_distance"]),
            (
                "weekend_gap_previous",
                round(abs(p["h26_weekend_weekday_change_gap"]), 2),
            ),
            ("weekend_gap_current", round(abs(c["h26_weekend_weekday_change_gap"]), 2)),
        ]
    changed = facts["grid_changes"][0]
    values = [
        ("grid_highest", facts["grid_rows"][0]["anomaly_score"]),
        ("grid_largest_change", changed["grid_score_change"]),
    ]
    if code == DAECHI:
        values += [
            ("grid_count", len(facts["grid_changes"])),
            (
                "grid_falling_count",
                sum(r["grid_score_change"] < 0 for r in facts["grid_changes"]),
            ),
        ]
    else:
        values += [
            ("grid_changed_current", changed["anomaly_score"]),
            (
                "grid_previous_rank",
                facts["grid_ranks"]["2025-11-01"][changed["grid_cd"]],
            ),
            (
                "grid_current_rank",
                facts["grid_ranks"]["2025-12-01"][changed["grid_cd"]],
            ),
            (
                "grid_september",
                next(
                    r["anomaly_score"]
                    for r in facts["grid_history"]
                    if r["grid_cd"] == changed["grid_cd"]
                    and r["period_start"] == "2025-09-01"
                ),
            ),
        ]
    return values
