"""원본 보관과 JSON으로 이동한 본문의 표현·예외·근거 보존을 확인한다."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from eval.scripts.check_node_criteria_migration import (
    NAMES,
    audit_principles,
    normalized_tables,
    original_rows,
    revised_principle,
    source_revisions,
    source_splits,
)

AI = Path(__file__).resolve().parents[2]
ORIGINS = Path(__file__).parent / "fixtures" / "node_criteria_origins.json"


def assert_archive_bytes(root):
    origins = json.loads(ORIGINS.read_text(encoding="utf-8"))
    supporting = origins.get("supporting_sources_sha256", {})
    assert not set(supporting) & set(origins["archives_sha256"])
    for path, expected in (origins["archives_sha256"] | supporting).items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected, path


def test_archive_bytes_match_recovered_baseline():
    assert_archive_bytes(AI)
    origins = json.loads(ORIGINS.read_text(encoding="utf-8"))
    baseline = origins["archive_baseline"]
    assert baseline["status"] == "recovered"
    assert baseline["reason"]
    assert set(baseline["historical_sha256"]) == set(origins["archives_sha256"])


def test_archive_byte_change_is_rejected(tmp_path):
    shutil.copytree(
        AI / "eval/docs/nodes/originals", tmp_path / "eval/docs/nodes/originals"
    )
    path = tmp_path / "eval/docs/nodes/originals/common.md"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(AssertionError, match="originals/common.md"):
        assert_archive_bytes(tmp_path)


def test_all_principles_preserve_source_or_explicit_sentence_splits():
    assert not audit_principles(AI)


def test_supporting_archive_byte_change_is_rejected(tmp_path):
    origins = json.loads(ORIGINS.read_text(encoding="utf-8"))
    supporting = origins["supporting_sources_sha256"]
    for relative in origins["archives_sha256"] | supporting:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(AI / relative, destination)
    relative = next(iter(supporting))
    path = tmp_path / relative
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(AssertionError, match=re.escape(relative)):
        assert_archive_bytes(tmp_path)


@pytest.fixture
def preservation_root(tmp_path):
    shutil.copytree(AI / "eval/docs", tmp_path / "eval/docs")
    return tmp_path


def test_reorganized_principle_cannot_lose_an_independent_violation_condition(
    preservation_root,
):
    path = preservation_root / "eval/docs/nodes/common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    principle = next(
        p for p in data["principles"] if p["key"] == "independent-violations"
    )
    principle["text"] = principle["text"].replace(
        "한 검사가 실패했다는 이유만으로 다른 검사도 실패시키지 않는다.", ""
    )
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert (
        "common/independent-violations: principle content differs from mapped source"
        in audit_principles(preservation_root)
    )


@pytest.mark.parametrize("change", ["omit", "duplicate", "insert-condition"])
def test_layout_cannot_omit_duplicate_or_invent_revision_conditions(change):
    origins = json.loads(ORIGINS.read_text(encoding="utf-8"))
    targets = origins["principle_layout"]["common"]["check-responsibility"]["targets"]
    target = next(item for item in targets if item["key"] == "revision-evaluation")
    if change == "omit":
        target["fragments"].pop()
        error = "layout source condition omitted"
    elif change == "duplicate":
        target["fragments"].append(target["fragments"][0])
        error = "layout source used more than once"
    else:
        target["joiner"] = "\n수정본은 항상 통과한다.\n"
        error = "invalid layout target or joiner"
    assert any(error in item for item in audit_principles(AI, origins))


def test_deduplicated_rule_requires_its_canonical_clause(preservation_root):
    path = preservation_root / "eval/docs/nodes/common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    principle = next(p for p in data["principles"] if p["key"] == "verdict")
    principle["selection"]["clauses"] = [
        c for c in principle["selection"]["clauses"] if c["id"] != "verdicts"
    ]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert any(
        "removed condition has no canonical clause" in error
        for error in audit_principles(preservation_root)
    )


def test_compacted_principle_still_requires_its_original_source():
    origins = json.loads(ORIGINS.read_text(encoding="utf-8"))
    changes = origins["source_refinements"]["principles"]["common"]["verdict"]
    changes[0]["before"] = "보관 원문에 없는 판정 기준"
    assert any(
        "common/verdict refinement: source changed" in error
        for error in audit_principles(AI, origins)
    )


def test_compacted_principle_cannot_lose_failure_priority(preservation_root):
    path = preservation_root / "eval/docs/nodes/common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    principle = next(p for p in data["principles"] if p["key"] == "verdict")
    principle["text"] = principle["text"].replace(
        "현재 검사가 담당하는 위반과 확인 불가 조건이 함께 있으면 실패다.",
        "증거가 부족하면 항상 미판정이다.",
    )
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert (
        "common/verdict: principle content differs from mapped source"
        in audit_principles(preservation_root)
    )


def test_source_split_mappings_only_target_existing_principles_and_checks():
    splits = source_splits()
    origins = json.loads(ORIGINS.read_text(encoding="utf-8"))
    originals = original_rows()
    assert set(splits.get("checks", {})) <= set(originals)
    for name, principles in splits.get("principles", {}).items():
        assert set(principles) <= set(origins["principles"][name])
    revisions = source_revisions()
    for name, principles in revisions.get("principles", {}).items():
        assert set(principles) <= set(origins["principles"][name])
        for changes in principles.values():
            assert all(change["basis"] in revisions["basis"] for change in changes)
    for changes in revisions.get("paragraphs", {}).values():
        assert all(change["basis"] in revisions["basis"] for change in changes)


def test_principle_revision_rejects_changed_source():
    with pytest.raises(ValueError, match="revision: source changed"):
        revised_principle("interpret", "output-format", "원문과 무관한 내용")


def baseline_links(text, source, root):
    """Compare relocated Markdown using the archived document's link base."""

    def previous(path):
        if path == root / "eval/docs/runner.md":
            return root / "docs/runtime/evaluation-runner.md"
        if path.is_relative_to(root / "eval/docs"):
            return root / "docs/eval" / path.relative_to(root / "eval/docs")
        if path.is_relative_to(root / "eval"):
            return root / "evaluation" / path.relative_to(root / "eval")
        return path

    def replace(match):
        target = urlsplit(match[1])
        if target.scheme or target.netloc or not target.path:
            return match[0]
        destination = previous((source.parent / target.path).resolve())
        relative = Path(
            os.path.relpath(destination, previous(source).parent)
        ).as_posix()
        return "(" + relative + ("#" + target.fragment if target.fragment else "") + ")"

    return re.sub(r"(?<=\])\(([^\s()]+)\)", replace, text)


