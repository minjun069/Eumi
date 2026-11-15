"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {parseFiles} = require("./data.js");

const time = "2026-11-12T00:00:00+00:00";
const json = (path, value) => ({path, text: JSON.stringify(value)});
const trace = () => ({version: "local-execution-trace-v1", scope: "로컬 추적", limitations: [], counts: {},
  coverage: Object.fromEntries(["model_attempts", "model_inputs", "http_requests", "http_responses", "sdk_responses", "model_errors", "unfinished_spans"].map(key => [key, 0])), spans: []});
const input = () => ({id: "case-1", unit: "node", target: "interpret", role: "interpretation", purpose: "목적 확인",
  initial: {}, assessment: {checks: ["N-F.1"], required: true}});
const report = () => ({schema_version: "evaluation-run-v1", run: {id: "run-1", suite_id: "suite-1", case_id: "case-1",
  repetition: 1, unit: "node", target: "interpret", role: "interpretation", dependencies: "real", evaluation_scope: "model_output",
  status: "returned", started_at: time, ended_at: time, elapsed_seconds: 0.1}, output: {model_call: "Interpretation", raw: "{}"},
  failure: null, trace: trace(), assessment: {verdict: "미판정", executed: false, reason: "원문만 수집", checks: ["N-F.1"]},
  fixtures: {calls: [], unexpected: [], unused: []}, journal_saved: false});
const entry = value => ({case_id: value.run.case_id, run_id: value.run.id, unit: value.run.unit, target: value.run.target,
  repetition: value.run.repetition, status: value.run.status, path: `runs/${value.run.id}/report.json`});
const batch = (runs = [report()]) => ({schema_version: "evaluation-batch-v1", id: "batch-1", suite_id: "suite-1",
  status: "returned", started_at: time, ended_at: time, planned_runs: runs.length, runs: runs.map(entry)});
const filters = () => ({case_ids: null, check_ids: null, row_ids: null});
const detail = () => ({id: "format", verdict: "통과", reason: "구조 일치", executed: true, evidence: ["runs/run-1/report.json#/trace/spans/0"], actual: null});
function score() {
  return {schema_version: "node-evaluation-v1", id: "score-1", batch_id: "batch-1", suite_id: "suite-1", assessed_at: time,
    status: "completed", method: "rules", criteria: {documents: {}, checks: {}, cases: [input()], effective_cases: [input()],
      plan: {case_ids: ["case-1"], repeat: 1}, node_performance: [], selection: filters()}, criteria_sha256: "criteria",
    evidence_sha256: {}, evaluator_sha256: {}, provenance: [], limitations: [], judge_trace: trace(),
    runs: [{run_id: "run-1", case_id: "case-1", repetition: 1, verdict: "통과", complete: true, reason: "판정 완료",
      node_ids: ["node-1"], unmatched_expectations: [], unmatched_checks: [], model_scope: [{case_id: "case-1", repetition: 1,
        node: "interpret", role: "interpretation", occurrence: 1, calls: [{id: "model-1", name: "Interpretation", index: 1, path: "runs/run-1/report.json#/trace/spans/0"}]}]}],
    assessments: [{node_id: "node-1", run_id: "run-1", case_id: "case-1", repetition: 1, node: "interpret", role: "interpretation",
      counted: true, verdict: "통과", complete: true, reason: "완료", checks: [{check: "N-F.1", axis: "형식 준수", method: "규칙 기반",
        executed: true, verdict: "통과", reason: "확인", details: [detail()], related_checks: [], calls: [
          {id: "model-1", name: "Interpretation", index: 1, row_id: "N-F.1/interpret", details: [detail()], format_contract: {equal: true}}]}]}],
    nodes: [], selection: {filters: filters(), decisions: [{case_id: "case-1", repetition: 1, check: "N-F.1", expectation_id: null,
      status: "selected", reason: "범위 일치", row_ids: ["N-F.1/interpret"]}], case_ids: ["case-1"],
      run_cases: [{case_id: "case-1", repetition: 1, assessment: input().assessment}]}};
}
function files(scored = score(), raw = report(), cases = [input()]) {
  return [json("batch/batch.json", batch([raw])), json("batch/suite.json", {schema_version: "evaluation-suite-v1", id: "suite-1", cases}),
    json("batch/runs/run-1/report.json", raw), json("batch/runs/run-1/case.json", cases[0]),
    json("batch/assessments/score.json", scored)];
}
const loadedScore = result => result.batches[0].assessments[0].report;

