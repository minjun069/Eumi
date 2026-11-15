"""가상 모델 경계로 실제 노드 실행·채점 파일과 뷰어의 연결을 검증한다.

Eumi/ai에서 ``uv run python -m eval.viewers.nodes.runner_integration``.
``--write-samples``는 같은 가상 산출물로 화면 샘플을 갱신한다.
외부 모델·운영 DB를 호출하지 않으며 실행 결과는 임시 폴더에만 저장한다.
"""

import argparse
import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from eval.assessment_store import load_assessment
from eval.nodes.scoring import score_nodes
from eval.runner import load_suite, run_suite
from eval.schema import Suite, suite_adapter
from src.settings import Settings


def fixture_suite() -> Suite:
    """사례와 가상 응답만 준비하고 실행·채점은 현행 실행기를 사용한다."""
    cases = []
    for case_id, unit, target, role, checks, expected in (
        (
            "interpret-pass",
            "node",
            "interpret",
            "interpretation",
            ["N-F.1", "N01-O.2", "N01-O.1"],
            [
                {
                    "id": "goal-present",
                    "check": "N01-O.2",
                    "value": "가상 A지역의 고립 위험 신호를 확인한다.",
                },
                {
                    "id": "goal-meaning",
                    "check": "N01-O.1",
                    "value": "요청에 없는 지역·기간·조건을 추가하지 않는다.",
                },
            ],
        ),
        (
            "decide-format-fail",
            "node",
            "decide",
            "request",
            ["N-F.1", "N03-O.3"],
            [{"id": "next", "check": "N03-O.3", "path": "/next", "value": "ask"}],
        ),
        (
            "ask-unjudged",
            "node",
            "ask",
            "request",
            ["N-F.1", "N05-O.2"],
            [],
        ),
        (
            "selection-only",
            "selection",
            "act",
            "interpretation",
            ["N-F.1"],
            [],
        ),
    ):
        cases.append(
            {
                "id": case_id,
                "unit": unit,
                "target": target,
                "role": role,
                "purpose": {
                    "interpret-pass": "[가상] 형식·목표 포함·해석 검사와 재평가 전환",
                    "decide-format-fail": "[가상] 잘못된 진행 방향과 후속 검사 생략",
                    "ask-unjudged": "[가상] 규칙 미판정과 모의 LLM 판정 전환",
                    "selection-only": "[가상] 작업 선택의 판정과 노드 집계 제외",
                }[case_id],
                "initial": {
                    "request": {"goal": "가상 A지역의 고립 위험 신호를 확인한다."},
                    "event": "user_request"
                    if role == "request"
                    else "analysis_pipeline",
                    "messages": [
                        {
                            "type": "human",
                            "content": "가상 A지역의 고립 위험 신호를 확인해 줘.",
                            "id": "fixture-request",
                        }
                    ],
                },
                "assessment": {
                    "checks": checks,
                    "required": True,
                    "expected": {
                        "schema_version": "node-expectations-v1",
                        "items": expected,
                    },
                },
                "tags": ["가상", "뷰어 통합 검증", "반복 실행"],
            }
        )
    return suite_adapter.validate_python(
        {
            "schema_version": "evaluation-suite-v1",
            "id": "node-viewer-fictional-fixture",
            "cases": cases,
            "node_performance": [
                {
                    "target": "interpret",
                    "role": "interpretation",
                    "metric": "response_time",
                    "group": "normal",
                    "statistic": "p95",
                    "max_seconds": 5.0,
                    "case_ids": ["interpret-pass"],
                    "environment": "가상 모델 응답을 사용하는 로컬 통합 검증",
                    "data_size": "가상 요청 1개 · 외부 자료 없음",
                },
                {
                    "target": "interpret",
                    "role": "interpretation",
                    "metric": "failure_rate",
                    "max_rate": 0.0,
                    "case_ids": ["interpret-pass"],
                    "environment": "가상 모델 응답을 사용하는 로컬 통합 검증",
                    "data_size": "가상 요청 1개 · 외부 자료 없음",
                },
            ],
        }
    )


