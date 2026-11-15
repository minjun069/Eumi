"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const EvaluationNames = require("../shared/record-names.js");
const EvaluationData = require("./data.js");
const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
require("./samples.js");
const samples = globalThis.EvaluationSamples;
const {copyFiles} = require("../shared/assessment-fixtures.cjs");
const catalog = EvaluationData.parseFiles(samples.files);
const {fixture: lazyFixture, until} = require("../shared/lazy-ui-fixtures.cjs");


// Exercise the actual UI event handlers and rendered content without replacing
// their navigation logic. Browser layout and file-picker checks are separate.
function harness(initial = catalog, {width = 1440, autoOnly = false, lazy} = {}) {
  const elements = new Map();
  const documentListeners = new Map();
  const downloaded = [];
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
    createElement: () => ({click() { downloaded.push({name: this.download, url: this.href}); }}),
    querySelector: element,
    querySelectorAll: selector => selector === ".page-tabs [data-page]" ? pageTabs : [],
    addEventListener: (type, listener) => documentListeners.set(type, listener),
  };
  let initialRead = !autoOnly;
  let loadedCatalog;
  vm.runInNewContext(source, {
    document, URL, Blob, setTimeout, EvaluationNames,
    EvaluationLazy: lazy, location: {href: "http://localhost/eval/viewers/results/"},
    matchMedia: query => ({matches: width <= Number(query.match(/max-width:\s*(\d+)px/)[1]), addEventListener() {}}),
    EvaluationSamples: samples,
    EvaluationData: {
      parseFiles(files) {
        const result = initialRead ? structuredClone(initial) : EvaluationData.parseFiles(files);
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
    async files(files) {
    element("#files-input").files = files;
    return trigger("#files-input", "change");
  } };
}

test("HTTP startup uses current catalog and sample replacement preserves original local values", async () => {
  const fixture = lazyFixture(samples.files, "tool-evaluation-v1");
  const original = structuredClone(catalog);
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => /선택한 채점 집계를 읽었습니다/.test(app.element("#notice").textContent));
  assert.equal(app.element("#welcome").hidden,true);
  assert.equal(app.element("#sample-notice").hidden,true);
  assert.equal(app.element("#aggregate-page").hidden,false);
  assert.match(app.element("#local-status").textContent,/작은 목록/);
  assert.ok(app.element("#aggregate-page").innerHTML.includes(fixture.entry.assessments[0].path));
  app.trigger("#sample-button", "click");
  assert.equal(app.element("#sample-notice").hidden,false);
  assert.equal(app.element("#local-status").hidden,true);
  assert.deepEqual(app.loadedCatalog(),original);
});

test("missing or invalid HTTP catalog keeps manual opening and samples available", async () => {
  for (const content of [null, "{}", JSON.stringify({version:"evaluation-viewer-local-v2",generated_at:"now",batches:[],files:[],issues:[]})]) {
    const fixture = lazyFixture(samples.files, "tool-evaluation-v1");
    if (content === null) fixture.texts.delete("eval/outputs/evaluation-viewer/catalog.json");
    else fixture.texts.set("eval/outputs/evaluation-viewer/catalog.json",content);
    const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
    await until(() => /목록 읽기 오류|저장된 실행 묶음이 없습니다/.test(app.element("#notice").textContent));
    assert.equal(app.loadedCatalog(),undefined);
    app.trigger("#sample-button", "click");
    assert.equal(app.loadedCatalog().batches.length,catalog.batches.length);
  }
});

function repeatedCase() {
  const batch = structuredClone(catalog.batches.find(item => item.runs.length === 2));
  batch.runs[1].report.run.status = "error";
  batch.runs[1].report.failure = { type: "ToolFailure", code: "sample_error" };
  batch.runs[1].entry.status = "error";
  return { batches: [batch], issues: [] };
}

function scoredCatalog() {
  return {batches: [structuredClone(catalog.batches.find(b => b.assessments?.length))], issues: []};
}


test("saved tool grades, distinct latency statistics and selected re-evaluations reach every view", () => {
  const data = scoredCatalog(), before = structuredClone(data), app = harness(data);
  assert.match(app.element("#case-detail").innerHTML, /선택한 채점 기록의 검사·판정/);
  assert.match(app.element("#case-detail").innerHTML, /반환 건수가 기대와 다릅니다/);
  app.click({page: "aggregate"});
  let html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /50%/);
  assert.match(html, /통과 1 \/ 분모 2사례/);
  assert.match(html, /0.012초/);
  assert.match(html, /0.007초/);
  assert.match(html, /운영 목표 충족 여부/);
  assert.match(html, /가상 로컬 환경/);
  assert.match(html, /2행/);
  app.change("assessment-select", data.batches[0].assessments[1].path);
  html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /통과 0 \/ 분모 2사례/);
  app.click({page: "cases"});
  app.change("run-select", data.batches[0].runs[1].key);
  app.click({detail: "history"});
  assert.match(app.element("#case-detail").innerHTML, /도구평가_2026-11-09_실행01_채점01/);
  assert.match(app.element("#case-detail").innerHTML, /도구평가_2026-11-09_실행01_채점02/);
  app.click({assessmentKey: data.batches[0].assessments[0].path});
  app.click({page: "aggregate"});
  assert.match(app.element("#aggregate-page").innerHTML, /통과 1 \/ 분모 2사례/);
  assert.deepEqual(app.loadedCatalog(), before);
});