test("node scoring, calls, selection and source run remain unchanged", () => {
  const source = files();
  const parsed = parseFiles(source);
  assert.equal(parsed.batches.length, 1);
  assert.deepEqual(loadedScore(parsed), score());
  assert.deepEqual(parsed.batches[0].runs[0].report, report());
  assert.equal(parsed.batches[0].runs[0].report.assessment.verdict, "미판정");
  assert.deepEqual(parsed.batches[0].report, batch());
  assert.deepEqual(source, files());
  assert.deepEqual(parsed.issues.filter(item => item.severity === "error"), []);
});

test("renamed scoring files work without fabricating a run and preserve null versus absent", () => {
  const scored = score();
  scored.extra = {preserved: true};
  const result = parseFiles([json("renamed.json", scored)]);
  assert.equal(result.batches[0].source, "assessment");
  assert.deepEqual(result.batches[0].runs, []);
  assert.deepEqual(loadedScore(result), scored);
  const item = loadedScore(result).assessments[0].checks[0].calls[0].details[0];
  assert.equal(item.actual, null);
  assert.equal(Object.hasOwn(item, "expected"), false);
});

test("cancelled scoring and missing planned run remain unresolved", () => {
  const scored = score();
  scored.status = "cancelled";
  scored.assessments = [];
  Object.assign(scored.runs[0], {run_id: null, verdict: "미판정", complete: false, node_ids: [], model_scope: [], reason: "원본 없음"});
  const parsed = parseFiles([json("score.json", scored)]);
  assert.deepEqual(loadedScore(parsed), scored);
  assert.deepEqual(parsed.batches[0].runs, []);
});

test("node raw output is retained even when it is invalid JSON", () => {
  const raw = report();
  raw.output.raw = '{"broken":';
  const result = parseFiles([json("report.json", raw)]);
  assert.deepEqual(result.batches[0].runs[0].report.output, raw.output);
  const obsolete = report();
  obsolete.output = {goto: "act"};
  assert.equal(parseFiles([json("report.json", obsolete)]).batches.length, 0);
});

test("selection assessments remain visible with their explicit exclusion from node statistics", () => {
  const scored = score(), raw = report(), selected = input();
  Object.assign(selected, {unit: "selection", target: "act", role: "request"});
  Object.assign(raw.run, {unit: "selection", target: "act", role: "request"});
  raw.output = {model_call: "Selection", raw: "{}"};
  scored.criteria.cases = scored.criteria.effective_cases = [selected];
  Object.assign(scored.assessments[0], {node: "act", role: "request", counted: false});
  Object.assign(scored.runs[0].model_scope[0], {node: "act", role: "request"});
  const result = parseFiles(files(scored, raw, [selected]));
  assert.equal(loadedScore(result).assessments[0].counted, false);
  assert.deepEqual(loadedScore(result).nodes, []);
  assert.equal(result.batches[0].runs[0].report.run.unit, "selection");
});

test("latest re-evaluations sort by timestamp and duplicate identities are not chosen", () => {
  const old = score(), latest = score();
  latest.id = "score-2"; latest.assessed_at = "2026-11-12T01:00:00+00:00";
  const source = [json("old.json", old), json("new.json", latest)];
  assert.equal(parseFiles(source).batches[0].assessments[0].report.id, "score-2");
  const duplicated = parseFiles([...source, json("copy.json", latest)]);
  assert.equal(duplicated.batches[0].assessments.length, 1);
  assert.equal(duplicated.issues.filter(item => item.code === "duplicate-assessment").length, 2);
});

test("invalid scoring contracts are isolated from valid raw runs", () => {
  for (const mutate of [
    item => { item.schema_version = "node-evaluation-v2"; },
    item => { delete item.selection; },
    item => { item.assessments[0].role = "request"; },
    item => { item.assessments[0].checks[0].calls[0].details = {}; },
    item => { item.runs.push(structuredClone(item.runs[0])); },
    item => { item.assessments[0].run_id = "different-run"; },
  ]) {
    const scored = score(); mutate(scored);
    const result = parseFiles(files(scored));
    assert.equal(result.batches[0].runs.length, 1);
    assert.equal(result.batches[0].assessments.length, 0);
    assert.ok(result.issues.some(item => item.code === "invalid-artifact"));
  }
});

test("same run ID cannot connect a different repetition, suite or node role", () => {
  for (const mutate of [
    item => { item.suite_id = "another-suite"; },
    item => { item.runs[0].run_id = "run-1"; item.runs[0].repetition = 2; item.runs[0].model_scope = []; item.assessments[0].repetition = 2; },
    item => { item.criteria.cases[0].role = "request"; item.assessments[0].role = "request"; item.runs[0].model_scope[0].role = "request"; },
  ]) {
    const scored = score(); mutate(scored);
    const result = parseFiles(files(scored));
    assert.equal(result.batches[0].assessments.length, 0);
    assert.ok(result.issues.some(item => item.code === "assessment-mismatch"));
  }
});

