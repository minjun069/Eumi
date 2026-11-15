"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {parseFiles, forCase} = require("./scenarios.js");
const json = (path, value) => ({path, text: JSON.stringify(value)});

function fixture() {
  const record = {id: "scenario-1", title: "상위에서 하위를 호출하고 반환", steps: [
    {step_id: "s1", case_id: "parent-call", node: "act", role: "request", frame: "root", boundary_before: {kind: "entry", from_step: null}},
    {step_id: "s2", case_id: "child-write", node: "compose", role: "interpretation", frame: "child", boundary_before: {kind: "call", from_step: "s1"}},
    {step_id: "s3", case_id: "parent-resume", node: "decide", role: "request", frame: "root", boundary_before: {kind: "return", from_step: "s1"}},
  ], preserved: {unknown: ["원문 보존"]}};
  const index = {schema_version: "node-scenarios-v4", scenarios: [{id: record.id, title: record.title, file: "scenarios/path.json"}],
    case_index: Object.fromEntries(record.steps.map(step => [step.case_id, {node: step.node, role: step.role, usages: [{scenario_id: record.id, step_id: step.step_id}]}]))};
  const files = () => [json("nodes/scenarios.json", index), json("nodes/scenarios/path.json", record)];
  return {index, record, files};
}

test("preserves ordered scenario, return boundary and exact selected occurrence", () => {
  const source = fixture(), files = source.files(), before = JSON.stringify(files);
  const catalog = parseFiles(files);
  const matches = forCase(catalog, "parent-resume", "decide", "request");
  assert.equal(matches.length, 1);
  assert.deepEqual(matches[0].scenario, source.record);
  assert.deepEqual(matches[0].steps, source.record.steps);
  assert.deepEqual(matches[0].stepIds, ["s3"]);
  assert.equal(matches[0].steps[2].boundary_before.from_step, "s1");
  assert.deepEqual(catalog.issues, []);
  assert.equal(JSON.stringify(files), before);
  assert.deepEqual(forCase(catalog, "parent-resume", "decide", "interpretation"), []);
  assert.deepEqual(forCase(catalog, "parent-resume", "act", "request"), []);
});

test("missing index, missing referenced file and duplicate input paths never invent a flow", () => {
  const source = fixture();
  assert.deepEqual(forCase(parseFiles(source.files().slice(1)), "parent-call", "act", "request"), []);
  const missing = parseFiles(source.files().slice(0, 1));
  assert.equal(missing.scenarios.length, 0);
  assert.equal(missing.issues.length, 1);
  for (const duplicated of [source.files()[0], source.files()[1]]) {
    const catalog = parseFiles([...source.files(), duplicated]);
    assert.deepEqual(forCase(catalog, "parent-call", "act", "request"), []);
    assert.equal(catalog.issues.length, 1);
  }
});

test("rejects duplicate index identities, step identities and reversed mapping mismatches", () => {
  const mutations = [
    source => source.index.scenarios.push({...source.index.scenarios[0]}),
    source => source.record.steps.push({...source.record.steps[0]}),
    source => source.index.case_index["parent-call"].usages[0].step_id = "s9",
    source => source.index.case_index["parent-call"].role = "interpretation",
    source => source.record.steps[0].case_id = "unindexed-case",
    source => source.record.steps[1].boundary_before.from_step = "s9",
    source => source.index.case_index["parent-call"].usages.push({...source.index.case_index["parent-call"].usages[0]}),
    source => source.index.scenarios[0].file = "../outside.json",
  ];
  for (const mutate of mutations) {
    const source = fixture(); mutate(source);
    const catalog = parseFiles(source.files());
    assert.deepEqual(catalog.scenarios, []);
    assert.equal(catalog.issues.length, 1);
  }
});

test("ambiguous case in separate datasets is never assigned to an arbitrary scenario", () => {
  const source = fixture(), files = source.files();
  const catalog = parseFiles([...files, ...files.map(file => ({...file, path: file.path.replace("nodes/", "copy/")}))]);
  assert.deepEqual(forCase(catalog, "parent-call", "act", "request"), []);
  assert.equal(catalog.issues.filter(issue => issue.code === "ambiguous-scenario-case").length, 3);
});

test("supports one case used at multiple exact positions in the same dataset", () => {
  const source = fixture();
  source.record.steps.push({step_id: "s4", case_id: "parent-resume", node: "decide", role: "request", frame: "root", boundary_before: {kind: "next", from_step: "s3"}});
  source.index.case_index["parent-resume"].usages.push({scenario_id: source.record.id, step_id: "s4"});
  const catalog = parseFiles(source.files());
  assert.deepEqual(catalog.issues, []);
  assert.deepEqual(forCase(catalog, "parent-resume", "decide", "request")[0].stepIds, ["s3", "s4"]);
});

test("current 21-scenario dataset maps all 131 cases to their recorded node and role", () => {
  const base = path.join(__dirname, "../../scenarios/nodes");
  const indexText = fs.readFileSync(path.join(base, "scenarios.json"), "utf8");
  const index = JSON.parse(indexText);
  const files = [{path: "nodes/scenarios.json", text: indexText}, ...index.scenarios.map(item => ({path: `nodes/${item.file}`, text: fs.readFileSync(path.join(base, item.file), "utf8")}))];
  const catalog = parseFiles(files);
  assert.deepEqual(catalog.issues, []);
  assert.equal(catalog.scenarios.length, index.scenarios.length);
  let matched = 0;
  for (const [caseId, entry] of Object.entries(index.case_index)) {
    const usages = forCase(catalog, caseId, entry.node, entry.role).flatMap(item => item.stepIds.map(stepId => ({scenario_id: item.scenario.id, step_id: stepId})));
    assert.deepEqual(usages, entry.usages);
    matched += usages.length;
  }
  assert.equal(matched, index.summary.path_node_execution_count);
});
