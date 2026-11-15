"""JSON 단일 원본, 상황별 선택, 잘못된 정의의 조기 거부를 검증한다."""

import hashlib
import json
import re
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from eval.nodes.criteria import (
    CriteriaError,
    criterion_sections,
    load_criteria,
    select_rows,
)
from eval.scripts import check_node_criteria_migration as migration
from eval.scripts.check_node_criteria_migration import (
    audit,
    original_rows,
    source_revisions,
)


@pytest.fixture
def criteria_root(tmp_path):
    source = Path(__file__).resolve().parents[2] / "eval" / "docs"
    destination = tmp_path / "eval" / "docs"
    destination.mkdir(parents=True)
    shutil.copytree(source / "nodes", destination / "nodes")
    shutil.copytree(source / "originals", destination / "originals")
    shutil.copyfile(source / "methods.md", destination / "methods.md")
    for basis in source_revisions()["basis"].values():
        target = tmp_path / basis["path"]
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source.parents[1] / basis["path"], target)
    return tmp_path


def edit(root, name, change):
    path = root / f"eval/docs/nodes/{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_every_original_column_and_sentence_is_preserved():
    originals = original_rows()
    assert len(originals) == 30
    assert sum(len(value["fields"]) for value in originals.values()) == 282
    errors, _ = audit()
    assert errors == []


