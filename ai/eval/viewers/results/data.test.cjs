"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { parseFiles } = require("./data.js");

const time = "2026-11-09T00:00:00+00:00";
function span(overrides = {}) {
  return { id: "call-1", parent_id: null, sequence: 1, kind: "evaluation", name: "query_data",
    started_at: time, ended_at: time, elapsed_seconds: 0.2, status: "success", input: { arguments: {} }, ...overrides };
}
function trace(spans = [span()]) {
  return { version: "local-execution-trace-v1", scope: "로컬 추적", limitations: [], counts: { evaluation: spans.length },
    coverage: { model_attempts: 0, model_inputs: 0, http_requests: 0, http_responses: 0, sdk_responses: 0, model_errors: 0, unfinished_spans: 0 }, spans };
}
function report(overrides = {}) {
  return { schema_version: "evaluation-run-v1", run: { id: "run-1", suite_id: "suite-1", case_id: "case-1", repetition: 1,
    unit: "tool", target: "query_data", role: null, dependencies: "real", status: "returned", started_at: time, ended_at: time, elapsed_seconds: 0.2 },
    output: { data: [], count: 0 }, failure: null, trace: trace(),
    assessment: { verdict: "미판정", executed: false, reason: "실행 증거만 수집함.", checks: ["T01-I.1"] },
    fixtures: { calls: [], unexpected: [], unused: [] }, journal_saved: true, ...overrides };
}
function caseFile(overrides = {}) {
  return { id: "case-1", unit: "tool", target: "query_data", purpose: "정상 0건 확인", arguments: { dataset: "small" },
    assessment: { reference: { source: "독립 기준" }, expected: [], tolerance: null, checks: ["T01-I.1"], required: true }, ...overrides };
}
function manifest(suiteId = "suite-1") {
  return { version: "execution-manifest-v1", captured_at: time, git: { revision: null, dirty: true }, content_sha256: "hash",
    files_sha256: { "src/state.py": "hash" }, settings: {}, evaluation: { suite_id: suiteId, suite_sha256: "hash", source: null, source_sha256: null, runner_sha256: { "runner.py": "hash" } } };
}
function batchEntry(run = report().run) {
  return { case_id: run.case_id, run_id: run.id, unit: run.unit, target: run.target, repetition: run.repetition, status: run.status, path: `runs/${run.id}/report.json` };
}
function batch(reports = [report()], overrides = {}) {
  return { schema_version: "evaluation-batch-v1", id: "batch-1", suite_id: "suite-1", status: "returned", started_at: time, ended_at: time,
    planned_runs: reports.length, runs: reports.map(item => batchEntry(item.run)), ...overrides };
}
function json(path, value) { return { path, text: JSON.stringify(value) }; }
function runFiles(value = report(), input = caseFile(), prefix = "batch-1") {
  const root = `${prefix}/runs/${value.run.id}`;
  return [json(`${root}/report.json`, value), json(`${root}/case.json`, input), json(`${root}/manifest.json`, manifest(value.run.suite_id)),
    { path: `${root}/trace.jsonl`, text: value.trace.spans.map(item => JSON.stringify({ event: "end", span: item })).join("\n") }];
}
function completeFiles(reports = [report()], cases = [caseFile()]) {
  return [json("batch-1/batch.json", batch(reports)), json("batch-1/suite.json", { schema_version: "evaluation-suite-v1", id: "suite-1", cases }),
    ...reports.flatMap(item => runFiles(item, cases.find(input => input.id === item.run.case_id)))];
}
const firstRun = result => result.batches[0].runs[0];

function scoredFiles() {
  require("./samples.js");
  return structuredClone(globalThis.EvaluationSamples.files.filter(file => file.path.includes("도구평가_2026-11-09_실행01/")));
}

test("separate tool assessments retain all raw values and latest-first re-evaluation snapshots", () => {
  const files = scoredFiles(), result = parseFiles(files);
  assert.deepEqual(result.issues, []);
  const b = result.batches[0];
  assert.equal(b.assessments.length, 2);
  assert.equal(b.assessments[0].report.id, "도구평가_2026-11-09_실행01_채점02");
  assert.equal(b.assessments[0].report.tools[0].functional.rate, 0.5);
  for (const a of b.assessments) assert.deepEqual(a.report, JSON.parse(files.find(f => f.path === a.path).text));
  for (const run of b.runs) {
    assert.deepEqual(run.report, JSON.parse(files.find(f => f.path === run.path).text));
    assert.equal(run.report.assessment.verdict, "미판정");
  }
});

