"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {parseFiles} = require("./data.js");
const {qualityScore, assessmentFiles} = require("../shared/assessment-fixtures.cjs");

const time = "2026-11-13T00:00:00+00:00";
const json = (path, value) => ({path, text: JSON.stringify(value)});
const trace = () => ({version: "local-execution-trace-v1", scope: "로컬 추적", limitations: [], counts: {},
  coverage: Object.fromEntries(["model_attempts", "model_inputs", "http_requests", "http_responses", "sdk_responses", "model_errors", "unfinished_spans"].map(key => [key, 0])), spans: []});
const input = () => ({id: "case-1", unit: "agent", target: "request", purpose: "실행 경계 확인",
  initial: {}, assessment: {checks: ["EX-1"], required: true,
    expected: {schema_version: "execution-expectations-v1", situation: "normal", entry: "initial"}}});
const report = () => ({schema_version: "evaluation-run-v1", run: {id: "run-1", suite_id: "suite-1", case_id: "case-1",
  repetition: 1, unit: "agent", target: "request", role: "request", dependencies: "real",
  status: "returned", started_at: time, ended_at: time, elapsed_seconds: 0.1}, output: null,
  state: {execution: {run_id: "run-1", status: "completed"}}, failure: null, trace: trace(),
  assessment: {verdict: "미판정", executed: false, reason: "실행 증거 수집", checks: ["EX-1"]},
  fixtures: {calls: [], unexpected: [], unused: []}, journal_saved: false});
const entry = value => ({case_id: value.run.case_id, run_id: value.run.id, unit: value.run.unit, target: value.run.target,
  repetition: value.run.repetition, status: value.run.status, path: "runs/" + value.run.id + "/report.json"});
const batch = (runs = [report()]) => ({schema_version: "evaluation-batch-v1", id: "batch-1", suite_id: "suite-1",
  status: "returned", started_at: time, ended_at: time, planned_runs: runs.length, runs: runs.map(entry),
  plan: {case_ids: runs.map(item => item.run.case_id), repeat: 1}});
const ratio = () => ({numerator: 0, denominator: 0, rate: null});
const stats = () => ({sample_count: 0, missing_count: 0, mean: null, median: null, p95: null, minimum: null, maximum: null});
const metrics = ["elapsed_seconds", "model_calls", "tool_calls", "agent_calls", "node_entries", "retries", "input_tokens", "output_tokens", "cost"];
const measurements = () => Object.fromEntries(metrics.map(key => [key, stats()]));
const measure = () => ({case_id: "case-1", run_id: "run-1", repetition: 1, unit: "agent", target: "request",
  role: "request", dependencies: "real", situation: "normal", entry: "initial", environment: null, data_size: null,
  dong_code: null, month: null, started: true, ended: true, returned: true, evidence_complete: true,
  outcome: "completed", returned_status: "completed", elapsed_seconds: 0, observed_at: null, timing_scope: "execution",
  model_calls: 0, tool_calls: 0, agent_calls: 0, node_entries: 1, retries: 0, budget_delta: {steps: 1},
  input_tokens: null, output_tokens: 0, observed_tokens: {input_tokens: null, output_tokens: 0},
  missing_token_calls: {input_tokens: 1, output_tokens: 0}, observed_calls: {model: 0, tool: 0, agent: 0, node: 1},
  model_cost: null, tool_cost: 0, cost: null, currency: null, failed_calls: {}, reasons: ["단가 미제공"]});
