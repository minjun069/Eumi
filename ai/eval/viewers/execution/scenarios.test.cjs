"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const vm = require("node:vm");
const catalog = require("./scenarios.js");
const scenarios = require("./scenario.js");
const dataset = path.join(__dirname, "../../scenarios/nodes");
const sha256 = data => crypto.createHash("sha256").update(data).digest("hex");

function runFor(id, workflow = false) {
  const scenario = catalog.scenarios.find(item => item.id === id);
  assert.ok(scenario);
  const unit = workflow ? "workflow" : "agent", target = workflow ? "report" : scenario.role;
  return {
    case: { id, unit, target },
    report: { run: { case_id: id, unit, target, role: workflow ? null : target, suite_id: "scenarios" } },
    manifest: { evaluation: {
      suite_id: "scenarios",
      source_selection: [{ scenario_id: id, scenario_file: scenario.file, unit, target,
        entry_state: workflow ? "entry_transition.before_state" : "start_state", providers: [] }],
      source_files_sha256: { [catalog.index_file]: catalog.index_sha256,
        ...Object.fromEntries((workflow ? catalog.scenarios : [scenario]).map(item => [item.file, item.sha256])) },
    } },
  };
}

function nodeCount(result) { return (result.html.match(/class="scenario-step"/g) || []).length; }
function stepRoles(result) { return [...result.html.matchAll(/<strong>[^<]*<\/strong><small>(.*?)<\/small>/g)].map(item => item[1]); }

test("all 21 scenario descriptions and diagrams are tied to the current source bytes", () => {
  const indexBytes = fs.readFileSync(path.join(dataset, "scenarios.json"));
  const index = JSON.parse(indexBytes);
  assert.equal(catalog.index_sha256, sha256(indexBytes));
  assert.equal(catalog.scenarios.length, 21);
  assert.deepEqual(catalog.scenarios.map(item => item.id), index.scenarios.map(item => item.id));
  for (const scenario of catalog.scenarios) {
    const bytes = fs.readFileSync(path.join(dataset, scenario.file)), source = JSON.parse(bytes);
    assert.equal(scenario.sha256, sha256(bytes));
    const result = scenarios.resolve(runFor(scenario.id));
    assert.equal(result.name, source.title);
    assert.ok(result.description.length > 0);
    assert.equal(nodeCount(result), source.steps.length);
    assert.match(result.html, /데이터셋 기준 도식/);
  }
});

test("request scenario preserves parent, expanded child, and resumed parent order", () => {
  const result = scenarios.resolve(runFor("basic-request-none"));
  assert.equal(nodeCount(result), 14);
  assert.deepEqual(stepRoles(result), [...Array(3).fill("사용자 요청 처리"), ...Array(9).fill("데이터 분석 결과 해석"), ...Array(2).fill("사용자 요청 처리")]);
  assert.match(result.html, /<ol class="scenario-flow">/);
  assert.doesNotMatch(result.html, /aria-current|scenario-step current/);
});

test("standalone specialist diagrams exclude the parent preparation nodes", () => {
  const result = scenarios.resolve(runFor("basic-interpretation-none"));
  assert.equal(nodeCount(result), 9);
  assert.doesNotMatch(result.html, /사용자 요청 처리/);
});

test("a report role remains standalone while report workflows join the explicit three-role chain", () => {
  for (const region of ["1168065500", "1168063000", "5111062000"]) {
    const selectionId = `basic-report_selection-${region}`;
    const role = scenarios.resolve(runFor(selectionId));
    assert.equal(nodeCount(role), 8);
    const workflow = scenarios.resolve(runFor(selectionId, true));
    assert.equal(nodeCount(workflow), 12);
    assert.deepEqual(stepRoles(workflow), [...Array(8).fill("보고서 시각화 선정"), ...Array(2).fill("보고서 시각화 설명"), ...Array(2).fill("보고서 퀵 인사이트")]);
    assert.match(workflow.name, /보고서 전체/);
    const description = scenarios.resolve(runFor(`basic-report_description-${region}`));
    assert.equal(nodeCount(description), 2);
    assert.equal(scenarios.resolve(runFor(`basic-report_description-${region}`, true)), null);
  }
});

