"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const {createHash, webcrypto} = require("node:crypto");
const Automatic = require("./automatic.js"), Lazy = require("../shared/lazy-results.js");
const Data = require("./data.js");
const {fixture: baseFixture} = require("../shared/lazy-ui-fixtures.cjs");
require("./samples.js");
const samples = globalThis.ExecutionEvaluationSamples().files;
function fixture() {
  const f = baseFixture(samples, "execution-evaluation-v1");
  f.entry.assessments = f.entry.assessments.filter(ref => Boolean(ref.report_schema_version));
  f.client = f.lazy.create({baseURL:"http://localhost/", maxFileBytes:128*1048576, maxBytes:32*1048576, maxEntries:4096, deduplicate:true});
  return f;
}
test("complete batch loading preserves all saved verdicts, criteria, inputs and trace snapshots", async () => {
  const f = fixture(), original = Data.parseFiles(samples).batches.find(batch => batch.report.id === f.entry.id);
  const loaded = await Automatic.load(f.client, f.entry, {files:f.index.files});
  assert.deepEqual(loaded.readErrors, []);
  for (const record of loaded.assessments) {
    assert.equal(record.partial, false);
    assert.deepEqual(record.report, original.assessments.find(item => item.report.id === record.report.id).report);
  }
  for (const run of loaded.runs) {
    const expected = original.runs.find(item => item.report?.run.id === run.report?.run.id);
    assert.deepEqual(run.report, expected.report);
    assert.deepEqual(run.case, expected.case);
    assert.deepEqual(run.manifest, expected.manifest);
    assert.equal(run.availability.journal, "loaded");
  }
  assert.deepEqual(loaded.suite, original.suite);
});
test("aborting a batch stops subsequent jobs and rejects instead of publishing a partial selection", async () => {
  const f = fixture(), controller = new AbortController();
  await assert.rejects(Automatic.load(f.client, f.entry, {files:f.index.files, signal:controller.signal,
    onProgress: ({completed}) => { if (completed) controller.abort(); }}), {name:"AbortError"});
  assert.ok(!f.calls.some(path => path.endsWith("/summary.json")));
});
test("execution HTTP limit accepts an 82 MiB legacy file and still rejects files beyond 128 MiB", async () => {
  let declared = 82 * 1048576;
  const client = Lazy.create({baseURL:"http://localhost/", maxFileBytes:128*1048576, crypto:webcrypto,
    fetch:async () => ({ok:true,status:200,headers:{get:()=>String(declared)},text:async()=>'{"existing":"log"}'})});
  assert.equal((await client.raw("accepted.json")).text, '{"existing":"log"}');
  declared = 129 * 1048576;
  await assert.rejects(client.raw("rejected.json"), error => error.code === "too-large");
});
