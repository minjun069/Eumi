/* 실행: node --test eval/tests/test_report_evaluation.cjs */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const catalog = require("../viewers/report/evaluation-catalog.js");
const E = require("../viewers/report/evaluation.js");

function evaluation(metrics = []) {
  return {
    type: "evaluation",
    schema_version: 1,
    id: "evaluation-one",
    title: "평가 묶음",
    sample: false,
    run_ids: ["run-one", "run-two"],
    units: [{ id: "tool-one", kind: "tools", target: "T04 저장", target_id: "T04", metrics }],
  };
}

function ratio(values = {}) {
  return { name: "입력 처리 정확도", ...values };
}

function measurement(values = {}) {
  return { name: "호출 응답시간", ...values };
}

function check(values = {}) {
  return {
    case_id: "normal-input",
    check_id: "T-I.1",
    target: "입력 조건",
    run_id: "run-one",
    executed: true,
    verdict: "통과",
    ...values,
  };
}

function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

test("임시 결과를 검사하고 적용되는 지표의 원본 수치를 보존한다", () => {
  const exampleVerdicts = new Set();
  for (const filename of ["evaluation-sample.json", "evaluation-user-request-sample.json"]) {
    const sample = JSON.parse(fs.readFileSync(path.join(__dirname, "../viewers/report", filename), "utf8"));
    const value = E.normalize(sample);
    assert.equal(value.sample, true);
    assert.equal(value.run_ids.length, 1);
    const scope = E.scopeUnits(value, report(value.run_ids[0], value.event));
    assert.deepEqual(scope.units, value.units);
    assert.deepEqual(scope.excluded, []);
    assert.deepEqual(scope.warnings, []);
    const kinds = value.units.map((item) => item.kind);
    assert.equal(kinds.includes(value.event === "analysis_pipeline" ? "user-request" : "report"), false);
    value.units.forEach((unit) => {
      for (const item of E.metricRows(unit)) {
        if (!item.result) continue;
        assert.equal(item.result.name, item.definition.name);
        if (item.definition.kind === "ratio") {
          const percentage = E.ratio(item.result);
          if (item.result.denominator > 0) assert.ok(percentage >= 0 && percentage <= 100);
          else assert.equal(percentage, null);
        } else if (item.result.measurements) assert.ok(Array.isArray(item.result.measurements));
      }
      for (const item of unit.checks) {
        exampleVerdicts.add(item.verdict);
        assert.equal(item.run_id, value.run_ids[0]);
        assert.ok(item.input !== undefined && item.expected !== undefined && item.actual !== undefined);
        assert.ok(item.metrics.length > 0);
        for (const name of item.metrics) assert.ok(E.casesForMetric(unit, name).includes(item));
      }
    });
  }
  assert.ok(exampleVerdicts.has("통과") && exampleVerdicts.has("실패"), "화면 예시 판정은 유지하되 각 대상에 가짜 호출을 추가하지 않는다.");
});

function execution(values = {}) {
  return {
    id: "span-one", name: "act", caller: "api.report", run_id: "run-one",
    status: "success", elapsed_seconds: 0,
    evidence: "outputs/report.json#/trace/spans/1", ...values,
  };
}

test("호출 기록은 실행 범위와 식별자를 검사하고 실제 0초 및 원본을 보존한다", () => {
  const value = { ...evaluation(), run_ids: ["run-one"] };
  value.units[0].executions = [execution()];
  value.units[0].checks = [check({ execution_id: "span-one", verdict: "실패" })];
  const before = JSON.stringify(value);
  freeze(value);
  assert.equal(E.normalize(value), value);
  assert.deepEqual(E.executionSummary(value.units), { recorded: true, targetCount: 1, executionCount: 1 });
  assert.equal(value.units[0].executions[0].elapsed_seconds, 0);
  assert.equal(value.units[0].executions[0].status, "success", "예시 평가 실패가 실제 실행 상태를 바꾸면 안 된다.");
  assert.equal(JSON.stringify(value), before);
});