test("check counts deduplicate identical verdicts and drill down to escaped original evidence", () => {
  const data = scoredCatalog(), a = data.batches[0].assessments[0].report;
  a.runs[0].checks.push(structuredClone(a.runs[0].checks[1]));
  a.runs[0].checks[1].reason = '<img src=x onerror="bad()">';
  const app = harness(data);
  app.click({page: "aggregate"});
  assert.match(app.element("#aggregate-page").innerHTML, /개별 판정 근거 · 5건/);
  app.click({scoreCheck: JSON.stringify(["query_data", "T-O.1", "실패"])});
  const html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /개별 판정 근거 · 1건/);
  assert.match(html, /&lt;img src=x onerror=&quot;bad\(\)&quot;&gt;/);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /기대값/);
  assert.match(html, /실제값/);
  assert.match(html, /허용 오차/);
  assert.match(html, /실행 입출력 확인/);
  assert.equal(app.element("#score-evidence").focused, 1);
  app.click({scoreCheck: JSON.stringify(["query_data", "T-O.1", "비적용"])});
  assert.match(app.element("#aggregate-page").innerHTML, /개별 판정 근거 · 0건/);
});

test("score-only files retain missing executions, zero denominator, and missing operational goals", () => {
  const file = samples.files.find(f => f.path.endsWith("도구평가_2026-11-09_실행01_채점02.json"));
  const data = EvaluationData.parseFiles([file]);
  const a = data.batches[0].assessments[0].report;
  Object.assign(a.tools[0].functional, {numerator: 0, denominator: 0, rate: null, verdict: "미판정"});
  a.tools[0].latency.normal = {sample_count: 0, median_seconds: null, p95_seconds: null};
  a.tools[0].performance = [];
  a.runs[0].run_id = null;
  const app = harness(data);
  assert.equal(app.element("#aggregate-page").hidden, false);
  const html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /통과 0 \/ 분모 0사례/);
  assert.doesNotMatch(html, /0%|NaN|Infinity/);
  assert.match(html, /운영 목표 미제공/);
  assert.match(html, /계획된 실행 · 실행 ID 없음/);
  assert.match(html, /실행 원본 미제공/);
  assert.match(app.element("#target-nav").innerHTML, /T01/);
  app.click({target: JSON.stringify(["tool", "query_data", null, "real"])});
  assert.match(app.element("#aggregate-page").innerHTML, /필수 사례 통과율/);
});

