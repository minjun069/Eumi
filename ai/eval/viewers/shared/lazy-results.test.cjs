"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {createHash, webcrypto} = require("node:crypto");
const {create, batchIndex, relative} = require("./lazy-results.js");

const hash = text => createHash("sha256").update(text).digest("hex");
const json = value => JSON.stringify(value);
const batchPath = "eval/outputs/evaluations/batch/batch.json";
const directory = "eval/outputs/evaluations/batch/assessments/score";

function fixture(schema = "node-evaluation-v1") {
  const nodeCollection = ["node-evaluation-v1", "output-evaluation-v1"].includes(schema);
  const check = name => ({check: name, verdict: "실패", reason: "저장된 근거", calls: [{id: "call-one", index: 1,
    row_id: `${name}/general`, judge: {response: {details: [{id: "항목 1", verdict: "실패"}]},
      raw_response: {content: "원문 응답"}, prompt: {messages: [{role: "user", content: "전송한 입력"}],
        criteria: [{text: "원문 기준 A"}, {text: "원문 기준 B"}, {text: "원문 기준 A"}]}}}]});
  const parents = [1, 2].map(rep => ({case_id: "case-one", run_id: `run-${rep}`, repetition: rep,
    ...(nodeCollection ? {node_id: `node-${rep}`, node: "interpret", role: "request"} : {}),
    ...(schema === "output-evaluation-v1" ? {id: `assessment-${rep}`, call_id: "call-one", call_index: 1} : {}),
    checks: [check("N01-O.2"), check("N01-O.1")]}));
  const score = {schema_version: schema, id: "score", batch_id: "batch", suite_id: "suite", criteria: {text: "기준 전체"},
    [nodeCollection ? "assessments" : "runs"]: parents,
    judge_trace: {spans: [{id: "judge", output: {content: "큰 추적 원문"}}]}};
  const files = new Map([[`${directory}.json`, json(score)]]);
  const batch = {schema_version: "evaluation-batch-v1", id: "batch", suite_id: "suite", status: "returned",
    started_at: "2026-11-13T01:00:00Z", ended_at: "2026-11-13T01:02:00Z", planned_runs: 2,
    runs: [1, 2].map(rep => ({case_id: "case-one", run_id: `run-${rep}`, repetition: rep,
      unit: "node", target: "interpret", status: "returned", path: `runs/run-${rep}/report.json`}))};
  const ref = {path: `${directory}.json`, format: "legacy", id: "score", batch_id: "batch", suite_id: "suite", report_schema_version: schema};
  const entry = {path: batchPath, id: "batch", suite_id: "suite", units: ["node"], assessments: [ref], suite_path: null};
  const catalog = {version: "evaluation-viewer-local-v2", generated_at: "now", roots: ["eval/outputs/evaluations"],
    batches: [entry], files: [...files].map(([path, text]) => ({path, size_bytes: Buffer.byteLength(text)})), scenario_index: null, issues: []};
  files.set(batchPath, json(batch));
  files.set("eval/outputs/evaluation-viewer/catalog.json", json(catalog));
  for (const run of batch.runs) {
    files.set(`eval/outputs/evaluations/batch/${run.path}`, json({schema_version: "evaluation-run-v1", run: {...run, id: run.run_id,
      suite_id: "suite", role: "request", dependencies: "real"}, output: {request: {goal: "확인"}}, trace: {spans: [{id: "embedded"}]}}));
    files.set(`eval/outputs/evaluations/batch/runs/${run.run_id}/case.json`, json({id: run.case_id, unit: "node", target: "interpret", role: "request", initial: {}}));
  }
  return {files, entry, ref, batch, score};
}
function transport(files, options = {}) {
  const calls = [];
  const fetch = async (url, opts) => {
    const path = new URL(url).pathname.slice("/ai/".length).split("/").map(decodeURIComponent).join("/");
    calls.push({path, url, opts});
    return new Response(files.get(path) ?? "missing", {status: files.has(path) ? 200 : 404});
  };
  return {calls, client: create({baseURL: "http://localhost/ai/", fetch, crypto: webcrypto, ...options})};
}

