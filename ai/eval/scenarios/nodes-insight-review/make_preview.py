"""실제 보고서 반환과 보관한 직전 문안을 비교해 검토 문서를 만든다."""

from __future__ import annotations

# ruff: noqa: E501 -- Markdown prose retains its layout.
import json
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "nodes"
ACTION_ARCHIVE = HERE / "before-action-revision/comparison.json"
INTERPRETATION_ARCHIVE = HERE / "before-interpretation-revision/comparison.json"
OUTREACH_ARCHIVE = HERE / "before-outreach-revision/comparison.json"
FINAL_ARCHIVE = HERE / "before-final-revision/comparison.json"
BEFORE_VERSION = "before_final_revision"
ROLES = [
    ("request", "사용자 요청", "basic-request-none.json"),
    (
        "report_selection",
        "보고서 시각화 선정",
        "basic-report-selection-1168065500.json",
    ),
    (
        "report_description",
        "보고서 시각화 설명",
        "basic-report-description-1168065500.json",
    ),
    ("report_insight", "보고서 퀵 인사이트", "basic-report-insight-1168065500.json"),
]
VIEW_TITLES = {
    "EmbedDetailV07": "월별 활동량 추이",
    "EmbedDetailV02": "주요 행동 지표 구성과 전월 변화",
    "EmbedDetailV01": "행동 이상 점수의 최근 흐름",
    "EmbedDetailV08": "격자별 행동 이상 점수 분포",
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def quote(text):
    return "\n".join("> " + line for line in text.splitlines())


def cell(text):
    """원문 내용은 보존하고 Markdown 표에 필요한 문자만 변환한다."""
    return str(text).replace("|", r"\|").replace("\n", "<br>")


def table(headers, rows):
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    output.extend(
        "| " + " | ".join(cell(value) for value in row) + " |" for row in rows
    )
    return "\n".join(output) + "\n\n"


def sentences(text):
    """소수점은 보존하고 문장 끝 구두점 뒤의 공백에서만 분리한다."""
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", text.strip())
        if part.strip()
    ]