test("tool selection scopes check counts and metrics without applying case-list filters", () => {
  const data = scoredCatalog(), a = data.batches[0].assessments[0].report;
  const second = structuredClone(a.tools[0]);
  second.target = "process_data";
  second.functional.numerator = 0; second.functional.rate = 0;
  a.tools.push(second);
  a.runs.push({...structuredClone(a.runs[0]), target: "process_data", run_id: "other-tool-run"});
  const app = harness(data);
  app.click({target: JSON.stringify(["tool", "query_data", null, "real"])});
  app.trigger("#case-search", "input", "no-matching-case");
  app.click({page: "aggregate"});
  let html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /통과 1 \/ 분모 2사례/);
  assert.match(html, /개별 판정 근거 · 5건/);
  app.click({target: JSON.stringify(["tool", "process_data", null, "real"])});
  html = app.element("#aggregate-page").innerHTML;
  assert.match(html, /T02 · 데이터 가공/);
  assert.match(html, /통과 0 \/ 분모 2사례/);
  assert.match(html, /개별 판정 근거 · 4건/);
  assert.match(html, /실행 원본 미제공/);
});

function hundredCases() {
  const data = repeatedCase();
  const batch = data.batches[0];
  const source = batch.runs[0];
  batch.runs = Array.from({ length: 100 }, (_, index) => {
    const run = structuredClone(source);
    run.key = `batch/runs/run-${index}/report.json`;
    run.path = run.key;
    run.report.run.id = `run-${index}`;
    run.report.run.case_id = `case-${index}`;
    run.report.state.execution.run_id = `run-${index}`;
    run.entry.run_id = `run-${index}`;
    run.entry.case_id = `case-${index}`;
    run.case.id = `case-${index}`;
    run.case.purpose = `페이지 탐색 사례 ${index}`;
    return run;
  });
  batch.report.planned_runs = 100;
  batch.report.runs = batch.runs.map(run => run.entry);
  return data;
}

test("100-case pagination and a matching search keep detail on the visible page", () => {
  const app = harness(hundredCases());
  for (let index = 0; index < 3; index++) app.click({ pageStep: "1" });
  assert.match(app.element("#pagination").innerHTML, /4 \/ 4쪽/);
  assert.match(app.element("#case-detail").innerHTML, /사례 case-75/);
  app.trigger("#case-search", "input", "페이지 탐색 사례");
  assert.match(app.element("#pagination").innerHTML, /1 \/ 4쪽/);
  assert.match(app.element("#case-rows").innerHTML, /class="selected"/);
  assert.match(app.element("#case-detail").innerHTML, /사례 case-0/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /사례 case-75/);
});

test("history can select a returned repetition while the list has an error filter", () => {
  const data = repeatedCase();
  const app = harness(data);
  app.trigger("#status-filter", "change", "error");
  app.click({ detail: "history" });
  assert.match(app.element("#case-detail").innerHTML, /2회차 · 선택/);
  app.click({ runKey: data.batches[0].runs[0].key });
  assert.equal(app.element("#status-filter").value, "all");
  assert.match(app.element("#case-detail").innerHTML, /1회차 · 선택/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /2회차 · 선택/);
});

test("recorded execution values never become grades or calculated metric statistics", () => {
  const app = harness(repeatedCase());
  const detail = app.element("#case-detail").innerHTML;
  assert.match(detail, /사례별 평가 지표 미제공/);
  assert.match(detail, /채점 수행<\/dt><dd>미실행/);
  assert.match(detail, /미판정/);
  assert.match(detail, /실행 관측 시간/);
  app.click({ page: "aggregate" });
  const aggregate = app.element("#aggregate-page").innerHTML;
  assert.match(aggregate, /지표 집계·통계 미제공/);
  assert.match(aggregate, /이 화면에서 계산하지 않습니다/);
  assert.doesNotMatch(aggregate, /\d+(?:\.\d+)?%/);
});

