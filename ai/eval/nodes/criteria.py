"""정형 평가 정의를 읽고 호출 상황에 맞는 행과 관련 원칙을 선택한다."""

import hashlib
import json
import re
from bisect import bisect_right
from collections.abc import Collection
from itertools import combinations
from pathlib import Path
from typing import Annotated, Literal, NotRequired

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, with_config
from typing_extensions import TypedDict

from eval.nodes.format import strict_json

NodeName = Literal["interpret", "act", "decide", "compose", "ask"]
Method = Literal["규칙 기반", "LLM 기반"]
Axis = Literal["형식 준수", "필수 내용 충족", "내용 정확성"]
Role = Literal[
    "request",
    "interpretation",
    "visualization",
    "report_selection",
    "report_description",
    "report_insight",
]
RuntimeInput = Literal[
    "모델 호출 입력",
    "공통 원칙",
    "현재 Agent 역할",
    "이번 노드의 작업 지침",
    "현재 작업 목표",
    "작업 조건",
    "실제 대화 · 입력 메시지",
    "기존 공개 응답",
    "기존 공개 산출물",
    "입력 작업 이력",
    "입력 자료 내용",
    "입력 자료 정보",
    "실행 조건",
    "조회 가능한 자료 목록",
    "가공 가능한 결과 ID와 열",
    "시각화 목록과 입력 조건",
    "도구 기능 설명",
    "도구 입력 명세",
    "사용·공개 조건",
]
InputScope = Literal[
    "확정된 선정 결과",
    "배정된 설명 대상",
    "검토를 통과한 설명",
    "검토 대상 산출물",
    "근거 자료 내용",
]
ResultInput = Literal["모델 반환값", "작성 내용", "모델 호출 입력"]
AssessmentInput = Literal[
    "기준 자료",
    "기대 결과",
    "허용 범위",
    "동작 명세",
    "결함 주입 내역",
]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Texts = Annotated[list[Text], Field(min_length=1)]
STRICT = ConfigDict(extra="forbid", strict=True)
NODE_FILES = ("interpret", "act", "decide", "compose", "ask")
NODE_DIRECTORY = "eval/docs/nodes"
NODE_NAMES = {
    "작업 목적 파악": "interpret",
    "작업 선택 및 실행": "act",
    "작업 진행 판단": "decide",
    "응답 작성": "compose",
    "사용자 정보 요청": "ask",
}
INPUT_GROUPS = {
    "실행 당시 입력": "runtime",
    "검사 대상 결과": "result",
    "별도 평가 자료": "assessment",
}


@with_config(STRICT)
class PrincipleReference(TypedDict):
    path: Text
    key: Text
    clause_ids: NotRequired[list[Text]]


JudgeSection = Literal[
    "평가 대상과 적용 조건", "대조할 기준", "담당 범위", "공통 판정 규칙"
]


@with_config(STRICT)
class ClauseRange(TypedDict):
    id: Text
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=1)]
    section: NotRequired[JudgeSection]
    group: NotRequired[Annotated[int, Field(ge=0)]]


@with_config(STRICT)
class PrincipleSelection(TypedDict):
    text_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    clauses: list[ClauseRange]


JudgeFieldName = Literal["적용 조건", "측정 방법", "성공 기준"]


@with_config(STRICT)
class Principle(TypedDict):
    key: Text
    title: Text
    text: Text
    classification: Literal["judgment", "operation", "mixed"]
    selection: PrincipleSelection


@with_config(STRICT)
class When(TypedDict, total=False):
    nodes: Annotated[list[NodeName], Field(min_length=1)]
    roles: Annotated[list[Role], Field(min_length=1)]
    calls: Texts
    tools: Texts
    exclude_nodes: Annotated[list[NodeName], Field(min_length=1)]
    exclude_roles: Annotated[list[Role], Field(min_length=1)]
    exclude_calls: Texts
    exclude_tools: Texts


@with_config(STRICT)
class Inputs(TypedDict):
    runtime: list[RuntimeInput]
    result: list[ResultInput]
    assessment: list[AssessmentInput]