function score() {
  const measured = measure();
  return {schema_version: "execution-evaluation-v1", id: "score-1", batch_id: "batch-1", suite_id: "suite-1", assessed_at: time,
    method: "rules", criteria: {documents: {}, cases: [input()], original_plan: {case_ids: ["case-1"], repeat: 1},
      execution_performance: [], execution_prices: null}, criteria_sha256: "criteria",
    evidence_sha256: {}, evaluator_sha256: {}, provenance: [], limitations: ["합성 자료"],
    selection: {case_ids: [], check_ids: [], excluded: [], functional_excluded: [], selected_case_ids: ["case-1"]},
    runs: [{run_id: "run-1", case_id: "case-1", repetition: 1, verdict: "통과", complete: true, started: true,
      report_completeness: null, checks: [{check: "EX-1", verdict: "통과", complete: true, executed: true, reason: "경로 일치",
        details: [{target: "node_path", verdict: "통과", executed: true, reason: "일치", evidence: ["trace.spans[id=node-1]"]}]}]}],
    summary: {functional: {verdict: "통과", complete: true, checks: [{check: "EX-1", numerator: 1, denominator: 1, rate: 1,
      passed: 1, failed: 0, undetermined: 0, unexecuted: 0, not_applicable: 0, reasons: []}],
      cases: {numerator: 1, denominator: 1, rate: 1, passed: 1, failed: 0, undetermined: 0, excluded: 0, unspecified_required: 0,
        items: [{case_id: "case-1", required: true, verdict: "통과", complete: true, planned_repetitions: 1, recorded_repetitions: 1,
          missing_repetitions: [], incomplete_repetitions: [], reasons: []}]},
      verification: {required_cases: 1, completed_cases: 1, incomplete_cases: 0, missing_repetitions: 0}},
      report_completion: ratio(), operational: {measurement_scope: "execution", verdict: "미판정", complete: false,
        groups: [{conditions: Object.fromEntries(["target", "role", "dependencies", "situation", "entry", "environment", "data_size"].map(key => [key, measured[key]])),
          started: 1, ended: 1, unfinished: 0, outcomes: {completed: {numerator: 1, denominator: 1, rate: 1}},
          failure_rate: {...ratio(), unclassified_count: 0, evaluation_failure_count: 0, unfinished_count: 0},
          measurements: measurements(), elapsed_by_outcome: {completed: stats()}, report_completion: ratio(), runs: [structuredClone(measured)]}],
        repetitions: [{case_id: "case-1", planned: 1, started: 1, ended: 1, unfinished: 0, missing_repetitions: [],
          measurements: measurements(), runs: [structuredClone(measured)]}], goals: [], runs: [measured],
        unfinished_usage: [], reasons: ["운영 목표 미지정"]}}};
}
function files(scored = score(), raw = report(), cases = [input()]) {
  return [json("batch/batch.json", batch([raw])), json("batch/suite.json", {schema_version: "evaluation-suite-v1", id: "suite-1", cases}),
    json("batch/runs/run-1/report.json", raw), json("batch/runs/run-1/case.json", cases[0]),
    json("batch/assessments/score.json", scored)];
}
const loadedScore = result => result.batches[0].assessments[0].report;
const replaceMeasured = (scored, mutate) => {
  const ops = scored.summary.operational;
  [ops.runs, ...ops.groups.map(item => item.runs), ...ops.repetitions.map(item => item.runs), ops.unfinished_usage]
    .forEach(items => items.forEach(mutate));
};

test("saved functional results, execution metrics and raw state remain unchanged", () => {
  const source = files(), parsed = parseFiles(source);
  assert.equal(parsed.batches.length, 1);
  assert.deepEqual(loadedScore(parsed), score());
  assert.deepEqual(parsed.batches[0].runs[0].report, report());
  assert.equal(parsed.batches[0].runs[0].report.assessment.verdict, "미판정");
  assert.deepEqual(source, files());
  assert.deepEqual(parsed.issues.filter(item => item.severity === "error"), []);
});

test("output quality and execution assessments coexist without merging verdicts", () => {
  const source = files(), quality = qualityScore(score());
  source.push(json("batch/assessments/quality.json", quality));
  const original = structuredClone(source), parsed = parseFiles(source);
  assert.equal(parsed.issues.filter(item => item.severity === "error").length, 0);
  assert.deepEqual(parsed.batches[0].assessments.find(item => item.report.schema_version === "output-evaluation-v1").report, quality);
  assert.equal(parsed.batches[0].assessments.find(item => item.report.schema_version === "execution-evaluation-v1").report.summary.functional.verdict, "통과");
  assert.equal(quality.summary.verdict, "실패");
  assert.deepEqual(source, original);
});


test("different adopted calls from the same original node retain their separate identities after JSON loading", () => {
  const quality = qualityScore(score()), second = structuredClone(quality.assessments[0]);
  second.id = "quality-assessment-2";
  second.call_id = "original-call-2";
  second.call_index = 5;
  for (const result of second.checks) for (const call of result.calls) { call.id = second.call_id; call.index = second.call_index; }
  quality.assessments.push(second);
  const component = structuredClone(quality.runs[0].components[0]);
  component.id = "response-2"; component.assessment_ids = [second.id];
  quality.runs[0].components.push(component);
  quality.summary.checks[0].failed = quality.summary.checks[0].denominator = 2;
  const parsed = parseFiles([...files(), ...assessmentFiles(quality, "batch/assessments/quality")]);
  assert.deepEqual(parsed.issues.filter(item => item.severity === "error"), []);
  const restored = parsed.batches[0].assessments.find(item => item.report.schema_version === "output-evaluation-v1").report;
  assert.deepEqual(restored, quality);
  assert.deepEqual(restored.assessments.map(item => [item.node_id, item.call_id, item.call_index]), [
    ["original-compose", "original-call", 3], ["original-compose", "original-call-2", 5],
  ]);
});

