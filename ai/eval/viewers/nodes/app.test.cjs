"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {webcrypto, createHash} = require("node:crypto");
const EvaluationNames = require("../shared/record-names.js");
const EvaluationLazy = require("../shared/lazy-results.js");
const EvaluationData = require("./data.js");
const NodeRunMetrics = require("./run-metrics.js");
const NodeAggregateMetrics = require("./aggregate-metrics.js");
const NodeScenarios = require("./scenarios.js");
const NodeValues = require("./structured-value.js");
const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
require("./samples.js");
const samples = globalThis.EvaluationSamples;
const {assessmentFiles, copyFiles} = require("../shared/assessment-fixtures.cjs");
const catalog = EvaluationData.parseFiles(samples.files);

// Exercise the actual UI event handlers and rendered content without replacing
// their navigation logic. Seed-only tests bypass the HTTP bootstrap, not rendering.
function harness(initial = catalog, {width = 1440, remote, autoOnly = false, scenarioFiles = []} = {}) {
  const elements = new Map();
  const documentListeners = new Map();
  const downloaded = [];
  function element(selector) {
    if (!elements.has(selector)) {
      const classes = new Set();
      const properties = new Map();
      elements.set(selector, {
        innerHTML: "", textContent: "", value: "", hidden: false, disabled: false,
        id: selector.startsWith("#") ? selector.slice(1) : "", isConnected: true,
        dataset: {}, attributes: {}, listeners: new Map(), focused: 0, scrolled: 0,
        rect: {left: 0, width: 1000, top: 0, height: 600}, captured: new Set(),
        classList: {
          toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
          contains(name) { return classes.has(name); },
          add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
        },
        style: {setProperty(name, value) { properties.set(name, value); }, getPropertyValue(name) { return properties.get(name) || ""; }},
        addEventListener(type, listener) { this.listeners.set(type, listener); },
        setAttribute(name, value) { this.attributes[name] = value; },
        getAttribute(name) { return this.attributes[name]; },
        getBoundingClientRect() { return this.rect; },
        setPointerCapture(pointerId) { this.captured.add(pointerId); },
        releasePointerCapture(pointerId) { this.captured.delete(pointerId); },
        hasPointerCapture(pointerId) { return this.captured.has(pointerId); },
        closest(query) {
          if (query === "#case-splitter") return this.id === "case-splitter" ? this : null;
          if ((query.includes("data-aggregate-role") && this.dataset.aggregateRole) ||
              (query.includes("data-case-tab") && this.dataset.caseTab) ||
              (query.includes("data-aggregate-tab") && this.dataset.aggregateTab)) return this;
          return null;
        },
        matches(query) { return query === selector; },
        focus() { this.focused++; },
        scrollIntoView() { this.scrolled++; },
        click() {},
      });
    }
    return elements.get(selector);
  }
  const pageTabs = ["cases", "aggregate"].map(page => {
    const button = element(`[data-page=${page}]`);
    button.dataset.page = page;
    return button;
  });
  const document = {
    baseURI: "http://localhost/eval/viewers/nodes/",
    createElement: () => ({click() { downloaded.push({name: this.download, url: this.href}); }}),
    querySelector: element,
    querySelectorAll: selector => selector === ".page-tabs [data-page]" ? pageTabs : [],
    addEventListener: (type, listener) => documentListeners.set(type, listener),
  };
  const loadedCatalog = autoOnly ? undefined : structuredClone(initial);
  const boot = `ui.catalog = __initial; ui.batch = 0; ui.assessmentKey = null;
    ui.scenarios = NodeScenarios.parseFiles(__scenarioFiles); resetSelection();
    ui.page = currentBatch().source === "assessment" ? "aggregate" : "cases"; render();`;
  assert.ok(source.includes("  loadLocalResults();"), "application has its HTTP bootstrap");
  vm.runInNewContext(autoOnly ? source : source.replace("  loadLocalResults();", boot), {
    document, URL, Blob, setTimeout, EvaluationNames, NodeRunMetrics, NodeAggregateMetrics, NodeScenarios, NodeValues,
    __initial: loadedCatalog, __scenarioFiles: scenarioFiles,
    matchMedia: query => ({matches: width <= Number(query.match(/max-width:\s*(\d+)px/)[1]), addEventListener() {}}),
    location: {protocol: "http:"},
    ...(remote ? {EvaluationLazy: {...EvaluationLazy, create: options => EvaluationLazy.create({...options, fetch: remote.fetch, crypto: webcrypto})}} : {}),
    EvaluationData,
  });
  function trigger(selector, type, value) {
    const node = element(selector);
    if (value !== undefined) node.value = value;
    return node.listeners.get(type)({ target: node });
  }
  function click(dataset) {
    return documentListeners.get("click")({ target: { closest: () => ({ dataset, disabled: false }) } });
  }
  return { element, trigger, click, downloaded, loadedCatalog: () => loadedCatalog,
    change(id, value) { return documentListeners.get("change")({target: {id, value}}); },
    dispatch(type, selector, fields = {}) {
      let prevented = false;
      const handler = documentListeners.get(type);
      assert.ok(handler, `${type} is registered`);
      handler({target: element(selector), ...fields, preventDefault() { prevented = true; }});
      return prevented;
    },
  };
}

function scoredCatalog() {
  return {batches: [structuredClone(catalog.batches.find(b => b.assessments?.length))], issues: []};
}

const catalogPath = "eval/outputs/evaluation-viewer/catalog.json";

function remoteFixture(files = copyFiles(samples.files), {scenarioIndex = null} = {}) {
  const original = new Map(files.map(file => [file.path, file.text]));
  const metadata = (value, keys) => Object.fromEntries(keys.filter(key => Object.hasOwn(value, key)).map(key => [key, value[key]]));
  const batches = files.filter(file => file.path.endsWith("/batch.json")).map(file => {
    const batch = JSON.parse(file.text), directory = file.path.slice(0, -"batch.json".length);
    const assessments = files.filter(item => item.path.startsWith(`${directory}assessments/`) && /^(node|tool|execution|output)-evaluation-v1$/.test(JSON.parse(item.text).schema_version || "")).map(item => {
      const manifest = JSON.parse(item.text);
      return {path: item.path, format: "legacy", report_schema_version: manifest.schema_version, ...metadata(manifest, ["id", "batch_id", "suite_id", "report_schema_version", "assessed_at", "status", "method", "judge_model"])};
    });
    return {path: file.path, suite_path: `${directory}suite.json`, units: [...new Set(batch.runs.map(run => run.unit))],
      ...metadata(batch, ["id", "suite_id", "status", "started_at", "ended_at", "planned_runs"]), registered_runs: batch.runs.length, assessments};
  });
  const index = {version: "evaluation-viewer-local-v2", generated_at: "2026-11-13T12:00:00Z", roots: [], batches,
    files: files.map(file => ({path: file.path, size_bytes: Buffer.byteLength(file.text), modified_at: "2026-11-13T12:00:00Z"})),
    scenario_index: scenarioIndex, issues: []};
  const sources = new Map([...original, [catalogPath, JSON.stringify(index)]]), requests = [];
  const selected = [...(batches[0]?.assessments || [])].sort((a, b) => Date.parse(b.assessed_at) - Date.parse(a.assessed_at))[0];
  return {files, sources, original, index, requests, selected,
    initialPaths: selected ? [catalogPath, batches[0].path, selected.path] : [catalogPath],
    async fetch(url) {
      const filePath = new URL(url).pathname.slice(1).split("/").map(decodeURIComponent).join("/");
      requests.push(filePath);
      const value = sources.get(filePath);
      if (value instanceof Error) throw value;
      return new Response(value ?? "File not found", {status: value === undefined ? 404 : 200});
    },
    assertPreserved() {
      for (const [filePath, text] of original) assert.equal(sources.get(filePath), text, filePath);
    },
  };
}

function automaticPaths(remote, batch = remote.index.batches[0], ref = remote.selected) {
  const directory = batch.path.replace(/batch\.json$/, ""), report = JSON.parse(remote.sources.get(batch.path));
  const paths = [catalogPath, batch.path, batch.suite_path];
  for (const run of report.runs) paths.push(directory + run.path, directory + run.path.replace(/report\.json$/, "case.json"));
  if (ref) {
    paths.push(ref.path);
  }
  if (remote.index.scenario_index) {
    const path = remote.index.scenario_index, index = JSON.parse(remote.sources.get(path));
    const wanted = new Set(report.runs.flatMap(r => index.case_index[r.case_id]?.usages.map(u => u.scenario_id) || []));
    paths.push(path, ...index.scenarios.filter(r => wanted.has(r.id)).map(r => path.replace(/[^/]+$/, r.file)));
  }
  return [...new Set(paths.filter(Boolean))].sort();
}
function assertRequests(remote, expected) {
  assert.deepEqual([...new Set(remote.requests)].sort(), [...new Set(expected)].sort());
}

function legacyRemoteFixture() {
  const remote = remoteFixture(samples.files);
  for (const batch of remote.index.batches) {
    const directory = batch.path.replace(/batch\.json$/, "assessments/");
    batch.assessments = samples.files.filter(file => file.path.startsWith(directory) &&
      file.path.endsWith(".json") && JSON.parse(file.text).schema_version === "node-evaluation-v1")
      .map(file => ({path: file.path, format: "legacy"}));
  }
  remote.sources.set(catalogPath, JSON.stringify(remote.index));
  return remote;
}

