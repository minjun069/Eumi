"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {forNode, forAll} = require("./aggregate-metrics.js");
const clone = value => JSON.parse(JSON.stringify(value));
const time = "2026-11-14T00:00:00Z";
function stats(values = [], missing = 0, unfinished = 0) {
  const sorted = [...values].sort((a, b) => a - b), length = sorted.length;
  return {sample_count: length, missing_count: missing, unfinished_count: unfinished,
    mean: length ? sorted.reduce((a, b) => a + b) / length : null,
    median: length ? (sorted[Math.floor((length - 1) / 2)] + sorted[Math.floor(length / 2)]) / 2 : null,
    p95: length ? sorted[Math.ceil(.95 * length) - 1] : null};
}
function item(case_id, verdict = "통과", complete = true, required = true) {
  return {case_id, verdict, complete, required, planned_repetitions: 1, recorded_repetitions: 1,
    missing_repetitions: [], incomplete_repetitions: [], excluded_repetitions: [], missing_expectations: [], missing_checks: [], reason: ""};
}
function check(checkId, axis = "형식 준수", method = "규칙 기반", passed = 1, failed = 0, undetermined = 0) {
  return {check: checkId, axis, method, passed, failed, undetermined, not_applicable: 0, unexecuted: 0, skipped_after_failure: 0,
    numerator: passed, denominator: passed + failed, rate: passed + failed ? passed / (passed + failed) : null};
}
function node(role, items = [], values = []) {
  const measured = values.filter(value => !value.unfinished);
  const known = measured.filter(value => typeof value.failure === "boolean");
  const pending = values.length - measured.length;
  const failed = known.filter(value => value.failure).length;
  const metric = property => stats(measured.map(value => value[property]).filter(value => value != null), measured.filter(value => value[property] == null).length, pending);
  return {node: "act", role, runs: values.length, functional: {verdict: "미판정", complete: false,
    cases: {items, passed: 0, failed: 0, undetermined: 0, excluded: 0, unspecified_required: items.length, numerator: 0, denominator: 0, rate: null},
    verification: {required_cases: 0, completed_cases: 0, incomplete_cases: 0, missing_repetitions: 0}, checks: [], details: []},
    operational: {measurement_scope: "selected_model_calls", verdict: "통과", complete: true,
      failure_rate: {numerator: failed, denominator: known.length, rate: known.length ? failed / known.length : null, missing_count: measured.length - known.length, unfinished_count: pending},
      response_time: {normal: stats(known.filter(value => !value.failure).map(value => value.elapsed).filter(value => value != null), known.filter(value => !value.failure && value.elapsed == null).length),
        error: stats(known.filter(value => value.failure).map(value => value.elapsed).filter(value => value != null), known.filter(value => value.failure && value.elapsed == null).length), unclassified_count: measured.length - known.length, unfinished_count: pending},
      tokens: {input_tokens: metric("input"), output_tokens: metric("output")}, model_calls: metric("calls"), technical_retries: metric("retries"),
      technical_retries_by_kind: {model: metric("retries"), tool: stats([], measured.length, pending), agent: stats([], measured.length, pending)}, unfinished_usage: []},
    performance: [], complete: false, verdict: "미판정", verdict_scope: "기능과 지정된 운영 목표", conflicting_assessments: [], conflicting_evidence: []};
}
function sample(index, role, elapsed = index, options = {}) {
  const caseId = options.caseId ?? `case-${index}`, runId = `run-${role}-${index}`, nodeId = `node-${index}`, modelId = `model-${index}`;
  const value = {elapsed, input: elapsed * 10, output: elapsed, calls: 1, retries: 0, failure: false, ...options};
  const raw = {run: {id: runId, case_id: caseId, repetition: 1, unit: "node", target: "act", role}, trace: {spans: [
    {id: nodeId, parent_id: null, kind: "node", name: "act", ended_at: time, elapsed_seconds: elapsed + 100, input: {role, evaluation_scope: "model_output", state: {results: []}}, output: {applied_update: {results: []}}},
    {id: modelId, parent_id: nodeId, kind: "model", name: "Selection", ended_at: value.unfinished ? null : time, elapsed_seconds: value.elapsed,
      input: {messages: []}, output: {sdk_response: {text: value.failure ? null : "{}", usage_metadata: {input_tokens: value.input, output_tokens: value.output}}}, error: value.failure ? {type: "ConnectionError"} : null}
  ]}};
  const scored = {run_id: runId, case_id: caseId, repetition: 1, node_id: nodeId, node: "act", role, counted: true, verdict: "통과", complete: true,
    checks: [{check: "N-F.1", axis: "형식 준수", method: "규칙 기반", executed: true, verdict: "통과", details: [], calls: [{id: modelId, name: "Selection", index: 1}]}]};
  return {value, raw, scored};
}
function fixture(samples) {
  const roles = [...new Set(samples.map(value => value.raw.run.role))];
  const nodes = roles.map(role => {
    const matches = samples.filter(value => value.raw.run.role === role);
    return node(role, matches.map(value => item(value.raw.run.case_id)), matches.map(value => value.value));
  });
  const reports = samples.map(value => value.raw);
  const evaluation = {status: "completed", nodes, assessments: samples.map(value => value.scored), runs: samples.map(value => ({run_id: value.scored.run_id, case_id: value.scored.case_id, repetition: 1}))};
  return {nodes, reports, evaluation};
}
function deepFreeze(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    Object.values(value).forEach(deepFreeze);
  }
  return value;
}