class FixtureModel:
    """실제 모델 어댑터가 수신하는 응답 경계만 가상 자료로 대체한다."""

    def with_structured_output(self, schema, **_kwargs):
        async def invoke(_messages, config):
            output = {
                "Interpretation": {
                    "request": {
                        "goal": "가상 A지역의 고립 위험 신호를 확인한다.",
                        "constraints": {},
                    },
                    "reason": "사용자가 요청한 가상 지역과 작업 목표를 정리했다.",
                },
                "Decision": {"next": "invalid-next", "reason": "가상 형식 실패 사례"},
                "Question": {
                    "content": "어느 기간을 확인할까요?",
                    "reason": "가상 질문 사례",
                },
                "Selection": {
                    "name": "query_data",
                    "arguments_json": '{"target":"analysis_result"}',
                    "reason": "가상 지역 조회를 선택만 하고 도구를 실행하지 않는다.",
                },
            }[schema["title"]]
            return {
                "raw": AIMessage(
                    content=json.dumps(output, ensure_ascii=False),
                    response_metadata={"model_name": "fictional-viewer-model"},
                    usage_metadata={
                        "input_tokens": 40,
                        "output_tokens": 20,
                        "total_tokens": 60,
                    },
                )
            }

        return RunnableLambda(invoke)


class FixtureJudge:
    """뷰어 통합 검증용 고정 판정이며 실제 의미 품질 평가가 아니다."""

    def with_structured_output(self, _schema, **_kwargs):
        return self

    async def ainvoke(self, messages, config):
        items = re.findall(r"^\[(항목 \d+)\]$", messages[1].content, re.MULTILINE)
        comparison = re.findall(
            r"^\[((?:입력|기대|기준) \d+)\]", messages[1].content, re.MULTILINE
        )[:1]
        return {
            "raw": AIMessage(
                content=json.dumps(
                    {
                        "details": [
                            {
                                "id": item,
                                "verdict": "통과",
                                "reason": "[가상] 세부 항목 표시 검증용 고정 판정",
                                "evidence": ["출력 1", *comparison],
                            }
                            for item in items
                        ],
                        "reason": "[가상] 실제 품질을 판정하지 않는 통합 검증 모델",
                    },
                    ensure_ascii=False,
                ),
                response_metadata={"model_name": "fictional-viewer-judge"},
                usage_metadata={
                    "input_tokens": 15,
                    "output_tokens": 8,
                    "total_tokens": 23,
                },
            )
        }


