"use strict";

const Lazy = require("./lazy-results.js");

function fixture(original, schema) {
  const files = structuredClone(original), texts = new Map(files.map(file => [file.path, file.text]));
  const docs = files.flatMap(file => { try { return [{path: file.path, value: JSON.parse(file.text)}]; } catch (_) { return []; } });
  const manifests = docs.filter(item => item.value.schema_version === schema);
  const batchSource = docs.find(item => item.value.schema_version === "evaluation-batch-v1" && manifests.some(manifest => manifest.value.batch_id === item.value.id));
  const directory = batchSource.path.slice(0, batchSource.path.lastIndexOf("/"));
  const assessments = docs.filter(item => /^(node|tool|execution|output)-evaluation-v1$/.test(item.value.schema_version || "") && item.value.batch_id === batchSource.value.id).map(item => ({path: item.path, format: "legacy", id: item.value.id, batch_id: item.value.batch_id, suite_id: item.value.suite_id, assessed_at: item.value.assessed_at, report_schema_version: item.value.schema_version}));
  assessments.sort((a,b) => b.assessed_at.localeCompare(a.assessed_at));
  const legacy = {path: directory + "/assessments/legacy-large.json", format: "legacy"};
  const entry = {path: batchSource.path, ...Object.fromEntries(["id","suite_id","status","started_at","ended_at","planned_runs"].map(key => [key,batchSource.value[key]])), assessments: [...assessments, legacy], suite_path: directory + "/suite.json"};
  const index = {version: "evaluation-viewer-local-v2", generated_at: "2026-11-13T00:00:00Z", batches: [entry], issues: [], files: [...texts].map(([path,text]) => ({path,size_bytes:Buffer.byteLength(text)}))};
  index.files.push({path: legacy.path, size_bytes: 128 * 1048576});
  texts.set("eval/outputs/evaluation-viewer/catalog.json", JSON.stringify(index));
  const calls = [];
  const lazy = {...Lazy, create: options => Lazy.create({...options, crypto: require("node:crypto").webcrypto, fetch: async address => {
    const path = new URL(address).pathname.slice(1).split("/").map(decodeURIComponent).join("/");
    calls.push(path);
    return {ok: texts.has(path), status: texts.has(path) ? 200 : 404, text: async () => texts.get(path)};
  }})};
  return {lazy,index,entry,calls,texts,manifest:manifests.find(item => item.path === assessments.find(ref => ref.report_schema_version === schema).path).value};
}
async function until(predicate) {
  for (let attempt = 0; attempt < 300; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  throw new Error("UI state did not settle");
}
module.exports = {fixture,until};
