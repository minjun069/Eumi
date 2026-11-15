"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const EvaluationNames = require("../shared/record-names.js");
const ExecutionEvaluationData = require("./data.js");
const ExecutionValues = require("./structured-value.js");
const ExecutionOperational = require("./operational.js");
const ExecutionAutomatic = require("./automatic.js");
const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
require("./samples.js");
const samples = globalThis.ExecutionEvaluationSamples();
const {copyFiles, qualityScore} = require("../shared/assessment-fixtures.cjs");
const catalog = ExecutionEvaluationData.parseFiles(samples.files);
const {fixture: baseLazyFixture} = require("../shared/lazy-ui-fixtures.cjs");
function lazyFixture(files, schema) {
  const fixture = baseLazyFixture(files, schema);
  fixture.entry.assessments = fixture.entry.assessments.filter(ref => ref.report_schema_version);
  fixture.texts.set("eval/outputs/evaluation-viewer/catalog.json", JSON.stringify(fixture.index));
  return fixture;
}
async function until(predicate) {
  for (let i = 0; i < 2000; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 5)); }
  throw new Error("UI state did not settle");
}

test("HTTP startup loads every case, check, criteria and trace in the selected execution batch", async () => {
  const fixture = lazyFixture(samples.files, "execution-evaluation-v1");
  const entry = (id, units, schema) => ({id, path:`fixture-${id}/batch.json`, units,
    assessments:schema ? [{format:"legacy", path:`fixture-${id}/assessments/score.json`, report_schema_version:schema}] : []});
  fixture.index.batches.push(entry("node-only", ["node"], "node-evaluation-v1"), entry("tool-only", ["tool"], "tool-evaluation-v1"),
    entry("unknown-legacy", undefined), entry("mixed-agent", ["node", "agent"]), entry("workflow-only", ["workflow"]),
    entry("quality-only", undefined, "output-evaluation-v1"));
  fixture.texts.set("eval/outputs/evaluation-viewer/catalog.json", JSON.stringify(fixture.index));
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => app.element("#application").attributes["aria-busy"] === "false");
  assert.doesNotMatch(app.element("#notice").textContent, /오류/);
  assert.doesNotMatch(app.element("#batch-select").innerHTML, /node-only|tool-only|unknown-legacy/);
  for (const name of ["mixed-agent", "workflow-only", "quality-only"]) assert.match(app.element("#batch-select").innerHTML, new RegExp(name));
  const folder = fixture.entry.path.replace(/[^/]+$/, "");
  const required = [...fixture.texts.keys()].filter(path => path.startsWith(folder));
  for (const path of required) assert.ok(fixture.calls.includes(path), path);
  assert.ok(!fixture.calls.some(path => path.startsWith("fixture-")), "other batches remain untouched");
  const before = fixture.calls.length;
  await app.click({aggregate:"operational"});
  assertAggregateTab(app, "operational");
  assert.doesNotMatch(app.element("#aggregate-page").innerHTML, /data-lazy|원문 읽기|아직 읽지 않은/);
  await app.click({page:"cases"});
  assert.match(detailPanelHtml(app, "assessment"), /검사 항목/);
  assert.equal(fixture.calls.length, before);
});

test("HTTP batch choices distinguish the same execution name across agent folders", async () => {
  const fixture = lazyFixture(samples.files, "execution-evaluation-v1");
  fixture.index.batches.push({id:fixture.entry.id, path:`evaluations/interpretation/${fixture.entry.id}/batch.json`, units:["agent"], assessments:[]});
  fixture.texts.set("eval/outputs/evaluation-viewer/catalog.json", JSON.stringify(fixture.index));
  const app = harness(catalog, {lazy:fixture.lazy, autoOnly:true});
  await until(() => app.element("#application").attributes["aria-busy"] === "false");
  assert.match(app.element("#batch-select").innerHTML, /evaluations\/interpretation/);
  assert.ok(!fixture.calls.some(path => path.startsWith("evaluations/interpretation/")));
});