test("catalog and batch selection do not fetch any run, case, suite or assessment body", async () => {
  const data = fixture(), before = structuredClone(data.files), {client, calls} = transport(data.files);
  const catalog = await client.catalog();
  assert.deepEqual(calls.map(call => call.path), ["eval/outputs/evaluation-viewer/catalog.json"]);
  const initial = batchIndex(catalog.batches[0]);
  assert.equal(initial.lazy, true); assert.equal(initial.runs.length, 0);
  const batch = await client.batch(catalog.batches[0]);
  assert.deepEqual(calls.map(call => call.path), ["eval/outputs/evaluation-viewer/catalog.json", batchPath]);
  assert.deepEqual(batch.report, data.batch); assert.equal(batch.runs.length, 2);
  assert.equal(batch.runs[0].report, null); assert.equal(batch.runs[0].entry.run_id, "run-1");
  assert.equal(batch.assessments[0].lazy, true); assert.equal(batch.assessments[0].report.id, "score");
  assert.deepEqual(data.files, before);
});



test("only selected run report and case are read; standalone trace and run manifest wait for explicit raw reads", async () => {
  const data = fixture(), {client, calls} = transport(data.files);
  const batch = await client.batch(data.entry), run = await client.run(batch, batch.runs[1]);
  assert.deepEqual(calls.slice(1).map(call => call.path).sort(), ["case.json", "report.json"].map(name => `eval/outputs/evaluations/batch/runs/run-2/${name}`));
  assert.equal(run.report.run.id, "run-2"); assert.equal(run.case.id, "case-one");
  assert.equal(run.trace, null); assert.equal(run.manifest, null); assert.equal(run.lazy, false);
  assert.equal(run.caseSource, "case");
  assert.deepEqual(run.availability, {report: "loaded", case: "loaded", manifest: "unloaded", journal: "unloaded"});
  assert.ok(!calls.some(call => call.path.includes("run-1/")));
  const tracePath = "eval/outputs/evaluations/batch/runs/run-2/trace.jsonl";
  data.files.set(tracePath, '{"event":"start"}\n');
  assert.deepEqual(await client.raw(tracePath), {path: tracePath, text: '{"event":"start"}\n'});
});

test("missing run case is reported without reading the complete suite or treating it as a parse failure", async () => {
  const data = fixture(); data.files.delete("eval/outputs/evaluations/batch/runs/run-1/case.json");
  const {client, calls} = transport(data.files), batch = await client.batch(data.entry);
  const run = await client.run(batch, batch.runs[0]);
  assert.equal(run.case, null); assert.equal(run.report.run.id, "run-1");
  assert.equal(run.issues[0].code, "not-found"); assert.equal(calls.length, 3);
});

for (const [kind, fetch, code] of [
  ["missing", async () => new Response("missing", {status: 404}), "not-found"],
  ["server", async () => new Response("error", {status: 503}), "http"],
  ["connection", async () => { throw new TypeError("disconnected"); }, "network"],
  ["json", async () => new Response("{"), "parse"],
  ["utf8", async () => new Response(new Uint8Array([0xff])), "parse"],
]) test(`${kind} failures have a distinct actionable error`, async () => {
  const client = create({baseURL: "http://localhost/ai/", fetch});
  await assert.rejects(client.catalog("catalog.json"), error => error.code === code && error.path === "catalog.json");
  assert.equal(client.cacheInfo().entries, 0);
});