for (const corruption of ["reference", "call", "run", "summary"]) test("quality rejects mismatched " + corruption, () => {
  const quality = qualityScore(score());
  if (corruption === "reference") quality.runs[0].components[0].assessment_ids = ["absent"];
  if (corruption === "call") quality.assessments[0].checks[0].calls[0].index = 99;
  if (corruption === "run") quality.runs[0].repetition = 10;
  if (corruption === "summary") quality.summary.rate = 2;
  const parsed = parseFiles([...files(), json("batch/assessments/quality.json", quality)]);
  assert.ok(parsed.issues.some(item => item.severity === "error"));
  assert.equal(parsed.batches[0].assessments.length, 1);
});

test("renamed standalone assessments preserve unknown fields, nulls and measured zero", () => {
  const scored = score(); scored.extra = {preserved: true};
  const result = parseFiles([json("renamed.json", scored)]);
  assert.equal(result.batches[0].source, "assessment");
  assert.deepEqual(result.batches[0].runs, []);
  assert.deepEqual(loadedScore(result), scored);
  const measured = loadedScore(result).summary.operational.runs[0];
  assert.equal(measured.input_tokens, null); assert.equal(measured.output_tokens, 0);
  assert.equal(Object.hasOwn(measured, "unknown"), false);
});

test("operating groups accept current and legacy conditions while preserving each run's region and month", () => {
  for (const legacy of [false, true]) {
    const scored = score();
    replaceMeasured(scored, measured => Object.assign(measured, {dong_code: "1111051500", month: "2026-10"}));
    if (legacy) Object.assign(scored.summary.operational.groups[0].conditions, {dong_code: "1111051500", month: "2026-10"});
    const original = structuredClone(scored), result = parseFiles([json("score.json", scored)]);
    assert.deepEqual(result.issues.filter(item => item.severity === "error"), []);
    assert.deepEqual(loadedScore(result), original);
    const group = loadedScore(result).summary.operational.groups[0];
    assert.equal(Object.hasOwn(group.conditions, "dong_code"), legacy);
    assert.equal(Object.hasOwn(group.conditions, "month"), legacy);
    assert.equal(group.runs[0].dong_code, "1111051500");
    assert.equal(group.runs[0].month, "2026-10");
  }
});

test("missing scheduled runs remain unresolved without fabricated execution files", () => {
  const scored = score();
  Object.assign(scored.runs[0], {run_id: null, verdict: "미판정", complete: false, started: false, checks: []});
  scored.summary.operational.runs = []; scored.summary.operational.groups = [];
  scored.summary.operational.repetitions[0].runs = [];
  scored.summary.operational.repetitions[0].missing_repetitions = [1];
  const parsed = parseFiles([json("score.json", scored)]);
  assert.deepEqual(loadedScore(parsed), scored); assert.deepEqual(parsed.batches[0].runs, []);
});

test("all six agent roles and the report workflow remain readable without scoring", () => {
  for (const target of ["request", "interpretation", "visualization", "report_selection", "report_description", "report_insight", "report"]) {
    const raw = report();
    Object.assign(raw.run, {unit: target === "report" ? "workflow" : "agent", target, role: target === "report" ? null : target});
    const parsed = parseFiles([json("report.json", raw)]);
    assert.equal(parsed.batches.length, 1, target); assert.deepEqual(parsed.batches[0].runs[0].report, raw);
  }
});

test("role-only diagnostics retain operational evidence and explicit functional exclusion", () => {
  const scored = score(), raw = report(), selected = input();
  Object.assign(raw.run, {target: "interpretation", role: "interpretation"});
  selected.target = "interpretation"; selected.assessment = {};
  scored.criteria.cases = [selected]; scored.runs = [];
  scored.summary.functional.checks = []; scored.summary.functional.cases.items = [];
  scored.selection.functional_excluded = [{case_id: selected.id, reason: "역할 단독은 운영 진단"}];
  replaceMeasured(scored, item => {item.target = "interpretation"; item.role = "interpretation";});
  scored.summary.operational.groups[0].conditions.target = "interpretation";
  scored.summary.operational.groups[0].conditions.role = "interpretation";
  assert.deepEqual(loadedScore(parseFiles(files(scored, raw, [selected]))), scored);
});

