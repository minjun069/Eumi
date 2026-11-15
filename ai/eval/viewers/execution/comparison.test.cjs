"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {rows} = require("./comparison.js");
const expected = () => ({schema_version: "execution-expectations-v1", situation: "normal", entry: "initial"});
const span = (id, parent_id, sequence, kind, name, input = {}) => ({id, parent_id, sequence, kind, name, input, status: "success", ended_at: "2026-11-13T00:00:00Z"});
const report = () => ({run: {id: "run-1", unit: "agent", target: "request", status: "returned"},
  state: {execution: {status: "completed", error: null}, response: {kind: "final"}},
  trace: {spans: [span("root", null, 1, "execution", "request"), span("node-1", "root", 2, "node", "interpret"), span("node-2", "root", 3, "node", "compose")]}});
const byKey = result => Object.fromEntries(result.map(row => [row.key, row]));

test("scenario-derived conditions do not become output expectations; actual fields stay visible", () => {
  const result = byKey(rows(report(), expected()));
  assert.deepEqual(Object.keys(result), ["node_path", "run_status", "execution_status", "response_kind", "error_code"]);
  assert.ok(Object.values(result).every(row => row.expected === undefined));
  assert.deepEqual(result.node_path.actual, ["interpret", "compose"]);
  assert.equal(result.run_status.actual, "returned");
  assert.equal(result.execution_status.actual, "completed");
  assert.equal(result.response_kind.actual, "final");
  assert.equal(result.error_code.actual, null);
});

test("paths follow sequence and exclude wait and non-report nested agent nodes", () => {
  const raw = report();
  raw.trace.spans = [span("root", null, 1, "execution", "request"),
    span("interpret", "root", 2, "node", "interpret"), span("act", "root", 3, "node", "act"),
    span("child", "act", 4, "agent", "interpretation_agent", {role: "interpretation"}),
    span("child-node", "child", 5, "node", "decide"), span("child-wait", "child", 6, "node", "wait"),
    span("compose", "root", 7, "node", "compose"), span("wait", "root", 8, "node", "wait")].reverse();
  const result = byKey(rows(raw, {...expected(), node_path: ["interpret", "act", "compose"]}));
  assert.deepEqual(result.node_path.actual, ["interpret", "act", "compose"]);
  assert.deepEqual(result.node_path.expected, ["interpret", "act", "compose"]);
});

test("report reentry includes only this invocation's report roles and retains report nodes", () => {
  const raw = report(); raw.run = {...raw.run, unit: "workflow", target: "report"};
  raw.trace.spans = [span("root", null, 1, "execution", "report", {initial_state: {results: [{decision: "composition", outcome: "success", action: {name: "report_selection_agent"}}]}}),
    span("desc", "root", 2, "agent", "report_description_agent", {role: "report_description"}),
    span("desc-node", "desc", 3, "node", "compose"),
    span("nested", "desc-node", 4, "agent", "visualization_agent", {role: "visualization"}),
    span("nested-node", "nested", 5, "node", "act"),
    span("insight", "root", 6, "agent", "report_insight_agent", {role: "report_insight"}),
    span("insight-node", "insight", 7, "node", "compose")];
  const result = byKey(rows(raw, {...expected(), entry: "reentry"}, {report_completeness: "partial"}));
  assert.deepEqual(result.role_path.actual, ["report_description", "report_insight"]);
  assert.deepEqual(result.node_path.actual, ["compose", "compose"]);
  assert.equal(result.report_completeness.actual, "partial");
});

test("missing, duplicate and conflicting boundaries never appear as an empty known path", () => {
  const mutations = [
    raw => delete raw.trace,
    raw => { raw.trace.spans = []; },
    raw => raw.trace.spans.push({...raw.trace.spans[1]}),
    raw => { raw.trace.spans[2].sequence = 2; },
    raw => { raw.trace.spans[1].parent_id = "missing"; },
    raw => { raw.trace.spans[1].parent_id = "node-2"; },
    raw => { raw.trace.spans[1].status = "unknown"; },
    raw => { raw.trace.spans[1].evidence_conflict = true; },
    raw => { raw.trace.recovery_issues = ["damaged line"]; },
    raw => { raw.evidence = {complete: false}; },
    raw => { raw.trace.counts = {execution: 1, node: 3}; },
    raw => { raw.trace.coverage = {unfinished_spans: 1}; },
  ];
  for (const mutate of mutations) {
    const raw = report(); mutate(raw);
    const row = byKey(rows(raw, expected())).node_path;
    assert.equal(row.actual, undefined); assert.ok(row.unavailable);
  }
  const raw = report(); raw.trace.spans.length = 1;
  assert.deepEqual(byKey(rows(raw, expected())).node_path.actual, []);
});

