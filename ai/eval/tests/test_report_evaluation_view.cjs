/* 실행: node --test eval/tests/test_report_evaluation_view.cjs
 * 실제 DOM 구성 함수를 실행한다. 브라우저의 레이아웃·키보드 동작 검증은 포함하지 않는다. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// 외부 DOM 패키지 없이 생성된 요소와 이벤트를 관찰하는 테스트 경계다.
class TestNode {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName?.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.childNodes = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.hidden = false;
    this.dataset = {};
    this.style = {};
    this.className = "";
    this._text = "";
    this.classList = {
      contains: (name) => this.className.split(/\s+/).includes(name),
      add: (...names) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(" "); },
      remove: (...names) => { this.className = this.className.split(/\s+/).filter((name) => !names.includes(name)).join(" "); },
      toggle: (name, force) => {
        const add = force === undefined ? !this.classList.contains(name) : force;
        this.classList[add ? "add" : "remove"](name);
        return add;
      },
    };
  }
  get children() { return this.childNodes.filter((node) => node.tagName); }
  get textContent() { return this._text + this.childNodes.map((node) => node.textContent).join(""); }
  set textContent(value) { this._text = String(value ?? ""); this.childNodes = []; }
  set innerHTML(value) {
    throw new Error("평가 DOM은 HTML 문자열을 삽입하지 않아야 합니다: " + value);
  }
  append(...nodes) {
    for (let node of nodes) {
      if (!(node instanceof TestNode)) {
        const text = new TestNode(undefined, this.ownerDocument);
        text.textContent = node;
        node = text;
      }
      if (node.parentNode) node.remove();
      node.parentNode = this;
      this.childNodes.push(node);
    }
  }
  replaceChildren(...nodes) {
    for (const node of this.childNodes) node.parentNode = undefined;
    this.childNodes = [];
    this._text = "";
    this.append(...nodes);
  }
  remove() {
    if (this.parentNode) this.parentNode.childNodes = this.parentNode.childNodes.filter((node) => node !== this);
    this.parentNode = undefined;
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "class") this.className = String(value);
    if (name === "id") this.id = String(value);
  }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }
  dispatchEvent(event) {
    event.target ??= this;
    event.currentTarget = this;
    event.preventDefault ??= () => {};
    for (const listener of this.listeners.get(event.type) || []) listener(event);
    return true;
  }
  click() { if (!this.disabled) this.dispatchEvent({ type: "click" }); }
  focus() { this.ownerDocument.activeElement = this; }
}

function descendants(root) {
  return root.childNodes.flatMap((node) => [node, ...descendants(node)]);
}

function harness() {
  const document = { createElement: (tag) => new TestNode(tag, document) };
  const panel = document.createElement("section");
  document.getElementById = (id) => [panel, ...descendants(panel)].find((node) => node.id === id) || null;
  const context = vm.createContext({ document, Node: TestNode, console, setTimeout, clearTimeout });
  for (const file of ["data.js", "components.js", "evaluation-catalog.js", "evaluation.js", "evaluation-view.js"]) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, file.startsWith("evaluation") ? "../viewers/report" : "../../report_viewer", file), "utf8"), context, { filename: file });
  }
  return { context, panel, E: context.ReportEvaluation, view: context.ReportEvaluationView };
}

function nodes(root, predicate) { return descendants(root).filter(predicate); }
function byClass(root, name) { return nodes(root, (node) => node.classList.contains(name)); }
function button(root, label) {
  const found = nodes(root, (node) => node.tagName === "BUTTON" && node.textContent === label);
  assert.equal(found.length, 1, `버튼을 하나 찾을 수 있어야 합니다: ${label}`);
  return found[0];
}

function report(event = "analysis_pipeline", runId = "run-one") {
  return { state: { execution: { run_id: runId, event }, results: [] } };
}

function evaluation(units, extra = {}) {
  return {
    type: "evaluation", schema_version: 1, id: "view-test", title: "실행별 평가",
    sample: false, run_ids: ["run-one"], units, ...extra,
  };
}

function unit(extra = {}) {
  return {
    id: "report-one", kind: "report", target: "가동 11월 보고서",
    metrics: [
      { name: "출력 정확도", numerator: 1, denominator: 2, verdict: "실패", criterion: "필수 출력 검사 모두 통과" },
      { name: "입력 정확도", numerator: 1, denominator: 1, verdict: "통과" },
    ],
    checks: [
      check("case-pass", "통과", { input: { area: "가동" }, expected: "예상 수치 10", actual: "관측 수치 10", reason: "원자료와 일치", evidence: "trace.json#/pass" }),
      check("case-fail", "실패", { expected: "예상 수치 10", actual: "관측 수치 20", reason: "원자료와 불일치", cause: "분모 선택 오류", evidence: "trace.json#/fail" }),
      check("case-unjudged", "미판정", { reason: "기준 자료 미확정", actual: "관측 수치 15" }),
      check("case-unexecuted", "미판정", { executed: false, reason: "검사 미실행" }),
      check("case-input", "통과", { metrics: ["입력 정확도"], check_id: "R01-I.1", actual: "11월 가동 입력" }),
    ],
    ...extra,
  };
}

function check(caseId, verdict, extra = {}) {
  return {
    case_id: caseId, check_id: "A-O.4", target: "첫 번째 설명 수치",
    executed: true, verdict, metrics: ["출력 정확도"], ...extra,
  };
}

function render(units, options = {}) {
  const testView = harness();
  const value = testView.E.normalize(evaluation(units, options.evaluation));
  testView.view.render(testView.panel, value, options.report ?? report(), "evaluation.json");
  return { ...testView, value };
}

function control(root, key, value) {
  const found = nodes(root, (node) => node.tagName === "BUTTON" && node.dataset[key] === value);
  assert.equal(found.length, 1, `${key}=${value} 선택 버튼이 하나 있어야 합니다.`);
  return found[0];
}

function cases(root) { return byClass(root, "evaluation-case-button").map((node) => node.dataset.caseId); }
function detail(root) {
  const found = byClass(root, "evaluation-case-detail");
  assert.equal(found.length, 1);
  return found[0];
}

test("선택 실행의 트리거에 맞는 평가 단위와 대상별 지표만 표시한다", () => {
  const units = [
    unit(),
    unit({ id: "user", kind: "user-request", target: "질문별 사용자 요청" }),
    unit({ id: "n01", kind: "nodes", target_id: "N01", target: "작업 목적 파악", metrics: [], checks: [] }),
    unit({ id: "n04", kind: "nodes", target_id: "N04", target: "응답 작성", metrics: [], checks: [] }),
    unit({ id: "t03", kind: "tools", target_id: "T03", target: "표시 설정 도구", metrics: [], checks: [] }),
  ];
  const { panel } = render(units);
  assert.deepEqual(nodes(panel, (node) => node.dataset.kind).map((node) => node.dataset.kind), ["report", "nodes", "tools"]);
  control(panel, "kind", "nodes").click();
  assert.ok(panel.textContent.includes("응답 작성"));
  assert.equal(nodes(panel, (node) => node.tagName === "OPTION").length, 0, "제외된 목적 파악 노드는 선택 목록에 넣지 않는다.");
  assert.equal(nodes(panel, (node) => node.dataset.metric === "분기 정확도").length, 0);
  control(panel, "kind", "tools").click();
  assert.equal(nodes(panel, (node) => node.dataset.metric === "행동 준수율").length, 0, "저장 전용 지표를 표시 설정 도구에 붙이지 않는다.");
  const user = render(units, { report: report("user_request") });
  assert.deepEqual(nodes(user.panel, (node) => node.dataset.kind).map((node) => node.dataset.kind), ["user-request", "nodes", "tools"]);
  control(user.panel, "kind", "nodes").click();
  assert.deepEqual(nodes(user.panel, (node) => node.tagName === "OPTION").map((node) => node.textContent), ["작업 목적 파악", "응답 작성"]);
});

test("같은 파일의 다른 실행과 분리할 수 없는 집계가 현재 실행의 대상 선택에 섞이지 않는다", () => {
  const { panel } = render([
    unit({ run_ids: ["run-one"] }),
    unit({ id: "other-run", target: "다른 실행의 보고서", run_ids: ["run-two"] }),
    unit({ id: "mixed-runs", target: "여러 실행을 합친 보고서" }),
    unit({ id: "other-tool", target: "다른 실행의 도구", kind: "tools", target_id: "T03", run_ids: ["run-two"], metrics: [], checks: [] }),
  ], { evaluation: { run_ids: ["run-one", "run-two"] } });
  assert.equal(control(panel, "kind", "report").textContent, "세부 대시보드 보고서 · 1개 대상 · 횟수 미기록");
  assert.equal(nodes(panel, (node) => node.dataset.kind === "tools").length, 0);
  assert.equal(nodes(panel, (node) => node.tagName === "OPTION").length, 0);
  assert.equal(byClass(panel, "evaluation-unit-head")[0].textContent.includes("가동 11월 보고서"), true);
  assert.equal(panel.textContent.includes("다른 실행의 보고서"), false);
  assert.equal(panel.textContent.includes("여러 실행을 합친 보고서"), false);
  assert.ok(panel.textContent.includes("표시 범위 확인 · 3개 대상"));
});

test("지표 선택 후 성공·실패 사례를 바꾸면 입력·기대·실제 결과와 근거가 함께 바뀐다", () => {
  const { panel } = render([unit()]);
  assert.equal(control(panel, "metric", "출력 정확도").getAttribute("aria-pressed"), "true");
  assert.equal(control(panel, "caseId", "case-fail").getAttribute("aria-pressed"), "true");
  for (const value of ["예상 수치 10", "관측 수치 20", "원자료와 불일치", "분모 선택 오류", "trace.json#/fail"])
    assert.ok(detail(panel).textContent.includes(value), value);
  control(panel, "caseFilter", "통과").click();
  assert.deepEqual(cases(panel), ["case-pass"]);
  assert.equal(control(panel, "caseFilter", "통과").getAttribute("aria-pressed"), "true");
  for (const value of ["가동", "예상 수치 10", "관측 수치 10", "원자료와 일치", "trace.json#/pass"])
    assert.ok(detail(panel).textContent.includes(value), value);
  assert.equal(detail(panel).textContent.includes("분모 선택 오류"), false);
  control(panel, "caseFilter", "실패").click();
  assert.deepEqual(cases(panel), ["case-fail"]);
  assert.ok(detail(panel).textContent.includes("관측 수치 20"));
});

test("미판정과 미실행 사례를 통과·실패에서 구분하고 이전 사례의 상세를 지운다", () => {
  const { panel } = render([unit()]);
  control(panel, "caseFilter", "미판정").click();
  assert.deepEqual(cases(panel), ["case-unjudged"]);
  assert.ok(detail(panel).textContent.includes("기준 자료 미확정"));
  control(panel, "caseFilter", "미실행").click();
  assert.deepEqual(cases(panel), ["case-unexecuted"]);
  assert.ok(detail(panel).textContent.includes("검사 미실행"));
  assert.ok(detail(panel).textContent.includes("미기록"));
  assert.equal(detail(panel).textContent.includes("관측 수치 15"), false);
  control(panel, "caseFilter", "전체").click();
  assert.deepEqual(cases(panel), ["case-pass", "case-fail", "case-unjudged", "case-unexecuted"]);
});

test("다른 지표를 선택하면 연결된 사례만 보이고 집계만 있는 지표에 사례를 만들어 넣지 않는다", () => {
  const source = unit();
  source.metrics.push({ name: "보고서 완성률", numerator: 1, denominator: 1, verdict: "통과" });
  const { panel } = render([source]);
  control(panel, "metric", "입력 정확도").click();
  assert.deepEqual(cases(panel), ["case-input"]);
  assert.ok(detail(panel).textContent.includes("11월 가동 입력"));
  assert.equal(control(panel, "metric", "출력 정확도").getAttribute("aria-pressed"), "false");
  control(panel, "metric", "보고서 완성률").click();
  assert.deepEqual(cases(panel), []);
  assert.ok(panel.textContent.includes("이 지표에 연결된 사례 기록이 없습니다."));
  assert.ok(panel.textContent.includes("집계값만으로 성공·실패 사례를 추정하지 않습니다."));
  assert.equal(byClass(panel, "evaluation-case-detail").length, 0);
  control(panel, "group", "operational").click();
  assert.deepEqual(cases(panel), []);
  assert.ok(panel.textContent.includes("미기록"));
});

test("대상 전환 시 이전 대상의 선택 사례와 필터를 남기지 않는다", () => {
  const second = unit({ id: "report-two", target: "나동 11월 보고서", checks: [check("second-failure", "실패", { actual: "나동 오류 기록" })] });
  const { panel } = render([unit(), second]);
  control(panel, "caseFilter", "통과").click();
  assert.deepEqual(cases(panel), ["case-pass"]);
  const picker = nodes(panel, (node) => node.tagName === "SELECT" && node.getAttribute("aria-label") === "평가 대상 선택")[0];
  picker.value = "report-two";
  picker.dispatchEvent({ type: "change" });
  assert.deepEqual(cases(panel), ["second-failure"]);
  assert.equal(control(panel, "caseFilter", "전체").getAttribute("aria-pressed"), "true");
  assert.ok(detail(panel).textContent.includes("나동 오류 기록"));
  assert.equal(detail(panel).textContent.includes("trace.json#/pass"), false);
  control(panel, "caseFilter", "통과").click();
  assert.deepEqual(cases(panel), []);
  assert.equal(detail(panel).textContent, "");
  assert.ok(panel.textContent.includes("통과 사례가 없습니다."));
});

test("같은 사례의 여러 검사는 한 사례로 묶고 실패 검사와 통과 검사를 모두 열람한다", () => {
  const source = unit({ checks: [
    check("mixed-case", "통과", { check_id: "A-O.4", actual: "수치 검사 통과" }),
    check("mixed-case", "실패", { check_id: "A-O.6", actual: "범위 검사 실패" }),
  ] });
  const { panel } = render([source]);
  assert.deepEqual(cases(panel), ["mixed-case"]);
  assert.equal(control(panel, "caseFilter", "실패").textContent, "실패 1");
  assert.equal(control(panel, "caseFilter", "통과").textContent, "통과 0");
  assert.ok(detail(panel).textContent.includes("수치 검사 통과"));
  const disclosures = nodes(detail(panel), (node) => node.tagName === "DETAILS");
  const failed = disclosures.find((node) => node.children[0]?.textContent.includes("A-O.6"));
  assert.ok(failed);
  failed.open = true;
  failed.dispatchEvent({ type: "toggle" });
  assert.ok(detail(panel).textContent.includes("범위 검사 실패"));
  assert.ok(detail(panel).textContent.includes("수치 검사 통과"));
  assert.ok(panel.textContent.includes("사례 수는 지표의 분모와 다를 수 있습니다."));
});

test("판정 기준과 사례 화면을 오가며 파일의 집계·기준을 원본 그대로 확인한다", () => {
  const source = unit();
  const before = JSON.stringify(source);
  const { panel } = render([source]);
  button(panel, "집계·판정 기준").click();
  assert.ok(panel.textContent.includes("필수 출력 검사 모두 통과"));
  assert.ok(panel.textContent.includes("판정한 출력 항목 수"));
  assert.equal(byClass(panel, "evaluation-case-detail").length, 0);
  button(panel, "사례 확인").click();
  assert.deepEqual(cases(panel), ["case-pass", "case-fail", "case-unjudged", "case-unexecuted"]);
  assert.equal(JSON.stringify(source), before);
});

test("외부 파일의 HTML 모양 문자열은 요소나 실행 코드가 아닌 텍스트로 표시한다", () => {
  const hostile = '<img src=x onerror="globalThis.injected=true"><script>throw 1</script>';
  const source = unit({ target: hostile, checks: [check(hostile, "실패", { expected: hostile, actual: hostile, evidence: hostile, reason: hostile })] });
  const { panel, context } = render([source], { evaluation: { title: hostile } });
  assert.ok(detail(panel).textContent.includes(hostile));
  assert.equal(control(panel, "caseId", hostile).dataset.caseId, hostile);
  assert.equal(nodes(panel, (node) => ["IMG", "SCRIPT"].includes(node.tagName)).length, 0);
  assert.equal(context.injected, undefined);
});

function execution(values = {}) {
  return {
    id: "node-span-one", name: "act", caller: "api.report", run_id: "run-one",
    status: "success", elapsed_seconds: 0,
    evidence: "outputs/report.json#/trace/spans/1", ...values,
  };
}

test("실제 호출 기록이 없는 예전 파일은 사례 수와 무관하게 횟수 미기록으로 표시한다", () => {
  const { panel } = render([unit()]);
  assert.equal(control(panel, "kind", "report").textContent, "세부 대시보드 보고서 · 1개 대상 · 횟수 미기록");
  assert.ok(byClass(panel, "evaluation-unit-head")[0].textContent.includes("실행 횟수 미기록"));
  assert.equal(byClass(panel, "evaluation-unit-head")[0].textContent.includes("실행 기록 · 0회"), false);
  assert.ok(panel.textContent.includes("사례 수는 지표의 분모와 다를 수 있습니다."));
});

test("실행 기록과 사례 상세에서 실제 성공·시간을 예시 평가 실패와 구분해 확인한다", () => {
  const source = unit({
    id: "act-node", kind: "nodes", target_id: "N02", target: "N02 작업 선택 및 실행",
    executions: [execution(), execution({ id: "node-span-two", caller: "visualization_agent", run_id: "child-run", elapsed_seconds: 1.25 })],
    metrics: [{ name: "노드 출력 정확도", numerator: 7, denominator: 11, verdict: "실패" }],
    checks: [
      check("first-case", "실패", { execution_id: "node-span-one", metrics: ["노드 출력 정확도"], actual: { actual_output: "원본 성공 결과" } }),
      check("second-case", "통과", { execution_id: "node-span-two", metrics: ["노드 출력 정확도"], actual: { actual_output: "하위 호출 원본" } }),
    ],
  });
  const { panel } = render([source]);
  control(panel, "kind", "nodes").click();
  assert.equal(control(panel, "kind", "nodes").textContent, "노드 · 1종 · 2회");
  const executionDetail = nodes(detail(panel), (node) => node.tagName === "DETAILS" && node.children[0]?.textContent.startsWith("실제 실행 정보"))[0];
  assert.ok(executionDetail, "실제 실행 메타데이터는 별도로 펼쳐 확인한다.");
  assert.ok(executionDetail.children[0].textContent.includes("success"));
  assert.ok(executionDetail.children[0].textContent.includes("0초"));
  executionDetail.open = true;
  executionDetail.dispatchEvent({ type: "toggle" });
  assert.ok(detail(panel).textContent.includes("실제 실행 상태success"));
  assert.ok(detail(panel).textContent.includes("실제 실행 시간0초"));
  assert.ok(detail(panel).textContent.includes("평가 판정실패"));
  assert.ok(detail(panel).textContent.includes("원본 성공 결과"));
  assert.equal(control(panel, "caseFilter", "실패").textContent, "실패 1");
  const inventory = nodes(panel, (node) => node.tagName === "DETAILS" && node.children[0]?.textContent === "실행 기록 · 2회")[0];
  assert.ok(inventory);
  inventory.open = true;
  inventory.dispatchEvent({ type: "toggle" });
  assert.ok(inventory.textContent.includes("api.report"));
  assert.ok(inventory.textContent.includes("visualization_agent"));
  assert.ok(inventory.textContent.includes("child-run"));
  control(panel, "caseFilter", "통과").click();
  assert.ok(detail(panel).textContent.includes("1.25초"));
  assert.ok(detail(panel).textContent.includes("하위 호출 원본"));
  assert.equal(detail(panel).textContent.includes("node-span-one"), false);
});

test("실제 임시 파일 탭은 평가 항목 수 대신 종류와 실행 횟수를 표시한다", () => {
  const expectations = [
    { file: "evaluation-sample.json", labels: { report: "세부 대시보드 보고서 · 1건", nodes: "노드 · 3종 · 19회", tools: "도구 · 2종 · 9회" } },
    { file: "evaluation-user-request-sample.json", labels: { "user-request": "사용자 요청 처리 · 1건", visualization: "데이터 시각화 · 1회", nodes: "노드 · 4종 · 8회", tools: "도구 · 1종 · 1회" } },
  ];
  for (const expected of expectations) {
    const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "../viewers/report", expected.file), "utf8"));
    const { panel } = render(fixture.units, { evaluation: fixture, report: report(fixture.event, fixture.run_ids[0]) });
    for (const [kind, label] of Object.entries(expected.labels)) assert.equal(control(panel, "kind", kind).textContent, label);
    assert.equal(nodes(panel, (node) => node.dataset.kind).length, Object.keys(expected.labels).length);
    control(panel, "kind", "nodes").click();
    const targets = nodes(panel, (node) => node.tagName === "OPTION");
    assert.equal(targets.length, expected.file === "evaluation-sample.json" ? 3 : 4);
    for (const target of fixture.units.filter((item) => item.kind === "nodes")) {
      assert.ok(targets.some((option) => option.value === target.id));
    }
  }
});