test("every required, optional and unspecified case, including undetermined, contributes to the denominator", () => {
  const source = node("request", [item("required"), item("optional", "통과", true, false), item("unspecified", "미판정", false, null)]);
  source.functional.cases.items[2].missing_repetitions = [2, 2];
  const result = forNode(source);
  assert.equal(result.functional.cases.rate, 2 / 3);
  assert.equal(result.functional.cases.denominator, 3);
  assert.equal(result.functional.cases.numerator, 2);
  assert.equal(result.functional.verdict, "미판정");
  assert.deepEqual(result.functional.verification, {total_cases: 3, completed_cases: 2, incomplete_cases: 1, missing_repetitions: 1});
  assert.deepEqual(result.functional.cases.items.map(value => value.required), [true, false, null]);
  assert.strictEqual(result.operational, source.operational);
});

test("failure and completion remain independent and optional-only completed passing cases pass", () => {
  const failed = forNode(node("request", [item("a", "실패", false, false), item("b", "통과", true, null)]));
  assert.equal(failed.functional.verdict, "실패");
  assert.equal(failed.functional.complete, false);
  assert.equal(failed.functional.cases.rate, .5);
  const passed = forNode(node("request", [item("a", "통과", true, false), item("b", "통과", true, null)]));
  assert.equal(passed.functional.verdict, "통과");
  assert.equal(passed.functional.complete, true);
});

test("case deduplication uses node, role and case ID; repeated summaries do not inflate totals", () => {
  const one = item("shared"), first = node("request", [one, clone(one)]), second = node("interpretation", [item("shared", "미판정", false)]);
  const result = forAll([first, clone(first), second], [], null);
  assert.equal(result.functional.cases.denominator, 2);
  assert.equal(result.functional.cases.rate, .5);
  assert.deepEqual(result.functional.cases.items.map(value => [value.case_id, value.role]), [["shared", "request"], ["shared", "interpretation"]]);
  assert.throws(() => forAll([first, {...first, runs: 2}], [], null), /서로 다릅니다/);
});

test("conflicting case duplicate remains incomplete and preserves a known failure", () => {
  const result = forNode(node("request", [item("same"), item("same", "실패", false)]));
  assert.equal(result.functional.cases.denominator, 1);
  assert.equal(result.functional.verdict, "실패");
  assert.equal(result.functional.complete, false);
});

