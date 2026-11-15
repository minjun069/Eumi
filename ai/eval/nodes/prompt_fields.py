"""호출 입력 전체와 검사 행별 대상 출력 필드를 평가 자료로 연결한다."""

from copy import deepcopy
from typing import Literal, NotRequired

from pydantic import JsonValue
from typing_extensions import TypedDict

from eval.nodes.format import strict_json
from eval.nodes.inputs import valid_message


class PromptField(TypedDict):
    section: Literal["output", "input"]
    label: str
    path: str
    status: Literal["present", "missing", "invalid"]
    value: NotRequired[JsonValue]
    reason: NotRequired[str]
    missing_path: NotRequired[str]
    json_path: NotRequired[str]


class FieldProjection(TypedDict):
    fields: list[PromptField]
    excluded_paths: list[str]


class FieldSpec(TypedDict):
    path: str
    label: str
    kind: Literal["text", "boolean", "texts", "object"]
    optional: NotRequired[bool]


class FieldProfile(TypedDict):
    outputs: dict[str, tuple[str, ...]]


FIELDS: dict[str, FieldSpec] = {
    "goal": {"path": "/request/goal", "label": "파악한 작업 목표", "kind": "text"},
    "required": {
        "path": "/request/constraints/required",
        "label": "파악한 필수 조건",
        "kind": "texts",
        "optional": True,
    },
    "preferred": {
        "path": "/request/constraints/preferred",
        "label": "파악한 선호 조건",
        "kind": "texts",
        "optional": True,
    },
    "excluded": {
        "path": "/request/constraints/excluded",
        "label": "파악한 제외 조건",
        "kind": "texts",
        "optional": True,
    },
    "reason": {"path": "/reason", "label": "작성한 판단 이유", "kind": "text"},
    "name": {"path": "/name", "label": "선택한 작업", "kind": "text"},
    "arguments": {
        "path": "/arguments_json/@json",
        "label": "선택한 작업의 입력 인자",
        "kind": "object",
    },
    "view": {
        "path": "/arguments_json/@json/view_key",
        "label": "선택한 시각화",
        "kind": "text",
    },
    "next": {"path": "/next", "label": "선택한 다음 단계", "kind": "text"},
    "content": {"path": "/content", "label": "작성한 본문", "kind": "text"},
    "artifacts": {
        "path": "/artifact_ids",
        "label": "공개 대상으로 선택한 결과",
        "kind": "texts",
    },
    "status": {"path": "/status", "label": "판단한 완료 상태", "kind": "text"},
    "views": {"path": "/views/*/view_key", "label": "선정한 뷰", "kind": "text"},
    "view_reasons": {
        "path": "/views/*/reason",
        "label": "뷰 선정 이유와 설명 범위",
        "kind": "text",
    },
    "evidence_ids": {
        "path": "/views/*/evidence_ids",
        "label": "선정한 뷰의 근거",
        "kind": "texts",
    },
    "accepted": {"path": "/accepted", "label": "검토한 적합 여부", "kind": "boolean"},
}
REQUEST = ("goal", "required", "preferred", "excluded")
VIEWS = ("views", "view_reasons", "evidence_ids")
ALL_OUTPUTS = {
    "Interpretation": (*REQUEST, "reason"),
    "Selection": ("name", "arguments", "reason"),
    "Decision": ("next", "reason"),
    "Composition": ("content", "artifacts", "status", "reason"),
    "Question": ("content", "reason"),
    "ReportSelection": VIEWS,
    "ReportText": ("content",),
    "Verification": ("accepted", "reason"),
}
AUTHORED = {
    "Selection": ("reason",),
    "Composition": ("content", "reason"),
    "ReportSelection": ("view_reasons",),
    "ReportText": ("content",),
    "Verification": ("reason",),
}
PUBLIC = {
    "Selection": (),
    "Decision": (),
    "Composition": ("content",),
    "Question": ("content",),
    "ReportSelection": ("view_reasons",),
    "ReportText": ("content",),
    "Verification": (),
}


def _profile(outputs) -> FieldProfile:
    return {"outputs": outputs}


