"""실제 도구 실행 산출물을 브라우저용 파서에 연결하는 로컬 통합 검증.

Eumi/ai에서 ``uv run python -m eval.viewers.results.runner_integration``으로 실행한다.
모든 입력과 출력은 임시 폴더에 생성하며 모델·운영 DB를 사용하지 않는다.
"""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from eval.assessment_store import load_assessment
from eval.runner import load_suite, run_suite
from eval.schema import Suite, suite_adapter
from eval.tools.scoring import score_batch
from src.settings import Settings


def fixture_suite() -> Suite:
    """조회 반환·정상 0건·실행 오류를 만드는 검증용 입력만 준비한다."""
    dataset = {
        "reference": {"id": "viewer_fixture", "version": "integration-only-v1"},
        "as_of": "2026-09",
        "sources": [{"label": "뷰어 통합 검증용 가상 자료", "uri": "fixture://viewer"}],
        "columns": [
            {
                "name": name,
                "kind": kind,
                "unit": unit,
                "spatial_unit": "district",
                "temporal_unit": "month",
                "denominator": "same population",
            }
            for name, kind, unit in (
                ("region", "string", "code"),
                ("value", "number", "index"),
            )
        ],
        "rows": [{"region": "A", "value": 10.0}, {"region": "B", "value": 20.0}],
    }
    queries = [
        (
            "filtered-query",
            "필터 조회의 실제 반환값과 기대 자료를 보존한다.",
            {"filters": [{"field": "region", "operator": "eq", "value": "B"}]},
            [{"region": "B", "value": 20.0}],
        ),
        (
            "empty-query",
            "정상 0건 반환을 오류와 구분한다.",
            {"filters": [{"field": "region", "operator": "eq", "value": "Z"}]},
            [],
        ),
        (
            "invalid-field",
            "실제 입력 오류와 후속 반복의 실행 증거를 보존한다.",
            {"fields": ["missing_field"]},
            {"code": "invalid_field"},
        ),
    ]
    return suite_adapter.validate_python(
        {
            "schema_version": "evaluation-suite-v1",
            "id": "viewer-integration-fixture",
            "datasets": {"viewer_fixture": dataset},
            "performance": [
                {
                    "target": "query_data",
                    "group": group,
                    "case_ids": case_ids,
                    "statistic": "p95",
                    "max_seconds": 5.0,
                    "environment": "local integration fixture",
                    "data_size": "2 rows",
                }
                for group, case_ids in (
                    ("normal", ["filtered-query", "empty-query"]),
                    ("error", ["invalid-field"]),
                )
            ],
            "cases": [
                {
                    "id": case_id,
                    "unit": "tool",
                    "target": "query_data",
                    "purpose": purpose,
                    "arguments": {"target": "viewer_fixture"} | arguments,
                    "assessment": {
                        "reference": "통합 검증용 가상 자료",
                        "expected": {
                            "schema_version": "tool-expectations-v1",
                            "items": [
                                {
                                    "check": "T-O.1",
                                    "path": "/failure/code"
                                    if case_id == "invalid-field"
                                    else "/output/data/rows",
                                    "value": expected["code"]
                                    if case_id == "invalid-field"
                                    else expected,
                                }
                            ],
                        },
                        "checks": ["T-O.1"],
                        "required": True,
                    },
                    "tags": ["integration-fixture"],
                }
                for case_id, purpose, arguments, expected in queries
            ],
        }
    )


NODE_ASSERTIONS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { parseFiles } = require(process.argv[1]);

