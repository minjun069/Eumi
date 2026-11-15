"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {forRun, forCase} = require("./run-metrics.js");

const clone = value => JSON.parse(JSON.stringify(value));
const time = "2026-11-12T00:00:00+00:00";
function model(id = "model-1", options = {}) {
  return {id, parent_id: "node-1", kind: "model", name: "Interpretation", ended_at: time, elapsed_seconds: 2, status: "success",
    input: {messages: [{type: "human", content: "요청"}]}, output: {sdk_response: {text: '{"goal":"확인"}', usage_metadata: {input_tokens: 10, output_tokens: 4}}}, ...options};
}
function report(options = {}) {
  return {run: {id: "run-1", case_id: "case-1", repetition: 1, unit: "node", target: "interpret", role: "request", elapsed_seconds: 99, ...options},
    trace: {spans: [{id: "node-1", parent_id: null, kind: "node", name: "interpret", ended_at: time, elapsed_seconds: 98, status: "success",
      input: {role: "request", evaluation_scope: "model_output", state: {results: []}}, output: {applied_update: {results: []}}}, model()]}};
}
function check(id = "N-F.1", calls = [{id: "model-1", name: "Interpretation", index: 1}]) {
  return {check: id, axis: "형식 준수", method: "규칙 기반", executed: true, verdict: "통과", reason: "확인", details: [{id: "shape", executed: true, verdict: "통과", reason: "확인"}],
    calls: calls.map(call => ({...call, details: [{id: "shape", executed: true, verdict: "통과", reason: "확인"}]}))};
}
function assessment(options = {}) {
  return {node_id: "node-1", run_id: "run-1", case_id: "case-1", repetition: 1, node: "interpret", role: "request", counted: true,
    verdict: "통과", complete: true, checks: [check()], ...options};
}
function evaluation(values = [assessment()]) {
  return {status: "completed", assessments: values,
    runs: values.map(value => ({run_id: value.run_id, case_id: value.case_id, repetition: value.repetition, verdict: value.verdict, complete: value.complete})), nodes: []};
}
const one = (raw, score, scope) => forRun(raw, score, scope).nodes[0];

test("standalone observations use selected model time and preserve model input/raw output", () => {
  const raw = report(), score = evaluation(), before = clone({raw, score});
  const result = one(raw, score);
  assert.equal(result.operational.elapsedSeconds, 2);
  assert.equal(result.operational.inputTokens, 10);
  assert.equal(result.operational.outputTokens, 4);
  assert.equal(result.operational.modelCalls, 1);
  assert.equal(result.operational.technicalRetries, 0);
  assert.equal(result.operational.technicalFailure, false);
  assert.equal(result.calls[0].raw, '{"goal":"확인"}');
  assert.deepEqual(result.calls[0].input, [{type: "human", content: "요청"}]);
  assert.deepEqual(result.calls[0].output, {goal: "확인"});
  assert.equal(result.functional.details.passed, 1);
  assert.deepEqual({raw, score}, before);
});

test("raw-only standalone calls expose observations without fabricating a verdict", () => {
  const result = one(report(), null);
  assert.equal(result.verdict, null);
  assert.equal(result.functional, null);
  assert.equal(result.operational.modelCalls, 1);
  assert.equal(result.calls.length, 1);
});

test("an unscored standalone run still shows its raw observations with another assessment loaded", () => {
  const raw = report(), score = evaluation([assessment({run_id: "run-2", repetition: 2})]);
  const result = one(raw, score);
  assert.equal(result.verdict, null);
  assert.equal(result.complete, null);
  assert.equal(result.functional, null);
  assert.deepEqual(result.checks, []);
  assert.equal(result.operational.elapsedSeconds, 2);
  assert.equal(result.operational.modelCalls, 1);
  assert.equal(result.calls[0].input[0].content, "요청");
  assert.deepEqual(forRun(raw, score, {node: "compose"}).nodes, []);
  assert.deepEqual(forRun(raw, score, {node: "interpret", role: "interpretation"}).nodes, []);
  const selection = report({unit: "selection", target: "act"});
  selection.trace.spans[0].name = "act";
  selection.trace.spans[1].name = "Selection";
  const selected = one(selection, score);
  assert.equal(selected.functional, null);
  assert.equal(selected.calls[0].name, "Selection");
  assert.equal(selected.operational.modelCalls, 1);
});