test("check and detail rollups preserve their own decided-result denominator and axis/method identities", () => {
  const a = node("request"), b = node("interpretation"), c = node("visualization");
  a.functional.checks = [check("N-F.1", "형식 준수", "규칙 기반", 2, 1, 4)];
  b.functional.checks = [check("N-F.1", "형식 준수", "규칙 기반", 1, 1, 3)];
  c.functional.checks = [check("N-F.1", "내용 정확성", "LLM 기반", 1)];
  for (const value of [a, b, c]) value.functional.details = value.functional.checks.map(({axis, method, ...row}) => ({...row, id: "shape"}));
  const result = forAll([a, b, c], [], null).functional;
  assert.equal(result.checks.length, 2);
  assert.equal(result.checks[0].denominator, 5);
  assert.equal(result.checks[0].rate, 3 / 5);
  assert.equal(result.checks[0].undetermined, 7);
  assert.equal(result.details.length, 2);
  assert.equal(result.details[0].rate, 3 / 5);
  assert.equal(result.details[1].method, "LLM 기반");
});

test("pooled observations compute weighted mean and pooled median/p95 instead of averaging role statistics", () => {
  const f = fixture([sample(1, "request", 1), sample(2, "request", 2), sample(3, "interpretation", 30)]);
  const result = forAll(f.nodes, f.reports, f.evaluation).operational;
  assert.deepEqual(result.response_time.normal, {sample_count: 3, missing_count: 0, unfinished_count: 0, raw_missing_count: 0, mean: 11, median: 2, p95: 30});
  assert.equal(result.tokens.input_tokens.mean, 110);
  assert.equal(result.tokens.input_tokens.median, 20);
  assert.equal(result.tokens.input_tokens.p95, 300);
  assert.equal(result.model_calls.mean, 1);
  assert.equal(result.technical_retries.mean, 0);
  assert.equal(result.technical_retries_by_kind.model.mean, 0);
  assert.equal(result.technical_retries_by_kind.tool.mean, null);
  assert.equal(result.technical_retries_by_kind.tool.missing_count, 3);
  assert.deepEqual(result.source_issues, []);
});

test("failure totals and operational verdicts use saved role values; goals retain role provenance", () => {
  const f = fixture([sample(1, "request", 2), sample(2, "interpretation", 4, {failure: true})]);
  f.nodes[0].operational.verdict = "미판정";
  f.nodes[0].operational.complete = false;
  f.nodes[1].operational.verdict = "실패";
  f.nodes[1].performance = [{metric: "failure_rate", value_rate: 1, max_rate: .1, verdict: "실패", complete: true, case_ids: ["case-2"]}];
  const result = forAll(f.nodes, f.reports, f.evaluation);
  assert.equal(result.operational.verdict, "실패");
  assert.equal(result.operational.complete, false);
  assert.deepEqual(result.operational.failure_rate, {numerator: 1, denominator: 2, rate: .5, missing_count: 0, unfinished_count: 0});
  assert.equal(result.operational.response_time.normal.mean, 2);
  assert.equal(result.operational.response_time.error.mean, 4);
  assert.deepEqual(result.performance[0], {...f.nodes[1].performance[0], node: "act", role: "interpretation"});
});

test("missing originals preserve stored failure counts and explicitly mark incomplete pooled samples", () => {
  const f = fixture([sample(1, "request", 1), sample(2, "interpretation", 30)]);
  const some = forAll(f.nodes, f.reports.slice(0, 1), f.evaluation).operational;
  assert.equal(some.failure_rate.denominator, 2);
  assert.equal(some.failure_rate.rate, 0);
  assert.equal(some.response_time.normal.sample_count, 1);
  assert.equal(some.response_time.normal.missing_count, 1);
  assert.equal(some.response_time.normal.raw_missing_count, 1);
  assert.equal(some.response_time.normal.mean, 1);
  assert.match(some.source_issues[0], /확인된 측정값만/);
  const none = forAll(f.nodes, [], f.evaluation).operational;
  assert.equal(none.tokens.input_tokens.sample_count, 0);
  assert.equal(none.tokens.input_tokens.missing_count, 2);
  assert.equal(none.tokens.input_tokens.mean, null);
  assert.match(none.source_issues[0], /계산할 수 없습니다/);
});

