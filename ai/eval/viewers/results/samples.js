/* 화면 검토용 가상 파일. 실행기 결과 계약만 사용하며 채점 결과를 만들지 않는다.
 * 시각·소요 시간·해시·업무 결과도 예시이며 실제 실행 증거가 아니다.
 * sample 여부는 원본 파일에 넣지 않고 EvaluationSamples wrapper에만 둔다.
 */
(function (root) {
  "use strict";

  const copy = value => JSON.parse(JSON.stringify(value));
  const json = value => JSON.stringify(value, null, 2);
  const uuid = number => `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`;
  const started = "2026-11-09T00:00:00+00:00";
  const ended = "2026-11-09T00:00:02+00:00";
  const files = [];
  const add = (path, value) => files.push({ path, text: json(value) });
  const dataset = {
    reference: { id: "sample.activity", version: "sample-v1" },
    as_of: "2026-09",
    sources: [{ label: "가상 지역 활동 자료", uri: "fixture://sample/activity" }],
    columns: [
      { name: "region", kind: "string", unit: "지역 코드", spatial_unit: "district", temporal_unit: "month", denominator: "해당 없음" },
      { name: "value", kind: "number", unit: "지수", spatial_unit: "district", temporal_unit: "month", denominator: "동일 기준 인구" }
    ],
    rows: [{ region: "가상 A지역", value: 10 }, { region: "가상 B지역", value: 20 }]
  };
  const queryArguments = { target: "sample.activity" };
  const queryOutput = { data: dataset, applied: queryArguments, total: 2, returned: 2, next_offset: null };
  const initial = goal => ({ request: { goal }, event: "analysis_pipeline", messages: [] });
  const assessment = (checks, expected, required = true) => ({
    reference: { source: "fixture://sample/reference", description: "화면 검토용 독립 기준 자료" },
    expected, tolerance: { description: "이 가상 사례의 기대값을 검토하기 위한 예시이며 합격 기준이 아님" },
    checks, required
  });
  const result = (id, node, decision, reason, output = null, action = null, outcome = "success") => ({
    id, node, decision, reason, action, output, description: reason, outcome
  });
  const reply = (kind, content, artifacts = []) => ({ id: "sample-response", kind, label: "가상 응답", content, artifacts });
  const queryStub = { name: "query_data", arguments: queryArguments, output: queryOutput, uses: 1 };
  const cases = [
    {
      id: "tool-query", unit: "tool", target: "query_data", purpose: "[가상] 도구 단독 입출력과 State 없음 확인",
      arguments: queryArguments, providers: ["sample.activity"], tags: ["정상 조회", "가상"],
      assessment: assessment(["T-I.1", "T-O.1", "T-O.2", "T-O.5"], { returned: 2, rows: dataset.rows })
    },
    {
      id: "tool-query-error", unit: "tool", target: "query_data", purpose: "[가상] 미등록 자료 오류와 미판정 구분",
      arguments: { target: "not-registered" }, tags: ["오류 주입", "가상"],
      assessment: assessment(["T-I.1", "T-O.2"], { error_code: "reference_not_found" })
    },
    {
      id: "node-act-stub", unit: "node", target: "act", role: "interpretation", purpose: "[가상] 선택·호출·State 반영과 반복 실행 확인",
      initial: initial("가상 지역 활동 자료를 조회한다."), dependencies: "stub", stubs: [queryStub], tags: ["하위 모의 응답", "반복", "가상"],
      assessment: assessment(["N02-O.1", "N02-O.3", "N02-B.1"], { selected: "query_data", goto: "decide" })
    },
    {
      id: "node-act-unexpected", unit: "node", target: "act", role: "interpretation", purpose: "[가상] 예상 밖 모의 호출과 미사용 응답 확인",
      initial: initial("가상 자료 중 첫 행을 확인한다."), dependencies: "stub", stubs: [queryStub], tags: ["모의 응답 불일치", "가상"],
      assessment: assessment(["N02-O.3", "N02-B.4"], { prepared_arguments: queryArguments }, false)
    },
    {
      id: "selection-raw", unit: "selection", target: "act", role: "request", purpose: "[가상] 선택 결과의 인자 원문 보존과 하위 호출 없음 확인",
      initial: initial("가상 자료를 선택하되 호출하지 않는다."), tags: ["선택만", "가상"],
      assessment: assessment(["N02-O.1", "N02-O.3"], { selected: "query_data" })
    },
    {
      id: "agent-question", unit: "agent", target: "request", purpose: "[가상] 반환됨과 사용자 입력 대기 구분",
      initial: { ...initial("활동 자료를 알려줘."), event: "user_request", messages: [{ type: "human", content: "활동 자료를 알려줘.", id: "sample-human-1" }] },
      tags: ["되묻기", "가상"], assessment: assessment([], { response_kind: "question", asks_for: "지역" })
    },
    {
      id: "agent-failed", unit: "agent", target: "visualization", purpose: "[가상] 실행 반환과 업무 실패 상태 구분",
      initial: initial("등록되지 않은 시각화 조건을 적용한다."), tags: ["업무 실패", "가상"],
      assessment: assessment([], { response: "지원 범위와 부족한 입력 안내" }, false)
    },
    {
      id: "workflow-report-partial", unit: "workflow", target: "report", purpose: "[가상] 동별 보고서 일부 반환과 서비스 저장 미포함 확인",
      initial: {
        ...initial("가상 지역의 동별 보고서를 작성한다."),
        results: [
          result("sample-report-input", "report", "report_input", "가상 보고서 요청", { requestId: "sample-report", month: "2026-09", dongCodes: ["1168066000"], dongCode: "1168066000" }),
          result("sample-report-source", "report", "report_source", "가상 자료 기준 시점", { period_start: "2026-09-01", adm_cd10: "1168066000", updated_at: "2026-09-30T00:00:00" })
        ]
      },
      tags: ["부분 반환", "DB 저장 제외", "가상"], assessment: assessment([], { missing_report_fields: ["quick_insight"] })
    },
    {
      id: "node-compose-cancelled", unit: "node", target: "compose", role: "request", purpose: "[가상] 취소와 남아 있는 추적 기록 확인",
      initial: initial("확보한 가상 자료를 응답으로 작성한다."), tags: ["취소", "가상"], assessment: assessment([], { preserve_trace: true }, false)
    },
    {
      id: "agent-running", unit: "agent", target: "interpretation", purpose: "[가상] 실행 등록 후 report.json이 아직 없는 상태 확인",
      initial: initial("가상 지역 자료 해석을 진행한다."), tags: ["진행 중", "가상"], assessment: assessment([], { response_kind: "final" })
    }
  ];
  const suite = { schema_version: "evaluation-suite-v1", id: "viewer-synthetic-examples", datasets: { "sample.activity": dataset }, cases };
  const manifest = {
    version: "execution-manifest-v1", captured_at: started, git: { revision: null, dirty: null },
    content_sha256: "0".repeat(64), files_sha256: {}, settings: { version: "viewer-sample" },
    evaluation: { suite_id: suite.id, suite_sha256: "0".repeat(64), source: null, source_sha256: null, runner_sha256: {} }
  };
  const stateFor = (caseData, runId, options) => ({
    request: copy(caseData.initial.request), messages: copy(caseData.initial.messages),
    results: copy(options.results || caseData.initial.results || []), response: options.response || null,
    execution: {
      run_id: runId, event: caseData.initial.event, status: options.initialSnapshot ? "queued" : options.stateStatus || "running", version: "viewer-sample",
      budget: {
        steps: { used: options.initialSnapshot || caseData.unit === "selection" ? 0 : 1, limit: 30 },
        tool_calls: { used: (options.fixtures?.calls || []).length, limit: 20 },
        agent_calls: { used: 0, limit: 10 }, retries: { used: 0, limit: 3 },
        active_seconds: { used: options.initialSnapshot ? 0 : 2, limit: 120 }, final_model_calls: { used: 0, limit: 1 }, final_active_seconds: { used: 0, limit: 30 }
      },
      error: options.stateError || null
    }
  });
  const makeSpan = (id, kind, name, input, output, status = "success", error = null) => {
    const span = { id, parent_id: null, sequence: 1, kind, name, started_at: started, ended_at: ended, elapsed_seconds: 2, status, input };
    if (output !== undefined) span.output = output;
    if (error) span.error = error;
    return span;
  };
  function makeReport(caseData, runId, repetition, options = {}) {
    const runStatus = options.status || "returned";
    const state = caseData.initial ? stateFor(caseData, runId, options) : undefined;
    const output = options.output === undefined ? (caseData.unit === "node" && runStatus === "returned" ? { goto: "decide" } : null) : options.output;
    const traceFailure = options.failure?.type === "UnexpectedStubCall" && output !== null ? null : options.failure;
    const span = makeSpan(`${runId}-evaluation`, "evaluation", caseData.target,
      { unit: caseData.unit, role: caseData.unit === "agent" ? caseData.target : caseData.role || null, dependencies: caseData.dependencies || "real", initial_state: caseData.initial ? stateFor(caseData, runId, { initialSnapshot: true }) : null, arguments: caseData.arguments || null },
      traceFailure ? undefined : { output, state: state || null }, traceFailure ? "error" : "success", traceFailure);
    const report = {
      schema_version: "evaluation-run-v1",
      run: { id: runId, suite_id: suite.id, case_id: caseData.id, repetition, unit: caseData.unit, target: caseData.target,
        role: caseData.unit === "agent" ? caseData.target : caseData.role || null, dependencies: caseData.dependencies || "real",
        status: runStatus, started_at: started, ended_at: ended, elapsed_seconds: 2 },
      output, failure: options.failure || null,
      trace: {
        version: "local-execution-trace-v1", scope: "호출 직전 입력·반환값·노드 갱신의 로컬 스냅샷. State와 모델 컨텍스트에 재주입하지 않음.",
        limitations: ["모델 내부 계산·비공개 추론과 공급자 서버 내부 설정은 관측할 수 없다."],
        counts: { evaluation: 1 },
        coverage: { model_attempts: 0, model_inputs: 0, http_requests: 0, http_responses: 0, sdk_responses: 0, model_errors: 0, unfinished_spans: 0 },
        spans: [span]
      },
      assessment: { verdict: "미판정", executed: false, reason: "실행 증거만 수집함. 자동 채점은 수행하지 않음.", checks: caseData.assessment?.checks || [] },
      fixtures: options.fixtures || { calls: [], unexpected: [], unused: [] }, journal_saved: options.journalSaved !== false
    };
    if (state !== undefined) report.state = state;
    return report;
  }
  function writeReport(folder, caseData, report) {
    const runFolder = `${folder}/runs/${report.run.id}`;
    add(`${runFolder}/report.json`, report);
    add(`${runFolder}/case.json`, caseData);
    add(`${runFolder}/manifest.json`, manifest);
    if (report.journal_saved) files.push({ path: `${runFolder}/trace.jsonl`, text: report.trace.spans.map(span => JSON.stringify({ event: "end", span })).join("\n") + "\n" });
    return { case_id: caseData.id, run_id: report.run.id, unit: caseData.unit, target: caseData.target, repetition: report.run.repetition, status: report.run.status, path: `runs/${report.run.id}/report.json` };
  }
  function batch(number, reports, status, failure = null, planned = reports.length) {
    const names = {
      101: "통합평가_2026-11-09_실행01",
      102: "노드평가_2026-11-09_실행01",
      103: "노드평가_2026-11-09_실행02",
      104: "실행평가_2026-11-09_실행01",
      105: "도구평가_2026-11-09_실행01"
    };
    const batchId = names[number];
    const folder = `viewer-samples/${batchId}`;
    const entries = reports.map(({ caseData, report }) => writeReport(folder, caseData, report));
    const value = { schema_version: "evaluation-batch-v1", id: batchId, suite_id: suite.id, status, started_at: "2026-11-09T09:00:00+09:00", ended_at: status === "running" ? null : "2026-11-09T09:00:02+09:00", planned_runs: planned, runs: entries };
    if (failure) value.failure = failure;
    add(`${folder}/suite.json`, suite);
    add(`${folder}/batch.json`, value);
    return { folder, value };
  }
  const called = result("sample-call", "act", "call", "가상 모의 응답 수신", queryOutput, { name: "query_data", arguments: queryArguments });
  const selected = result("sample-selection", "act", "selection", "요청한 자료가 필요함", { name: "query_data", arguments_json: JSON.stringify(queryArguments), reason: "가상 자료 확인" });
  const matched = { calls: [{ name: "query_data", arguments: queryArguments, stub: 0 }], unexpected: [], unused: [] };
  const unexpectedArguments = { target: "sample.activity", limit: 1 };
  const unexpectedFailure = { type: "UnexpectedStubCall", code: "unexpected_stub_call" };
  const cancelled = { type: "CancelledError", code: null, http_status: null };
  const reportArtifact = { type: "analysis_report", data: {
    period_start: "2026-09-01", adm_cd10: "1168066000", result_updated_at: "2026-09-30T00:00:00", generated_at: started,
    quick_insight: null, graph_1: "EmbedDetailV01", desc_1: "가상 자료에서 확인한 범위의 설명", graph_2: null, desc_2: null, graph_3: null, desc_3: null
  } };
  const mainOptions = [
    { output: queryOutput },
    { status: "error", failure: { type: "ToolFailure", code: "reference_not_found", http_status: null, details: {}, retryable: false } },
    { output: { goto: "decide" }, results: [selected, called], fixtures: matched },
    { status: "error", output: { goto: "decide" }, failure: unexpectedFailure,
      results: [result("sample-unexpected-call", "act", "call", "준비된 응답과 호출 인자가 다름", { code: "unexpected_stub_call" }, { name: "query_data", arguments: unexpectedArguments }, "failure")],
      fixtures: { calls: [], unexpected: [{ name: "query_data", arguments: unexpectedArguments }], unused: [{ stub: 0, remaining: 1 }] } },
    { output: { name: "query_data", arguments_json: '{"target": "sample.activity", "limit":', reason: "선택 단계의 인자 원문은 도구 입력으로 해석하지 않음" }, results: [result("sample-raw-selection", "act", "selection", "가상 선택 결과", { name: "query_data", arguments_json: '{"target": "sample.activity", "limit":', reason: "원문 보존 예시" })] },
    { stateStatus: "waiting_input", response: reply("question", "어느 지역의 활동 자료를 확인할까요?"), results: [result("sample-question", "ask", "question", "지역 정보 필요", { content: "어느 지역을 확인할까요?" })] },
    { stateStatus: "failed", stateError: { code: "unsupported_visualization", cause: "가상 사례에 설정한 지원 범위 밖의 시각화 조건" }, response: reply("final", "현재 등록 조건으로 적용할 수 없습니다. 지역과 기간을 확인해 주세요."), results: [result("sample-failed", "compose", "compose", "지원 범위 안내", null, null, "failure")], journalSaved: false },
    { stateStatus: "partial", stateError: { code: "execution_limit_exceeded", cause: "가상 사례의 일반 실행 한도 도달" }, response: reply("final", "확보한 범위의 가상 동별 보고서를 반환합니다. DB 저장은 수행하지 않았습니다.", [reportArtifact]), results: [...cases[7].initial.results, result("sample-report-partial", "compose", "compose", "확보한 범위로 종료", { artifact: reportArtifact })] }
  ];
  batch(101, mainOptions.map((options, index) => ({ caseData: cases[index], report: makeReport(cases[index], uuid(index + 1), 1, options) })), "error");
  batch(102, [1, 2].map(repetition => ({ caseData: cases[2], report: makeReport(cases[2], uuid(20 + repetition), repetition, { output: { goto: "decide" }, results: [selected, called], fixtures: matched }) })), "returned");
  batch(103, [{ caseData: cases[8], report: makeReport(cases[8], uuid(30), 1, { status: "cancelled", stateStatus: "cancelled", failure: cancelled }) }], "cancelled", cancelled);

  // 실행기는 시작 직전에 batch에 등록하므로 report.json이 아직 없을 수 있다.
  const running = batch(104, [], "running", null, 2);
  const pendingId = uuid(40);
  running.value.runs.push({ case_id: cases[9].id, run_id: pendingId, unit: "agent", target: "interpretation", repetition: 1, status: "running", path: `runs/${pendingId}/report.json` });
  files.find(file => file.path === `${running.folder}/batch.json`).text = json(running.value);
  const pendingFolder = `${running.folder}/runs/${pendingId}`;
  add(`${pendingFolder}/case.json`, cases[9]);
  add(`${pendingFolder}/manifest.json`, manifest);
  const pendingSpan = makeSpan(`${pendingId}-evaluation`, "evaluation", "interpretation", { unit: "agent", role: "interpretation", dependencies: "real", initial_state: stateFor(cases[9], pendingId, { initialSnapshot: true }), arguments: null }, undefined, "running");
  Object.assign(pendingSpan, { ended_at: null, elapsed_seconds: null });
  files.push({ path: `${pendingFolder}/trace.jsonl`, text: JSON.stringify({ event: "start", span: pendingSpan }) + "\n" });

  // Separate, explicitly fictional scoring snapshots exercise the same importer.
  const scoredReports = cases.slice(0, 2).map((caseData, index) => ({caseData, report: makeReport(caseData, uuid(50 + index), 1, mainOptions[index])}));
  const scored = batch(105, scoredReports, "error");
  const check = (id, verdict, path, extra = {}) => ({check: id, target: path, executed: verdict !== "미판정", verdict,
    reason: `[가상] ${verdict} 근거 예시`, evidence: [path], ...extra});
  const caseSummary = (index, verdict, complete) => ({case_id: cases[index].id, required: true, verdict, complete,
    planned_repetitions: 1, recorded_repetitions: 1, missing_repetitions: [], undetermined_repetitions: complete ? [] : [1],
    checks: [], reasons: complete ? [] : ["[가상] 출처 검사 기준이 부족합니다."]});
  const sampleScore = {
    schema_version: "tool-evaluation-v1", id: `${scored.value.id}_채점02`, batch_id: scored.value.id, suite_id: suite.id,
    assessed_at: "2026-11-12T10:00:00+09:00", criteria: {suite_id: suite.id, cases: cases.slice(0, 2), plan: {case_ids: cases.slice(0, 2).map(c => c.id), repeat: 1}, performance: []},
    criteria_sha256: "sample-criteria-not-a-real-hash", evidence_sha256: {}, evaluator_sha256: {}, limitations: ["화면 검토용 가상 채점입니다."],
    runs: scoredReports.map(({caseData, report}, index) => ({run_id: report.run.id, case_id: caseData.id, target: "query_data", repetition: 1,
      executed: true, verdict: index ? "통과" : "실패", reason: index ? "[가상] 예상한 오류를 반환했습니다." : "[가상] 반환 건수가 기대와 다릅니다.",
      checks: index ? [check("T-O.2", "통과", "/failure/code", {expected: "reference_not_found", actual: "reference_not_found", match: "equal"})] : [
        check("T-I.1", "통과", "/output/applied/target", {expected: "sample.activity", actual: "sample.activity", match: "equal"}),
        check("T-O.1", "실패", "/output/returned", {expected: 3, actual: 2, match: "equal", tolerance: {absolute: 0}}),
        check("T-O.5", "미판정", ""), check("T-O.2", "비적용", "/failure", {expected: null, actual: null}),
      ]})),
    tools: [{target: "query_data", functional: {verdict: "실패", complete: false, numerator: 1, denominator: 2, rate: 0.5,
      completed_cases: 1, completed_passed_cases: 1, completed_failed_cases: 0, incomplete_cases: 1, passed_cases: 1,
      failed_cases: 1, missing_cases: 0, undetermined_cases: 1, unspecified_required_cases: 0, excluded_cases: 0,
      cases: [caseSummary(0, "실패", false), caseSummary(1, "통과", true)]},
      latency: {normal: {sample_count: 1, median_seconds: 0.012, p95_seconds: 0.012}, error: {sample_count: 1, median_seconds: 0.007, p95_seconds: 0.007},
        unfinished_count: 0, unfinished: [], conflicting_span_ids: [], invalid_measurements: 0, execution_limit_exceeded: 0, reasons: []},
      performance: ["normal", "error"].map((group, index) => ({group, case_ids: [cases[index].id], statistic: "p95", max_seconds: 0.01,
        environment: "가상 로컬 환경", data_size: "2행", sample_count: 1, value_seconds: index ? 0.007 : 0.012, verdict: index ? "통과" : "실패", complete: true, reasons: []}))}],
  };
  const earlier = copy(sampleScore);
  earlier.id = `${scored.value.id}_채점01`;
  earlier.assessed_at = "2026-11-11T10:00:00+09:00";
  earlier.runs[1].verdict = "실패";
  Object.assign(earlier.runs[1].checks[0], {verdict: "실패", expected: "different_expected_code", reason: "[가상] 이전 기대 오류 코드와 다릅니다."});
  Object.assign(earlier.tools[0].functional, {numerator: 0, rate: 0, passed_cases: 0, completed_passed_cases: 0, failed_cases: 2, completed_failed_cases: 1});
  earlier.tools[0].functional.cases[1].verdict = "실패";
  add(`${scored.folder}/assessments/${earlier.id}.json`, earlier);
  add(`${scored.folder}/assessments/${sampleScore.id}.json`, sampleScore);

  root.EvaluationSamples = {
    label: "화면 검토용 가상 기록 · 실제 실행·평가 결과 아님 (시각·소요 시간·해시 포함)",
    files
  };
})(typeof window === "undefined" ? globalThis : window);