test("missing, stale, or conflicting provenance never receives a guessed diagram", () => {
  const mutations = [
    run => { delete run.manifest; },
    run => { delete run.manifest.evaluation.source_selection; },
    run => { delete run.manifest.evaluation.source_files_sha256; },
    run => { run.manifest.evaluation.source_files_sha256[run.manifest.evaluation.source_selection[0].scenario_file] = "stale-body"; },
    run => { run.manifest.evaluation.source_selection.push(structuredClone(run.manifest.evaluation.source_selection[0])); },
    run => { run.manifest.evaluation.source_selection[0].scenario_file = "other/scenario.json"; },
    run => { run.manifest.evaluation.source_selection[0].target = "interpretation"; },
    run => { run.manifest.evaluation.source_selection[0].unit = "workflow"; },
    run => { run.manifest.evaluation.source_selection[0].entry_state = "entry_transition.before_state"; },
    run => { run.case.id = "another-case"; },
    run => { run.report.run.role = "interpretation"; },
    run => { run.report.run.suite_id = "another-suite"; },
  ];
  for (const mutate of mutations) {
    const run = runFor("basic-request-none");
    mutate(run);
    assert.equal(scenarios.resolve(run), null, mutate.toString());
  }
  assert.equal(scenarios.resolve(null), null);
  assert.equal(scenarios.resolve({ case: { id: "request-context", unit: "agent", target: "request" } }), null);
  assert.equal(scenarios.resolve(runFor("basic-request-none"), { suite: { id: "another-suite" } }), null);
});

test("a batch entry can supply identity when a run report is missing", () => {
  const run = runFor("basic-request-revision");
  run.entry = { case_id: run.case.id, unit: run.case.unit, target: run.case.target };
  delete run.report;
  assert.equal(nodeCount(scenarios.resolve(run)), 3);
});

test("browser export works and source strings cannot inject diagram markup", () => {
  const copy = structuredClone(catalog), chosen = copy.scenarios.find(item => item.id === "basic-request-revision");
  chosen.steps[0].action = '<img src=x onerror="alert(1)">';
  const context = { ExecutionScenarioCatalog: copy };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "scenario.js"), "utf8"), context);
  const html = context.ExecutionScenarios.resolve(runFor(chosen.id)).html;
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

test("an index-only change preserves the exact selected scenario while changed workflow bodies are rejected", () => {
  const run = runFor("basic-request-none");
  run.manifest.evaluation.source_files_sha256[catalog.index_file] = "previous-index";
  assert.equal(nodeCount(scenarios.resolve(run)), 14);
  const workflow = runFor("basic-report_selection-1168065500", true);
  const description = catalog.scenarios.find(item => item.id === "basic-report_description-1168065500");
  workflow.manifest.evaluation.source_files_sha256[description.file] = "changed-body";
  assert.equal(scenarios.resolve(workflow), null);
});

function tracedRun() {
  const span = (sequence, kind, name, parent_id, input = {}) => ({id: String(sequence), sequence, kind, name,
    parent_id: parent_id === null ? null : String(parent_id), input, status: "success", ended_at: "2026-11-13T00:00:00Z"});
  return {
    case: {id: "saved-case", purpose: "저장된 시나리오 제목", unit: "agent", target: "request"},
    report: {run: {case_id: "saved-case", unit: "agent", target: "request", role: "request"}, trace: {spans: [
      span(1, "evaluation", "request", null, {role: "request"}), span(2, "execution", "request", 1),
      span(3, "node", "act", 2), span(4, "model", "Selection", 3),
      span(5, "agent", "interpretation_agent", 3, {role: "interpretation"}),
      span(6, "node", "interpret", 5), span(7, "node", "act", 5), span(8, "tool", "query_data", 7),
      span(9, "node", "compose", 5), span(10, "node", "decide", 2), span(11, "node", "wait", 2),
    ]}},
  };
}