# 명시한 행만 지원한다. 새 검사 행에 넓은 기본 프로필을 자동 적용하지 않는다.
PROFILES: dict[str, FieldProfile] = {
    "N-O.5/general": _profile(AUTHORED),
    "N-O.2/general": _profile(AUTHORED),
    "N-O.3/general": _profile(AUTHORED),
    "N-O.4/general": _profile(AUTHORED),
    "N-O.9/general": _profile(AUTHORED),
    "N-O.10/general": _profile(AUTHORED),
    "N-B.2/general": _profile(ALL_OUTPUTS),
    "N-B.3/general": _profile(PUBLIC),
    "N01-O.2/general": _profile({"Interpretation": (*REQUEST, "reason")}),
    "N01-O.1/general": _profile({"Interpretation": (*REQUEST, "reason")}),
    "N02-O.2/general": _profile({"Selection": ("name", "reason")}),
    "N02-O.1/general": _profile({"Selection": ("name", "reason")}),
    "N02-O.4/general": _profile({"Selection": ("name", "view")}),
    "N03-O.4/general": _profile({"Decision": ("next", "reason")}),
    "N03-O.2/general": _profile({"Decision": ("next", "reason")}),
    "N03-O.2/view-context": _profile({"Decision": ("next", "reason")}),
    "N03-O.3/general": _profile({"Decision": ("next",)}),
    "N04-O.1/interpretation": _profile(
        {"Composition": ("content", "artifacts", "status", "reason")}
    ),
    "N04-O.1/visualization": _profile(
        {"Composition": ("content", "artifacts", "status", "reason")}
    ),
    "N04-O.1/request": _profile(
        {"Composition": ("content", "artifacts", "status", "reason")}
    ),
    "N04-O.1/report-selection": _profile({"ReportSelection": VIEWS}),
    "N04-O.1/report-description": _profile({"ReportText": ("content",)}),
    "N04-O.1/report-insight": _profile({"ReportText": ("content",)}),
    "N04-O.4/general": _profile(
        {"Composition": ("content", "status", "reason", "artifacts")}
    ),
    "N04-O.4/report-selection": _profile({"ReportSelection": VIEWS}),
    "N04-O.4/report-description": _profile({"ReportText": ("content",)}),
    "N04-O.4/report-insight": _profile({"ReportText": ("content",)}),
    "N04-B.1/general": _profile({"Composition": ("content", "artifacts")}),
    "N04-B.1/report-selection": _profile({"ReportSelection": VIEWS}),
    "N04-B.1/report-description": _profile({"ReportText": ("content",)}),
    "N04-B.1/report-insight": _profile({"ReportText": ("content",)}),
    "N04-O.3/report-selection": _profile({"Verification": ("accepted", "reason")}),
    "N04-O.3/report-description": _profile({"Verification": ("accepted", "reason")}),
    "N04-O.3/report-insight": _profile({"Verification": ("accepted", "reason")}),
    "N05-O.3/general": _profile({"Question": ("content",)}),
    "N05-O.2/general": _profile({"Question": ("content",)}),
    "N05-O.1/general": _profile({"Question": ("content", "reason")}),
}

# 원문 단위는 구조로 정한다. 질문·주장 키워드로 관련 문장/필수 항목을 추정하지
# 않으며, 후보 도구·뷰·자료 목록과 대화는 실제 제공된 단위를 모두 보존한다.
ROLE_TEXT = {
    "request": "사용자 요청을 처리하고 필요한 전문 작업의 결과를 통합하는 역할",
    "interpretation": "지역·집단 자료를 분석하고 근거에 맞게 해석하는 역할",
    "visualization": "등록된 시각화와 조건을 선택하고 유효한 산출물을 제공하는 역할",
    "report_selection": "보고서에서 설명할 시각화와 근거·설명 범위를 선정하는 역할",
    "report_description": (
        "확정된 선정 결과의 배정 범위에 맞춰 뷰별 설명을 작성하는 역할"
    ),
    "report_insight": "검토를 통과한 설명의 범위 안에서 핵심 내용을 요약하는 역할",
}
CALL_TEXT = {
    "Interpretation": "요청의 목표와 조건을 파악한 결과",
    "Selection": "진행 판단에서 정한 정보를 확보하기 위해 작업을 선택한 결과",
    "Decision": "확보한 정보와 부족한 정보를 비교해 다음 단계를 판단한 결과",
    "Composition": "현재 역할을 마치며 사용자에게 제공할 응답을 작성한 결과",
    "Question": "사용자만 제공할 수 있는 미확보 정보를 묻는 질문을 작성한 결과",
    "ReportSelection": "보고서에 사용할 뷰·근거·설명 범위를 선정한 결과",
    "ReportText": "보고서의 설명 또는 핵심 요약을 작성한 결과",
    "Verification": "이미 준비된 보고서 산출물의 적합 여부와 수정 사유를 검토한 결과",
}


def _get_profile(definition):
    identity = definition.get("row_id")
    if identity not in PROFILES:
        raise ValueError(f"평가 행의 필드 선택 프로필이 없습니다: {identity}")
    return PROFILES[identity]