test("unsafe paths are rejected before fetch and literal escaped filenames stay inside the base", async () => {
  const {client, calls} = transport(new Map());
  for (const path of ["../secret", "/secret", "https://example.com/x", "a\\b", "a:b", "a//b", "a/./b", "a/../b", "a\0b"]) {
    assert.throws(() => relative(path), error => error.code === "unsafe-path");
    await assert.rejects(client.raw(path), error => error.code === "unsafe-path");
  }
  assert.equal(calls.length, 0);
  assert.equal(client.url("cases/%2E%2E/a%2Fb.json"), "http://localhost/ai/cases/%252E%252E/a%252Fb.json");
  assert.equal(client.url("한글/가?나#다.json"), "http://localhost/ai/%ED%95%9C%EA%B8%80/%EA%B0%80%3F%EB%82%98%23%EB%8B%A4.json");
  assert.throws(() => create({baseURL: "file:///C:/ai/"}), error => error.code === "unsupported-protocol");
});

test("a replaced selection aborts its request and a late response cannot populate the cache", async () => {
  let finish;
  const client = create({baseURL: "http://localhost/ai/", fetch: () => new Promise(resolve => { finish = resolve; })});
  const old = client.begin("detail"), pending = client.raw("old.json", {signal: old.signal});
  const current = client.begin("detail");
  assert.equal(old.current(), false); assert.equal(old.signal.aborted, true); assert.equal(current.current(), true);
  finish(new Response("old response"));
  await assert.rejects(pending, {name: "AbortError"});
  assert.equal(client.cacheInfo().entries, 0);
  const other = client.begin("batch"); assert.equal(current.current(), true); assert.equal(other.current(), true);
  client.dispose(); assert.equal(current.current(), false); assert.equal(other.current(), false);
});

test("already cancelled requests never use cached content or fetch another file", async () => {
  const {client, calls} = transport(new Map([["data.json", "value"]]));
  await client.raw("data.json"); const selection = client.begin(); selection.cancel();
  await assert.rejects(client.raw("data.json", {signal: selection.signal}), {name: "AbortError"});
  assert.equal(calls.length, 1);
});

test("LRU cache bounds both total original bytes and entry count", async () => {
  const files = new Map([["a", "1234"], ["b", "5678"], ["c", "90ab"], ["large", "123456789"]]);
  const {client, calls} = transport(files, {maxBytes: 8, maxEntries: 2});
  await client.raw("a"); await client.raw("b"); await client.raw("a"); await client.raw("c");
  assert.equal(calls.length, 3); assert.deepEqual(client.cacheInfo(), {entries: 2, bytes: 8, maxEntries: 2, maxBytes: 8});
  await client.raw("b"); assert.equal(calls.length, 4);
  await client.raw("large"); await client.raw("large"); assert.equal(calls.length, 6);
  assert.equal(client.cacheInfo().bytes, 8); client.clear(); assert.equal(client.cacheInfo().bytes, 0);
});

test("large streaming files stop at the configured limit and remain directly downloadable", async () => {
  let cancelled = false, pulls = 0;
  const client = create({baseURL: "http://localhost/ai/", maxFileBytes: 8,
    fetch: async () => new Response(new ReadableStream({pull(controller) {
      pulls++; controller.enqueue(new Uint8Array([65, 66, 67, 68, 69]));
    }, cancel() { cancelled = true; }}))});
  await assert.rejects(client.raw("huge.json"), error => error.code === "too-large" && error.path === "huge.json");
  assert.equal(cancelled, true); assert.ok(pulls < 5); assert.equal(client.cacheInfo().entries, 0);
  assert.equal(client.url("huge.json"), "http://localhost/ai/huge.json");
});




test("a UTF-8 BOM and raw values survive plain assessment loading", async () => {
  const data = fixture(); data.files.set(data.ref.path, "\uFEFF" + data.files.get(data.ref.path));
  const {client} = transport(data.files);
  assert.deepEqual((await client.assessment(data.ref)).report, data.score);
});

test("a response from a different batch cannot replace the selected assessment", async () => {
  const data = fixture(), manifest = JSON.parse(data.files.get(`${directory}.json`));
  manifest.batch_id = "other"; data.files.set(`${directory}.json`, json(manifest));
  const {client} = transport(data.files); await assert.rejects(client.assessment(data.ref), error => error.code === "identity");
});