test("mixed batches keep original metadata and exclude unrelated tool executions", () => {
  const node = report(), tool = report();
  Object.assign(tool.run, {id: "tool-run", case_id: "tool-case", unit: "tool", target: "query_data", role: null});
  tool.output = {data: []};
  const original = batch([node, tool]);
  const result = parseFiles([json("batch/batch.json", original), json("batch/runs/run-1/report.json", node),
    json("batch/runs/tool-run/report.json", tool), json("tool-score.json", {schema_version: "tool-evaluation-v1"})]);
  assert.equal(result.batches[0].runs.length, 1);
  assert.deepEqual(result.batches[0].report, original);
  assert.equal(result.batches[0].report.planned_runs, 2);
  assert.equal(parseFiles([json("report.json", tool)]).batches.length, 0);
});

test("agent source runs are included only when referenced by node scoring", () => {
  const raw = report(), agent = input(), scored = score();
  Object.assign(raw.run, {unit: "agent", target: "interpretation"}); raw.output = null;
  Object.assign(agent, {unit: "agent", target: "interpretation"}); delete agent.role;
  scored.criteria.cases = scored.criteria.effective_cases = [agent];
  assert.equal(parseFiles(files(scored, raw, [agent]).filter(file => !file.path.includes("assessments/"))).batches.length, 0);
  const result = parseFiles(files(scored, raw, [agent]));
  assert.equal(result.batches[0].runs.length, 1);
  assert.deepEqual(result.batches[0].runs[0].report, raw);
  assert.deepEqual(loadedScore(result), scored);
});

test("missing source file and unsafe path do not become failed evaluation results", () => {
  const rawBatch = batch();
  rawBatch.status = "cancelled";
  rawBatch.runs[0].status = "running";
  const result = parseFiles([json("batch/batch.json", rawBatch), json("../escape.json", score())]);
  assert.equal(result.batches[0].runs[0].report, null);
  assert.equal(result.batches[0].runs[0].availability.report, "missing");
  assert.ok(result.issues.some(item => item.code === "unsafe-path"));
  assert.equal(result.batches[0].runs[0].entry.status, "running");
});

test("duplicate paths and damaged JSON are isolated without selecting an arbitrary original", () => {
  const source = files();
  source.push(json("batch/runs/run-1/report.json", report()));
  const duplicate = parseFiles(source);
  assert.equal(duplicate.batches[0].runs[0].report, null);
  assert.ok(duplicate.issues.some(item => item.code === "duplicate-path"));
  const broken = files(); broken.find(file => file.path.endsWith("report.json")).text = "{broken";
  assert.equal(parseFiles(broken).batches[0].runs[0].availability.report, "invalid");
});

test("real runner-generated samples preserve all source files and node summaries", () => {
  require("./samples.js");
  const source = globalThis.EvaluationSamples.files;
  const parsed = parseFiles(source);
  assert.deepEqual(parsed.issues, []);
  assert.equal(parsed.batches.length, 1);
  const group = parsed.batches[0];
  assert.equal(group.runs.length, 8);
  assert.equal(group.assessments.length, 2);
  for (const record of group.assessments) {
    assert.deepEqual(record.report, JSON.parse(source.find(file => file.path === record.path).text));
    assert.equal(record.report.nodes.length, 3);
    assert.ok(record.report.assessments.some(item => !item.counted));
    assert.ok(record.report.nodes.every(item => item.operational.measurement_scope === "selected_model_calls"));
  }
  for (const run of group.runs) {
    assert.deepEqual(run.report, JSON.parse(source.find(file => file.path === run.path).text));
    assert.deepEqual(run.case, JSON.parse(source.find(file => file.path === run.path.replace("report.json", "case.json")).text));
    assert.equal(run.report.assessment.executed, false);
  }
});

test("invalid operational samples cannot be mistaken for zero measurements", () => {
  require("./samples.js");
  const source = globalThis.EvaluationSamples.files.find(file => {
    if (!file.path.endsWith(".json")) return false;
    return JSON.parse(file.text).schema_version === "node-evaluation-v1";
  });
  for (const mutate of [
    item => { item.nodes[0].operational.tokens.input_tokens.mean = "0"; },
    item => { item.nodes[0].operational.failure_rate.rate = 1.5; },
    item => { delete item.nodes[0].functional.verification; },
    item => { item.selection.decisions[0].status = "passed"; },
  ]) {
    const scored = JSON.parse(source.text); mutate(scored);
    const parsed = parseFiles([json("score.json", scored)]);
    assert.equal(parsed.batches.length, 0);
    assert.ok(parsed.issues.some(item => item.code === "invalid-artifact"));
  }
});