def test_refinement_still_checks_its_original_source(tmp_path, monkeypatch):
    origins = json.loads(migration.ORIGINS.read_text(encoding="utf-8"))
    change = origins["source_refinements"]["checks"]["N01-O.1/general"]["측정 방법"][0]
    change["before"] = "보관 원문에 없는 대조 방법"
    path = tmp_path / "origins.json"
    path.write_text(json.dumps(origins, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(migration, "ORIGINS", path)
    errors, _ = audit()
    assert "N01-O.1/general: 측정 방법 contains rewritten text" in errors


def test_migration_records_keep_current_refined_fields():
    errors, records = audit()
    assert not errors
    record = next(row for row in records if row["row_id"] == "N01-O.1/general")
    assert record["fields"]["측정 방법"].startswith(
        "출력의 대상·목표·조건·파악 이유를 실행 당시 "
        "요청·대화·현재 역할·업무 지침과 대조한다."
    )


@pytest.mark.parametrize("column", ["검사 내용", "측정 방법", "성공 기준"])
def test_migration_audit_rejects_rewriting_even_when_the_schema_is_valid(
    criteria_root, column
):
    edit(criteria_root, "ask", lambda d: d["checks"][0].update({column: "축약한 기준"}))
    errors, _ = audit(criteria_root)
    assert any(column in error for error in errors)


def test_migration_audit_rejects_lost_original_sentence(criteria_root):
    def omit(data):
        for row in data["checks"]:
            if row["검사 ID"] == "N04-O.4":
                row["측정 방법"] = "<br>".join(
                    value
                    for value in row["측정 방법"].split("<br>")
                    if not value.startswith("해결·미해결로 설명한 항목")
                )

    edit(criteria_root, "compose", omit)
    errors, _ = audit(criteria_root)
    assert any(
        error.startswith("N04-O.4/") and "측정 방법 refinement target changed" in error
        for error in errors
    )


def test_migration_audit_rejects_lost_current_requirement(criteria_root):
    required = (
        "추가 작업이 필요하면 확보할 정보를 설명하고, 보완할 수 없으면 사유를 밝힌다."
    )

    def omit(data):
        row = next(row for row in data["checks"] if row["검사 ID"] == "N03-O.4")
        assert required in row["성공 기준"].split("<br>")
        row["성공 기준"] = "<br>".join(
            sentence
            for sentence in row["성공 기준"].split("<br>")
            if sentence != required
        )

    edit(criteria_root, "decide", omit)
    errors, _ = audit(criteria_root)
    assert any(
        "N03-O.4/general: 성공 기준 refinement target changed" in error
        for error in errors
    )


def test_migration_audit_rejects_changed_revision_source(criteria_root):
    path = criteria_root / "eval/docs/nodes/originals/interpret.md"
    source = source_revisions()["checks"]["N01-O.1"]["fields"]["검사 내용"]["before"]
    path.write_text(
        path.read_text(encoding="utf-8").replace(source, "변경된 과거 기준"),
        encoding="utf-8",
    )
    errors, _ = audit(criteria_root)
    assert "N01-O.1: 검사 내용 revision source changed" in errors


def test_migration_audit_rejects_changed_revision_basis(criteria_root):
    basis = source_revisions()["basis"]["workflow"]
    path = criteria_root / basis["path"]
    path.write_text(
        path.read_text(encoding="utf-8").replace(basis["text"], "다른 책임 배분"),
        encoding="utf-8",
    )
    errors, _ = audit(criteria_root)
    assert "workflow: revision basis changed" in errors


def test_migration_audit_rejects_missing_split_condition_in_its_assigned_row(
    criteria_root,
):
    baseline, _ = audit(criteria_root)
    row_id = "N04-B.1/report-description"
    column = "측정 방법"
    omitted = "설명문의 대상·기간·내용을 확정된 선정의 뷰·근거·범위와 대조한다."

    def omit(data):
        binding = next(item for item in data["bindings"] if item["row_id"] == row_id)
        row = data["checks"][binding["row"]]
        sentences = row[column].split("<br>")
        assert omitted in sentences
        row[column] = "<br>".join(text for text in sentences if text != omitted)

    edit(criteria_root, "compose", omit)
    errors, _ = audit(criteria_root)
    assert f"{row_id}: {column} refinement target changed" in (
        set(errors) - set(baseline)
    )


def test_migration_audit_rejects_split_condition_assigned_to_another_role(
    criteria_root,
):
    baseline, _ = audit(criteria_root)
    row_id = "N04-B.1/report-insight"
    column = "측정 방법"
    selection_only = (
        "선정 뷰·개수·이유를 확보 근거·설명 범위·"
        "제공된 뷰 목록과 산출물별 선정 기준에 대조한다."
    )

    def add_other_role_condition(data):
        bindings = {item["row_id"]: item for item in data["bindings"]}
        selection = data["checks"][bindings["N04-B.1/report-selection"]["row"]]
        insight = data["checks"][bindings[row_id]["row"]]
        assert selection_only in selection[column].split("<br>")
        assert selection_only not in insight[column].split("<br>")
        insight[column] += "<br>" + selection_only

    edit(criteria_root, "compose", add_other_role_condition)
    errors, _ = audit(criteria_root)
    assert f"{row_id}: {column} refinement target changed" in (
        set(errors) - set(baseline)
    )


def test_loads_all_original_ids_and_methods_from_json_with_hashes():
    catalog = load_criteria()
    originals = Path(catalog["root"]) / "eval/docs/nodes/originals"
    baseline = {}
    for path in originals.glob("*.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and re.fullmatch(r"N(?:\d{2})?-[A-Z]\.\d+", cells[0]):
                baseline[cells[0]] = next(
                    cell for cell in cells if cell in {"규칙 기반", "LLM 기반"}
                )
    assert {key: item["method"] for key, item in catalog["checks"].items()} == baseline
    assert len(catalog["documents"]) == 6
    for name, document in catalog["documents"].items():
        assert name.endswith(".json")
        raw = (Path(catalog["root"]) / name).read_bytes()
        assert document["sha256"] == hashlib.sha256(raw).hexdigest()
    for check in catalog["checks"].values():
        for row in check["rows"]:
            assert "related_checks" not in row
            source = row["source"]
            data = json.loads(catalog["documents"][source["path"]]["text"])
            for token in source["pointer"].strip("/").split("/"):
                data = data[int(token)] if isinstance(data, list) else data[token]
            assert data == row["fields"]
            assert json.loads(row["text"]) == data


def test_reload_reads_latest_json_but_markdown_cannot_change_evaluation(criteria_root):
    first = load_criteria(criteria_root)
    for path in (criteria_root / "docs/eval").rglob("*.md"):
        path.write_text("설명 문서 변경", encoding="utf-8")
    assert load_criteria(criteria_root) == first
    edit(
        criteria_root,
        "ask",
        lambda d: d["checks"][0].update({"검사 항목": "질문 대상 변경"}),
    )
    second = load_criteria(criteria_root)
    identifier = json.loads(
        (criteria_root / "eval/docs/nodes/ask.json").read_text(encoding="utf-8")
    )["checks"][0]["검사 ID"]
    assert second["checks"][identifier]["fields"]["검사 항목"] == "질문 대상 변경"
    assert first["documents"] != second["documents"]


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["checks"][0].pop("평가 방식"),
        lambda d: d["checks"][0].update({"평가 방식": "사람 기반"}),
        lambda d: d["checks"][0].update({"평가 축": "다른 축"}),
        lambda d: d["checks"][0].update({"검사 ID": "BAD-ID"}),
        lambda d: d["checks"][0].update({"성공 기준": ""}),
        lambda d: d["bindings"][0]["when"].update(unknown=["x"]),
        lambda d: d["checks"][0].update(unrecognized=True),
    ],
)
def test_rejects_invalid_definition_before_scoring(criteria_root, change):
    edit(criteria_root, "ask", change)
    with pytest.raises(CriteriaError):
        load_criteria(criteria_root)


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (
            lambda d: d["checks"].append(d["checks"][0]),
            "every row requires exactly one binding",
        ),
        (
            lambda d: d["bindings"].append(d["bindings"][0]),
            "duplicate or invalid row binding",
        ),
        (
            lambda d: d["bindings"][0]["principles"].append(
                {"path": "../outside.json", "key": "missing"}
            ),
            "missing principle",
        ),
        (
            lambda d: d["bindings"][0].update(
                input_scopes={"도구 입력 명세": ["검토 대상 산출물"]}
            ),
            "input scope must name a declared input",
        ),
    ],
)
def test_rejects_duplicate_or_dangling_references(criteria_root, change, error):
    edit(criteria_root, "ask", change)
    with pytest.raises(CriteriaError, match=error):
        load_criteria(criteria_root)