test("search filters case navigation while leaving the selected aggregate scope unchanged", () => {
  const app = harness(hundredCases());
  app.click({ page: "aggregate" });
  const aggregate = app.element("#aggregate-page").innerHTML;
  app.click({ page: "cases" });
  app.trigger("#case-search", "input", "일치하지 않는 검색어");
  assert.match(app.element("#case-rows").innerHTML, /표시할 사례가 없습니다/);
  app.click({ page: "aggregate" });
  assert.equal(app.element("#aggregate-page").innerHTML, aggregate);
});

test("a malformed newly selected report keeps the loaded results and explains the failure", async () => {
  const app = harness(repeatedCase());
  const rows = app.element("#case-rows").innerHTML;
  const detail = app.element("#case-detail").innerHTML;
  await app.files([{ name: "report.json", text: async () => "{broken" }]);
  assert.equal(app.element("#case-rows").innerHTML, rows);
  assert.equal(app.element("#case-detail").innerHTML, detail);
  assert.match(app.element("#notice").textContent, /기존 화면은 유지됩니다/);
  assert.match(app.element("#load-issues").innerHTML, /report.json/);
  assert.equal(app.element("#files-input").value, "");
  assert.equal(app.element("#files-button").disabled, false);
});

test("loaded evidence text is escaped in the list, input view, and file issue message", async () => {
  const data = repeatedCase();
  const injection = '<img src=x onerror="alert(1)">';
  for (const run of data.batches[0].runs) {
    run.case.purpose = injection;
    run.report.output = { goto: injection };
  }
  const app = harness(data);
  assert.doesNotMatch(app.element("#case-rows").innerHTML, /<img /);
  assert.match(app.element("#case-rows").innerHTML, /&lt;img /);
  app.click({ detail: "io" });
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /<img /);
  assert.match(app.element("#case-detail").innerHTML, /&lt;img /);
  await app.files([{ name: injection + ".json", text: async () => { throw new Error("unreadable"); } }]);
  assert.doesNotMatch(app.element("#load-issues").innerHTML, /<img /);
  assert.match(app.element("#load-issues").innerHTML, /&lt;img /);
});

test("mobile list/detail roundtrip preserves filters, page and selected repetition", () => {
  const data = hundredCases();
  for (const run of data.batches[0].runs) {
    run.case.tags = ["mobile-fixture"];
    run.case.assessment.required = true;
  }
  const selected = data.batches[0].runs[77];
  const repetition = structuredClone(selected);
  repetition.key = "mobile/run-77-repeat/report.json";
  repetition.path = repetition.key;
  repetition.report.run.id = "run-77-repeat";
  repetition.report.run.repetition = 2;
  repetition.report.state.execution.run_id = "run-77-repeat";
  repetition.entry.run_id = "run-77-repeat";
  repetition.entry.repetition = 2;
  data.batches[0].runs.push(repetition);
  const original = structuredClone(data);
  const app = harness(data, {width: 390});
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), false);
  assert.equal(app.element("#target-picker").open, false);
  assert.equal(app.element("#case-filters").open, false);
  app.trigger("#case-search", "input", "페이지 탐색 사례");
  app.trigger("#status-filter", "change", "returned");
  app.trigger("#tag-filter", "change", "mobile-fixture");
  app.trigger("#required-filter", "change", "yes");
  for (let index = 0; index < 3; index++) app.click({pageStep: "1"});
  app.click({case: JSON.stringify([selected.report.run.case_id, selected.report.run.unit, selected.report.run.target])});
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), true);
  assert.equal(app.element("#case-detail").focused, 1);
  assert.equal(app.element("#case-detail").scrolled, 1);
  app.change("run-select", repetition.key);
  app.click({detail: "history"});
  assert.match(app.element("#case-detail").innerHTML, /사례 case-77/);
  assert.match(app.element("#case-detail").innerHTML, /2회차 · 선택/);
  const before = Object.fromEntries(["#case-rows", "#case-detail", "#pagination"].map(id => [id, app.element(id).innerHTML]));
  app.click({backToList: ""});
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), false);
  assert.equal(app.element("#case-list").focused, 1);
  assert.equal(app.element("#case-list").scrolled, 1);
  for (const [id, markup] of Object.entries(before)) assert.equal(app.element(id).innerHTML, markup);
  for (const [id, value] of [["case-search", "페이지 탐색 사례"], ["status-filter", "returned"], ["tag-filter", "mobile-fixture"], ["required-filter", "yes"]]) {
    assert.equal(app.element("#" + id).value, value);
  }
  assert.match(app.element("#pagination").innerHTML, /4 \/ 4쪽/);
  assert.deepEqual(app.loadedCatalog(), original, "pane changes do not mutate loaded evidence");
});