// Exercise the actual UI event handlers and rendered content without replacing
// their navigation logic. Browser layout and file-picker checks are separate.
function harness(initial = catalog, {width = 1440, autoOnly = false, scenarios = {resolve: () => null}, lazy} = {}) {
  const elements = new Map();
  const documentListeners = new Map();
  const downloaded = [];
  const downloadBlobs = new Map();
  function element(selector) {
    if (!elements.has(selector)) {
      const classes = new Set();
      elements.set(selector, {
        innerHTML: "", textContent: "", value: "", hidden: false, disabled: false,
        dataset: {}, attributes: {}, listeners: new Map(), focused: 0, scrolled: 0,
        classList: {
          toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
          contains(name) { return classes.has(name); },
        },
        addEventListener(type, listener) { this.listeners.set(type, listener); },
        setAttribute(name, value) { this.attributes[name] = value; },
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
    createElement: () => ({click() { downloaded.push({name: this.download, url: this.href, blob: downloadBlobs.get(this.href)}); }}),
    querySelector: element,
    querySelectorAll: selector => selector === ".page-tabs [data-page]" ? pageTabs : [],
    addEventListener: (type, listener) => documentListeners.set(type, listener),
  };
  let initialRead = !autoOnly;
  let loadedCatalog;
  vm.runInNewContext(source, {
    document, Blob, setTimeout, EvaluationNames, ExecutionValues, ExecutionOperational, ExecutionAutomatic, ExecutionScenarios: scenarios,
    EvaluationLazy: lazy, location: {href: "http://localhost/eval/viewers/execution/"},
    URL: class extends URL {
      static createObjectURL(blob) { const url = URL.createObjectURL(blob); downloadBlobs.set(url, blob); return url; }
      static revokeObjectURL = URL.revokeObjectURL;
    },
    matchMedia: query => ({matches: width <= Number(query.match(/max-width:\s*(\d+)px/)[1]), addEventListener() {}}),
    ExecutionEvaluationSamples: () => samples,
    ExecutionEvaluationData: {
      parseFiles(files) {
        const result = initialRead ? structuredClone(initial) : ExecutionEvaluationData.parseFiles(files);
        initialRead = false;
        if (result.batches.length) loadedCatalog = result;
        return result;
      },
    },
  });
  function trigger(selector, type, value) {
    const node = element(selector);
    if (value !== undefined) node.value = value;
    return node.listeners.get(type)({ target: node });
  }
  function click(dataset) {
    return documentListeners.get("click")({ target: { closest: () => ({ dataset, disabled: false }) } });
  }
  if (!autoOnly) trigger("#sample-button", "click");
  return { element, trigger, click, downloaded, loadedCatalog: () => loadedCatalog,
    change(id, value) { return documentListeners.get("change")({target: {id, value}}); },
    toggleScenario(open) { return documentListeners.get("toggle")({target: {id:"case-scenario", isConnected:true, open}}); },
    key(detail, key) {
      let prevented = false;
      documentListeners.get("keydown")({target: {dataset: {detail}}, key, preventDefault() { prevented = true; }});
      return prevented;
    },
    aggregateKey(aggregate, key) {
      let prevented = false;
      documentListeners.get("keydown")({target: {dataset: {aggregate}}, key, preventDefault() { prevented = true; }});
      return prevented;
    },
    operationalKey(operationalAgent, key) {
      let prevented = false;
      documentListeners.get("keydown")({target: {dataset: {operationalAgent}}, key, preventDefault() { prevented = true; }});
      return prevented;
    },
    async files(files) {
    element("#files-input").files = files;
    return trigger("#files-input", "change");
  } };
}

function scoredCatalog() {
  return {batches: [structuredClone(catalog.batches.find(b => b.assessments?.length))], issues: []};
}


function unscoredCatalog() {
  const data = scoredCatalog();
  data.batches[0].assessments = [];
  return data;
}

const keyFor = (target) => JSON.stringify([target === "report" ? "workflow" : "agent", target]);
const caseKey = run => JSON.stringify([run.report.run.case_id, run.report.run.unit, run.report.run.target]);

function assertTabs(html, prefix, attribute, keys, selected) {
  const tabs = [...html.matchAll(new RegExp(`<button\\b[^>]*\\bdata-${attribute}="([^"]+)"[^>]*>`, "g"))];
  assert.deepEqual(tabs.map(match => match[1]), keys);
  for (const [button, key] of tabs) {
    assert.match(button, /\brole="tab"/);
    assert.ok(button.includes(`id="${prefix}-tab-${key}"`));
    assert.ok(button.includes(`aria-controls="${prefix}-panel-${key}"`));
    assert.ok(button.includes(`aria-selected="${key === selected}"`));
    assert.ok(button.includes(`tabindex="${key === selected ? 0 : -1}"`));
    const panel = html.match(new RegExp(`<[^>]+\\bid="${prefix}-panel-${key}"[^>]*>`));
    assert.ok(panel, `the ${key} panel is available`);
    assert.match(panel[0], /\brole="tabpanel"/);
    assert.ok(panel[0].includes(`aria-labelledby="${prefix}-tab-${key}"`));
    assert.equal(/\bhidden(?:\s|>|=)/.test(panel[0]), key !== selected, `${key} panel visibility`);
  }
}

function assertDetailTab(app, selected) {
  assertTabs(app.element("#case-detail").innerHTML, "case", "detail", ["assessment", "quality", "operational", "io"], selected);
}

function assertAggregateTab(app, selected) {
  assertTabs(app.element("#aggregate-page").innerHTML, "aggregate", "aggregate", ["functional", "quality", "operational"], selected);
}

function panelHtml(html, prefix, key) {
  const panels = [...html.matchAll(/<[^>]+\brole="tabpanel"[^>]*>/g)].filter(match => match[0].includes(`id="${prefix}-panel-`));
  const index = panels.findIndex(match => match[0].includes(`id="${prefix}-panel-${key}"`));
  assert.ok(index >= 0, `the ${key} panel exists`);
  return html.slice(panels[index].index, panels[index + 1]?.index ?? html.length);
}

const detailPanelHtml = (app, key) => panelHtml(app.element("#case-detail").innerHTML, "case", key);
const aggregatePanelHtml = (app, key) => panelHtml(app.element("#aggregate-page").innerHTML, "aggregate", key);

function qualityFiles() {
  const source = samples.files.find(file => {
    try { return JSON.parse(file.text).schema_version === "execution-evaluation-v1"; } catch (_) { return false; }
  });
  const quality = qualityScore(JSON.parse(source.text));
  const path = source.path.replace(/[^/]+$/, "quality.json");
  return {quality, path, files: [...samples.files, {path, text: JSON.stringify(quality)}]};
}

test("quality records keep their verdict and original author/judge evidence separate from execution and operations", async () => {
  const fixture = qualityFiles(), data = ExecutionEvaluationData.parseFiles(fixture.files);
  const batch = data.batches.find(item => item.assessments.some(a => a.report.schema_version === "output-evaluation-v1"));
  const quality = batch.assessments.find(a => a.report.schema_version === "output-evaluation-v1");
  const before = structuredClone(batch);
  const changed = structuredClone(quality);
  changed.path = changed.path.replace("quality.json", "quality-regraded.json");
  changed.report.id += "-regraded";
  changed.report.assessed_at = "2026-11-13T13:00:00+09:00";
  changed.report.runs[0].reason = "새로 선택한 품질 판정 사유";
  batch.assessments.push(changed);
  const app = harness({batches: [batch], issues: []});
  await app.click({page:"aggregate"});
  const functional = aggregatePanelHtml(app, "functional"), operating = aggregatePanelHtml(app, "operational");
  await app.click({aggregate:"quality"});
  assertAggregateTab(app, "quality");
  const html = aggregatePanelHtml(app, "quality");
  for (const term of ["실제로 반환한 설명", "N04-O.1", "original-compose", "original-call", "작성 모델 호출 3", "품질 평가 입력", "저장된 평가 원응답"])
    assert.ok(html.includes(term), term);
  assert.doesNotMatch(html, /보고서 완성률|기술적 실패율/);
  const download = html.match(/<summary>평가 모델 원응답<\/summary>\s*<div class="raw-tools"><button type="button" data-download="(\d+)"/);
  assert.ok(download, "quality evidence downloads remain available");
  await app.click({download: download[1]});
  assert.deepEqual(JSON.parse(await app.downloaded[0].blob.text()), {content: "저장된 평가 원응답"});
  assert.deepEqual(Object.keys(quality.report.summary).filter(key => ["functional", "operational", "report_completion"].includes(key)), []);
  await app.change("quality-select", changed.path);
  assert.match(aggregatePanelHtml(app,"quality"), /새로 선택한 품질 판정 사유/);
  await app.click({aggregate:"functional"});
  assert.equal(aggregatePanelHtml(app, "functional"), functional);
  assert.equal(aggregatePanelHtml(app, "operational"), operating);
  assert.deepEqual(app.loadedCatalog().batches[0].assessments.find(a => a.path === quality.path).report, before.assessments.find(a => a.path === quality.path).report);
  assert.doesNotMatch(app.element("#aggregate-page").innerHTML, /data-aggregate="(?:records|evidence|criteria)"/);
});

test("quality without an execution assessment still links the original run and retains unavailable EX metrics", async () => {
  const fixture = qualityFiles();
  const files = fixture.files.filter(file => {
    try { return JSON.parse(file.text).schema_version !== "execution-evaluation-v1"; } catch (_) { return true; }
  });
  const data = ExecutionEvaluationData.parseFiles(files);
  const batch = data.batches.find(item => item.assessments.length);
  const app = harness({batches: [batch], issues: []});
  const run = batch.runs.find(item => item.report.run.id === fixture.quality.runs[0].run_id);
  assert.ok(run, "the quality result links to its actual report");
  await app.click({openRun:run.key});
  await app.click({detail:"quality"});
  assertDetailTab(app, "quality");
  assert.match(detailPanelHtml(app, "quality"), /실제로 반환한 설명/);
  assert.match(detailPanelHtml(app, "assessment"), /미제공/);
  await app.click({page:"aggregate"});
  assert.match(aggregatePanelHtml(app, "functional"), /실행 채점 결과 미제공/);
  assert.match(aggregatePanelHtml(app, "quality"), /original-compose/);
});

test("HTTP startup restores quality call identity and original criteria beside execution results", async () => {
  const fixture = lazyFixture(qualityFiles().files, "execution-evaluation-v1");
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => app.element("#application").attributes["aria-busy"] === "false");
  assert.doesNotMatch(app.element("#notice").textContent, /오류/);
  const before = fixture.calls.length, execution = aggregatePanelHtml(app, "functional");
  await app.click({aggregate:"quality"});
  const html = aggregatePanelHtml(app, "quality");
  for (const term of ["실제로 반환한 설명", "original-compose", "original-call", "작성 모델 호출 3", "저장된 평가 원응답", "실제 작성 호출의 내용 검사"])
    assert.ok(html.includes(term), term);
  assert.doesNotMatch(html, /data-lazy|원문 읽기/);
  await app.click({aggregate:"functional"});
  assert.equal(aggregatePanelHtml(app, "functional"), execution);
  assert.equal(fixture.calls.length, before, "switching tabs uses already loaded evidence");
});

function operationalCatalog() {
  const data = scoredCatalog();
  for (const record of data.batches[0].assessments) {
    const operations = record.report.summary.operational;
    const base = structuredClone(operations.runs.find(run => run.target === "request"));
    const conditions = [
      {situation:"normal", entry:"initial", environment:"local", data_size:"small", dependencies:"real", elapsed_seconds:0},
      {situation:"fault", entry:"initial", environment:"local", data_size:"small", dependencies:"real", elapsed_seconds:10},
      {situation:"normal", entry:"reentry", environment:"remote", data_size:"large", dependencies:"stub", elapsed_seconds:20},
      {situation:"fault", entry:"reentry", environment:"local", data_size:"large", dependencies:"real", elapsed_seconds:100},
      {unit:"agent", target:"interpretation", situation:"normal", entry:"initial", environment:"local", data_size:"small", dependencies:"real", elapsed_seconds:7},
      {unit:"workflow", target:"report", situation:"normal", entry:"initial", environment:"local", data_size:"small", dependencies:"real", elapsed_seconds:9},
    ];
    operations.runs = conditions.map((condition, index) => ({...structuredClone(base), ...condition,
      run_id:`operational-${index}`, started:true, ended:true, outcome:"completed", input_tokens:0,
      dong_code:index ? "REGION-BETA" : "REGION-ALPHA", month:index ? "2050-02" : "2050-01"}));
    for (const group of operations.groups) {
      group.started = 999;
      for (const statistic of Object.values(group.measurements)) Object.assign(statistic, {mean:999, median:999, p95:999});
    }
  }
  return data;
}

const operationalHtml = app => aggregatePanelHtml(app, "operational");
const decodeAttribute = value => value.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
function selectedOperationalAgent(app) {
  const button = [...operationalHtml(app).matchAll(/<button\b[^>]*data-operational-agent="([^"]+)"[^>]*>/g)].find(match => /aria-selected="true"/.test(match[0]));
  return button && decodeAttribute(button[1]);
}
function selectedOperationalFilters(app) {
  return [...operationalHtml(app).matchAll(/<button\b[^>]*data-operational-filter="([^"]+)"[^>]*>/g)]
    .filter(match => /aria-pressed="true"/.test(match[0])).map(match => match[1]);
}
const filterOperational = (app, key, value) => app.click({operationalFilter:key, conditionValue:JSON.stringify(value), conditionIndex:"0"});
function elapsedStatistics(app) {
  const row = operationalHtml(app).match(/<tr><td>전체 실행 시간<\/td>(.*?)<\/tr>/);
  assert.ok(row, "the selected population has an elapsed-time statistics row");
  return [...row[1].matchAll(/<td>(.*?)<\/td>/g)].map(match => match[1]);
}

test("HTTP startup uses current catalog and sample replacement preserves original local values", async () => {
  const fixture = lazyFixture(samples.files, "execution-evaluation-v1");
  const original = structuredClone(catalog);
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => app.element("#application").attributes["aria-busy"] === "false");
  assert.equal(app.element("#welcome").hidden,true);
  assert.equal(app.element("#sample-notice").hidden,true);
  assert.equal(app.element("#aggregate-page").hidden,false);
  assert.equal(app.element("#notice").hidden,true);
  assert.ok(app.element("#assessment-toolbar").innerHTML.includes(fixture.entry.assessments[0].path));
  app.trigger("#sample-button", "click");
  assert.equal(app.element("#sample-notice").hidden,false);
  assert.equal(app.element("#notice").hidden,true);
  assert.deepEqual(app.loadedCatalog(),original);
});

test("missing or invalid HTTP catalog keeps manual opening and samples available", async () => {
  for (const content of [null, "{}", JSON.stringify({version:"evaluation-viewer-local-v2",generated_at:"now",batches:[],files:[],issues:[]})]) {
    const fixture = lazyFixture(samples.files, "execution-evaluation-v1");
    if (content === null) fixture.texts.delete("eval/outputs/evaluation-viewer/catalog.json");
    else fixture.texts.set("eval/outputs/evaluation-viewer/catalog.json",content);
    const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
    await until(() => /목록 읽기 오류|저장된 실행 묶음이 없습니다/.test(app.element("#notice").textContent));
    assert.equal(app.loadedCatalog(),undefined);
    app.trigger("#sample-button", "click");
    assert.equal(app.loadedCatalog().batches.length,catalog.batches.length);
  }
});

test("saved functional, operational and quality metrics remain in three aggregate tabs", () => {
  const data = scoredCatalog(), app = harness(data), a = data.batches[0].assessments[0].report;
  const markup = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  assert.doesNotMatch(markup, /id="(?:scope|local-status|files-button|folder-button|context|target-count)"/);
  assert.doesNotMatch(markup, /<details[^>]+id="target-picker"/);
  assert.match(markup, /id="folder-input"[^>]*hidden/);
  assert.match(markup, /id="files-input"[^>]*hidden/);
  assert.match(markup, /id="welcome-open"/);
  assert.equal(app.element("#breadcrumb").textContent, "모든 대상");
  assert.doesNotMatch(app.element("#target-nav").innerHTML, /<small\b/);
  app.click({page:"aggregate"});
  const html = app.element("#aggregate-page").innerHTML;
  assert.ok(html.includes(`통과 ${a.summary.functional.cases.numerator} / 분모 ${a.summary.functional.cases.denominator}사례`));
  for (const term of ["보고서 완성률", "기술적 실패율", "종료 결과 분포", "재시도 수", "입력 토큰", "출력 토큰", "실행 비용", "사례별 반복 결과", "미종료 실행의 관측 사용량", "운영 목표 충족 여부", "시험 단가·버전"]) assert.ok(html.includes(term), term);
  assert.doesNotMatch(html, /선택한 모델 호출|노드·역할별|평가 모델 입력/);
  assertAggregateTab(app, "functional");
  const functional = aggregatePanelHtml(app, "functional");
  assert.doesNotMatch(functional, /기능 지표 · 채점 기록 전체|사용자 요청 처리·보고서 전체 흐름의 저장된 집계|통과율 분모는 통과·실패로 판정된 필수 사례/);
  assert.match(functional, /보고서 완성률/);
  assert.match(functional, /<th>통과율<\/th>/);
  assert.doesNotMatch(functional, /<th>통과율 · 분자\/분모<\/th>/);
  assert.doesNotMatch(functional, /조건별 실행 통계|id="score-evidence"|class="aggregate-table"|<summary>채점 결과 전체/);
  const operational = aggregatePanelHtml(app, "operational");
  assert.match(operational, /조건별 실행 통계|운영 목표 충족 여부/);
  assert.doesNotMatch(operational, /기능 지표 · 채점 기록 전체|id="score-evidence"|class="aggregate-table"/);
  assert.doesNotMatch(html, /id="aggregate-panel-(?:evidence|records|criteria)"|aggregate-header|data-score-check=|id="score-evidence"|채점 당시 기준 원문·사례|실행 당시 기준과의 비교/);
});

test("aggregate tab selection survives target, assessment and page changes and supports keyboard navigation", () => {
  const data = scoredCatalog(), original = structuredClone(data), app = harness(data);
  app.click({page:"aggregate"});
  app.click({aggregate:"operational"});
  assertAggregateTab(app, "operational");
  app.click({target:keyFor("interpretation")});
  assertAggregateTab(app, "operational");
  app.change("assessment-select", data.batches[0].assessments[1].path);
  assertAggregateTab(app, "operational");
  app.click({page:"cases"});
  app.click({page:"aggregate"});
  assertAggregateTab(app, "operational");
  for (const [from, key, to] of [
    ["operational", "ArrowRight", "functional"],
    ["functional", "ArrowRight", "quality"],
    ["quality", "Home", "functional"],
    ["functional", "ArrowLeft", "operational"],
    ["operational", "ArrowRight", "functional"],
    ["functional", "End", "operational"],
  ]) {
    const before = app.element(`#aggregate-tab-${to}`).focused;
    assert.equal(app.aggregateKey(from, key), true);
    assertAggregateTab(app, to);
    assert.equal(app.element(`#aggregate-tab-${to}`).focused, before + 1);
  }
  assert.equal(app.aggregateKey("operational", "Tab"), false);
  assertAggregateTab(app, "operational");
  assert.deepEqual(app.loadedCatalog(), original);
  app.trigger("#sample-button", "click");
  app.click({page:"aggregate"});
  assertAggregateTab(app, "functional");
});

test("removed aggregate headers and original-file panels do not alter loaded assessment data", () => {
  const data = scoredCatalog();
  data.batches[0].assessments[0].report.limitations = ['removed-limitations-sentinel <img src=x onerror="bad()">'];
  const original = structuredClone(data), app = harness(data);
  app.click({page:"aggregate"});
  const html = app.element("#aggregate-page").innerHTML;
  assert.doesNotMatch(html, /aggregate-header|<dt>결과 파일<\/dt>|<summary>저장 위치|removed-limitations-sentinel/);
  for (const key of ["functional", "operational", "quality"]) {
    assert.doesNotMatch(aggregatePanelHtml(app, key), /removed-limitations-sentinel/);
  }
  assert.doesNotMatch(html, /<summary>채점 결과 전체|data-aggregate="(?:criteria|records|evidence)"/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("targets select the matching operational agent while saved functional metrics remain unchanged", () => {
  const data = scoredCatalog(), app = harness(data), a = data.batches[0].assessments[0].report;
  assert.match(app.element("#target-nav").innerHTML, /사용자 요청 처리|대시보드 보고서 생성|분석 결과 해석/);
  app.click({target:keyFor("interpretation")});
  assert.equal(app.element("#breadcrumb").textContent, "INTERPRETATION");
  assert.match(app.element("#case-detail").innerHTML, /운영 진단 전용/);
  app.click({page:"aggregate"});
  const html = app.element("#aggregate-page").innerHTML;
  assert.ok(html.includes(`통과 ${a.summary.functional.cases.numerator} / 분모 ${a.summary.functional.cases.denominator}사례`));
  const count = a.summary.operational.runs.filter(run => run.unit === "agent" && run.target === "interpretation").length;
  assert.ok(aggregatePanelHtml(app, "operational").includes(`${count} / ${count}회 선택`));
  assert.doesNotMatch(html, /개별 판정 근거/);
  app.click({page:"cases"});
  assert.match(app.element("#case-detail").innerHTML, /운영 지표/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /이 기록에 실행 판정·측정이 없습니다/);
});

test("operational agent tabs combine regions and periods from individual measurements, ignoring stored groups", () => {
  const data = operationalCatalog(), original = structuredClone(data), app = harness(data);
  app.click({page:"aggregate"}); app.click({aggregate:"operational"});
  const html = operationalHtml(app);
  assert.equal(selectedOperationalAgent(app), keyFor("request"));
  const tabs = [...html.matchAll(/<button\b[^>]*data-operational-agent="([^"]+)"[^>]*>/g)];
  assert.deepEqual(tabs.map(match => decodeAttribute(match[1])), [keyFor("request"), keyFor("interpretation"), keyFor("report")]);
  for (let index = 0; index < tabs.length; index++) {
    assert.match(tabs[index][0], /role="tab"/);
    assert.match(tabs[index][0], /aria-controls="operational-selection"/);
    assert.ok(tabs[index][0].includes(`aria-selected="${index === 0}"`));
    assert.ok(tabs[index][0].includes(`tabindex="${index === 0 ? 0 : -1}"`));
  }
  assert.match(html, /id="operational-selection"[^>]*role="tabpanel"[^>]*aria-labelledby="operational-agent-0"/);
  assert.match(html, /4 \/ 4회 선택/);
  assert.deepEqual(elapsedStatistics(app), ["4", "0", "32.5초", "15초", "100초", "0초", "100초"]);
  assert.equal((html.match(/<fieldset class="operational-filter">/g) || []).length, 5);
  assert.deepEqual([...new Set([...html.matchAll(/data-operational-filter="([^"]+)"/g)].map(match => match[1]))], ExecutionOperational.FILTER_KEYS);
  assert.doesNotMatch(html, /data-operational-filter="(?:dong_code|month)"|조건별 실행 통계/);
  assert.match(html, /대상 지역<\/dt><dd>REGION-ALPHA/);
  assert.match(html, /대상 기간<\/dt><dd>2050-01/);
  assert.match(html, /REGION-BETA|2050-02/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("a planned report with no measurements stays selectable without substituting request statistics", () => {
  const data = operationalCatalog();
  for (const record of data.batches[0].assessments) {
    record.report.summary.operational.runs = record.report.summary.operational.runs.filter(run => run.target !== "report");
  }
  const original = structuredClone(data), app = harness(data);
  app.click({page:"aggregate"}); app.click({aggregate:"operational"});
  assert.match(operationalHtml(app), /4 \/ 4회 선택/);
  for (const selection of [{target:keyFor("report")}, {operationalAgent:keyFor("report")}]) {
    app.click({operationalAgent:keyFor("request")});
    app.click(selection);
    assert.equal(selectedOperationalAgent(app), keyFor("report"));
    assert.match(operationalHtml(app), /0 \/ 0회 선택/);
    assert.deepEqual(elapsedStatistics(app), ["0", "0", "미기록", "미기록", "미기록", "미기록", "미기록"]);
    assert.match(operationalHtml(app), /<dt>대상<\/dt><dd>대시보드 보고서 생성<\/dd>/);
    assert.match(operationalHtml(app), /<dt>지표<\/dt><dd>실행 비용<\/dd>/);
    assert.doesNotMatch(operationalHtml(app), /32\.5초|4 \/ 4회 선택/);
  }
  assert.deepEqual(app.loadedCatalog(), original);
});

test("planned agents and goal-only agents retain tabs and saved goals when no measurements exist", () => {
  for (const goalsOnly of [false, true]) {
    const data = operationalCatalog();
    for (const record of data.batches[0].assessments) {
      record.report.summary.operational.runs = [];
      record.report.summary.operational.unfinished_usage = [];
      if (goalsOnly) record.report.criteria.cases = [];
    }
    if (goalsOnly) data.batches[0].runs = [];
    const original = structuredClone(data), app = harness(data);
    app.click({page:"aggregate"}); app.click({aggregate:"operational"});
    const tabKeys = [...operationalHtml(app).matchAll(/data-operational-agent="([^"]+)"/g)].map(match => decodeAttribute(match[1]));
    assert.ok(tabKeys.includes(keyFor("request")));
    assert.ok(tabKeys.includes(keyFor("report")));
    if (!goalsOnly) assert.ok(tabKeys.includes(keyFor("interpretation")));
    app.click({operationalAgent:keyFor("report")});
    assert.equal(selectedOperationalAgent(app), keyFor("report"));
    assert.match(operationalHtml(app), /0 \/ 0회 선택/);
    assert.deepEqual(elapsedStatistics(app), ["0", "0", "미기록", "미기록", "미기록", "미기록", "미기록"]);
    assert.match(operationalHtml(app), /<dt>대상<\/dt><dd>대시보드 보고서 생성<\/dd>/);
    assert.match(operationalHtml(app), /<dt>지표<\/dt><dd>실행 비용<\/dd>/);
    assert.deepEqual(app.loadedCatalog(), original);
  }
});

test("operational chips implement OR within groups, AND across groups, empty results and clearing", () => {
  const data = operationalCatalog(), original = structuredClone(data), app = harness(data);
  app.click({page:"aggregate"}); app.click({aggregate:"operational"});
  filterOperational(app, "situation", "normal");
  assert.match(operationalHtml(app), /2 \/ 4회 선택/);
  assert.deepEqual(elapsedStatistics(app), ["2", "0", "10초", "10초", "20초", "0초", "20초"]);
  filterOperational(app, "situation", "fault");
  assert.match(operationalHtml(app), /4 \/ 4회 선택/);
  assert.deepEqual(selectedOperationalFilters(app), ["situation", "situation"]);
  filterOperational(app, "entry", "initial");
  filterOperational(app, "environment", "local");
  filterOperational(app, "dependencies", "real");
  assert.match(operationalHtml(app), /2 \/ 4회 선택/);
  assert.deepEqual(elapsedStatistics(app), ["2", "0", "5초", "5초", "10초", "0초", "10초"]);
  filterOperational(app, "data_size", "large");
  assert.match(operationalHtml(app), /0 \/ 4회 선택|선택한 조건에 해당하는 실행이 없습니다/);
  assert.deepEqual(elapsedStatistics(app), ["0", "0", "미기록", "미기록", "미기록", "미기록", "미기록"]);
  assert.doesNotMatch(operationalHtml(app), /NaN|Infinity|undefined/);
  app.click({clearOperational:""});
  assert.match(operationalHtml(app), /4 \/ 4회 선택/);
  assert.deepEqual(selectedOperationalFilters(app), []);
  assert.equal(app.element("#operational-selection").focused, 1);
  assert.match(operationalHtml(app), /id="operational-clear"[^>]*disabled/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("operational agent changes reset conditions and support arrow, Home and End keyboard focus", () => {
  const app = harness(operationalCatalog()); app.click({page:"aggregate"}); app.click({aggregate:"operational"});
  filterOperational(app, "situation", "normal");
  app.click({operationalAgent:keyFor("request")});
  assert.deepEqual(selectedOperationalFilters(app), ["situation"], "reselecting the current agent retains its filter");
  app.click({operationalAgent:keyFor("interpretation")});
  assert.equal(selectedOperationalAgent(app), keyFor("interpretation"));
  assert.deepEqual(selectedOperationalFilters(app), []);
  assert.match(operationalHtml(app), /1 \/ 1회 선택/);
  assert.equal(app.element("#target-title").textContent, "분석 결과 해석");
  for (const [from, key, to, index] of [
    ["interpretation", "ArrowRight", "report", 2], ["report", "ArrowRight", "request", 0],
    ["request", "ArrowLeft", "report", 2], ["report", "Home", "request", 0], ["request", "End", "report", 2],
  ]) {
    filterOperational(app, "situation", "normal");
    const before = app.element(`#operational-agent-${index}`).focused;
    assert.equal(app.operationalKey(keyFor(from), key), true);
    assert.equal(selectedOperationalAgent(app), keyFor(to));
    assert.deepEqual(selectedOperationalFilters(app), []);
    assert.equal(app.element(`#operational-agent-${index}`).focused, before + 1);
    assertAggregateTab(app, "operational");
  }
  assert.equal(app.operationalKey(keyFor("report"), "Tab"), false);
});

test("changing assessment, batch or sample clears operational conditions", () => {
  const data = operationalCatalog();
  const second = structuredClone(data.batches[0]); second.key += "-second"; second.path = "second/" + second.path;
  data.batches.push(second);
  const app = harness(data); app.click({page:"aggregate"}); app.click({aggregate:"operational"});
  filterOperational(app, "situation", "fault");
  app.change("assessment-select", data.batches[0].assessments[1].path);
  assert.deepEqual(selectedOperationalFilters(app), []);
  assert.match(operationalHtml(app), /4 \/ 4회 선택/);
  filterOperational(app, "situation", "fault");
  app.trigger("#batch-select", "change", "1");
  assert.deepEqual(selectedOperationalFilters(app), []);
  assertAggregateTab(app, "functional");
  app.click({aggregate:"operational"}); filterOperational(app, "situation", "fault");
  app.trigger("#sample-button", "click"); app.click({page:"aggregate"});
  assert.deepEqual(selectedOperationalFilters(app), []);
  assertAggregateTab(app, "functional");
});

test("operational selections persist across aggregate tabs and case browsing without changing saved goals", () => {
  const data = operationalCatalog(), app = harness(data);
  app.click({page:"aggregate"}); app.click({aggregate:"operational"});
  filterOperational(app, "situation", "fault");
  const storedGoals = () => operationalHtml(app).slice(operationalHtml(app).indexOf("운영 목표 충족 여부")).replace(/data-download="\d+"/g, 'data-download="index"');
  const before = storedGoals();
  app.click({aggregate:"functional"}); app.click({aggregate:"operational"});
  assert.deepEqual(selectedOperationalFilters(app), ["situation"]);
  app.click({page:"cases"}); app.click({page:"aggregate"});
  assert.deepEqual(selectedOperationalFilters(app), ["situation"]);
  assert.match(operationalHtml(app), /2 \/ 4회 선택/);
  app.click({clearOperational:""});
  assert.equal(storedGoals(), before);
});

test("HTTP operational filters and agent tabs reuse fully loaded evidence without additional requests", async () => {
  const fixture = lazyFixture(samples.files, "execution-evaluation-v1");
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => app.element("#application").attributes["aria-busy"] === "false");
  const before = fixture.calls.length;
  await app.click({aggregate:"operational"});
  const initial = operationalHtml(app);
  const chip = initial.match(/data-operational-filter="([^"]+)" data-condition-value="([^"]+)"/);
  assert.ok(chip);
  await filterOperational(app, chip[1], JSON.parse(decodeAttribute(chip[2])));
  assert.ok(selectedOperationalFilters(app).length);
  const tabs = [...initial.matchAll(/data-operational-agent="([^"]+)"/g)];
  assert.ok(tabs.length > 1);
  await app.click({operationalAgent:decodeAttribute(tabs[1][1])});
  assert.deepEqual(selectedOperationalFilters(app), []);
  await app.click({clearOperational:""});
  assert.equal(fixture.calls.length, before, fixture.calls.join("\n"));
  assert.ok(fixture.calls.includes(fixture.entry.assessments[0].path));
  assert.ok(fixture.calls.some(path => /trace\.jsonl/.test(path)));
});

test("regrading switches check results and functional metrics without overwriting original input or output", () => {
  const data = scoredCatalog(), records = data.batches[0].assessments;
  records.forEach((record, index) => {
    record.report.criteria.cases.find(c => c.id === "request-context").assessment.expected.execution_status = index === 0 ? "completed" : "failed";
    record.report.runs.filter(run => run.case_id === "request-context").forEach(run => {
      run.verdict = index === 0 ? "통과" : "실패";
      run.checks[0].details[0].reason = `regrade-${index}-check-detail`;
    });
  });
  const run = data.batches[0].runs.find(r => r.report.run.case_id === "request-context");
  run.report.state.execution.status = "completed";
  const original = structuredClone(data), app = harness(data);
  app.click({target:keyFor("request")});
  app.click({case:caseKey(run)});
  const before = app.element("#case-detail").innerHTML;
  assert.match(detailPanelHtml(app, "assessment"), /regrade-0-check-detail/);
  assert.match(detailPanelHtml(app, "assessment"), /실행 기능 판정<\/dt><dd><span[^>]*>통과<\/span>/);
  app.click({detail:"io"});
  assertDetailTab(app, "io");
  const io = detailPanelHtml(app, "io");
  app.change("assessment-select", records[1].path);
  const after = app.element("#case-detail").innerHTML;
  assertDetailTab(app, "io");
  assert.notEqual(after, before);
  assert.equal(detailPanelHtml(app, "io"), io);
  assert.match(detailPanelHtml(app, "assessment"), /regrade-1-check-detail/);
  assert.match(detailPanelHtml(app, "assessment"), /실행 기능 판정<\/dt><dd><span[^>]*>실패<\/span>/);
  for (const term of ["검사 항목", "기능 지표", "운영 지표", "입력", "출력"]) assert.ok(after.includes(term), term);
  app.click({page:"aggregate"});
  assert.ok(app.element("#assessment-toolbar").innerHTML.includes(`value="${records[1].path}" selected`));
  app.change("assessment-select", records[0].path);
  assert.ok(app.element("#assessment-toolbar").innerHTML.includes(`value="${records[0].path}" selected`));
  assert.deepEqual(app.loadedCatalog(), original);
});

test("scenario title and diagram come from the selected execution without duplicate description rows", () => {
  const data = scoredCatalog(), calls = [];
  const run = data.batches[0].runs.find(r => r.report.run.case_id === "request-context");
  const app = harness(data, {scenarios: {resolve(selected, batch) {
    calls.push({run: selected, batch});
    return selected.report.run.case_id === "request-context" ? {
      name: '시나리오 <img src=x onerror="bad()">',
      description: '데이터셋 설명 <script>bad()</script>',
      html: '<div class="scenario-diagram">dataset-flow-sentinel</div>',
    } : null;
  }}});
  app.click({target:keyFor("request")});
  app.click({case:caseKey(run)});
  const html = app.element("#case-detail").innerHTML;
  assert.match(html, /<details[^>]*>\s*<summary[^>]*>[\s\S]*?Scenario 시나리오 &lt;img/);
  assert.doesNotMatch(html, /scenario-description|데이터셋 설명/);
  assert.match(app.element("#case-rows").innerHTML, /시나리오 &lt;img/);
  assert.doesNotMatch(app.element("#case-rows").innerHTML, /case-purpose|데이터셋 설명/);
  assert.match(html, /<div class="scenario-diagram">dataset-flow-sentinel<\/div>/);
  assert.doesNotMatch(html, /<img |<script>/);
  app.toggleScenario(true);
  app.click({detail:"operational"});
  assertDetailTab(app, "operational");
  assert.match(app.element("#case-detail").innerHTML, /<details[^>]*id="case-scenario"[^>]* open>/);
  app.toggleScenario(false);
  app.click({detail:"assessment"});
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /<details[^>]*id="case-scenario"[^>]* open>/);
  assert.ok(calls.some(call => call.run.report.run.id === run.report.run.id && call.batch === app.loadedCatalog().batches[0]));
});

test("detail tabs support arrow, Home and End navigation with focus on the selected tab", () => {
  const app = harness(scoredCatalog());
  app.click({target:keyFor("request")});
  assertDetailTab(app, "assessment");
  for (const [from, key, to] of [
    ["assessment", "ArrowRight", "quality"],
    ["quality", "ArrowRight", "operational"],
    ["operational", "ArrowRight", "io"],
    ["io", "ArrowRight", "assessment"],
    ["assessment", "ArrowLeft", "io"],
    ["io", "Home", "assessment"],
    ["assessment", "End", "io"],
  ]) {
    const before = app.element(`#case-tab-${to}`).focused;
    assert.equal(app.key(from, key), true);
    assertDetailTab(app, to);
    assert.equal(app.element(`#case-tab-${to}`).focused, before + 1);
  }
  assert.equal(app.key("io", "Tab"), false);
  assertDetailTab(app, "io");
});

test("individual cases exclude metadata, raw evidence downloads and removed detail panels", () => {
  const data = scoredCatalog();
  const run = data.batches[0].runs.find(r => r.report.run.case_id === "request-context");
  run.case.tags = ["removed-tag-sentinel"];
  run.manifest.viewer_test_metadata = "removed-manifest-sentinel";
  run.report.trace.viewer_test_metadata = "removed-trace-sentinel";
  run.journal = [{type: "removed-journal-sentinel"}];
  const original = structuredClone(data), app = harness(data);
  app.click({target:keyFor("request")});
  app.click({case:caseKey(run)});
  const html = app.element("#case-detail").innerHTML;
  assert.doesNotMatch(html, /data-download=|removed-(?:tag|manifest|trace|journal)-sentinel/);
  assertDetailTab(app, "assessment");
  const functional = detailPanelHtml(app, "assessment");
  assert.match(functional, /<h3>검사 항목<\/h3>/);
  assert.match(functional, /<h3>기능 지표<\/h3>/);
  assert.ok(functional.indexOf('<h3>기능 지표</h3>') < functional.indexOf('<h3>검사 항목</h3>'), "functional metrics precede the check list immediately after the tabs");
  const checkResults = functional.slice(functional.indexOf('<h3>검사 항목</h3>'));
  assert.match(checkResults, /<summary><h4>EX-1 · [^<]+<\/h4><span class="chip/);
  assert.match(checkResults, /class="detail-result"/);
  assert.doesNotMatch(checkResults, /check-location|검사 원본 파일|검사 수행|검증 완료|판정 사유|<dl class="facts">/);
  assert.doesNotMatch(app.element("#assessment-toolbar").innerHTML, /서로 다른 범위의 판정|<p class="hint">/);
  assert.doesNotMatch(functional, /<h3>운영 지표<\/h3>|class="case-value"/);
  const operational = detailPanelHtml(app, "operational");
  assert.match(operational, /<h3>운영 지표<\/h3>/);
  assert.doesNotMatch(operational, /<h3>검사 항목<\/h3>|<h3>기능 지표<\/h3>|class="evidence-list"|class="case-value"|측정값 설명|metric-notes/);
  const io = detailPanelHtml(app, "io");
  assert.match(io, /<summary>입력<\/summary>/);
  assert.match(io, /<summary>전체 출력<\/summary>/);
  const inputStart = io.indexOf('class="case-input"');
  const outputStart = io.indexOf('class="case-output"');
  assert.ok(inputStart >= 0, "input has its own section");
  assert.ok(outputStart > inputStart, "input precedes the original output");
  assert.doesNotMatch(io, /io-comparison|comparison-table|data-comparison-key=|기대결과|기대값|<h3>/);
  assert.match(html, /id="case-tab-io"[^>]*>입출력<\/button>/);
  assert.doesNotMatch(html, /detail-heading|사례 상세<\/span>|입출력 및 기대결과/);
  assert.doesNotMatch(io, /<pre\b|class="raw\b/);
  assert.doesNotMatch(io, /<h3>검사 항목<\/h3>|<h3>기능 지표<\/h3>|<h3>운영 지표<\/h3>|class="evidence-list"/);
  assert.doesNotMatch(html, /사례 태그|실행 ID<|사례 ID<|파일 연결 상태|실행 조건·코드·설정·해시|추적 이벤트 원문|직접 실행·호출 근거|동일 실행의 채점·재평가 기록|사례 준비 자료 전체|실행 결과 전체|독립 기준 자료|허용 범위/);
  const options = html.match(/<select id="run-select"[^>]*>([\s\S]*?)<\/select>/);
  assert.ok(options, "the execution selector remains available");
  const labels = [...options[1].matchAll(/<option[^>]*>([^<]*)<\/option>/g)].map(match => match[1]);
  assert.deepEqual(labels, ["1회차", "2회차"]);
  assert.match(options[0], /aria-label="실행 회차"/);
  assert.doesNotMatch(html, /<label>실행 건/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("selecting a repetition switches its actual input, output and operational values", () => {
  const data = scoredCatalog(), batch = data.batches[0];
  const runs = batch.runs.filter(r => r.report.run.case_id === "request-context").sort((a, b) => a.report.run.repetition - b.report.run.repetition);
  runs.forEach((run, index) => {
    run.case.initial = {request: `repetition-${index + 1}-input`};
    run.report.state.response = {...run.report.state.response, kind: index === 0 ? "final" : "question", content: `repetition-${index + 1}-output`};
    batch.assessments[0].report.summary.operational.runs.find(m => m.run_id === run.report.run.id).input_tokens = 23456 + index;
  });
  batch.assessments[0].report.criteria.cases.find(c => c.id === "request-context").assessment.expected.response_kind = "final";
  const original = structuredClone(data), app = harness(data);
  app.click({target:keyFor("request")});
  app.click({case:caseKey(runs[0])});
  app.click({detail:"io"});
  assertDetailTab(app, "io");
  let html = app.element("#case-detail").innerHTML;
  for (const term of ["repetition-1-input", "repetition-1-output", "23456"]) assert.ok(html.includes(term), term);
  assert.doesNotMatch(html, /repetition-2-(?:input|output)|23457/);
  assert.match(detailPanelHtml(app, "io"), />final</);
  app.change("run-select", runs[1].key);
  assertDetailTab(app, "io");
  html = app.element("#case-detail").innerHTML;
  for (const term of ["repetition-2-input", "repetition-2-output", "23457"]) assert.ok(html.includes(term), term);
  assert.doesNotMatch(html, /repetition-1-(?:input|output)|23456/);
  assert.match(detailPanelHtml(app, "io"), />question</);
  assert.doesNotMatch(detailPanelHtml(app, "io"), /comparison-table|data-comparison/);
  app.click({detail:"operational"});
  assertDetailTab(app, "operational");
  app.click({detail:"assessment"});
  assertDetailTab(app, "assessment");
  html = app.element("#case-detail").innerHTML;
  assert.match(html, /<option[^>]* selected>2회차<\/option>/);
  for (const term of ["repetition-2-input", "repetition-2-output", "23457"]) assert.ok(html.includes(term), term);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("sidebar cases remain available in aggregate and repetition selection opens the corresponding input/output", () => {
  const data = scoredCatalog(), app = harness(data);
  const run = data.batches[0].runs.find(r => r.report.run.case_id === "request-context" && r.report.run.repetition === 2);
  app.click({page:"aggregate"});
  app.trigger("#case-search", "input", "request-context");
  assert.match(app.element("#case-rows").innerHTML, /request-context/);
  assert.doesNotMatch(app.element("#case-rows").innerHTML, /request-exhausted/);
  app.click({case:caseKey(run)});
  assert.equal(app.element("#case-page").hidden, false);
  assert.equal(app.element("#aggregate-page").hidden, true);
  assert.ok(app.element("#case-detail").innerHTML.includes(`<h2>Scenario ${run.case.purpose}</h2>`));
  app.change("run-select", run.key);
  app.click({detail:"io"});
  assert.equal(app.element("#case-page").hidden, false);
  assert.equal(app.element("#aggregate-page").hidden, true);
  assertDetailTab(app, "io");
  assert.match(app.element("#case-detail").innerHTML, /<option[^>]* selected>2회차<\/option>/);
  assert.ok(app.element("#case-detail").innerHTML.includes(`<h2>Scenario ${run.case.purpose}</h2>`));
});

test("case result text and original input/output are escaped without truncating values", () => {
  const data = scoredCatalog(), batch = data.batches[0];
  const run = batch.runs.find(r => r.report.run.case_id === "request-context");
  const dangerous = '<img src=x onerror="bad()">';
  run.case.initial = {request: dangerous};
  run.report.state.response = {...run.report.state.response, kind: dangerous, content: dangerous + "x".repeat(25000) + "output-tail-sentinel"};
  const scored = batch.assessments[0].report.runs.find(r => r.run_id === run.report.run.id);
  scored.checks[0].details[0].reason = dangerous;
  batch.assessments[0].report.criteria.cases.find(c => c.id === "request-context").assessment.expected.response_kind = dangerous;
  const app = harness(data);
  app.click({target:keyFor("request")});
  app.click({case:caseKey(run)});
  const html = app.element("#case-detail").innerHTML;
  assert.ok((html.match(/&lt;img/g) || []).length >= 4, "detail reason, input, response kind and output content are escaped");
  assert.match(detailPanelHtml(app, "assessment"), /&lt;img/);
  assert.match(detailPanelHtml(app, "io"), /&lt;img/);
  assert.match(html, /output-tail-sentinel/);
  assert.doesNotMatch(html, /<img |data-download=/);
});

test("individual functional verdicts retain incomplete failures and operational zero differs from missing", () => {
  const data = scoredCatalog(), batch = data.batches[0];
  const run = batch.runs.find(r => r.report.run.case_id === "request-context");
  const a = batch.assessments[0].report;
  Object.assign(a.runs.find(r => r.run_id === run.report.run.id), {verdict: "실패", complete: false});
  Object.assign(a.summary.operational.runs.find(r => r.run_id === run.report.run.id), {
    elapsed_seconds: 0, model_calls: 0, input_tokens: 0, output_tokens: null, cost: null,
  });
  const app = harness(data);
  app.click({target:keyFor("request")});
  app.click({case:caseKey(run)});
  const html = app.element("#case-detail").innerHTML;
  assert.match(html, /실행 기능 판정<\/dt><dd><span[^>]*>실패<\/span>/);
  assert.match(html, /기능 검증 완료<\/dt><dd>미완료<\/dd>/);
  assert.match(html, /전체 실행 시간<\/dt><dd>0초<\/dd>/);
  assert.match(html, /입력 토큰<\/dt><dd>0<\/dd>/);
  assert.match(html, /출력 토큰<\/dt><dd>미기록<\/dd>/);
  assert.match(html, /실행 비용<\/dt><dd>산출 불가<\/dd>/);
  assert.doesNotMatch(html, /NaN|Infinity|undefined|통과율/);
});

test("saved scenario titles remain visible when the diagram is unavailable, with ID as a last fallback", () => {
  const data = unscoredCatalog();
  const runs = data.batches[0].runs.filter(r => r.report.run.case_id === "request-context");
  runs.forEach(run => { run.case.purpose = "사용자 요청 처리 · 이전 대화 없음"; });
  const titled = harness(data);
  titled.click({target:keyFor("request")});
  titled.click({case:caseKey(runs[0])});
  assert.match(titled.element("#case-detail").innerHTML, /<summary><h2>Scenario 사용자 요청 처리 · 이전 대화 없음<\/h2><\/summary>/);
  assert.match(titled.element("#case-rows").innerHTML, /<span class="case-id">사용자 요청 처리 · 이전 대화 없음<\/span>/);
  assert.doesNotMatch(titled.element("#case-detail").innerHTML, /scenario-description/);
  assert.doesNotMatch(titled.element("#case-rows").innerHTML, /case-purpose/);
  assert.equal(titled.element("#breadcrumb").textContent, "REQUEST");
  titled.trigger("#case-search", "input", "request-context");
  assert.match(titled.element("#case-rows").innerHTML, /사용자 요청 처리 · 이전 대화 없음/);
  assert.deepEqual(titled.loadedCatalog(), data, "display changes preserve the saved records");
  runs.forEach(run => { delete run.case.purpose; });
  const app = harness(data);
  app.click({target:keyFor("request")});
  app.click({case:caseKey(runs[0])});
  const html = app.element("#case-detail").innerHTML;
  assert.match(html, /<summary><h2>Scenario request-context<\/h2><\/summary>/);
  assert.match(html, /시나리오 도식 미제공/);
  assert.doesNotMatch(html, /class="scenario-description"|설명 미제공/);
  app.click({detail:"operational"});
  assertDetailTab(app, "operational");
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /class="scenario-description"|설명 미제공/);
});

test("null rates with a positive denominator, zero measurements and incomplete failure stay distinct", () => {
  const data = scoredCatalog(), a = data.batches[0].assessments[0].report;
  Object.assign(a.summary.functional.cases, {numerator:0, denominator:0, rate:null});
  Object.assign(a.summary.functional, {verdict:"실패", complete:false});
  a.summary.operational.runs = a.summary.operational.runs.filter(run => run.target === "request").slice(0, 2);
  a.summary.operational.runs.forEach((run, index) => Object.assign(run, {started:true, ended:true, outcome:index ? "unclassified" : "technical_failure", input_tokens:0}));
  const app = harness(data); app.click({page:"aggregate"});
  const html = app.element("#aggregate-page").innerHTML;
  assert.match(aggregatePanelHtml(app, "operational"), /기술적 실패율<\/span><strong>산출 불가<\/strong><span>1 \/ 2회/);
  assert.match(html, /통과 0 \/ 분모 0사례/);
  assert.match(html, /기능 합격 여부<\/span><strong><span[^>]*>실패<\/span>/);
  assert.match(html, /미완료/);
  assert.doesNotMatch(html, /실패가 확인된 사례에도 미완료 반복/);
  assert.match(html, /입력 토큰<\/td><td>2<\/td><td>0<\/td><td>0<\/td><td>0/);
  assert.doesNotMatch(html, /NaN|Infinity|undefined/);
});

test("saved check counts remain visible without links to removed evidence tabs", () => {
  const data = scoredCatalog(), a = data.batches[0].assessments[0].report;
  const original = structuredClone(data);
  const app = harness(data); app.click({page:"aggregate"});
  const html = aggregatePanelHtml(app, "functional");
  assertAggregateTab(app, "functional");
  for (const check of a.summary.functional.checks) {
    const row = html.match(new RegExp(`<tr><td>${check.check}<br>([\\s\\S]*?)</tr>`));
    assert.ok(row, check.check);
    const cells = [...row[1].matchAll(/<td>(.*?)<\/td>/g)].map(match => match[1]);
    assert.deepEqual(cells.slice(-5), [check.passed, check.failed, check.undetermined, check.not_applicable, check.unexecuted].map(String));
  }
  assert.doesNotMatch(html, /data-score-check|건수를 누르면|개별 판정 근거/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("assessment-only files preserve target navigation and saved metrics while the case list stays empty", () => {
  const files = samples.files.filter(f => f.path.includes("/assessments/"));
  const data = ExecutionEvaluationData.parseFiles(files), app = harness(data);
  assert.equal(app.element("#aggregate-page").hidden, false);
  assert.match(app.element("#target-nav").innerHTML, /분석 결과 해석/);
  assert.match(app.element("#aggregate-page").innerHTML, /필수 사례 통과율/);
  assert.match(app.element("#case-rows").innerHTML, /표시할 사례가 없습니다/);
  assert.doesNotMatch(app.element("#aggregate-page").innerHTML, /data-open-run=/);
  app.click({target:keyFor("report")});
  assert.match(app.element("#aggregate-page").innerHTML, /보고서 완성률/);
});

test("not-applicable and unexecuted saved counts remain separate", () => {
  const data = scoredCatalog(), a = data.batches[0].assessments[0].report;
  const stat = a.summary.functional.checks.find(c => c.check === "EX-4");
  assert.ok(stat.not_applicable > 0);
  const app = harness(data); app.click({page:"aggregate"});
  const html = aggregatePanelHtml(app, "functional");
  const row = html.match(/<tr><td>EX-4<br>([\s\S]*?)<\/tr>/);
  assert.ok(row);
  const cells = [...row[1].matchAll(/<td>(.*?)<\/td>/g)].map(match => match[1]);
  assert.deepEqual(cells.slice(-2), [String(stat.not_applicable), String(stat.unexecuted)]);
});

test("operational goals show spread measure, outcome, conditions and time units", () => {
  const app = harness(); app.click({page:"aggregate"});
  const html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /통계 \/ 편차 측정 대상<\/dt><dd>모델 호출 수/);
  assert.match(html, /종료 구분<\/dt><dd>정상 반환/);
  assert.match(html, /초 \/ 10초/);
  assert.match(html, /환경 \/ 입력 규모/);
});

test("unscored cases retain original input and output with no fabricated metrics", () => {
  const data = unscoredCatalog(), app = harness(data);
  const run = data.batches[0].runs.find(r => r.report.run.case_id === "request-context");
  app.click({target:keyFor("request")});
  app.click({case:caseKey(run)});
  const html = app.element("#case-detail").innerHTML;
  for (const term of ["검사 항목", "기능 지표", "운영 지표", "입력", "출력"]) assert.ok(html.includes(term), term);
  assert.doesNotMatch(html, /기대결과|io-comparison/);
  assert.deepEqual(app.loadedCatalog(), data);
  assert.match(html, /미제공/);
  assertDetailTab(app, "assessment");
  assert.doesNotMatch(html, /data-download=|동일 실행의 채점·재평가 기록|직접 실행·호출 근거|파일 연결 상태|실행 조건·코드·설정·해시|NaN|Infinity|undefined/);
  app.click({page:"aggregate"});
  assert.match(app.element("#aggregate-page").innerHTML, /실행 채점 결과 미제공/);
  assertAggregateTab(app, "functional");
  assert.match(aggregatePanelHtml(app, "functional"), /미제공/);
  app.click({aggregate:"operational"});
  assertAggregateTab(app, "operational");
  assert.match(aggregatePanelHtml(app, "operational"), /미제공/);
  assert.doesNotMatch(app.element("#aggregate-page").innerHTML, /data-aggregate="(?:records|evidence|criteria)"/);
});

test("unavailable original output remains distinct from removed expectation guidance", () => {
  const data = scoredCatalog(), batch = data.batches[0];
  const run = batch.runs.find(r => r.report.run.case_id === "request-context");
  const criteria = batch.assessments[0].report.criteria.cases.find(c => c.id === "request-context");
  const {schema_version, situation, entry, environment, data_size} = criteria.assessment.expected;
  criteria.assessment.expected = {schema_version, situation, entry, environment, data_size};
  run.report.state = null;
  const original = structuredClone(data), app = harness(data);
  app.click({target:keyFor("request")});
  app.click({case:caseKey(run)});
  app.click({detail:"io"});
  const io = detailPanelHtml(app, "io");
  assert.match(io, /<summary>전체 출력<\/summary>/);
  assert.match(io, />null</);
  assert.doesNotMatch(io, /항목별 기대값이 지정되어|기대결과|기대값|io-comparison|<h3>/);
  assert.deepEqual(app.loadedCatalog(), original);
});

test("invalid file selection preserves the current view and is escaped", async () => {
  const app = harness(), before = app.loadedCatalog();
  await app.files([{name:"invalid.json", text:async () => "{"}]);
  assert.equal(app.loadedCatalog(), before);
  assert.match(app.element("#notice").textContent, /기존 화면은 유지됩니다/);
  assert.equal(app.element("#notice").hidden, false);
  await app.files([{name:'<img src=x onerror="bad()">.json', text:async () => {throw new Error("unreadable");}}]);
  assert.match(app.element("#load-issues").innerHTML, /&lt;img/);
  assert.doesNotMatch(app.element("#load-issues").innerHTML, /<img /);
  assert.equal(app.element("#welcome-open").disabled, false);
  assert.equal(app.element("#sample-button").disabled, false);
});

test("mobile sidebar/detail focus preserves query, filters, tab, repetition and original state", () => {
  const data = scoredCatalog(), original = structuredClone(data), app = harness(data, {width:390});
  assert.match(app.element("#target-nav").innerHTML, /사용자 요청 처리/);
  assert.equal(app.element("#case-list-picker").open, false);
  assert.equal(app.element("#assessment-controls").open, false);
  const run = data.batches[0].runs.find(r => r.report.run.case_id === "request-context");
  app.click({target:keyFor("request")});
  app.trigger("#case-search", "input", "request-context");
  app.trigger("#status-filter", "change", "returned");
  app.trigger("#required-filter", "change", "yes");
  const detailFocusBefore = app.element("#case-detail").focused;
  app.click({case:caseKey(run)});
  assert.equal(app.element("#case-detail").focused, detailFocusBefore + 1);
  assert.equal(app.element("#case-page").hidden, false);
  const repeated = data.batches[0].runs.find(r => r.report.run.case_id === "request-context" && r.report.run.repetition === 2);
  app.change("run-select", repeated.key);
  app.click({detail:"io"});
  assertDetailTab(app, "io");
  assert.match(app.element("#case-detail").innerHTML, /<option[^>]* selected>2회차<\/option>/);
  const before = app.element("#case-detail").innerHTML;
  const listFocusBefore = app.element("#case-list").focused;
  app.click({backToList:""});
  assert.equal(app.element("#case-list-picker").open, true);
  assert.equal(app.element("#case-list").focused, listFocusBefore + 1);
  assert.equal(app.element("#case-page").hidden, false);
  assert.equal(app.element("#case-detail").innerHTML, before);
  assertDetailTab(app, "io");
  assert.equal(app.element("#case-search").value, "request-context");
  assert.equal(app.element("#required-filter").value, "yes");
  assert.deepEqual(app.loadedCatalog(), original);
});

test("status filters safely exclude individual groups and all cases", () => {
  const data = scoredCatalog(), runs = data.batches[0].runs;
  const contextRuns = runs.filter(r => r.report.run.case_id === "request-context");
  contextRuns.forEach(run => { run.report.run.status = "error"; });
  const app = harness(data);
  app.click({target:keyFor("request")});
  assert.doesNotThrow(() => app.trigger("#status-filter", "change", "returned"));
  assert.doesNotMatch(app.element("#case-rows").innerHTML, /request-context/);
  assert.doesNotThrow(() => app.trigger("#status-filter", "change", "error"));
  assert.match(app.element("#case-rows").innerHTML, /request-context/);
  assert.doesNotThrow(() => app.trigger("#status-filter", "change", "cancelled"));
  assert.match(app.element("#case-rows").innerHTML, /표시할 사례가 없습니다/);
  assert.match(app.element("#case-detail").innerHTML, /사례를 선택하세요/);
});



test("assessment selectors use compact grading numbers while retaining distinct record paths", () => {
  const data = scoredCatalog(), batch = data.batches[0];
  batch.report.id = "실행평가_2026-11-12_실행07";
  batch.report.started_at = "2026-11-12T08:00:00Z";
  batch.assessments.forEach((record, index) => {
    record.report.batch_id = batch.report.id;
    record.report.id = `${batch.report.id}_채점${String(8 - index).padStart(2, "0")}`;
    record.report.assessed_at = "2026-11-12T08:59:01.322553+00:00";
    record.path = `saved/${batch.report.id}/assessments/${record.report.id}.json`;
  });
  const original = structuredClone(data), app = harness(data);
  app.click({page: "aggregate"});
  const html = app.element("#aggregate-page").innerHTML;
  assert.match(app.element("#batch-select").innerHTML, /실행평가 · 2026-11-12 실행07/);
  assert.doesNotMatch(html, /aggregate-header|평가 이름|채점 일시|<summary>채점 결과 전체/);
  app.click({page: "cases"});
  const selector = app.element("#assessment-toolbar").innerHTML.match(/<select id="assessment-select"[^>]*>([\s\S]*?)<\/select>/);
  assert.ok(selector);
  assert.deepEqual([...selector[1].matchAll(/<option[^>]*>([^<]*)<\/option>/g)].map(match => match[1]), ["채점 08", "채점 07"]);
  assert.doesNotMatch(selector[1].replace(/value="[^"]*"/g, ""), /실행평가|한국시간|2026년/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /동일 실행의 채점·재평가 기록|data-download=/);
  app.change("assessment-select", batch.assessments[1].path);
  app.click({page: "aggregate"});
  assert.ok(app.element("#assessment-toolbar").innerHTML.includes(`value="${batch.assessments[1].path}" selected`));
  assert.deepEqual(app.loadedCatalog(), original);
});

test("HTTP partial failures preserve loaded cases, checks and saved aggregate verdicts", async () => {
  const fixture = lazyFixture(samples.files, "execution-evaluation-v1");
  const batch = JSON.parse(fixture.texts.get(fixture.entry.path)), folder = fixture.entry.path.replace(/[^/]+$/, "");
  const firstPath = folder + batch.runs[0].path, secondPath = folder + batch.runs[1].path;
  fixture.texts.delete(secondPath);
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => app.element("#application").attributes["aria-busy"] === "false");
  assert.match(app.element("#notice").textContent, /일부 파일의 읽기 오류/);
  assert.match(app.element("#aggregate-page").innerHTML, /필수 사례 통과율/);
  const before = fixture.calls.length;
  await app.click({openRun:firstPath});
  assert.match(detailPanelHtml(app, "io"), /<summary>입력<\/summary>|<summary>전체 출력<\/summary>/);
  await app.click({openRun:secondPath});
  assert.match(detailPanelHtml(app, "io"), /확인할 수 없|확인 불가|미제공/);
  await app.click({page:"aggregate"}); await app.click({aggregate:"functional"});
  assert.match(app.element("#aggregate-page").innerHTML, /필수 사례 통과율/);
  assert.doesNotMatch(app.element("#aggregate-page").innerHTML, /data-lazy/);
  assert.equal(fixture.calls.length, before);
});

test("manual selection rejects oversized source files before reading contents", async () => {
  const app = harness(); let reads = 0;
  const before = app.element("#case-detail").innerHTML;
  await app.files([{name:"too-large.json",size:65*1048576,text:async()=>{ reads++; return "{}"; }}]);
  assert.equal(reads,0);
  assert.match(app.element("#notice").textContent, /64 MB/);
  assert.equal(app.element("#case-detail").innerHTML,before);
});

test("sample replacement cancels an in-progress automatic batch and ignores its late result", async () => {
  const fixture = lazyFixture(samples.files, "execution-evaluation-v1"), create = fixture.lazy.create;
  let release, firstReady = false;
  const gate = new Promise(resolve => { release = resolve; });
  fixture.lazy.create = options => {
    const client = create(options); let first = true;
    return {...client, run: async (...args) => {
      const delay = first; first = false; const value = await client.run(...args);
      if (delay) { firstReady = true; await gate; } return value;
    }};
  };
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => firstReady);
  await app.trigger("#sample-button", "click");
  const selected = app.element("#case-detail").innerHTML;
  release(); await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(app.element("#case-detail").innerHTML, selected);
  assert.equal(app.element("#sample-notice").hidden, false);
  assert.deepEqual(app.loadedCatalog(), catalog);
});

test("legacy results load automatically and invalid manual replacement retains loaded HTTP navigation", async () => {
  const fixture = lazyFixture(samples.files, "execution-evaluation-v1");
  const legacy = samples.files.flatMap(file => { try { return [JSON.parse(file.text)]; } catch { return []; } }).find(value => value.schema_version === "execution-evaluation-v1" && value.id === fixture.manifest.id);
  const legacyPath = fixture.entry.path.replace(/[^/]+$/, "assessments/legacy.json"), source = structuredClone(legacy);
  source.runs[0].checks[0].details[0].reason = "legacy-visible-check-sentinel";
  fixture.entry.assessments.push({path:legacyPath, format:"legacy"});
  fixture.texts.set(legacyPath, JSON.stringify(source));
  fixture.texts.set("eval/outputs/evaluation-viewer/catalog.json", JSON.stringify(fixture.index));
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => app.element("#application").attributes["aria-busy"] === "false");
  assert.ok(fixture.calls.includes(legacyPath));
  assert.doesNotMatch(app.element("#notice").textContent, /오류/);
  const before = fixture.calls.length;
  await app.files([{name:"invalid.json",size:2,text:async()=>"{}"}]);
  assert.match(app.element("#notice").textContent,/기존 화면은 유지/);
  await app.change("assessment-select",legacyPath);
  const runEntry = JSON.parse(fixture.texts.get(fixture.entry.path)).runs.find(run => run.run_id === source.runs[0].run_id);
  assert.ok(runEntry);
  await app.click({openRun:fixture.entry.path.replace(/[^/]+$/, runEntry.path)});
  await app.click({detail:"assessment"});
  assert.match(detailPanelHtml(app, "assessment"), /legacy-visible-check-sentinel/);
  assert.doesNotMatch(detailPanelHtml(app, "assessment"), /아직 읽지 않은 검사|data-lazy/);
  assert.equal(fixture.calls.length, before);
});