test("report workflow completeness is separate from functional verdict", () => {
  const scored = score(), raw = report(), selected = input();
  Object.assign(raw.run, {unit: "workflow", target: "report", role: null});
  Object.assign(selected, {unit: "workflow", target: "report"});
  scored.criteria.cases = [selected]; scored.runs[0].report_completeness = "partial";
  scored.summary.report_completion = {numerator: 0, denominator: 1, rate: 0};
  replaceMeasured(scored, item => Object.assign(item, {unit: "workflow", target: "report", role: null, outcome: "partial"}));
  assert.deepEqual(loadedScore(parseFiles(files(scored, raw, [selected]))), scored);
});

test("re-evaluations sort by timestamp while duplicate assessment IDs remain unlinked", () => {
  const old = score(), latest = score();
  latest.id = "score-2"; latest.assessed_at = "2026-11-13T01:00:00+00:00";
  const source = [json("old.json", old), json("new.json", latest)];
  assert.equal(parseFiles(source).batches[0].assessments[0].report.id, "score-2");
  const duplicated = parseFiles([...source, json("copy.json", latest)]);
  assert.equal(duplicated.batches[0].assessments.length, 1);
  assert.equal(duplicated.issues.filter(item => item.code === "duplicate-assessment").length, 2);
});

test("invalid execution evaluation contracts are isolated from valid raw runs", () => {
  for (const mutate of [
    item => { item.schema_version = "execution-evaluation-v2"; },
    item => { delete item.selection; },
    item => { item.summary.operational.measurement_scope = "selected_model_calls"; },
    item => { item.runs[0].checks[0].details = {}; },
    item => { item.runs.push(structuredClone(item.runs[0])); },
    item => { item.runs[0].run_id = "different-run"; },
    item => { item.summary.operational.groups[0].measurements.input_tokens.mean = "0"; },
    item => { item.summary.operational.groups[0].conditions.dong_code = 1111051500; },
    item => { item.summary.operational.groups[0].conditions.month = []; },
    item => { delete item.summary.operational.runs[0].dong_code; },
    item => { delete item.summary.operational.runs[0].month; },
    item => { item.summary.functional.cases.rate = 1.5; },
    item => { item.criteria.execution_prices = {currency: "USD"}; },
  ]) {
    const scored = score(); mutate(scored);
    const result = parseFiles(files(scored));
    assert.equal(result.batches[0].runs.length, 1); assert.equal(result.batches[0].assessments.length, 0);
    assert.ok(result.issues.some(item => item.code === "invalid-artifact"));
  }
});

test("same run ID cannot join a different repetition, suite, target or dependency mode", () => {
  for (const mutate of [
    item => { item.suite_id = "another-suite"; },
    item => { item.criteria.original_plan.repeat = 2; item.runs[0].repetition = 2; replaceMeasured(item, measured => {measured.repetition = 2;}); },
    item => { replaceMeasured(item, measured => {measured.dependencies = "stub";}); },
    item => { item.criteria.cases[0].target = "visualization"; item.runs = [];
      replaceMeasured(item, measured => {measured.target = "visualization"; measured.role = "visualization";}); },
  ]) {
    const scored = score(); mutate(scored);
    const result = parseFiles(files(scored));
    assert.equal(result.batches[0].assessments.length, 0);
    assert.ok(result.issues.some(item => item.code === "assessment-mismatch"));
  }
});

test("mixed batches preserve original metadata and exclude tools, nodes and their assessments", () => {
  const agent = report(), node = report();
  Object.assign(node.run, {id: "node-run", case_id: "node-case", unit: "node", target: "interpret", role: "interpretation"});
  delete node.state; node.output = {model_call: "Interpretation", raw: "{}"};
  const original = batch([agent, node]);
  const result = parseFiles([json("batch/batch.json", original), json("batch/runs/run-1/report.json", agent),
    json("batch/runs/node-run/report.json", node), json("node-score.json", {schema_version: "node-evaluation-v1"}),
    json("tool-score.json", {schema_version: "tool-evaluation-v1"})]);
  assert.equal(result.batches[0].runs.length, 1); assert.deepEqual(result.batches[0].report, original);
  assert.equal(result.batches[0].report.planned_runs, 2);
  assert.equal(parseFiles([json("report.json", node)]).batches.length, 0);
});

test("missing source files and unsafe paths do not become failed evaluation results", () => {
  const rawBatch = batch();
  rawBatch.status = "cancelled"; rawBatch.runs[0].status = "running";
  const result = parseFiles([json("batch/batch.json", rawBatch), json("../escape.json", score())]);
  assert.equal(result.batches[0].runs[0].report, null);
  assert.equal(result.batches[0].runs[0].availability.report, "missing");
  assert.ok(result.issues.some(item => item.code === "unsafe-path"));
  assert.equal(result.batches[0].runs[0].entry.status, "running");
});