test("score-only retains functional data while observations explain missing original", () => {
  const result = one(null, evaluation(), {caseId: "case-1", repetition: 1, runId: "run-1"});
  assert.equal(result.functional.checks.passed, 1);
  assert.equal(result.operational.inputTokens, null);
  assert.match(result.operational.missingReasons.inputTokens, /원본/);
  assert.deepEqual(result.calls, []);
});

test("missing tokens stay null while measured zero and missing model time remain distinct", () => {
  const raw = report();
  raw.trace.spans[1].output.sdk_response.usage_metadata = {input_tokens: 0, output_tokens: null};
  raw.trace.spans[1].elapsed_seconds = null;
  const result = one(raw, evaluation()).operational;
  assert.equal(result.inputTokens, 0);
  assert.equal(result.outputTokens, null);
  assert.equal(result.elapsedSeconds, null);
  assert.equal(result.modelCalls, 1);
  assert.match(result.missingReasons.outputTokens, /토큰/);
});

test("technical failure is separated from malformed returned model output", () => {
  const failed = report();
  failed.trace.spans[1] = model("model-1", {status: "error", error: {type: "ConnectionError"}, output: {}});
  assert.equal(one(failed, evaluation()).operational.technicalFailure, true);
  assert.equal(one(failed, evaluation()).operational.elapsedSeconds, 2);
  const malformed = report();
  malformed.trace.spans[1].output.sdk_response.text = "invalid JSON";
  assert.equal(one(malformed, evaluation()).operational.technicalFailure, false);
  assert.equal(one(malformed, evaluation()).calls[0].raw, "invalid JSON");
  assert.equal(one(malformed, evaluation()).calls[0].output, null);
  const unknown = report();
  unknown.trace.spans[1].output = {};
  assert.equal(one(unknown, evaluation()).operational.technicalFailure, null);
});

test("the same call across checks is measured once; merged detail counts are not doubled", () => {
  const scored = assessment({checks: [check(), check("N-O.1")]});
  scored.checks[0].details.push(clone(scored.checks[0].details[0]));
  scored.checks.push(clone(scored.checks[0]));
  const result = one(report(), evaluation([scored]));
  assert.equal(result.operational.modelCalls, 1);
  assert.equal(result.operational.inputTokens, 10);
  assert.equal(result.functional.checks.total, 2);
  assert.equal(result.functional.details.total, 2);
});

test("unexecuted and prerequisite-skipped functional items use existing rate semantics", () => {
  const scored = assessment();
  scored.checks.push({...check("N-O.1"), executed: false, verdict: "미판정", reason: "선행 단계 실패로 미실행", details: [{id: "body", executed: false, verdict: "미판정", reason: "선행 단계 실패로 미실행"}]});
  const result = one(report(), evaluation([scored]));
  assert.equal(result.functional.checks.undetermined, 0);
  assert.equal(result.functional.checks.notExecuted, 1);
  assert.equal(result.functional.checks.skippedAfterFailure, 1);
  assert.equal(result.functional.details.notExecuted, 1);
});

test("partial selected-model tokens cannot be presented as a completed total", () => {
  const raw = report({unit: "agent"});
  delete raw.trace.spans[0].input.evaluation_scope;
  raw.trace.spans.push(model("model-2", {output: {sdk_response: {text: "{}", usage_metadata: {input_tokens: 7}}}}));
  const refs = [{id: "model-1", name: "Interpretation", index: 1}, {id: "model-2", name: "Interpretation", index: 2}];
  const result = one(raw, evaluation([assessment({checks: [check("N-F.1", refs)]})]));
  assert.equal(result.operational.inputTokens, 17);
  assert.equal(result.operational.outputTokens, null);
  assert.equal(result.operational.elapsedSeconds, 4);
  assert.equal(result.operational.modelCalls, 2);
  assert.equal(result.operational.technicalRetries, 0);
});

test("partial model selection does not invent a retry count", () => {
  const raw = report({unit: "workflow", role: null});
  delete raw.trace.spans[0].input.evaluation_scope;
  raw.trace.spans.push(model("model-2"));
  const result = one(raw, evaluation());
  assert.equal(result.operational.modelCalls, 1);
  assert.equal(result.operational.technicalRetries, null);
  assert.match(result.operational.missingReasons.technicalRetries, /일부/);
});