test("score-only and renamed files expose metrics without fabricating execution evidence", () => {
  const file = scoredFiles().find(f => f.path.endsWith("도구평가_2026-11-09_실행01_채점02.json"));
  file.path = "renamed.json";
  const b = parseFiles([file]).batches[0];
  assert.equal(b.source, "assessment");
  assert.deepEqual(b.runs, []);
  assert.equal(b.report, null);
  assert.equal(b.suite, null);
  assert.equal(b.assessments[0].report.tools[0].latency.normal.sample_count, 1);
});

test("invalid scoring shape, version, duplicate ID and mismatched identity are isolated", () => {
  for (const mutate of [
    a => { a.tools[0].functional.rate = "50%"; },
    a => { a.schema_version = "tool-evaluation-v2"; },
    a => { a.runs[0].checks[0].verdict = "pass"; },
    a => { a.runs.push(a.runs[0]); },
    a => { a.suite_id = a.criteria.suite_id = "wrong-suite"; },
    a => { a.runs[0].case_id = "wrong-case"; },
    a => { a.runs[0].repetition = 2; },
  ]) {
    const files = scoredFiles();
    const f = files.find(f => f.path.endsWith("도구평가_2026-11-09_실행01_채점02.json"));
    const a = JSON.parse(f.text); mutate(a); f.text = JSON.stringify(a);
    const result = parseFiles(files);
    assert.equal(result.batches[0].runs.length, 2);
    assert.equal(result.batches[0].assessments.length, 1);
    assert.ok(result.issues.some(i => i.severity === "error"));
  }
  const files = scoredFiles(), latest = files.find(f => f.path.endsWith("도구평가_2026-11-09_실행01_채점02.json"));
  files.push({...latest, path: "duplicate-score.json"});
  const result = parseFiles(files);
  assert.equal(result.batches[0].assessments.length, 1);
  assert.equal(result.issues.filter(i => i.code === "duplicate-assessment").length, 2);
});

test("missing planned executions and absent versus null comparison values survive scoring import", () => {
  const file = scoredFiles().find(f => f.path.endsWith("도구평가_2026-11-09_실행01_채점02.json"));
  const a = JSON.parse(file.text);
  a.runs[0].run_id = null;
  a.runs[0].checks[0].expected = null;
  delete a.runs[0].checks[0].actual;
  file.text = JSON.stringify(a);
  const result = parseFiles([file]);
  const c = result.batches[0].assessments[0].report.runs[0].checks[0];
  assert.equal(c.expected, null);
  assert.equal(Object.hasOwn(c, "actual"), false);
  assert.equal(result.batches[0].runs.length, 0);
});

test("ambiguous batch copies do not receive an arbitrary scoring snapshot", () => {
  const files = scoredFiles();
  const b = files.find(f => f.path.endsWith("batch.json"));
  files.push({...b, path: b.path.replace("batch.json", "batch-copy.json")});
  const result = parseFiles(files);
  assert.ok(result.batches.every(b => b.assessments.length === 0));
  assert.equal(result.issues.filter(i => i.code === "assessment-mismatch").length, 2);
});

test("batch and sibling evidence retain originals without creating State or passing grades", () => {
  const result = parseFiles(completeFiles());
  assert.equal(result.issues.length, 0);
  assert.equal(result.batches.length, 1);
  const run = firstRun(result);
  assert.deepEqual(run.report, report());
  assert.equal(Object.hasOwn(run.report, "state"), false);
  assert.equal(run.report.run.status, "returned");
  assert.deepEqual(run.report.assessment, report().assessment);
  assert.equal(run.caseSource, "case");
  assert.deepEqual(run.case.assessment.expected, []);
  assert.deepEqual(run.manifest, manifest());
  assert.deepEqual(run.journal, [{ event: "end", span: span() }]);
  assert.deepEqual(run.availability, { report: "loaded", case: "loaded", manifest: "loaded", journal: "loaded" });
  assert.equal(Object.hasOwn(run.report, "metrics"), false);
});