def _call_name(definition, evidence, profile):
    call = evidence.get("call")
    name = call.get("name") if isinstance(call, dict) else None
    if name:
        if name not in profile["outputs"]:
            raise ValueError(f"평가 행에 정의하지 않은 모델 호출입니다: {name}")
        return name
    choices = definition.get("when", {}).get("calls", [])
    if len(choices) == 1 and choices[0] in profile["outputs"]:
        return choices[0]
    if len(profile["outputs"]) == 1:
        return next(iter(profile["outputs"]))
    return None


def situation_text(definition, evidence) -> str:
    profile = _get_profile(definition)
    name = _call_name(definition, evidence, profile)
    role = evidence.get("role")
    roles = definition.get("when", {}).get("roles", [])
    if role is None and len(roles) == 1:
        role = roles[0]
    role_text = ROLE_TEXT.get(role, "실행 증거에서 담당 역할을 확인할 수 없는 상황")
    call_text = CALL_TEXT.get(name, "실행 증거에서 호출 목적을 확인할 수 없는 결과")
    if name == "ReportSelection":
        return f"{call_text}를 평가한다."
    if name == "ReportText" and role == "report_description":
        return "확정된 선정 결과의 배정 범위에 맞춰 작성한 뷰별 설명을 평가한다."
    if name == "ReportText" and role == "report_insight":
        return "검토를 통과한 설명을 요약한 퀵 인사이트를 평가한다."
    if name == "Verification" and role in {
        "report_selection",
        "report_description",
        "report_insight",
    }:
        target = {
            "report_selection": "뷰·근거·설명 범위 선정",
            "report_description": "뷰별 설명",
            "report_insight": "퀵 인사이트",
        }[role]
        return f"보고서 {target}의 적합 여부와 수정 사유를 검토한 결과를 평가한다."
    return f"{role_text}에서 {call_text}를 평가한다."


def _pointer(path, token):
    return path + "/" + str(token).replace("~", "~0").replace("/", "~1")


def _kind(value, kind):
    if kind == "text":
        return isinstance(value, str)
    if kind == "boolean":
        return type(value) is bool
    if kind == "object":
        return isinstance(value, dict)
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _field(
    fields,
    section,
    label,
    path,
    value,
    *,
    status="present",
    reason=None,
    json_path=None,
):
    item: PromptField = {
        "section": section,
        "label": label,
        "path": path,
        "status": status,
        "value": deepcopy(value),
    }
    if reason:
        item["reason"] = reason
    if json_path is not None:
        item["json_path"] = json_path
    fields.append(item)


def _missing(fields, section, label, parent, desired, *, json_path=None, reason=None):
    item: PromptField = {
        "section": section,
        "label": label,
        "path": parent,
        "status": "missing",
        "missing_path": desired,
        "reason": reason or "선택한 항목이 원본에 없습니다.",
    }
    if json_path is not None:
        item["json_path"] = json_path
    fields.append(item)


def _select_output(value, tokens, spec, fields, path, *, json_path=None, label=None):
    label = label or spec["label"]
    if not tokens:
        valid = _kind(value, spec["kind"])
        _field(
            fields,
            "output",
            label,
            path,
            value,
            status="present" if valid else "invalid",
            json_path=json_path,
            reason=None if valid else "선택한 필드의 자료형이 응답 명세와 다릅니다.",
        )
        return
    token, *rest = tokens
    if token == "@json":
        try:
            decoded = strict_json(value)
        except (TypeError, ValueError):
            _field(
                fields,
                "output",
                label,
                path,
                value,
                status="invalid",
                reason="입력 인자 문자열을 JSON으로 해석할 수 없습니다.",
            )
            return
        _select_output(decoded, rest, spec, fields, path, json_path="", label=label)
        return
    if token == "*":
        if not isinstance(value, list):
            _field(
                fields,
                "output",
                label,
                path,
                value,
                status="invalid",
                reason="항목 배열이 필요한 위치의 자료형이 다릅니다.",
                json_path=json_path,
            )
        elif not value:
            _field(fields, "output", label, path, [], json_path=json_path)
        else:
            for index, child in enumerate(value):
                _select_output(
                    child,
                    rest,
                    spec,
                    fields,
                    _pointer(path, index) if json_path is None else path,
                    json_path=None if json_path is None else _pointer(json_path, index),
                    label=f"{label} {index + 1}",
                )
        return
    next_path = _pointer(path, token) if json_path is None else path
    next_json = None if json_path is None else _pointer(json_path, token)
    if isinstance(value, dict) and token in value:
        _select_output(
            value[token],
            rest,
            spec,
            fields,
            next_path,
            json_path=next_json,
            label=label,
        )
    elif isinstance(value, dict):
        _missing(
            fields,
            "output",
            label,
            path,
            next_path,
            json_path=next_json,
            reason=(
                "응답 명세상 생략할 수 있는 선택 항목입니다. "
                "이 필드가 없다는 사실만으로 내용 누락을 판단하지 않습니다. "
                "제공된 출력에서 현재 검사의 대상 의미를 확인합니다."
            )
            if spec.get("optional") and token != "request"
            else None,
        )
    else:
        _field(
            fields,
            "output",
            label,
            path,
            value,
            status="invalid",
            reason="필드를 읽어야 하는 위치가 객체가 아닙니다.",
            json_path=json_path,
        )