test("잘못된 호출 기록·중복 실행 ID·없는 사례 연결을 거부하며 하위 실행 ID는 보존한다", () => {
  function withExecutions(records) {
    const value = { ...evaluation(), run_ids: ["run-one"] };
    value.units[0].executions = records;
    return value;
  }
  assert.throws(() => E.normalize(withExecutions({})), /executions 목록/);
  assert.throws(() => E.normalize(withExecutions([null])), /실행 기록/);
  for (const key of ["id", "name", "caller", "run_id", "status", "evidence"]) {
    assert.throws(() => E.normalize(withExecutions([execution({ [key]: "" })])), /실행 기록/);
  }
  const child = withExecutions([execution({ run_id: "child-run" })]);
  assert.equal(E.normalize(child).units[0].executions[0].run_id, "child-run");
  assert.throws(() => E.normalize(withExecutions([execution(), execution()])), /실행 ID 중복/);
  for (const elapsed of [-1, "0.1", Infinity, NaN])
    assert.throws(() => E.normalize(withExecutions([execution({ elapsed_seconds: elapsed })])), /elapsed_seconds/);
  const dangling = withExecutions([execution()]);
  dangling.units[0].checks = [check({ execution_id: "missing-span" })];
  assert.throws(() => E.normalize(dangling), /execution_id/);
  delete dangling.units[0].executions;
  assert.throws(() => E.normalize(dangling), /execution_id/);
});

test("종류·호출 횟수를 지표 분모나 검사 수에서 추정하지 않고 미기록과 실제 0회를 구분한다", () => {
  const first = unit("first", "nodes", "N02 작업 선택", {
    target_id: "N02", executions: [execution()],
    metrics: [{ name: "노드 출력 정확도", numerator: 19, denominator: 23 }],
    checks: [check({ case_id: "one" }), check({ case_id: "two" })],
  });
  const sameKind = unit("second", "nodes", "N02 하위 작업 선택", {
    target_id: "N02", executions: [execution(), execution({ id: "span-two" })],
  });
  const otherKind = unit("third", "nodes", "N03 진행 판단", {
    target_id: "N03", executions: [execution({ id: "span-three", name: "decide" })],
  });
  assert.deepEqual(E.executionSummary([first, sameKind, otherKind]), { recorded: true, targetCount: 2, executionCount: 3 });
  assert.deepEqual(E.executionSummary([{ ...first, executions: [] }]), { recorded: true, targetCount: 1, executionCount: 0 });
  assert.deepEqual(E.executionSummary([first, { ...otherKind, executions: undefined }]),
    { recorded: false, targetCount: 2, executionCount: null });
  assert.deepEqual(E.executionSummary([unit("legacy", "tools", "T01 조회")]),
    { recorded: false, targetCount: 1, executionCount: null });
});

const sampleExpectations = [
  { filename: "evaluation-sample.json", event: "analysis_pipeline", nodes: { N02: 9, N03: 9, N04: 1 }, tools: { T01: 3, T02: 6 }, agentKinds: ["report"] },
  { filename: "evaluation-user-request-sample.json", event: "user_request", nodes: { N01: 2, N02: 2, N03: 2, N04: 2 }, tools: { T03: 1 }, agentKinds: ["user-request", "visualization"] },
];

test("임시 결과의 대상 종류와 고유 실행 횟수는 보고서19·9회와 사용자8·1회에 맞는다", () => {
  for (const expected of sampleExpectations) {
    const value = E.normalize(JSON.parse(fs.readFileSync(path.join(__dirname, "../viewers/report", expected.filename), "utf8")));
    assert.equal(value.event, expected.event);
    for (const kind of ["nodes", "tools"]) {
      const actual = {};
      for (const target of value.units.filter((item) => item.kind === kind)) {
        assert.ok(Array.isArray(target.executions), `${expected.filename} ${target.target}: 실제 호출 목록 필요`);
        const id = E.targetId(target);
        actual[id] = (actual[id] || 0) + target.executions.length;
      }
      assert.deepEqual(actual, expected[kind]);
    }
    assert.deepEqual(value.units.filter((item) => !["nodes", "tools"].includes(item.kind)).map((item) => item.kind).sort(), expected.agentKinds.toSorted());
    for (const target of value.units) {
      const ids = new Set(target.executions.map((item) => item.id));
      for (const item of target.checks) {
        assert.ok(ids.has(item.execution_id), `${target.id}/${item.case_id}: 사례는 실제 호출을 가리켜야 한다.`);
        assert.equal(item.case_id, item.execution_id, "여러 검사를 위해 실제 호출과 다른 합성 사례를 추가하지 않는다.");
      }
    }
  }
});