test("mobile aggregate navigation opens a run and scope/new-file changes reset the detail pane", async () => {
  const data = hundredCases();
  const second = structuredClone(repeatedCase().batches[0]);
  data.batches.push(second);
  const app = harness(data, {width: 760});
  app.trigger("#case-search", "input", "일치하지 않는 검색어");
  app.click({page: "aggregate"});
  const selected = data.batches[0].runs[75];
  app.click({openRun: selected.key});
  assert.equal(app.element("#case-page").hidden, false);
  assert.equal(app.element("#aggregate-page").hidden, true);
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), true);
  assert.equal(app.element("#case-detail").focused, 1);
  assert.match(app.element("#case-detail").innerHTML, /사례 case-75/);
  assert.match(app.element("#case-detail").innerHTML, /data-detail="io" aria-pressed="true"/);
  assert.match(app.element("#pagination").innerHTML, /4 \/ 4쪽/);
  assert.equal(app.element("#case-search").value, "");
  assert.equal(app.element("#status-filter").value, "all");

  app.element("#target-picker").open = true;
  app.click({target: "all"});
  assert.equal(app.element("#target-picker").open, false);
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), false);
  assert.match(app.element("#pagination").innerHTML, /1 \/ 4쪽/);
  app.click({case: JSON.stringify(["case-0", selected.report.run.unit, selected.report.run.target])});
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), true);
  app.trigger("#batch-select", "change", "1");
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), false);
  assert.match(app.element("#pagination").innerHTML, /1 \/ 1쪽/);
  const run = second.runs[0];
  app.click({case: JSON.stringify([run.report.run.case_id, run.report.run.unit, run.report.run.target])});
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), true);
  await app.files([{name: "report.json", text: async () => JSON.stringify(run.report)}]);
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), false);
  assert.equal(app.element("#sample-notice").hidden, true);
  assert.match(app.element("#pagination").innerHTML, /1 \/ 1사례/);
  assert.equal(app.element("#files-button").disabled, false);
});

test("failed mobile file replacement preserves the active detail pane and navigation state", async () => {
  const data = repeatedCase();
  const app = harness(data, {width: 390});
  app.trigger("#status-filter", "change", "error");
  const run = data.batches[0].runs[1];
  app.click({case: JSON.stringify([run.report.run.case_id, run.report.run.unit, run.report.run.target])});
  app.click({detail: "io"});
  const before = Object.fromEntries(["#case-rows", "#case-detail", "#pagination"].map(id => [id, app.element(id).innerHTML]));
  await app.files([{name: "report.json", text: async () => "{broken"}]);
  assert.equal(app.element("#case-browser").classList.contains("detail-open"), true);
  assert.equal(app.element("#status-filter").value, "error");
  for (const [id, markup] of Object.entries(before)) assert.equal(app.element(id).innerHTML, markup);
  assert.match(app.element("#notice").textContent, /기존 화면은 유지됩니다/);
  assert.equal(app.element("#sample-notice").hidden, false);
  assert.equal(app.element("#files-input").value, "");
  assert.equal(app.element("#files-button").disabled, false);
});