test("retries require technical failure and linked extra action rather than calls minus one", () => {
  const raw = report({unit: "agent"});
  const parent = raw.trace.spans[0];
  delete parent.input.evaluation_scope;
  parent.output.applied_update.results = [
    {id: "failed", action: {name: "Interpretation", arguments: {a: 1}}, outcome: "failure", output: {type: "ConnectionError"}},
    {id: "retry", decision: "retry", output: {call_id: "failed"}},
    {id: "again", action: {arguments: {a: 1}, name: "Interpretation"}, outcome: "success"}
  ];
  raw.trace.spans.push(model("model-2"));
  const refs = [{id: "model-1", name: "Interpretation", index: 1}, {id: "model-2", name: "Interpretation", index: 2}];
  const score = evaluation([assessment({checks: [check("N-F.1", refs)]})]);
  assert.equal(one(raw, score).operational.technicalRetries, 1);
  parent.output.applied_update.results[0].outcome = "success";
  assert.equal(one(raw, score).operational.technicalRetries, 0);
});

test("different node or role and nested agent calls cannot supply selected observations", () => {
  const raw = report({unit: "agent"});
  raw.trace.spans.push({id: "node-child", parent_id: "node-1", kind: "node", name: "interpret", ended_at: time, input: {role: "interpretation"}});
  raw.trace.spans.push(model("child-call", {parent_id: "node-child"}));
  const wrongCall = assessment({checks: [check("N-F.1", [{id: "child-call", name: "Interpretation", index: 1}])]});
  assert.equal(one(raw, evaluation([wrongCall])).operational.modelCalls, null);
  assert.equal(one(raw, evaluation([assessment({role: "visualization"})])).operational.modelCalls, null);
  assert.deepEqual(forRun(raw, evaluation(), {node: "compose"}).nodes, []);
});

test("call index conflicts, conflicting trace IDs and missing parents block observations", () => {
  const score = evaluation();
  score.assessments[0].checks.push(check("N-O.1", [{id: "model-1", name: "Interpretation", index: 2}]));
  assert.equal(one(report(), score).operational.modelCalls, null);
  const conflict = report();
  conflict.trace.spans.push(model("model-1", {elapsed_seconds: 9}));
  assert.equal(one(conflict, evaluation()).operational.modelCalls, null);
  const missing = report();
  missing.trace.spans[0].parent_id = "absent";
  assert.equal(one(missing, evaluation()).operational.modelCalls, null);
});

test("cancelled agent assessment does not assume its recorded calls are complete", () => {
  const raw = report({unit: "agent"}), score = evaluation([assessment({complete: false})]);
  score.status = "cancelled";
  assert.equal(one(raw, score).operational.modelCalls, null);
  assert.match(one(raw, score).operational.reason, /취소/);
  const completed = evaluation();
  completed.status = "cancelled";
  assert.equal(one(raw, completed).operational.modelCalls, 1);
});

test("unfinished calls provide observed tokens separately and never become complete samples", () => {
  const raw = report();
  raw.trace.spans[1].ended_at = null;
  delete raw.trace.spans[1].output.sdk_response.usage_metadata.output_tokens;
  const result = one(raw, evaluation()).operational;
  assert.equal(result.unfinished, true);
  assert.equal(result.inputTokens, null);
  assert.equal(result.modelCalls, null);
  assert.deepEqual(result.observed, {modelCalls: 1, inputTokens: 10, inputMissingCalls: 0, outputTokens: null, outputMissingCalls: 1});
  const summary = forCase([raw], evaluation(), {caseId: "case-1"}).nodes[0].operational;
  assert.equal(summary.tokens.input_tokens.sample_count, 0);
  assert.equal(summary.tokens.input_tokens.unfinished_count, 1);
  assert.equal(summary.unfinished_usage[0].usage.input_tokens, 10);
});