# 저장 형식은 원문 표의 열이다. 실행용 분류는 로딩할 때 파생한다.
EvaluationRow = with_config(STRICT)(
    TypedDict(
        "EvaluationRow",
        {
            "검사 ID": Annotated[str, Field(pattern=r"^N(?:\d{2})?-[A-Z]\.\d+$")],
            "평가 축": Axis,
            "검사 항목": Text,
            "검사 내용": Text,
            "적용 노드": NotRequired[Text],
            "적용 조건": Text,
            "평가 방식": Method,
            "평가 입력": Text,
            "측정 방법": Text,
            "성공 기준": Text,
        },
    )
)


@with_config(STRICT)
class Binding(TypedDict):
    row: Annotated[int, Field(ge=0)]
    row_id: Text
    when: When
    principles: list[PrincipleReference]
    judge_fields: NotRequired[dict[JudgeFieldName, PrincipleSelection]]
    input_scopes: NotRequired[
        dict[RuntimeInput, Annotated[list[InputScope], Field(min_length=1)]]
    ]


@with_config(STRICT)
class DefinitionFile(TypedDict):
    checks: Annotated[list[EvaluationRow], Field(min_length=1)]
    bindings: Annotated[list[Binding], Field(min_length=1)]
    principles: list[Principle]


definition_adapter = TypeAdapter(DefinitionFile)
inputs_adapter = TypeAdapter(Inputs)


class Source(TypedDict):
    path: str
    line: int
    pointer: NotRequired[str]


class Document(TypedDict):
    sha256: str
    text: str


class Section(TypedDict):
    key: str
    title: str
    level: int
    source: Source
    text: str
    direct_text: str
    classification: Literal["judgment", "operation", "mixed"]
    selection: PrincipleSelection


class JudgeClause(ClauseRange):
    text: str


class JudgePrinciple(TypedDict):
    key: str
    title: str
    text: str
    source: Source
    text_sha256: str
    clauses: list[JudgeClause]


class JudgeField(TypedDict):
    field: JudgeFieldName
    text_sha256: str
    clauses: list[JudgeClause]


class CheckDefinition(TypedDict):
    id: str
    axis: Axis
    method: Method
    node: NodeName | None
    nodes: list[NodeName]
    fields: dict[str, str]
    source: Source
    text: str
    header: str
    rows: NotRequired[list["CheckDefinition"]]
    row_id: NotRequired[str]
    when: NotRequired[When]
    applicability: NotRequired[str]
    inputs: NotRequired[Inputs]
    measurement: NotRequired[str]
    success: NotRequired[str]
    principles: NotRequired[list[PrincipleReference]]
    judge_fields: NotRequired[dict[JudgeFieldName, PrincipleSelection]]
    input_scopes: NotRequired[dict[RuntimeInput, list[InputScope]]]


class CriteriaCatalog(TypedDict):
    root: str
    checks: dict[str, CheckDefinition]
    documents: dict[str, Document]
    sections: dict[str, list[Section]]


class RowSelection(TypedDict):
    rows: list[CheckDefinition]
    missing_context: list[str]