function resolvePointer(value, fragment) {
  assert.ok(fragment.startsWith("/"), "근거는 JSON 포인터여야 한다.");
  return fragment.slice(1).split("/").reduce((current, key) => current[key.replaceAll("~1", "/").replaceAll("~0", "~")], value);
}

test("임시 실행 식별자·상태·시간·종류와 사례 입출력은 원본 추적 기록과 같다", (t) => {
  const samples = sampleExpectations.map(({ filename }) => JSON.parse(fs.readFileSync(path.join(__dirname, "../viewers/report", filename), "utf8")));
  const documents = new Map();
  for (const value of samples) for (const target of value.units) for (const item of target.executions) {
    const [source] = item.evidence.split("#");
    const filename = path.resolve(__dirname, "../..", source);
    if (!fs.existsSync(filename)) return t.skip(`Git에 포함하지 않는 원본 실행 기록 없음: ${source}`);
    if (!documents.has(source)) documents.set(source, JSON.parse(fs.readFileSync(filename, "utf8")));
  }
  for (const value of samples) for (const target of value.units) for (const item of target.executions) {
    const [source, pointer] = item.evidence.split("#");
    const original = documents.get(source);
    const span = resolvePointer(original, pointer);
    assert.equal(item.id, span.id, item.evidence);
    assert.equal(item.name, span.name, item.evidence);
    assert.equal(item.status, span.status, item.evidence);
    assert.equal(item.elapsed_seconds, span.elapsed_seconds, item.evidence);
    let owner = span;
    while (owner && !(owner.input?.state || owner.input?.initial_state))
      owner = original.trace.spans.find((candidate) => candidate.id === owner.parent_id);
    const inputState = owner?.input?.state || owner?.input?.initial_state;
    assert.equal(item.run_id, inputState?.execution.run_id, item.evidence);
    let caller = original.trace.spans.find((candidate) => candidate.id === span.parent_id);
    while (caller && caller.kind !== "agent")
      caller = original.trace.spans.find((candidate) => candidate.id === caller.parent_id);
    if (caller) assert.equal(item.caller, caller.name, item.evidence);
    if (["nodes", "tools"].includes(target.kind)) assert.equal(span.kind, target.kind === "nodes" ? "node" : "tool");
  }
  for (const value of samples) {
    const [source] = value.units[0].executions[0].evidence.split("#");
    for (const [kind, spanKind] of [["nodes", "node"], ["tools", "tool"]]) {
      const actualIds = value.units.filter((target) => target.kind === kind).flatMap((target) => target.executions.map((item) => item.id));
      const sourceIds = documents.get(source).trace.spans.filter((span) => span.kind === spanKind).map((span) => span.id);
      assert.deepEqual(actualIds.toSorted(), sourceIds.toSorted(), `${value.id}: 실제 ${kind} 실행의 누락·중복이 없어야 한다.`);
    }
  }
  for (const value of samples) for (const target of value.units) for (const item of target.checks) {
    for (const key of ["input", "actual"]) {
      assert.equal(typeof item.evidence[key], "string", `${target.id}/${item.case_id}/${key}: 원본 포인터 필요`);
      const [source, pointer] = item.evidence[key].split("#");
      assert.ok(documents.has(source), `호출과 같은 실행 기록에서 값을 읽어야 한다: ${source}`);
      assert.deepEqual(item[key], resolvePointer(documents.get(source), pointer), `${target.id}/${item.case_id}/${key}`);
    }
  }
});

test("분모 0과 미기록은 산출하지 않고 실제 0%는 보존한다", () => {
  for (const item of [undefined, ratio(), ratio({ numerator: null, denominator: null }),
    ratio({ numerator: 0, denominator: 0, verdict: "비적용" })]) {
    if (item) E.normalize(evaluation([item]));
    assert.equal(E.ratio(item), null);
  }
  const zero = ratio({ numerator: 0, denominator: 5, verdict: "실패" });
  E.normalize(evaluation([zero]));
  assert.equal(E.ratio(zero), 0);
  assert.equal(E.ratio(ratio({ numerator: 2, denominator: 5 })), 40);
});