test("repetition identity survives, and returned business failure remains ungraded", () => {
  const one = report();
  const two = report({ run: { ...one.run, id: "run-2", repetition: 2, unit: "node", target: "act", role: "request", dependencies: "stub" },
    state: { execution: { run_id: "run-2", status: "failed" } }, output: { goto: "compose" },
    fixtures: { calls: [{ name: "query_data", arguments: {}, stub: 0 }], unexpected: [], unused: [{ stub: 1, remaining: 2 }] } });
  const cases = [caseFile(), caseFile({ id: "node-case", unit: "node", target: "act", role: "request", initial: {}, dependencies: "stub" })];
  delete cases[1].arguments;
  two.run.case_id = "node-case";
  const result = parseFiles(completeFiles([one, two], cases));
  assert.equal(result.issues.length, 0);
  const run = result.batches[0].runs[1];
  assert.equal(run.report.run.repetition, 2);
  assert.equal(run.report.run.status, "returned");
  assert.equal(run.report.state.execution.status, "failed");
  assert.equal(run.report.assessment.verdict, "미판정");
  assert.deepEqual(run.report.fixtures, two.fixtures);
});

test("selection arguments_json remains uninterpreted text even when it is not valid JSON", () => {
  const value = report();
  value.run = { ...value.run, unit: "selection", target: "act", role: "request" };
  value.state = { execution: { run_id: value.run.id, status: "running" } };
  value.output = { name: "query_data", arguments_json: '{"incomplete":', reason: "모델 선택 원문" };
  const result = parseFiles([json("chosen.json", value)]);
  assert.equal(firstRun(result).report.output.arguments_json, '{"incomplete":');
  assert.equal(firstRun(result).case, null);
  assert.equal(result.batches[0].source, "standalone");
});

test("cancelled batch retains planned executions without inventing unstarted runs", () => {
  const data = batch([], { status: "cancelled", planned_runs: 3, failure: { type: "CancelledError", code: null },
    runs: [{ ...batchEntry(), status: "running" }] });
  const result = parseFiles([json("batch-1/batch.json", data)]);
  assert.equal(result.batches[0].report.planned_runs, 3);
  assert.equal(result.batches[0].runs.length, 1);
  assert.equal(firstRun(result).entry.status, "running");
  assert.equal(firstRun(result).report, null);
  assert.equal(firstRun(result).availability.report, "missing");
  assert.equal(firstRun(result).availability.journal, "missing");
});

test("bad report does not discard another run and wrong versions are not interpreted", () => {
  const one = report();
  const two = report({ run: { ...one.run, id: "run-2", repetition: 2 } });
  const files = completeFiles([one, two]);
  files.find(file => file.path.endsWith("run-1/report.json")).text = "{broken";
  const result = parseFiles(files);
  assert.equal(firstRun(result).availability.report, "invalid");
  assert.deepEqual(result.batches[0].runs[1].report, two);
  const unsupported = parseFiles([json("future.json", { ...one, schema_version: "evaluation-run-v2" })]);
  assert.equal(unsupported.batches.length, 0);
  assert.equal(unsupported.issues[0].code, "invalid-artifact");
});

test("required nested fields, types, and current ungraded contract are checked", () => {
  for (const change of [
    value => { delete value.run.elapsed_seconds; },
    value => { value.run.repetition = true; },
    value => { value.run.status = "running"; },
    value => { value.journal_saved = "true"; },
    value => { delete value.trace.coverage.model_inputs; },
    value => { value.fixtures.unused = [{ stub: 0, remaining: 0 }]; },
    value => { value.assessment.executed = true; },
    value => { value.assessment.verdict = "통과"; },
    value => { value.output = []; },
  ]) {
    const value = report(); change(value);
    const result = parseFiles([json("report.json", value)]);
    assert.equal(result.batches.length, 0);
    assert.ok(result.issues.some(item => item.code === "invalid-artifact"));
  }
});

test("run identity, State ID, case target, and manifest suite mismatch are isolated", () => {
  const files = completeFiles();
  const bad = report(); bad.run.id = "another-run";
  files.find(file => file.path.endsWith("/report.json")).text = JSON.stringify(bad);
  const result = parseFiles(files);
  assert.equal(firstRun(result).report, null);
  assert.equal(firstRun(result).availability.report, "mismatch");
  assert.ok(firstRun(result).case);
  const stateMismatch = report({ state: { execution: { run_id: "wrong", status: "completed" } } });
  assert.equal(parseFiles([json("report.json", stateMismatch)]).batches.length, 0);
  const withAttachments = runFiles();
  withAttachments[1] = json(withAttachments[1].path, caseFile({ target: "process_data" }));
  withAttachments[2] = json(withAttachments[2].path, manifest("another-suite"));
  const attached = firstRun(parseFiles(withAttachments));
  assert.equal(attached.availability.case, "mismatch");
  assert.equal(attached.availability.manifest, "mismatch");
  assert.deepEqual(attached.report, report());
});