async function waitFor(predicate, description) {
  const deadline = Date.now() + 3000;
  while (!predicate()) {
    assert.ok(Date.now() < deadline, `Timed out: ${description}`);
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}

async function waitForRemote(app) {
  await waitFor(() => app.element("#notice").hidden && /채점 정보/.test(app.element("#aggregate-page").innerHTML), "remote summary ready without a success notice");
}

test("removed upload, sample and redundant navigation controls are absent", () => {
  const index = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  assert.doesNotMatch(index, /id="(?:sample-button|sample-notice|files-button|folder-button|files-input|folder-input|welcome-open|local-status|scope-badge|breadcrumb|target-picker|target-count)"/);
  assert.match(index, /<nav\b[^>]*id="target-nav"/);
  assert.doesNotMatch(index, /<input[^>]*type="file"|samples\.js|<th>실행<\/th>/);
  assert.doesNotMatch(source, /function (?:acceptFiles|loadFiles)\(|#(?:sample-button|files-button|folder-button|files-input|folder-input|local-status)/);
  const app = harness(scoredCatalog());
  assert.doesNotMatch(source, /#breadcrumb/);
  assert.doesNotMatch(app.element("#target-nav").innerHTML, / · 노드/);
  assert.doesNotMatch(app.element("#assessment-toolbar").innerHTML, /<p class="hint">/);
  const rows = app.element("#case-rows").innerHTML;
  for (const row of rows.matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/g)) assert.equal((row[1].match(/<td\b/g) || []).length, 1);
});

test("case checks keep prompts without source-location text while aggregate retains original evidence", () => {
  const score = structuredClone(scoredCatalog().batches[0].assessments[0].report);
  for (const assessment of score.assessments.filter(item => item.case_id === "interpret-pass")) {
    const check = assessment.checks.find(item => item.check === "N01-O.2");
    check.calls[0].judge.prompt.messages = [{role: "user", content: `전송 원문 ${assessment.repetition} <script>data</script>`}];
    check.calls[0].judge.raw_response = {text: `SDK 원응답 ${assessment.repetition}`, extra: {value: false}};
    check.calls[0].judge.response = {details: [{id: "항목 1", verdict: "통과", reason: `검증 전 응답 ${assessment.repetition}`, evidence: ["출력 1"]}]};
    check.calls[0].judge.model_usage = {input_tokens: 111 + assessment.repetition, output_tokens: 0};
  }
  const execution = samples.files.filter(file => { try { return JSON.parse(file.text).schema_version !== "node-evaluation-v1"; } catch (_) { return true; } });
  const files = [...execution, ...assessmentFiles(score, "sample/assessments/ui-raw")];
  const data = EvaluationData.parseFiles(files), before = structuredClone(data), app = harness(data);
  const run = data.batches.find(item => item.assessments.length).runs.find(item => item.report.run.case_id === "interpret-pass");
  app.click({case: caseKey(run)});
  for (const repetition of [1, 2]) {
    app.change("run-select", data.batches.find(item => item.assessments.length).runs.find(item => item.report.run.case_id === "interpret-pass" && item.report.run.repetition === repetition).key);
    const html = app.element("#case-detail").innerHTML;
    assert.doesNotMatch(html, /검사 원본 파일:|sample\/assessments\/ui-raw\/cases\//);
    assert.match(html, /class="check-prompt"/);
    assert.ok(html.includes(`전송 원문 ${repetition} &lt;script&gt;data&lt;/script&gt;`));
    assert.doesNotMatch(html, /<script>|class="check-model-records"|호출별 판정·평가 모델 기록|SDK 원응답|검증 전 응답|평가 모델 사용량|평가 모델 전송 메시지/);
  }
  app.click({page: "aggregate"});
  app.click({aggregateRole: keyFor("interpret", "interpretation"), roleMetric: "functional"});
  assert.match(app.element("#aggregate-page").innerHTML, /평가 모델 원응답 · SDK/);
  assert.match(app.element("#aggregate-page").innerHTML, /SDK 원응답 1/);
  assert.deepEqual(app.loadedCatalog(), before);
});

function unscoredCatalog() {
  const data = scoredCatalog();
  data.batches[0].assessments = [];
  return data;
}

test("prepared and cancelled judge messages are not presented as completed transmissions", () => {
  for (const state of [false, true]) {
    const data = scoredCatalog(), row = data.batches[0].assessments[0].report.assessments.find(item => item.case_id === "interpret-pass" && item.repetition === 1);
    const check = row.checks.find(item => item.check === "N01-O.2"), judge = check.calls[0].judge;
    judge.executed = state;
    if (state) judge.error = {type: "CancelledError"};
    else delete judge.error;
    judge.prompt.messages = [{role: "user", content: "보존된 준비 메시지"}];
    judge.raw_response = null;
    const app = harness(data);
    app.click({case: caseKey(runFor(data, "interpret-pass"))});
    const card = markedElement(app.element("#case-detail").innerHTML, "data-check", check.check);
    assert.ok(card.includes("보존된 준비 메시지"));
    if (!state) assert.match(card, /준비된 평가 프롬프트 · 평가 모델 미실행/);
    assert.doesNotMatch(card, /평가 모델 전송 메시지/);
  }
});

const keyFor = (node, role, counted = true) => JSON.stringify([counted ? "node" : "selection", node, role ?? null]);
const caseKey = run => JSON.stringify([run.report.run.case_id, run.report.run.unit, run.report.run.target]);
const runFor = (data, id, repetition = 1) => data.batches[0].runs.find(run => run.report.run.case_id === id && run.report.run.repetition === repetition);
const escapeHTML = value => String(value).replace(/[&<>"']/g, character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character]));
function ioSection(app, label) {
  const sectionClass = {"입력": "case-input", "출력": "case-output"}[label];
  return classElement(app.element("#case-detail").innerHTML, sectionClass);
}
function classElement(html, className) {
  const opening = [...html.matchAll(/<[a-z][a-z0-9]*\b[^>]*class="([^"]+)"[^>]*>/g)].find(match => match[1].split(/\s+/).includes(className));
  assert.ok(opening, `${className} section is available`);
  return markedElement(html.slice(opening.index), "class", opening[1]);
}
function markedElement(html, attribute, value) {
  const anchor = html.indexOf(`${attribute}="${value}"`);
  assert.ok(anchor >= 0, `${attribute}=${value} is present`);
  return balancedElement(html.slice(html.lastIndexOf("<", anchor)));
}
function balancedElement(content) {
  const tag = content.match(/^<([a-z][a-z0-9]*)\b/)[1];
  let depth = 0;
  for (const match of content.matchAll(new RegExp(`</?${tag}\\b[^>]*>`, "g"))) {
    depth += match[0].startsWith("</") ? -1 : 1;
    if (depth === 0) return content.slice(0, match.index + match[0].length);
  }
  assert.fail(`${tag} must have a closing element`);
}
function aggregatePanel(app, tab) {
  return markedElement(app.element("#aggregate-page").innerHTML, "id", `aggregate-panel-${tab}`);
}
function assertAggregateTab(app, selected) {
  const html = app.element("#aggregate-page").innerHTML;
  assert.match(classElement(html, "aggregate-tabs"), /role="tablist"[^>]*aria-label="전체 집계"/);
  assert.deepEqual([...html.matchAll(/data-aggregate-tab="([^"]+)"/g)].map(match => match[1]), ["functional", "operational", "info"]);
  for (const [key, label] of [["functional", "기능 지표"], ["operational", "운영 지표"], ["info", "채점 정보"]]) {
    const button = markedElement(html, "id", `aggregate-tab-${key}`);
    assert.ok(button.includes(`>${label}</button>`));
    assert.match(button, /role="tab"/);
    assert.ok(button.includes(`aria-controls="aggregate-panel-${key}"`));
    assert.ok(button.includes(`aria-selected="${key === selected}"`));
    assert.ok(button.includes(`tabindex="${key === selected ? 0 : -1}"`));
    const opening = aggregatePanel(app, key).match(/^<section\b[^>]*>/)[0];
    assert.match(opening, /role="tabpanel"/);
    assert.ok(opening.includes(`aria-labelledby="aggregate-tab-${key}"`));
    assert.equal(/\shidden(?:\s|=|>)/.test(opening), key !== selected, `${key} panel visibility`);
  }
}
function assertAllCaseFunctionalRollup(app, functional) {
  const summary = classElement(aggregatePanel(app, "functional"), "functional-rollup");
  const items = functional.cases.items, passed = items.filter(item => item.verdict === "통과").length, failed = items.filter(item => item.verdict === "실패").length;
  const completed = items.filter(item => item.complete).length;
  const expectedRate = items.length ? `${Number((passed * 100 / items.length).toFixed(3))}%` : "산출 불가";
  const expectedVerdict = failed ? "실패" : items.length && passed === items.length && completed === items.length ? "통과" : "미판정";
  assert.ok(summary.includes(`<strong>${expectedRate}</strong>`), "pass rate includes every case, including pending and optional cases");
  assert.ok(summary.includes(`>${expectedVerdict}</span>`), "overall verdict follows all case results and completion");
  const counts = classElement(summary, "case-verdict-counts");
  for (const [label, count] of [["통과", passed], ["실패", failed], ["미판정", items.length - passed - failed]]) assert.ok(counts.includes(`<span>${label} ${count}</span>`));
  assert.equal(classElement(summary, "verification-progress"), `<p class="verification-progress">검증 완료 ${completed} / 전체 ${items.length}</p>`);
  return summary;
}
function assertAggregateRole(app, nodes, selectedIndex) {
  const choices = [{key: "all"}, ...nodes.map(node => ({key: keyFor(node.node, node.role)}))];
  for (const metric of ["functional", "operational"]) {
    const panel = aggregatePanel(app, metric), tabs = classElement(panel, "aggregate-role-tabs");
    assert.match(tabs, /role="tablist"/);
    assert.equal((tabs.match(/data-aggregate-role=/g) || []).length, choices.length);
    assert.match(markedElement(tabs, "id", `aggregate-role-${metric}-0`), />전체<\/button>$/);
    for (const [index, choice] of choices.entries()) {
      const id = `aggregate-role-${metric}-${index}`, button = markedElement(tabs, "id", id);
      assert.ok(button.includes(`data-aggregate-role="${escapeHTML(choice.key)}"`));
      assert.ok(button.includes(`aria-selected="${index === selectedIndex + 1}"`));
      assert.ok(button.includes(`tabindex="${index === selectedIndex + 1 ? 0 : -1}"`));
      assert.ok(button.includes(`aria-controls="${id}-panel"`));
      const content = markedElement(panel, "id", `${id}-panel`), opening = content.match(/^<section\b[^>]*>/)[0];
      assert.match(opening, /role="tabpanel"/);
      assert.ok(opening.includes(`aria-labelledby="${id}"`));
      assert.equal(/\shidden(?:\s|=|>)/.test(opening), index !== selectedIndex + 1);
      if (index !== selectedIndex + 1) assert.match(content, /^<section[^>]*><\/section>$/, "unselected roles cannot leak another role's metrics");
    }
  }
}
function metricRow(html, label) {
  const anchor = html.indexOf(`<th scope="row">${label}</th>`);
  assert.ok(anchor >= 0, `${label} has its own metric row`);
  return balancedElement(html.slice(html.lastIndexOf("<tr", anchor)));
}
function assertMetricValue(html, label, value) {
  assert.ok(metricRow(html, label).includes(`<td>${escapeHTML(value)}</td>`), `${label} is ${value}`);
}
function checkCard(html, identity) {
  const opening = [...html.matchAll(/<details\b[^>]*class="check-comparison"[^>]*>/g)].find(match =>
    [["check", identity.check], ["axis", identity.axis], ["method", identity.method]].every(([field, value]) => value === undefined || match[0].includes(`data-${field}="${escapeHTML(value)}"`)));
  assert.ok(opening, `card for ${JSON.stringify([identity.check, identity.axis, identity.method])} is present`);
  return balancedElement(html.slice(opening.index));
}
function checkHeading(card) {
  const summary = card.indexOf("<summary>");
  assert.ok(summary >= 0, "check disclosure has a visible summary");
  return balancedElement(card.slice(summary));
}
function checkIsOpen(card) { return /\sopen(?:\s|=|>)/.test(card.match(/^<details\b[^>]*>/)[0]); }
function toggleCheck(app, identity, open) {
  const card = checkCard(app.element("#case-detail").innerHTML, identity);
  const key = card.match(/^<details\b[^>]*data-check-key="([^"]+)"/)[1]
    .replace(/&(amp|lt|gt|quot|#39);/g, (_, entity) => ({amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'"}[entity]));
  const target = app.element(".check-comparison");
  target.dataset.checkKey = key;
  target.open = open;
  app.dispatch("toggle", ".check-comparison");
  return key;
}

function scenarioFiles() {
  const scenario = {
    id: "fixture-scenario", title: "사례 위치 확인 시나리오",
    steps: [
      {step_id: "first", case_id: "interpret-pass", node: "interpret", role: "interpretation", frame: "root", boundary_before: {kind: "entry", from_step: null}},
      {step_id: "middle", case_id: "decide-format-fail", node: "decide", role: "request", frame: "root", boundary_before: {kind: "next", from_step: "first"}},
      {step_id: "last", case_id: "interpret-pass", node: "interpret", role: "interpretation", frame: "root", boundary_before: {kind: "next", from_step: "middle"}},
    ],
  };
  const index = {
    schema_version: "node-scenarios-v4",
    scenarios: [{id: scenario.id, title: scenario.title, file: "flow.json"}],
    case_index: {
      "interpret-pass": {node: "interpret", role: "interpretation", usages: [{scenario_id: scenario.id, step_id: "first"}, {scenario_id: scenario.id, step_id: "last"}]},
      "decide-format-fail": {node: "decide", role: "request", usages: [{scenario_id: scenario.id, step_id: "middle"}]},
    },
  };
  return [{path: "dataset/scenarios.json", text: JSON.stringify(index)}, {path: "dataset/flow.json", text: JSON.stringify(scenario)}];
}

function scenarioPositions(positions, titles = ["순서 확인"]) {
  const index = {schema_version: "node-scenarios-v4", scenarios: [], case_index: {}};
  const files = titles.map((title, scenarioIndex) => {
    const scenario = {id: `positions-${scenarioIndex}`, title, steps: []};
    for (let position = 1; position <= Math.max(...positions); position++) {
      const current = positions.includes(position), caseId = current ? "interpret-pass" : `filler-${scenarioIndex}-${position}`;
      const step = {step_id: `position-${position}`, case_id: caseId, node: "interpret", role: "interpretation", frame: "root", boundary_before: {kind: position === 1 ? "entry" : "next", from_step: position === 1 ? null : `position-${position - 1}`}};
      scenario.steps.push(step);
      if (!index.case_index[caseId]) index.case_index[caseId] = {node: step.node, role: step.role, usages: []};
      index.case_index[caseId].usages.push({scenario_id: scenario.id, step_id: step.step_id});
    }
    index.scenarios.push({id: scenario.id, title, file: `${scenario.id}.json`});
    return {path: `dataset/${scenario.id}.json`, text: JSON.stringify(scenario)};
  });
  return [{path: "dataset/scenarios.json", text: JSON.stringify(index)}, ...files];
}

function selectedCaseLabels(app, run) {
  const item = markedElement(app.element("#case-rows").innerHTML, "data-case", escapeHTML(caseKey(run)));
  const inner = markup => markup.replace(/^<[^>]+>|<\/[^>]+>$/g, "");
  return {list: inner(classElement(item, "case-id")), detail: inner(classElement(app.element("#case-detail").innerHTML, "detail-title"))};
}

test("case titles and list labels use every exact scenario position with correct ordinal suffixes", () => {
  const positions = [1, 2, 3, 6, 11, 12, 13, 21, 22, 23], ordinals = ["1st", "2nd", "3rd", "6th", "11th", "12th", "13th", "21st", "22nd", "23rd"];
  const data = scoredCatalog(), run = runFor(data, "interpret-pass"), files = scenarioPositions(positions);
  const original = structuredClone(data), originalFiles = structuredClone(files), app = harness(data, {scenarioFiles: files});
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  const labels = selectedCaseLabels(app, run);
  assert.equal(labels.detail, labels.list);
  assert.equal(labels.detail, `Scenario 순서 확인 - ${ordinals.join(", ")}`);
  assert.doesNotMatch(labels.detail, /11st|12nd|13rd|사례 interpret-pass/);
  assert.match(classElement(app.element("#case-detail").innerHTML, "scenario-disclosure"), /<summary>시나리오 도식<\/summary>/);
  assert.equal((app.element("#case-detail").innerHTML.match(/aria-current="step"/g) || []).length, positions.length);
  app.change("run-select", runFor(data, "interpret-pass", 2).key);
  assert.deepEqual(selectedCaseLabels(app, run), labels);
  assert.deepEqual(app.loadedCatalog(), original);
  assert.deepEqual(files, originalFiles);
});

test("case labels preserve multiple scenarios and escape titles in both navigation and detail", () => {
  const data = scoredCatalog(), run = runFor(data, "interpret-pass"), titles = ['지역 <img src=x onerror="bad()"> & "근거"', "다른 지역 검토"];
  const files = scenarioPositions([6], titles), app = harness(data, {scenarioFiles: files});
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  const labels = selectedCaseLabels(app, run);
  assert.equal(labels.list, labels.detail);
  for (const title of titles) assert.ok(labels.detail.includes(`Scenario ${escapeHTML(title)} - 6th`));
  for (const html of [app.element("#case-rows").innerHTML, app.element("#case-detail").innerHTML]) {
    assert.doesNotMatch(html, /<img /);
    assert.match(html, /&lt;img /);
  }
});

test("unmapped or role-mismatched scenarios use the same case fallback in list and detail", () => {
  for (const mode of ["unmapped", "wrong-role"]) {
    const data = scoredCatalog(), run = runFor(data, "interpret-pass");
    if (mode === "wrong-role") for (const selected of data.batches[0].runs.filter(item => item.report.run.case_id === "interpret-pass")) {
      selected.report.run.role = "request";
      selected.case.role = "request";
    }
    const app = harness(data, {scenarioFiles: mode === "unmapped" ? [] : scenarioFiles()});
    app.click({case: caseKey(run)});
    const labels = selectedCaseLabels(app, run);
    assert.deepEqual(labels, {list: "사례 interpret-pass", detail: "사례 interpret-pass"});
    assert.doesNotMatch(labels.detail, /Scenario/);
  }
});

test("HTTP loading keeps only node-unit batches, preloads the selected records and hides success notices", async () => {
  const remote = remoteFixture();
  for (const [id, units] of [["tool-only", ["tool"]], ["agent-only", ["agent"]], ["selection-only-batch", ["selection"]], ["unknown-unit", []]]) {
    const entry = {...structuredClone(remote.index.batches[0]), id, path: `excluded/${id}/batch.json`, units};
    entry.assessments = entry.assessments.map((ref, index) => ({...ref, batch_id: id, path: `excluded/${id}/assessments/score-${index}/manifest.json`}));
    remote.index.batches.push(entry);
  }
  remote.sources.set(catalogPath, JSON.stringify(remote.index));
  const app = harness(catalog, {remote, autoOnly: true});
  assert.equal(app.element("#notice").hidden, false);
  assert.match(app.element("#notice").textContent, /읽는 중/);
  await waitForRemote(app);
  assert.equal(app.element("#welcome").hidden, true);
  assert.equal(app.element("#aggregate-page").hidden, false);
  assert.equal(app.element("#notice").textContent, "");
  assert.equal(app.element("#notice").hidden, true);
  assert.equal((app.element("#batch-select").innerHTML.match(/<option/g) || []).length, 1);
  assert.doesNotMatch(app.element("#batch-select").innerHTML, /tool-only|agent-only|selection-only-batch|unknown-unit/);
  const batchLabel = app.element("#batch-select").innerHTML;
  for (const label of ["작업 목적 파악", "작업 진행 판단", "사용자 정보 요청"]) assert.ok(batchLabel.includes(label));
  assert.match(batchLabel, /\(2026\.11\.12 - 01\)<\/option>/);
  assert.doesNotMatch(batchLabel, /batch\.json|node-viewer-fixture|노드평가_2026/);
  assertRequests(remote, automaticPaths(remote));
  remote.assertPreserved();
});

test("compact batch choices use catalog targets and stored date and sequence before reading the batch", async () => {
  const batchId = "노드평가_2026-11-12_실행07";
  const files = samples.files.map(file => ({path: file.path.replaceAll("노드평가_2026-11-12_실행01", batchId), text: file.text.replaceAll("노드평가_2026-11-12_실행01", batchId)}));
  const remote = remoteFixture(copyFiles(files)), entry = remote.index.batches[0];
  entry.node_targets = ["interpret", "decide", "ask"];
  entry.started_at = "2026-11-14T20:00:00Z";
  const other = {...structuredClone(entry), id: "노드평가_2026-11-12_실행19", path: "unselected/batch.json", node_targets: ["compose", null, {}], assessments: []};
  const invalid = {...structuredClone(other), id: "노드평가_2026-11-12_실행20", path: "invalid-label/batch.json", node_targets: "interpret"};
  remote.index.batches.push(other, invalid);
  remote.sources.set(catalogPath, JSON.stringify(remote.index));
  const fetch = remote.fetch.bind(remote);
  let release;
  const waiting = new Promise(resolve => { release = resolve; });
  remote.fetch = async url => {
    if (decodeURIComponent(new URL(url).pathname.slice(1)) === entry.path) await waiting;
    return fetch(url);
  };
  const app = harness(catalog, {remote, autoOnly: true});
  try {
    await waitFor(() => app.element("#batch-select").innerHTML.includes("2026.11.12 - 07"), "catalog batch labels before batch load");
    const labels = app.element("#batch-select").innerHTML;
    for (const name of ["작업 목적 파악", "작업 진행 판단", "사용자 정보 요청"]) assert.ok(labels.includes(name));
    assert.match(labels, /응답 작성 \(2026\.11\.12 - 19\)<\/option>/);
    assert.match(labels, /노드명 미기록 \(2026\.11\.12 - 20\)<\/option>/);
    assert.doesNotMatch(labels, /\[object Object\]/);
    assert.doesNotMatch(labels, /2026\.11\.1[45]|batch\.json|노드평가_/);
  } finally { release(); }
  await waitForRemote(app);
  assert.match(app.element("#batch-select").innerHTML, /\(2026\.11\.12 - 07\)<\/option>/);
  assert.ok(!remote.requests.includes(other.path), "listing an unselected batch does not read its report");
});

test("compact grading choices preserve stored ordinals and the shared legacy fallback", () => {
  const data = scoredCatalog(), batch = data.batches[0];
  batch.assessments[0].report.id = `${batch.report.id}_채점08`;
  batch.assessments[1].report.id = "legacy-grading-id";
  batch.assessments[1].report.assessed_at = "2026-11-01T00:00:00Z";
  const original = structuredClone(data), app = harness(data);
  const options = [...app.element("#assessment-toolbar").innerHTML.matchAll(/<option\b[^>]*>([^<]+)<\/option>/g)].map(match => match[1]);
  assert.deepEqual(options, batch.assessments.map(record => `채점 ${EvaluationNames.assessmentName(record, batch, data.batches).match(/채점(\d+)$/)[1]}`));
  assert.equal(options[0], "채점 08");
  assert.equal(options[1], "채점 01");
  assert.doesNotMatch(app.element("#assessment-toolbar").innerHTML, /한국시간|노드평가 ·|legacy-grading-id/);
  app.change("assessment-select", batch.assessments[1].path);
  assert.ok(app.element("#assessment-toolbar").innerHTML.includes(`value="${escapeHTML(batch.assessments[1].path)}" selected>채점 01</option>`));
  assert.deepEqual(app.loadedCatalog(), original);
});

test("catalog 404, network and malformed data remain distinct visible errors", async t => {
  for (const [name, value, expected] of [
    ["404", undefined, /자동 조회 목록 파일이 없습니다/],
    ["network", new TypeError("offline fixture"), /자동 조회 목록 로딩 실패:.*파일 서버 연결/],
    ["malformed JSON", "{invalid", /자동 조회 목록 로딩 실패:.*JSON/],
    ["unsupported version", JSON.stringify({version: "evaluation-viewer-local-v1", files: []}), /자동 조회 목록 로딩 실패:.*목록 형식/],
  ]) await t.test(name, async () => {
    const remote = remoteFixture();
    remote.sources.set(catalogPath, value);
    const app = harness(catalog, {remote, autoOnly: true});
    await waitFor(() => expected.test(app.element("#notice").textContent), name);
    assert.equal(app.element("#notice").hidden, false);
    assert.equal(app.loadedCatalog(), undefined);
    assert.deepEqual(remote.requests, [catalogPath]);
    remote.assertPreserved();
  });
});

test("all cases, repetitions, prompts, criteria and scenarios are ready without read buttons", async () => {
  const remote = remoteFixture([...copyFiles(samples.files), ...scenarioFiles()], {scenarioIndex:"dataset/scenarios.json"});
  const app = harness(catalog, {remote, autoOnly:true});
  await waitForRemote(app);
  assertRequests(remote, automaticPaths(remote));
  const fetched = [...remote.requests], score = JSON.parse(remote.sources.get(remote.selected.path));
  const checks = score.assessments.filter(item => item.case_id === "interpret-pass");
  for (const caseId of ["interpret-pass", "decide-format-fail", "interpret-pass"]) {
    const run = runFor(catalog, caseId);
    app.click({case:caseKey(run)});
    assert.doesNotMatch(app.element("#case-detail").innerHTML, /data-remote-kind|아직 읽지|자료 불러오기 실패/);
    assert.match(app.element("#case-detail").innerHTML, /사례 위치 확인 시나리오/);
    assert.match(ioSection(app, "입력"), /class="prompt-text"/);
    for (const tab of ["operational", "functional"]) app.click({caseTab:tab});
  }
  for (const repetition of [1,2]) {
    const run = runFor(catalog,"interpret-pass",repetition);
    app.change("run-select",run.key);
    for (const message of checks.find(r => r.repetition === repetition).checks.find(c => c.check === "N01-O.2").calls[0].judge.prompt.messages)
      assert.ok(app.element("#case-detail").innerHTML.includes(escapeHTML(message.content)));
  }
  assert.match(app.element("#case-detail").innerHTML, /class="functional-summary"/);
  assert.equal((app.element("#case-detail").innerHTML.match(/aria-current="step"/g)||[]).length,2);
  assert.doesNotMatch(app.element("#case-detail").innerHTML,/호출별 판정·평가 모델 기록/);
  assert.deepEqual(remote.requests,fetched);
  assert.equal(app.element("#load-issues").hidden,true);
  remote.assertPreserved();
});

test("legacy grading and regrading load automatically while execution inputs stay available", async () => {
  const remote = legacyRemoteFixture(), app = harness(catalog,{remote,autoOnly:true});
  await waitForRemote(app);
  const batch = remote.index.batches[0];
  const scorePath = batch.assessments.find(ref => JSON.parse(remote.sources.get(ref.path)).method === "all").path;
  app.change("assessment-select",scorePath);
  await waitForRemote(app);
  app.click({scoreCheck:JSON.stringify(["interpret","interpretation","N01-O.2","통과",null])});
  assert.match(app.element("#case-rows").innerHTML,/interpret-pass/);
  assert.doesNotMatch(app.element("#case-rows").innerHTML,/decide-format-fail/);
  assert.match(app.element("#case-detail").innerHTML,/data-check="N01-O.2"|class="check-prompt"/);
  assert.match(ioSection(app,"입력"),/class="prompt-text"/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML,/data-remote-kind/);
  assertRequests(remote,[...automaticPaths(remote,batch,batch.assessments[0]),scorePath]);
  remote.assertPreserved();
});


test("an obsolete loading response cannot complete a replacement batch", async () => {
  const remote=remoteFixture(), fetch=remote.fetch, releases=[], signals=[];
  const blocked=remote.selected.path;
  remote.fetch=async(url,options)=>{
    const response=await fetch(url,options);
    if(decodeURIComponent(new URL(url).pathname.slice(1))===blocked){
      signals.push(options.signal); await new Promise(resolve=>releases.push(resolve));
    }
    return response;
  };
  const app=harness(catalog,{remote,autoOnly:true});
  await waitFor(()=>releases.length===1,"first automatic check request");
  app.click({case:caseKey(runFor(catalog,"interpret-pass"))});
  assert.match(app.element("#case-detail").innerHTML,/자동 불러오는 중/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML,/미제공|미판정/);
  app.trigger("#batch-select","change","0");
  await waitFor(()=>releases.length===2,"replacement automatic request");
  assert.equal(signals[0].aborted,true);
  releases[0](); await new Promise(resolve=>setTimeout(resolve,20));
  assert.equal(app.element("#notice").hidden,false);
  assert.equal(signals[1].aborted,false);
  releases[1](); await waitForRemote(app);
  app.click({case:caseKey(runFor(catalog,"interpret-pass"))});
  assert.match(app.element("#case-detail").innerHTML,/data-check="N01-O.2"/);
  assert.match(ioSection(app,"입력"),/prompt-text/);
  remote.assertPreserved();
});

test("changing an assessment fetches its full checks and preserves loaded run data", async()=>{
  const remote=remoteFixture(), app=harness(catalog,{remote,autoOnly:true});
  await waitForRemote(app);
  const previous=[...remote.requests];
  const ref=remote.index.batches[0].assessments.find(r=>r.path!==remote.selected.path);
  app.change("assessment-select",ref.path); await waitForRemote(app);
  const expected=automaticPaths(remote,remote.index.batches[0],ref);
  assertRequests(remote,[...previous,...expected]);
  assert.ok(remote.requests.slice(previous.length).every(p=>p.includes("/assessments/")));
  app.click({case:caseKey(runFor(catalog,"interpret-pass"))});
  assert.match(ioSection(app,"입력"),/prompt-text/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML,/data-remote-kind/);
  remote.assertPreserved();
});

test("reselecting grading retries missing execution files and clears recovered warnings", async()=>{
  for (const name of ["report.json", "case.json"]) {
    const remote = remoteFixture(), batch = remote.index.batches[0];
    const savedBatch = JSON.parse(remote.sources.get(batch.path));
    const run = savedBatch.runs.find(item => item.case_id === "interpret-pass" && item.repetition === 1);
    const missing = batch.path.replace(/batch\.json$/, run.path.replace(/report\.json$/, name));
    const content = remote.sources.get(missing);
    remote.sources.delete(missing);
    const app = harness(catalog, {remote, autoOnly:true});
    await waitForRemote(app);
    assert.ok(app.element("#load-issues").innerHTML.includes(escapeHTML(missing)));
    assert.equal(remote.requests.filter(path => path === missing).length, 1);
    remote.sources.set(missing, content);
    const other = batch.assessments.find(ref => ref.path !== remote.selected.path);
    app.change("assessment-select", other.path);
    await waitForRemote(app);
    assert.equal(remote.requests.filter(path => path === missing).length, 2);
    assert.equal(app.element("#load-issues").hidden, true);
    app.click({case:caseKey(runFor(catalog, "interpret-pass"))});
    assert.match(ioSection(app, "입력"), /prompt-text/);
    remote.assertPreserved();
  }
});




test("switching batches loads the new records and ignores unrelated scenario files",async()=>{
  const initial=copyFiles(samples.files), oldBatch=JSON.parse(initial.find(f=>f.path.endsWith("/batch.json")).text);
  const oldDirectory=initial.find(f=>f.path.endsWith("/batch.json")).path.replace(/batch\.json$/,"");
  const additional=initial.map(file=>({path:file.path.replace(oldDirectory,"another-batch/"),text:file.text}));
  const remote=remoteFixture([...initial,...additional,...scenarioFiles()],{scenarioIndex:"dataset/scenarios.json"});
  const index=JSON.parse(remote.sources.get("dataset/scenarios.json"));
  index.scenarios.push({id:"unrelated",title:"다른 묶음 시나리오",file:"unrelated.json"});
  remote.sources.set("dataset/scenarios.json",JSON.stringify(index));
  const app=harness(catalog,{remote,autoOnly:true});await waitForRemote(app);
  const previous=[...remote.requests];
  app.trigger("#batch-select","change","1");await waitForRemote(app);
  const next=remote.index.batches[1], ref=[...next.assessments].sort((a,b)=>Date.parse(b.assessed_at)-Date.parse(a.assessed_at))[0];
  assertRequests(remote,[...previous,...automaticPaths(remote,next,ref)]);
  assert.ok(!remote.requests.includes("dataset/unrelated.json"));
  const run=oldBatch.runs.find(r=>r.case_id==="interpret-pass");
  app.click({case:JSON.stringify([run.case_id,run.unit,run.target])});
  assert.match(ioSection(app,"입력"),/prompt-text/);
  assert.match(app.element("#case-detail").innerHTML,/another-batch\/runs\//);
});

test("case detail keeps two metric tabs beside disclosed input and full-width structured output", () => {
  const data = scoredCatalog(), run = runFor(data, "interpret-pass");
  const original = structuredClone(data), app = harness(data, {scenarioFiles: scenarioFiles()});
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  for (const tab of ["functional", "operational"]) {
    if (tab !== "functional") app.click({caseTab: tab});
    const html = app.element("#case-detail").innerHTML;
    for (const title of ["기능 지표", "운영 지표", '<h3 id="case-io-title">입출력</h3>']) assert.ok(html.includes(title), title);
    const scenario = classElement(html, "case-scenario");
    assert.match(scenario, /^<section class="case-scenario"><h2 class="detail-title">Scenario 사례 위치 확인 시나리오/);
    assert.equal((html.match(/class="detail-title"/g) || []).length, 1);
    assert.doesNotMatch(html, /class="detail-heading"|<span>사례 상세<\/span>/);
    assert.match(html, /^<button[^>]*class="back-to-list"[^>]*data-back-to-list[^>]*>← 목록으로<\/button><section class="case-scenario">/);
    assert.doesNotMatch(scenario, /<h3>소속 시나리오<|class="case-section"/);
    assert.doesNotMatch(html, /<h[23]>사례 설명<\/h[23]>|class="case-section case-description"/);
    assert.ok(!html.includes(run.case.purpose));
    const button = html.match(new RegExp(`<button[^>]*data-case-tab="${tab}"[^>]*>`))?.[0];
    assert.ok(button, `${tab} tab is present`);
    assert.match(button, /role="tab"/);
    assert.match(button, /aria-selected="true"/);
    assert.ok(html.indexOf(scenario) < html.indexOf('id="run-select"'));
    assert.ok(html.indexOf('id="run-select"') < html.indexOf('role="tablist"'));
    assert.deepEqual([...html.matchAll(/data-case-tab="([^"]+)"/g)].map(match => match[1]), ["functional", "operational"]);
    const split = classElement(html, "case-results-split"), metrics = classElement(split, "case-metrics-pane"), io = markedElement(split, "id", "case-io-pane");
    assert.ok(metrics.includes('id="case-tab-panel"'));
    assert.ok(split.indexOf('class="case-metrics-pane"') < split.indexOf('id="case-splitter"'));
    assert.ok(split.indexOf('id="case-splitter"') < split.indexOf('id="case-io-pane"'));
    const splitter = split.match(/<[^>]+id="case-splitter"[^>]*>/)[0];
    assert.match(splitter, /role="separator"/);
    assert.match(splitter, /aria-valuemin="25"/);
    assert.match(splitter, /aria-valuemax="75"/);
    assert.match(io, /<summary>입력<\/summary>/);
    const output = classElement(io, "case-output");
    assert.match(output, /^<details class="case-output" open><summary>출력<\/summary>/);
    assert.match(output, /class="value-table"/);
    assert.doesNotMatch(io, /class="(?:io-values-table|io-values-scroll|case-expectations)"|기대 결과|<p class="hint">\d+회차<\/p>/);
    assert.doesNotMatch(output, /<pre>|class="comparison-table"|data-comparison-key=|data-comparison-side=|<summary>기대 기준 자료<\/summary>/);
    assert.doesNotMatch(metrics, /class="(?:case-input|case-output|case-expectations)"/);
    if (tab === "functional") {
      const summary = html.indexOf('class="functional-summary"'), firstCheck = html.indexOf('class="check-comparison"');
      assert.ok(summary >= 0 && firstCheck > summary, "functional verdict and completion precede check comparisons");
    }
    assert.doesNotMatch(html, /data-metric-scope=|data-detail=|data-download=|data-assessment-key=|호출별 근거|재평가·원본|실행기 메타|채점 기준·근거·평가기 해시|평가 모델 입력·응답·근거|<summary>저장 위치<\/summary>|검사 기준 원문/);
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("actual model input uses prompt formatting for role and type messages without losing original content", () => {
  const data = scoredCatalog(), run = runFor(data, "interpret-pass");
  const messages = [
    {role: "system", content: '시스템 첫째 줄\n<script>원문</script> & "따옴표"'},
    {type: "human", content: "사용자 입력\n" + "긴 입력 ".repeat(5000) + "마지막 문장"},
    {role: "assistant", content: [{type: "text", text: "구조화 내용 <img>"}, {count: 0, enabled: false}]},
    {role: "tool", content: {answer: 0, missing: null}, name: "lookup", tool_call_id: "original-call-id"},
  ];
  for (const model of run.report.trace.spans.filter(span => span.kind === "model")) model.input.messages = messages;
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  app.change("run-select", run.key);
  const input = ioSection(app, "입력");
  assert.deepEqual([...input.matchAll(/<pre class="prompt-text">([\s\S]*?)<\/pre>/g)].map(match => match[1]), messages.map(message => escapeHTML(typeof message.content === "string" ? message.content : JSON.stringify(message.content, null, 2))));
  for (const role of ["시스템 메시지", "사용자 메시지", "어시스턴트 메시지", "도구 메시지"]) assert.ok(input.includes(`<summary>${role}</summary>`));
  assert.equal((input.match(/<details class="prompt-message input-message"[^>]* open>/g) || []).length, messages.length);
  assert.doesNotMatch(input, /message-metadata|메시지 부가 정보|original-call-id/);
  assert.doesNotMatch(input, /<script>|<img>/);
  const prompt = classElement(checkCard(app.element("#case-detail").innerHTML, {check: "N01-O.2"}), "check-prompt");
  assert.match(prompt, /class="prompt-message"/);
  assert.match(prompt, /class="prompt-text"/);
  app.change("run-select", runFor(data, "interpret-pass", 2).key);
  assert.doesNotMatch(ioSection(app, "입력"), /시스템 첫째 줄|original-call-id|마지막 문장/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("output and individual input messages retain independent disclosure states across tabs and repetitions", () => {
  const data = scoredCatalog(), first = runFor(data, "interpret-pass"), second = runFor(data, "interpret-pass", 2);
  for (const run of [first, second]) for (const model of run.report.trace.spans.filter(span => span.kind === "model")) {
    model.input.messages = [
      {role: "system", content: `시스템 원문 ${run.report.run.repetition}\n두 번째 줄`, private_metadata: "화면에서 제외할 부가 정보"},
      {role: "user", content: `사용자 원문 ${run.report.run.repetition} <script>문자열</script>`},
    ];
  }
  const original = structuredClone(data), app = harness(data);
  app.click({case: caseKey(first)});
  app.change("run-select", first.key);
  const messages = () => [...ioSection(app, "입력").matchAll(/<details\b[^>]*class="prompt-message input-message"[^>]*>/g)]
    .map(match => balancedElement(ioSection(app, "입력").slice(match.index)));
  const firstMessages = messages();
  assert.equal(firstMessages.length, 2);
  assert.ok(firstMessages.every(checkIsOpen));
  assert.equal(checkIsOpen(ioSection(app, "출력")), true);
  const firstOutput = classElement(ioSection(app, "출력"), "structured-value");
  const target = app.element(".input-message");
  target.dataset.messageKey = firstMessages[0].match(/data-message-key="([^"]+)"/)[1]
    .replace(/&(amp|lt|gt|quot|#39);/g, (_, entity) => ({amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'"}[entity]));
  target.open = false;
  app.dispatch("toggle", ".input-message");
  app.element(".case-output").open = false;
  app.dispatch("toggle", ".case-output");
  for (const tab of ["operational", "functional"]) {
    app.click({caseTab: tab});
    assert.deepEqual(messages().map(checkIsOpen), [false, true]);
    assert.equal(checkIsOpen(ioSection(app, "출력")), false);
    assert.equal(classElement(ioSection(app, "출력"), "structured-value"), firstOutput);
    assert.match(messages()[0], /시스템 원문 1\n두 번째 줄/);
    assert.match(messages()[1], /사용자 원문 1 &lt;script&gt;문자열&lt;\/script&gt;/);
    assert.doesNotMatch(ioSection(app, "입력"), /화면에서 제외할 부가 정보|메시지 부가 정보|<script>/);
  }
  app.change("run-select", second.key);
  assert.deepEqual(messages().map(checkIsOpen), [true, true], "another repetition has its own message state");
  assert.equal(checkIsOpen(ioSection(app, "출력")), false, "output disclosure remains the user's choice");
  assert.match(messages()[0], /시스템 원문 2/);
  app.change("run-select", first.key);
  assert.deepEqual(messages().map(checkIsOpen), [false, true]);
  target.isConnected = false;
  target.open = true;
  app.dispatch("toggle", ".input-message");
  app.click({caseTab: "operational"});
  assert.equal(checkIsOpen(messages()[0]), false, "detached render events cannot overwrite disclosure state");
  target.isConnected = true;
  app.dispatch("toggle", ".input-message");
  app.element(".case-output").open = true;
  app.dispatch("toggle", ".case-output");
  app.click({caseTab: "functional"});
  assert.deepEqual(messages().map(checkIsOpen), [true, true]);
  assert.equal(checkIsOpen(ioSection(app, "출력")), true);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("functional summaries for every included node appear before the first check comparison", () => {
  const data = scoredCatalog(), run = runFor(data, "interpret-pass"), evaluation = data.batches[0].assessments[0].report;
  Object.assign(run.report.run, {unit: "agent", target: "request", role: "request"});
  Object.assign(run.entry, {unit: "agent", target: "request"});
  const additional = structuredClone(evaluation.assessments.find(item => item.node === "decide"));
  Object.assign(additional, {run_id: run.report.run.id, case_id: run.report.run.case_id, repetition: run.report.run.repetition, node_id: "additional-node-summary"});
  evaluation.assessments.push(additional);
  const original = structuredClone(data), app = harness(data);
  app.click({target: "all"});
  app.click({case: caseKey(run)});
  const html = app.element("#case-detail").innerHTML, summaries = [...html.matchAll(/class="functional-summary"/g)];
  assert.equal(summaries.length, 2);
  const firstCheck = html.indexOf('class="check-comparison"');
  assert.ok(firstCheck > summaries.at(-1).index, "all node summaries precede every check card");
  assert.deepEqual(app.loadedCatalog(), original);
});

test("missing model inputs use prepared input only when every selected call lacks input", () => {
  for (const source of ["effective_cases", "cases"]) for (const mode of ["absent-trace", "absent-messages", "null-messages", "mixed"]) {
    const data = scoredCatalog(), run = runFor(data, "interpret-pass"), evaluation = data.batches[0].assessments[0].report, criteria = evaluation.criteria;
    run.case = null;
    if (mode === "absent-trace") run.report.trace.spans = [];
    else if (mode === "mixed") {
      const model = run.report.trace.spans.find(span => span.kind === "model"), missing = structuredClone(model);
      model.input.messages = [{type: "human", content: "실제 입력 원문 보존"}];
      missing.id = `${model.id}-missing-input`;
      delete missing.input.messages;
      run.report.trace.spans.push(missing);
      const assessed = evaluation.assessments.find(item => item.run_id === run.report.run.id), calls = assessed.checks[0].calls;
      calls.push({...structuredClone(calls[0]), id: missing.id, index: 2});
    } else {
      for (const span of run.report.trace.spans.filter(span => span.kind === "model")) {
        if (mode === "absent-messages") delete span.input.messages;
        else span.input.messages = null;
      }
    }
    if (source === "cases") criteria.effective_cases = [];
    const prepared = criteria[source].find(item => item.id === "interpret-pass");
    prepared.initial = {request: {goal: `${source}에 저장한 준비 입력 <goal>`, constraints: {required: [], preferred: [], excluded: []}}};
    const original = structuredClone(data), app = harness(data);
    app.click({target: keyFor("interpret", "interpretation")});
    app.click({case: caseKey(run)});
    app.change("run-select", run.key);
    const input = ioSection(app, "입력");
    if (mode === "mixed") {
      assert.match(input, /실제 입력 원문 보존/);
      assert.match(input, /미제공/);
      assert.doesNotMatch(input, /데이터셋의 준비 입력|에 저장한 준비 입력/);
    } else {
      assert.ok(input.includes(escapeHTML(prepared.initial.request.goal)));
      assert.match(input, /class="value-table"/);
      assert.match(input, /데이터셋의 준비 입력/);
      assert.match(input, /실제 모델 입력은 미제공/);
    }
    assert.doesNotMatch(input, /<goal>/);
    assert.deepEqual(app.loadedCatalog(), original);
  }
});

test("removed expectation display preserves every selected repetition reference and tolerance in source", () => {
  const data = scoredCatalog(), run = runFor(data, "interpret-pass");
  for (const item of data.batches[0].runs.filter(item => item.report.run.case_id === "interpret-pass")) item.case.assessment = {expected: {value: "실행 당시 기대값"}, reference: {"N01-O.2": {expected_behavior: "실행 당시 기대문장"}}, tolerance: {absolute: 101}};
  for (const [recordIndex, record] of data.batches[0].assessments.entries()) {
    for (const source of ["cases", "effective_cases"]) {
      record.report.criteria[source].find(item => item.id === "interpret-pass").assessment = {expected: {value: "사례 전체 기대값"}, reference: {"N01-O.2": {expected_behavior: "사례 전체 기대문장"}}, tolerance: {absolute: 202}};
    }
    for (const selected of record.report.selection.run_cases.filter(item => item.case_id === "interpret-pass")) {
      const prefix = `${recordIndex ? "이전" : "현재"} 채점 ${selected.repetition}회차`;
      selected.assessment = {expected: {value: `${prefix} 기대값`}, reference: {"N01-O.2": {expected_behavior: `${prefix} 기대문장`, request: {goal: `${prefix} 목표`}}}, tolerance: {absolute: selected.repetition / 100}};
    }
  }
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  for (const [recordIndex, record] of data.batches[0].assessments.entries()) {
    app.change("assessment-select", record.path);
    for (const repetition of [1, 2]) {
      app.change("run-select", runFor(data, "interpret-pass", repetition).key);
      const io = markedElement(app.element("#case-detail").innerHTML, "id", "case-io-pane");
      assert.doesNotMatch(io, /case-expectations|기대 결과|실행 당시|사례 전체|채점 \d+회차 (?:기대값|기대문장|목표)/);
      assert.match(ioSection(app, "출력"), /^<details class="case-output" open>/);
    }
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("full-width output preserves the selected original values independently of saved grading comparisons", () => {
  const data = scoredCatalog(), records = data.batches[0].assessments;
  const unsafe = '<img src=x onerror="bad()">';
  for (const repetition of [1, 2]) {
    const run = runFor(data, "interpret-pass", repetition);
    for (const span of run.report.trace.spans.filter(item => item.kind === "model")) {
      span.input.messages = [{type: "human", content: `${repetition}회차 실제 입력`}];
      span.output.sdk_response.content = JSON.stringify({request: {goal: `${repetition}회차 실제 목표`}, reason: repetition === 2 ? unsafe + "x".repeat(25000) + "output-tail-sentinel" : "첫 실행 근거"});
    }
    for (const [index, record] of records.entries()) {
      const prefix = `${index === 0 ? "현재" : "이전"} 채점 ${repetition}회차`;
      const selected = record.report.selection.run_cases.find(item => item.case_id === "interpret-pass" && item.repetition === repetition);
      selected.assessment.expected = {schema_version: "node-expectations-v1", items: [
        {id: "ui-goal-path", check: "N01-O.2", path: "/request/goal", value: `${prefix} 기대 목표`},
        {id: "ui-saved-pair", check: "N01-O.2", value: "데이터셋 원래 기대값"},
        {id: "ui-missing-path", check: "N01-O.2", path: "/missing", value: 0},
      ]};
      const check = record.report.assessments.find(item => item.run_id === run.report.run.id).checks.find(item => item.check === "N01-O.2");
      check.calls[0].details.push({id: "ui-saved-pair", verdict: "통과", executed: true, reason: "저장된 비교값", evidence: [], expected: `${prefix} 저장 기대값`, actual: `${repetition}회차 저장 실제값`});
    }
  }
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(runFor(data, "interpret-pass"))});
  for (const [index, record] of records.entries()) {
    app.change("assessment-select", record.path);
    for (const repetition of [1, 2]) {
      app.change("run-select", runFor(data, "interpret-pass", repetition).key);
      assert.ok(ioSection(app, "입력").includes(`${repetition}회차 실제 입력`));
      const output = ioSection(app, "출력");
      assert.match(output, /^<details class="case-output" open><summary>출력<\/summary>/);
      assert.ok(output.includes(`${repetition}회차 실제 목표`));
      if (repetition === 2) {
        assert.match(output, /&lt;img /);
        assert.match(output, /output-tail-sentinel/);
      }
      assert.doesNotMatch(output, /<img |<pre>|data-download=|저장 실제값|저장 기대값|데이터셋 원래 기대값|해당 항목 경로가 없습니다/);
      assert.doesNotMatch(app.element("#case-detail").innerHTML, /data-comparison-key=|data-comparison-side=|class="comparison-table"|class="case-expectations"|class="io-values-table"/);
    }
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("expected-only criteria stay in saved evidence after their case display is removed", () => {
  const data = scoredCatalog(), run = runFor(data, "interpret-pass");
  const selected = data.batches[0].assessments[0].report.selection.run_cases.find(item => item.case_id === "interpret-pass" && item.repetition === 1);
  delete selected.assessment.reference;
  delete selected.assessment.tolerance;
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  app.change("run-select", run.key);
  const io = markedElement(app.element("#case-detail").innerHTML, "id", "case-io-pane");
  assert.doesNotMatch(io, /case-expectations|node-expectations-v1|기대 결과/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("removing scoped expectation rendering preserves common and node-role occurrence criteria", () => {
  const data = scoredCatalog(), run = runFor(data, "interpret-pass"), evaluation = data.batches[0].assessments[0].report;
  const selected = evaluation.selection.run_cases.find(item => item.case_id === "interpret-pass" && item.repetition === 1);
  evaluation.criteria.checks["N01-O.2"].nodes = ["interpret"];
  evaluation.criteria.checks["N03-O.3"].nodes = ["decide"];
  selected.assessment = {
    expected: {schema_version: "node-expectations-v1", items: [
      {id: "first", check: "N01-O.2", node: "interpret", role: "interpretation", occurrence: 1, call: 1, value: "같은 역할 첫 발생 기대"},
      {id: "second", check: "N01-O.2", node: "interpret", role: "interpretation", occurrence: 2, call: 2, value: "같은 역할 둘째 발생 기대"},
      {id: "common", check: "N-F.1", value: "공통 형식 기대"},
      {id: "wrong-node", check: "N01-O.2", node: "decide", value: "다른 노드 명시 기대"},
      {id: "wrong-role", check: "N01-O.2", node: "interpret", role: "request", value: "다른 역할 명시 기대"},
      {id: "wrong-check", check: "N03-O.3", value: "다른 노드 검사 기대"},
    ]},
    reference: {"N01-O.2": {expected_behavior: "현재 노드 기준 문장"}, "N03-O.3": {expected_behavior: "다른 노드 기준 문장"}, source: "공통 자료 설명"},
    tolerance: {"N01-O.2": {absolute: 0.111}, "N03-O.3": {absolute: 0.222}, relative: 0.333},
  };
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  app.change("run-select", run.key);
  const io = markedElement(app.element("#case-detail").innerHTML, "id", "case-io-pane");
  assert.doesNotMatch(io, /case-expectations|공통 자료 설명|현재 노드 기준 문장|다른 노드 기준 문장|발생 기대|명시 기대/);
  assert.doesNotMatch(source, /function scopedExpectations\(/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("scenario disclosure shows original path and highlights every exact case location", () => {
  const data = scoredCatalog(), files = scenarioFiles(), app = harness(data, {scenarioFiles: files});
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(runFor(data, "interpret-pass"))});
  let html = app.element("#case-detail").innerHTML;
  assert.match(html, /<details[^>]*class="[^"]*scenario-disclosure/);
  assert.match(html, /class="[^"]*scenario-flow/);
  assert.match(html, /사례 위치 확인 시나리오/);
  assert.equal((html.match(/aria-current="step"/g) || []).length, 2);
  assert.equal((html.match(/class="scenario-step current"/g) || []).length, 2);
  app.click({target: keyFor("decide", "request")});
  app.click({case: caseKey(runFor(data, "decide-format-fail"))});
  html = app.element("#case-detail").innerHTML;
  assert.equal((html.match(/aria-current="step"/g) || []).length, 1);
  assert.match(html, /작업 진행 판단/);
});

test("an empty remote result index does not request scenario bodies", async () => {
  const remote = remoteFixture(scenarioFiles(), {scenarioIndex: "dataset/scenarios.json"});
  const app = harness(catalog, {remote, autoOnly: true});
  await waitFor(() => /노드 평가 묶음이 없습니다/.test(app.element("#notice").textContent), "empty node index");
  assert.equal(app.loadedCatalog(), undefined);
  assert.deepEqual(remote.requests, [catalogPath]);
  remote.assertPreserved();
});

test("case detail omits unavailable description and never invents scenario membership", () => {
  const data = scoredCatalog();
  for (const run of data.batches[0].runs) delete run.case.purpose;
  for (const item of data.batches[0].suite.cases) delete item.purpose;
  for (const record of data.batches[0].assessments) for (const item of record.report.criteria.cases) delete item.purpose;
  const app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  const html = app.element("#case-detail").innerHTML;
  assert.doesNotMatch(html, /<h[23]>사례 설명<\/h[23]>/);
  assert.doesNotMatch(html, /aria-current="step"|class="scenario-flow"/);
  assert.match(html, /시나리오.*(?:미제공|없|확인)/);
});

test("three scopes appear together within metric tabs and tab changes preserve selected repetition", () => {
  const data = scoredCatalog(), node = data.batches[0].assessments[0].report.nodes.find(n => n.node === "interpret");
  node.operational.tokens.input_tokens.mean = 9997;
  node.operational.tokens.input_tokens.p95 = 9998;
  const run = runFor(data, "interpret-pass", 2);
  run.report.output = {model_call: "Objective", raw: "두 번째 실행의 출력"};
  for (const span of run.report.trace.spans.filter(span => span.kind === "model")) span.output.sdk_response.content = JSON.stringify({result: "두 번째 실행의 출력"});
  for (const assessed of data.batches[0].assessments[0].report.assessments.filter(item => item.case_id === "interpret-pass")) {
    assessed.checks[0].reason = assessed.repetition === 2 ? "선택 반복의 검사 판정" : "다른 반복의 검사 판정";
  }
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  app.change("run-select", run.key);
  for (const tab of ["functional", "operational", "functional"]) {
    app.click({caseTab: tab});
    const html = app.element("#case-detail").innerHTML;
    assert.match(markedElement(html, "data-case-tab", tab), /aria-selected="true"/);
    assert.match(html, /selected>2회차/);
    assert.doesNotMatch(html, /data-download=|data-detail=|data-metric-scope=/);
    assert.match(ioSection(app, "출력"), /두 번째 실행의 출력/);
    const metrics = markedElement(html, "id", "case-tab-panel");
    if (tab === "functional") {
      assert.match(metrics, /선택 반복의 검사 판정/);
      assert.doesNotMatch(metrics, /다른 반복의 검사 판정|두 번째 실행의 출력|9997|9998/);
      for (const scope of ["run", "case", "node"]) assert.ok(markedElement(metrics, "data-result-scope", scope));
    } else {
      assert.match(metrics, /<th>측정 항목<\/th><th>개별 결과<\/th><th>반복 결과<\/th><th>전체 결과<\/th>/);
      for (const table of metrics.matchAll(/<table class="metric-values"><caption class="sr-only">운영 지표 통계<\/caption>([\s\S]*?)<\/table>/g)) assert.match(table[1], /^<tbody><tr><th scope="row">표본<\/th>/);
      const tokenRow = metricRow(metrics, "입력 토큰");
      const individual = markedElement(tokenRow, "data-result-scope", "run"), repeated = markedElement(tokenRow, "data-result-scope", "case"), overall = markedElement(tokenRow, "data-result-scope", "node");
      assert.match(individual, />40(?:<|\s)/);
      assert.doesNotMatch(individual, /평균/);
      for (const summary of [repeated, overall]) {
        assert.match(summary, /class="metric-values"/);
        assert.match(summary, /<tbody><tr><th scope="row">표본<\/th>/);
        for (const label of ["평균", "중앙값", "p95", "표본", "누락", "미종료"]) assert.ok(metricRow(summary, label));
      }
      assertMetricValue(repeated, "평균", 40);
      assertMetricValue(overall, "평균", 9997);
      assertMetricValue(overall, "p95", 9998);
      assert.doesNotMatch(individual + repeated, /9997|9998/);
      assert.doesNotMatch(metrics, /두 번째 실행의 출력|선택 반복의 검사 판정/);
    }
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("metric values round to three decimals across case and aggregate views without changing original IO or evidence", () => {
  const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report, node = evaluation.nodes.find(item => item.node === "interpret");
  const first = runFor(data, "interpret-pass"), second = runFor(data, "interpret-pass", 2), input = "원문 수치 1.23456789", output = {original_value: 1.23456789};
  for (const run of [first, second]) {
    for (const span of run.report.trace.spans.filter(item => item.kind === "model")) {
      span.elapsed_seconds = 1.23456;
      span.input.messages = [{role: "user", content: input}];
      span.output.sdk_response.content = JSON.stringify(output);
    }
  }
  Object.assign(node.operational.response_time.normal, {sample_count: 2, mean: 1.23456, median: .00049, p95: 2.34567});
  Object.assign(node.operational.tokens.input_tokens, {mean: 1234.56789, median: 0, p95: null});
  node.operational.failure_rate.rate = .123456789;
  node.performance = [
    {metric: "response_time", group: "normal", statistic: "p95", value_seconds: 1.23456, max_seconds: 2.34567, verdict: "통과", complete: true, sample_count: 2, case_ids: ["interpret-pass"], reasons: ["원문 근거 1.23456789"]},
    {metric: "failure_rate", value_rate: .123456789, max_rate: .333333333, verdict: "통과", complete: true, sample_count: 2, case_ids: ["interpret-pass"], reasons: []},
  ];
  const check = evaluation.assessments.find(item => item.run_id === first.report.run.id).checks.find(item => item.check === "N01-O.2");
  check.calls[0].judge.prompt.messages = [{role: "user", content: input}];
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor(node.node, node.role)});
  app.click({case: caseKey(first)});
  app.change("run-select", first.key);
  assert.ok(classElement(checkCard(app.element("#case-detail").innerHTML, {check: check.check}), "check-prompt").includes(input));
  app.click({caseTab: "operational"});
  const metrics = markedElement(app.element("#case-detail").innerHTML, "id", "case-tab-panel"), duration = metricRow(metrics, "호출 응답시간"), tokens = metricRow(metrics, "입력 토큰");
  assert.match(markedElement(duration, "data-result-scope", "run"), /<p>1.235초<\/p>/);
  assertMetricValue(markedElement(duration, "data-result-scope", "case"), "평균", "1.235초");
  const totalDuration = markedElement(duration, "data-result-scope", "node");
  assertMetricValue(totalDuration, "평균", "1.235초");
  assertMetricValue(totalDuration, "중앙값", "0초");
  assertMetricValue(totalDuration, "p95", "2.346초");
  const totalTokens = markedElement(tokens, "data-result-scope", "node");
  assertMetricValue(totalTokens, "평균", "1234.568");
  assertMetricValue(totalTokens, "중앙값", 0);
  assertMetricValue(totalTokens, "p95", "미기록");
  assert.match(markedElement(metricRow(metrics, "기술적 실행 실패"), "data-result-scope", "node"), /<strong>12.346%<\/strong>/);
  assert.ok(ioSection(app, "입력").includes(input));
  assert.match(ioSection(app, "출력"), /1\.23456789/);
  app.click({page: "aggregate"});
  app.click({aggregateRole: keyFor(node.node, node.role), roleMetric: "operational"});
  const aggregate = aggregatePanel(app, "operational"), goals = classElement(aggregate, "operational-goals-table");
  assert.match(aggregate, /<td>정상<\/td><td>2<\/td><td>1.235초<\/td><td>0초<\/td><td>2.346초<\/td>/);
  assert.match(aggregate, /<td>입력 토큰<\/td><td>2<\/td><td>1234.568<\/td><td>0<\/td><td>미기록<\/td>/);
  assert.match(goals, /<td>1.235초<\/td><td>≤ 2.346초<\/td>/);
  assert.match(goals, /<td>12.346%<\/td><td>≤ 33.333%<\/td>/);
  assert.match(goals, /원문 근거 1\.23456789/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("operational repeat metrics are inapplicable only when one planned and one recorded run are confirmed", () => {
  for (const mode of ["single", "planned-repeat", "unknown-plan", "extra-record"]) {
    const data = scoredCatalog(), batch = data.batches[0], evaluation = batch.assessments[0].report, first = runFor(data, "interpret-pass"), second = runFor(data, "interpret-pass", 2);
    const node = evaluation.nodes.find(item => item.node === "interpret"), saved = node.functional.cases.items[0];
    if (mode !== "extra-record") {
      batch.runs = batch.runs.filter(run => run.key !== second.key);
      evaluation.runs = evaluation.runs.filter(run => run.run_id !== second.report.run.id);
      evaluation.assessments = evaluation.assessments.filter(item => item.run_id !== second.report.run.id);
    }
    Object.assign(saved, {planned_repetitions: mode === "planned-repeat" ? 2 : 1, recorded_repetitions: 1, missing_repetitions: mode === "planned-repeat" ? [2] : []});
    if (mode === "unknown-plan") delete saved.planned_repetitions;
    const original = structuredClone(data), app = harness(data);
    app.click({target: keyFor(node.node, node.role)});
    app.click({case: caseKey(first)});
    app.click({caseTab: "operational"});
    const metrics = markedElement(app.element("#case-detail").innerHTML, "id", "case-tab-panel");
    for (const label of ["기술적 실행 실패", "호출 응답시간", "입력 토큰", "출력 토큰", "모델 호출 수", "기술적 재시도"]) {
      const row = metricRow(metrics, label), repeated = markedElement(row, "data-result-scope", "case");
      assert.doesNotMatch(markedElement(row, "data-result-scope", "run") + markedElement(row, "data-result-scope", "node"), /반복 해당 없음/);
      if (mode === "single") {
        assert.match(repeated, /반복 해당 없음/);
        assert.doesNotMatch(repeated, /<table|<strong>/);
      } else {
        assert.doesNotMatch(repeated, /반복 해당 없음/);
        assert.match(repeated, /class="metric-values"/);
      }
    }
    if (mode !== "single") assertMetricValue(markedElement(metricRow(metrics, "입력 토큰"), "data-result-scope", "case"), "표본", mode === "extra-record" ? 2 : 1);
    app.click({caseTab: "functional"});
    const functional = classElement(app.element("#case-detail").innerHTML, "functional-summary");
    assert.doesNotMatch(functional, /반복 해당 없음/);
    assertMetricValue(markedElement(functional, "data-result-scope", "case"), "기록 반복", 1);
    if (mode === "planned-repeat") assertMetricValue(markedElement(functional, "data-result-scope", "case"), "예정 반복", 2);
    assert.deepEqual(app.loadedCatalog(), original);
  }
});

test("closed check summaries show inline metadata and the selected criteria description with fallback", () => {
  const data = scoredCatalog(), records = data.batches[0].assessments, id = "N01-O.2", otherId = "N01-O.1";
  const current = records[0].report.criteria.checks[id], previous = records[1].report.criteria.checks[id];
  const description = '현재 검사 내용\n<script>설명</script> & "원문"';
  current.fields["검사 내용"] = description;
  current.rows[0].fields["검사 내용"] = "우선순위가 낮은 행 설명";
  delete previous.fields["검사 내용"];
  previous.rows[0].fields["검사 내용"] = "이전 채점의 행 검사 내용";
  for (const record of records) {
    const missing = record.report.criteria.checks[otherId];
    delete missing.fields["검사 내용"];
    for (const row of missing.rows) delete row.fields["검사 내용"];
  }
  const original = structuredClone(data), app = harness(data), run = runFor(data, "interpret-pass");
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  for (const [record, expected] of [[records[0], description], [records[1], "이전 채점의 행 검사 내용"]]) {
    app.change("assessment-select", record.path);
    const html = app.element("#case-detail").innerHTML, card = checkCard(html, {check: id});
    const cards = classElement(html, "case-checks");
    assert.deepEqual([...cards.matchAll(/<details class="check-comparison"[^>]*data-axis="([^"]*)"/g)].map(match => match[1]), ["형식 준수", "필수 내용 충족", "내용 정확성"]);
    for (const [axis, tone] of [["형식 준수", "format"], ["필수 내용 충족", "required"], ["내용 정확성", "accuracy"]]) assert.ok(cards.includes(`<span class="axis-label axis-${tone}">${axis}</span>`));
    const heading = checkHeading(card), title = classElement(heading, "check-title-row");
    assert.ok(classElement(title, "check-name").includes(`${id} · ${escapeHTML(current.fields["검사 항목"])}`));
    assert.match(classElement(title, "check-meta"), /<span class="axis-label axis-required">필수 내용 충족<\/span> · LLM 기반/);
    assert.ok(classElement(heading, "check-description").includes(escapeHTML(expected)));
    assert.equal(checkIsOpen(card), false);
    assert.match(heading, /class="check-verdict"/);
    assert.ok(card.indexOf('class="check-title-row"') < card.indexOf('class="check-description"'));
    assert.ok(card.indexOf('class="check-description"') < card.indexOf('class="comparison-scroll"'));
    assert.doesNotMatch(classElement(card, "check-description"), /<script>|우선순위가 낮은 행 설명/);
    assert.match(classElement(checkCard(html, {check: otherId}), "check-description"), /검사 내용 미기록/);
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("check disclosure state survives metric tabs and remains separate for repetitions and check identities", () => {
  const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report;
  const first = runFor(data, "interpret-pass"), second = runFor(data, "interpret-pass", 2);
  const assessed = evaluation.assessments.find(item => item.run_id === first.report.run.id);
  const check = assessed.checks.find(item => item.check === "N01-O.2");
  const alternate = evaluation.assessments.find(item => item.run_id === second.report.run.id).checks.find(item => item.check === check.check);
  Object.assign(alternate, {axis: "별도 평가 축", method: "규칙 기반"});
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(first)});
  const card = identity => checkCard(app.element("#case-detail").innerHTML, identity);
  for (const identity of [check, alternate]) assert.equal(checkIsOpen(card(identity)), false);
  const key = toggleCheck(app, check, true);
  assert.deepEqual(JSON.parse(key), [first.key, "interpret", "interpretation", JSON.stringify([check.check, check.axis, check.method])]);
  app.click({caseTab: "operational"});
  app.click({caseTab: "functional"});
  assert.equal(checkIsOpen(card(check)), true);
  assert.equal(checkIsOpen(card(alternate)), false);
  for (const scope of ["run", "case", "node"]) assert.ok(markedElement(card(check), "data-result-scope", scope));
  assert.match(card(check), /class="check-prompt"/);
  app.change("run-select", second.key);
  assert.equal(checkIsOpen(card(check)), false, "a different repetition starts closed");
  app.change("run-select", first.key);
  assert.equal(checkIsOpen(card(check)), true, "returning to the opened repetition restores its disclosure");
  toggleCheck(app, check, false);
  app.click({caseTab: "operational"});
  app.click({caseTab: "functional"});
  assert.equal(checkIsOpen(card(check)), false);
  toggleCheck(app, alternate, true);
  app.click({caseTab: "operational"});
  app.click({caseTab: "functional"});
  assert.equal(checkIsOpen(card(check)), false);
  assert.equal(checkIsOpen(card(alternate)), true, "same check ID with a different axis and method has independent state");
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /검사 항목별로 선택한 실행, 같은 사례의 모든 반복|목록 필터는 집계 범위를 바꾸지 않습니다\./);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("check disclosure keys distinguish the same check in multiple node-role results of one execution", () => {
  const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report, run = runFor(data, "interpret-pass");
  const assessed = evaluation.assessments.find(item => item.run_id === run.report.run.id);
  const other = structuredClone(assessed);
  Object.assign(other, {node: "decide", role: "request", node_id: "another-node-role"});
  evaluation.assessments.push(other);
  Object.assign(run.report.run, {unit: "agent", target: "request", role: "request"});
  Object.assign(run.entry, {unit: "agent", target: "request"});
  const original = structuredClone(data), app = harness(data);
  app.click({case: caseKey(run)});
  const keys = [...app.element("#case-detail").innerHTML.matchAll(/<details class="check-comparison"[^>]*data-check="N-F\.1"[^>]*data-check-key="([^"]+)"/g)].map(match => match[1]);
  assert.equal(keys.length, 2);
  assert.notEqual(keys[0], keys[1]);
  toggleCheck(app, {check: "N-F.1"}, true);
  app.click({caseTab: "operational"});
  app.click({caseTab: "functional"});
  const cards = [...app.element("#case-detail").innerHTML.matchAll(/<details class="check-comparison"[^>]*data-check="N-F\.1"[^>]*>/g)];
  assert.equal(/\sopen(?:\s|=|>)/.test(cards[0][0]), true);
  assert.equal(/\sopen(?:\s|=|>)/.test(cards[1][0]), false);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("judge prompt text preserves role, newlines and full escaped content across repetitions and regrading", () => {
  const data = scoredCatalog(), id = "N01-O.2", records = data.batches[0].assessments;
  const expected = new Map();
  for (const [recordIndex, record] of records.entries()) {
    for (const assessed of record.report.assessments.filter(item => item.case_id === "interpret-pass")) {
      const stamp = `채점${recordIndex} 반복${assessed.repetition}`;
      const messages = [
        {role: "system", content: `${stamp} 시스템 원문\n<script>실행하지 않는 문장</script> & "따옴표"`},
        {role: "user", content: `${stamp} 사용자 원문\n{"실제 평가 입력": "그대로 보존"}\n${"긴 입력 ".repeat(5000)}\n${stamp} 마지막 문장`},
      ];
      assessed.checks.find(check => check.check === id).calls[0].judge = {
        executed: true, prompt: {messages},
        raw_response: {sentinel: "프롬프트에서 제외할 SDK 응답"}, response: "프롬프트에서 제외할 채점 출력",
        model_usage: {model: "프롬프트에서 제외할 평가 모델 메타"}, details: [],
      };
      expected.set(stamp, messages);
    }
  }
  for (const run of data.batches[0].runs.filter(item => item.report.run.case_id === "interpret-pass")) {
    for (const model of run.report.trace.spans.filter(span => span.kind === "model")) model.input.messages = [{type: "human", content: `${run.report.run.repetition}회차 업무 모델의 실제 입력`}];
  }
  const original = structuredClone(data), app = harness(data), run = runFor(data, "interpret-pass");
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  for (const [recordIndex, record] of records.entries()) {
    app.change("assessment-select", record.path);
    for (const repetition of [1, 2]) {
      app.change("run-select", runFor(data, "interpret-pass", repetition).key);
      const card = checkCard(app.element("#case-detail").innerHTML, {check: id}), prompt = classElement(card, "check-prompt");
      assert.match(prompt, /^<details\b/);
      assert.doesNotMatch(prompt.match(/^<details[^>]*>/)[0], /\sopen(?:\s|>)/);
      assert.match(prompt, /<summary>평가 프롬프트<\/summary>/);
      assert.match(prompt, /class="check-prompt-content"/);
      assert.match(prompt, /시스템 메시지/);
      assert.match(prompt, /사용자 메시지/);
      const messages = expected.get(`채점${recordIndex} 반복${repetition}`);
      assert.deepEqual([...prompt.matchAll(/<pre class="prompt-text">([\s\S]*?)<\/pre>/g)].map(match => match[1]), messages.map(message => escapeHTML(message.content)));
      for (const [stamp, otherMessages] of expected) if (stamp !== `채점${recordIndex} 반복${repetition}`) assert.ok(!prompt.includes(escapeHTML(otherMessages[0].content)));
      assert.doesNotMatch(prompt, /<script>|프롬프트에서 제외할|data-download=|data-detail=/);
      assert.match(ioSection(app, "입력"), new RegExp(`${repetition}회차 업무 모델의 실제 입력`));
      assert.doesNotMatch(ioSection(app, "입력"), /사용자 원문|시스템 원문/);
      const format = checkCard(app.element("#case-detail").innerHTML, {check: "N-F.1"});
      assert.match(format, /class="check-details"/);
      assert.doesNotMatch(format, /class="check-prompt"/);
    }
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("judge prompts retain node and call identity without mixing roles or check axes", () => {
  const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report, run = runFor(data, "interpret-pass"), id = "N01-O.2";
  const first = evaluation.assessments.find(item => item.run_id === run.report.run.id);
  const originalCheck = first.checks.find(check => check.check === id);
  function promptCheck(source, marker) {
    const check = structuredClone(source);
    check.calls = [structuredClone(check.calls[0])];
    check.calls[0].judge = {executed: true, prompt: {messages: [{role: "user", content: marker}]}};
    return check;
  }
  first.checks = [promptCheck(originalCheck, "첫째 노드 첫째 평가 입력")];
  const second = structuredClone(first);
  second.node_id += "-second"; second.occurrence = 2;
  second.checks = [promptCheck(originalCheck, "둘째 노드 첫째 평가 입력")];
  const laterCall = structuredClone(second.checks[0].calls[0]);
  Object.assign(laterCall, {id: "second-saved-call", index: 2, name: "두 번째 호출 이름"});
  laterCall.judge = {executed: false, reason: "평가 요청 전 취소됨", prompt: {messages: [{role: "system", content: "둘째 노드 둘째 준비 평가 입력"}]}};
  second.checks[0].calls.push(laterCall);
  const otherAxis = structuredClone(first);
  otherAxis.node_id += "-different-axis"; otherAxis.occurrence = 3;
  otherAxis.checks = [promptCheck(originalCheck, "같은 ID 다른 축 평가 입력")];
  otherAxis.checks[0].axis = "다른 평가 축";
  const otherRole = structuredClone(first);
  otherRole.node_id += "-other-role"; otherRole.role = "report_selection";
  otherRole.checks = [promptCheck(originalCheck, "다른 역할의 제외할 평가 입력")];
  evaluation.assessments.push(second, otherAxis, otherRole);
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  app.change("run-select", run.key);
  const html = app.element("#case-detail").innerHTML;
  const primary = classElement(checkCard(html, {check: id, axis: originalCheck.axis, method: originalCheck.method}), "check-prompt");
  for (const marker of ["첫째 노드 첫째 평가 입력", "둘째 노드 첫째 평가 입력", "둘째 노드 둘째 준비 평가 입력", "노드 기록 1", "노드 기록 2", "모델 호출 2 · 두 번째 호출 이름"]) assert.ok(primary.includes(marker));
  assert.match(primary, /준비된 평가 프롬프트 · 평가 모델 미실행/);
  assert.match(primary, /평가 요청 전 취소됨/);
  assert.doesNotMatch(primary, /다른 역할의 제외할 평가 입력|같은 ID 다른 축 평가 입력/);
  const alternate = classElement(checkCard(html, {check: id, axis: "다른 평가 축", method: originalCheck.method}), "check-prompt");
  assert.match(alternate, /같은 ID 다른 축 평가 입력/);
  assert.doesNotMatch(alternate, /첫째 노드 첫째 평가 입력|둘째 노드 첫째 평가 입력|둘째 노드 둘째 준비 평가 입력/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("rule-based checks omit judge prompts while missing or invalid LLM prompts show explicit absence", () => {
  for (const mode of ["rule", "rule-with-prompt", "missing-judge", "missing-messages", "empty-messages", "invalid-messages"]) {
    const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report, run = runFor(data, "interpret-pass"), id = "N01-O.2";
    const check = evaluation.assessments.find(item => item.run_id === run.report.run.id).checks.find(item => item.check === id);
    const ruleBased = mode.startsWith("rule");
    if (ruleBased) check.method = "규칙 기반";
    check.calls[0].judge = ["rule", "missing-judge"].includes(mode) ? null : {executed: false, prompt: mode === "missing-messages" ? {} : {messages: mode === "empty-messages" ? [] : [{role: "user", content: mode === "rule-with-prompt" ? "표시하지 않을 규칙 검사 프롬프트" : {unexpected: "재구성하지 않을 값"}}]}};
    const original = structuredClone(data), app = harness(data);
    app.click({target: keyFor("interpret", "interpretation")});
    app.click({case: caseKey(run)});
    app.change("run-select", run.key);
    const card = checkCard(app.element("#case-detail").innerHTML, {check: id, axis: check.axis, method: check.method});
    if (ruleBased) assert.doesNotMatch(card, /class="check-prompt"|평가 프롬프트|표시하지 않을 규칙 검사 프롬프트/);
    else {
      const prompt = classElement(card, "check-prompt");
      assert.match(prompt, /선택한 실행에 저장된 평가 프롬프트가 없습니다/);
      assert.doesNotMatch(prompt, /class="prompt-text"|재구성하지 않을 값|평가 모델 미실행/);
    }
    assert.deepEqual(app.loadedCatalog(), original);
  }
});

test("only the format compliance check shows detail comparisons and functional counts have separate rows", () => {
  const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report, run = runFor(data, "interpret-pass");
  const assessed = evaluation.assessments.find(item => item.run_id === run.report.run.id);
  const format = assessed.checks.find(check => check.check === "N-F.1"), other = assessed.checks.find(check => check.check !== "N-F.1");
  assert.ok(format.details.length && other, "fixture has a format detail and a different check");
  other.details = [{...structuredClone(format.details[0]), id: "hidden-non-format-detail", reason: "숨겨야 하는 다른 검사 세부 항목"}];
  const overall = evaluation.nodes.find(node => node.node === "interpret");
  Object.assign(overall.functional.cases, {numerator: 7, denominator: 11, rate: 7 / 11});
  Object.assign(overall.functional.verification, {completed_cases: 8, incomplete_cases: 3});
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  app.change("run-select", run.key);
  const html = markedElement(app.element("#case-detail").innerHTML, "id", "case-tab-panel");
  assert.match(markedElement(html, "data-check", "N-F.1"), /class="check-details"/);
  assert.doesNotMatch(markedElement(html, "data-check", other.check), /class="check-details"|hidden-non-format-detail|숨겨야 하는 다른 검사 세부 항목/);
  const summary = classElement(html, "functional-summary"), individual = markedElement(summary, "data-result-scope", "run"), repeated = markedElement(summary, "data-result-scope", "case"), total = markedElement(summary, "data-result-scope", "node");
  for (const label of ["검사 통과", "검사 실패", "미판정", "비적용", "미실행"]) assert.ok(metricRow(individual, label));
  assertMetricValue(repeated, "기록 반복", 2);
  assertMetricValue(repeated, "예정 반복", 2);
  for (const label of ["누락 반복", "미완료 반복", "제외 반복"]) assert.ok(metricRow(repeated, label));
  for (const [label, value] of [["통과 사례", 7], ["평가 대상 사례", 11], ["필수 사례 완료", 8], ["필수 사례 미완료", 3]]) assertMetricValue(total, label, value);
  assert.doesNotMatch(summary, /\d+ \/ \d+|<dt>/);
  app.click({caseTab: "operational"});
  const ops = markedElement(app.element("#case-detail").innerHTML, "id", "case-tab-panel");
  const failure = metricRow(ops, "기술적 실행 실패"), duration = metricRow(ops, "호출 응답시간");
  for (const scope of ["case", "node"]) {
    const failureScope = markedElement(failure, "data-result-scope", scope), durationScope = markedElement(duration, "data-result-scope", scope);
    for (const label of ["실패", "평가 대상", "누락", "미종료"]) assert.ok(metricRow(failureScope, label));
    for (const label of ["미분류", "미종료"]) assert.ok(metricRow(durationScope, label));
  }
  assert.doesNotMatch(ops, /\d+ \/ \d+|<dt>/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("functional summary headings retain all saved verdicts while each scope starts with its metric table", () => {
  const data = scoredCatalog(), run = runFor(data, "interpret-pass"), evaluation = data.batches[0].assessments[0].report;
  const first = evaluation.assessments.find(item => item.run_id === run.report.run.id), second = structuredClone(first);
  first.verdict = "통과";
  for (const check of first.checks) Object.assign(check, {executed: true, verdict: "통과"});
  Object.assign(second, {node_id: `${first.node_id}-second-summary`, occurrence: 2, verdict: "실패"});
  for (const check of second.checks) Object.assign(check, {executed: true, verdict: "실패"});
  evaluation.assessments.push(second);
  const savedNode = evaluation.nodes.find(node => node.node === first.node && node.role === first.role);
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor(first.node, first.role)});
  app.click({case: caseKey(run)});
  app.change("run-select", run.key);
  const summary = classElement(app.element("#case-detail").innerHTML, "functional-summary");
  for (const [scope, title] of [["run", "개별 실행 결과"], ["case", "사례 반복 집계 결과"], ["node", "노드·역할 전체 결과"]]) {
    const column = markedElement(summary, "data-result-scope", scope), heading = classElement(column, "scope-heading"), body = classElement(column, "scope-content");
    assert.ok(heading.includes(`<h5>${title}</h5>`));
    assert.ok(heading.indexOf('<h5>') < heading.indexOf('class="scope-verdict"'));
    assert.match(body, /^<div class="scope-content"><table class="metric-values">/);
    assert.doesNotMatch(body, /class="chip /, "summary verdicts stay in column headings");
  }
  const runColumn = markedElement(summary, "data-result-scope", "run"), runHeading = classElement(runColumn, "scope-heading");
  for (const value of ["기록 1", "기록 2", ">통과</span>", ">실패</span>"]) assert.ok(runHeading.includes(value), value);
  const runTables = [...runColumn.matchAll(/<table class="metric-values">/g)].map(match => balancedElement(runColumn.slice(match.index)));
  assert.equal(runTables.length, 2);
  assertMetricValue(runTables[0], "노드 기록", 1);
  assertMetricValue(runTables[0], "검사 통과", first.checks.length);
  assertMetricValue(runTables[1], "노드 기록", 2);
  assertMetricValue(runTables[1], "검사 실패", second.checks.length);
  const nodeColumn = markedElement(summary, "data-result-scope", "node");
  assert.ok(classElement(nodeColumn, "scope-verdict").includes(`>${savedNode.functional.verdict}</span>`));
  assert.doesNotMatch(nodeColumn, /class="metric-rate"|필수 사례 통과율/);
  for (const label of ["통과 사례", "평가 대상 사례", "필수 사례 완료", "필수 사례 미완료"]) assert.ok(metricRow(nodeColumn, label));
  assert.deepEqual(app.loadedCatalog(), original);
});

test("splitter pointer gestures clamp the ratio and stop on release, cancellation or rerender", () => {
  const data = scoredCatalog(), app = harness(data), pane = app.element(".case-results-split"), splitter = app.element("#case-splitter");
  pane.rect = {left: 100, width: 1000};
  const ratio = () => pane.style.getPropertyValue("--case-metrics-width");
  assert.equal(ratio(), "50%");
  assert.equal(app.dispatch("pointerdown", "#case-splitter", {button: 2, pointerId: 7}), false);
  assert.equal(splitter.captured.size, 0);
  for (const ending of ["pointerup", "pointercancel", "lostpointercapture"]) {
    assert.equal(app.dispatch("pointerdown", "#case-splitter", {button: 0, pointerId: 7}), true);
    assert.equal(splitter.hasPointerCapture(7), true);
    assert.equal(pane.classList.contains("is-resizing"), true);
    const before = ratio();
    app.dispatch("pointermove", "#case-splitter", {pointerId: 8, clientX: 900});
    assert.equal(ratio(), before, "unrelated pointers cannot resize the case");
    app.dispatch("pointermove", "#case-splitter", {pointerId: 7, clientX: 800});
    assert.equal(ratio(), "70%");
    assert.equal(splitter.getAttribute("aria-valuenow"), "70");
    assert.equal(splitter.getAttribute("aria-valuetext"), "기능·운영 지표 70%, 입출력 30%");
    app.dispatch("pointermove", "#case-splitter", {pointerId: 7, clientX: 90});
    assert.equal(ratio(), "25%");
    app.dispatch("pointermove", "#case-splitter", {pointerId: 7, clientX: 1200});
    assert.equal(ratio(), "75%");
    app.dispatch(ending, "#case-splitter", {pointerId: 7});
    assert.equal(splitter.hasPointerCapture(7), false);
    assert.equal(pane.classList.contains("is-resizing"), false);
    app.dispatch("pointermove", "#case-splitter", {pointerId: 7, clientX: 600});
    assert.equal(ratio(), "75%", `${ending} ends the active drag`);
  }
  app.dispatch("pointerdown", "#case-splitter", {button: 0, pointerId: 7});
  app.click({caseTab: "operational"});
  assert.equal(splitter.hasPointerCapture(7), false);
  assert.equal(pane.classList.contains("is-resizing"), false);
  app.dispatch("pointermove", "#case-splitter", {pointerId: 7, clientX: 600});
  assert.equal(ratio(), "75%", "a rerender ends the old drag while preserving its last ratio");
});

test("splitter keyboard and input disclosure state survive tabs, repetition and case navigation", () => {
  const data = scoredCatalog(), app = harness(data), first = runFor(data, "interpret-pass"), second = runFor(data, "interpret-pass", 2);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(first)});
  const ratio = () => app.element(".case-results-split").style.getPropertyValue("--case-metrics-width");
  for (const [key, expected] of [["ArrowLeft", "48%"], ["ArrowRight", "50%"], ["Home", "25%"], ["ArrowLeft", "25%"], ["End", "75%"], ["ArrowRight", "75%"], ["ArrowLeft", "73%"]]) {
    assert.equal(app.dispatch("keydown", "#case-splitter", {key}), true);
    assert.equal(ratio(), expected);
  }
  assert.equal(app.dispatch("keydown", "#case-splitter", {key: "Enter"}), false);
  assert.equal(ratio(), "73%");
  const input = app.element(".case-input");
  input.open = true;
  app.dispatch("toggle", ".case-input");
  app.click({caseTab: "operational"});
  assert.match(ioSection(app, "입력"), /^<details[^>]* open>/);
  assert.equal(ratio(), "73%");
  app.change("run-select", second.key);
  assert.equal(ratio(), "73%");
  assert.match(app.element("#case-detail").innerHTML, /selected>2회차/);
  app.click({target: "all"});
  app.click({case: caseKey(runFor(data, "decide-format-fail"))});
  assert.equal(ratio(), "73%");
  input.open = false;
  app.dispatch("toggle", ".case-input");
  app.click({caseTab: "functional"});
  assert.doesNotMatch(ioSection(app, "입력").match(/^<details[^>]*>/)[0], / open/);
  app.click({caseTab: "operational"});
  app.click({page: "aggregate"});
  app.click({openRun: second.key});
  assert.equal(ratio(), "73%");
  assert.match(app.element("#case-detail").innerHTML, /data-case-tab="operational"[^>]*aria-selected="true"/);
  assert.equal(app.element("#case-io-pane").focused, 1);
  assert.equal(app.element("#case-io-pane").scrolled, 1);
});

test("mobile layouts keep original IO visible and ignore splitter pointer and keyboard gestures", () => {
  for (const width of [390, 760]) {
    const app = harness(scoredCatalog(), {width}), pane = app.element(".case-results-split"), splitter = app.element("#case-splitter");
    assert.equal(app.dispatch("pointerdown", "#case-splitter", {button: 0, pointerId: 4}), false);
    app.dispatch("pointermove", "#case-splitter", {pointerId: 4, clientX: 900});
    assert.equal(app.dispatch("keydown", "#case-splitter", {key: "End"}), false);
    assert.equal(splitter.captured.size, 0);
    assert.equal(pane.classList.contains("is-resizing"), false);
    assert.equal(pane.style.getPropertyValue("--case-metrics-width"), "50%");
    const before = markedElement(app.element("#case-detail").innerHTML, "id", "case-io-pane");
    app.click({caseTab: "operational"});
    assert.equal(markedElement(app.element("#case-detail").innerHTML, "id", "case-io-pane"), before);
    assert.match(before, /<details class="case-output" open><summary>출력<\/summary>/);
    assert.doesNotMatch(before, /class="io-values-table"|case-expectations/);
  }
});

test("each functional check aligns its own execution verdict and case/node rates in one comparison card", () => {
  const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report, node = evaluation.nodes.find(item => item.node === "interpret");
  const first = runFor(data, "interpret-pass"), second = runFor(data, "interpret-pass", 2);
  for (const assessed of evaluation.assessments.filter(item => item.case_id === "interpret-pass")) {
    for (const check of assessed.checks) {
      if (!["N-F.1", "N01-O.2"].includes(check.check)) continue;
      Object.assign(check, {executed: true, verdict: check.check === "N-F.1" && assessed.repetition === 1 ? "통과" : "실패", reason: `${check.check} ${assessed.repetition}회차 확인 근거`});
    }
  }
  Object.assign(node.functional.checks.find(item => item.check === "N-F.1"), {numerator: 3, denominator: 5, rate: 0.6, passed: 3, failed: 2});
  Object.assign(node.functional.checks.find(item => item.check === "N01-O.2"), {numerator: 2, denominator: 7, rate: 2 / 7, passed: 2, failed: 5});
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(first)});
  app.click({caseTab: "functional"});
  for (const [run, repetition] of [[first, 1], [second, 2]]) {
    app.change("run-select", run.key);
    const html = app.element("#case-detail").innerHTML;
    for (const [checkId, caseRate, casePassed, caseTotal, nodeRate, nodePassed, nodeTotal] of [["N-F.1", "50%", 1, 2, "60%", 3, 5], ["N01-O.2", "0%", 0, 2, "28.571%", 2, 7]]) {
      const card = markedElement(html, "data-check", checkId);
      assert.match(card, /^<details class="check-comparison"/);
      assert.equal(checkIsOpen(card), false);
      assert.match(card, /class="[^"]*\bcomparison-grid\b[^"]*"/);
      const individual = markedElement(card, "data-result-scope", "run"), repeated = markedElement(card, "data-result-scope", "case"), overall = markedElement(card, "data-result-scope", "node");
      assert.ok(individual.includes(`${checkId} ${repetition}회차 확인 근거`));
      const verdict = checkId === "N-F.1" && repetition === 1 ? "통과" : "실패";
      assert.ok(individual.includes(`>${verdict}</span>`));
      assert.ok(checkHeading(card).includes(`>${verdict}</span>`), "closed summary exposes the selected execution's saved verdict");
      assert.doesNotMatch(checkHeading(card), /class="comparison-grid"|data-result-scope=/);
      assert.ok(repeated.includes(`<strong>${caseRate}</strong>`));
      assertMetricValue(repeated, "통과", casePassed);
      assertMetricValue(repeated, "평가 대상", caseTotal);
      assert.ok(overall.includes(`<strong>${nodeRate}</strong>`));
      assertMetricValue(overall, "통과", nodePassed);
      assertMetricValue(overall, "평가 대상", nodeTotal);
      assertMetricValue(overall, "실패", nodeTotal - nodePassed);
      for (const counts of [repeated, overall]) assert.doesNotMatch(counts, /\d+ \/ \d+/);
      assert.doesNotMatch(card, /data-metric-scope=|<summary>출력<\/summary>/);
    }
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("check and detail results retain original node occurrence numbers when an earlier node lacks the check", () => {
  const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report, run = runFor(data, "interpret-pass");
  const first = evaluation.assessments.find(item => item.run_id === run.report.run.id);
  const originalCheck = first.checks.find(item => item.check === "N-F.1");
  const second = structuredClone(first);
  second.node_id = `${first.node_id}-second-occurrence`;
  second.occurrence = 2;
  second.checks = [structuredClone(originalCheck)];
  Object.assign(second.checks[0], {verdict: "통과", reason: "둘째 노드 발생의 통과 근거"});
  Object.assign(second.checks[0].details[0], {verdict: "통과", reason: "둘째 노드 세부 통과 근거"});
  const third = structuredClone(second);
  third.node_id = `${first.node_id}-third-occurrence`;
  third.occurrence = 3;
  Object.assign(third.checks[0], {verdict: "실패", reason: "셋째 노드 발생의 실패 근거"});
  Object.assign(third.checks[0].details[0], {verdict: "실패", reason: "셋째 노드 세부 실패 근거"});
  first.checks = first.checks.filter(item => item.check !== "N-F.1");
  evaluation.assessments.push(second, third);
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(run)});
  app.change("run-select", run.key);
  const card = markedElement(app.element("#case-detail").innerHTML, "data-check", "N-F.1"), detail = markedElement(card, "class", "detail-comparison");
  const header = checkHeading(card);
  assert.equal((header.match(/>통과<\/span>/g) || []).length, 1);
  assert.equal((header.match(/>실패<\/span>/g) || []).length, 1);
  assert.equal(checkIsOpen(card), false);
  for (const [container, reasons] of [[card, ["둘째 노드 발생의 통과 근거", "셋째 노드 발생의 실패 근거"]], [detail, ["둘째 노드 세부 통과 근거", "셋째 노드 세부 실패 근거"]]]) {
    const individual = markedElement(container, "data-result-scope", "run");
    const results = [...individual.matchAll(/<div class="individual-check">[\s\S]*?<\/div>/g)].map(match => match[0]);
    assert.equal(results.length, 3);
    for (const [index, result] of results.entries()) assert.ok(result.includes(`노드 기록 ${index + 1}`));
    assert.match(results[0], /채점 결과 미제공/);
    assert.ok(results[1].includes(reasons[0]));
    assert.ok(results[2].includes(reasons[1]));
    assert.match(results[1], />통과<\/span>/);
    assert.match(results[2], />실패<\/span>/);
  }
  app.change("run-select", runFor(data, "interpret-pass", 2).key);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /둘째 노드 발생의 통과 근거|셋째 노드 발생의 실패 근거|둘째 노드 세부 통과 근거|셋째 노드 세부 실패 근거/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("same check IDs with different axes or methods keep separate case and node metric rows", () => {
  for (const dimension of ["axis", "method"]) {
    const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report, first = runFor(data, "interpret-pass"), second = runFor(data, "interpret-pass", 2);
    const base = {check: "N01-O.2", axis: "필수 내용 충족", method: "규칙 기반"};
    const alternate = {...base, [dimension]: dimension === "axis" ? "내용 정확성" : "LLM 기반"};
    for (const assessed of evaluation.assessments.filter(item => item.case_id === "interpret-pass")) {
      Object.assign(assessed.checks.find(item => item.check === base.check), assessed.repetition === 1 ? base : alternate,
        {verdict: assessed.repetition === 1 ? "통과" : "실패", executed: true, reason: `${assessed.repetition}회차 ${dimension} 비교 근거`});
    }
    const node = evaluation.nodes.find(item => item.node === "interpret"), saved = node.functional.checks.find(item => item.check === base.check);
    node.functional.checks = node.functional.checks.filter(item => item.check !== base.check);
    node.functional.checks.push({...saved, ...base, rate: 0.25, numerator: 1, denominator: 4, passed: 1, failed: 3}, {...saved, ...alternate, rate: 0.75, numerator: 3, denominator: 4, passed: 3, failed: 1});
    const original = structuredClone(data), app = harness(data);
    app.click({target: keyFor("interpret", "interpretation")});
    app.click({case: caseKey(first)});
    for (const [selectedRun, repetition] of [[first, 1], [second, 2]]) {
      app.change("run-select", selectedRun.key);
      const html = app.element("#case-detail").innerHTML;
      for (const [identity, current, caseRate, nodeRate, passed] of [[base, 1, "100%", "25%", 1], [alternate, 2, "0%", "75%", 3]]) {
        const opening = [...html.matchAll(/<details\b[^>]*class="[^"]*\bcheck-comparison\b[^"]*"[^>]*>/g)].find(match => match[0].includes(`data-check="${identity.check}"`) && match[0].includes(`data-axis="${identity.axis}"`) && match[0].includes(`data-method="${identity.method}"`));
        assert.ok(opening, `${dimension}: exact check identity has a card`);
        const card = markedElement(html.slice(opening.index), "data-check", identity.check);
        const individual = markedElement(card, "data-result-scope", "run"), repeated = markedElement(card, "data-result-scope", "case"), overall = markedElement(card, "data-result-scope", "node");
        if (repetition === current) assert.ok(individual.includes(`${repetition}회차 ${dimension} 비교 근거`));
        else assert.match(individual, /선택한 실행의 채점 결과 미제공/);
        assert.ok(repeated.includes(`<strong>${caseRate}</strong>`));
        assert.ok(overall.includes(`<strong>${nodeRate}</strong>`));
        assertMetricValue(overall, "통과", passed);
        assertMetricValue(overall, "평가 대상", 4);
      }
    }
    assert.deepEqual(app.loadedCatalog(), original);
  }
});

test("selection-only cases keep their check results and explicitly exclude overall node comparison", () => {
  const data = scoredCatalog(), selected = data.batches[0].assessments[0].report.assessments.find(item => !item.counted), run = runFor(data, selected.case_id);
  const app = harness(data);
  app.click({target: keyFor(selected.node, selected.role, false)});
  app.click({case: caseKey(run)});
  const card = markedElement(app.element("#case-detail").innerHTML, "data-check", selected.checks[0].check);
  assert.ok(markedElement(card, "data-result-scope", "run").includes(`>${selected.checks[0].verdict}</span>`));
  const overall = markedElement(card, "data-result-scope", "node");
  assert.match(overall, /노드 지표 집계 제외/);
  assert.doesNotMatch(overall, /\d+(?:\.\d+)?%/);
});

test("aggregate tabs isolate functional results, operational measurements and grading information", () => {
  const data = scoredCatalog(), original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({page: "aggregate"});
  assertAggregateTab(app, "functional");
  const functional = aggregatePanel(app, "functional"), operational = aggregatePanel(app, "operational"), information = aggregatePanel(app, "info");
  for (const content of ["전체 사례 통과율", "항목별 검사결과", "세부 항목 통과율", "개별 판정 근거", "평가 모델 원응답 · SDK"]) assert.ok(functional.includes(content), content);
  assert.doesNotMatch(functional, /<h4>호출 응답시간<|<h4>운영 목표 충족 여부<|<summary>선택한 채점 기준<|<h[23]>채점 정보<|묶음 전체의 저장 정보/);
  for (const content of ["기술적 실행 실패율", "호출 응답시간", "입력 토큰", "출력 토큰", "모델 호출 수", "기술적 재시도 합계"]) assert.ok(operational.includes(content), content);
  assert.match(operational, /class="operational-goals-table"/);
  assert.doesNotMatch(operational, /<span>전체 사례 통과율<|<h4>항목별 검사결과<|id="score-evidence"|<summary>선택한 채점 기준<|묶음 전체의 저장 정보/);
  for (const content of ["평가 이름", "결과 파일", "저장 위치", "채점 결과 전체", "묶음 전체의 저장 정보", "실행별 관측값·평가 상태"]) assert.ok(information.includes(content), content);
  for (const panel of [functional, operational, information]) assert.doesNotMatch(panel, /<h2>(?:기능 지표|운영 지표|채점 정보)<\/h2>|<summary>선택한 채점 기준<\/summary>/);
  assert.doesNotMatch(information, /<span>전체 사례 통과율<|<h4>항목별 검사결과<|<h4>호출 응답시간<|id="score-evidence"/);
  for (const tab of ["operational", "info", "functional"]) {
    app.click({aggregateTab: tab});
    assertAggregateTab(app, tab);
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("aggregate click and keyboard navigation preserve case, repetition and grading selections", () => {
  const data = scoredCatalog(), original = structuredClone(data), app = harness(data);
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({case: caseKey(runFor(data, "interpret-pass"))});
  app.change("run-select", runFor(data, "interpret-pass", 2).key);
  app.click({caseTab: "operational"});
  app.click({page: "aggregate"});
  const detail = app.element("#case-detail").innerHTML, rows = app.element("#case-rows").innerHTML, assessment = app.element("#assessment-toolbar").innerHTML;
  app.click({aggregateTab: "info"});
  assertAggregateTab(app, "info");
  assert.equal(app.element("#aggregate-tab-info").focused, 1);
  for (const [from, key, to] of [
    ["info", "ArrowRight", "functional"], ["functional", "ArrowLeft", "info"],
    ["info", "Home", "functional"], ["functional", "ArrowRight", "operational"],
    ["operational", "End", "info"], ["info", "ArrowLeft", "operational"],
  ]) {
    const selector = `#aggregate-tab-${from}`, destination = app.element(`#aggregate-tab-${to}`), focusCount = destination.focused;
    app.element(selector).dataset.aggregateTab = from;
    assert.equal(app.dispatch("keydown", selector, {key}), true);
    assertAggregateTab(app, to);
    assert.equal(destination.focused, focusCount + 1);
    assert.equal(app.element("#case-detail").innerHTML, detail);
    assert.equal(app.element("#case-rows").innerHTML, rows);
    assert.equal(app.element("#assessment-toolbar").innerHTML, assessment);
  }
  app.element("#aggregate-tab-operational").dataset.aggregateTab = "operational";
  assert.equal(app.dispatch("keydown", "#aggregate-tab-operational", {key: "Enter"}), false);
  assertAggregateTab(app, "operational");
  app.click({page: "cases"});
  assert.equal(app.element("#case-detail").innerHTML, detail);
  assert.match(detail, /selected>2회차/);
  assert.match(detail, /data-case-tab="operational"[^>]*aria-selected="true"/);
  app.element("#case-tab-operational").dataset.caseTab = "operational";
  assert.equal(app.dispatch("keydown", "#case-tab-operational", {key: "ArrowRight"}), true);
  assert.match(app.element("#case-detail").innerHTML, /data-case-tab="functional"[^>]*aria-selected="true"/);
  assert.match(app.element("#case-detail").innerHTML, /selected>2회차/);
  assert.equal(app.element("#case-tab-functional").focused, 1);
  app.click({page: "aggregate"});
  assertAggregateTab(app, "operational");
  app.change("assessment-select", data.batches[0].assessments[1].path);
  assertAggregateTab(app, "operational");
  assert.match(app.element("#case-detail").innerHTML, /selected>2회차/);
  assert.ok(app.element("#assessment-toolbar").innerHTML.includes(`value="${escapeHTML(data.batches[0].assessments[1].path)}" selected`));
  app.click({target: keyFor("ask", "request")});
  assertAggregateTab(app, "operational");
  app.click({target: "all"});
  assertAggregateTab(app, "operational");
  assert.deepEqual(app.loadedCatalog(), original);
});

test("aggregate tabs use preloaded HTTP records and retain the current tab across regrading", async () => {
  const remote = remoteFixture(), app = harness(catalog, {remote, autoOnly: true});
  await waitForRemote(app);
  assertAggregateTab(app, "functional");
  const initialRequests = [...remote.requests];
  app.click({case: caseKey(runFor(catalog, "interpret-pass"))});
  app.change("run-select", runFor(catalog, "interpret-pass", 2).key);
  app.click({page: "aggregate"});
  const detail = app.element("#case-detail").innerHTML, assessment = app.element("#assessment-toolbar").innerHTML;
  for (const tab of ["operational", "info", "functional", "info"]) {
    app.click({aggregateTab: tab});
    assertAggregateTab(app, tab);
  }
  app.element("#aggregate-tab-info").dataset.aggregateTab = "info";
  assert.equal(app.dispatch("keydown", "#aggregate-tab-info", {key: "Home"}), true);
  assertAggregateTab(app, "functional");
  assert.equal(app.element("#case-detail").innerHTML, detail);
  assert.equal(app.element("#assessment-toolbar").innerHTML, assessment);
  assert.deepEqual(remote.requests, initialRequests);
  assert.match(aggregatePanel(app, "functional"), /전체 사례 통과율/);
  assert.doesNotMatch(aggregatePanel(app, "functional"), /<h4>호출 응답시간<|<h[23]>채점 정보<|<h3>원본 파일</);
  assert.match(aggregatePanel(app, "operational"), /<h4>호출 응답시간</);
  assert.doesNotMatch(aggregatePanel(app, "operational"), /<span>전체 사례 통과율<|<h3>원본 파일</);
  const info = aggregatePanel(app, "info"), selected = JSON.parse(remote.sources.get(remote.selected.path));
  for (const label of ["채점 ID", "채점 일시", "채점 상태"]) assert.ok(info.includes(`<dt>${label}</dt>`));
  assert.ok(info.includes(escapeHTML(selected.id)));
  assert.ok(info.includes(escapeHTML(selected.status)));
  assert.equal((info.match(/<dl\b/g) || []).length, 1);
  assert.doesNotMatch(info, /<h[23]\b|선택한 채점 기준|묶음 기록|등록 실행|예정 실행|원본 파일|채점 manifest|<a\b|judge_trace/);
  for (const tab of ["functional", "operational"]) assert.doesNotMatch(aggregatePanel(app, tab), /<h2>(?:기능 지표|운영 지표)<\/h2>/);
  assert.doesNotMatch(aggregatePanel(app, "info"), /<span>전체 사례 통과율<|<h4>호출 응답시간</);
  app.click({aggregateTab: "info"});
  const older = remote.index.batches[0].assessments.find(record => record.path !== remote.selected.path);
  app.change("assessment-select", older.path);
  await waitForRemote(app);
  assertAggregateTab(app, "info");
  const regradedRequests = [...remote.requests];
  for (const tab of ["functional", "operational", "info"]) app.click({aggregateTab: tab});
  assert.deepEqual(remote.requests, regradedRequests);
  remote.assertPreserved();
});

test("aggregate role tabs share selection across metrics while preserving case scope and keyboard focus", () => {
  const data = scoredCatalog(), nodes = data.batches[0].assessments[0].report.nodes, original = structuredClone(data), app = harness(data);
  app.click({target: "all"});
  app.click({page: "aggregate"});
  const rows = app.element("#case-rows").innerHTML, context = app.element("#context").textContent, detail = app.element("#case-detail").innerHTML;
  const allButton = markedElement(app.element("#target-nav").innerHTML, "data-target", "all");
  assertAggregateRole(app, nodes, -1);
  const labels = nodes.map((_, index) => markedElement(aggregatePanel(app, "functional"), "id", `aggregate-role-functional-${index + 1}`).match(/>([^<]+)<\/button>$/)[1]);
  assert.notEqual(labels[0], labels[1], "identical role names on different nodes remain distinguishable");
  assert.ok(labels[0].includes(" / 사용자 요청 처리") && labels[1].includes(" / 사용자 요청 처리"));
  app.click({aggregateRole: keyFor(nodes[2].node, nodes[2].role), roleMetric: "functional"});
  assertAggregateRole(app, nodes, 2);
  assertAllCaseFunctionalRollup(app, nodes[2].functional);
  app.click({aggregateTab: "operational"});
  assertAggregateRole(app, nodes, 2);
  assert.equal(app.element("#case-rows").innerHTML, rows);
  assert.equal(app.element("#case-detail").innerHTML, detail);
  assert.equal(app.element("#context").textContent, context);
  assert.equal(markedElement(app.element("#target-nav").innerHTML, "data-target", "all"), allButton);
  for (const [from, key, to] of [[2, "ArrowRight", -1], [-1, "ArrowLeft", 2], [2, "Home", -1], [-1, "End", 2], [2, "ArrowLeft", 1]]) {
    const selector = `#aggregate-role-operational-${from + 1}`, target = app.element(`#aggregate-role-operational-${to + 1}`), before = target.focused;
    Object.assign(app.element(selector).dataset, {aggregateRole: from < 0 ? "all" : keyFor(nodes[from].node, nodes[from].role), roleMetric: "operational"});
    assert.equal(app.dispatch("keydown", selector, {key}), true);
    assertAggregateRole(app, nodes, to);
    assert.equal(target.focused, before + 1);
    assert.ok(target.scrolled > 0);
  }
  const selected = classElement(aggregatePanel(app, "functional"), "functional-rollup");
  app.trigger("#case-search", "input", "해당하는 사례 없음");
  assert.match(app.element("#case-rows").innerHTML, /표시할 사례가 없습니다/);
  assert.equal(classElement(aggregatePanel(app, "functional"), "functional-rollup"), selected);
  assertAggregateRole(app, nodes, 1);
  app.click({aggregateRole: keyFor("missing-node", "missing-role"), roleMetric: "operational"});
  assertAggregateRole(app, nodes, 1);
  app.click({target: keyFor(nodes[2].node, nodes[2].role)});
  assertAggregateRole(app, [nodes[2]], -1);
  assertAllCaseFunctionalRollup(app, nodes[2].functional);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("HTTP role navigation uses prepared records and falls back when a new grading record lacks the selected role", async () => {
  const remote = remoteFixture(), latest = JSON.parse(remote.sources.get(remote.selected.path));
  const nodes = latest.nodes;
  const older = remote.index.batches[0].assessments.find(record => record.path !== remote.selected.path);
  const olderSummary = JSON.parse(remote.sources.get(older.path));
  olderSummary.nodes = olderSummary.nodes.filter(node => node.node !== nodes.at(-1).node || node.role !== nodes.at(-1).role);
  const altered = JSON.stringify(olderSummary);
  remote.sources.set(older.path, altered);
  remote.original.set(older.path, altered);
  remote.index.files.find(entry => entry.path === older.path).size_bytes = Buffer.byteLength(altered);
  remote.sources.set(catalogPath, JSON.stringify(remote.index));
  const app = harness(catalog, {remote, autoOnly: true});
  await waitForRemote(app);
  const requests = [...remote.requests], rows = app.element("#case-rows").innerHTML;
  app.click({aggregateRole: keyFor(nodes.at(-1).node, nodes.at(-1).role), roleMetric: "functional"});
  assertAggregateRole(app, nodes, nodes.length - 1);
  for (const tab of ["operational", "info", "functional"]) app.click({aggregateTab: tab});
  assertAggregateRole(app, nodes, nodes.length - 1);
  assert.deepEqual(remote.requests, requests);
  assert.equal(app.element("#case-rows").innerHTML, rows);
  app.change("assessment-select", older.path);
  await waitForRemote(app);
  assertAggregateRole(app, olderSummary.nodes, -1);
  assertAllCaseFunctionalRollup(app, {cases: {items: olderSummary.nodes.flatMap(node => node.functional.cases.items)}});
  assert.equal(app.element("#load-issues").hidden, true);
  remote.assertPreserved();
});

test("functional summaries count unclassified and optional cases and always show verification progress", () => {
  for (const unclassified of [16, 0]) {
    const data = scoredCatalog(), node = data.batches[0].assessments[0].report.nodes.find(item => item.node === "interpret"), f = node.functional;
    const base = structuredClone(f.cases.items[0]);
    Object.assign(f, {verdict: "미판정", complete: false});
    Object.assign(f.cases, {numerator: 0, denominator: 0, rate: null, passed: 0, failed: 0, undetermined: 0, excluded: 1, unspecified_required: unclassified});
    f.cases.items = [...Array.from({length: unclassified}, (_, index) => ({...structuredClone(base), case_id: `unclassified-${index}`, required: null, verdict: index % 2 ? "미판정" : "통과", complete: index % 2 === 0})), {...base, case_id: "optional-preserved", required: false, reason: "선택 사례의 근거를 보존합니다."}];
    Object.assign(f.verification, {required_cases: 0, completed_cases: 0, incomplete_cases: 0, missing_repetitions: 0});
    const original = structuredClone(data), app = harness(data);
    app.click({target: keyFor(node.node, node.role)});
    app.click({page: "aggregate"});
    const panel = aggregatePanel(app, "functional"), summary = assertAllCaseFunctionalRollup(app, f);
    assert.equal((summary.match(/class="summary-card"/g) || []).length, 3);
    assert.match(summary, /전체 사례 통과율|verification-progress/);
    assert.doesNotMatch(panel, /class="required-notice"|class="functional-help"|필수 사례 집계에서 제외한 선택 사례/);
    assert.match(panel, /optional-preserved(?:<small>[^<]*<\/small>)?<\/td><td>선택<\/td>/);
    assert.match(panel, /선택 사례의 근거를 보존합니다/);
    if (unclassified) assert.match(panel, /unclassified-15(?:<small>[^<]*<\/small>)?<\/td><td>미지정<\/td>/);
    assert.deepEqual(app.loadedCatalog(), original);
  }
});

test("all-case verdicts and pass rates remain separate from verification progress and include pending cases", () => {
  for (const [verdict, complete, passed, failed, pending, finished, required, missing, storedRate] of [
    ["통과", true, 2, 0, 0, 2, 2, 0, 1],
    ["실패", false, 3, 2, 4, 5, 9, 3, .6],
    ["미판정", false, 0, 0, 2, 0, 2, 0, null],
  ]) {
    const data = scoredCatalog(), node = data.batches[0].assessments[0].report.nodes.find(item => item.node === "interpret"), f = node.functional;
    Object.assign(f, {verdict: "미판정", complete: false});
    Object.assign(f.cases, {numerator: passed, denominator: passed + failed, rate: storedRate, passed, failed, undetermined: pending, excluded: 0, unspecified_required: 0});
    Object.assign(f.verification, {required_cases: required, completed_cases: finished, incomplete_cases: required - finished, missing_repetitions: missing});
    const item = structuredClone(f.cases.items[0]);
    f.cases.items = Array.from({length: required}, (_, index) => ({...structuredClone(item), case_id: `all-case-${index}`, required: [true, false, null][index % 3],
      verdict: index < passed ? "통과" : index < passed + failed ? "실패" : "미판정", complete: index < finished,
      missing_repetitions: index === required - 1 ? Array.from({length: missing}, (_, repetition) => repetition + 3) : []}));
    const original = structuredClone(data), app = harness(data);
    app.click({target: keyFor(node.node, node.role)});
    app.click({page: "aggregate"});
    const summary = assertAllCaseFunctionalRollup(app, f);
    assert.ok(classElement(summary, "verification-progress").includes(`검증 완료 ${finished} / 전체 ${required}</p>`));
    assert.equal(summary.includes(`누락 반복 ${missing}회`), missing > 0);
    assert.doesNotMatch(summary, /누락 반복 0회/);
    if (verdict === "실패") {
      assert.match(summary, />실패<\/span>/);
      assert.match(summary, /<strong>33.333%<\/strong>/, "pending cases enter the denominator with every other case");
      assert.match(summary, /검증 완료 5 \/ 전체 9<\/p>/);
    }
    assert.deepEqual(app.loadedCatalog(), original);
  }
});

test("the default all tab combines every role and displays check names, descriptions and rates without fractions", () => {
  const data = scoredCatalog(), evaluation = data.batches[0].assessments[0].report, nodes = evaluation.nodes;
  for (const [index, node] of nodes.entries()) {
    Object.assign(node.functional.cases.items[0], {required: [null, false, true][index], verdict: ["미판정", "실패", "통과"][index], complete: index === 2});
    Object.assign(node.functional.cases, {rate: .99, numerator: 99, denominator: 100});
    node.functional.verdict = "통과";
  }
  Object.assign(evaluation.criteria.checks["N-F.1"].fields, {"검사 항목": "출력 <형식> 준수", "검사 내용": "구조 <script>원문</script> 확인"});
  const original = structuredClone(data), app = harness(data);
  app.click({page: "aggregate"});
  assertAggregateRole(app, nodes, -1);
  let panel = aggregatePanel(app, "functional"), summary = classElement(panel, "functional-rollup");
  assert.match(summary, /<strong>33.333%<\/strong>/);
  assert.match(summary, /class="chip error">실패<\/span>/);
  assert.match(summary, /검증 완료 1 \/ 전체 3<\/p>/);
  for (const count of ["통과 1", "실패 1", "미판정 1"]) assert.ok(summary.includes(`<span>${count}</span>`));
  const table = classElement(panel, "check-results-table");
  assert.match(table, /<th>검사 항목<\/th><th>통과율<\/th>/);
  assert.match(table, /N-F\.1 출력 &lt;형식&gt; 준수/);
  assert.match(table, /class="metric-check-description">구조 &lt;script&gt;원문&lt;\/script&gt; 확인/);
  assert.match(table, /<span class="axis-label axis-format">형식 준수<\/span> · 규칙 기반/);
  assert.match(table, /<td>66.667%<\/td>/);
  const axisRanks = [...table.matchAll(/class="axis-label axis-(format|required|accuracy)"/g)].map(match => ["format", "required", "accuracy"].indexOf(match[1]));
  assert.deepEqual(axisRanks, [...axisRanks].sort((left, right) => left - right));
  assert.doesNotMatch(table, /분자|분모|%<br>|<script>/);
  assert.ok(panel.indexOf('class="section case-assessment-details"') > panel.indexOf('<h4>세부 항목 통과율</h4>'));
  app.click({aggregateRole: keyFor(nodes[0].node, nodes[0].role), roleMetric: "functional"});
  assert.match(classElement(aggregatePanel(app, "functional"), "functional-rollup"), /<strong>0%<\/strong>/);
  app.click({aggregateRole: "all", roleMetric: "functional"});
  app.trigger("#case-search", "input", "interpret-pass");
  assert.equal(classElement(aggregatePanel(app, "functional"), "functional-rollup"), summary);
  app.click({scoreCheck: JSON.stringify(["all", "all", "N-F.1", "통과", null])});
  panel = aggregatePanel(app, "functional");
  assertAggregateRole(app, nodes, -1);
  assert.match(panel, /개별 판정 근거 · 4건/);
  assert.match(panel, /<strong>ask-unjudged ·/);
  assert.match(panel, /<strong>interpret-pass ·/);
  assert.doesNotMatch(classElement(panel, "score-evidence-row"), /selection-only/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("operational cards and goal tables preserve saved values, units, verdicts and disclosure evidence", () => {
  const data = scoredCatalog(), node = data.batches[0].assessments[0].report.nodes.find(item => item.node === "interpret");
  Object.assign(node.operational, {verdict: "실패", complete: false});
  Object.assign(node.operational.failure_rate, {numerator: 1, denominator: 2, rate: .5, missing_count: 2, unfinished_count: 1});
  node.performance = [
    {metric: "response_time", group: "normal", statistic: "p95", value_seconds: 1.25, max_seconds: 2.5, value_rate: null, max_rate: null, verdict: "통과", complete: true, sample_count: 2, case_ids: ["interpret-pass"], reasons: ["응답시간 근거 <script>원문</script>"]},
    {metric: "failure_rate", group: null, statistic: null, value_rate: .5, max_rate: .25, value_seconds: null, max_seconds: null, verdict: "실패", complete: false, sample_count: 2, case_ids: ["interpret-pass"], reasons: ["추가 측정 필요"]},
  ];
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor(node.node, node.role)});
  app.click({page: "aggregate"});
  app.click({aggregateRole: keyFor(node.node, node.role), roleMetric: "functional"});
  app.click({aggregateTab: "operational"});
  const panel = aggregatePanel(app, "operational"), summary = classElement(panel, "operational-rollup"), goals = classElement(panel, "operational-goals-table");
  assert.equal((summary.match(/class="summary-card"/g) || []).length, 3);
  assert.match(summary, />실패<\/span>/);
  assert.match(summary, /<strong>50%<\/strong>/);
  assert.match(summary, /실패 1 \/ 측정 2건/);
  for (const notice of ["실패 여부 미확인 2건", "미종료 1건"]) assert.ok(summary.includes(notice));
  assert.match(goals, /<th>목표<\/th><th>측정값<\/th><th>기준<\/th><th>판정<\/th>/);
  assert.match(goals, /<td>1.25초<\/td><td>≤ 2.5초<\/td><td><span class="chip pass">통과/);
  assert.match(goals, /<td>50%<\/td><td>≤ 25%<\/td><td><span class="chip error">실패/);
  assert.match(goals, /<details><summary>정상 응답시간 · p95<\/summary>/);
  assert.match(goals, /응답시간 근거 &lt;script&gt;원문&lt;\/script&gt;/);
  assert.match(goals, /<dt>측정 완료<\/dt><dd>미완료<\/dd>/);
  assert.match(goals, /추가 측정 필요/);
  assert.doesNotMatch(goals, /<script>/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("empty case and check collections retain all-role navigation and explicit empty metrics", () => {
  const data = scoredCatalog(), node = data.batches[0].assessments[0].report.nodes.find(item => item.node === "interpret");
  Object.assign(node.functional, {checks: [], details: []});
  node.functional.cases.items = [];
  node.performance = [];
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor(node.node, node.role)});
  app.click({page: "aggregate"});
  for (const [key, index] of [["all", -1], [keyFor(node.node, node.role), 0]]) {
    app.click({aggregateRole: key, roleMetric: "functional"});
    assertAggregateRole(app, [node], index);
    const functional = aggregatePanel(app, "functional"), summary = classElement(functional, "functional-rollup");
    assert.equal((summary.match(/class="summary-card"/g) || []).length, 3);
    assert.match(summary, />미판정<\/span>/);
    assert.match(summary, /<strong>산출 불가<\/strong>/);
    assert.match(summary, /검증 완료 0 \/ 전체 0<\/p>/);
    assert.equal((functional.match(/저장된 지표가 없습니다\./g) || []).length, 2);
    assert.match(functional, /사례별 판정·반복 충족·미완료 사유 \(0사례\)/);
    assert.match(classElement(aggregatePanel(app, "operational"), "operational-goals-table"), /등록된 운영 목표가 없습니다/);
    assert.doesNotMatch(summary, /NaN|Infinity/);
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("numbered node names label only the all-target button while titles and scopes remain unchanged", () => {
  const data = scoredCatalog(), original = structuredClone(data), app = harness(data);
  const initialRows = app.element("#case-rows").innerHTML, initialContext = app.element("#context").textContent;
  const navigation = app.element("#target-nav").innerHTML, all = markedElement(navigation, "data-target", "all");
  assert.doesNotMatch(all, /전체 대상/);
  for (const name of ["N01 작업 목적 파악", "N02 작업 선택 및 실행", "N03 작업 진행 판단", "N05 사용자 정보 요청"]) assert.ok(all.includes(name), name);
  assert.doesNotMatch(app.element("#target-title").textContent, /N0\d/);
  assert.doesNotMatch(app.element("#batch-select").innerHTML, /N0\d/);
  assert.match(initialContext, /4개 사례 · 8개 등록 실행/);
  for (const [node, role, label] of [["interpret", "interpretation", "분석 결과 해석"], ["ask", "request", "사용자 요청 처리"]]) {
    const button = markedElement(navigation, "data-target", escapeHTML(keyFor(node, role)));
    const visible = button.replace(/<[^>]*>/g, "");
    assert.ok(visible.includes(label));
    assert.doesNotMatch(visible, /N0\d|작업 목적 파악|사용자 정보 요청/);
    app.click({target: keyFor(node, role)});
    assert.equal(app.element("#target-title").textContent, label);
    app.click({page: "aggregate"});
    for (const tab of ["functional", "operational"]) {
      const panel = aggregatePanel(app, tab);
      assert.doesNotMatch(panel, new RegExp(`<h3[^>]*>(?:${label}|N0\\d[^<]*)</h3>`));
    }
  }
  app.click({target: "all"});
  assert.equal(app.element("#case-rows").innerHTML, initialRows);
  assert.equal(app.element("#context").textContent, initialContext);
  assert.match(app.element("#case-rows").innerHTML, /selection-only/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("saved node and role metrics, operational statistics and re-evaluations reach both views", () => {
  const data = scoredCatalog(), original = structuredClone(data), app = harness(data);
  const records = data.batches[0].assessments;
  const latest = records[0].report.nodes.find(n => n.node === "interpret");
  app.click({target: keyFor("interpret", "interpretation")});
  assert.match(app.element("#case-detail").innerHTML, /data-case-tab="functional"/);
  app.click({page: "aggregate"});
  let html = app.element("#aggregate-page").innerHTML;
  assert.equal(app.element("#target-title").textContent, "분석 결과 해석");
  assertAllCaseFunctionalRollup(app, latest.functional);
  assert.match(html, /입력 토큰/);
  assert.match(html, /출력 토큰/);
  assert.match(html, /모델 호출 수/);
  assert.match(html, /기술적 재시도 합계/);
  assert.ok(classElement(html, "operational-rollup"));
  assert.match(html, /class="operational-goals-table"/);
  app.change("assessment-select", records[1].path);
  html = app.element("#aggregate-page").innerHTML;
  const earlier = records[1].report.nodes.find(n => n.node === "interpret");
  assertAllCaseFunctionalRollup(app, earlier.functional);
  app.click({page: "cases"});
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /data-detail=|data-assessment-key=/);
  app.change("assessment-select", records[0].path);
  app.click({page: "aggregate"});
  assertAllCaseFunctionalRollup(app, latest.functional);
  assert.deepEqual(app.loadedCatalog(), original, "switching records never rewrites saved evidence");
});

test("node role navigation separates identical node names and selection-only evidence", () => {
  const data = scoredCatalog(), a = data.batches[0].assessments[0].report;
  const n = structuredClone(a.nodes.find(n => n.node === "interpret"));
  n.role = "report_selection";
  n.functional.cases.numerator = 0;
  n.functional.cases.denominator = 7;
  n.functional.cases.rate = 0;
  a.nodes.push(n);
  const evidence = structuredClone(a.assessments.find(x => x.node === "interpret"));
  evidence.role = n.role;
  evidence.run_id = "missing-role-run";
  a.assessments.push(evidence);
  const app = harness(data);
  assert.match(app.element("#target-nav").innerHTML, /분석 결과 해석/);
  assert.match(app.element("#target-nav").innerHTML, /보고서 시각화 선정/);
  app.click({target: keyFor("interpret", n.role)});
  app.click({page: "aggregate"});
  assertAllCaseFunctionalRollup(app, n.functional);
  assert.match(app.element("#aggregate-page").innerHTML, /실행 원본 미제공 · missing-role-run/);
  const selected = a.assessments.find(x => !x.counted);
  assert.ok(selected, "fixture includes selection-only evidence");
  app.click({target: keyFor(selected.node, selected.role, false)});
  const html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /작업 선택만 실행한 결과는 노드 지표에서 제외됩니다/);
  assert.match(html, /노드 지표 집계 제외/);
  assert.doesNotMatch(html, /<span>필수 사례 통과율<\/span>/);
});

test("stored metrics preserve zero, null, pending verdicts, missing counts and skipped checks", () => {
  const data = scoredCatalog(), n = data.batches[0].assessments[0].report.nodes.find(n => n.node === "interpret");
  Object.assign(n.functional.cases, {numerator: 0, denominator: 0, rate: null});
  Object.assign(n.functional, {verdict: "미판정", complete: false});
  Object.assign(n.functional.cases.items[0], {verdict: "미판정", complete: false});
  Object.assign(n.operational.failure_rate, {numerator: 0, denominator: 0, rate: null, missing_count: 9, unfinished_count: 8});
  Object.assign(n.operational.tokens.input_tokens, {sample_count: 2, mean: 0, median: 0, p95: 0, missing_count: 0, unfinished_count: 0});
  n.performance = [];
  Object.assign(n.functional.checks[0], {numerator: 0, denominator: 2, rate: 0, failed: 2, passed: 0, unexecuted: 3, skipped_after_failure: 2});
  const original = structuredClone(data), app = harness(data);
  app.click({target: keyFor(n.node, n.role)});
  app.click({page: "aggregate"});
  app.click({aggregateRole: keyFor(n.node, n.role), roleMetric: "functional"});
  const html = app.element("#aggregate-page").innerHTML;
  assertAllCaseFunctionalRollup(app, n.functional);
  assert.match(html, /산출 불가/);
  assert.match(classElement(aggregatePanel(app, "functional"), "check-results-table"), /<td>0%<\/td>/);
  assert.match(html, /미판정/);
  assert.match(html, /실패 여부 미확인 9건/);
  assert.match(html, /미종료 8건/);
  assert.match(html, /입력 토큰<\/td><td>2<\/td><td>0<\/td><td>0<\/td><td>0/);
  assert.match(html, /선행 실패로 생략/);
  assert.doesNotMatch(html, /운영 목표 미제공 · 목표 충족 여부 미판정/);
  assert.doesNotMatch(html, /NaN|Infinity/);
  const functional = aggregatePanel(app, "functional"), operational = aggregatePanel(app, "operational");
  assert.doesNotMatch(classElement(functional, "functional-rollup"), /0 \/ 0/);
  assert.match(classElement(functional, "functional-rollup"), /<strong>0%<\/strong>/);
  assert.match(classElement(functional, "check-results-table"), /<td>0%<\/td>/);
  assert.match(functional, /미판정/);
  assert.match(functional, /선행 실패로 생략/);
  app.click({aggregateTab: "operational"});
  assertAggregateTab(app, "operational");
  assert.match(operational, /실패 여부 미확인 9건/);
  assert.match(operational, /미종료 8건/);
  assert.match(operational, /입력 토큰<\/td><td>2<\/td><td>0<\/td><td>0<\/td><td>0/);
  assert.match(operational, /등록된 운영 목표가 없습니다/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("check and detail drilldowns expose saved actual, expected, LLM calls and escaped evidence", () => {
  const data = scoredCatalog(), a = data.batches[0].assessments[0].report;
  const assessed = a.assessments.find(item => item.node === "interpret" && item.checks.some(check => check.calls.some(call => call.judge)));
  assert.ok(assessed, "all-mode fixture includes judge evidence");
  const check = assessed.checks.find(check => check.calls.some(call => call.judge));
  const detail = check.details[0];
  const injection = '<img src=x onerror="bad()">';
  detail.reason = injection;
  detail.actual = {saved_actual: injection};
  detail.expected = {saved_expected: 0};
  const app = harness(data);
  app.click({page: "aggregate"});
  app.click({scoreCheck: JSON.stringify([assessed.node, assessed.role, check.check, check.verdict, null])});
  let html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /개별 판정 근거 · 2건/);
  assert.match(html, /평가 모델 판정·입력·근거 전체 기록/);
  assert.match(html, /평가 모델 원응답 · SDK/);
  assert.match(html, /기대값/);
  assert.match(html, /실제값/);
  assert.match(html, /saved_actual/);
  assert.match(html, /saved_expected/);
  assert.match(html, /&lt;img src=x onerror=&quot;bad\(\)&quot;&gt;/);
  assert.doesNotMatch(html, /<img /);
  assert.equal(app.element("#score-evidence").focused, 1);
  app.click({scoreCheck: JSON.stringify([assessed.node, assessed.role, check.check, detail.verdict, detail.id])});
  html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /실행 입출력 확인/);
  app.click({scoreCheck: JSON.stringify([assessed.node, assessed.role, check.check, "실패", "missing-detail"]) });
  assert.match(app.element("#aggregate-page").innerHTML, /개별 판정 근거 · 0건/);
});

test("score-only files keep role navigation and expose missing executions without inventing inputs", () => {
  const files = samples.files.filter(f => f.path.endsWith(".json") && JSON.parse(f.text).schema_version === "node-evaluation-v1");
  const data = EvaluationData.parseFiles(files), app = harness(data);
  assert.equal(app.element("#aggregate-page").hidden, false);
  assert.match(app.element("#target-nav").innerHTML, /분석 결과 해석/);
  assert.match(app.element("#aggregate-page").innerHTML, /실행 원본 미제공/);
  app.click({target: keyFor("interpret", "interpretation")});
  assert.match(app.element("#aggregate-page").innerHTML, /전체 사례 통과율/);
  assert.doesNotMatch(app.element("#aggregate-page").innerHTML, /data-open-run=/);
});

function pendingEvidenceCatalog() {
  const data = scoredCatalog(), report = data.batches[0].assessments[0].report;
  const source = report.assessments.find(item => item.counted && item.checks.some(check => check.details.length));
  const check = source.checks.find(check => check.details.length);
  report.assessments = ["assessed-pending", "unexecuted-pending", "selection-pending"].map(caseId => {
    const item = structuredClone(source);
    item.case_id = caseId;
    item.run_id = `run-${caseId}`;
    item.node_id = `node-${caseId}`;
    item.counted = caseId !== "selection-pending";
    item.checks = [structuredClone(check)];
    Object.assign(item.checks[0], {verdict: "미판정", executed: true});
    item.checks[0].details = [{...structuredClone(check.details[0]), verdict: "미판정", executed: true}];
    return item;
  });
  return {data, assessments: report.assessments};
}

test("check-count links exclude unexecuted and selection-only verdicts while all evidence preserves them", () => {
  const {data, assessments} = pendingEvidenceCatalog();
  assessments[1].checks[0].executed = false;
  const checked = assessments[0], check = checked.checks[0], app = harness(data);
  app.click({page: "aggregate"});
  app.click({aggregateRole: keyFor(checked.node, checked.role), roleMetric: "functional"});
  let html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /개별 판정 근거 · 3건/);
  for (const item of assessments) assert.ok(html.includes(`<strong>${item.case_id} ·`));
  app.click({scoreCheck: JSON.stringify([checked.node, checked.role, check.check, "미판정", null])});
  html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /개별 판정 근거 · 1건/);
  assert.match(html, /<strong>assessed-pending ·/);
  assert.doesNotMatch(html, /<strong>(?:unexecuted|selection)-pending ·/);
  app.click({clearScoreFilter: ""});
  html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /개별 판정 근거 · 3건/);
  for (const item of assessments) assert.ok(html.includes(`<strong>${item.case_id} ·`));
});

test("detail-count links use each detail's execution status and keep selection-only details out", () => {
  const {data, assessments} = pendingEvidenceCatalog();
  assessments[1].checks[0].details[0].executed = false;
  const checked = assessments[0], check = checked.checks[0], app = harness(data);
  app.click({page: "aggregate"});
  app.click({aggregateRole: keyFor(checked.node, checked.role), roleMetric: "functional"});
  let html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /개별 판정 근거 · 3건/);
  for (const item of assessments) assert.ok(html.includes(`<strong>${item.case_id} ·`));
  // Both counted checks ran, but only one of their matching details ran.
  app.click({scoreCheck: JSON.stringify([checked.node, checked.role, check.check, "미판정", null])});
  assert.match(app.element("#aggregate-page").innerHTML, /개별 판정 근거 · 2건/);
  app.click({scoreCheck: JSON.stringify([checked.node, checked.role, check.check, "미판정", check.details[0].id])});
  html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /개별 판정 근거 · 1건/);
  assert.match(html, /<strong>assessed-pending ·/);
  assert.doesNotMatch(html, /<strong>(?:unexecuted|selection)-pending ·/);
  app.click({clearScoreFilter: ""});
  assert.match(app.element("#aggregate-page").innerHTML, /개별 판정 근거 · 3건/);
});

test("execution-only files show raw model evidence while leaving node grading unavailable", () => {
  const data = unscoredCatalog(), app = harness(data);
  const run = runFor(data, "interpret-pass");
  app.click({case: caseKey(run)});
  assert.match(app.element("#case-detail").innerHTML, /채점.*미제공|검사.*미제공/);
  assert.match(app.element("#case-detail").innerHTML, /<h3 id="case-io-title">입출력<\/h3>/);
  const saved = run.report.trace.spans.find(span => span.kind === "model").output.sdk_response.content;
  const output = ioSection(app, "출력");
  assert.match(output, /class="value-table"/);
  assert.ok(output.includes(escapeHTML(JSON.parse(saved).request.goal)));
  assert.doesNotMatch(output, /<pre>/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /data-detail=|data-download=/);
  app.click({page: "aggregate"});
  assert.match(app.element("#aggregate-page").innerHTML, /노드 채점 결과 미제공/);
  assert.doesNotMatch(app.element("#aggregate-page").innerHTML, /\d+(?:\.\d+)?%/);
});

function hundredCases() {
  const data = unscoredCatalog(), batch = data.batches[0];
  const sourceRun = runFor(data, "interpret-pass");
  batch.runs = Array.from({length: 100}, (_, index) => {
    const run = structuredClone(sourceRun);
    run.key = `batch/runs/run-${index}/report.json`;
    run.path = run.key;
    Object.assign(run.report.run, {id: `run-${index}`, case_id: `case-${index}`, repetition: 1});
    if (run.report.state) run.report.state.execution.run_id = `run-${index}`;
    Object.assign(run.entry, {run_id: `run-${index}`, case_id: `case-${index}`, repetition: 1});
    Object.assign(run.case, {id: `case-${index}`, purpose: `페이지 탐색 사례 ${index}`, tags: ["mobile-fixture"]});
    run.case.assessment.required = true;
    return run;
  });
  batch.report.planned_runs = 100;
  batch.report.runs = batch.runs.map(run => run.entry);
  return data;
}

test("100-case pagination and search keep selected detail on the visible page", () => {
  const app = harness(hundredCases());
  for (let index = 0; index < 3; index++) app.click({pageStep: "1"});
  assert.match(app.element("#pagination").innerHTML, /4 \/ 4쪽/);
  assert.match(app.element("#case-detail").innerHTML, /사례 case-75/);
  app.trigger("#case-search", "input", "페이지 탐색 사례");
  assert.match(app.element("#pagination").innerHTML, /1 \/ 4쪽/);
  assert.match(app.element("#case-rows").innerHTML, /class="selected"/);
  assert.match(app.element("#case-detail").innerHTML, /사례 case-0/);
});

test("case-list filters leave the selected node aggregate metrics unchanged", () => {
  const app = harness(scoredCatalog());
  app.click({target: keyFor("interpret", "interpretation")});
  app.click({page: "aggregate"});
  const before = app.element("#aggregate-page").innerHTML;
  app.click({page: "cases"});
  app.trigger("#case-search", "input", "없는 사례");
  assert.match(app.element("#case-rows").innerHTML, /표시할 사례가 없습니다/);
  app.click({page: "aggregate"});
  assert.equal(app.element("#aggregate-page").innerHTML, before);
});

test("sidebar cases remain searchable in aggregate and selecting a case opens its detail", () => {
  const data = scoredCatalog(), app = harness(data), run = runFor(data, "interpret-pass");
  app.click({page: "aggregate"});
  app.trigger("#case-search", "input", "interpret-pass");
  assert.match(app.element("#case-rows").innerHTML, /interpret-pass/);
  assert.doesNotMatch(app.element("#case-rows").innerHTML, /decide-format-fail/);
  app.click({case: caseKey(run)});
  assert.equal(app.element("#case-page").hidden, false);
  assert.equal(app.element("#aggregate-page").hidden, true);
  assert.match(app.element("#case-detail").innerHTML, /사례 interpret-pass/);
  assert.equal(app.element("#case-search").value, "interpret-pass");
});

test("original case and model-output text remains escaped in list and input views", () => {
  const data = unscoredCatalog(), injection = '<img src=x onerror="alert(1)">', modelInjection = '<script>alert("model")</script>';
  for (const run of data.batches[0].runs) {
    run.case.purpose = injection;
    run.report.output = {model_response: modelInjection};
    for (const span of run.report.trace.spans.filter(span => span.kind === "model")) span.output.sdk_response.content = modelInjection;
  }
  const app = harness(data);
  assert.match(app.element("#case-rows").innerHTML, /&lt;img /);
  assert.doesNotMatch(app.element("#case-rows").innerHTML, /<img /);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /&lt;img /);
  assert.match(app.element("#case-detail").innerHTML, /&lt;script&gt;/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /<img /);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /<script>/);
});

test("mobile sidebar and detail focus preserve filters, page, tab and selected repetition", () => {
  const data = hundredCases(), selected = data.batches[0].runs[77];
  const repetition = structuredClone(selected);
  repetition.key = "mobile/run-77-repeat/report.json";
  repetition.path = repetition.key;
  Object.assign(repetition.report.run, {id: "run-77-repeat", repetition: 2});
  if (repetition.report.state) repetition.report.state.execution.run_id = "run-77-repeat";
  Object.assign(repetition.entry, {run_id: "run-77-repeat", repetition: 2});
  data.batches[0].runs.push(repetition);
  const original = structuredClone(data), app = harness(data, {width: 390});
  assert.equal(app.element("#case-page").hidden, false);
  assert.match(app.element("#target-nav").innerHTML, /class="target-button"/);
  assert.doesNotMatch(source, /#target-picker|#target-count/);
  assert.equal(app.element("#case-filters").open, false);
  assert.equal(app.element("#case-list-picker").open, false);
  assert.equal(app.element("#case-list-count").textContent, "100개");
  assert.equal(app.element("#case-list-selection").textContent, "선택: 사례 case-0");
  app.trigger("#case-search", "input", "페이지 탐색 사례");
  app.trigger("#status-filter", "change", "returned");
  app.trigger("#tag-filter", "change", "mobile-fixture");
  app.trigger("#required-filter", "change", "yes");
  for (let index = 0; index < 3; index++) app.click({pageStep: "1"});
  app.click({case: caseKey(selected)});
  assert.equal(app.element("#case-list-picker").open, false);
  assert.equal(app.element("#case-list-selection").textContent, "선택: 사례 case-77");
  assert.equal(app.element("#case-page").hidden, false);
  assert.equal(app.element("#case-detail").focused, 1);
  assert.equal(app.element("#case-detail").scrolled, 1);
  app.change("run-select", repetition.key);
  app.click({caseTab: "operational"});
  assert.match(app.element("#case-detail").innerHTML, /selected>2회차/);
  assert.match(app.element("#case-detail").innerHTML, /data-case-tab="operational"[^>]*aria-selected="true"/);
  assert.match(app.element("#case-detail").innerHTML, /^<button[^>]*class="back-to-list"[^>]*data-back-to-list/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /class="detail-heading"|<span>사례 상세<\/span>/);
  const before = Object.fromEntries(["#case-rows", "#case-detail", "#pagination"].map(id => [id, app.element(id).innerHTML]));
  app.click({backToList: ""});
  assert.equal(app.element("#case-list-picker").open, true);
  assert.equal(app.element("#case-page").hidden, false);
  assert.equal(app.element("#case-list").focused, 1);
  for (const [id, markup] of Object.entries(before)) assert.equal(app.element(id).innerHTML, markup);
  for (const [id, value] of [["case-search", "페이지 탐색 사례"], ["status-filter", "returned"], ["tag-filter", "mobile-fixture"], ["required-filter", "yes"]]) assert.equal(app.element("#" + id).value, value);
  assert.match(app.element("#pagination").innerHTML, /4 \/ 4쪽/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("mobile aggregate opens original run and retains metric selection", () => {
  const data = hundredCases(), app = harness(data, {width: 760});
  app.click({caseTab: "operational"});
  app.trigger("#case-search", "input", "없는 사례");
  app.click({page: "aggregate"});
  const run = data.batches[0].runs[75];
  app.click({openRun: run.key});
  assert.equal(app.element("#case-page").hidden, false);
  assert.equal(app.element("#aggregate-page").hidden, true);
  assert.match(app.element("#case-detail").innerHTML, /사례 case-75/);
  assert.match(app.element("#case-detail").innerHTML, /<h3 id="case-io-title">입출력<\/h3>/);
  assert.match(app.element("#case-detail").innerHTML, /data-case-tab="operational"[^>]*aria-selected="true"/);
  assert.equal(app.element("#case-io-pane").focused, 1);
  assert.equal(app.element("#case-io-pane").scrolled, 1);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /data-detail=/);
  assert.match(app.element("#pagination").innerHTML, /4 \/ 4쪽/);
  assert.equal(app.element("#case-search").value, "");
  app.click({target: "all"});
  assert.equal(app.element("#case-page").hidden, false);
  app.click({case: caseKey(data.batches[0].runs[0])});

});



test("readable evaluation names, Korean times and downloads remain in aggregate and grading selection", () => {
  const data = scoredCatalog(), batch = data.batches[0];
  batch.report.id = "노드평가_2026-11-12_실행07";
  batch.report.started_at = "2026-11-12T08:00:00Z";
  batch.assessments.forEach((record, index) => {
    record.report.batch_id = batch.report.id;
    record.report.id = `${batch.report.id}_채점${String(8 - index).padStart(2, "0")}`;
    record.report.assessed_at = "2026-11-12T08:59:01.322553+00:00";
    record.path = `saved/${batch.report.id}/assessments/${record.report.id}.json`;
  });
  const original = structuredClone(data), app = harness(data), record = batch.assessments[0];
  app.click({page: "aggregate"});
  const html = app.element("#aggregate-page").innerHTML;
  assert.ok(html.includes("노드평가 · 2026-11-12 실행07 · 채점08"));
  assert.ok(html.includes("2026년 11월 12일 17:59:01 (한국시간)"));
  assert.ok(html.includes(`<dt>결과 파일</dt><dd>${record.report.id}.json</dd>`));
  assert.ok(html.includes(`<summary>저장 위치</summary><code>${record.path}</code>`));
  assert.doesNotMatch(html, /<dt>평가 ID<|<dt>채점 시각<|<dt>실행 묶음 ID</);
  const download = html.match(/<summary>채점 결과 전체<\/summary>\s*<div class="raw-tools"><button type="button" data-download="(\d+)"/);
  assert.ok(download, "the original full assessment has a download action");
  app.click({download: download[1]});
  assert.equal(app.downloaded[0].name, `${record.report.id}.json`);
  app.click({page: "cases"});
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /data-detail=|data-download=|채점 기준·근거·평가기 해시|<summary>저장 위치<\/summary>/);
  app.change("assessment-select", batch.assessments[1].path);
  app.click({page: "aggregate"});
  assert.ok(app.element("#aggregate-page").innerHTML.includes("노드평가 · 2026-11-12 실행07 · 채점07"));
  assert.deepEqual(app.loadedCatalog(), original);
});
