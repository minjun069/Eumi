/* Saved evaluation evidence only. This module never executes or grades. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.EvaluationData = api;
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
      if (run.unit === "node") fields(value.output, { goto: string }, "output");
      if (run.unit === "selection") fields(value.output, { name: string, arguments_json: string, reason: string }, "output");
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
    fields(value, {schema_version: item => item === "tool-evaluation-v1", id: nonempty,
      batch_id: nonempty, suite_id: nonempty, assessed_at: item => string(item) && Number.isFinite(Date.parse(item)),
      criteria: object, criteria_sha256: string, evidence_sha256: hashes, evaluator_sha256: hashes,
      runs: Array.isArray, tools: Array.isArray, limitations: strings}, "tool-evaluation");
    fields(value.criteria, {suite_id: item => item === value.suite_id, cases: Array.isArray, plan: object}, "criteria");
    fields(value.criteria.plan, {case_ids: strings, repeat: positive}, "criteria.plan");
    const caseIds = new Set();
    value.criteria.cases.forEach(item => {
      caseFile(item);
      check(!caseIds.has(item.id), "criteria.cases: 중복 사례 ID입니다.");
      caseIds.add(item.id);
    });
    const runKeys = new Set(), runIds = new Set();
    value.runs.forEach((run, index) => {
      const at = `runs[${index}]`;
      fields(run, {run_id: item => item === null || nonempty(item), case_id: nonempty, target: nonempty,
        repetition: positive, executed: boolean, verdict, reason: string, checks: Array.isArray}, at);
      const key = JSON.stringify([run.case_id, run.target, run.repetition]);
      check(!runKeys.has(key) && (run.run_id === null || !runIds.has(run.run_id)), `${at}: 중복 실행 판정입니다.`);
      runKeys.add(key); if (run.run_id !== null) runIds.add(run.run_id);
      run.checks.forEach((item, i) => {
        fields(item, {check: nonempty, target: string, executed: boolean, verdict, reason: string, evidence: strings}, `${at}.checks[${i}]`);
        optional(item, "match", mode => ["equal", "subset", "present", "absent"].includes(mode), at);
        if (own(item, "tolerance")) {
          check(object(item.tolerance), `${at}.tolerance: 객체가 필요합니다.`);
          for (const key of ["absolute", "relative"]) optional(item.tolerance, key, n => n !== null && nullableNumber(n), at);
        }
      });
    });
    const toolIds = new Set();
    value.tools.forEach(tool => {
      fields(tool, {target: nonempty, functional: object, latency: object, performance: Array.isArray}, "tools[]");
      check(!toolIds.has(tool.target), "tools: 중복 도구 지표입니다.");
      toolIds.add(tool.target);
      const f = tool.functional;
      fields(f, {verdict, complete: boolean, numerator: integer, denominator: integer,
        rate: n => n === null || (nullableNumber(n) && n <= 1), cases: Array.isArray,
        ...Object.fromEntries(["completed_cases", "completed_passed_cases", "completed_failed_cases", "incomplete_cases",
          "passed_cases", "failed_cases", "missing_cases", "undetermined_cases", "unspecified_required_cases", "excluded_cases"].map(k => [k, integer]))}, "functional");
      f.cases.forEach(item => {
        fields(item, {case_id: nonempty, required: n => n === null || boolean(n), verdict, complete: boolean,
          planned_repetitions: integer, recorded_repetitions: integer, missing_repetitions: integers,
          undetermined_repetitions: integers, checks: Array.isArray, reasons: strings}, "functional.cases[]");
        item.checks.forEach(c => fields(c, {check: nonempty, unexecuted: integer, undetermined: integer, reasons: strings}, "functional.cases[].checks[]"));
      });
      const l = tool.latency;
      fields(l, {normal: object, error: object, unfinished_count: integer, unfinished: Array.isArray,
        conflicting_span_ids: strings, invalid_measurements: integer, execution_limit_exceeded: integer, reasons: strings}, "latency");
      for (const group of ["normal", "error"]) fields(l[group], {sample_count: integer, median_seconds: nullableNumber, p95_seconds: nullableNumber}, `latency.${group}`);
      l.unfinished.forEach(item => fields(item, {span_id: nonempty, run_id: nullableString, case_id: nonempty,
        repetition: positive, elapsed_seconds: nullableNumber}, "latency.unfinished[]"));
      tool.performance.forEach(item => fields(item, {group: n => ["normal", "error"].includes(n), case_ids: strings,
        statistic: n => n === null || ["median", "p95"].includes(n), max_seconds: nullableNumber,
        environment: nullableString, data_size: nullableString, sample_count: integer,
        value_seconds: nullableNumber, verdict, complete: boolean, reasons: strings}, "performance[]"));
    });
  }
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
            else if (value.schema_version.startsWith("tool-evaluation-")) assessmentPaths.push(path);
          }
        } catch (_) {
          if (/(?:^|\/)assessments\//.test(path)) assessmentPaths.push(path);
        }
      }
    }
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
        if (idCounts.get(entry.run_id) > 1 || repetitionCounts.get(repetitionKey) > 1) {
          issue("duplicate-run", path, "중복된 실행 ID 또는 사례·반복 순번을 연결하지 않았습니다.", batch, "error");
          continue;
        }
        claimed.add(reportPath);
        attachRun(batch, reportPath, entry);
      }
      batches.push(batch);
    }
    const standalone = new Map();
    for (const path of reportPaths) {
      if (claimed.has(path)) continue;
      const parsed = read(path, "report", runReport, null);
      if (!parsed.value) continue;
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
    const assessments = [...assessmentPaths.map(path => ({path, report: read(path, "tool-evaluation", scoredBatch, null).value})).filter(item => item.report)];
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
      const ids = a.runs.map(run => run.run_id).filter(Boolean);
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
      if (batch && a.runs.some(scored => {
        const run = batch.runs.find(r => (r.entry?.run_id || r.report?.run.id) === scored.run_id);
        const i = run?.entry || run?.report?.run;
        return i && (i.case_id !== scored.case_id || i.target !== scored.target || i.repetition !== scored.repetition);
      })) {
        issue("assessment-mismatch", record.path, "동일 실행 ID의 사례·대상·반복 순번이 달라 채점 기록을 연결하지 않았습니다.", batch, "error");
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
    // Empty declared batches and score-only snapshots are valid loads.
    return { batches: batches.filter(batch => batch.source === "batch" || batch.runs.length > 0 || batch.assessments.length > 0), issues };
  }
  return Object.freeze({ parseFiles });
});