test("partial JSONL preserves good start/update/end records with repeated span IDs", () => {
  const files = runFiles();
  const start = { event: "start", span: span({ ended_at: null, elapsed_seconds: null, status: "running" }) };
  const end = { event: "end", span: span() };
  files[3].text = `${JSON.stringify(start)}\n{truncated\n${JSON.stringify(end)}\n`;
  const result = parseFiles(files);
  const run = firstRun(result);
  assert.deepEqual(run.journal, [start, end]);
  assert.equal(run.availability.journal, "partial");
  assert.equal(result.issues.find(item => item.code === "invalid-journal-line").line, 2);
  assert.deepEqual(run.report.trace, trace());
});

test("journal span identity conflict is not attached as the report's evidence", () => {
  const files = runFiles();
  files[3].text = JSON.stringify({ event: "end", span: span({ name: "other-call" }) });
  const run = firstRun(parseFiles(files));
  assert.equal(run.availability.journal, "mismatch");
  assert.deepEqual(run.journal, []);
  assert.ok(run.report);
});

test("duplicate paths cannot silently select an arbitrary source", () => {
  const files = completeFiles();
  files.push({ ...files.find(file => file.path.endsWith("/report.json")) });
  const result = parseFiles(files);
  assert.equal(firstRun(result).availability.report, "duplicate");
  assert.ok(result.issues.some(item => item.code === "duplicate-path"));
});

test("traversal, absolute references, and duplicate run identities are rejected", () => {
  for (const path of ["../escape/report.json", "C:/secret/report.json", "/outside/report.json", "runs/../report.json"]) {
    const result = parseFiles([json("batch-1/batch.json", batch([], { planned_runs: 1, runs: [{ ...batchEntry(), path }] }))]);
    assert.equal(result.batches[0].runs.length, 0);
    assert.ok(result.issues.some(item => item.code === "invalid-batch-entry"));
  }
  const duplicate = batch([], { planned_runs: 2, runs: [batchEntry(), batchEntry()] });
  const result = parseFiles([json("batch-1/batch.json", duplicate), ...runFiles()]);
  assert.equal(result.batches[0].runs.length, 0);
  assert.equal(result.batches[1].source, "standalone");
  assert.equal(result.batches[1].runs.length, 1);
  assert.ok(result.issues.some(item => item.code === "duplicate-run"));
  assert.equal(parseFiles([json("../report.json", report())]).issues[0].code, "unsafe-path");
});

test("unrelated malformed files are ignored and unknown data keys remain safe", () => {
  const value = report();
  value.output = JSON.parse('{"__proto__":{"polluted":true},"constructor":{"prototype":{"polluted":true}},"extra":"<img src=x onerror=alert(1)>"}');
  value.future_metadata = { source: "kept" };
  const result = parseFiles([{ path: "notes.json", text: "not json" }, { path: "table.csv", text: "1,2" }, json("saved.json", value)]);
  assert.equal(result.issues.filter(item => item.code === "invalid-artifact").length, 0);
  assert.equal({}.polluted, undefined);
  assert.equal(Object.hasOwn(firstRun(result).report.output, "__proto__"), true);
  assert.deepEqual(firstRun(result).report.future_metadata, { source: "kept" });
});

test("standalone runs group by source location and suite, never across batch folders", () => {
  const two = report({ run: { ...report().run, id: "run-2", repetition: 2 } });
  const result = parseFiles([...runFiles(), ...runFiles(two), ...runFiles(report(), caseFile(), "different-batch")]);
  assert.equal(result.batches.length, 2);
  assert.equal(result.batches[0].runs.length, 2);
  assert.equal(result.batches[1].runs.length, 1);
});

