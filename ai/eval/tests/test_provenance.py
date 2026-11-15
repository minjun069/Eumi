"""평가 코드 이동 뒤에도 지문 수집과 과거 기준 대조를 보존한다."""

import json
from hashlib import sha256

import pytest

from eval import provenance
from eval.execution.scoring import _provenance as execution_provenance
from eval.nodes.assessment import RULES_SHA256, rules_digest
from eval.nodes.criteria import load_criteria
from eval.nodes.scoring import _provenance as node_provenance
from src.execution_trace import execution_manifest
from src.settings import Settings


def test_code_hashes_include_nested_core_files_without_test_or_viewer_assets(
    tmp_path, monkeypatch
):
    files = {
        "runner.py": "runner",
        "nodes/scoring.py": "nodes",
        "execution/scoring.py": "execution",
        "tools/rules/numeric.py": "numeric",
        "tests/test_example.py": "test",
        "viewers/catalog.py": "viewer",
        "scripts/generate.py": "script",
        "scenarios/generate.py": "scenario",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(provenance, "PACKAGE_ROOT", tmp_path)

    hashes = provenance.code_hashes()
    assert hashes == {
        name: sha256(content.encode()).hexdigest()
        for name, content in files.items()
        if name.startswith(("runner", "nodes/", "execution/", "tools/"))
    }
    (tmp_path / "nodes/scoring.py").write_text("changed", encoding="utf-8")
    updated = provenance.code_hashes("nodes/scoring.py", "execution/scoring.py")
    assert updated["nodes/scoring.py"] != hashes["nodes/scoring.py"]
    assert updated["execution/scoring.py"] == hashes["execution/scoring.py"]


@pytest.mark.parametrize("kind", ["nodes", "execution"])
@pytest.mark.parametrize(
    ("saved", "expected", "original"),
    [
        ({"docs/eval/nodes/common.json": "same-hash"}, "same", "same-hash"),
        ({"docs/eval/nodes/common.json": "old-hash"}, "changed", "old-hash"),
        ({}, "unknown", None),
        (
            {
                "eval/docs/nodes/common.json": "current-hash",
                "docs/eval/nodes/common.json": "same-hash",
            },
            "changed",
            "current-hash",
        ),
    ],
)
def test_old_document_paths_preserve_comparison_and_original_evidence(
    tmp_path, kind, saved, expected, original
):
    run = tmp_path / "runs" / "run-1"
    run.mkdir(parents=True)
    assessment = {"checks": ["N-F.1"]}
    (run / "case.json").write_text(
        json.dumps({"assessment": assessment}), encoding="utf-8"
    )
    (run / "manifest.json").write_text(
        json.dumps({"files_sha256": saved}), encoding="utf-8"
    )
    originals = {path: path.read_bytes() for path in run.iterdir()}
    documents = {"eval/docs/nodes/common.json": {"sha256": "same-hash"}}
    hashes = {}
    entry = {"run_id": "run-1"}
    case = {"assessment": assessment}
    result = (
        node_provenance(tmp_path, entry, case, {"documents": documents}, hashes)
        if kind == "nodes"
        else execution_provenance(tmp_path, entry, case, documents, hashes)
    )

    assert result["case_criteria"] == "same"
    assert result["documents"]["eval/docs/nodes/common.json"] == {
        "original_sha256": original,
        "status": expected,
    }
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert hashes == {
        path.relative_to(tmp_path).as_posix(): sha256(content).hexdigest()
        for path, content in originals.items()
    }


def test_runtime_manifest_reads_moved_criteria_and_excludes_archived_originals(
    tmp_path,
):
    files = {
        "src/graph.py": "runtime",
        "eval/docs/methods.md": "methods",
        "eval/docs/nodes/common.json": "criteria",
        "eval/docs/nodes/originals/common.md": "archive",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    manifest = execution_manifest(Settings(_env_file=None), root=tmp_path)
    assert manifest["files_sha256"] == {
        name: sha256(content.encode()).hexdigest()
        for name, content in files.items()
        if "/originals/" not in name
    }


def test_rule_fingerprint_preserves_location_changes_but_detects_criteria_changes():
    catalog = load_criteria()
    assert rules_digest(catalog) == RULES_SHA256
    definition = next(
        item for item in catalog["checks"].values() if item["method"] == "규칙 기반"
    )
    original = json.loads(definition["text"])
    for binding in original["bindings"]:
        for reference in binding["principles"]:
            reference["path"] = reference["path"].replace("eval/docs/", "docs/eval/")
    definition["text"] = json.dumps(original, ensure_ascii=False, indent=2)
    assert rules_digest(catalog) == RULES_SHA256

    original["checks"][0]["성공 기준"] += " 추가된 필수 조건."
    definition["text"] = json.dumps(original, ensure_ascii=False, indent=2)
    assert rules_digest(catalog) != RULES_SHA256