def test_rejects_duplicate_json_keys(criteria_root):
    path = criteria_root / "eval/docs/nodes/ask.json"
    path.write_text('{"checks":[],"checks":[]}', encoding="utf-8")
    with pytest.raises(CriteriaError, match="duplicate JSON key"):
        load_criteria(criteria_root)


def test_responsibility_references_still_require_an_existing_check(criteria_root):
    edit(
        criteria_root,
        "common",
        lambda data: data["checks"][0].update(
            {"측정 방법": "내용의 정확성은 N99-O.1에서 판정한다."}
        ),
    )
    with pytest.raises(CriteriaError, match="unknown referenced check N99-O.1"):
        load_criteria(criteria_root)


def test_rejects_missing_definition_files(criteria_root):
    (criteria_root / "eval/docs/nodes/common.json").unlink()
    with pytest.raises(CriteriaError, match="common.json"):
        load_criteria(criteria_root)


def test_principle_line_points_to_definition_instead_of_earlier_reference():
    catalog = load_criteria()
    for path, sections in catalog["sections"].items():
        lines = catalog["documents"][path]["text"].splitlines()
        for section in sections:
            source = section["source"]
            assert json.loads(
                "{" + lines[source["line"] - 1].strip().rstrip(",") + "}"
            ) == {"key": section["key"]}
            assert any('"principles": [' in line for line in lines[: source["line"]])
            # 원칙 정의에는 title이 있고 검사 행의 참조에는 없다.
            assert '"title":' in lines[source["line"]]


@pytest.mark.parametrize(
    ("role", "call"),
    [
        ("interpretation", "Composition"),
        ("report_selection", "ReportSelection"),
        ("report_description", "ReportText"),
        ("report_insight", "ReportText"),
    ],
)
def test_response_roles_select_one_self_contained_row(role, call):
    catalog = load_criteria()
    definition = catalog["checks"]["N04-B.1"]
    selected = select_rows(
        definition, {"node": "compose", "role": role}, {"name": call}
    )
    assert not selected["missing_context"]
    assert len(selected["rows"]) == 1
    row = selected["rows"][0]
    assert row["inputs"]["runtime"] == ["모델 호출 입력"]
    if role != "report_selection":
        assert "시각화 목록과 입력 조건" not in row["inputs"]["runtime"]
    text = "\n".join(section["text"] for section in criterion_sections(row, catalog))
    assert "## 시험 사례" not in text
    assert all(
        section["source"]["path"].endswith(".json")
        for section in criterion_sections(row, catalog)
    )


def test_writing_and_review_do_not_share_dedicated_checks():
    catalog = load_criteria()
    node = {"node": "compose", "role": "report_description"}
    for check in ("N04-O.1", "N04-O.4", "N04-B.1"):
        assert not select_rows(
            catalog["checks"][check], node, {"name": "Verification"}
        )["rows"]
    review = catalog["checks"]["N04-O.3"]
    assert not select_rows(review, node, {"name": "ReportText"})["rows"]
    assert len(select_rows(review, node, {"name": "Verification"})["rows"]) == 1