test("all three duplicate standalone IDs are withheld without hiding unique runs or another source", () => {
  const duplicatePaths = ["source/first.json", "source/second.json", "source/third.json"];
  const unique = report({ run: { ...report().run, id: "unique-run", repetition: 2 } });
  const result = parseFiles([
    json(duplicatePaths[0], report()),
    json("source/unique.json", unique),
    json(duplicatePaths[1], report({ output: { changed: true } })),
    json("another-source/report.json", report()),
    json(duplicatePaths[2], report()),
  ]);
  assert.equal(result.batches.length, 2);
  const sameSource = result.batches.find(item => item.path === "source");
  const anotherSource = result.batches.find(item => item.path === "another-source");
  assert.deepEqual(sameSource.runs.map(run => run.report.run.id), ["unique-run"]);
  assert.deepEqual(anotherSource.runs.map(run => run.report.run.id), ["run-1"]);
  assert.deepEqual(result.issues.filter(item => item.code === "duplicate-run").map(item => item.path), duplicatePaths);
  assert.equal(sameSource.issues.filter(item => item.code === "duplicate-run").length, 3);
  const onlyDuplicates = parseFiles(duplicatePaths.map(path => json(path, report())));
  assert.equal(onlyDuplicates.batches.length, 0);
  assert.equal(onlyDuplicates.issues.filter(item => item.code === "duplicate-run").length, 3);
});

test("only a matching batch suite supplies a missing case, with explicit provenance", () => {
  const files = completeFiles().filter(file => !file.path.endsWith("/case.json"));
  const run = firstRun(parseFiles(files));
  assert.deepEqual(run.case, caseFile());
  assert.equal(run.caseSource, "suite");
  assert.equal(run.availability.case, "missing");
  files.find(file => file.path.endsWith("/suite.json")).text = JSON.stringify({ schema_version: "evaluation-suite-v1", id: "other", cases: [caseFile()] });
  assert.equal(firstRun(parseFiles(files)).case, null);
});

test("BOM and Windows directory separators load the same relative artifacts", () => {
  const files = completeFiles().map(file => ({ path: file.path.replaceAll("/", "\\"), text: `\uFEFF${file.text}` }));
  const result = parseFiles(files);
  assert.equal(result.issues.length, 0);
  assert.equal(firstRun(result).report.run.id, "run-1");
});

test("differing saved run statuses stay visible instead of becoming grades", () => {
  const files = completeFiles();
  const data = JSON.parse(files[0].text); data.runs[0].status = "running"; data.status = "running"; data.ended_at = null;
  files[0].text = JSON.stringify(data);
  const result = parseFiles(files);
  assert.equal(firstRun(result).entry.status, "running");
  assert.equal(firstRun(result).report.run.status, "returned");
  assert.ok(result.issues.some(item => item.code === "status-difference"));
});

test("report roles and workflow link their own State without a direct return or inferred role", () => {
  for (const [unit, target] of [
    ["workflow", "report"], ["agent", "report_selection"],
    ["agent", "report_description"], ["agent", "report_insight"],
  ]) {
    const value = report();
    Object.assign(value.run, {unit, target, role: unit === "agent" ? target : null, dependencies: "stub"});
    value.output = null;
    value.state = {execution: {run_id: value.run.id, status: "partial"}, results: [{decision: "composition"}], response: null};
    const input = caseFile({unit, target, initial: {}, dependencies: "stub"});
    delete input.arguments;
    const loaded = parseFiles(completeFiles([value], [input]));
    assert.deepEqual(loaded.issues, []);
    assert.deepEqual(firstRun(loaded).report, value);
    assert.deepEqual(firstRun(loaded).case, input);
    value.output = {content: "wrong direct return"};
    assert.equal(parseFiles([json("report.json", value)]).batches.length, 0);
  }
  const wrong = report();
  Object.assign(wrong.run, {unit: "workflow", target: "report", role: "report_selection"});
  wrong.output = null;
  assert.equal(parseFiles([json("report.json", wrong)]).batches.length, 0);
});


test("equal readable IDs in separate output directories retain their own assessments", () => {
  const source = scoredFiles(), id = "도구평가_2026-11-12_실행01";
  const oldRoot = source.find(file => file.path.endsWith("/batch.json")).path.replace(/\/batch.json$/, "");
  const copy = parent => {
    let number = 0;
    return source.map(file => {
      const result = {...file, path: `${parent}/${id}${file.path.slice(oldRoot.length)}`};
      if (!file.path.endsWith(".json")) return result;
      const value = JSON.parse(file.text);
      if (value.schema_version === "evaluation-batch-v1") value.id = id;
      if (value.schema_version === "tool-evaluation-v1") {
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