NODE_ASSERTIONS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { parseFiles } = require(process.argv[1]);
(async () => {
  const {files, assessments} = JSON.parse(fs.readFileSync(0, 'utf8'));
  const sources = new Map(files.map(file => [file.path, file.text]));
    const stored = new Map(files.map(file => [file.path, file]));
  const originalAt = path => JSON.parse(sources.get(path));
  const result = await parseFiles(files);
  assert.equal(result.issues.length, 0, JSON.stringify(result.issues));
  assert.equal(result.batches.length, 4);
  assert.equal(Object.keys(assessments).length, 8);
  for (const batch of result.batches) {
  assert.equal(batch.runs.length, 2);
  assert.equal(batch.assessments.length, 2);
  assert.equal(new Set(batch.runs.map(run => run.report.run.target)).size, 1);
  for (const run of batch.runs) {
    assert.equal(run.report.assessment.verdict, '미판정', '원본 실행과 별도 채점 구분');
    assert.equal(run.report.assessment.executed, false);
    assert.ok(run.report.trace.spans.some(span => span.kind === 'model'));
    assert.ok(run.report.trace.spans.every(span =>
      !['tool', 'database', 'agent'].includes(span.kind)));
    assert.equal(run.report.state.results.length, 0,
      '단독 노드 모델 출력은 업무 State에 적용하지 않음');
    assert.ok(run.journal.length > 0);
  }
  for (const record of batch.assessments) {
    assert.ok(Object.hasOwn(assessments, record.path), 'Python 복원 결과 연결');
    assert.deepEqual(record.report, assessments[record.path],
      'Python·뷰어의 전체 채점 결과 복원 동등성');
    assert.deepEqual(record.report, originalAt(record.path), '채점 JSON 원문 보존');
    const score = record.report;
    assert.equal(score.schema_version, 'node-evaluation-v1');
    assert.equal(score.runs.length, 2);
    assert.equal(score.assessments.length, 2);
    assert.equal(score.nodes.length,
      score.runs[0].case_id === 'selection-only' ? 0 : 1,
      '선택만 실행한 act는 노드 지표에서 제외');
    assert.ok(score.assessments.filter(item => item.case_id === 'selection-only')
      .every(item => !item.counted));
    assert.ok(score.runs.filter(item => item.case_id === 'decide-format-fail')
      .every(item => item.verdict === '실패'));
    assert.ok(score.runs.filter(item => item.case_id === 'ask-unjudged')
      .every(item => item.verdict === (score.method === 'all' ? '통과' : '미판정')));
    const interpret = score.nodes.find(item =>
      item.node === 'interpret' && item.role === 'interpretation');
    if (interpret) {
    assert.equal(interpret.operational.measurement_scope, 'selected_model_calls');
    assert.equal(interpret.operational.model_calls.mean, 1);
    assert.equal(interpret.operational.tokens.input_tokens.mean, 40);
    assert.equal(interpret.operational.tokens.output_tokens.mean, 20);
    assert.equal(interpret.operational.response_time.normal.sample_count, 2);
    assert.equal(interpret.performance.length, 2);
    }
    assert.equal(score.selection.run_cases.length, 2);
    assert.ok(score.provenance.every(item => item.case_criteria === 'same'));
    if (score.method === 'all') {
      assert.ok(score.runs.filter(item => item.case_id === 'interpret-pass')
        .every(item => item.verdict === '통과'));
      if (interpret) {
        assert.ok(score.judge_trace.spans.some(span => span.kind === 'model'));
      }
    } else {
      assert.ok(score.runs.filter(item => item.case_id === 'interpret-pass')
        .every(item => item.verdict === '미판정'));
      assert.ok(score.judge_trace.spans.every(span => span.kind !== 'model'));
    }
  }
  }
  console.log('PASS: 노드별 4 묶음 × 2 반복; 규칙/모의 LLM 채점 8건; ' +
    '원본·판정·선택 제외·운영 지표 연결.');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


async def generate_files(root: Path) -> list[dict[str, str]]:
    source = root / "suite.json"
    source.write_text(
        suite_adapter.dump_json(fixture_suite(), indent=2).decode(), encoding="utf-8"
    )
    settings = Settings(
        _env_file=None, api_key=None, database_url=None, langfuse_enabled=False
    )
    with patch(
        "eval.runner.create_model",
        side_effect=AssertionError("외부 모델 생성 금지"),
    ):
        batches = await run_suite(
            load_suite(source),
            settings,
            root / "outputs",
            repeat=2,
            source_path=source,
            model=FixtureModel(),
        )
        originals = {
            path: path.read_bytes()
            for batch in batches
            for path in batch.rglob("*")
            if path.is_file()
        }
        for batch in batches:
            await score_nodes(batch)
            await score_nodes(batch, method="all", model=FixtureJudge())
    assert all(path.read_bytes() == content for path, content in originals.items()), (
        "채점이 원본 증거를 변경함"
    )
    return [
        {
            "path": "node-viewer-fixture/"
            + path.relative_to(root / "outputs").as_posix(),
            "text": path.read_text(encoding="utf-8"),
        }
        for path in sorted((root / "outputs").rglob("*"))
        if path.is_file()
    ]


def write_samples(files: list[dict[str, str]]) -> None:
    # JSON은 파서와 같은 경로로 읽으며 실행기 산출 구조를 임의로 재구성하지 않는다.
    payload = {
        "label": "화면 검토용 가상 모델·가상 판정 · 실제 업무 모델의 평가 아님",
        "files": files,
    }
    destination = Path(__file__).with_name("samples.js")
    destination.write_text(
        "// runner_integration.py --write-samples로 생성한 가상 화면 자료.\n"
        "(function (root) {\n  'use strict';\n  root.EvaluationSamples = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n})(typeof window === 'undefined' ? globalThis : window);\n",
        encoding="utf-8",
    )
    print(f"가상 화면 샘플 저장: {destination}")


async def verify(*, save_samples: bool = False) -> None:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("통합 검증에는 Node.js가 필요합니다.")
    parser = Path(__file__).with_name("data.js")
    with TemporaryDirectory(prefix="eumi-node-viewer-") as temporary:
        files = await generate_files(Path(temporary))
        output = Path(temporary) / "outputs"
        assessments = {
            "node-viewer-fixture/"
            + path.relative_to(output).as_posix(): load_assessment(path)
            for path in output.glob("*/*/assessments/*.json")
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
        if save_samples:
            write_samples(files)


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument(
        "--write-samples", action="store_true", help="가상 화면 샘플 갱신"
    )
    asyncio.run(verify(save_samples=arguments.parse_args().write_samples))
