/* UI state and rendering only. Artifact validation/linking lives in data.js.
 * Operational filters aggregate recorded run measurements without grading or persistence. */
(function () {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const has = (object, key) => object != null && Object.hasOwn(object, key);
  const text = (value) => value == null ? "미기록" : escape(value);
  const dateTime = value => text(EvaluationNames.dateTime(value));
  const statusNames = {
    running: "진행 중", returned: "반환됨", error: "실행 오류", cancelled: "취소됨",
    queued: "대기", completed: "완료", partial: "부분 완료", failed: "실패 종료", waiting_input: "질문 대기",
  };
  const targetNames = {
    request: "사용자 요청 처리",
    interpretation: "분석 결과 해석", visualization: "데이터 시각화", report: "대시보드 보고서 생성",
    report_selection: "보고서 시각화 선정", report_description: "보고서 시각화 설명", report_insight: "보고서 퀵 인사이트",
  };
  const checkNames = {
    "EX-1": "노드 간 전이", "EX-2": "노드 간 상태 전달", "EX-3": "공유 예산 유지",
    "EX-4": "중단과 종료 경로", "EX-5": "최종 반환 경계", "EX-R1": "보고서 역할 순서",
    "EX-R2": "역할 입력 전달", "EX-R3": "재진입 역할", "EX-R4": "보고서 항목 구성", "EX-R5": "보고서 완성 상태",
  };
  const outcomeNames = {completed: "완료", partial: "부분 완료", question: "질문 반환", refusal: "거부 반환", no_data: "자료 없음", technical_failure: "기술적 실패", cancelled: "취소", unfinished: "미종료", evaluation_failure: "평가 증거 오류", unclassified: "미분류", not_started: "미실행"};
  const measureNames = {elapsed_seconds: "전체 실행 시간", model_calls: "모델 호출 수", tool_calls: "도구 호출 수", agent_calls: "하위 에이전트 호출 수", node_entries: "노드 진입 수", retries: "재시도 수", input_tokens: "입력 토큰", output_tokens: "출력 토큰", cost: "실행 비용"};
  const conditionNames = {dependencies: "실제·모의 호출", situation: "실행 상황", entry: "진입 방식", environment: "실행 환경", data_size: "입력 규모"};
  const conditionValues = {real: "실제 하위 호출", stub: "모의 하위 응답", normal: "정상", data_shortage: "자료 부족", fault: "오류·재시도", limit_cancel: "한도·취소", initial: "최초 진입", reentry: "재진입"};
  const ui = {
    catalog: null, batch: 0, target: "all", caseKey: null, runKey: null,
    page: "cases", detail: "assessment", aggregate: "functional", scenarioOpen: false, query: "", status: "all", tag: "all",
    required: "all", pageNumber: 0, sample: false, loading: false,
    assessmentKey: null, qualityKey: null, operationalAgent: null, operationalFilters: {},
  };
  let downloads = [];
  const PAGE_SIZE = 25;
  const detailTabs = [["assessment", "기능지표"], ["quality", "최종 출력 품질"], ["operational", "운영지표"], ["io", "입출력"]];
  const aggregateTabs = [["functional", "기능지표"], ["quality", "최종 출력 품질"], ["operational", "운영지표"]];
  const qualityRecord = record => (record?.report.schema_version || record?.ref?.report_schema_version) === "output-evaluation-v1";
  const viewerSchema = schema => ["execution-evaluation-v1", "output-evaluation-v1"].includes(schema);

  // These disclosures and pane choices are presentation state only.
  const mobileLayout = globalThis.matchMedia?.("(max-width: 760px)");
  function syncDisclosures() {
    if (!mobileLayout) return;
    $("#case-filters").open = false;
    $("#case-list-picker").open = !mobileLayout.matches;
    $("#assessment-controls").open = !mobileLayout.matches;
  }
  mobileLayout?.addEventListener("change", syncDisclosures);
  syncDisclosures();

  function focusPane(selector) {
    const pane = $(selector);
    pane.focus({preventScroll: true});
    pane.scrollIntoView({block: "start"});
  }

  function info(run) {
    if (run.report) return run.report.run;
    const entry = run.entry || {};
    const prepared = run.case || {};
    return {
      ...entry, id: entry.run_id, case_id: entry.case_id || prepared.id,
      unit: entry.unit || prepared.unit, target: entry.target || prepared.target,
      role: entry.role ?? (entry.unit === "agent" ? entry.target : prepared.unit === "agent" ? prepared.target : prepared.role),
      dependencies: entry.unit === "tool" ? "real" : entry.dependencies ?? (run.case ? prepared.dependencies || "real" : null),
    };
  }

  const executionKey = (unit, target) => JSON.stringify([unit, target]);
  function targetKey(run) { const i = info(run); return executionKey(i.unit, i.target); }
  function functionalTarget(i) { return (i.unit === "agent" && i.target === "request") || (i.unit === "workflow" && i.target === "report"); }
  function criteriaCase(id) { return currentAssessment()?.report.criteria?.cases.find(c => c.id === id); }
  function inScopeCase(id) { const c = criteriaCase(id) || currentBatch()?.runs.map(info).find(run => run.case_id === id); return ui.target === "all" || (c && executionKey(c.unit, c.target) === ui.target); }
  function measurement(run, record = currentAssessment()) {
    const i = info(run);
    return record?.report.summary?.operational.runs.find(r => r.run_id === i.id && r.case_id === i.case_id && r.repetition === i.repetition);
  }
  function appliedChecks(run) {
    return run.report ? run.report.assessment.checks : run.case?.assessment?.checks || [];
  }
  function definition(id) {
    return {category: id.startsWith("EX-R") ? "보고서 생성 흐름" : id.startsWith("EX-") ? "공통 실행 규칙" : "미등록", name: checkNames[id]};
  }
  function time(value) {
    return value == null ? "미기록" : `${escape(value)}초`;
  }

  function badge(value) {
    const tone = ["error", "failed", "실패"].includes(value) ? "error" : value === "통과" ? "pass" : value === "미판정" || value === "running" ? "pending" : "";
    return `<span class="chip ${tone}">${text(statusNames[value] || value)}</span>`;
  }

  function facts(entries) {
    return `<dl class="facts">${entries.map(([name, value]) => `<dt>${escape(name)}</dt><dd>${value}</dd>`).join("")}</dl>`;
  }

  function downloadButton(value, name, label = "원본 내려받기", jsonl = false) {
    const key = downloads.push({value, name, jsonl}) - 1;
    return `<button type="button" data-download="${key}">${escape(label)}</button>`;
  }

  function raw(label, value, open = false, filename = "evidence.json") {
    if (value === undefined) return `<div class="section"><h3>${escape(label)}</h3><p class="hint">파일에 제공되지 않았습니다.</p></div>`;
    const original = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    const shortened = original.length > 24000;
    return `<details class="raw"${open ? " open" : ""}><summary>${escape(label)}</summary>
      <div class="raw-tools">${downloadButton(value, filename, "원본 내려받기", filename.endsWith(".jsonl"))}</div>
      <pre>${escape(shortened ? original.slice(0, 24000) : original)}</pre>
      ${shortened ? '<p class="hint">긴 원문은 앞부분만 표시합니다. 내려받기로 전체 내용을 확인할 수 있습니다.</p>' : ""}</details>`;
  }

  function currentBatch() { return ui.catalog?.batches[ui.batch]; }
  const assessmentName = record => EvaluationNames.assessmentName(record, currentBatch(), ui.catalog?.batches);
  const assessmentFilename = record => EvaluationNames.assessmentFilename(record, currentBatch(), ui.catalog?.batches);
  const assessmentOption = record => `채점 ${assessmentFilename(record).match(/_채점(\d+)\.json$/)[1]}`;
  function recordLocation(record) {
    const storage = record.report.judge_trace ? raw("평가 모델 전체 추적", record.report.judge_trace, false, "judge-trace.json") : "";
    return `<details class="section"><summary>저장 위치</summary><code>${text(record.path)}</code></details>${storage}${EvaluationNames.legacy(record) ? '<p class="hint">기존 기록의 표시 순번은 불러온 자료의 시간순입니다. 저장된 파일과 원본 내용은 유지하며 내려받기에는 표시 이름을 사용합니다.</p>' : ""}`;
  }


  function currentAssessment() {
    const records = (currentBatch()?.assessments || []).filter(record => !qualityRecord(record));
    return records.find(item => item.path === ui.assessmentKey) || records[0];
  }
  function currentQuality() {
    const records = (currentBatch()?.assessments || []).filter(qualityRecord);
    return records.find(item => item.path === ui.qualityKey) || records[0];
  }

  function scoredRun(run, record = currentAssessment()) {
    const i = info(run);
    return record?.report.runs?.find(a => a.run_id === i.id && a.case_id === i.case_id && a.repetition === i.repetition);
  }

  function assessmentPicker() {
    return [["assessment-select", "실행 기능·운영 채점 기록", currentAssessment(), false], ["quality-select", "최종 출력 품질 채점 기록", currentQuality(), true]].map(([id, label, selected, quality]) => {
      const records = (currentBatch()?.assessments || []).filter(record => qualityRecord(record) === quality);
      return `<label class="assessment-picker">${label}<select id="${id}" ${records.length ? "" : "disabled"}>${records.length ? records.map(item => `<option value="${escape(item.path)}"${item === selected ? " selected" : ""}>${assessmentOption(item)}</option>`).join("") : '<option>채점 파일 미제공</option>'}</select></label>`;
    }).join("");
  }

  function qualityCheckView(result, assessment) {
    const detail = item => `<section class="detail-result"><h5>${text(item.id)} · ${badge(item.verdict)}</h5>${facts([["검사 수행", item.executed ? "실행" : "미실행"], ["판정 사유", text(item.reason)], ["근거 경로", (item.evidence || []).map(text).join("<br>") || "미제공"]])}</section>`;
    return `<details class="evidence-item"><summary>${text(result.check)} · ${text(result.axis)} · ${text(result.method)} ${badge(result.verdict)}</summary>
      ${facts([["원본 노드 ID", text(assessment.node_id)], ["역할·노드", text(assessment.role + " / " + assessment.node)], ["검사 수행", result.executed ? "실행" : "미실행"], ["판정 사유", text(result.reason)]])}
      ${(result.details || []).map(detail).join("")}
      ${(result.calls || []).map(call => `<section class="model-assessment"><h4>작성 모델 호출 ${call.index} · ${text(call.name)}</h4><p>호출 ID: ${text(call.id)} · 기준 행: ${text(call.row_id)}</p>${(call.details || []).map(detail).join("")}
        ${has(call, "format_contract") ? raw("출력 형식 기준", call.format_contract) : ""}
        ${call.judge ? `<p class="hint">평가 모델 ${call.judge.executed === false ? "미실행" : call.judge.executed ? "호출 시도" : "호출 여부 미기록"} · 원응답과 검증한 판정을 구분합니다.</p>
          ${raw("평가 모델 전송 메시지", call.judge.prompt?.messages, false, "judge-messages.json")}${raw("평가 모델 원응답", call.judge.raw_response, false, "judge-raw-response.json")}${raw("평가 모델 판정·근거 전체", call.judge, false, "judge.json")}` : '<p class="hint">평가 모델 호출 기록 없음</p>'}</section>`).join("")}
    </details>`;
  }

  function qualityView(run = null) {
    const record = currentQuality();
    if (!record) return '<section class="empty"><h3>최종 출력 품질 미제공</h3><p>별도의 출력 품질 채점 결과를 함께 열면 확인할 수 있습니다. 실행 기능 통과와 품질 통과는 서로 다른 판정입니다.</p></section>';
    if (record.loadError) return readProblems(record);
    const value = record.report, identity = run ? info(run) : null;
    const runs = (value.runs || []).filter(item => identity
      ? item.run_id === identity.id && item.case_id === identity.case_id && item.repetition === identity.repetition
      : ui.target === "all" || value.criteria?.cases?.some(c => c.id === item.case_id && executionKey(c.unit, c.target) === ui.target) ||
        currentBatch()?.runs.some(r => info(r).case_id === item.case_id && targetKey(r) === ui.target));
    const summary = value.summary || {};
    const kindNames = {response: "최종 응답", artifacts: "반환 산출물", report_selection: "보고서 항목 선정", report_description: "보고서 설명", report_insight: "보고서 인사이트"};
    const linkNames = {matched: "연결 확인", mismatch: "연결 불일치", missing: "작성 원문 미제공"};
    const returnNames = {returned: "반환됨", not_returned: "반환되지 않음", unknown: "확인 불가"};
    let output = `<section class="section"><h3>최종 출력 품질 · ${text(assessmentName(record))}</h3>${facts([["채점 일시", dateTime(value.assessed_at)], ["채점 방식", text(value.method)], ["평가 모델", text(value.judge_model)]])}<p class="hint">실제로 반환한 최종 출력의 작성 호출을 평가합니다. 실행 연결 검사와 운영 합격에 합산하지 않습니다.</p>${recordLocation(record)}`;
    if (!identity) output += `<h4>채점 기록 전체의 저장 집계</h4>${facts([["품질 판정", badge(summary.verdict)], ["검증 완료", summary.complete ? "완료" : "미완료"], ["통과 / 판정 실행", (summary.numerator ?? "미기록") + " / " + (summary.denominator ?? "미기록")], ["통과율", rate(summary.rate)], ["계획 / 평가 실행", (summary.planned_runs ?? "미기록") + " / " + (summary.evaluated_runs ?? "미기록")], ["통과 / 실패 / 미판정 / 비적용 실행", [summary.passed, summary.failed, summary.undetermined, summary.not_applicable].map(item => item ?? "미기록").join(" / ")]])}${raw("품질 검사별 저장 지표", summary.checks)}`;
    output += runs.map(item => `<section class="case-section"><h4>${text(item.case_id)} · ${text(item.repetition)}회차 ${badge(item.verdict)}</h4>${facts([["반환 관측", text(returnNames[item.status] || item.status)], ["검증 완료", item.complete ? "완료" : "미완료"]])}<p>${text(item.reason)}</p>${reasonsView(item.issues)}
      ${item.components.map(component => `<section class="section"><h4>${text(kindNames[component.kind] || component.kind)} · ${text(component.role)} ${badge(component.verdict)}</h4>${facts([["검증 완료", component.complete ? "완료" : "미완료"], ["작성 호출 연결", text(linkNames[component.link_status] || component.link_status)], ["원본 결과 ID", text(component.result_id)], ["최종 출력 위치", component.paths.map(text).join("<br>")]])}<p>${text(component.reason)}</p>${reasonsView(component.issues)}${raw("반환한 출력 원문", component.value)}
        ${(value.assessments || []).filter(a => component.assessment_ids.includes(a.id)).map(a => `<p>작성 판정: ${text(a.id)} · 노드 ${text(a.node_id)} · ${text(a.role)}</p>${(a.checks || []).map(check => qualityCheckView(check, a)).join("")}`).join("")}</section>`).join("")}
      ${raw("최종 출력 연결 확인", item.connection_checks)}${raw("제외한 작성·검토 호출", item.excluded_calls)}</section>`).join("") || '<p class="hint">선택한 실행의 품질 판정이 없습니다.</p>';
    output += readProblems(record) + raw("품질 평가 기준·원본", value.criteria) + (record.partial ? "" : raw("품질 평가 전체", value, false, assessmentFilename(record)));
    return output + "</section>";
  }

  function reasonsView(reasons = []) {
    return reasons.length ? `<ul class="assessment-reasons">${reasons.map(reason => `<li>${text(reason)}</li>`).join("")}</ul>` : "";
  }
  const rate = value => value == null ? "산출 불가" : `${Number((value * 100).toFixed(2))}%`;
  const ratio = r => `${rate(r.rate)} · ${r.numerator} / ${r.denominator}`;
  function metricTable(rows) {
    return `<div class="table-scroll"><table class="assessment-table"><thead><tr><th>검사</th><th>통과율</th><th>통과</th><th>실패</th><th>미판정</th><th>비적용</th><th>미실행</th></tr></thead><tbody>${rows.map(r => `<tr><td>${text(r.check)}<br>${text(definition(r.check).name)}${reasonsView(r.reasons)}</td><td>${rate(r.rate)}<br>${r.numerator} / ${r.denominator}</td>${["passed", "failed", "undetermined", "not_applicable", "unexecuted"].map(key => `<td>${text(r[key])}</td>`).join("")}</tr>`).join("") || '<tr><td colspan="7">저장된 지표가 없습니다.</td></tr>'}</tbody></table></div>`;
  }
  function functionalView(f) {
    const c = f.cases, v = f.verification;
    const items = c.items.filter(i => inScopeCase(i.case_id));
    return `<div class="summary-cards"><div class="summary-card"><span>필수 사례 통과율</span><strong>${rate(c.rate)}</strong><span>통과 ${c.numerator} / 분모 ${c.denominator}사례</span></div><div class="summary-card"><span>기능 합격 여부</span><strong>${badge(f.verdict)}</strong><span>${f.complete ? "검증 완료" : "검증 미완료"}</span></div><div class="summary-card"><span>필수 사례 완료 / 미완료</span><strong>${v.completed_cases} / ${v.incomplete_cases}</strong><span>전체 필수 ${v.required_cases} · 누락 반복 ${v.missing_repetitions}</span></div></div>
      <div class="functional-case-counts">${facts([["통과 / 실패 / 미판정 사례", `${c.passed} / ${c.failed} / ${c.undetermined}`], ["선택 사례 / 필수 여부 미지정", `${c.excluded} / ${c.unspecified_required}`]])}</div>
      <details class="section"><summary>선택 범위의 사례별 판정·반복 충족 (${items.length}사례)</summary><div class="table-scroll"><table class="assessment-table"><thead><tr><th>사례</th><th>필수 여부</th><th>판정·완료</th><th>기록 / 예정 반복</th><th>미완료 사유</th></tr></thead><tbody>${items.map(i => `<tr><td>${text(i.case_id)}</td><td>${i.required === true ? "필수" : i.required === false ? "선택" : "미지정"}</td><td>${badge(i.verdict)} · ${i.complete ? "완료" : "미완료"}</td><td>${i.recorded_repetitions} / ${i.planned_repetitions}</td><td>누락: ${text(i.missing_repetitions.join(", ") || "없음")}<br>미완료: ${text(i.incomplete_repetitions.join(", ") || "없음")}${reasonsView(i.reasons)}</td></tr>`).join("")}</tbody></table></div></details>
      <h4>검사 항목별 통과율 · 채점 기록 전체</h4><p class="hint">실행 1회당 검사 ID별 판정 집계입니다. 미실행 건수는 미판정 등과 겹칠 수 있습니다.</p>${metricTable(f.checks)}`;
  }
  function statisticsTable(measurements, outcomes = false) {
    return `<div class="table-scroll"><table class="assessment-table"><thead><tr><th>측정 대상</th><th>표본</th><th>누락</th><th>평균</th><th>중앙값</th><th>p95</th><th>최솟값</th><th>최댓값</th></tr></thead><tbody>${Object.entries(measurements).map(([key, m]) => {
      const value = n => { const shown = typeof n === "number" ? Number(n.toPrecision(7)) : n; return key === "elapsed_seconds" || outcomes ? time(shown) : text(shown); };
      return `<tr><td>${text(outcomes ? outcomeNames[key] || key : measureNames[key] || key)}</td><td>${m.sample_count}</td><td>${m.missing_count}</td>${[m.mean,m.median,m.p95,m.minimum,m.maximum].map(n => `<td>${value(n)}</td>`).join("")}</tr>`;
    }).join("")}</tbody></table></div>`;
  }
  function measurementView(r) {
    const run = currentBatch().runs.find(x => info(x).id === r.run_id && info(x).case_id === r.case_id && info(x).repetition === r.repetition);
    return `<details class="section"><summary>${text(r.case_id)} · ${r.repetition}회차 · ${text(outcomeNames[r.outcome] || r.outcome)}</summary>
      <p>${run ? `<button type="button" class="link-button" data-open-run="${escape(run.key)}">실행 입출력 확인 ↗</button>` : r.run_id ? `실행 원본 미제공 · ${text(r.run_id)}` : "계획된 실행 · 실행 ID 없음"}</p>
      ${facts([["실행 ID", text(r.run_id)], ["대상", text(targetNames[r.target] || r.target)], ["대상 지역", text(r.dong_code)], ["대상 기간", text(r.month)], ...ExecutionOperational.FILTER_KEYS.map(key => [conditionNames[key], text(conditionValues[r[key]] || r[key])]), ["시작 / 종료 / 반환", `${r.started ? "시작" : "미시작"} / ${r.ended ? "종료" : "미종료"} / ${r.returned ? "반환" : "미반환"}`], ["증거 수집", r.evidence_complete ? "완전" : "불완전"], ["반환 상태", text(statusNames[r.returned_status] || r.returned_status)], ["관측 종료 시각", dateTime(r.observed_at)], ["시간 측정 범위", text(r.timing_scope)], ...Object.keys(measureNames).map(key => [measureNames[key], key === "elapsed_seconds" ? time(r[key]) : key === "cost" && r.cost == null ? "산출 불가" : text(r[key])]), ["비용 통화", text(r.currency)], ["모델 / 도구 비용", `${text(r.model_cost)} / ${text(r.tool_cost)}`]])}
      ${reasonsView(r.reasons)}${raw("진입 이후 예산 증가분·관측 호출·오류·토큰 누락", {budget_delta:r.budget_delta, observed_calls:r.observed_calls, failed_calls:r.failed_calls, observed_tokens:r.observed_tokens, missing_token_calls:r.missing_token_calls})}${raw("실행별 운영 측정 원문", r)}</details>`;
  }
  function operationalAgents() {
    const a = currentAssessment()?.report, o = a?.summary?.operational;
    return ExecutionOperational.agents([
      ...(o?.runs || []), ...(a?.criteria?.cases || []), ...(currentBatch()?.runs || []).map(info),
      ...(o?.goals || []).map(goal => ({unit: goal.target === "report" ? "workflow" : "agent", target: goal.target})),
    ].filter(item => item.unit === "agent" || item.unit === "workflow"));
  }
  function operationalView(o) {
    const agents = operationalAgents();
    if (!agents.some(agent => agent.key === ui.operationalAgent)) {
      ui.operationalAgent = agents.find(agent => agent.key === ui.target)?.key || agents[0]?.key || null;
      ui.operationalFilters = {};
    }
    const agent = agents.find(item => item.key === ui.operationalAgent);
    const population = agent ? ExecutionOperational.select(o.runs, agent.key, {}) : [];
    const selected = agent ? ExecutionOperational.select(population, agent.key, ui.operationalFilters) : [];
    const g = ExecutionOperational.summarize(selected);
    const filtered = Object.values(ui.operationalFilters).some(values => values.length);
    const caseIds = [...new Set(selected.map(r => r.case_id))];
    const a = currentAssessment().report;
    return `<h3>운영 지표</h3>
      <div class="operational-agents" role="tablist" aria-label="운영지표 에이전트 종류">${agents.map((item, index) => `<button type="button" role="tab" id="operational-agent-${index}" data-operational-agent="${escape(item.key)}" aria-selected="${item === agent}" aria-controls="operational-selection" tabindex="${item === agent ? 0 : -1}">${text(targetNames[item.target] || item.target)}</button>`).join("")}</div>
      ${agent ? `<section id="operational-selection" role="tabpanel" tabindex="-1" aria-labelledby="operational-agent-${agents.indexOf(agent)}">
        <div class="operational-filters"><div class="operational-filter-heading"><strong>실행 조건</strong><button type="button" id="operational-clear" class="link-button" data-clear-operational ${filtered ? "" : "disabled"}>선택 초기화</button></div>
          <p class="hint">묶음 안에서는 하나라도 일치(OR), 묶음 간에는 모두 일치(AND). 선택하지 않은 묶음은 전체를 포함합니다.</p>
          ${ExecutionOperational.FILTER_KEYS.map(key => `<fieldset class="operational-filter"><legend>${conditionNames[key]}</legend><div class="operational-chips">${ExecutionOperational.options(population,key).map((value,index) => {
            const active = (ui.operationalFilters[key] || []).includes(value);
            return `<button type="button" class="condition-chip" id="operational-filter-${key}-${index}" data-operational-filter="${key}" data-condition-value="${escape(JSON.stringify(value))}" data-condition-index="${index}" aria-pressed="${active}"><span class="condition-check" aria-hidden="true">${active ? "✓" : "+"}</span>${text(conditionValues[value] || (value === "" ? "빈 값" : value))}</button>`;
          }).join("")}</div></fieldset>`).join("")}
        </div>
        <div class="operational-result-heading"><h4>${filtered ? "선택 조건의 통계" : "에이전트 전체 통계"}</h4><span role="status" aria-live="polite">${selected.length} / ${population.length}회 선택</span></div>
        <div class="summary-cards operational-cards"><div class="summary-card"><span>시작 / 종료 / 미종료</span><strong>${g.started} / ${g.ended} / ${g.unfinished}</strong></div><div class="summary-card"><span>기술적 실패율</span><strong>${rate(g.failure_rate.rate)}</strong><span>${g.failure_rate.numerator} / ${g.failure_rate.denominator}회</span></div><div class="summary-card"><span>미분류 / 평가 증거 오류</span><strong>${g.failure_rate.unclassified_count} / ${g.failure_rate.evaluation_failure_count}</strong></div></div>
        ${selected.length ? "" : '<p class="empty operational-empty">선택한 조건에 해당하는 실행이 없습니다. 조건을 해제해 범위를 넓혀보세요.</p>'}
        <h4>시간·호출량·토큰·비용</h4>${statisticsTable(g.measurements)}
        <p class="hint">종료한 개별 실행의 측정값으로 집계하며 평가 증거 오류는 제외합니다. 누락은 0으로 대체하지 않습니다. p95는 정렬한 표본의 상위 95% 위치 값입니다.</p>
        <details class="section"><summary>종료 결과 분포·결과별 시간</summary>${facts(Object.entries(g.outcomes).map(([key,r]) => [outcomeNames[key] || key, ratio(r)]))}${statisticsTable(g.elapsed_by_outcome, true)}</details>
        <details class="section"><summary>사례별 반복 결과 (${caseIds.length}사례 · ${selected.length}회)</summary>${caseIds.map(id => {
          const runs = selected.filter(r => r.case_id === id), stats = ExecutionOperational.summarize(runs), plan = o.repetitions.find(r => r.case_id === id);
          return `<details class="section"><summary>${text(id)} · 선택 ${runs.length}회 / 종료 ${stats.ended}회</summary>${plan ? facts([["사례 전체 계획", `${plan.planned}회`], ["사례 전체의 누락 반복", text(plan.missing_repetitions.join(", ") || "없음")]]) : ""}${statisticsTable(stats.measurements)}${runs.map(measurementView).join("")}</details>`;
        }).join("")}</details>
        <details class="section"><summary>미종료 실행의 관측 사용량</summary>${selected.filter(r => r.started && !r.ended).map(measurementView).join("") || '<p class="hint">미종료 사용량 기록 없음</p>'}</details>
      </section>` : '<p class="empty">기록된 실행 측정값이 없습니다.</p>'}
      <details class="section"><summary>운영 목표 충족 여부 · 저장된 판정</summary><p class="hint">시험 당시 정한 조건으로 판정한 결과입니다. 위 조건 선택은 저장된 합격 판정을 바꾸지 않습니다.</p>
        ${facts([["운영 합격 여부 · 채점 기록 전체", badge(o.verdict)], ["운영 검증 완료", o.complete ? "완료" : "미완료"], ["비용 통화 / 단가 버전", a.criteria ? `${text(a.criteria.execution_prices?.currency)} / ${text(a.criteria.execution_prices?.version)}` : "기준 원문 읽기 오류"]])}${reasonsView(o.reasons)}
        ${o.goals.map((goal,index) => ({goal,index})).filter(({goal}) => goal.target === agent?.target).map(({goal,index}) => goalView(goal,a.criteria?.execution_performance?.[index],a.criteria?.execution_prices?.currency)).join("") || '<p class="hint">선택한 에이전트의 운영 목표 미제공 · 목표 충족 여부 미판정</p>'}
        ${a.criteria ? raw("운영 목표 원본·시험 조건", a.criteria.execution_performance) + raw("시험 단가·버전", a.criteria.execution_prices) : readProblems(currentAssessment())}
      </details>`;
  }
  function goalView(g, prepared, currency) {
    const p = prepared || {};
    const number = value => g.metric === "failure_rate" ? rate(value) : g.metric === "latency" || (g.metric === "repeat_spread" && p.measure === "elapsed_seconds") ? time(value) : g.metric === "cost" || p.measure === "cost" ? `${value == null ? "산출 불가" : text(value)}${currency ? " " + text(currency) : ""}` : text(value);
    return `<section class="performance-goal">${facts([["대상", text(targetNames[g.target] || g.target)], ["지표", text({latency:"전체 실행 시간",failure_rate:"기술적 실패율",cost:"실행 비용",repeat_spread:"반복 편차"}[g.metric] || g.metric)], ["통계 / 편차 측정 대상", g.metric === "repeat_spread" ? text(measureNames[p.measure] || p.measure) : text(g.statistic || "해당 없음")], ["종료 구분", text(p.group === "normal" ? "정상 반환" : outcomeNames[p.group] || "종료 표본 전체")], ["환경 / 입력 규모", `${text(p.environment)} / ${text(p.data_size)}`], ["측정값 / 목표 상한", `${number(g.value)} / ${number(g.maximum)}`], ["판정", badge(g.verdict)], ["검증 완료", g.complete ? "완료" : "미완료"], ["표본 수", text(g.sample_count)], ["대상 사례", g.case_ids.map(text).join(", ")]])}${reasonsView(g.reasons)}</section>`;
  }
  function scopedRuns() { return (currentBatch()?.runs || []).filter(run => ui.target === "all" || targetKey(run) === ui.target); }

  function caseGroups() {
    const groups = new Map();
    for (const run of scopedRuns()) {
      const i = info(run);
      const key = JSON.stringify([i.case_id, i.unit, i.target]);
      if (!groups.has(key)) groups.set(key, {key, id: i.case_id, runs: []});
      groups.get(key).runs.push(run);
    }
    for (const group of groups.values()) {
      group.runs.sort((a, b) => (info(a).repetition || 0) - (info(b).repetition || 0));
      group.prepared = group.runs.find((run) => run.case)?.case;
    }
    return [...groups.values()];
  }

  function matchingRuns(group) {
    return group.runs.filter((run) => ui.status === "all" || info(run).status === ui.status);
  }

  function filteredGroups() {
    return caseGroups().filter((group) => {
      if (!matchingRuns(group).length) return false;
      const c = group.prepared;
      const query = ui.query.trim().toLocaleLowerCase();
      const checkTerms = group.runs.flatMap(run => appliedChecks(run).flatMap(id => {
        const check = definition(id);
        return [id, check.category, check.name];
      }));
      const scenario = scenarioFor(selectedRun(group));
      const searchable = [group.id, scenario.name, scenario.description, c?.purpose, ...(c?.tags || []), ...checkTerms].join(" ").toLocaleLowerCase();
      const required = c?.assessment?.required;
      return (!query || searchable.includes(query)) &&
        (ui.tag === "all" || c?.tags?.includes(ui.tag)) &&
        (ui.required === "all" || (ui.required === "yes" && required === true) ||
         (ui.required === "no" && required === false) || (ui.required === "unknown" && required === undefined));
    });
  }

  function selectedRun(group) {
    const matches = group ? matchingRuns(group) : [];
    return matches.find((run) => run.key === ui.runKey) || matches[0];
  }

  function setNotice(message, error = false) {
    $("#notice").textContent = message;
    $("#notice").classList.toggle("error", error);
    $("#notice").hidden = !message || !error;
  }

  function showIssues(issues) {
    const root = $("#load-issues");
    root.hidden = !issues.length;
    root.innerHTML = issues.length ? `<details class="issues"><summary>파일 확인 사항 ${issues.length}건 · 정상 기록은 계속 확인할 수 있습니다</summary><ul>${issues.map((issue) => `<li class="${issue.severity === "error" ? "error" : ""}"><strong>${escape(issue.path || "선택 파일")}${issue.line ? `:${escape(issue.line)}` : ""}</strong><br>${escape(issue.message)}</li>`).join("")}</ul></details>` : "";
  }

  function resetSelection() {
    ui.operationalAgent = null; ui.operationalFilters = {};
    Object.assign(ui, {target: "all", caseKey: null, runKey: null, pageNumber: 0, query: "", status: "all", tag: "all", required: "all", detail: "assessment", scenarioOpen: false});
    $("#case-search").value = "";
    $("#status-filter").value = "all";
    $("#required-filter").value = "all";
    $("#case-list-picker").open = !mobileLayout?.matches;
  }

  function acceptFiles(files, sample, readIssues = []) {
    const catalog = ExecutionEvaluationData.parseFiles(files);
    showIssues([...readIssues, ...catalog.issues]);
    if (!catalog.batches.length) {
      setNotice("지원하는 에이전트 실행·채점 결과를 찾지 못했습니다. 실행 결과 폴더 또는 execution-evaluation-v1 파일을 선택하세요. 기존 화면은 유지됩니다.", true);
      return false;
    }

    remoteEpoch++; remote?.dispose(); remote = null; $("#application").setAttribute("aria-busy", "false");
    ui.catalog = catalog;
    ui.batch = 0;
    ui.assessmentKey = null; ui.qualityKey = null;
    ui.aggregate = "functional";
    ui.page = catalog.batches[0].source === "assessment" ? "aggregate" : "cases";
    ui.sample = sample;
    resetSelection();
    $("#welcome").hidden = true;
    $("#application").hidden = false;
    $("#sample-notice").hidden = !sample;

    $("#batch-select").innerHTML = catalog.batches.map((batch, index) => {
      const label = EvaluationNames.batchLabel(batch, catalog.batches);
      return `<option value="${index}">${escape(label)}</option>`;
    }).join("");
    setNotice(sample ? "" : `${catalog.batches.length}개 묶음을 불러왔습니다. 새 파일을 열면 현재 자료를 교체합니다.`);
    render();
    return true;
  }

  let remote = null, remoteIndex = null, remoteEpoch = 0;
  function readProblems(record) {
    if (!record?.loadError && !record?.issues?.length) return "";
    const messages = record.issues?.map(issue => text(issue.path) + " · " + text(issue.message)) || [text(record.loadError)];
    return '<section class="empty"><h3>일부 원본 읽기 오류</h3><p>읽은 결과는 그대로 표시합니다. 저장된 판정은 변경하지 않았습니다.</p><ul>' + messages.map(message => '<li>' + message + '</li>').join("") + '</ul></section>';
  }
  async function loadRemoteBatch(index) {
    const epoch = ++remoteEpoch, client = remote, request = client.begin("batch");
    if (currentBatch() && remoteIndex.batches[ui.batch]) ui.catalog.batches[ui.batch] = EvaluationLazy.batchIndex(remoteIndex.batches[ui.batch]);
    client.clear(); downloads = [];
    ui.batch = index; ui.assessmentKey = null; ui.qualityKey = null; resetSelection(); ui.page = "aggregate";
    $("#application").setAttribute("aria-busy", "true");
    $("#case-page").hidden = true; $("#aggregate-page").hidden = false;
    $("#assessment-toolbar").innerHTML = "";
    renderNavigation();
    setNotice("");
    const progress = ({completed, total}) => {
      if (epoch === remoteEpoch && request.current()) $("#aggregate-page").innerHTML = '<p class="hint" role="status">평가 결과 자동 불러오는 중… ' + completed + ' / ' + total + '</p>';
    };
    progress({completed: 0, total: 0});
    try {
      const batch = await ExecutionAutomatic.load(client, remoteIndex.batches[index], {files: remoteIndex.files, signal: request.signal, onProgress: progress});
      if (epoch !== remoteEpoch || remote !== client || !request.current()) return;
      ui.catalog.batches[index] = batch;
      if (!currentAssessment() && currentQuality()) ui.aggregate = "quality";
      showIssues([...(remoteIndex.issues || []), ...batch.readErrors]);
      setNotice(batch.readErrors.length ? "자동 불러오기를 마쳤습니다. 일부 파일의 읽기 오류를 확인하세요." : "평가 결과와 원문을 모두 불러왔습니다.", batch.readErrors.length > 0);
      render();
    } catch (error) {
      if (epoch === remoteEpoch && request.current() && error.name !== "AbortError") {
        setNotice("묶음 읽기 오류: " + error.message, true);
        $("#aggregate-page").innerHTML = '<div class="empty"><h3>평가 결과를 불러오지 못했습니다.</h3><p>' + text(error.message) + '</p></div>';
      }
    } finally {
      if (epoch === remoteEpoch && remote === client) { client.clear(); $("#application").setAttribute("aria-busy", "false"); }
    }
  }
  async function loadRemoteCatalog() {
    try {
      const epoch = remoteEpoch, client = EvaluationLazy.create({baseURL: new URL("../../../", location.href), maxFileBytes: 128 * 1048576, maxBytes: 32 * 1048576, maxEntries: 4096, deduplicate: true});
      remote = client;
      const index = await client.catalog("eval/outputs/evaluation-viewer/catalog.json");
      if (remote !== client || epoch !== remoteEpoch) return;
      remoteIndex = index;
      const executionBatch = entry => entry.assessments.some(item => viewerSchema(item.report_schema_version)) ||
        (Array.isArray(entry.units) && entry.units.some(unit => ["agent", "workflow"].includes(unit)));
      remoteIndex.batches = remoteIndex.batches.filter(executionBatch);
      if (!remoteIndex.batches.length) { setNotice("저장된 실행 묶음이 없습니다."); return; }
      ui.catalog = {batches: remoteIndex.batches.map(EvaluationLazy.batchIndex), issues: remoteIndex.issues || []};
      ui.sample = false;
      $("#welcome").hidden = true; $("#application").hidden = false; $("#sample-notice").hidden = true;
      $("#batch-select").innerHTML = remoteIndex.batches.map((batch, index) => {
        let label = batch.id || batch.path;
        if (batch.id && remoteIndex.batches.some(other => other !== batch && other.id === batch.id)) {
          label += " · " + batch.path.replaceAll("\\", "/").split("/").slice(0, -2).join("/");
        }
        return '<option value="' + index + '">' + text(label) + '</option>';
      }).join("");
      showIssues(remoteIndex.issues || []);
      await loadRemoteBatch(0);
    } catch (error) { setNotice("목록 읽기 오류: " + error.message + " HTTP 주소에서 열거나 결과 파일을 직접 선택하세요.", true); }
  }
  function loadLocalResults() {
    if (typeof EvaluationLazy !== "undefined") { void loadRemoteCatalog(); return; }
    setNotice("자동 조회를 사용할 수 없습니다. HTTP 주소에서 열거나 결과 파일을 직접 선택하세요.");
  }

  async function loadFiles(fileList) {
    if (!fileList.length || ui.loading) return;
    ui.loading = true;
    toggleLoading(true);
    const candidates = [...fileList].filter((file) => /\.(json|jsonl)$/i.test(file.name));
    const totalBytes = candidates.reduce((sum, file) => sum + (file.size || 0), 0);
    if (totalBytes > 64 * 1024 * 1024) {
      setNotice("수동으로 선택한 파일은 전체를 읽습니다. 합계 64 MB를 넘어서 읽지 않았습니다. HTTP 조회에서 평가 묶음을 선택하면 파일당 128 MB 한도로 자동 불러옵니다.", true);
      ui.loading = false; toggleLoading(false); return;
    }
    const entries = new Array(candidates.length), issues = [];
    let next = 0, completed = 0;
    try {
      setNotice(`파일 읽는 중 · 0 / ${candidates.length}`);
      async function readNext() {
        while (next < candidates.length) {
          const index = next++, file = candidates[index];
          // Preserve paths and selection order, with bounded concurrent local reads.
          const path = file.webkitRelativePath || file.name;
          try { entries[index] = {path, text: await file.text()}; }
          catch { issues.push({severity: "error", path, message: "이 파일을 읽을 수 없습니다. 접근 권한과 파일 상태를 확인하세요."}); }
          completed++;
          setNotice(`파일 읽는 중 · ${completed} / ${candidates.length}`);
        }
      }
      await Promise.all(Array.from({length: Math.min(8, candidates.length)}, readNext));
      acceptFiles(entries.filter(Boolean), false, issues);
    } catch (error) {
      setNotice(`불러오기를 완료하지 못했습니다. 기존 자료는 유지됩니다. ${error instanceof Error ? error.message : "파일을 확인하세요."}`, true);
    } finally {
      ui.loading = false;
      toggleLoading(false);
      $("#folder-input").value = "";
      $("#files-input").value = "";
    }
  }

  function toggleLoading(value) {
    for (const id of ["sample-button", "welcome-open"]) $("#" + id).disabled = value;
  }

  function renderNavigation() {
    const groups = new Map();
    function add(unit, target, caseId) {
      const key = executionKey(unit, target);
      if (!groups.has(key)) groups.set(key, {key, unit, target, cases: new Set()});
      groups.get(key).cases.add(caseId);
    }
    for (const run of currentBatch().runs) { const i = info(run); add(i.unit,i.target,i.case_id); }
    for (const record of [currentAssessment(), currentQuality()]) for (const c of record?.report.criteria?.cases || []) add(c.unit,c.target,c.id);
    if (ui.target !== "all" && !groups.has(ui.target)) ui.target = "all";
    $("#target-nav").innerHTML = `<button type="button" class="target-button" data-target="all" aria-pressed="${ui.target === "all"}">전체 대상</button>` + [...groups.values()].map(g => `<button type="button" class="target-button" data-target="${escape(g.key)}" aria-pressed="${ui.target === g.key}"><span>${text(targetNames[g.target] || g.target)}</span><span>${g.cases.size}</span></button>`).join("");
    const selected = groups.get(ui.target);
    $("#breadcrumb").textContent = selected ? selected.target.toUpperCase() : "모든 대상";
    $("#target-title").textContent = selected ? targetNames[selected.target] || selected.target : "에이전트 실행 평가 결과 검토";
    const filterCount = [ui.status, ui.tag, ui.required].filter((value) => value !== "all").length;
    $("#filter-count").textContent = filterCount ? `${filterCount}개 적용` : "";
    const tags = [...new Set(caseGroups().flatMap((group) => group.prepared?.tags || []))];
    $("#tag-filter").innerHTML = '<option value="all">모든 태그</option>' + tags.map((tag) => `<option value="${escape(tag)}">${escape(tag)}</option>`).join("");
    $("#tag-filter").value = ui.tag;
  }

  function renderCases() {
    const groups = filteredGroups();
    const totalPages = Math.max(1, Math.ceil(groups.length / PAGE_SIZE));
    ui.pageNumber = Math.min(ui.pageNumber, totalPages - 1);
    const shown = groups.slice(ui.pageNumber * PAGE_SIZE, (ui.pageNumber + 1) * PAGE_SIZE);
    let selected = shown.find((group) => group.key === ui.caseKey);
    if (!selected) {
      selected = shown[0];
      ui.caseKey = selected?.key || null;
      ui.runKey = null;
      ui.scenarioOpen = false;
    }
    $("#case-rows").innerHTML = shown.length ? shown.map((group) => {
      const scenario = scenarioFor(selectedRun(group));
      return `<tr class="${group.key === ui.caseKey ? "selected" : ""}"><td><button type="button" class="case-button" data-case="${escape(group.key)}" aria-pressed="${group.key === ui.caseKey}"><span class="case-id">${text(scenario.name)}</span></button></td><td class="nowrap">${group.runs.length}건</td></tr>`;
    }).join("") : '<tr><td colspan="2"><div class="empty"><h3>표시할 사례가 없습니다</h3><p>검색 조건을 바꾸거나 결과 파일이 있는 다른 대상을 선택하세요.</p></div></td></tr>';
    $("#pagination").innerHTML = `<span>${groups.length} / ${caseGroups().length}사례 · ${ui.pageNumber + 1} / ${totalPages}쪽</span><div><button type="button" data-page-step="-1" ${ui.pageNumber === 0 ? "disabled" : ""}>이전</button> <button type="button" data-page-step="1" ${ui.pageNumber + 1 >= totalPages ? "disabled" : ""}>다음</button></div>`;
    if (ui.page === "cases") renderDetail(selected, selectedRun(selected));
  }

  function scenarioFor(run) {
    return globalThis.ExecutionScenarios?.resolve(run, currentBatch()) || {
      name: run.case?.purpose || info(run).case_id,
      description: "",
      html: '<section class="scenario-diagram scenario-reference"><h3>이상적인 시나리오</h3><p class="hint">시나리오 도식 미제공</p></section><section class="scenario-diagram scenario-actual"><h3>실제 실행 결과</h3><p class="hint">실제 실행 기록 미제공</p></section>',
    };
  }

  function caseChecks(run, scored) {
    if (currentAssessment()?.loadError) return readProblems(currentAssessment());
    if (!functionalTarget(info(run))) return '<p class="hint">운영 진단 전용 · 기능 검사 적용 대상이 아닙니다.</p>';
    if (!scored) {
      const checks = criteriaCase(info(run).case_id)?.assessment?.checks || appliedChecks(run);
      return checks.length ? `<div class="evidence-list">${checks.map(id => `<div class="case-check-missing"><span>${text(id)} · ${text(definition(id).name || "항목명 미등록")}</span><span class="dim">결과 미제공</span></div>`).join("")}</div>` : '<p class="hint">검사 결과 미제공</p>';
    }
    return `<div class="evidence-list">${scored.checks.map(check => `<details class="evidence-item"><summary><h4>${text(check.check)} · ${text(definition(check.check).name || "항목명 미등록")}</h4>${badge(check.verdict)}</summary>
      ${check.details.map((d, index) => `<section class="detail-result"><h4>세부 판정 ${index + 1} · ${badge(d.verdict)}</h4><p>${text(d.reason)}</p></section>`).join("")}</details>`).join("") || '<p class="hint">검사 결과 미제공</p>'}</div>`;
  }

  function caseFunctional(run, scored) {
    if (!functionalTarget(info(run))) return '<p class="hint">운영 진단 전용 · 기능 지표 적용 대상이 아닙니다.</p>';
    if (!scored) return '<p class="hint">선택한 채점 기록에 이 실행의 기능 지표가 없습니다.</p>';
    const entries = [["실행 기능 판정", badge(scored.verdict)], ["기능 검증 완료", scored.complete ? "완료" : "미완료"]];
    if (info(run).target === "report") entries.push(["보고서 완성 범위", text({complete: "완성", partial: "부분", none: "생성 결과 없음"}[scored.report_completeness])]);
    return facts(entries);
  }

  function caseOperational(run) {
    const m = measurement(run);
    if (!m) return '<p class="hint">선택한 채점 기록에 이 실행의 운영 지표가 없습니다.</p>';
    const cost = value => value == null ? "산출 불가" : `${text(value)}${m.currency ? ` ${text(m.currency)}` : ""}`;
    return facts([
      ["종료 결과", text(outcomeNames[m.outcome] || m.outcome)],
      ["대상 지역", text(m.dong_code)], ["대상 기간", text(m.month)],
      ["전체 실행 시간", time(m.elapsed_seconds)],
      ...["model_calls", "tool_calls", "agent_calls", "node_entries", "retries", "input_tokens", "output_tokens"].map(key => [measureNames[key], text(m[key])]),
      ["모델 비용", cost(m.model_cost)], ["도구 비용", cost(m.tool_cost)], ["실행 비용", cost(m.cost)],
    ]);
  }

  function renderDetail(group, run) {
    if (!group || !run) {
      $("#case-detail").innerHTML = '<div class="empty"><h3>사례를 선택하세요</h3><p>목록에서 확인할 시나리오를 선택하세요.</p></div>';
      return;
    }
    ui.runKey = run.key;
    const scenario = scenarioFor(run), scored = scoredRun(run);
    const wanted = key => !remote || ui.detail === key;
    const panels = {
      quality: wanted("quality") ? qualityView(run) : "",
      assessment: wanted("assessment") ? `<section class="case-section"><h3>기능 지표</h3>${caseFunctional(run, scored)}</section>
        <section class="case-section"><h3>검사 항목</h3>${readProblems(currentAssessment())}${caseChecks(run, scored)}</section>` : "",
      operational: wanted("operational") ? `<section class="case-section"><h3>운영 지표</h3>${caseOperational(run)}</section>` : "",
      io: wanted("io") ? `<section class="case-section"><details class="case-input"><summary>입력</summary>${ExecutionValues.render(run.case?.initial)}</details><details class="case-output"><summary>전체 출력</summary>${ExecutionValues.render(run.report?.state)}</details></section>` : "",
    };
    $("#case-detail").innerHTML = `<button type="button" class="back-to-list" data-back-to-list>← 목록으로</button>
      <details id="case-scenario" class="case-scenario"${ui.scenarioOpen ? " open" : ""}><summary><h2>Scenario ${text(scenario.name)}</h2></summary>${scenario.html}</details>
      ${run.loadError ? readProblems(run) : ""}<div class="selectors"><select id="run-select" aria-label="실행 회차">${matchingRuns(group).map(r => `<option value="${escape(r.key)}"${r.key === run.key ? " selected" : ""}>${text(info(r).repetition)}회차</option>`).join("")}</select></div>
      <div class="detail-tabs" role="tablist" aria-label="사례 상세 항목">${detailTabs.map(([key, label]) => `<button type="button" role="tab" id="case-tab-${key}" data-detail="${key}" aria-selected="${ui.detail === key}" aria-controls="case-panel-${key}" tabindex="${ui.detail === key ? 0 : -1}">${label}</button>`).join("")}</div>
      ${detailTabs.map(([key]) => `<div role="tabpanel" id="case-panel-${key}" aria-labelledby="case-tab-${key}" tabindex="0"${ui.detail === key ? "" : " hidden"}>${panels[key]}</div>`).join("")}`;
  }

  function renderAggregate() {
    const record = currentAssessment(), a = record?.loadError ? null : record?.report;
    const unavailable = '<div class="empty"><h3>실행 채점 결과 미제공</h3><p>execution-evaluation-v1 채점 파일을 함께 열면 기능·운영 지표와 검사 근거를 확인할 수 있습니다.</p></div>';
    const wanted = key => !remote || ui.aggregate === key;
    const panels = {
      quality: wanted("quality") ? qualityView() : "",
      functional: wanted("functional") ? (a ? `${functionalView(a.summary.functional)}<section class="section"><h3>보고서 완성률 · 채점 기록 전체</h3>${facts([["완성률 · 완성 / 시작 실행", ratio(a.summary.report_completion)]])}<p class="hint">실제로 완성 보고서를 반환하고 해당 반환·구성·완성 검사를 통과한 실행의 비율입니다. 부분 보고서의 기능 통과와 구분합니다.</p></section>` : unavailable) : "",
      operational: wanted("operational") ? (a ? operationalView(a.summary.operational) : unavailable) : "",
    };
    $("#aggregate-page").innerHTML = `${ui.aggregate === "quality" ? "" : readProblems(record)}
      <div id="aggregate-tabs" class="detail-tabs aggregate-tabs" role="tablist" aria-label="전체 집계 항목">${aggregateTabs.map(([key, label]) => `<button type="button" role="tab" id="aggregate-tab-${key}" data-aggregate="${key}" aria-selected="${ui.aggregate === key}" aria-controls="aggregate-panel-${key}" tabindex="${ui.aggregate === key ? 0 : -1}">${label}</button>`).join("")}</div>
      ${aggregateTabs.map(([key]) => `<div role="tabpanel" id="aggregate-panel-${key}" aria-labelledby="aggregate-tab-${key}" tabindex="0"${ui.aggregate === key ? "" : " hidden"}>${panels[key]}</div>`).join("")}`;
    const tablist = $("#aggregate-tabs"), selected = $("#aggregate-tab-" + ui.aggregate);
    if (tablist.clientWidth) tablist.scrollLeft = Math.max(0, selected.offsetLeft + selected.offsetWidth - tablist.clientWidth);
    if (ui.aggregate === "operational") {
      const agents = $(".operational-agents"), selectedAgent = $(".operational-agents [aria-selected=true]");
      if (agents?.clientWidth && selectedAgent) agents.scrollLeft = Math.max(0, selectedAgent.offsetLeft + selectedAgent.offsetWidth - agents.clientWidth);
    }
  }

  function render() {
    if (!ui.catalog) return;
    if (remote && (!currentBatch()?.report || currentBatch().lazy)) return;
    downloads = [];
    renderNavigation();
    $("#assessment-toolbar").innerHTML = assessmentPicker();
    for (const button of document.querySelectorAll(".page-tabs [data-page]")) button.setAttribute("aria-pressed", String(button.dataset.page === ui.page));
    $("#case-page").hidden = ui.page !== "cases";
    $("#aggregate-page").hidden = ui.page !== "aggregate";
    // The sidebar remains available on both pages; detailed evidence is rendered only for its page.
    renderCases();
    if (ui.page === "aggregate") renderAggregate();
  }

  function openRun(key) {
    const run = scopedRuns().find((r) => r.key === key);
    if (!run) return;
    const i = info(run);
    ui.caseKey = JSON.stringify([i.case_id, i.unit, i.target]);
    ui.runKey = key;
    ui.page = "cases";
    ui.detail = "io";
    ui.scenarioOpen = false;
    ui.query = ""; ui.status = "all"; ui.tag = "all"; ui.required = "all";
    $("#case-search").value = "";
    $("#status-filter").value = "all";
    $("#required-filter").value = "all";
    ui.pageNumber = Math.floor(caseGroups().findIndex((group) => group.key === ui.caseKey) / PAGE_SIZE);
    if (mobileLayout?.matches) $("#case-list-picker").open = false;
    render();
    focusPane("#case-detail");
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (has(button.dataset, "download")) {
      const item = downloads[Number(button.dataset.download)];
      if (!item) return;
      const data = item.jsonl ? (typeof item.value === "string" ? item.value : item.value.map((line) => JSON.stringify(line)).join("\n") + "\n") : JSON.stringify(item.value, null, 2);
      const url = URL.createObjectURL(new Blob([data], {type: item.jsonl ? "application/x-ndjson;charset=utf-8" : "application/json;charset=utf-8"}));
      const link = document.createElement("a");
      link.href = url; link.download = item.name; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return;
    }
    if (button.dataset.openRun) { openRun(button.dataset.openRun); return; }
    if (button.dataset.operationalAgent) {
      selectOperationalAgent(button.dataset.operationalAgent); return;
    }
    if (button.dataset.operationalFilter && ExecutionOperational.FILTER_KEYS.includes(button.dataset.operationalFilter)) {
      const key = button.dataset.operationalFilter, value = JSON.parse(button.dataset.conditionValue), previous = ui.operationalFilters[key] || [];
      ui.operationalFilters[key] = previous.includes(value) ? previous.filter(item => item !== value) : [...previous, value];
      render(); $("#operational-filter-" + key + "-" + button.dataset.conditionIndex).focus({preventScroll: true}); return;
    }
    if (has(button.dataset, "clearOperational")) {
      ui.operationalFilters = {}; render(); $("#operational-selection").focus({preventScroll: true}); return;
    }
    if (button.dataset.target) {
      resetSelection(); ui.target = button.dataset.target;
    }
    else if (button.dataset.case) {
      if (ui.caseKey !== button.dataset.case) ui.scenarioOpen = false;
      ui.caseKey = button.dataset.case; ui.runKey = null; ui.page = "cases";
      if (mobileLayout?.matches) $("#case-list-picker").open = false;
    }
    else if (has(button.dataset, "backToList")) $("#case-list-picker").open = true;
    else if (button.dataset.page) ui.page = button.dataset.page;
    else if (button.dataset.detail && detailTabs.some(([key]) => key === button.dataset.detail)) ui.detail = button.dataset.detail;
    else if (button.dataset.aggregate && aggregateTabs.some(([key]) => key === button.dataset.aggregate)) ui.aggregate = button.dataset.aggregate;
    else if (button.dataset.pageStep) {
      ui.pageNumber += Number(button.dataset.pageStep); ui.caseKey = null; ui.runKey = null;
    }
    else return;
    render();
    if (button.dataset.case) focusPane("#case-detail");
    else if (has(button.dataset, "backToList")) focusPane("#case-list");
    else if (button.dataset.detail) $("#case-tab-" + ui.detail).focus({preventScroll: true});
    else if (button.dataset.aggregate) $("#aggregate-tab-" + ui.aggregate).focus({preventScroll: true});
  });
  document.addEventListener("toggle", event => {
    if (event.target.id === "case-scenario" && event.target.isConnected) ui.scenarioOpen = event.target.open;
  }, true);
  function selectOperationalAgent(key) {
    const agents = operationalAgents();
    const index = agents.findIndex(agent => agent.key === key);
    if (index < 0) return;
    if (ui.operationalAgent !== key) {
      resetSelection(); ui.target = key; ui.operationalAgent = key;
    }
    render(); $("#operational-agent-" + index).focus({preventScroll: true});
  }
  document.addEventListener("keydown", event => {
    if (has(event.target.dataset, "operationalAgent")) {
      const agents = operationalAgents();
      const index = agents.findIndex(agent => agent.key === event.target.dataset.operationalAgent);
      if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? agents.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + agents.length) % agents.length;
      selectOperationalAgent(agents[next].key); return;
    }
    const aggregate = has(event.target.dataset, "aggregate");
    const tabs = aggregate ? aggregateTabs : detailTabs;
    const selected = aggregate ? "aggregate" : "detail";
    const index = tabs.findIndex(([key]) => key === event.target.dataset?.[selected]);
    if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    ui[selected] = tabs[next][0];
    render();
    $((aggregate ? "#aggregate-tab-" : "#case-tab-") + ui[selected]).focus({preventScroll: true});
  });
  $("#welcome-open").addEventListener("click", () => $("#folder-input").click());
  $("#folder-input").addEventListener("change", (event) => loadFiles(event.target.files));
  $("#files-input").addEventListener("change", (event) => loadFiles(event.target.files));
  $("#sample-button").addEventListener("click", async () => {
    if (typeof ExecutionEvaluationSamples === "undefined") {
      try { await new Promise((resolve, reject) => { const script = document.createElement("script"); script.src = "samples.js"; script.onload = resolve; script.onerror = reject; document.head.append(script); }); }
      catch { setNotice("화면 샘플을 읽을 수 없습니다.", true); return; }
    }
    acceptFiles(ExecutionEvaluationSamples().files, true);
  });
  $("#batch-select").addEventListener("change", (event) => { if (remote) { ui.aggregate = "functional"; return loadRemoteBatch(Number(event.target.value)); } ui.batch = Number(event.target.value); ui.assessmentKey = null; ui.qualityKey = null; ui.aggregate = "functional"; resetSelection(); if (currentBatch().source === "assessment") ui.page = "aggregate"; render(); });
  $("#case-search").addEventListener("input", (event) => { ui.query = event.target.value; ui.pageNumber = 0; render(); });
  for (const [id, key] of [["status-filter", "status"], ["tag-filter", "tag"], ["required-filter", "required"]]) {
    $("#" + id).addEventListener("change", (event) => { ui[key] = event.target.value; ui.pageNumber = 0; render(); });
  }
  document.addEventListener("change", (event) => {
    if (event.target.id === "quality-select") { ui.qualityKey = event.target.value; render(); }
    if (event.target.id === "run-select") { ui.runKey = event.target.value; render(); }
    if (event.target.id === "assessment-select") { ui.assessmentKey = event.target.value; ui.operationalAgent = null; ui.operationalFilters = {}; render(); }
  });
  loadLocalResults();
})();