test("report workflow and individual report roles have distinct navigation and State output", () => {
  const app = harness();
  const workflow = catalog.batches[0].runs.find(run => run.report.run.unit === "workflow");
  assert.ok(workflow);
  app.click({target: JSON.stringify(["workflow", "report", null, "real"])});
  assert.match(app.element("#target-nav").innerHTML, /생성 흐름/);
  assert.match(app.element("#target-title").textContent, /대시보드 보고서 생성/);
  assert.match(app.element("#case-detail").innerHTML, /선정 → 설명 → 인사이트/);
  app.click({detail: "io"});
  assert.match(app.element("#case-detail").innerHTML, /공개 응답/);
  assert.match(app.element("#case-detail").innerHTML, /업무 결과·작업 이력/);
  assert.doesNotMatch(app.element("#case-detail").innerHTML, /도구 직접 반환값/);

  for (const [role, label] of [
    ["report_selection", "보고서 시각화 선정"],
    ["report_description", "보고서 시각화 설명"],
    ["report_insight", "보고서 퀵 인사이트"],
  ]) {
    const data = structuredClone(catalog);
    data.batches = [data.batches[0]];
    const run = structuredClone(workflow);
    Object.assign(run.report.run, {unit: "agent", target: role, role});
    Object.assign(run.case, {unit: "agent", target: role});
    Object.assign(run.entry, {unit: "agent", target: role});
    data.batches[0].runs = [run];
    const roleApp = harness(data);
    roleApp.click({target: JSON.stringify(["agent", role, role, "real"])});
    assert.equal(roleApp.element("#target-title").textContent, label);
    assert.match(roleApp.element("#case-detail").innerHTML, /한 역할의 공통 실행 흐름과 산출물/);
    roleApp.click({detail: "io"});
    assert.match(roleApp.element("#case-detail").innerHTML, /업무 결과·작업 이력/);
  }
});


test("readable evaluation names, Korean times and downloads stay consistent across selection and history", () => {
  const data = scoredCatalog(), batch = data.batches[0];
  batch.report.id = "도구평가_2026-11-12_실행07";
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
  assert.match(app.element("#batch-select").innerHTML, /도구평가 · 2026-11-12 실행07/);
  assert.ok(html.includes("도구평가 · 2026-11-12 실행07 · 채점08"));
  assert.ok(html.includes("2026년 11월 12일 17:59:01 (한국시간)"));
  assert.ok(html.includes(`<dt>결과 파일</dt><dd>${record.report.id}.json</dd>`));
  assert.ok(html.includes(`<summary>저장 위치</summary><code>${record.path}</code>`));
  assert.doesNotMatch(html, /<dt>평가 ID<|<dt>채점 시각<|<dt>실행 묶음 ID</);
  const download = html.match(/<summary>채점 결과 전체<\/summary>\s*<div class="raw-tools"><button type="button" data-download="(\d+)"/);
  assert.ok(download, "the original full assessment has a download action");
  app.click({download: download[1]});
  assert.equal(app.downloaded[0].name, `${record.report.id}.json`);
  app.click({page: "cases"});
  app.click({detail: "history"});
  assert.ok(app.element("#case-detail").innerHTML.includes("도구평가 · 2026-11-12 실행07 · 채점08"));
  app.change("assessment-select", batch.assessments[1].path);
  app.click({page: "aggregate"});
  assert.ok(app.element("#aggregate-page").innerHTML.includes("도구평가 · 2026-11-12 실행07 · 채점07"));
  assert.deepEqual(app.loadedCatalog(), original);
});