test("음수·소수·문자·과다 분자와 분자 또는 분모만 있는 집계를 거부한다", () => {
  const invalid = [
    { numerator: -1, denominator: 5 },
    { numerator: 1, denominator: -5 },
    { numerator: 1.5, denominator: 5 },
    { numerator: 1, denominator: 5.5 },
    { numerator: "1", denominator: 5 },
    { numerator: 6, denominator: 5 },
    { numerator: 1 },
    { denominator: 5 },
    { numerator: null, denominator: 5 },
    { numerator: 1, denominator: Number.MAX_SAFE_INTEGER + 1 },
  ];
  for (const values of invalid) {
    assert.throws(() => E.normalize(evaluation([ratio(values)])), /분자·분모/);
  }
  for (const key of ["unjudged", "not_applicable", "not_executed"]) {
    assert.throws(() => E.normalize(evaluation([ratio({ [key]: -1 })])), /0 이상의 정수/);
  }
});

test("시간·비용의 실제 0과 미측정을 보존하고 잘못된 측정값을 거부한다", () => {
  const values = [{ label: "성공 중앙값", value: 0, unit: "초" },
    { label: "오류 p95", value: null, unit: "초" }];
  const value = E.normalize(evaluation([measurement({ measurements: values })]));
  const saved = E.metricRows(value.units[0]).find((row) => row.result).result;
  assert.equal(saved.measurements[0].value, 0);
  assert.equal(saved.measurements[1].value, null);
  for (const invalid of [-0.1, "0.1", Infinity, NaN]) {
    assert.throws(() => E.normalize(evaluation([measurement({
      measurements: [{ label: "p95", value: invalid, unit: "초" }],
    })])), /측정 항목/);
  }
  assert.throws(() => E.normalize(evaluation([measurement({ measurements: {} })])), /measurements/);
  assert.throws(() => E.normalize(evaluation([measurement({
    measurements: [{ label: "p95", value: 0.1 }],
  })])), /측정 항목/);
});

test("자료가 없거나 분모가 0인 지표를 통과로 받아들이지 않는다", () => {
  for (const item of [ratio({ verdict: "통과" }),
    ratio({ numerator: 0, denominator: 0, verdict: "통과" }),
    measurement({ verdict: "통과", measurements: [] }),
    measurement({ verdict: "통과", measurements: [{ label: "p95", value: null, unit: "초" }] })]) {
    assert.throws(() => E.normalize(evaluation([item])), /통과로 기록할 수 없습니다/);
  }
  assert.doesNotThrow(() => E.normalize(evaluation([measurement({
    verdict: "통과", measurements: [{ label: "p95", value: 0, unit: "초" }],
  })])));
});

test("알 수 없는 지표·평가 단위, 중복 지표와 중복 단위 ID를 거부한다", () => {
  assert.throws(() => E.normalize(evaluation([{ name: "임의 정확도" }])), /평가 문서에 없는 지표/);
  assert.throws(() => E.normalize(evaluation([null])), /평가 문서에 없는 지표/);
  assert.throws(() => E.normalize(evaluation([ratio(), ratio()])), /지표가 중복/);
  const duplicated = evaluation();
  duplicated.units.push({ ...duplicated.units[0] });
  assert.throws(() => E.normalize(duplicated), /평가 단위 ID 중복/);
  const unknown = evaluation();
  unknown.units[0].kind = "unknown";
  assert.throws(() => E.normalize(unknown), /평가 단위/);
  const malformed = evaluation();
  malformed.units[0].metrics = {};
  assert.throws(() => E.normalize(malformed), /metrics 목록/);
});

test("실행 보고서와 지원하지 않는 평가 버전·잘못된 판정 입력을 거부한다", () => {
  for (const value of [null, [], { state: { execution: { run_id: "run-one" } } },
    { ...evaluation(), schema_version: 2 }, { ...evaluation(), schema_version: "1" }]) {
    assert.throws(() => E.normalize(value), /schema_version: 1/);
  }
  assert.throws(() => E.normalize({ ...evaluation(), sample: "false" }), /sample/);
  assert.throws(() => E.normalize({ ...evaluation(), run_ids: [] }), /run_ids/);
  assert.throws(() => E.normalize(evaluation([ratio({ verdict: "성공" })])), /판정 값/);
  assert.throws(() => E.normalize(evaluation([ratio({ required: "true" })])), /required/);
  const value = evaluation();
  value.units[0].verdicts = { functional: "성공" };
  assert.throws(() => E.normalize(value), /기능·운영·연동 판정/);
});