test("duplicate paths and damaged JSON are isolated without choosing an arbitrary source", () => {
  const source = files();
  source.push(json("batch/runs/run-1/report.json", report()));
  const duplicate = parseFiles(source);
  assert.equal(duplicate.batches[0].runs[0].report, null);
  assert.ok(duplicate.issues.some(item => item.code === "duplicate-path"));
  const broken = files(); broken.find(file => file.path.endsWith("report.json")).text = "{broken";
  assert.equal(parseFiles(broken).batches[0].runs[0].availability.report, "invalid");
});

test("journal parsing preserves complete lines and reports a truncated line", () => {
  const source = files();
  const span = {id: "node-1", parent_id: null, sequence: 1, kind: "node", name: "act", started_at: time,
    ended_at: null, elapsed_seconds: null, status: "running", input: {state: {}}};
  source.push({path: "batch/runs/run-1/trace.jsonl", text: JSON.stringify({event: "start", span}) + '\n{"event":'});
  const parsed = parseFiles(source);
  assert.equal(parsed.batches[0].runs[0].availability.journal, "partial");
  assert.deepEqual(parsed.batches[0].runs[0].journal, [{event: "start", span}]);
  assert.ok(parsed.issues.some(item => item.code === "invalid-journal-line" && item.line === 2));
});

test("incomplete operating goals preserve missing conditions for the scorer's unresolved result", () => {
  const scored = score();
  scored.criteria.execution_performance = [
    {target: "request", metric: "latency", case_ids: ["case-1"]},
    {target: "request", metric: "failure_rate", case_ids: ["case-1"], max_rate: 0},
  ];
  assert.deepEqual(loadedScore(parseFiles([json("score.json", scored)])), scored);
});

test("malformed operating goals do not displace valid scoring snapshots", () => {
  const goal = {target: "request", metric: "latency", case_ids: ["case-1"],
    group: "normal", statistic: "p95", max_seconds: 5, environment: "로컬 검사", data_size: "사례 1개"};
  const valid = score(); valid.criteria.execution_performance = [goal];
  for (const malformed of [null, {}, {...goal, target: "unknown"}, {...goal, metric: "unknown"},
    {...goal, case_ids: null}, {...goal, case_ids: []}, {...goal, case_ids: [null]}, {...goal, case_ids: [""]},
    {...goal, group: "unknown"}, {...goal, statistic: "sum"}, {...goal, max_seconds: "5"},
    {...goal, max_seconds: null}, {...goal, max_seconds: -1}, {...goal, max_rate: 1.1},
    {...goal, environment: {}}, {...goal, data_size: null}]) {
    const invalid = structuredClone(valid); invalid.id = "invalid-score"; invalid.criteria.execution_performance = [malformed];
    const result = parseFiles([...files(valid), json("batch/assessments/invalid.json", invalid)]);
    assert.equal(result.batches[0].assessments.length, 1); assert.deepEqual(loadedScore(result), valid);
    assert.ok(result.issues.some(item => item.code === "invalid-artifact" && item.path.endsWith("invalid.json")));
  }
});

test("unfinished recovered measurements retain observed usage and evidence limits", () => {
  const scored = score();
  replaceMeasured(scored, item => Object.assign(item, {ended: false, returned: false, evidence_complete: false,
    outcome: "unfinished", elapsed_seconds: null, model_calls: null, input_tokens: null, output_tokens: null,
    role: null, dependencies: "unknown", observed_tokens: {input_tokens: 17, output_tokens: null},
    reasons: ["결과 보고서 없이 누적 추적에서 확인"]}));
  scored.summary.operational.unfinished_usage = [structuredClone(scored.summary.operational.runs[0])];
  assert.deepEqual(loadedScore(parseFiles([json("score.json", scored)])), scored);
});


test("equal readable IDs in separate output directories retain their own assessments", () => {
  const source = files(), id = "실행평가_2026-11-12_실행01";
  const oldRoot = source.find(file => file.path.endsWith("/batch.json")).path.replace(/\/batch.json$/, "");
  const copy = parent => {
    let number = 0;
    return source.map(file => {
      const result = {...file, path: `${parent}/${id}${file.path.slice(oldRoot.length)}`};
      if (!file.path.endsWith(".json")) return result;
      const value = JSON.parse(file.text);
      if (value.schema_version === "evaluation-batch-v1") value.id = id;
      if (value.schema_version === "execution-evaluation-v1") {
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


