/* Saved evaluation evidence only. This module never executes or grades. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ExecutionEvaluationData = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const string = value => typeof value === "string";
  const nonempty = value => string(value) && value.length > 0;
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const nullableString = value => value === null || string(value);
  const nullableNumber = value => value === null || (typeof value === "number" && Number.isFinite(value) && value >= 0);
  const strings = value => Array.isArray(value) && value.every(string);
  const targets = new Map([
    ["tool", ["query_data", "process_data", "validate_visualization", "render_visualization"]],
    ["node", ["interpret", "act", "decide", "compose", "ask"]],
    ["selection", ["act"]],
    ["agent", ["request", "interpretation", "visualization", "report_selection", "report_description", "report_insight"]],
    ["workflow", ["report"]],
  ]);
  const roles = targets.get("agent");
  const executionRun = item => item.unit === "agent" || item.unit === "workflow" && item.target === "report";
  const functionalRun = item => item.unit === "agent" && item.target === "request" || item.unit === "workflow" && item.target === "report";
  const statuses = ["running", "returned", "error", "cancelled"];
  const artifactNames = new Set(["batch.json", "suite.json", "report.json", "case.json", "manifest.json", "trace.jsonl"]);
  const basename = path => path.slice(path.lastIndexOf("/") + 1);
  const dirname = path => path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  const join = (directory, file) => directory ? `${directory}/${file}` : file;

  function check(condition, message) { if (!condition) throw new Error(message); }
  function fields(value, requirements, at) {
    check(object(value), `${at}: 객체가 필요합니다.`);
    for (const [key, test] of Object.entries(requirements)) {
      check(own(value, key) && test(value[key]), `${at}.${key}: 필수 필드의 형식이 올바르지 않습니다.`);
    }
  }
  function optional(value, key, test, at) {
    if (own(value, key)) check(test(value[key]), `${at}.${key}: 형식이 올바르지 않습니다.`);
  }
  function target(value, at) {
    check(targets.has(value.unit) && targets.get(value.unit).includes(value.target), `${at}: 실행 단위와 대상 조합이 올바르지 않습니다.`);
  }
  function failure(value, at, depth = 0) {
    check(depth < 64, `${at}: 오류 원인의 중첩이 너무 깊습니다.`);
    fields(value, { type: string, code: nullableString }, at);
    optional(value, "http_status", item => item === null || integer(item), at);
    optional(value, "validation_errors", item => Array.isArray(item) && item.every(object), at);
    optional(value, "retryable", item => typeof item === "boolean", at);
    if (own(value, "cause")) failure(value.cause, `${at}.cause`, depth + 1);
  }
  function span(value, at) {
    fields(value, { id: nonempty, parent_id: nullableString, sequence: integer, kind: string,
      name: string, started_at: string, ended_at: nullableString, elapsed_seconds: nullableNumber,
      status: string, input: () => true }, at);
    optional(value, "http_request", object, at);
    optional(value, "http_response", object, at);
    if (own(value, "error")) failure(value.error, `${at}.error`);
  }
  function trace(value) {
    fields(value, { version: item => item === "local-execution-trace-v1", scope: string,
      limitations: strings, counts: object, coverage: object, spans: Array.isArray }, "trace");
    check(Object.values(value.counts).every(integer), "trace.counts: 0 이상의 정수 값이 필요합니다.");
    fields(value.coverage, Object.fromEntries(["model_attempts", "model_inputs", "http_requests", "http_responses", "sdk_responses", "model_errors", "unfinished_spans"].map(key => [key, integer])), "trace.coverage");
    value.spans.forEach((item, index) => span(item, `trace.spans[${index}]`));
  }
  function fixtures(value) {
    fields(value, { calls: Array.isArray, unexpected: Array.isArray, unused: Array.isArray }, "fixtures");
    value.calls.forEach((item, index) => fields(item, { name: string, arguments: object, stub: integer }, `fixtures.calls[${index}]`));
    value.unexpected.forEach((item, index) => fields(item, { name: string, arguments: object }, `fixtures.unexpected[${index}]`));
    value.unused.forEach((item, index) => fields(item, { stub: integer, remaining: item => integer(item) && item >= 1 }, `fixtures.unused[${index}]`));
  }
  function runReport(value) {
    fields(value, { schema_version: item => item === "evaluation-run-v1", run: object,
      output: item => item === null || object(item), failure: item => item === null || object(item),
      trace: object, assessment: object, fixtures: object, journal_saved: item => typeof item === "boolean" }, "report");
    fields(value.run, { id: nonempty, suite_id: nonempty, case_id: nonempty,
      repetition: item => integer(item) && item >= 1, unit: string, target: string,
      role: item => item === null || roles.includes(item), dependencies: item => ["real", "stub"].includes(item),
      status: item => ["returned", "error", "cancelled"].includes(item), started_at: string,
      ended_at: nullableString, elapsed_seconds: nullableNumber }, "run");
    target(value.run, "run");
    const run = value.run;
    check(run.unit === "tool" ? run.role === null && run.dependencies === "real" : run.unit === "workflow" ? run.role === null : roles.includes(run.role), "run: 역할 또는 하위 호출 방식이 실행 단위와 맞지 않습니다.");
    if (run.unit === "agent") check(run.role === run.target, "run.role: 에이전트 대상과 역할이 다릅니다.");
    if (run.unit === "selection") check(run.dependencies === "real", "run.dependencies: 작업 선택에는 하위 호출이 없습니다.");
    if (value.output !== null) {
      if (["node", "selection"].includes(run.unit)) fields(value.output, { model_call: nonempty, raw: string }, "output");
      if (["agent", "workflow"].includes(run.unit)) check(false, "output: 에이전트·생성 흐름의 직접 반환값은 null이어야 합니다.");
    }
    if (own(value, "state")) {
      fields(value.state, { execution: object }, "state");
      fields(value.state.execution, { run_id: item => item === run.id, status: string }, "state.execution");
    }
    if (value.failure !== null) failure(value.failure, "failure");
    fields(value.assessment, { verdict: item => item === "미판정", executed: item => item === false, reason: string, checks: strings }, "assessment");
    trace(value.trace);
    fixtures(value.fixtures);
  }
  function batchReport(value) {
    fields(value, { schema_version: item => item === "evaluation-batch-v1", id: nonempty, suite_id: nonempty,
      status: item => statuses.includes(item), started_at: string, ended_at: nullableString,
      planned_runs: integer, runs: Array.isArray }, "batch");
    check(value.planned_runs >= value.runs.length, "batch.planned_runs: 등록 실행 수보다 작습니다.");
    if (own(value, "failure")) failure(value.failure, "batch.failure");
  }
  function batchEntry(value) {
    fields(value, { case_id: nonempty, run_id: nonempty, unit: string, target: string,
      repetition: item => integer(item) && item >= 1, status: item => statuses.includes(item), path: nonempty }, "batch.runs[]");
    target(value, "batch.runs[]");
    check(!/[\\/]/.test(value.run_id), "batch.runs[].run_id: 실행 ID에 경로 구분자를 사용할 수 없습니다.");
    check(relativePath(value.path) === `runs/${value.run_id}/report.json`, "batch.runs[].path: 실행 ID에 맞는 runs/<실행 ID>/report.json 상대 경로가 필요합니다.");
  }
  function caseFile(value) {
    fields(value, { id: nonempty, unit: string, target: string, purpose: string }, "case");
    target(value, "case");
    optional(value, "assessment", object, "case");
    optional(value, "tags", strings, "case");
    optional(value, "providers", strings, "case");
    optional(value, "dependencies", item => ["real", "stub"].includes(item), "case");
    optional(value, "stubs", Array.isArray, "case");
    if (value.unit === "tool") {
      fields(value, { arguments: object }, "case");
      check(!own(value, "role") && (value.dependencies || "real") === "real", "case: 도구는 실제 구현을 실행하며 역할을 지정하지 않습니다.");
      if (value.target === "validate_visualization") fields(value, { initial: object }, "case");
    } else {
      fields(value, { initial: object }, "case");
      check(!own(value, "arguments"), "case.arguments: 도구 외 단위는 initial을 사용합니다.");
      if (["agent", "workflow"].includes(value.unit)) check(!own(value, "role"), "case.role: 에이전트·생성 흐름에 역할을 따로 지정하지 않습니다.");
      else fields(value, { role: item => roles.includes(item) }, "case");
      if (value.unit === "selection") check((value.dependencies || "real") === "real", "case.dependencies: 작업 선택에는 하위 호출이 없습니다.");
    }
    if (value.assessment) {
      optional(value.assessment, "checks", strings, "case.assessment");
      optional(value.assessment, "required", item => typeof item === "boolean", "case.assessment");
    }
  }
  function suiteFile(value) {
    fields(value, { schema_version: item => item === "evaluation-suite-v1", id: nonempty, cases: Array.isArray }, "suite");
    const ids = new Set();
    for (const item of value.cases) {
      caseFile(item);
      check(!ids.has(item.id), "suite.cases: 중복된 사례 ID가 있습니다.");
      ids.add(item.id);
    }
    optional(value, "datasets", object, "suite");
    optional(value, "catalog", object, "suite");
  }
  function manifestFile(value) {
    fields(value, { version: item => item === "execution-manifest-v1", captured_at: string,
      git: object, content_sha256: string, files_sha256: object, settings: object, evaluation: object }, "manifest");
    fields(value.git, { revision: nullableString, dirty: item => item === null || typeof item === "boolean" }, "manifest.git");
    check(Object.values(value.files_sha256).every(string), "manifest.files_sha256: 문자열 해시가 필요합니다.");
    fields(value.evaluation, { suite_id: nonempty, suite_sha256: string, source: nullableString,
      source_sha256: nullableString, runner_sha256: object }, "manifest.evaluation");
    check(Object.values(value.evaluation.runner_sha256).every(string), "manifest.evaluation.runner_sha256: 문자열 해시가 필요합니다.");
  }
  function scoredBatch(value) {
    const boolean = item => typeof item === "boolean";
    const verdict = item => ["통과", "실패", "미판정", "비적용"].includes(item);
    const positive = item => integer(item) && item > 0;
    const integers = item => Array.isArray(item) && item.every(positive);
    const hashes = item => object(item) && Object.values(item).every(string);
    const rate = item => item === null || (nullableNumber(item) && item <= 1);
    const metrics = ["elapsed_seconds", "model_calls", "tool_calls", "agent_calls", "node_entries", "retries", "input_tokens", "output_tokens", "cost"];
    const conditions = ["target", "role", "dependencies", "situation", "entry", "environment", "data_size"];
    const ratio = (item, at) => fields(item, {numerator: integer, denominator: integer, rate}, at);
    const statistics = (item, at) => fields(item, {sample_count: integer, missing_count: integer,
      mean: nullableNumber, median: nullableNumber, p95: nullableNumber, minimum: nullableNumber, maximum: nullableNumber}, at);
    const statisticsMap = (item, at) => {
      fields(item, Object.fromEntries(metrics.map(key => [key, object])), at);
      Object.entries(item).forEach(([key, values]) => statistics(values, at + "." + key));
    };
    fields(value, {schema_version: item => item === "execution-evaluation-v1", id: nonempty,
      batch_id: nonempty, suite_id: nonempty, assessed_at: item => string(item) && Number.isFinite(Date.parse(item)),
      method: item => item === "rules", criteria: object, criteria_sha256: string, evidence_sha256: hashes,
      evaluator_sha256: hashes, runs: Array.isArray, summary: object, limitations: strings,
      provenance: Array.isArray, selection: object}, "execution-evaluation");
    fields(value.criteria, {documents: object, cases: Array.isArray, original_plan: object,
      execution_performance: Array.isArray, execution_prices: item => item === null || object(item)}, "criteria");
    fields(value.criteria.original_plan, {case_ids: strings, repeat: positive}, "criteria.original_plan");
    const cases = new Map();
    value.criteria.cases.forEach(item => {
      caseFile(item);
      check(executionRun(item), "criteria.cases: 에이전트·보고서 실행 사례가 필요합니다.");
      check(!cases.has(item.id), "criteria.cases: 중복 사례 ID입니다.");
      check(value.criteria.original_plan.case_ids.includes(item.id), "criteria.cases: 원래 실행 계획에 없는 사례입니다.");
      cases.set(item.id, item);
    });
    value.criteria.execution_performance.forEach((goal, index) => {
      const at = "criteria.execution_performance[" + index + "]";
      fields(goal, {target: item => ["request", "report"].includes(item),
        metric: item => ["latency", "failure_rate", "cost", "repeat_spread"].includes(item),
        case_ids: item => strings(item) && item.length > 0 && item.every(nonempty)}, at);
      optional(goal, "statistic", item => ["median", "p95", "mean"].includes(item), at);
      optional(goal, "group", item => ["normal", "technical_failure", "cancelled"].includes(item), at);
      for (const key of ["max_seconds", "max_cost", "max_spread"]) optional(goal, key, item => item !== null && nullableNumber(item), at);
      optional(goal, "max_rate", item => item !== null && rate(item), at);
      optional(goal, "measure", item => metrics.includes(item), at);
      for (const key of ["environment", "data_size"]) optional(goal, key, nonempty, at);
    });
    const prices = value.criteria.execution_prices;
    if (prices !== null) {
      fields(prices, {version: nonempty, currency: nonempty, models: object, tools: object}, "criteria.execution_prices");
      for (const price of Object.values(prices.models)) fields(price, {
        input_per_million: item => item !== null && nullableNumber(item),
        output_per_million: item => item !== null && nullableNumber(item)}, "criteria.execution_prices.models[]");
      for (const price of Object.values(prices.tools)) fields(price, {
        per_call: item => item !== null && nullableNumber(item)}, "criteria.execution_prices.tools[]");
    }
    const runKeys = new Set(), runIds = new Set();
    value.runs.forEach((run, index) => {
      const at = "runs[" + index + "]";
      fields(run, {run_id: item => item === null || nonempty(item), case_id: nonempty,
        repetition: positive, complete: boolean, verdict, started: boolean, checks: Array.isArray,
        report_completeness: item => item === null || ["complete", "partial", "none"].includes(item)}, at);
      const input = cases.get(run.case_id);
      check(input && functionalRun(input), at + ": 기능 평가 대상 사례가 아닙니다.");
      check(run.repetition <= value.criteria.original_plan.repeat, at + ": 예정 반복 범위를 벗어났습니다.");
      const key = JSON.stringify([run.case_id, run.repetition]);
      check(!runKeys.has(key) && (run.run_id === null || !runIds.has(run.run_id)), at + ": 중복 실행 판정입니다.");
      runKeys.add(key); if (run.run_id !== null) runIds.add(run.run_id);
      const checks = new Set();
      run.checks.forEach((item, i) => {
        const checkAt = at + ".checks[" + i + "]";
        fields(item, {check: nonempty, executed: boolean, complete: boolean, verdict, reason: string, details: Array.isArray}, checkAt);
        check(!checks.has(item.check), checkAt + ": 중복 검사입니다."); checks.add(item.check);
        item.details.forEach((detail, j) => fields(detail, {target: string, verdict, executed: boolean,
          reason: string, evidence: strings}, checkAt + ".details[" + j + "]"));
      });
    });
    fields(value.summary, {functional: object, report_completion: object, operational: object}, "summary");
    const functional = value.summary.functional;
    fields(functional, {verdict, complete: boolean, checks: Array.isArray, cases: object, verification: object}, "summary.functional");
    functional.checks.forEach(item => {
      fields(item, {check: nonempty, passed: integer, failed: integer, undetermined: integer,
        unexecuted: integer, not_applicable: integer, reasons: strings}, "functional.checks[]");
      ratio(item, "functional.checks[]");
    });
    fields(functional.cases, {passed: integer, failed: integer, undetermined: integer,
      excluded: integer, unspecified_required: integer, items: Array.isArray}, "functional.cases");
    ratio(functional.cases, "functional.cases");
    functional.cases.items.forEach(item => {
      fields(item, {case_id: nonempty, required: n => n === null || boolean(n), verdict, complete: boolean,
        planned_repetitions: integer, recorded_repetitions: integer, missing_repetitions: integers,
        incomplete_repetitions: integers, reasons: strings}, "functional.cases.items[]");
      check(cases.has(item.case_id), "functional.cases.items[]: 기준에 없는 사례입니다.");
    });
    fields(functional.verification, {required_cases: integer, completed_cases: integer,
      incomplete_cases: integer, missing_repetitions: integer}, "functional.verification");
    ratio(value.summary.report_completion, "summary.report_completion");
    function measurement(item, at) {
      fields(item, {case_id: nonempty, run_id: item => item === null || nonempty(item), repetition: positive,
        unit: string, target: nonempty, role: item => item === null || roles.includes(item),
        dependencies: string, started: boolean, ended: boolean, returned: boolean,
        evidence_complete: boolean, outcome: string, returned_status: nullableString,
        elapsed_seconds: nullableNumber, observed_at: nullableString, timing_scope: nullableString,
        budget_delta: object, observed_tokens: object, missing_token_calls: object, observed_calls: object,
        model_cost: nullableNumber, tool_cost: nullableNumber, cost: nullableNumber,
        currency: nullableString, failed_calls: object, reasons: strings,
        ...Object.fromEntries(["situation", "entry", "environment", "data_size", "dong_code", "month"].map(key => [key, nullableString])),
        ...Object.fromEntries(["model_calls", "tool_calls", "agent_calls", "node_entries", "retries", "input_tokens", "output_tokens"].map(key => [key, nullableNumber]))}, at);
      const input = cases.get(item.case_id);
      check(input && input.unit === item.unit && input.target === item.target, at + ": 기준 사례와 단위·대상이 다릅니다.");
      check(item.repetition <= value.criteria.original_plan.repeat, at + ": 예정 반복 범위를 벗어났습니다.");
      check(Object.values(item.budget_delta).every(nullableNumber), at + ".budget_delta: 사용량 형식이 올바르지 않습니다.");
      fields(item.observed_tokens, {input_tokens: nullableNumber, output_tokens: nullableNumber}, at + ".observed_tokens");
      fields(item.missing_token_calls, {input_tokens: integer, output_tokens: integer}, at + ".missing_token_calls");
      fields(item.observed_calls, {model: integer, tool: integer, agent: integer, node: integer}, at + ".observed_calls");
      check(Object.values(item.failed_calls).every(integer), at + ".failed_calls: 호출 건수 형식이 올바르지 않습니다.");
    }
    const ops = value.summary.operational;
    fields(ops, {measurement_scope: item => item === "execution", verdict, complete: boolean,
      groups: Array.isArray, repetitions: Array.isArray, goals: Array.isArray, runs: Array.isArray,
      unfinished_usage: Array.isArray, reasons: strings}, "summary.operational");
    const measurementKeys = new Set(), measurementIds = new Set();
    ops.runs.forEach((item, index) => {
      const at = "operational.runs[" + index + "]";
      measurement(item, at);
      const key = JSON.stringify([item.case_id, item.repetition]);
      check(!measurementKeys.has(key) && (item.run_id === null || !measurementIds.has(item.run_id)), at + ": 중복 실행 측정입니다.");
      measurementKeys.add(key); if (item.run_id !== null) measurementIds.add(item.run_id);
      const scored = value.runs.find(run => run.case_id === item.case_id && run.repetition === item.repetition);
      check(!scored || scored.run_id === item.run_id, at + ": 기능 판정과 실행 ID가 다릅니다.");
    });
    function measuredRuns(items, at) {
      items.forEach((item, index) => {
        measurement(item, at + "[" + index + "]");
        check(ops.runs.some(run => run.case_id === item.case_id && run.repetition === item.repetition && run.run_id === item.run_id),
          at + ": 원래 실행 측정이 없습니다.");
      });
    }
    ops.groups.forEach(group => {
      fields(group, {conditions: object, started: integer, ended: integer, unfinished: integer,
        outcomes: object, failure_rate: object, measurements: object, elapsed_by_outcome: object,
        report_completion: object, runs: Array.isArray}, "operational.groups[]");
      fields(group.conditions, Object.fromEntries(conditions.map(key => [key, nullableString])), "operational.groups[].conditions");
      ["dong_code", "month"].forEach(key => optional(group.conditions, key, nullableString, "operational.groups[].conditions"));
      Object.values(group.outcomes).forEach(item => ratio(item, "operational.groups[].outcomes[]"));
      ratio(group.failure_rate, "operational.groups[].failure_rate");
      fields(group.failure_rate, {unclassified_count: integer, evaluation_failure_count: integer, unfinished_count: integer}, "operational.groups[].failure_rate");
      statisticsMap(group.measurements, "operational.groups[].measurements");
      Object.values(group.elapsed_by_outcome).forEach(item => statistics(item, "operational.groups[].elapsed_by_outcome[]"));
      ratio(group.report_completion, "operational.groups[].report_completion");
      measuredRuns(group.runs, "operational.groups[].runs");
    });
    ops.repetitions.forEach(item => {
      fields(item, {case_id: nonempty, planned: integer, started: integer, ended: integer, unfinished: integer,
        missing_repetitions: integers, measurements: object, runs: Array.isArray}, "operational.repetitions[]");
      check(cases.has(item.case_id), "operational.repetitions[]: 기준에 없는 사례입니다.");
      statisticsMap(item.measurements, "operational.repetitions[].measurements");
      measuredRuns(item.runs, "operational.repetitions[].runs");
    });
    ops.goals.forEach(item => fields(item, {target: nonempty, metric: nonempty, case_ids: strings,
      statistic: nullableString, value: nullableNumber, maximum: nullableNumber, sample_count: integer,
      verdict, complete: boolean, reasons: strings}, "operational.goals[]"));
    measuredRuns(ops.unfinished_usage, "operational.unfinished_usage");
    fields(value.selection, {case_ids: strings, check_ids: strings, excluded: Array.isArray,
      functional_excluded: Array.isArray, selected_case_ids: strings}, "selection");
    for (const name of ["excluded", "functional_excluded"]) value.selection[name].forEach(item =>
      fields(item, {case_id: nonempty, reason: string}, "selection." + name + "[]"));
    check(value.selection.selected_case_ids.length === cases.size &&
      new Set(value.selection.selected_case_ids).size === cases.size &&
      value.selection.selected_case_ids.every(id => cases.has(id)), "selection.selected_case_ids: 기준 사례와 선택 사례가 다릅니다.");
    value.provenance.forEach(item => {
      fields(item, {run_id: nonempty, case_criteria: value => ["same", "changed", "unknown"].includes(value), documents: object}, "provenance[]");
      Object.values(item.documents).forEach(document => fields(document, {
        original_sha256: nullableString, status: value => ["same", "changed", "unknown"].includes(value)}, "provenance[].documents[]"));
    });
  }
  function qualityBatch(value) {
    const boolean = item => typeof item === "boolean";
    const verdict = item => ["통과", "실패", "미판정", "비적용"].includes(item);
    const positive = item => integer(item) && item > 0;
    const hashes = item => object(item) && Object.values(item).every(string);
    fields(value, {schema_version: item => item === "output-evaluation-v1", id: nonempty,
      batch_id: nonempty, suite_id: nonempty, assessed_at: item => string(item) && Number.isFinite(Date.parse(item)),
      status: item => ["completed", "cancelled"].includes(item), method: item => ["rules", "all"].includes(item),
      criteria: object, criteria_sha256: string, evidence_sha256: hashes, evaluator_sha256: hashes,
      runs: Array.isArray, assessments: Array.isArray, summary: object, limitations: strings,
      provenance: Array.isArray, selection: object, judge_trace: object}, "output-evaluation");
    fields(value.criteria, {cases: Array.isArray, plan: object}, "quality.criteria");
    fields(value.criteria.plan, {case_ids: strings, repeat: positive}, "quality.criteria.plan");
    const ratio = item => item === null || nullableNumber(item) && item <= 1;
    fields(value.summary, {verdict, complete: boolean, planned_runs: integer, evaluated_runs: integer,
      passed: integer, failed: integer, undetermined: integer, not_applicable: integer,
      numerator: integer, denominator: integer, rate: ratio, checks: Array.isArray}, "quality.summary");
    value.summary.checks.forEach(item => fields(item, {check: nonempty, axis: string, method: string,
      passed: integer, failed: integer, undetermined: integer, not_applicable: integer, unexecuted: integer,
      numerator: integer, denominator: integer, rate: ratio}, "quality.summary.checks[]"));
    const cases = new Map();
    for (const item of value.criteria.cases) {
      caseFile(item);
      check(executionRun(item) && !cases.has(item.id), "quality.criteria.cases: 고유한 에이전트·보고서 사례가 필요합니다.");
      cases.set(item.id, item);
    }
    const runs = new Map(), runIds = new Set(), assessments = new Map();
    for (const run of value.runs) {
      fields(run, {run_id: item => item === null || nonempty(item), case_id: nonempty,
        repetition: positive, verdict, complete: boolean, reason: string, status: item => ["returned", "not_returned", "unknown"].includes(item),
        components: Array.isArray, issues: strings, connection_checks: Array.isArray, excluded_calls: Array.isArray}, "quality.runs[]");
      const key = JSON.stringify([run.case_id, run.repetition]);
      check(cases.has(run.case_id) && !runs.has(key) && (run.run_id === null || !runIds.has(run.run_id)), "quality.runs: 기준에 없거나 중복된 실행 판정입니다.");
      check(value.criteria.plan.case_ids.includes(run.case_id) && run.repetition <= value.criteria.plan.repeat, "quality.runs: 예정 사례·반복 범위를 벗어났습니다.");
      runs.set(key, run); if (run.run_id !== null) runIds.add(run.run_id);
    }
    const details = items => items.forEach(item => fields(item,
      {id: nonempty, verdict, reason: string, evidence: strings, executed: boolean}, "quality.details[]"));
    for (const item of value.assessments) {
      fields(item, {id: nonempty, node_id: nonempty, call_id: nonempty, call_index: positive, run_id: nullableString, case_id: nonempty,
        repetition: positive, node: name => targets.get("node").includes(name), role: name => roles.includes(name),
        counted: boolean, verdict, complete: boolean, reason: string, checks: Array.isArray}, "quality.assessments[]");
      const run = runs.get(JSON.stringify([item.case_id, item.repetition]));
      check(run && run.run_id === item.run_id && !assessments.has(item.id), "quality.assessments: 실행 연결이 다르거나 판정 ID가 중복되었습니다.");
      assessments.set(item.id, item);
      for (const result of item.checks) {
        fields(result, {check: nonempty, axis: string, method: string, executed: boolean, verdict,
          reason: string, details: Array.isArray, calls: Array.isArray, related_checks: strings}, "quality.checks[]");
        details(result.details);
        for (const call of result.calls) {
          fields(call, {id: nonempty, name: nonempty, index: positive, details: Array.isArray}, "quality.calls[]");
          check(call.id === item.call_id && call.index === item.call_index, "quality.calls: 선택한 작성 호출의 원본 ID·순서가 다릅니다.");
          details(call.details);
          optional(call, "judge", object, "quality.calls[]");
          optional(call, "format_contract", object, "quality.calls[]");
        }
      }
    }
    for (const run of runs.values()) {
      const ids = new Set();
      for (const component of run.components) {
        fields(component, {id: nonempty, role: name => roles.includes(name), kind: nonempty,
          paths: strings, value: () => true, result_id: nullableString, link_status: item => ["matched", "mismatch", "missing"].includes(item),
          issues: strings, assessment_ids: strings, verdict, complete: boolean, reason: string}, "quality.components[]");
        check(!ids.has(component.id), "quality.components: 중복 산출물 ID입니다."); ids.add(component.id);
        check(new Set(component.assessment_ids).size === component.assessment_ids.length, "quality.components: 중복 판정 참조입니다.");
        for (const id of component.assessment_ids) {
          const item = assessments.get(id);
          check(item && item.run_id === run.run_id && item.case_id === run.case_id && item.repetition === run.repetition && item.role === component.role,
            "quality.components: 산출물과 작성 호출 판정의 실행·역할이 다릅니다.");
        }
      }
    }
    trace(value.judge_trace);
  }
  const assessmentRuns = value => value.schema_version === "output-evaluation-v1"
    ? value.runs : [...value.runs, ...value.summary.operational.runs];
  const validateAssessment = value => value?.schema_version === "output-evaluation-v1" ? qualityBatch(value) : scoredBatch(value);

  function relativePath(value) {
    check(nonempty(value) && !/[\u0000-\u001f]/.test(value), "유효한 상대 파일 경로가 필요합니다.");
    const path = value.replace(/\\/g, "/");
    check(!path.startsWith("/") && !/^[A-Za-z]:/.test(path), "절대 파일 경로는 연결하지 않습니다.");
    const parts = path.split("/");
    check(parts.every(part => part && part !== "." && part !== ".."), "빈 경로·상위 경로 이동은 허용하지 않습니다.");
    return path;
  }

  /**
   * Parse already-read local files. Original records are retained verbatim as JSON
   * values, including unknown keys; Maps keep data keys from modifying prototypes.
   * This is a presentation adapter, not an evaluator or a substitute input validator.
   */
  function parseFiles(files) {
    const issues = [];
    const records = new Map();
    const cache = new Map();
    const batches = [];
    const claimed = new Set();
    function issue(code, path, message, owner, severity = "warning", line) {
      const item = { severity, code, path, message };
      if (line !== undefined) item.line = line;
      issues.push(item);
      if (owner) owner.issues.push(item);
      return item;
    }
    if (!Array.isArray(files)) return { batches, issues: [{ severity: "error", code: "invalid-files", path: "", message: "파일 목록이 필요합니다." }] };
    for (const file of files) {
      let path;
      try { path = relativePath(file && file.path); }
      catch (error) { issue("unsafe-path", string(file && file.path) ? file.path : "", error.message, null, "error"); continue; }
      if (records.has(path)) {
        records.set(path, { path, duplicate: true });
        issue("duplicate-path", path, "같은 상대 경로의 파일이 여러 개여서 어느 파일도 임의로 선택하지 않습니다.", null, "error");
      } else records.set(path, { path, text: file.text });
    }
    function read(path, kind, validate, owner) {
      const key = `${kind}:${path}`;
      if (cache.has(key)) {
        const cached = cache.get(key);
        if (owner) owner.issues.push(...cached.issues.filter(item => !owner.issues.includes(item)));
        return cached;
      }
      const result = { value: null, status: "missing", issues: [] };
      const record = records.get(path);
      function fail(code, message, status = "invalid") {
        result.status = status;
        result.issues.push(issue(code, path, message, owner, status === "missing" ? "warning" : "error"));
      }
      if (!record) fail("missing-file", "선택한 파일에 이 자료가 없습니다. 저장 중단 또는 부분 선택일 수 있습니다.", "missing");
      else if (record.duplicate) fail("duplicate-artifact", "상대 경로가 중복되어 자료를 연결하지 않았습니다.", "duplicate");
      else {
        try {
          check(string(record.text), "텍스트로 읽은 파일이 필요합니다.");
          const value = JSON.parse(record.text.replace(/^\uFEFF/, ""));
          validate(value);
          result.value = value;
          result.status = "loaded";
        } catch (error) { fail("invalid-artifact", `${kind}: ${error.message}`); }
      }
      cache.set(key, result);
      return result;
    }
    function journal(path, owner) {
      const record = records.get(path);
      const result = { value: [], status: "missing" };
      if (!record) { issue("missing-file", path, "누적 추적 파일이 선택되지 않았습니다. 보고서의 추적 스냅샷은 별도로 확인할 수 있습니다.", owner); return result; }
      if (record.duplicate) { result.status = "duplicate"; issue("duplicate-artifact", path, "상대 경로가 중복되어 누적 추적을 연결하지 않았습니다.", owner, "error"); return result; }
      if (!string(record.text)) { result.status = "invalid"; issue("invalid-artifact", path, "누적 추적 파일 텍스트가 필요합니다.", owner, "error"); return result; }
      result.status = "loaded";
      record.text.replace(/^\uFEFF/, "").split(/\r?\n/).forEach((line, index) => {
        if (!line.trim()) return;
        try {
          const item = JSON.parse(line);
          fields(item, { event: value => ["start", "update", "end"].includes(value), span: object }, "journal");
          span(item.span, "journal.span");
          result.value.push(item);
        } catch (error) {
          result.status = "partial";
          issue("invalid-journal-line", path, error.message, owner, "error", index + 1);
        }
      });
      return result;
    }
    function mismatch(run, property, path, message) {
      run[property] = property === "journal" ? [] : null;
      run.availability[property] = "mismatch";
      issue("identity-mismatch", path, message, run, "error");
    }
    function attachRun(batch, path, entry, supplied) {
      const run = { key: path, path, entry, report: null, case: null, caseSource: null,
        manifest: null, journal: [], availability: {}, issues: [] };
      const parsed = supplied || read(path, "report", runReport, run);
      run.report = parsed.value;
      run.availability.report = parsed.status;
      if (supplied) run.issues.push(...parsed.issues);
      const identity = run.report && run.report.run;
      if (identity && entry && [
        [identity.id, entry.run_id], [identity.case_id, entry.case_id], [identity.unit, entry.unit],
        [identity.target, entry.target], [identity.repetition, entry.repetition], [identity.suite_id, batch.report.suite_id],
      ].some(([left, right]) => left !== right)) mismatch(run, "report", path, "묶음 항목과 결과 보고서의 실행·사례·반복·대상·묶음 식별이 다릅니다.");
      if (identity && run.report && entry && identity.status !== entry.status) {
        issue("status-difference", path, "묶음과 결과의 실행 상태가 다릅니다. 저장 시점 차이일 수 있으므로 두 원본 상태를 유지합니다.", run);
      }
      const directory = dirname(path);
      const casePath = join(directory, "case.json");
      const caseData = read(casePath, "case", caseFile, run);
      run.case = caseData.value;
      run.availability.case = caseData.status;
      if (run.case) run.caseSource = "case";
      const expected = entry || (run.report && { case_id: run.report.run.case_id, unit: run.report.run.unit, target: run.report.run.target });
      if (run.case && expected && (run.case.id !== expected.case_id || run.case.unit !== expected.unit || run.case.target !== expected.target)) {
        mismatch(run, "case", casePath, "사례 파일의 사례 ID 또는 실행 대상이 결과의 식별과 다릅니다.");
        run.caseSource = null;
      }
      if (run.case && run.report) {
        const role = run.case.unit === "agent" ? run.case.target : (run.case.role || null);
        if (role !== run.report.run.role || (run.case.dependencies || "real") !== run.report.run.dependencies) {
          mismatch(run, "case", casePath, "사례 파일과 결과의 역할 또는 하위 호출 방식이 다릅니다.");
          run.caseSource = null;
        }
      }
      if (!run.case && caseData.status === "missing" && batch.suite && expected) {
        const candidate = batch.suite.cases.find(item => item.id === expected.case_id && item.unit === expected.unit && item.target === expected.target);
        const matchesRun = candidate && (!run.report ||
          (candidate.unit === "agent" ? candidate.target : candidate.role || null) === run.report.run.role &&
          (candidate.dependencies || "real") === run.report.run.dependencies);
        if (matchesRun) { run.case = candidate; run.caseSource = "suite"; }
        else if (candidate) issue("identity-mismatch", join(dirname(batch.path), "suite.json"), "입력 묶음의 사례 역할 또는 하위 호출 방식이 실행 결과와 달라 대체 입력으로 연결하지 않았습니다.", run, "error");
      }
      const manifestPath = join(directory, "manifest.json");
      const manifest = read(manifestPath, "manifest", manifestFile, run);
      run.manifest = manifest.value;
      run.availability.manifest = manifest.status;
      const suiteId = batch.report ? batch.report.suite_id : run.report && run.report.run.suite_id;
      if (run.manifest && run.manifest.evaluation.suite_id !== suiteId) mismatch(run, "manifest", manifestPath, "실행 조건의 입력 묶음 ID가 결과와 다릅니다.");
      const journalPath = join(directory, "trace.jsonl");
      const entries = journal(journalPath, run);
      run.journal = entries.value;
      run.availability.journal = entries.status;
      // A journal has no run ID; only its exact sibling location links it. When a
      // report exists, common span IDs must not disagree about call identity.
      if (run.report && run.journal.length) {
        const spans = new Map(run.report.trace.spans.map(item => [item.id, item]));
        if (run.journal.some(item => spans.has(item.span.id) && ["kind", "name", "parent_id", "sequence"].some(key => spans.get(item.span.id)[key] !== item.span[key]))) {
          mismatch(run, "journal", journalPath, "누적 추적과 보고서의 동일 호출 ID가 서로 다른 호출을 가리킵니다.");
        }
      }
      batch.runs.push(run);
      return run;
    }
    const batchPaths = [];
    const reportPaths = [];
    const assessmentPaths = [];
    for (const [path, record] of records) {
      const name = basename(path);
      if (name === "batch.json") batchPaths.push(path);
      else if (name === "report.json") reportPaths.push(path);
      else if (string(record.text) && /\.json$/i.test(name) && !artifactNames.has(name)) {
        try {
          const value = JSON.parse(record.text.replace(/^\uFEFF/, ""));
          if (object(value) && string(value.schema_version)) {
            if (value.schema_version.startsWith("evaluation-batch-")) batchPaths.push(path);
            else if (value.schema_version.startsWith("evaluation-run-")) reportPaths.push(path);
            else if (/^(execution|output)-evaluation-/.test(value.schema_version)) assessmentPaths.push(path);
          }
        } catch (_) {
          if (/(?:^|\/)assessments\//.test(path)) assessmentPaths.push(path);
        }
      }
    }
    const assessments = [...assessmentPaths.map(path => ({path, report: read(path, "execution-evaluation", validateAssessment, null).value})).filter(item => item.report)];
    for (const path of batchPaths) {
      const batch = { key: path, path, source: "batch", report: null, suite: null, runs: [], issues: [] };
      const parsed = read(path, "batch", batchReport, batch);
      if (!parsed.value) continue;
      batch.report = parsed.value;
      const directory = dirname(path);
      const suitePath = join(directory, "suite.json");
      batch.suite = read(suitePath, "suite", suiteFile, batch).value;
      if (batch.suite && batch.suite.id !== batch.report.suite_id) {
        batch.suite = null;
        issue("identity-mismatch", suitePath, "입력 스냅샷의 묶음 ID가 batch.suite_id와 다릅니다.", batch, "error");
      }
      const entries = [];
      const idCounts = new Map();
      const repetitionCounts = new Map();
      for (const entry of batch.report.runs) {
        try { batchEntry(entry); }
        catch (error) { issue("invalid-batch-entry", path, error.message, batch, "error"); continue; }
        const repetitionKey = JSON.stringify([entry.case_id, entry.repetition]);
        idCounts.set(entry.run_id, (idCounts.get(entry.run_id) || 0) + 1);
        repetitionCounts.set(repetitionKey, (repetitionCounts.get(repetitionKey) || 0) + 1);
        entries.push({ entry, repetitionKey });
      }
      for (const { entry, repetitionKey } of entries) {
        const reportPath = join(directory, relativePath(entry.path));
        claimed.add(reportPath);
        if (!executionRun(entry)) continue;
        if (idCounts.get(entry.run_id) > 1 || repetitionCounts.get(repetitionKey) > 1) {
          issue("duplicate-run", path, "중복된 실행 ID 또는 사례·반복 순번을 연결하지 않았습니다.", batch, "error");
          continue;
        }
        attachRun(batch, reportPath, entry);
      }
      batches.push(batch);
    }
    const standalone = new Map();
    for (const path of reportPaths) {
      if (claimed.has(path)) continue;
      const parsed = read(path, "report", runReport, null);
      if (!parsed.value) continue;
      if (!executionRun(parsed.value.run)) continue;
      const directory = dirname(path);
      const scope = /(?:^|\/)runs\/[^/]+$/.test(directory) ? dirname(dirname(directory)) : directory;
      const group = JSON.stringify([scope, parsed.value.run.suite_id]);
      if (!standalone.has(group)) {
        const batch = { key: `standalone:${group}`, path: scope, source: "standalone", report: null, suite: null, runs: [], issues: [] };
        standalone.set(group, { batch, candidates: [], idCounts: new Map() });
        batches.push(batch);
      }
      const candidateGroup = standalone.get(group);
      const id = parsed.value.run.id;
      candidateGroup.candidates.push({ path, parsed });
      candidateGroup.idCounts.set(id, (candidateGroup.idCounts.get(id) || 0) + 1);
    }
    for (const { batch, candidates, idCounts } of standalone.values()) {
      for (const { path, parsed } of candidates) {
        if (idCounts.get(parsed.value.run.id) > 1) {
          issue("duplicate-run", path, "같은 위치 묶음의 실행 ID가 중복되어 해당 ID의 모든 보고서를 연결하지 않았습니다.", batch, "error");
          continue;
        }
        attachRun(batch, path, null, parsed);
      }
    }
    // Scoring is a separate, immutable snapshot. Never replace raw run.assessment.
    for (const batch of batches) batch.assessments = [];
    // Readable IDs are unique within an output directory, so identify the source
    // batch before checking duplicates. A loose file still needs unambiguous evidence.
    const owners = new Map(assessments.map(record => {
      const a = record.report;
      const candidates = batches.filter(batch => batch.report?.id === a.batch_id);
      const nearby = candidates.filter(batch => record.path.startsWith(`${dirname(batch.path)}/assessments/`));
      if (nearby.length) return [record, nearby.length === 1 ? nearby[0] : null];
      if (candidates.length === 1) return [record, candidates[0]];
      const suites = candidates.filter(batch => batch.report.suite_id === a.suite_id);
      if (suites.length === 1) return [record, suites[0]];
      const ids = assessmentRuns(a).map(run => run.run_id).filter(Boolean);
      const matched = ids.length ? suites.filter(batch => ids.every(id => batch.report.runs.some(run => run.run_id === id))) : [];
      return [record, matched.length === 1 ? matched[0] : null];
    }));
    const detached = new Map();
    for (const record of assessments) {
      const a = record.report;
      let batch = owners.get(record);
      if (assessments.filter(other => other.report.id === a.id && other.report.batch_id === a.batch_id &&
          other.report.suite_id === a.suite_id && owners.get(other) === batch).length > 1) {
        issue("duplicate-assessment", record.path, "같은 묶음의 평가 ID가 중복되어 해당 평가 기록을 연결하지 않았습니다.", batch, "error");
        continue;
      }
      const candidates = batches.filter(item => item.report?.id === a.batch_id);
      if (candidates.length && (!batch || batch.report.suite_id !== a.suite_id)) {
        issue("assessment-mismatch", record.path, "평가 묶음 연결이 모호하거나 입력 묶음 ID가 달라 채점 기록을 연결하지 않았습니다.", batch, "error");
        continue;
      }
      if (batch && assessmentRuns(a).some(scored => {
        const run = batch.runs.find(r => (r.entry?.run_id || r.report?.run.id) === scored.run_id);
        const i = run?.entry || run?.report?.run;
        const input = a.criteria.cases.find(item => item.id === scored.case_id);
        return i && (i.case_id !== scored.case_id || i.repetition !== scored.repetition ||
          i.unit !== input.unit || i.target !== input.target ||
          (run.report && own(scored, "role") && scored.role !== null && run.report.run.role !== scored.role) ||
          (run.report && own(scored, "dependencies") && scored.dependencies !== "unknown" && run.report.run.dependencies !== scored.dependencies));
      })) {
        issue("assessment-mismatch", record.path, "동일 실행 ID의 사례·대상·역할·반복 순번이 달라 채점 기록을 연결하지 않았습니다.", batch, "error");
        continue;
      }
      if (!batch) {
        const key = JSON.stringify([a.batch_id, a.suite_id]);
        if (!detached.has(key)) {
          const group = {key: `assessment:${key}`, path: record.path, source: "assessment", report: null, suite: null, runs: [], issues: [], assessments: []};
          detached.set(key, group); batches.push(group);
        }
        batch = detached.get(key);
      }
      batch.assessments.push(record);
    }
    for (const batch of batches) batch.assessments.sort((a, b) => Date.parse(b.report.assessed_at) - Date.parse(a.report.assessed_at) || a.report.id.localeCompare(b.report.id));
    // Keep original mixed batch metadata; only the presentation run list is scoped.
    return { batches: batches.filter(batch => batch.runs.length > 0 || batch.assessments.length > 0 ||
      batch.suite?.cases.some(executionRun) || batch.report?.runs.some(executionRun)), issues };
  }
  return Object.freeze({ parseFiles });
});