test("미실행 검사의 통과·실패를 거부하고 미판정을 그대로 보존한다", () => {
  const value = evaluation();
  for (const verdict of ["통과", "실패"]) {
    value.units[0].checks = [check({ executed: false, verdict })];
    assert.throws(() => E.normalize(value), /미실행 검사를 통과·실패/);
  }
  value.units[0].checks = [check({ executed: false, verdict: "미판정" })];
  E.normalize(value);
  assert.equal(value.units[0].checks[0].executed, false);
  assert.equal(value.units[0].checks[0].verdict, "미판정");
  value.units[0].checks[0].run_id = "unrelated-run";
  assert.throws(() => E.normalize(value), /검사 실행 ID가 해당 단위 run_ids에 없습니다/);
});

test("평가 묶음은 기록된 실행 ID와 정확히 일치할 때만 연결한다", () => {
  const first = E.normalize(evaluation());
  const other = E.normalize({ ...evaluation(), id: "other", run_ids: ["run-three"] });
  assert.deepEqual([first, other].filter((value) => E.matches(value, "run-two")), [first]);
  for (const runId of [undefined, null, "", "run", "run-one ", "RUN-ONE"]) {
    assert.equal(E.matches(first, runId), false);
  }
  assert.equal(E.matches(first, "run-three"), false);
});

test("부분 평가도 모든 지표 자리를 남기며 누락을 0·비적용·통과로 채우지 않는다", () => {
  const value = evaluation([ratio({ numerator: 5, denominator: 5, verdict: "미판정" })]);
  value.units[0].verdicts = { functional: "실패", operational: "미판정" };
  E.normalize(value);
  const rows = E.metricRows(value.units[0]);
  assert.equal(rows.length, catalog.tools.metrics.length);
  assert.equal(rows.filter((row) => row.result === undefined).length, rows.length - 1);
  const recorded = rows.find((row) => row.result);
  assert.equal(E.ratio(recorded.result), 100);
  assert.equal(recorded.result.verdict, "미판정");
  assert.equal(value.units[0].verdicts.functional, "실패");
  assert.equal(value.units[0].metrics.length, 1);
});

test("입력 검사·실행 연결·표시용 변환은 원본 평가와 증거를 변경하지 않는다", () => {
  const value = evaluation([ratio({ numerator: 2, denominator: 3,
    evidence: [{ path: "trace.json#/calls/0", quoted: "원문 그대로" }], unjudged: 1 })]);
  value.units[0].checks = [check({ actual: { returned: [1, 2] } })];
  const before = JSON.stringify(value);
  freeze(value);
  assert.equal(E.normalize(value), value);
  E.matches(value, "run-one");
  E.scopeUnits(value, { state: { execution: { run_id: "run-one", event: "user_request" } } });
  E.casesForMetric(value.units[0], "입력 처리 정확도");
  E.metricRows(value.units[0]).forEach(({ result }) => E.ratio(result));
  assert.equal(JSON.stringify(value), before);
});

function report(runId, event) {
  return { state: { execution: { run_id: runId, event } } };
}

function unit(id, kind, target, extra = {}) {
  return { id, kind, target, metrics: [], ...extra };
}