def _excluded_output(value, selectors, path, excluded):
    """선택한 필드의 형제 항목도 원문/문자열 내부 위치로 보관한다."""
    if any(not selector for selector in selectors):
        return
    if isinstance(value, str) and any(selector[0] == "@json" for selector in selectors):
        try:
            decoded = strict_json(value)
        except (ValueError, TypeError):
            return
        _excluded_output(
            decoded,
            [s[1:] for s in selectors if s[0] == "@json"],
            path + "#json",
            excluded,
        )
    elif isinstance(value, dict):
        for key, child in value.items():
            remaining = [s[1:] for s in selectors if s[0] == key]
            location = _pointer(path, key)
            if remaining:
                _excluded_output(child, remaining, location, excluded)
            else:
                excluded.append(location)
    elif isinstance(value, list):
        remaining = [s[1:] for s in selectors if s[0] == "*"]
        for index, child in enumerate(value):
            _excluded_output(child, remaining, _pointer(path, index), excluded)


def project_fields(definition, evidence) -> FieldProjection:
    profile = _get_profile(definition)
    name = _call_name(definition, evidence, profile)
    fields: list[PromptField] = []
    excluded = []
    call = evidence.get("call")
    parent = "/evidence/call" if isinstance(call, dict) else "/evidence"
    if not isinstance(call, dict) or "output" not in call:
        _missing(fields, "output", "평가 대상 출력", parent, "/evidence/call/output")
    elif name is None:
        _missing(
            fields,
            "output",
            "평가 대상 출력의 호출 종류",
            parent,
            "/evidence/call/name",
            reason="호출 종류를 확인할 증거가 없습니다.",
        )
    else:
        output = call["output"]
        specs = profile["outputs"][name]
        for identity in specs:
            spec = FIELDS[identity]
            _select_output(
                output,
                spec["path"].strip("/").split("/"),
                spec,
                fields,
                "/evidence/call/output",
            )
        if not specs:
            _missing(
                fields,
                "output",
                "공개용 작성 내용",
                "/evidence/call/output",
                "/evidence/call/output/content",
                reason="이 호출의 반환 명세에는 공개용 본문 필드가 없습니다.",
            )
        _excluded_output(
            output,
            [FIELDS[i]["path"].strip("/").split("/") for i in specs],
            "/evidence/call/output",
            excluded,
        )
    entries = evidence.get("inputs", [])
    if not isinstance(entries, list):
        _field(
            fields,
            "input",
            "실행 입력 목록",
            "/evidence/inputs",
            entries,
            status="invalid",
            reason="실행 입력 목록이 배열이 아닙니다.",
        )
        entries = []
    if not any(
        isinstance(entry, dict) and entry.get("source") == "messages"
        for entry in entries
    ) and not evidence.get("missing_inputs"):
        _missing(
            fields,
            "input",
            "실행 당시 메시지",
            "/evidence",
            "/evidence/inputs",
            reason="실제 모델 입력 메시지를 확보하지 못했습니다.",
        )
    for index, entry in enumerate(entries):
        base = f"/evidence/inputs/{index}"
        if not isinstance(entry, dict) or "value" not in entry:
            _missing(fields, "input", f"실행 입력 {index + 1}", base, base + "/value")
            continue
        source, value = entry.get("source"), entry["value"]
        valid = (
            valid_message(value)
            if source == "messages"
            else (isinstance(value, dict) if source == "response_schema" else False)
        )
        _field(
            fields,
            "input",
            entry.get("label", f"실행 입력 {index + 1}"),
            base + "/value",
            value,
            status="present" if valid else "invalid",
            reason=None
            if valid
            else "저장된 모델 호출 입력의 출처나 형식이 올바르지 않습니다.",
        )
    for index, missing in enumerate(evidence.get("missing_inputs", [])):
        _field(
            fields,
            "input",
            "확보하지 못한 평가 입력",
            f"/evidence/missing_inputs/{index}",
            missing,
            status="missing",
            reason="필요한 원문 입력을 확보하지 못했습니다.",
        )
    # 같은 빈 배열/누락 부모가 여러 필드 선택에서 반복돼도 판정 자료는 한 번만 보낸다.
    unique = []
    for item in fields:
        if item not in unique:
            unique.append(item)
    return {"fields": unique, "excluded_paths": sorted(set(excluded))}
