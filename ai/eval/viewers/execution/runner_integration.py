"""가상 모델 경계로 실제 에이전트 실행·채점 파일과 뷰어의 연결을 검증한다.

Eumi/ai에서 ``uv run python -m eval.viewers.execution.runner_integration``.
``--write-samples``는 같은 산출물의 JSON 파일로 화면 샘플을 갱신한다.
업무 노드·그래프·도구·채점기는 그대로 실행하고 외부 모델·DB는 호출하지 않는다.
누락 반복·기준 변경은 임시 시험 자료에만 준비한다.
"""

import argparse
import asyncio
import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from eval.assessment_store import load_assessment
from eval.execution.scoring import score_executions
from eval.runner import load_suite, run_suite
from eval.scenarios.execution.generate import build_suite
from eval.schema import Suite, suite_adapter
from src.settings import Settings

ENVIRONMENT = "가상 모델·합성 자료를 사용하는 로컬 뷰어 통합 검증"
DATA_SIZE = "요청 1개 또는 동·월 1개 · 합성 자료 1행"
MODEL_NAME = "fictional-execution-viewer-model"


def fixture_suite() -> Suite:
    """현행 실행 연결 사례에 진단 역할과 명시한 가상 운영 목표를 준비한다."""
    suite = build_suite()
    suite["id"] = "execution-viewer-fictional-fixture"
    for case in suite["cases"]:
        case["purpose"] = "[가상] " + case["purpose"]
        case["tags"] = ["가상", "뷰어 통합 검증", "반복 실행"]
        case["assessment"]["expected"].update(
            environment=ENVIRONMENT, data_size=DATA_SIZE
        )
    request = suite["cases"][0]
    request["assessment"]["expected"].update(
        node_path=["interpret", "decide", "compose"], execution_status="completed"
    )
    diagnostic = deepcopy(request)
    diagnostic.update(
        id="interpretation-diagnostic",
        target="interpretation",
        purpose="[가상] 해석 역할의 운영 사용량을 표시하고 EX 기능 집계에서 제외한다.",
    )
    diagnostic.pop("assessment")
    suite["cases"].append(diagnostic)
    suite["execution_performance"] = [
        {
            "target": "request",
            "case_ids": ["request-context"],
            "metric": "latency",
            "statistic": "p95",
            "group": "normal",
            "max_seconds": 10.0,
            "environment": ENVIRONMENT,
            "data_size": DATA_SIZE,
        },
        {
            "target": "request",
            "case_ids": ["request-context", "request-exhausted"],
            "metric": "failure_rate",
            "max_rate": 0.0,
            "environment": ENVIRONMENT,
            "data_size": DATA_SIZE,
        },
        {
            "target": "report",
            "case_ids": ["report-start", "report-reentry"],
            "metric": "cost",
            "statistic": "mean",
            "max_cost": 0.1,
            "environment": ENVIRONMENT,
            "data_size": DATA_SIZE,
        },
        {
            "target": "request",
            "case_ids": ["request-context"],
            "metric": "repeat_spread",
            "measure": "model_calls",
            "max_spread": 0.0,
            "environment": ENVIRONMENT,
            "data_size": DATA_SIZE,
        },
    ]
    suite["execution_prices"] = {
        "version": "fictional-viewer-prices-v1",
        "currency": "USD",
        "models": {MODEL_NAME: {"input_per_million": 1.0, "output_per_million": 2.0}},
        "tools": {"query_data": {"per_call": 0.0}},
    }
    return suite_adapter.validate_python(suite)


def result_records(messages):
    """실제 모델 입력의 업무 기록에서 고정 응답에 필요한 참조만 읽는다."""
    text = messages[1].content
    if text.startswith("{"):
        return json.loads(text)["results"]
    return json.JSONDecoder().raw_decode(text.split("[작업 결과와 검증 이력]\n", 1)[1])[
        0
    ]