test("case aggregation keeps normal/error statistics and saved case completion without a new verdict", () => {
  const first = report(), second = report({id: "run-2", repetition: 2});
  second.trace.spans[1] = model("model-1", {elapsed_seconds: 5, output: {}, error: {type: "ConnectionError"}});
  const a2 = assessment({run_id: "run-2", repetition: 2, verdict: "실패", checks: [{...check(), verdict: "실패"}]});
  const score = evaluation([assessment(), a2]);
  const saved = {case_id: "case-1", verdict: "실패", complete: false, missing_repetitions: [3]};
  score.nodes = [{node: "interpret", role: "request", functional: {cases: {items: [saved]}}}];
  score.runs.push({run_id: null, case_id: "case-1", repetition: 3, verdict: "미판정", complete: false});
  const result = forCase([first, second], score, {caseId: "case-1"}).nodes[0];
  assert.strictEqual(result.caseSummary, saved);
  assert.equal(result.functional.checks[0].rate, 0.5);
  assert.equal(result.operational.response_time.normal.mean, 2);
  assert.equal(result.operational.response_time.error.p95, 5);
  assert.equal(result.operational.failure_rate.rate, 0.5);
  assert.equal(result.operational.tokens.input_tokens.missing_count, 1);
  assert.equal(result.runs.length, 3);
  assert.equal(result.runs[2].verdict, "미판정");
});

test("case statistics use nearest-rank p95, median, and no zero for missing originals", () => {
  const raw = [1, 2, 9, 10].map((duration, index) => {
    const item = report({id: `run-${index + 1}`, repetition: index + 1});
    item.trace.spans[1].elapsed_seconds = duration;
    return item;
  });
  const score = evaluation(raw.map(item => assessment({run_id: item.run.id, repetition: item.run.repetition})));
  const result = forCase(raw, score, {caseId: "case-1"}).nodes[0];
  assert.deepEqual(result.operational.response_time.normal, {sample_count: 4, missing_count: 0, unfinished_count: 0, mean: 5.5, median: 5.5, p95: 10});
  const missing = forCase([], score, {caseId: "case-1"}).nodes[0].operational;
  assert.equal(missing.model_calls.mean, null);
  assert.equal(missing.model_calls.missing_count, 4);
  assert.equal(missing.failure_rate.denominator, 0);
  assert.equal(missing.failure_rate.rate, null);
});

test("a report from another run cannot attach its inputs or observations", () => {
  const result = one(report({id: "other"}), evaluation(), {caseId: "case-1", repetition: 1, runId: "run-1"});
  assert.equal(result.operational.modelCalls, null);
  assert.deepEqual(result.calls, []);
  assert.match(result.operational.reason, /식별자/);
});

test("score-only unfinished observations retain the separately saved partial usage", () => {
  const score = evaluation();
  score.nodes = [{node: "interpret", role: "request", operational: {unfinished_usage: [{node_id: "node-1", run_id: "run-1", case_id: "case-1", repetition: 1,
    usage: {input_tokens: 0, output_tokens: null}, usage_missing_calls: {input_tokens: 0, output_tokens: 1}, model_calls: 1}]}}];
  const result = one(null, score, {caseId: "case-1", runId: "run-1", repetition: 1});
  assert.equal(result.operational.unfinished, true);
  assert.equal(result.operational.inputTokens, null);
  assert.equal(result.operational.observed.inputTokens, 0);
  assert.equal(result.operational.observed.outputTokens, null);
  const aggregate = forCase([], score, {caseId: "case-1"}).nodes[0].operational;
  assert.equal(aggregate.model_calls.unfinished_count, 1);
  assert.equal(aggregate.model_calls.missing_count, 0);
});

test("runner-generated sample per-case metrics agree with saved single-case node summaries", () => {
  const fs = require("node:fs"), vm = require("node:vm"), path = require("node:path");
  const {parseFiles} = require("./data.js"), context = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "samples.js"), "utf8"), context);
  const catalog = parseFiles(context.EvaluationSamples.files);
  let compared = 0;
  for (const batch of catalog.batches) for (const record of batch.assessments) {
    for (const saved of record.report.nodes) {
      if (saved.functional.cases.items.length !== 1) continue;
      const caseId = saved.functional.cases.items[0].case_id;
      const derived = forCase(batch.runs.map(run => run.report).filter(Boolean), record.report, {caseId, node: saved.node, role: saved.role}).nodes[0];
      assert.deepEqual(derived.functional.checks, saved.functional.checks);
      assert.deepEqual(derived.functional.details, saved.functional.details);
      for (const field of ["failure_rate", "response_time", "tokens", "model_calls", "technical_retries"]) assert.deepEqual(derived.operational[field], saved.operational[field]);
      compared++;
    }
  }
  assert.ok(compared > 0);
});