def test_missing_role_and_overlapping_rows_cannot_be_treated_as_not_applicable():
    catalog = load_criteria()
    definition = catalog["checks"]["N04-B.1"]
    node, call = {"node": "compose"}, {"name": "ReportText"}
    assert select_rows(definition, node, call)["missing_context"]
    definition["rows"].append(definition["rows"][0])
    assert select_rows(
        definition, {"node": "compose", "role": "request"}, {"name": "Composition"}
    )["missing_context"]


def test_invalid_action_output_still_selects_format_check():
    definition = load_criteria()["checks"]["N-F.1"]
    selected = select_rows(definition, {"node": "act"}, {"output": {}, "raw": "{}"})
    assert not selected["missing_context"]
    assert len(selected["rows"]) == 1
    assert "act" in selected["rows"][0]["nodes"]
    assert "시각화 목록과 입력 조건" not in selected["rows"][0]["inputs"]["runtime"]
    assert select_rows(definition, {"node": "act"}, {})["missing_context"]


@pytest.mark.parametrize("node", [{}, {"node": None}, {"node": "unknown"}])
def test_missing_or_unknown_node_is_not_a_non_applicable_check(node):
    selected = select_rows(load_criteria()["checks"]["N-F.1"], node, {})
    assert not selected["rows"]
    assert selected["missing_context"]


@pytest.mark.parametrize("output", [None, {"name": "query_data"}])
def test_tool_branch_comes_from_raw_response_before_cached_output(output):
    definition = load_criteria()["checks"]["N-F.1"]
    selected = select_rows(
        definition,
        {"node": "act"},
        {"raw": '{"name":"validate_visualization"}', "output": output},
    )
    assert not selected["missing_context"]
    assert [row["row_id"] for row in selected["rows"]] == ["N-F.1/act-visualization"]
    assert "시각화 목록과 입력 조건" in selected["rows"][0]["inputs"]["runtime"]


def test_invalid_raw_is_not_repaired_by_cached_tool_name():
    selected = select_rows(
        load_criteria()["checks"]["N-F.1"],
        {"node": "act"},
        {"raw": "invalid json", "output": {"name": "validate_visualization"}},
    )
    assert [row["row_id"] for row in selected["rows"]] == ["N-F.1/act-other"]
    assert not selected["missing_context"]


def test_row_allowlist_filters_after_actual_context_selection():
    definition = load_criteria()["checks"]["N04-B.1"]
    node, call = {"node": "compose", "role": "report_insight"}, {"name": "ReportText"}
    allowed = ["N04-B.1/report-insight", "N04-B.1/report-description"]
    selected = select_rows(definition, node, call, row_ids=allowed)
    assert [row["row_id"] for row in selected["rows"]] == ["N04-B.1/report-insight"]
    assert not selected["missing_context"]
    assert not select_rows(definition, node, call, row_ids=[])["rows"]
    assert not select_rows(
        definition, node, call, row_ids=["N04-B.1/report-description"]
    )["rows"]
    row = selected["rows"][0]
    assert row["inputs"]["runtime"] == ["모델 호출 입력"]
    assert not row.get("input_scopes")
    sections = criterion_sections(row, load_criteria())
    assert {(s["source"]["path"], s["key"]) for s in sections} == {
        (reference["path"], reference["key"]) for reference in row["principles"]
    }


def test_row_allowlist_cannot_hide_missing_context_or_overlapping_conditions():
    definition = load_criteria()["checks"]["N04-B.1"]
    selected = select_rows(
        definition,
        {"node": "compose"},
        {"name": "ReportText"},
        row_ids=["N04-B.1/report-description"],
    )
    assert selected["missing_context"]
    duplicate = deepcopy(definition["rows"][0])
    duplicate["row_id"] += "-duplicate"
    definition["rows"].append(duplicate)
    selected = select_rows(
        definition,
        {"node": "compose", "role": "request"},
        {"name": "Composition"},
        row_ids=[definition["rows"][0]["row_id"]],
    )
    assert len(selected["rows"]) == 1
    assert any("여러 평가 행" in reason for reason in selected["missing_context"])