class FixtureModel:
    """SDK 응답 경계만 대체한다. 판단 품질을 측정하는 모델이 아니다."""

    def with_structured_output(self, schema, **_kwargs):
        async def invoke(messages, config):
            kind = schema["title"]
            if kind == "Interpretation":
                value = {
                    "request": {"goal": "제공된 범위와 한계를 설명한다."},
                    "reason": "[가상] 제공된 집계 자료의 범위만 설명한다.",
                }
            else:
                records = result_records(messages)
                report = any(item["decision"] == "report_input" for item in records)
                if kind == "Decision":
                    available = any(
                        item["decision"] == "call" and item["outcome"] == "success"
                        for item in records
                    )
                    value = {
                        "next": "compose" if not report or available else "act",
                        "reason": "[가상] 자료 유무에 맞춰 다음 작업을 선택한다.",
                    }
                elif kind == "Selection":
                    value = {
                        "name": "query_data",
                        "arguments_json": '{"target":"public.region_result"}',
                        "reason": "[가상] 한 행의 합성 자료를 조회한다.",
                    }
                elif kind == "Composition":
                    value = {
                        "content": "[가상] 행정동 월별 집계로 "
                        "개인 상태를 판정할 수 없습니다.",
                        "artifact_ids": [],
                        "status": "completed",
                        "reason": "제공 범위와 한계를 설명했다.",
                    }
                elif kind == "ReportSelection":
                    evidence = next(
                        item["id"] for item in records if item["decision"] == "call"
                    )
                    value = {
                        "views": [
                            {
                                "view_key": key,
                                "reason": "[가상] 화면 검토용 선정",
                                "evidence_ids": [evidence],
                            }
                            for key in (
                                "EmbedDetailV01",
                                "EmbedDetailV02",
                                "EmbedDetailV08",
                            )
                        ]
                    }
                elif kind == "ReportText":
                    view = records[-1]["action"]["arguments"]["view_key"]
                    value = {
                        "content": "[가상] 확보한 합성 점수의 관측 범위를 설명합니다."
                        if view
                        else "[가상] 집계의 범위를 확인합니다.\n"
                        "비교 가능한 기간을 확인합니다.\n"
                        "개인 상태 판정에 쓰지 않습니다."
                    }
                elif kind == "Verification":
                    value = {"accepted": True, "reason": "[가상] 검토 연결 확인용 승인"}
                else:
                    raise AssertionError(f"예정하지 않은 모델 출력: {kind}")
            return {
                "raw": AIMessage(
                    content=json.dumps(value, ensure_ascii=False),
                    response_metadata={"model_name": MODEL_NAME},
                    usage_metadata={
                        "input_tokens": 40,
                        "output_tokens": 20,
                        "total_tokens": 60,
                    },
                )
            }

        return RunnableLambda(invoke)


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
  assert.equal(result.batches.length, 3);
  assert.equal(Object.keys(assessments).length, 6);
  assert.equal(result.batches.reduce((sum, batch) => sum + batch.runs.length, 0), 10);
  for (const batch of result.batches) {
  const target = batch.runs[0].report.run.target;
  const cases = target === 'interpretation' ? 1 : 2;
  assert.equal(batch.runs.length, cases * 2);
  assert.ok(batch.runs.every(run => run.report.run.target === target));
  assert.equal(batch.assessments.length, 2);
  for (const run of batch.runs) {
    assert.equal(run.report.assessment.verdict, '미판정', '실행과 별도 채점 구분');
    assert.equal(run.report.assessment.executed, false);
    assert.ok(run.report.trace.spans.some(span => span.kind === 'execution'));
    assert.ok(run.report.trace.spans.every(span => span.kind !== 'database'));
    assert.ok(run.journal.length > 0);
  }
  for (const record of batch.assessments) {
    assert.ok(Object.hasOwn(assessments, record.path), 'Python 복원 결과 연결');
    assert.deepEqual(record.report, assessments[record.path],
      'Python·뷰어의 전체 채점 결과 복원 동등성');
    assert.deepEqual(record.report, originalAt(record.path), '채점 JSON 원문 보존');
    const score = record.report;
    assert.equal(score.schema_version, 'execution-evaluation-v1');
    assert.equal(score.runs.length, target === 'interpretation' ? 0 : 6);
    assert.equal(score.criteria.original_plan.repeat, 3);
    assert.equal(score.runs.filter(run => run.run_id === null).length,
      target === 'interpretation' ? 0 : 2);
    assert.ok(score.runs.filter(run => run.repetition === 3)
      .every(run => run.verdict === '미판정' && !run.complete && !run.started));
    assert.deepEqual(score.selection.functional_excluded.map(item => item.case_id),
      target === 'interpretation' ? ['interpretation-diagnostic'] : []);
    assert.deepEqual(score.summary.report_completion,
      target === 'report' ? {numerator: 2, denominator: 4, rate: 0.5} :
      {numerator: 0, denominator: 0, rate: null});
    const operations = score.summary.operational;
    assert.equal(operations.runs.length, cases * 2);
    assert.equal(operations.repetitions.length, cases);
    assert.ok(operations.repetitions.every(item =>
      item.missing_repetitions.includes(3)));
    assert.equal(operations.goals.length,
      target === 'request' ? 3 : target === 'report' ? 1 : 0);
    assert.equal(operations.verdict, '미판정', '누락 반복을 정상 측정으로 채우지 않음');
    const request = operations.runs.filter(run => run.case_id === 'request-context');
    assert.ok(request.every(run => run.model_calls === 3 && run.input_tokens === 120
      && run.output_tokens === 60 && run.cost !== null));
    const diagnostic = operations.runs.filter(run => run.target === 'interpretation');
    assert.equal(diagnostic.length, target === 'interpretation' ? 2 : 0);
    assert.ok(diagnostic.every(run => run.model_calls === 3));
    const reentry = operations.runs.filter(run => run.case_id === 'report-reentry');
    assert.ok(reentry.every(run =>
      run.tool_calls === 0 && run.budget_delta.tool_calls === 0),
      '재진입 전의 도구 사용량은 이번 실행에 재합산하지 않음');
    const changed = score.provenance.some(item => item.case_criteria === 'changed');
    assert.ok(score.runs.filter(run => run.case_id === 'request-context' && run.run_id)
      .every(run => run.verdict === (changed ? '실패' : '통과')));
    assert.ok(score.runs.filter(run => run.case_id === 'report-start' && run.run_id)
      .every(run => run.report_completeness === 'complete' && run.verdict === '통과'));
    assert.ok(score.runs.filter(run => run.case_id === 'report-reentry' && run.run_id)
      .every(run => run.report_completeness === 'partial' && run.verdict === '통과'));
  }
  }
  console.log('PASS: 역할·보고서별 3 묶음, 5 가상 사례 × 2회; 누락·재채점 6건; ' +
    '원본·기능/운영 분리·보고서 완성·재진입 사용량 연결.');
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
        originals = {}
        for batch in batches:
            # 시험용 계획만 확장한다. 없는 세 번째 반복은 미판정으로 남는다.
            batch_file = batch / "batch.json"
            plan = json.loads(batch_file.read_text(encoding="utf-8"))
            plan["plan"]["repeat"] = 3
            plan["planned_runs"] = len(plan["plan"]["case_ids"]) * 3
            batch_file.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            originals.update(
                {path: path.read_bytes() for path in batch.rglob("*") if path.is_file()}
            )
            score_executions(batch)
            assert all(
                path.read_bytes() == value for path, value in originals.items()
            ), "채점이 원본 증거를 변경함"
            # 기준 변경 이력은 해당 역할의 재평가에만 사용한다.
            if batch.parent.name == "request":
                suite_file = batch / "suite.json"
                current = json.loads(suite_file.read_text(encoding="utf-8"))
                current["cases"][0]["assessment"]["expected"]["execution_status"] = (
                    "partial"
                )
                suite_file.write_text(
                    json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                originals[suite_file] = suite_file.read_bytes()
            score_executions(batch)
    assert all(path.read_bytes() == value for path, value in originals.items()), (
        "재채점이 원본 증거를 변경함"
    )
    return [
        {
            "path": "execution-viewer-fixture/"
            + path.relative_to(root / "outputs").as_posix(),
            "text": path.read_text(encoding="utf-8"),
        }
        for path in sorted((root / "outputs").rglob("*"))
        if path.is_file()
    ]


def write_samples(files: list[dict[str, str]]) -> None:
    payload = {
        "label": "가상 모델·합성 자료 · 실제 품질 평가 아님 · 3회 계획 중 2회 실행",
        "files": files,
    }
    destination = Path(__file__).with_name("samples.js")
    destination.write_text(
        "// runner_integration.py --write-samples로 생성한 가상 화면 자료.\n"
        "(function (root) {\n  'use strict';\n  const payload = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n  root.ExecutionEvaluationSamples = function () { return payload; };\n"
        "})(typeof window === 'undefined' ? globalThis : window);\n",
        encoding="utf-8",
    )
    print(f"가상 화면 샘플 저장: {destination}")


async def verify(*, save_samples: bool = False) -> None:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("통합 검증에는 Node.js가 필요합니다.")
    parser = Path(__file__).with_name("data.js")
    with TemporaryDirectory(prefix="eumi-execution-viewer-") as temporary:
        files = await generate_files(Path(temporary))
        output = Path(temporary) / "outputs"
        assessments = {
            "execution-viewer-fixture/"
            + path.relative_to(output).as_posix(): load_assessment(path)
            for path in output.rglob("assessments/*.json")
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
            timeout=60,
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