test("malformed operating goals are isolated while the valid scoring snapshot remains available", () => {
  const goal = {target: "interpret", role: "interpretation", metric: "response_time", case_ids: ["case-1"],
    group: "normal", statistic: "p95", max_seconds: 5, environment: "로컬 검사", data_size: "사례 1개"};
  const valid = score(); valid.criteria.node_performance = [goal];
  for (const malformed of [null, {}, {...goal, target: "unknown"}, {...goal, role: null},
    {...goal, metric: "unknown"}, {...goal, case_ids: null}, {...goal, case_ids: "case-1"},
    {...goal, case_ids: []}, {...goal, case_ids: [null]}, {...goal, case_ids: [""]},
    {...goal, group: "unknown"}, {...goal, statistic: "mean"}, {...goal, max_seconds: "5"},
    {...goal, max_seconds: null}, {...goal, max_seconds: -1}, {...goal, max_rate: 1.1},
    {...goal, environment: {}}, {...goal, data_size: null}]) {
    const invalid = structuredClone(valid); invalid.id = "invalid-score";
    invalid.criteria.node_performance = [malformed];
    const result = parseFiles([...files(valid), json("batch/assessments/invalid.json", invalid)]);
    assert.equal(result.batches[0].runs.length, 1);
    assert.equal(result.batches[0].assessments.length, 1);
    assert.deepEqual(loadedScore(result), valid);
    assert.ok(result.issues.some(item => item.code === "invalid-artifact" && item.path.endsWith("invalid.json")));
  }
});

test("incomplete operating goals retain omitted conditions for the scorer's undetermined result", () => {
  const scored = score();
  scored.criteria.node_performance = [
    {target: "interpret", role: "interpretation", metric: "response_time", case_ids: ["case-1"]},
    {target: "interpret", role: "interpretation", metric: "failure_rate", case_ids: ["case-1"], max_rate: 0},
  ];
  assert.deepEqual(loadedScore(parseFiles([json("score.json", scored)])), scored);
});


test("equal readable IDs in separate output directories retain their own assessments", () => {
  const source = files(), id = "노드평가_2026-11-12_실행01";
  const oldRoot = source.find(file => file.path.endsWith("/batch.json")).path.replace(/\/batch.json$/, "");
  const copy = parent => {
    let number = 0;
    return source.map(file => {
      const result = {...file, path: `${parent}/${id}${file.path.slice(oldRoot.length)}`};
      if (!file.path.endsWith(".json")) return result;
      const value = JSON.parse(file.text);
      if (value.schema_version === "evaluation-batch-v1") value.id = id;
      if (value.schema_version === "node-evaluation-v1") {
        value.batch_id = id;
        value.id = `${id}_채점${String(++number).padStart(2, "0")}`;
      }
      result.text = JSON.stringify(value);
      return result;
    });
  };
  const combined = [...copy("left"), ...copy("right")], result = parseFiles(combined);
  const expectedCount = source.filter(file => file.path.includes("/assessments/")).length;
  assert.equal(result.batches.length, 2);
  assert.ok(result.batches.every(batch => batch.assessments.length === expectedCount));
  assert.ok(result.batches.every(batch => batch.assessments.every(record => record.path.startsWith(batch.path.replace("batch.json", "")))));
  assert.equal(result.issues.filter(issue => ["duplicate-assessment", "assessment-mismatch"].includes(issue.code)).length, 0);
  const original = combined.find(file => file.path.startsWith("left/") && file.path.includes("/assessments/"));
  const duplicate = {...original, path: original.path.replace(/[^/]+$/, "copied-score.json")};
  const duplicated = parseFiles([...combined, duplicate]);
  assert.equal(duplicated.batches.find(batch => batch.path.startsWith("left/")).assessments.length, expectedCount - 1);
  assert.equal(duplicated.batches.find(batch => batch.path.startsWith("right/")).assessments.length, expectedCount);
  assert.equal(duplicated.issues.filter(issue => issue.code === "duplicate-assessment").length, 2);
  const loose = combined.filter(file => file.path.includes("/assessments/"));
  assert.equal(parseFiles(loose).batches.length, 0, "identical loose IDs without their batch evidence remain ambiguous");
});