test("시작 이벤트별 주 평가 대상과 N01을 구분하고 별도 전문 작업만 남긴다", () => {
  const value = {
    ...evaluation(), run_ids: ["run-one"], units: [
      unit("request", "user-request", "사용자 질문"),
      unit("report", "report", "동별 보고서"),
      unit("purpose", "nodes", "N01 작업 목적 파악"),
      unit("select", "nodes", "N02 작업 선택 및 실행"),
      unit("review", "nodes", "보고서 내부 검토"),
      unit("tool", "tools", "T03 시각화 설정 검사"),
      unit("specialist", "visualization", "상위에서 별도 배정한 시각화 작업"),
    ],
  };
  E.normalize(value);
  assert.deepEqual(E.visibleUnits(value, report("run-one", "user_request")).map((item) => item.id),
    ["request", "purpose", "select", "tool", "specialist"]);
  const scope = E.scopeUnits(value, report("run-one", "analysis_pipeline"));
  assert.deepEqual(scope.units.map((item) => item.id), ["report", "select", "tool", "specialist"]);
  assert.deepEqual(scope.excluded.map(({ unit: item, reason }) => [item.id, reason]), [
    ["request", "event-not-applicable"], ["purpose", "event-not-applicable"], ["review", "target-unidentified"],
  ]);
  value.units = [value.units[1]];
  assert.deepEqual(E.visibleUnits(value, report("run-one", "analysis_pipeline")).map((item) => item.kind), ["report"]);
});

test("단독 파일도 기록된 이벤트로 구분하고 실행과 파일 이벤트 불일치를 숨기지 않는다", () => {
  const value = { ...evaluation(), event: "analysis_pipeline", run_ids: ["run-one"], units: [
    unit("request", "user-request", "사용자 질문"), unit("report", "report", "동별 보고서"),
  ] };
  E.normalize(value);
  assert.deepEqual(E.visibleUnits(value).map((item) => item.id), ["report"]);
  const scope = E.scopeUnits(value, report("run-one", "user_request"));
  assert.equal(scope.units.length, 0);
  assert.ok(scope.excluded.every((item) => item.reason === "event-mismatch"));
  assert.throws(() => E.normalize({ ...value, event: "report" }), /평가 event/);
});

test("여러 실행의 합계를 개별 실행 값으로 표시하지 않고 단위별 실행 범위를 사용한다", () => {
  const value = { ...evaluation(), units: [
    unit("aggregate", "tools", "T01 조회", { metrics: [ratio({ numerator: 8, denominator: 10 })] }),
    unit("first", "tools", "T01 조회", { run_ids: ["run-one"], metrics: [ratio({ numerator: 2, denominator: 3 })] }),
    unit("second", "tools", "T01 조회", { run_ids: ["run-two"] }),
    unit("explicit-aggregate", "tools", "T01 조회", { run_ids: ["run-one", "run-two"] }),
  ] };
  E.normalize(value);
  const before = JSON.stringify(value);
  freeze(value);
  const scope = E.scopeUnits(value, report("run-one", "user_request"));
  assert.deepEqual(scope.units.map((item) => item.id), ["first"]);
  assert.equal(scope.units[0], value.units[1]);
  assert.equal(E.metricRows(scope.units[0])[0].result.numerator, 2);
  assert.deepEqual(scope.excluded.map(({ unit: item, reason }) => [item.id, reason]), [
    ["aggregate", "mixed-runs"], ["second", "run-mismatch"], ["explicit-aggregate", "mixed-runs"],
  ]);
  assert.equal(E.visibleUnits(value).length, 4);
  assert.equal(E.visibleUnits(value, report("unknown", "user_request")).length, 0);
  assert.equal(JSON.stringify(value), before);
});

test("저장 행동과 진행 판단 진단은 해당 도구·노드에서만 보여 준다", () => {
  const names = (value) => E.metricRows(value).map((row) => row.definition.name);
  const tool = unit("tool", "tools", "T03 시각화 설정 검사", {
    metrics: [{ name: "행동 준수율", numerator: 1, denominator: 1, verdict: "통과" }],
  });
  assert.equal(names(tool).includes("행동 준수율"), false);
  assert.equal(names({ ...tool, target_id: "T04" }).includes("행동 준수율"), true);
  assert.equal(names({ ...tool, target: "저장 도구" }).includes("행동 준수율"), false);
  const node = unit("node", "nodes", "N04 응답 작성");
  const diagnostic = ["분기 정확도", "진행 장애 탐지율", "정상 통과율"];
  assert.ok(diagnostic.every((name) => !names(node).includes(name)));
  assert.ok(diagnostic.every((name) => names({ ...node, target_id: "N03" }).includes(name)));
  assert.equal(names(node).includes("노드 출력 정확도"), true);
});

