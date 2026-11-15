"""이전 확장 보고서 자료를 보존한다. 현행 경로는 basic_reports에서 실행한다."""

import json
from hashlib import sha256
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[2] / "eval/scenarios/nodes-extended-v2"


def test_extended_report_inputs_remain_unchanged_in_the_archive():
    manifest = json.loads(
        (ARCHIVE / "archive-manifest.json").read_text(encoding="utf-8")
    )
    for name, expected in manifest["files_sha256"].items():
        assert sha256((ARCHIVE / name).read_bytes()).hexdigest() == expected
    sidecar = json.loads((ARCHIVE / "scenarios.json").read_text(encoding="utf-8"))
    reports = {
        path["id"]: path
        for path in sidecar["scenarios"]
        if path["event"] == "analysis_pipeline"
    }
    assert len(reports) == 8
    assert reports["report-path-no-evidence"]["terminal"]["status"] == "failed"
    assert reports["report-path-one"]["terminal"]["status"] == "partial"
    assert reports["report-path-two"]["terminal"]["status"] == "partial"
    for stage in ("selection", "description", "insight"):
        assert reports[f"report-path-{stage}-rewrite"]["events"]