test("identical raw and assessment duplicates are counted once; unrelated and uncounted calls are excluded", () => {
  const f = fixture([sample(1, "request", 2)]);
  const outside = sample(2, "request", 500);
  outside.scored.counted = false;
  f.reports.push(clone(f.reports[0]), outside.raw);
  f.evaluation.assessments.push(clone(f.evaluation.assessments[0]), outside.scored);
  f.reports[0].trace.spans.push({...clone(f.reports[0].trace.spans[1]), id: "unselected", elapsed_seconds: 999});
  f.reports[1] = clone(f.reports[0]);
  const result = forAll(f.nodes, f.reports, f.evaluation).operational;
  assert.equal(result.response_time.normal.sample_count, 1);
  assert.equal(result.response_time.normal.mean, 2);
  assert.equal(result.model_calls.mean, 1);
});

test("conflicting original or evidence identities cannot silently contribute an arbitrary observation", () => {
  const f = fixture([sample(1, "request", 2)]);
  const conflicting = clone(f.reports[0]);
  conflicting.trace.spans[1].elapsed_seconds = 100;
  const duplicate = forAll(f.nodes, [...f.reports, conflicting], f.evaluation).operational;
  assert.equal(duplicate.response_time.normal.mean, null);
  assert.equal(duplicate.response_time.normal.missing_count, 1);
  f.nodes[0].conflicting_evidence = [[f.reports[0].run.id, "node-1"]];
  const savedConflict = forAll(f.nodes, f.reports, f.evaluation).operational;
  assert.equal(savedConflict.response_time.normal.mean, null);
});

test("unfinished measurements stay separate from missing finished samples", () => {
  const f = fixture([sample(1, "request", 2), sample(2, "interpretation", 4, {unfinished: true})]);
  const result = forAll(f.nodes, f.reports, f.evaluation).operational;
  assert.equal(result.failure_rate.denominator, 1);
  assert.equal(result.failure_rate.unfinished_count, 1);
  assert.equal(result.tokens.input_tokens.sample_count, 1);
  assert.equal(result.tokens.input_tokens.unfinished_count, 1);
  assert.equal(result.tokens.input_tokens.missing_count, 0);
  assert.equal(result.response_time.unfinished_count, 1);
});

test("empty populations are undetermined with a persistent zero-size verification summary", () => {
  const result = forAll([], [], null);
  assert.equal(result.node, "all");
  assert.equal(result.role, "all");
  assert.equal(result.functional.verdict, "미판정");
  assert.equal(result.functional.cases.rate, null);
  assert.equal(result.functional.verification.total_cases, 0);
  assert.equal(result.operational.verdict, "미판정");
  assert.equal(result.operational.failure_rate.rate, null);
});

test("normalization and combined metrics do not mutate frozen source summaries, checks, goals or reports", () => {
  const f = fixture([sample(1, "request", 2), sample(2, "interpretation", 4)]);
  f.nodes[0].functional.checks = [check("N-F.1")];
  f.nodes[0].performance = [{metric: "response_time", value_seconds: 2, max_seconds: 4, verdict: "통과", complete: true}];
  const before = clone(f);
  deepFreeze(f);
  const local = forNode(f.nodes[0]);
  const all = forAll(f.nodes, f.reports, f.evaluation);
  all.functional.cases.items[0].missing_repetitions.push(99);
  all.performance[0].value_seconds = 99;
  local.functional.cases.items[0].verdict = "실패";
  assert.deepEqual(f, before);
});