@pytest.mark.parametrize(
    "exclusions",
    [
        {"exclude_nodes": ["ask"]},
        {
            "exclude_roles": [
                "request",
                "interpretation",
                "visualization",
                "report_selection",
                "report_description",
                "report_insight",
            ]
        },
    ],
)
def test_loader_rejects_rows_excluded_from_every_possible_context(
    criteria_root,
    exclusions,
):
    edit(criteria_root, "ask", lambda data: data["bindings"][0].update(when=exclusions))
    with pytest.raises(CriteriaError, match="unreachable row selector"):
        load_criteria(criteria_root)


def test_loader_rejects_overlapping_rows_before_either_is_scored(criteria_root):
    def overlap(data):
        original = deepcopy(data["bindings"][0])
        data["checks"].append(deepcopy(data["checks"][0]))
        original.update(
            row=len(data["checks"]) - 1, row_id=original["row_id"] + "-copy"
        )
        original["when"] = {"roles": ["request"]}
        data["bindings"].append(original)

    edit(criteria_root, "ask", overlap)
    with pytest.raises(CriteriaError, match="overlapping row selectors"):
        load_criteria(criteria_root)


@pytest.mark.parametrize(
    "check,node,role,call,tool,row_id",
    [
        ("N-F.1", "interpret", "request", "Interpretation", None, "interpret"),
        ("N-F.1", "decide", "interpretation", "Decision", None, "decide"),
        ("N-F.1", "ask", "request", "Question", None, "ask"),
        ("N-F.1", "act", "request", "Selection", "query_data", "act-other"),
        (
            "N-F.1",
            "act",
            "visualization",
            "Selection",
            "validate_visualization",
            "act-visualization",
        ),
        ("N-F.1", "compose", "request", "Composition", None, "compose-general"),
        (
            "N-F.1",
            "compose",
            "report_selection",
            "ReportSelection",
            None,
            "compose-selection",
        ),
        (
            "N-F.1",
            "compose",
            "report_description",
            "ReportText",
            None,
            "compose-description",
        ),
        ("N-F.1", "compose", "report_insight", "ReportText", None, "compose-insight"),
        ("N-F.1", "compose", "report_insight", "Verification", None, "compose-review"),
        ("N02-O.3", "act", "interpretation", "Selection", "query_data", "query"),
        ("N02-O.3", "act", "interpretation", "Selection", "process_data", "process"),
        (
            "N02-O.3",
            "act",
            "visualization",
            "Selection",
            "validate_visualization",
            "visualization",
        ),
        ("N02-O.3", "act", "request", "Selection", "interpretation_agent", "agent"),
        ("N02-O.3", "act", "request", "Selection", "visualization_agent", "agent"),
        ("N02-O.3", "act", "request", "Selection", "none", None),
        ("N02-B.2", "act", "request", "Selection", "query_data", "other"),
        (
            "N02-B.2",
            "act",
            "visualization",
            "Selection",
            "validate_visualization",
            "visualization",
        ),
        ("N04-O.1", "compose", "interpretation", "Composition", None, "interpretation"),
        ("N04-O.1", "compose", "visualization", "Composition", None, "visualization"),
        ("N04-O.1", "compose", "request", "Composition", None, "request"),
        (
            "N04-O.1",
            "compose",
            "report_selection",
            "ReportSelection",
            None,
            "report-selection",
        ),
        (
            "N04-O.1",
            "compose",
            "report_description",
            "ReportText",
            None,
            "report-description",
        ),
        ("N04-O.1", "compose", "report_insight", "ReportText", None, "report-insight"),
        (
            "N04-O.3",
            "compose",
            "report_selection",
            "Verification",
            None,
            "report-selection",
        ),
        (
            "N04-O.3",
            "compose",
            "report_description",
            "Verification",
            None,
            "report-description",
        ),
        (
            "N04-O.3",
            "compose",
            "report_insight",
            "Verification",
            None,
            "report-insight",
        ),
    ],
)
def test_current_json_selects_only_the_actual_node_role_call_and_tool(
    check,
    node,
    role,
    call,
    tool,
    row_id,
):
    definition = load_criteria()["checks"][check]
    selected = select_rows(
        definition,
        {"node": node, "role": role},
        {"name": call, "raw": json.dumps({"name": tool} if tool else {})},
    )
    assert not selected["missing_context"]
    expected = [check + "/" + row_id] if row_id is not None else []
    assert [row["row_id"] for row in selected["rows"]] == expected