(async () => {
  const {files, assessments} = JSON.parse(fs.readFileSync(0, 'utf8'));
  const sources = new Map(files.map(file => [file.path, file.text]));
  const originalAt = path => JSON.parse(sources.get(path));
  const result = await parseFiles(files);
  assert.equal(result.issues.length, 0, JSON.stringify(result.issues));
  assert.equal(result.batches.length, 1);
  const batch = result.batches[0];
  const batchPath = files.find(file => file.path.endsWith('/batch.json')).path;
  const prefix = batchPath.slice(0, -'batch.json'.length);
  const rawBatch = JSON.parse(sources.get(batchPath));
  assert.deepEqual(batch.report, rawBatch, '원본 batch.json 보존');
  assert.equal(rawBatch.status, 'error');
  assert.equal(Object.hasOwn(rawBatch, 'failure'), false);
  assert.equal(rawBatch.planned_runs, 6);
  assert.equal(batch.runs.length, 6);

  const records = batch.runs.map(run => run.report);
  assert.equal(new Set(records.map(report => report.run.id)).size, 6);
  for (const entry of rawBatch.runs) {
    const reportPath = prefix + entry.path;
    const folder = reportPath.slice(0, -'report.json'.length);
    const original = originalAt(reportPath);
    const parsed = batch.runs.find(run => run.report.run.id === entry.run_id);
    assert.ok(parsed, `누락 실행: ${entry.run_id}`);
    assert.deepEqual(parsed.report, original, '원본 report.json 보존');
    assert.deepEqual(parsed.case, originalAt(folder + 'case.json'));
    const manifest = originalAt(folder + 'manifest.json');
    assert.deepEqual(parsed.manifest, manifest);
    const journal = sources.get(folder + 'trace.jsonl')
      .trim().split(/\r?\n/).map(JSON.parse);
    assert.deepEqual(parsed.journal, journal, '시점별 추적 기록 보존');
    assert.ok(journal.length > 0);
    assert.equal(Object.hasOwn(parsed.report, 'state'), false,
      '없는 State를 만들지 않음');
    assert.equal(original.assessment.verdict, '미판정');
    assert.equal(original.assessment.executed, false);
    assert.deepEqual(original.assessment.checks, ['T-O.1']);
    assert.equal(original.run.dependencies, 'real');
    assert.equal(original.run.role, null);
    assert.equal(original.journal_saved, true);
    assert.equal(original.trace.coverage.unfinished_spans, 0);
    assert.ok(original.trace.spans.every(span => span.kind !== 'model'));
    assert.ok(original.trace.spans.every(span => span.kind !== 'database'));
    assert.equal(parsed.manifest.evaluation.source_sha256.length, 64);
  }

  for (const caseId of ['filtered-query', 'empty-query', 'invalid-field']) {
    const repeated = records.filter(report => report.run.case_id === caseId);
    assert.deepEqual(repeated.map(report => report.run.repetition).sort(), [1, 2]);
    for (const report of repeated) {
      if (caseId === 'invalid-field') {
        assert.equal(report.run.status, 'error');
        assert.equal(report.failure.code, 'invalid_field');
        assert.equal(report.output, null);
      } else {
        assert.equal(report.run.status, 'returned');
        assert.equal(report.failure, null);
        const expected = caseId === 'filtered-query' ? [{region: 'B', value: 20}] : [];
        assert.deepEqual(report.output.data.rows, expected);
        assert.equal(report.output.returned, expected.length);
      }
    }
  }
  assert.equal(batch.assessments.length, 2);
  assert.equal(batch.assessments.length, Object.keys(assessments).length);
  for (const record of batch.assessments) {
    assert.ok(Object.hasOwn(assessments, record.path), 'Python 복원 결과 연결');
    assert.deepEqual(record.report, assessments[record.path],
      'Python·뷰어의 전체 채점 결과 복원 동등성');
    assert.deepEqual(record.report, originalAt(record.path), '채점 JSON 원문 보존');
    assert.equal(record.report.runs.length, 6);
    assert.ok(record.report.runs.every(a => a.verdict === '통과'));
    assert.equal(record.report.tools[0].functional.numerator, 3);
    assert.equal(record.report.tools[0].functional.denominator, 3);
    assert.equal(record.report.tools[0].functional.rate, 1);
    assert.equal(record.report.tools[0].functional.verdict, '통과');
    assert.equal(record.report.tools[0].latency.normal.sample_count, 4);
    assert.equal(record.report.tools[0].latency.error.sample_count, 2);
    assert.ok(record.report.tools[0].latency.normal.p95_seconds >= 0);
    assert.equal(record.report.tools[0].performance.length, 2);
    for (const goal of record.report.tools[0].performance) {
      assert.equal(goal.max_seconds, 5);
      assert.equal(goal.data_size, '2 rows');
      assert.equal(goal.value_seconds,
        record.report.tools[0].latency[goal.group].p95_seconds);
    }
  }
  console.log('PASS: 3 real query_data cases x 2 repetitions; 2 scored snapshots; ' +
    '6 runs preserve raw evidence; saved check verdicts, 3/3 functional rate ' +
    'and 4 normal/2 error timings linked.');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


async def verify() -> None:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("이 통합 검증은 Node.js가 필요합니다.")
    parser = Path(__file__).with_name("data.js")
    if not parser.is_file():
        raise SystemExit(f"뷰어 파서가 없습니다: {parser}")
    settings = Settings(
        _env_file=None,
        api_key=None,
        database_url=None,
        langfuse_enabled=False,
    )
    with TemporaryDirectory(prefix="eumi-viewer-integration-") as temporary:
        root = Path(temporary)
        source = root / "suite.json"
        source.write_text(
            suite_adapter.dump_json(fixture_suite(), indent=2).decode("utf-8"),
            encoding="utf-8",
        )
        # 도구 단위 검증에 모델 생성이 추가되면 외부 호출 전에 실패한다.
        with patch(
            "eval.runner.create_model",
            side_effect=AssertionError(
                "뷰어 도구 통합 검증은 모델을 호출하지 않습니다."
            ),
        ):
            batch = await run_suite(
                load_suite(source),
                settings,
                root / "outputs",
                repeat=2,
                source_path=source,
            )
        score_batch(batch)
        score_batch(batch)
        files = [
            {
                "path": "fixture-results/" + path.relative_to(batch.parent).as_posix(),
                "text": path.read_text(encoding="utf-8"),
            }
            for path in sorted(batch.rglob("*"))
            if path.is_file()
        ]
        assessments = {
            "fixture-results/"
            + path.relative_to(batch.parent).as_posix(): load_assessment(path)
            for path in (batch / "assessments").glob("*.json")
        }
        completed = await asyncio.to_thread(
            subprocess.run,
            [node, "-e", NODE_ASSERTIONS, str(parser.resolve())],
            input=json.dumps(
                {"files": files, "assessments": assessments}, ensure_ascii=False
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
        print(completed.stdout.strip())


if __name__ == "__main__":
    asyncio.run(verify())