test("HTTP case selection reads one repetition only and separates unread and missing results", async () => {
  const fixture = lazyFixture(samples.files, "tool-evaluation-v1");
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => /선택한 채점 집계를 읽었습니다/.test(app.element("#notice").textContent));
  const batch = JSON.parse(fixture.texts.get(fixture.entry.path));
  const directory = fixture.entry.path.replace(/[^/]+$/, "");
  const first = batch.runs[0], firstPath = directory + first.path;
  const second = batch.runs.find(entry => entry.run_id !== first.run_id), secondPath = directory + second.path;

  assert.match(app.element("#aggregate-page").innerHTML, /미로딩 \d+건 · 읽기 오류·누락 0건/);
  await app.click({openRun:firstPath});
  await until(() => /data-detail=/.test(app.element("#case-detail").innerHTML));
  assert.deepEqual(fixture.calls.slice(3).sort(), [firstPath,firstPath.replace(/[^/]+$/, "case.json")].sort());
  assert.ok(!fixture.calls.some(path => /trace\.jsonl|judge-trace|criteria\.json/.test(path)));
  fixture.texts.delete(secondPath);
  await app.click({openRun:secondPath});
  await until(() => /data-detail=/.test(app.element("#case-detail").innerHTML));
  assert.match(app.element("#case-detail").innerHTML, /확인할 수 없|확인 불가|미제공/);
  await app.click({page:"aggregate"});
});

test("manual selection rejects oversized source files before reading contents", async () => {
  const app = harness(); let reads = 0;
  const before = app.element("#case-detail").innerHTML;
  await app.files([{name:"too-large.json",size:65*1048576,text:async()=>{ reads++; return "{}"; }}]);
  assert.equal(reads,0);
  assert.match(app.element("#notice").textContent, /64 MB/);
  assert.equal(app.element("#case-detail").innerHTML,before);
});

test("a slower previous repetition cannot replace the current selection", async () => {
  const fixture = lazyFixture(samples.files, "tool-evaluation-v1");
  const create = fixture.lazy.create;
  let release, firstReady = false;
  const gate = new Promise(resolve => { release = resolve; });
  fixture.lazy.create = options => {
    const client = create(options), load = client.run;
    let first = true;
    const run = async (...args) => {
      const delay = first; first = false;
      const value = await load(...args);
      if (delay) { firstReady = true; await gate; }
      return value;
    };
    return {...client,run};
  };
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => /선택한 채점 집계를 읽었습니다/.test(app.element("#notice").textContent));
  const batch = JSON.parse(fixture.texts.get(fixture.entry.path));
  const directory = fixture.entry.path.replace(/[^/]+$/, "");
  const firstPath = directory + batch.runs[0].path, secondPath = directory + batch.runs[1].path;
  await app.click({openRun:firstPath});
  await until(() => firstReady);
  await app.click({openRun:secondPath});
  await until(() => /data-detail=/.test(app.element("#case-detail").innerHTML));
  const selected = app.element("#case-detail").innerHTML;
  assert.ok(selected.includes('value="' + secondPath + '" selected'));
  release(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.element("#case-detail").innerHTML, selected);
});

test("explicit legacy loading restores actual checks and invalid manual replacement keeps HTTP navigation", async () => {
  const fixture = lazyFixture(samples.files, "tool-evaluation-v1");
  const legacy = samples.files.flatMap(file => { try { return [JSON.parse(file.text)]; } catch { return []; } }).find(value => value.schema_version === "tool-evaluation-v1" && value.id === fixture.manifest.id);
  assert.ok(legacy);
  const legacyPath = fixture.entry.assessments.at(-1).path;
  const source = structuredClone(legacy);
  source.runs[0].checks[0].reason = "legacy-visible-check-sentinel";
  fixture.texts.set(legacyPath,JSON.stringify(source));
  const app = harness(catalog, {lazy:fixture.lazy,autoOnly:true});
  await until(() => /선택한 채점 집계를 읽었습니다/.test(app.element("#notice").textContent));
  await app.files([{name:"invalid.json",size:2,text:async()=>"{}"}]);
  assert.match(app.element("#notice").textContent,/기존 화면은 유지/);
  await app.change("assessment-select",legacyPath);
  assert.ok(!fixture.calls.includes(legacyPath));
  await app.click({lazyAssessment:""});
  assert.doesNotMatch(app.element("#notice").textContent,/오류/);
  assert.ok(fixture.calls.includes(legacyPath));
  assert.match(app.element("#aggregate-page").innerHTML,/legacy-visible-check-sentinel/);
  assert.doesNotMatch(app.element("#aggregate-page").innerHTML,/아직 읽지 않은 검사/);
});