test("explicit null and recorded falsy values remain different from absent fields", () => {
  const raw = report(); raw.state.response = null;
  let result = byKey(rows(raw, {...expected(), response_kind: null, error_code: null}));
  assert.equal(result.response_kind.actual, null); assert.equal(result.response_kind.expected, null);
  assert.equal(result.error_code.actual, null); assert.equal(result.error_code.expected, null);
  delete raw.state.response; delete raw.state.execution.error;
  result = byKey(rows(raw, expected()));
  assert.equal(result.response_kind.actual, undefined); assert.ok(result.response_kind.unavailable);
  assert.equal(result.error_code.actual, undefined); assert.ok(result.error_code.unavailable);
  raw.state.response = {kind: 0}; raw.state.execution.error = {code: false};
  result = byKey(rows(raw, {response_kind: "", error_code: false}));
  assert.equal(result.response_kind.actual, 0); assert.equal(result.response_kind.expected, "");
  assert.equal(result.error_code.actual, false); assert.equal(result.error_code.expected, false);
});

test("report completeness uses only the selected saved assessment and never recomputes", () => {
  const raw = report(); raw.run.unit = "workflow"; raw.run.target = "report";
  raw.state.response.artifacts = [{type: "analysis_report", data: {quick_insight: "filled", graph_1: "filled", desc_1: "filled", graph_2: "filled", desc_2: "filled", graph_3: "filled", desc_3: "filled"}}];
  for (const scored of [undefined, {}, {report_completeness: null}]) {
    const row = byKey(rows(raw, expected(), scored)).report_completeness;
    assert.equal(row.actual, undefined); assert.ok(row.unavailable);
  }
  const result = byKey(rows(raw, {report_completeness: "complete"}, {report_completeness: "none"}));
  assert.equal(result.report_completeness.actual, "none");
  assert.equal(result.report_completeness.expected, "complete");
  const absent = byKey(rows(undefined, {role_path: []}, {report_completeness: "partial"}));
  assert.equal(absent.report_completeness.actual, "partial");
  assert.equal(absent.role_path.actual, undefined);
  const standalone = byKey(rows(undefined, expected(), {report_completeness: "complete"}, {unit: "workflow", target: "report", status: "returned"}));
  assert.equal(standalone.report_completeness.actual, "complete");
  assert.equal(standalone.role_path.actual, undefined);
  assert.equal(standalone.run_status.actual, undefined);
});

test("sources and source ordering are untouched and the browser API matches CommonJS", () => {
  const raw = report(), target = {...expected(), node_path: ["interpret", "compose"]}, scored = {report_completeness: null};
  raw.trace.spans.reverse();
  const before = structuredClone({raw, target, scored});
  rows(raw, target, scored);
  assert.deepEqual({raw, target, scored}, before);
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve("./comparison.js"), "utf8"), context);
  assert.equal(JSON.stringify(context.ExecutionComparison.rows(raw, target, scored)), JSON.stringify(rows(raw, target, scored)));
});

test("actual runner samples expose observed request paths and report reentry roles", () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve("./samples.js"), "utf8"), context);
  const reports = context.ExecutionEvaluationSamples().files.filter(file => file.path.endsWith("/report.json")).map(file => JSON.parse(file.text));
  const request = reports.find(item => item.run.case_id === "request-context");
  assert.deepEqual(byKey(rows(request, expected())).node_path.actual, ["interpret", "decide", "compose"]);
  const resumed = reports.find(item => item.run.case_id === "report-reentry");
  assert.deepEqual(byKey(rows(resumed, expected())).role_path.actual, ["report_description", "report_insight"]);
});