class CriteriaError(ValueError):
    """정형 정의가 잘못됐거나 필요한 판정 기준을 연결할 수 없는 경우."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CriteriaError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _locations(text):
    """검증한 JSON의 포인터별 시작 행을 기록한다. 같은 key의 참조와 정의를 구분한다."""
    decoder = json.JSONDecoder()
    locations = {}
    newlines = [index for index, char in enumerate(text) if char == "\n"]

    def whitespace(index):
        while index < len(text) and text[index].isspace():
            index += 1
        return index

    def visit(index, pointer):
        index = whitespace(index)
        locations[pointer] = bisect_right(newlines, index) + 1
        if text[index] not in "[{":
            return decoder.raw_decode(text, index)[1]
        object_value = text[index] == "{"
        end_token = "}" if object_value else "]"
        index = whitespace(index + 1)
        count = 0
        while text[index] != end_token:
            if object_value:
                key, index = decoder.raw_decode(text, index)
                index = whitespace(index) + 1  # colon; JSON validity already checked
                token = key.replace("~", "~0").replace("/", "~1")
            else:
                token = str(count)
            index = whitespace(visit(index, pointer + "/" + token))
            count += 1
            if text[index] == ",":
                index = whitespace(index + 1)
        return index + 1

    visit(0, "")
    return locations


def _inputs(value: str) -> Inputs:
    """원문 셀의 분류와 명칭만 읽는다. 문구를 재작성하거나 입력을 더하지 않는다."""
    parsed = {"runtime": [], "result": [], "assessment": []}
    seen = set()
    for part in value.split("<br>"):
        match = re.fullmatch(
            r"- (실행 당시 입력|검사 대상 결과|별도 평가 자료): (.+)", part
        )
        if match is None or match[1] in seen:
            raise CriteriaError(f"invalid evaluation input cell: {value}")
        seen.add(match[1])
        labels = match[2].split(", ")
        if len(labels) != len(set(labels)):
            raise CriteriaError(f"duplicate input: {value}")
        parsed[INPUT_GROUPS[match[1]]] = labels
    return inputs_adapter.validate_python(parsed)


def _matching_values(rows, field):
    """조건의 교집합이 비었는지만 확인한다. 업무 판단 조건을 추가하지 않는다."""
    allowed = (
        set(NodeName.__args__)
        if field == "nodes"
        else set(Role.__args__)
        if field == "roles"
        else None
    )
    excluded = set()
    for row in rows:
        when = row.get("when", {})
        if field == "nodes":
            allowed &= set(row["nodes"])
        if field in when:
            included = set(when[field])
            allowed = included if allowed is None else allowed & included
        excluded.update(when.get("exclude_" + field, []))
    return allowed is None or bool(allowed - excluded)


def _validate_row_conditions(definition):
    rows = definition["rows"]
    fields = ("nodes", "roles", "calls", "tools")
    for row in rows:
        if not all(_matching_values([row], field) for field in fields):
            raise CriteriaError(f"{row['row_id']}: unreachable row selector")
    for first, second in combinations(rows, 2):
        if all(_matching_values([first, second], field) for field in fields):
            raise CriteriaError(
                f"{first['row_id']}, {second['row_id']}: overlapping row selectors"
            )


def _validate_selection(text, selection, identity, kind):
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != selection["text_sha256"]:
        raise CriteriaError(
            f"{identity}: {kind} text changed; review clause selection metadata"
        )
    seen, previous_end = set(), 0
    for clause in sorted(selection["clauses"], key=lambda value: value["start"]):
        start, end = clause["start"], clause["end"]
        if clause["id"] in seen:
            raise CriteriaError(f"{identity}: duplicate clause ID {clause['id']}")
        seen.add(clause["id"])
        if not 0 <= start < end <= len(text) or not text[start:end].strip():
            raise CriteriaError(f"{identity}: invalid clause range {clause['id']}")
        if start < previous_end:
            raise CriteriaError(f"{identity}: overlapping clause ranges")
        previous_end = end


def _validate_principle(principle, path):
    identity = f"{path}: {principle['key']}"
    selection = principle["selection"]
    _validate_selection(principle["text"], selection, identity, "principle")
    if principle["classification"] == "operation" and selection["clauses"]:
        raise CriteriaError(f"{identity}: operational principle cannot select clauses")


def _validate_judge_fields(fields, selections, identity):
    if selections is None or set(selections) != set(JudgeFieldName.__args__):
        raise CriteriaError(f"{identity}: missing judge field selection")
    for name, selection in selections.items():
        if not selection["clauses"]:
            raise CriteriaError(f"{identity}: empty judge field selection: {name}")
        _validate_selection(fields[name], selection, f"{identity}: {name}", "field")
        for clause in selection["clauses"]:
            _validate_judge_layout(clause, identity)
            if (name == "적용 조건") != (clause["section"] == "평가 대상과 적용 조건"):
                raise CriteriaError(f"{identity}: invalid applicability section")


def _validate_judge_layout(clause, identity):
    if clause.get("section") not in JudgeSection.__args__:
        raise CriteriaError(f"{identity}: missing or invalid judge section")
    group = clause.get("group")
    if type(group) is not int or group < 0:
        raise CriteriaError(f"{identity}: missing or invalid judge group")


def load_criteria(root: Path | None = None) -> CriteriaCatalog:
    """평탄한 원문 행과 별도의 연결 정보를 읽는다. Markdown은 실행에 쓰지 않는다."""
    base = (root if root is not None else Path(__file__).resolve().parents[2]).resolve()
    catalog: CriteriaCatalog = {
        "root": str(base),
        "checks": {},
        "documents": {},
        "sections": {},
    }
    row_ids = set()
    for name in ("common", *NODE_FILES):
        path = f"{NODE_DIRECTORY}/{name}.json"
        try:
            raw = (base / path).read_bytes()
            text = raw.decode("utf-8")
            parsed = json.loads(text, object_pairs_hook=_unique_object)
            data = definition_adapter.validate_python(parsed)
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            raise CriteriaError(f"{path}: {exc}") from exc
        catalog["documents"][path] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "text": text,
        }
        locations = _locations(text)
        sections: list[Section] = []
        keys = set()
        for index, principle in enumerate(data["principles"]):
            if principle["key"] in keys:
                raise CriteriaError(f"{path}: duplicate principle {principle['key']}")
            keys.add(principle["key"])
            _validate_principle(principle, path)
            sections.append(
                {
                    "key": principle["key"],
                    "title": principle["title"],
                    "level": 1,
                    "source": {
                        "path": path,
                        "line": locations[f"/principles/{index}/key"],
                        "pointer": f"/principles/{index}",
                    },
                    "text": principle["text"],
                    "direct_text": principle["text"],
                    "classification": principle["classification"],
                    "selection": principle["selection"],
                }
            )
        catalog["sections"][path] = sections
        bindings = {}
        for binding in data["bindings"]:
            index = binding["row"]
            if index in bindings or index >= len(data["checks"]):
                raise CriteriaError(f"{path}: duplicate or invalid row binding {index}")
            bindings[index] = binding
        if set(bindings) != set(range(len(data["checks"]))):
            raise CriteriaError(f"{path}: every row requires exactly one binding")
        grouped = {}
        for index, fields in enumerate(data["checks"]):
            binding = bindings[index]
            identifier = fields["검사 ID"]
            identity = binding["row_id"]
            if not identity.startswith(identifier + "/"):
                raise CriteriaError(f"{path}: row ID must belong to {identifier}")
            if identity in row_ids:
                raise CriteriaError(f"{path}: duplicate row ID {identity}")
            row_ids.add(identity)
            if fields["평가 방식"] == "LLM 기반":
                _validate_judge_fields(fields, binding.get("judge_fields"), identity)
            if (name == "common") != ("적용 노드" in fields):
                raise CriteriaError(
                    f"{path}: 적용 노드 is required only for common rows"
                )
            try:
                nodes = (
                    [NODE_NAMES[label] for label in fields["적용 노드"].split("<br>")]
                    if name == "common"
                    else [name]
                )
                inputs = _inputs(fields["평가 입력"])
            except (ValueError, KeyError) as exc:
                raise CriteriaError(f"{path}: {identity}: {exc}") from exc
            if len(nodes) != len(set(nodes)):
                raise CriteriaError(f"{path}: duplicate node in {identity}")
            if not set(binding["when"].get("nodes", [])) <= set(nodes):
                raise CriteriaError(f"{identity}: selector conflicts with 적용 노드")
            for key, choices in binding["when"].items():
                if len(choices) != len(set(choices)):
                    raise CriteriaError(f"{path}: duplicate selector in {identity}")
                if key.startswith("exclude_") and set(choices) & set(
                    binding["when"].get(key.removeprefix("exclude_"), [])
                ):
                    raise CriteriaError(f"{path}: conflicting selector in {identity}")
            for label, scopes in binding.get("input_scopes", {}).items():
                if label not in inputs["runtime"]:
                    raise CriteriaError(
                        f"{identity}: input scope must name a declared input"
                    )
                if len(scopes) != len(set(scopes)):
                    raise CriteriaError(f"{identity}: duplicate input scope")
            row: CheckDefinition = {
                "id": identifier,
                "axis": fields["평가 축"],
                "method": fields["평가 방식"],
                "node": None if name == "common" else name,
                "nodes": nodes,
                "header": "정형 평가 정의",
                "fields": dict(fields),
                "source": {
                    "path": path,
                    "line": locations[f"/checks/{index}/검사 ID"],
                    "pointer": f"/checks/{index}",
                },
                "text": json.dumps(fields, ensure_ascii=False, indent=2),
                "row_id": identity,
                "when": binding["when"],
                "applicability": fields["적용 조건"],
                "inputs": inputs,
                "measurement": fields["측정 방법"],
                "success": fields["성공 기준"],
                "principles": binding["principles"],
                "input_scopes": binding.get("input_scopes", {}),
            }
            if "judge_fields" in binding:
                row["judge_fields"] = binding["judge_fields"]
            group = grouped.setdefault(
                identifier, {"rows": [], "checks": [], "bindings": []}
            )
            if group["rows"]:
                first = group["rows"][0]
                for column in (
                    "검사 ID",
                    "평가 축",
                    "검사 항목",
                    "검사 내용",
                    "평가 방식",
                ):
                    if first["fields"].get(column) != fields.get(column):
                        raise CriteriaError(
                            f"{identity}: inconsistent shared column {column}"
                        )
            group["rows"].append(row)
            group["checks"].append(fields)
            group["bindings"].append(binding)
        for identifier, group in grouped.items():
            if identifier in catalog["checks"]:
                raise CriteriaError(
                    f"{path}: duplicate check ID across files {identifier}"
                )
            first = group["rows"][0]
            shared = {
                key: value
                for key, value in first["fields"].items()
                if all(row["fields"].get(key) == value for row in group["rows"])
            }
            catalog["checks"][identifier] = {
                **{
                    key: first[key]
                    for key in (
                        "id",
                        "axis",
                        "method",
                        "node",
                        "nodes",
                        "header",
                        "source",
                    )
                },
                "fields": shared,
                "nodes": list(
                    dict.fromkeys(
                        node for row in group["rows"] for node in row["nodes"]
                    )
                ),
                "rows": group["rows"],
                "text": json.dumps(
                    {"checks": group["checks"], "bindings": group["bindings"]},
                    ensure_ascii=False,
                    indent=2,
                ),
            }
    for definition in catalog["checks"].values():
        _validate_row_conditions(definition)
        for row in definition["rows"]:
            seen_references = set()
            for ref in row["principles"]:
                section = next(
                    (
                        section
                        for section in catalog["sections"].get(ref["path"], [])
                        if section["key"] == ref["key"]
                    ),
                    None,
                )
                if section is None:
                    raise CriteriaError(f"{row['row_id']}: missing principle {ref}")
                identity = (ref["path"], ref["key"])
                if identity in seen_references:
                    raise CriteriaError(
                        f"{row['row_id']}: duplicate principle reference"
                    )
                seen_references.add(identity)
                if row["method"] == "LLM 기반" and "clause_ids" not in ref:
                    raise CriteriaError(
                        f"{row['row_id']}: missing judge clause selection"
                    )
                if "clause_ids" in ref:
                    selected = ref["clause_ids"]
                    available = {c["id"] for c in section["selection"]["clauses"]}
                    if len(selected) != len(set(selected)):
                        raise CriteriaError(
                            f"{row['row_id']}: duplicate selected clause"
                        )
                    if set(selected) - available:
                        raise CriteriaError(f"{row['row_id']}: unknown selected clause")
                    if row["method"] == "LLM 기반":
                        for clause in section["selection"]["clauses"]:
                            if clause["id"] in selected:
                                _validate_judge_layout(clause, row["row_id"])
            # 담당 범위의 교차 참조를 검증한다. 다른 판정의 입력 의존성은 아니다.
            references = re.findall(
                r"N(?:\d{2})?-[A-Z]\.\d+", row["measurement"] + " " + row["success"]
            )
            for reference in references:
                if reference not in catalog["checks"]:
                    raise CriteriaError(
                        f"{row['row_id']}: unknown referenced check {reference}"
                    )
    return catalog


def select_rows(
    definition: CheckDefinition,
    node: dict,
    call: dict,
    *,
    row_ids: Collection[str] | None = None,
) -> RowSelection:
    """실행 맥락으로 행을 고른다. 증거 누락·조건 중복은 비적용으로 숨기지 않는다."""
    node_name = node.get("node")
    if node_name not in NodeName.__args__:
        return {"rows": [], "missing_context": ["평가 대상 노드를 확인할 수 없습니다."]}
    if node_name not in definition["nodes"]:
        return {"rows": [], "missing_context": []}
    output = call.get("output")
    if call.get("raw") is not None:
        try:
            output = strict_json(call["raw"])
        except (ValueError, TypeError):
            output = None
    tool = output.get("name") if isinstance(output, dict) else None
    if tool is None and (output is not None or call.get("raw") is not None):
        # 원본에 호출 이름이 없는 형식 오류와 원본을 수집하지 못한 경우를 구분한다.
        tool = "__invalid_action__"
    context = {
        "nodes": node.get("node"),
        "roles": node.get("role"),
        "calls": call.get("name"),
        "tools": tool,
    }
    selected, missing = [], []
    for row in definition.get("rows", [definition]):
        if node.get("node") not in row["nodes"]:
            continue
        unknown, mismatch = [], False
        for key, choices in row.get("when", {}).items():
            excluded = key.startswith("exclude_")
            field = key.removeprefix("exclude_")
            value = context[field]
            if value is None:
                unknown.append(field)
            elif (value in choices) == excluded:
                mismatch = True
        if mismatch:
            continue
        if unknown:
            missing.extend(f"{row['row_id']}: {field}" for field in unknown)
        else:
            selected.append(row)
    if len(selected) > 1:
        missing.append(
            "동일 호출에 여러 평가 행이 적용됨: "
            + ", ".join(row["row_id"] for row in selected)
        )
    # 호출 상황 자체가 모호하면 --row로 한 행만 남겨도 확정된 선택으로 바꾸지 않는다.
    if row_ids is not None:
        selected = [row for row in selected if row["row_id"] in row_ids]
    return {"rows": selected, "missing_context": sorted(set(missing))}


def criterion_sections(
    definition: CheckDefinition,
    catalog: CriteriaCatalog,
    node: str | None = None,
) -> list[Section]:
    """선택 행에 명시한 JSON 원칙만 프롬프트에 제공한다."""
    if "rows" in definition:
        if len(definition["rows"]) != 1:
            raise CriteriaError("Select one applicable row before assembling criteria")
        definition = definition["rows"][0]
    selected, seen = [], set()
    for ref in definition["principles"]:
        identity = (ref["path"], ref["key"])
        if identity not in seen:
            seen.add(identity)
            selected.append(
                next(
                    section
                    for section in catalog["sections"][ref["path"]]
                    if section["key"] == ref["key"]
                )
            )
    return selected


def judge_principles(
    definition: CheckDefinition, catalog: CriteriaCatalog
) -> list[JudgePrinciple]:
    """검토된 조항의 원문만 제공하며 전체 원칙·출처는 catalog에 보존한다."""
    if "rows" in definition:
        if len(definition["rows"]) != 1:
            raise CriteriaError("Select one applicable row before assembling criteria")
        definition = definition["rows"][0]
    result = []
    sections = criterion_sections(definition, catalog)
    for reference, section in zip(definition["principles"], sections, strict=True):
        if "clause_ids" not in reference:
            raise CriteriaError(
                f"{definition['row_id']}: missing judge clause selection"
            )
        selected = set(reference["clause_ids"])
        available = {c["id"] for c in section["selection"]["clauses"]}
        if len(selected) != len(reference["clause_ids"]):
            raise CriteriaError(f"{definition['row_id']}: duplicate selected clause")
        if selected - available:
            raise CriteriaError(f"{definition['row_id']}: unknown selected clause")
        if not selected:
            continue
        _validate_principle(section, section["source"]["path"])
        for clause in section["selection"]["clauses"]:
            if clause["id"] in selected:
                _validate_judge_layout(clause, definition["row_id"])
        clauses = [
            {**clause, "text": section["text"][clause["start"] : clause["end"]]}
            for clause in sorted(
                section["selection"]["clauses"], key=lambda value: value["start"]
            )
            if clause["id"] in selected
        ]
        result.append(
            {
                "key": section["key"],
                "title": section["title"],
                "text": "\n".join(clause["text"] for clause in clauses),
                "source": dict(section["source"]),
                "text_sha256": section["selection"]["text_sha256"],
                "clauses": clauses,
            }
        )
    return result


def judge_fields(definition: CheckDefinition) -> list[JudgeField]:
    """행 선택과 별개인 적용 조건을 포함해, 명시한 원문 범위만 읽는다."""
    if "rows" in definition:
        if len(definition["rows"]) != 1:
            raise CriteriaError("Select one applicable row before assembling criteria")
        definition = definition["rows"][0]
    selections = definition.get("judge_fields")
    _validate_judge_fields(definition["fields"], selections, definition["row_id"])
    return [
        {
            "field": name,
            "text_sha256": selections[name]["text_sha256"],
            "clauses": [
                {
                    **clause,
                    "text": definition["fields"][name][clause["start"] : clause["end"]],
                }
                for clause in sorted(
                    selections[name]["clauses"], key=lambda value: value["start"]
                )
            ],
        }
        for name in JudgeFieldName.__args__
    ]
