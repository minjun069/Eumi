"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const Operational = require("./operational.js");
const {agentKey, agents, options, select, summarize, MEASURES, FILTER_KEYS} = Operational;
const run = (elapsed_seconds = 0, overrides = {}) => ({
  unit: "agent", target: "request", started: true, ended: true, outcome: "completed", elapsed_seconds,
  situation: "normal", entry: "initial", environment: "local", data_size: "small", dependencies: "real",
  dong_code: "region-a", month: "2026-01", model_calls: 0, tool_calls: 0, agent_calls: 0,
  node_entries: 0, retries: 0, input_tokens: 0, output_tokens: 0, cost: 0, ...overrides,
});
const emptyStats = {sample_count: 0, missing_count: 0, mean: null, median: null, p95: null, minimum: null, maximum: null};

test("region and month are combined using original runs, including unequal source groups", () => {
  const source = [run(0), run(0), run(0), run(100, {dong_code: "region-b", month: "2026-02"})];
  const selected = select(source, agentKey(source[0]), {dong_code: ["region-a"], month: ["2026-01"]});
  assert.equal(selected.length, 4);
  const actual = summarize(selected).measurements.elapsed_seconds;
  assert.deepEqual(actual, {sample_count: 4, missing_count: 0, mean: 25, median: 0, p95: 100, minimum: 0, maximum: 100});
  assert.notEqual(actual.mean, 50, "do not average the two source group means");
});

test("percentiles use nearest rank and median averages the middle two observations", () => {
  const source = Array.from({length: 20}, (_, index) => run(index + 1)).reverse();
  const actual = summarize(source).measurements.elapsed_seconds;
  assert.equal(actual.mean, 10.5); assert.equal(actual.median, 10.5); assert.equal(actual.p95, 19);
  assert.equal(actual.minimum, 1); assert.equal(actual.maximum, 20);
  assert.equal(summarize([run(8)]).measurements.elapsed_seconds.p95, 8);
});

test("only started, ended non-evaluation-failure runs contribute measurements", () => {
  const source = [run(2), run(4, {outcome: "technical_failure"}), run(100, {outcome: "evaluation_failure"}),
    run(200, {ended: false, outcome: "unfinished"}), run(300, {started: false, ended: false, outcome: "not_started"})];
  const actual = summarize(source);
  assert.equal(actual.started, 4); assert.equal(actual.ended, 3); assert.equal(actual.unfinished, 1);
  assert.equal(actual.measurements.elapsed_seconds.mean, 3);
  assert.equal(actual.measurements.elapsed_seconds.sample_count, 2);
  assert.equal(actual.measurements.elapsed_seconds.missing_count, 0);
  assert.deepEqual(actual.failure_rate, {numerator: 1, denominator: 2, rate: 0.5, unclassified_count: 0, evaluation_failure_count: 1, unfinished_count: 1});
  assert.deepEqual(actual.outcomes.unfinished, {numerator: 1, denominator: 4, rate: 0.25});
  assert.equal(actual.outcomes.not_started, undefined);
  assert.deepEqual(Object.keys(actual.elapsed_by_outcome), ["completed", "technical_failure"]);
  assert.equal(actual.elapsed_by_outcome.technical_failure.mean, 4);
});

test("unclassified outcomes stay in the denominator and make failure rate unavailable", () => {
  const actual = summarize([run(1, {outcome: "technical_failure"}), run(2, {outcome: "unclassified"})]);
  assert.deepEqual(actual.failure_rate, {numerator: 1, denominator: 2, rate: null, unclassified_count: 1, evaluation_failure_count: 0, unfinished_count: 0});
  assert.equal(actual.measurements.elapsed_seconds.sample_count, 2);
  assert.equal(actual.outcomes.unclassified.rate, 0.5);
});