def assert_non_check_paragraphs(root):
    originals = original_rows(root)
    origins = json.loads(ORIGINS.read_text(encoding="utf-8"))
    revisions = source_revisions()
    for name in NAMES:
        source = root / f"eval/docs/nodes/originals/{name}.md"
        lines = source.read_text(encoding="utf-8").splitlines()
        current_path = root / f"eval/docs/nodes/{name}.md"
        current = baseline_links(
            current_path.read_text(encoding="utf-8"), current_path, root
        )
        retained = [current]
        for revision in revisions.get("paragraphs", {}).get(name, []):
            assert lines.count(revision["before"]) == 1, (
                name,
                "paragraph revision source",
            )
            assert revision["after"] in current, (name, "paragraph revision missing")
            retained.append(revision["before"])
        example = revisions.get("archived_examples", {}).get(name)
        if example:
            example_text = "\n".join(
                lines[example["first_line"] - 1 : example["last_line"]]
            )
            assert (
                hashlib.sha256(example_text.encode()).hexdigest()
                == example["text_sha256"]
            )
            assert (root / example["current_reference"]).is_file()
            assert all(line.startswith("|") for line in example_text.splitlines())
            retained.append(example_text)
        for spans in origins["principles"][name].values():
            for span in spans:
                if span["path"] == source.relative_to(root).as_posix():
                    retained.append(
                        "\n".join(lines[span["first_line"] - 1 : span["last_line"]])
                    )
        copied = normalized_tables("\n".join(retained))
        check_lines = {
            item["line"] for item in originals.values() if item["file"] == name
        }
        for number, line in enumerate(lines, 1):
            if metadata := re.fullmatch(
                r"(상태: [^.]+\. 수정일: )\d{4}-\d{2}-\d{2}\.", line
            ):
                assert re.search(
                    re.escape(metadata[1]) + r"\d{4}-\d{2}-\d{2}\.", current
                )
                continue
            if (
                not line.strip()
                or line.startswith("#")
                or number in check_lines
                or re.match(r"\| 검사 ID\s*\|", line)
                or re.fullmatch(r"[| :\-]+", line)
            ):
                continue
            assert normalized_tables(line) in copied, (
                f"{name}:{number}: original paragraph lost"
            )


def test_non_check_paragraphs_preserve_content_or_explicit_current_revisions():
    assert_non_check_paragraphs(AI)


def test_unmapped_non_check_paragraph_loss_is_rejected(tmp_path):
    shutil.copytree(AI / "eval/docs/nodes", tmp_path / "eval/docs/nodes")
    examples = tmp_path / "eval/scenarios/nodes"
    examples.mkdir(parents=True)
    shutil.copyfile(AI / "eval/scenarios/nodes/README.md", examples / "README.md")
    path = tmp_path / "eval/docs/nodes/common.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "각 노드의 전용 검사와 함께 적용한다.\n", ""
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="original paragraph lost"):
        assert_non_check_paragraphs(tmp_path)