def paragraphs(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def collect_comparisons():
    preserved_inputs = load(HERE / "before-action-revision/input-hashes.json")
    for relative, expected in preserved_inputs.items():
        actual = sha256((HERE / relative).read_bytes()).hexdigest()
        assert actual == expected, ("유지 대상인 입력 파일이 바뀌었습니다.", relative)
    index = load(HERE / "scenarios.json")
    paths = {
        scenario["agent_role"]: (entry["file"], scenario)
        for entry in index["scenarios"]
        for scenario in [load(HERE / entry["file"])]
    }
    archives = {
        "previous_draft": load(HERE / "previous-draft/comparison.json"),
        "before_activity_revision": load(
            HERE / "before-activity-revision/comparison.json"
        ),
        "before_action_revision": load(ACTION_ARCHIVE),
        "before_interpretation_revision": load(INTERPRETATION_ARCHIVE),
        "before_outreach_revision": load(OUTREACH_ARCHIVE),
        BEFORE_VERSION: load(FINAL_ARCHIVE),
    }
    archived = {
        name: {item["role"]: item["after"] for item in values}
        for name, values in archives.items()
    }
    comparisons = []
    for role, label, original_name in ROLES:
        filename, candidate = paths[role]
        original = load(SOURCE / "scenarios" / original_name)
        item = {
            "role": role,
            "label": label,
            "original": "../nodes/scenarios/" + original_name,
            "copy": filename,
            "before": {
                "request": original["start_state"]["request"],
                "node_count": len(original["steps"]),
                "response": original["terminal"]["state"]["response"]["content"],
            },
            **{name: deepcopy(roles[role]) for name, roles in archived.items()},
            "after": {
                "request": candidate["start_state"]["request"],
                "node_count": len(candidate["steps"]),
                "response": candidate["terminal"]["state"]["response"]["content"],
            },
        }
        assert all(item[name] == values[role] for name, values in archived.items())
        comparisons.append(item)
    user = comparisons[0]
    for field in ("request", "response"):
        assert user["after"][field] == user[BEFORE_VERSION][field], (
            "이번 작업의 유지 대상인 사용자 질문·답변이 바뀌었습니다.",
            field,
        )
    return comparisons


def report_parts(comparisons, version):
    roles = {item["role"]: item[version] for item in comparisons}
    selected = re.findall(
        r"(?m)^(EmbedDetailV\d+):", roles["report_selection"]["response"]
    )
    descriptions = paragraphs(roles["report_description"]["response"])
    assert len(selected) == len(descriptions) == 3
    assert len(set(selected)) == 3
    return dict(zip(selected, descriptions, strict=True))


def check_format(comparisons):
    descriptions = report_parts(comparisons, "after")
    insight = next(item for item in comparisons if item["role"] == "report_insight")
    lines = paragraphs(insight["after"]["response"])
    assert all(1 <= len(sentences(text)) <= 3 for text in descriptions.values())
    assert 3 <= len(lines) <= 4
    assert all(len(sentences(line)) == 1 for line in lines)


def compared_views(comparisons):
    """같은 뷰를 우선 맞추고, 교체된 뷰의 이전·현재 키를 함께 남긴다."""
    before = report_parts(comparisons, BEFORE_VERSION)
    after = report_parts(comparisons, "after")
    removed = [key for key in before if key not in after]
    added = [key for key in after if key not in before]
    replacements = dict(zip(added, removed, strict=True))
    return [
        (replacements.get(key, key), key, before[replacements.get(key, key)], text)
        for key, text in after.items()
    ]


def view_change_label(old_key, new_key):
    old_label = VIEW_TITLES.get(old_key, old_key)
    new_label = VIEW_TITLES.get(new_key, new_key)
    if old_key == new_key:
        return new_label
    return f"{old_label} · {old_key} → {new_label} · {new_key}"


def content_changes(comparisons):
    rows = [
        (view_change_label(old_key, new_key), before, after)
        for old_key, new_key, before, after in compared_views(comparisons)
    ]
    insight = next(item for item in comparisons if item["role"] == "report_insight")
    rows.append(
        (
            "퀵 인사이트",
            insight[BEFORE_VERSION]["response"],
            insight["after"]["response"],
        )
    )
    selection = next(item for item in comparisons if item["role"] == "report_selection")
    rows.append(
        (
            "시각화 선정 이유",
            selection[BEFORE_VERSION]["response"],
            selection["after"]["response"],
        )
    )
    return table(["내용", "수정 직전 전문", "수정 후 전문"], rows)


def format_changes(comparisons):
    before = report_parts(comparisons, BEFORE_VERSION)
    after = report_parts(comparisons, "after")
    insight = next(item for item in comparisons if item["role"] == "report_insight")
    rows = []
    for old_key, new_key, old_text, new_text in compared_views(comparisons):
        old, new = sentences(old_text), sentences(new_text)
        rows.append(
            (
                view_change_label(old_key, new_key) + " 설명",
                f"한 단락 {len(old)}문장 · 최장 문장 {max(map(len, old))}자",
                f"한 단락 {len(new)}문장 · 최장 문장 {max(map(len, new))}자",
                "뷰별 한 단락·최대 3문장",
            )
        )
    counts = []
    for version in (BEFORE_VERSION, "after"):
        lines = paragraphs(insight[version]["response"])
        counts.append(
            f"{len(lines)}개 항목 · 문장 수 "
            + "/".join(str(len(sentences(line))) for line in lines)
        )
    rows.append(("퀵 인사이트", *counts, "3~4개 항목·항목당 한 문장"))
    old_insights = paragraphs(insight[BEFORE_VERSION]["response"])
    new_insights = paragraphs(insight["after"]["response"])
    assert all(3 <= len(lines) <= 4 for lines in (old_insights, new_insights))
    rows.append(
        (
            "첫 인사이트에 최근 추세의 맥락을 배치",
            old_insights[0],
            new_insights[0],
            "첫 문장에서 현재 감소와 이전 회복 흐름을 어떻게 구분하는지 비교",
        )
    )
    old_gender = sentences(before["EmbedDetailV02"])
    new_gender = sentences(after["EmbedDetailV02"])
    old_activity = sentences(before["EmbedDetailV07"])
    new_activity = sentences(after["EmbedDetailV07"])
    rows.append(
        (
            "활동 설명을 두 문장의 추세 비교로 구성",
            " ".join(old_activity),
            " ".join(new_activity),
            "V07 전문 비교: 모든 설명을 업무 권고로 끝내지 않고, 현재 수준·전월 변화와 이전 하락·회복을 두 문장으로 설명",
        )
    )
    rows.append(
        (
            "성별 차이의 해석을 서로 다른 조건으로 분리",
            " ".join(old_gender[1:]),
            " ".join(new_gender[1:]),
            "V02 두 번째·세 번째 문장 비교: 접촉 편중 확인·안내 경로 권고에서 여성 감소와 여성 유지·남성 증가의 서로 다른 해석으로 변경",
        )
    )
    old_grid = sentences(before["EmbedDetailV08"])
    new_grid = sentences(after["EmbedDetailV08"])
    rows.extend(
        [
            (
                "지속적으로 높은 곳과 최근 변화가 큰 곳을 구분",
                " ".join(old_grid[:2]),
                " ".join(new_grid[:2]),
                "V08 첫 두 문장 비교: 현재 점수 범위·상위 두 곳에서 월별 상위권 지속과 전월 상승·순위 변화의 비교로 구성",
            ),
            (
                "현장 확인은 필요한 조건에서 제시",
                old_grid[-1],
                new_grid[-1],
                "V08 마지막 문장 비교: 실제 변화가 큰 구역의 주거지 여부를 조건으로 필요한 확인을 제시",
            ),
        ]
    )
    rows.append(
        (
            "전문과 비교의 원문",
            "보관본의 after.response",
            "실행 결과의 terminal.state.response.content",
            "직접 추출하며 요약문을 원문 인용으로 표시하지 않음",
        )
    )
    return table(["형식", "수정 직전", "수정 후", "적용 기준"], rows)


def requirements_trace(comparisons):
    """검토 과정의 지적과 사용자가 확정한 최종 요구사항을 대응한다."""
    before = report_parts(comparisons, BEFORE_VERSION)
    after = report_parts(comparisons, "after")
    before_outreach = report_parts(comparisons, "before_outreach_revision")
    before_action = report_parts(comparisons, "before_action_revision")
    old_activity = sentences(before["EmbedDetailV07"])
    old_gender = sentences(before["EmbedDetailV02"])
    old_grid = sentences(before["EmbedDetailV08"])
    activity = sentences(after["EmbedDetailV07"])
    gender = sentences(after["EmbedDetailV02"])
    grid = sentences(after["EmbedDetailV08"])
    rows = [
        (
            "수치 나열·현재 월 중심 설명",
            old_activity[0],
            "현재 수치를 최근 추세 안에 놓고, 이전 하락·회복과 비교해 의미를 설명한다.",
            " ".join(activity),
        ),
        (
            "가능성만 제시",
            old_gender[0],
            "추가 원값에 따라 달라지는 조건을 나누고 서로 다른 해석을 제시한다.",
            " ".join(gender[1:]),
        ),
        (
            "현재 상위 격자만 제시",
            " ".join(old_grid[:2]),
            "지속적으로 높았던 곳과 최근 새롭게 변화한 곳을 구분한다.",
            " ".join(grid[:2]),
        ),
        (
            "설명마다 업무 행동을 붙임",
            old_activity[-1],
            "해석 자체로 충분한 곳은 해석으로 마치고, 확인이 필요한 곳에만 권고를 넣는다.",
            " ".join(activity),
        ),
        (
            "기존 이용자의 참여 관리로 업무 범위를 좁힘",
            "발굴 관점 수정 전 V07: "
            + sentences(before_outreach["EmbedDetailV07"])[-1],
            "숨겨진 사회적 고립자를 찾기 위해 탐색할 지역과 변화의 단서를 제공한다.",
            grid[-1],
        ),
        (
            "대상·근거가 넓고 추상적임",
            old_grid[-1],
            "격자명·기간·상승폭·순위 변화 등 구체적인 근거와 확인 대상을 연결한다.",
            " ".join(grid[1:]),
        ),
        (
            "분석 설명과 사용자에게 건네는 문체가 어긋남",
            "행동 구체화 전 V02: " + sentences(before_action["EmbedDetailV02"])[0],
            "정중하고 자연스러운 문체로 쓰되 전문성·조건·해석 한계를 유지한다.",
            gender[-1],
        ),
    ]
    return table(
        [
            "이전 결과에서 드러난 문제",
            "이전 문장 예시",
            "도출한 최종 요구사항",
            "최종 문안의 반영",
        ],
        rows,
    )


def action_mapping(comparisons):
    """시간 비교·조건별 해석과 필요한 확인만 실제 원문에서 구분한다."""
    descriptions = report_parts(comparisons, "after")
    parts = {key: sentences(content) for key, content in descriptions.items()}
    activity, gender, grid = (
        parts[key] for key in ("EmbedDetailV07", "EmbedDetailV02", "EmbedDetailV08")
    )
    selection = next(item for item in comparisons if item["role"] == "report_selection")
    reasons = {
        key: text
        for line in paragraphs(selection["after"]["response"])
        for key, text in [line.split(": ", 1)]
    }
    gender_check = next(
        sentence
        for sentence in sentences(reasons["EmbedDetailV02"])
        if "성별 절대 활동값" in sentence
    )
    # 문장 순서가 달라진 뒤 다른 내용을 관측·해석으로 잘못 표시하지 않는다.
    required = [
        (activity[0], ("평균 활동규모", "최근 6개월", "두 번째")),
        (activity[1], ("8월", "9월", "회복", "등락")),
        (gender[0], ("활동 변화율", "남성 비중", "60세 이상")),
        (gender[1], ("여성의 실제 활동이 줄었다면", "가능성")),
        (gender[2], ("여성 활동은 유지", "남성 활동만 늘었다면")),
        (grid[0], ("현재 점수가 가장 높은", "격자")),
        (grid[1], ("8~12월", "상위 5위", "상승폭", "순위")),
        (grid[2], ("주거지 여부", "주거지에 해당한다면", "현장 정보")),
    ]
    for original, anchors in required:
        assert all(anchor in original for anchor in anchors), (
            "해석 비교의 원문 위치가 바뀌었습니다.",
            anchors,
        )
    rows = [
        (
            "현재 감소와 이전 등락 · V07",
            activity[0],
            activity[1],
            "별도 확인 권고 없음 — 시간 비교와 해석으로 설명을 마침.",
        ),
        (
            "여성 감소와 여성 유지·남성 증가 · V02",
            gender[0],
            "\n".join(gender[1:]),
            "선정 이유의 원문: " + gender_check,
        ),
        (
            "지속 상위권과 최근 변화 · V08",
            grid[0],
            grid[1],
            grid[2],
        ),
    ]
    for source, observation, interpretation, _ in rows:
        key = "EmbedDetail" + source.rsplit(" · ", 1)[1]
        assert observation in descriptions[key]
        assert interpretation.replace("\n", " ") in descriptions[key]
    assert gender_check in reasons["EmbedDetailV02"]
    assert grid[2] in descriptions["EmbedDetailV08"]
    return table(
        [
            "해석에서 구분할 점",
            "현재 관측 · 설명 원문",
            "시간 비교·조건별 해석 · 설명 원문",
            "필요한 확인",
        ],
        rows,
    )


def render_preview(comparisons):
    check_format(comparisons)
    roles = {item["role"]: item for item in comparisons}
    text = """# 추세와 조건별 해석을 담은 최종 지역 탐색 보고서

수정일: 2026-11-13. 사용자가 제시한 최종 문안에 맞춰 도곡1동 2025년 12월의 활동 추세, 성별 변화의 조건별 의미, 격자의 지속적인 상위권과 최근 변화를 구분했다. 필요한 곳에만 추가 확인을 제시하며 모든 설명에 업무 행동을 붙이지 않는다. 사용자 요청 사본의 질문과 답변, 확보한 입력 자료, V07·V02·V08 선정은 유지했다. 원본 데이터셋·운영 코드·해석 지침은 변경하지 않았다.

아래 전문은 이번 실행의 실제 반환값이다. 수정 직전 문장은 [이번 수정 직전 비교본](before-final-revision/comparison.json)의 `after.response`에서 직접 읽었다. 관측한 지역 신호, 시간 비교, 조건에 따라 달라지는 해석, 필요한 확인을 구분하며 개인의 고립 상태나 원인이 이미 확인됐다고 쓰지 않는다.

## 수정된 보고서 전문

### 퀵 인사이트

"""
    insight = roles["report_insight"]
    text += quote(insight["after"]["response"]) + "\n\n"
    text += f"[인사이트 전체 시나리오]({insight['copy']})\n\n"
    text += "### 차트별 설명\n\n"
    for key, content in report_parts(comparisons, "after").items():
        text += f"**{VIEW_TITLES.get(key, key)} · {key}**\n\n" + quote(content) + "\n\n"
    text += f"[설명 전체 시나리오]({roles['report_description']['copy']})\n\n"
    text += (
        "### 차트를 고른 이유\n\n"
        + quote(roles["report_selection"]["after"]["response"])
        + "\n\n"
    )
    text += f"[선정 전체 시나리오]({roles['report_selection']['copy']})\n\n"
    text += "## 이전 결과에서 도출한 최종 요구사항\n\n사용자의 지적과 최종 문안에서 정리한 요구사항을 실제 수정 문장과 대응했다. 별도 표시가 없는 이전 예시는 이번 수정 직전 문안이며, 기존 이용자 관리와 문체 예시는 해당 문제가 남아 있던 과거 보관본에서 직접 읽었다. 이 표는 본문에 새로운 업무 의무를 추가하는 기준이 아니다.\n\n"
    text += requirements_trace(comparisons)
    text += "## 내용 수정 전후\n\n직전과 이번 문안을 생략 없이 나란히 놓았다. 아래 모든 인용은 대응하는 실행·보관본과 일치한다.\n\n"
    text += content_changes(comparisons)
    text += "## 형식 수정 전후\n\n실제로 바뀐 문장을 인용해 정보의 배치와 문장 구성을 비교한다. 문장 수와 길이도 같은 원문에서 계산한다. 원자료·계산에 쓰는 입력 파일은 기존 보관 해시와 대조해 유지 여부를 확인하며, 문장의 간결함과 해석의 유용성은 별도로 검토한다.\n\n"
    text += format_changes(comparisons)
    text += "## 관측·시간 비교·조건별 해석·필요한 확인\n\n실제 보고서 문장에서 현재 관측과 비교 맥락, 조건별 해석, 필요한 확인을 나눠 읽는다. 별도 확인을 제시하지 않은 설명에는 행동을 덧붙이지 않는다.\n\n"
    text += action_mapping(comparisons)
    text += """## 근거와 남은 범위

[활동 조회 원본](snapshots/activity-evidence.json)에 읽기 전용 SQL·조건·수집시각·정확소수·정의를, [활동 자료원](snapshots/activity-dataset.json)에 실행에서 조회하는 값을 보존했다. V07는 24개 시간대 일평균 활동값의 평균이며 활동 합계와 구분한다. h18·h29 원지표와 같은 항목의 점수 기여도도 서로 구분한다.

보고서는 활동·성별 원지표와 정의, 기여도, 격자의 월별 자료를 근거로 비교한다. 기존 점수·기여도·격자는 [조회 스냅샷](snapshots/data.json), 정의는 [정의 자료원](snapshots/definitions.json)에 있으며, 선정 이유와 후속 설명의 근거 범위가 일치하도록 구성했다.

성별 각각·시간대별·요일별 상세 원자료는 이번에도 추가하지 않았다. 개별 주민의 관계·생활 상태나 현장 발굴 결과는 확인하지 않았으며, 업무 권고는 지역 신호를 바탕으로 탐색할 대상과 방법을 검토하는 제안이다. 비율에서 원활동량을 역산하거나 특정 개인의 고립 여부를 단정하지 않는다.

## 유지한 사용자 요청 사본

"""
    user = roles["request"]
    text += "첫 질문: **" + user["after"]["request"]["goal"] + "**\n\n"
    text += quote(user["after"]["response"]) + "\n\n"
    text += f"[사용자 요청 전체 시나리오]({user['copy']})\n\n"
    text += "## 비교·검증·재생성\n\n"
    text += table(
        ["역할", "수정 직전 노드 수", "이번 노드 수"],
        [
            (
                item["label"],
                item[BEFORE_VERSION]["node_count"],
                item["after"]["node_count"],
            )
            for item in comparisons
        ],
    )
    text += """- [비교 자료](comparison.json)는 원본 `before`, 첫 사본 `previous_draft`, 활동 자료 추가 전 `before_activity_revision`, 행동 구체화 전 `before_action_revision`, 생활상 해석 보강 전 `before_interpretation_revision`, 발굴 관점 수정 전 `before_outreach_revision`, 사용자 최종 문안 반영 직전 `before_final_revision`, 현재 `after`를 함께 보존한다.
- [전체 색인](scenarios.json), [응답 작성 사례](compose.json), [보고서 작성·검토 10개 호출](report-calls.json), [호출 입력 대응](report-call-coverage.json).
- [보고서 품질 기준](report-quality-criteria.json), [검증 결과](validation.json).

선정→설명→인사이트의 기존 역할과 전달 경로를 유지한다. 작성한 모델 응답을 현재 노드와 실제 조회·가공 도구로 실행한 사본이며, 외부 업무 모델·평가 모델의 자율 실행 결과는 아니다. 수치·형식·입력 전달 검사와 관측·가설·권고의 의미 검토를 구분한다.

`Eumi/ai`에서 실행한다. 재생성은 확보한 스냅샷을 사용하며 DB에 접속하지 않는다.

```powershell
.venv/Scripts/python.exe eval/scenarios/nodes-insight-review/build_review.py
.venv/Scripts/python.exe eval/scenarios/nodes-insight-review/make_preview.py
```

작성 기준: [분석 해석 지침](../../../src/instructions/analysis-interpretation.md), [보고서 지침](../../../src/instructions/analysis-report.md), [보고서 명세](../../../docs/agent/report.md), [현행 노드 평가](../../../eval/docs/nodes/README.md).
"""
    return text


def build_preview():
    comparisons = collect_comparisons()
    text = render_preview(comparisons)
    (HERE / "comparison.json").write_text(
        json.dumps(comparisons, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "README.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    build_preview()