test("비적용 지표만 제외하고 필요한 미기록·미실행·미판정은 남긴다", () => {
  const value = unit("node", "nodes", "N03 작업 진행 판단", { metrics: [
    { name: "분기 정확도", verdict: "비적용", numerator: 0, denominator: 0 },
    { name: "진행 장애 탐지율", verdict: "미판정", not_executed: 2, numerator: 0, denominator: 2 },
    { name: "정상 통과율", verdict: "미판정", unjudged: 1, numerator: 0, denominator: 1 },
  ] });
  E.normalize({ ...evaluation(), units: [value] });
  const rows = E.metricRows(value);
  assert.equal(rows.length, catalog.nodes.metrics.length - 1);
  assert.equal(rows.some((row) => row.definition.name === "분기 정확도"), false);
  assert.equal(rows.find((row) => row.definition.name === "진행 장애 탐지율").result.not_executed, 2);
  assert.equal(rows.find((row) => row.definition.name === "정상 통과율").result.unjudged, 1);
  assert.equal(rows.find((row) => row.definition.name === "노드 출력 정확도").result, undefined);
});

test("식별되지 않은 도구는 공통 지표만 보이고 전용 지표 미확정 사유를 남긴다", () => {
  const value = { ...evaluation(), units: [unit("unknown", "tools", "외부 도구")] };
  const scope = E.scopeUnits(value);
  assert.equal(scope.units.length, 1);
  assert.deepEqual(scope.warnings.map((item) => item.reason), ["target-unidentified"]);
  assert.equal(E.metricRows(scope.units[0]).length, catalog.tools.metrics.length - 1);
});

test("성공·실패·미실행 사례는 명시적으로 연결된 지표에서만 원본 그대로 찾는다", () => {
  const value = evaluation([ratio({ numerator: 1, denominator: 2 })]);
  value.units[0].checks = [
    check({ case_id: "success", metrics: ["입력 처리 정확도"],
      input: { district: "가동" }, expected: "유효 입력 수용", actual: { accepted: true } }),
    check({ case_id: "failure", verdict: "실패", metrics: ["입력 처리 정확도", "도구 출력 정확도"],
      expected: "잘못된 입력 거부", actual: { accepted: true }, reason: "등록되지 않은 조건을 수용함" }),
    check({ case_id: "pending", executed: false, verdict: "미판정", metrics: ["입력 처리 정확도"] }),
    check({ case_id: "unlinked", metrics: undefined }),
  ];
  E.normalize(value);
  freeze(value);
  const cases = E.casesForMetric(value.units[0], "입력 처리 정확도");
  assert.deepEqual(cases.map((item) => item.case_id), ["success", "failure", "pending"]);
  assert.equal(cases[0], value.units[0].checks[0]);
  assert.equal(cases[0].expected, "유효 입력 수용");
  assert.deepEqual(cases[0].input, { district: "가동" });
  assert.deepEqual(E.casesForMetric(value.units[0], "도구 출력 정확도").map((item) => item.case_id), ["failure"]);
  assert.deepEqual(E.casesForMetric(value.units[0], "호출 응답시간"), []);
  assert.deepEqual(E.casesForMetric(unit("empty", "tools", "T01 조회"), "입력 처리 정확도"), []);
});

test("다른 실행의 사례·단위, 알 수 없는 대상 및 지표 연결을 거부한다", () => {
  for (const runIds of [[], ["unknown"], ["run-one", "run-one"], "run-one"]) {
    const value = evaluation();
    value.units[0].run_ids = runIds;
    assert.throws(() => E.normalize(value), /단위 run_ids/);
  }
  const scoped = evaluation();
  scoped.units[0].run_ids = ["run-two"];
  scoped.units[0].checks = [check()];
  assert.throws(() => E.normalize(scoped), /해당 단위 run_ids/);
  for (const links of ["입력 처리 정확도", ["없는 지표"], ["입력 처리 정확도", "입력 처리 정확도"], [null]]) {
    const value = evaluation();
    value.units[0].checks = [check({ metrics: links })];
    assert.throws(() => E.normalize(value), /metrics에는/);
  }
  const unknown = evaluation();
  unknown.units[0].target_id = "N03";
  assert.throws(() => E.normalize(unknown), /target_id/);
  assert.throws(() => E.normalize({ ...evaluation(), run_ids: ["run-one", "run-one"] }), /run_ids/);
});