test("zero is measured while null, missing, nonfinite, negative and nonnumeric values are missing", () => {
  const values = [0, 4, null, undefined, NaN, Infinity, -1, "3", false];
  const source = values.map(value => run(1, {input_tokens: value}));
  const actual = summarize(source).measurements;
  assert.deepEqual(actual.input_tokens, {sample_count: 2, missing_count: 7, mean: 2, median: 2, p95: 4, minimum: 0, maximum: 4});
  assert.equal(actual.output_tokens.sample_count, 9);
  assert.equal(actual.output_tokens.mean, 0);
  assert.equal(actual.cost.missing_count, 0);
  const extreme = summarize([run(Number.MAX_VALUE), run(Number.MAX_VALUE)]).measurements.elapsed_seconds;
  assert.equal(extreme.mean, Number.MAX_VALUE); assert.equal(extreme.median, Number.MAX_VALUE);
});

test("choices use OR within each filter and AND across filter groups", () => {
  const source = [run(1), run(2, {situation: "fault"}), run(3, {entry: "reentry"}),
    run(4, {dependencies: "stub"}), run(5, {situation: "limit_cancel"}), run(6, {environment: "remote"})];
  const selected = select(source, null, {situation: ["normal", "fault"], entry: ["initial"], dependencies: ["real"], environment: ["local"], data_size: []});
  assert.deepEqual(selected.map(item => item.elapsed_seconds), [1, 2]);
  assert.deepEqual(select(source, "all", {}).map(item => item.elapsed_seconds), [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(select(source, null, {situation: ["unknown"]}), []);
  assert.deepEqual(FILTER_KEYS, ["situation", "entry", "environment", "data_size", "dependencies"]);
});

test("filter options preserve null, empty strings and source spelling without duplicates", () => {
  const source = [run(1, {environment: null}), run(2, {environment: undefined}), run(3, {environment: ""}), run(4, {environment: "local"}), run(5, {environment: "local"})];
  assert.deepEqual(options(source, "environment"), [null, "", "local"]);
  assert.deepEqual(options(source, "dong_code"), []);
  assert.deepEqual(select(source, null, {environment: [null]}).map(item => item.elapsed_seconds), [1, 2]);
  assert.deepEqual(select(source, null, {environment: [""]}).map(item => item.elapsed_seconds), [3]);
  assert.deepEqual(select(source, null, {environment: [null, "local"]}).map(item => item.elapsed_seconds), [1, 2, 4, 5]);
});

test("agent identity includes both unit and target while repeated conditions stay one agent", () => {
  const source = [run(1), run(2, {month: "other"}), run(3, {target: "report", unit: "workflow"}), run(4, {target: "report", unit: "agent"}), run(5, {target: "interpretation"})];
  assert.equal(agents(source).length, 4);
  assert.deepEqual(agents(source)[0], {key: '["agent","request"]', unit: "agent", target: "request"});
  assert.deepEqual(select(source, agentKey(source[2]), {}).map(item => item.elapsed_seconds), [3]);
  assert.deepEqual(select(source, agentKey(source[3]), {}).map(item => item.elapsed_seconds), [4]);
});

test("an empty selection has zero counts and unavailable statistics and rates", () => {
  const actual = summarize([]);
  assert.equal(actual.started, 0); assert.equal(actual.ended, 0); assert.equal(actual.unfinished, 0);
  assert.deepEqual(actual.outcomes, {}); assert.deepEqual(actual.elapsed_by_outcome, {}); assert.deepEqual(actual.runs, []);
  assert.equal(actual.failure_rate.rate, null); assert.equal(actual.failure_rate.denominator, 0);
  for (const key of MEASURES) assert.deepEqual(actual.measurements[key], emptyStats);
  assert.deepEqual(agents([]), []); assert.deepEqual(options([], "entry"), []);
  assert.equal(actual.report_completion, undefined);
});

test("selection and summaries preserve their source and browser API matches CommonJS", () => {
  const source = [run(4), run(0, {situation: "fault"})], filters = {situation: ["fault", "normal"]};
  const before = structuredClone({source, filters});
  source.forEach(Object.freeze); Object.freeze(source); Object.freeze(filters.situation); Object.freeze(filters);
  const selected = select(source, null, filters), actual = summarize(selected);
  agents(source); options(source, "entry");
  assert.deepEqual({source, filters}, before); assert.notEqual(actual.runs, selected);
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve("./operational.js"), "utf8"), context);
  assert.equal(JSON.stringify(context.ExecutionOperational.summarize(selected)), JSON.stringify(actual));
});