test("actual steps preserve child calls and the resumed parent in recorded start order without inventing a return", () => {
  const run = tracedRun(), before = structuredClone(run);
  run.report.trace.spans.reverse();
  const result = scenarios.resolve(run);
  assert.equal(result.name, "저장된 시나리오 제목");
  assert.match(result.html, /이상적인 시나리오 미제공/);
  assert.match(result.html, /<section class="scenario-diagram scenario-actual"><h3>실제 실행 결과/);
  assert.deepEqual([...result.html.matchAll(/data-sequence="(\d+)"/g)].map(item => Number(item[1])), [3, 6, 7, 9, 10, 11]);
  assert.deepEqual(stepRoles(result), ["사용자 요청 처리", ...Array(3).fill("데이터 분석 결과 해석"), "사용자 요청 처리", "사용자 요청 처리"]);
  assert.match(result.html, /하위 호출 2 · 상위 1/);
  const cards = [...result.html.matchAll(/<li class="scenario-step".*?<\/li>/g)].map(item => item[0]);
  assert.match(cards[0], /호출: 해석 역할 호출/);
  assert.doesNotMatch(cards[0], /호출: 자료 조회/);
  assert.match(cards[2], /호출: 자료 조회/);
  assert.match(cards[5], /사용자 응답 대기/);
  assert.doesNotMatch(result.html, /aria-current|scenario-step current|>반환</);
  run.report.trace.spans.reverse();
  assert.deepEqual(run, before);
});

test("ideal and actual diagrams coexist and a stale reference does not hide a sound trace", () => {
  const run = runFor("basic-request-none");
  run.report.trace = tracedRun().report.trace;
  assert.equal(nodeCount(scenarios.resolve(run)), 20);
  run.manifest.evaluation.source_files_sha256[catalog.scenarios.find(item => item.id === "basic-request-none").file] = "changed";
  const result = scenarios.resolve(run);
  assert.equal(nodeCount(result), 6);
  assert.match(result.html, /이상적인 시나리오 미제공/);
});

test("journal snapshots are deduplicated by call identity and never counted as additional nodes", () => {
  const run = tracedRun();
  run.journal = run.report.trace.spans.flatMap(span => [
    {event: "start", span: {...span, status: "running", ended_at: null}},
    {event: "end", span: structuredClone(span)},
  ]);
  delete run.report.trace;
  assert.equal(nodeCount(scenarios.resolve(run)), 6);
  delete run.report;
  assert.equal(nodeCount(scenarios.resolve(run)), 6);
  run.journal[1].span.parent_id = "different-parent";
  assert.equal(scenarios.resolve(run), null);
});

test("missing parent, duplicate sequence, corrupt count and incomplete evidence never become a fabricated actual path", () => {
  for (const mutate of [
    run => { run.report.trace.spans[5].parent_id = "missing"; },
    run => { run.report.trace.spans[5].sequence = 3; },
    run => { run.report.trace.spans.push(structuredClone(run.report.trace.spans[0])); },
    run => { run.report.trace.counts = {node: 60}; },
    run => { run.report.evidence = {complete: false}; },
    run => { run.report.trace.recovery_issues = ["missing chunk"]; },
  ]) {
    const run = tracedRun(); mutate(run);
    assert.equal(scenarios.resolve(run), null, mutate.toString());
  }
});

test("unfinished recorded nodes remain visible and an unrecorded child role does not inherit its parent's role", () => {
  const run = tracedRun();
  run.report.trace.spans[4].input = {};
  run.report.trace.spans[10].status = "running";
  run.report.trace.spans[10].ended_at = null;
  const result = scenarios.resolve(run);
  assert.equal(nodeCount(result), 6);
  assert.equal(stepRoles(result)[1], "역할 미기록");
  assert.match(result.html, /사용자 응답 대기/);
});
