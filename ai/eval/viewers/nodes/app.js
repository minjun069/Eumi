/* UI state and rendering only. Artifact validation/linking lives in data.js.
 * No execution, grading, or persistence of loaded files. */
(function () {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const has = (object, key) => object != null && Object.hasOwn(object, key);
  const text = (value) => value == null ? "미기록" : escape(value);
  const decimalFormat = new Intl.NumberFormat("en-US", {useGrouping: false, maximumFractionDigits: 3});
  const metricNumber = value => typeof value === "number" && Number.isFinite(value) ? decimalFormat.format(value) : value;
  const metricText = value => text(metricNumber(value));
  const dateTime = value => text(EvaluationNames.dateTime(value));
  const statusNames = {
    running: "진행 중", returned: "반환됨", error: "실행 오류", cancelled: "취소됨",
    queued: "대기", completed: "완료", partial: "부분 완료", failed: "실패 종료", waiting_input: "질문 대기",
  };
  const targetNames = {
    query_data: "데이터 검색 및 조회", process_data: "데이터 가공",
    validate_visualization: "시각화 설정 검사", render_visualization: "표 렌더링",
    interpret: "작업 목적 파악", act: "작업 선택 및 실행", decide: "작업 진행 판단",
    compose: "응답 작성", ask: "사용자 정보 요청", request: "사용자 요청 처리",
    interpretation: "분석 결과 해석", visualization: "데이터 시각화", report: "대시보드 보고서 생성",
    report_selection: "보고서 시각화 선정", report_description: "보고서 시각화 설명", report_insight: "보고서 퀵 인사이트",
  };
  const nodeEvaluationIds = new Map([
    ["interpret", "N01"], ["act", "N02"], ["decide", "N03"], ["compose", "N04"], ["ask", "N05"],
  ]);
  const ui = {
    catalog: null, batch: 0, target: "all", caseKey: null, runKey: null,
    page: "cases", caseTab: "functional", aggregateTab: "functional", aggregateRole: "all", scenarios: {scenarios: [], issues: []}, query: "", status: "all", tag: "all",
    required: "all", pageNumber: 0, scenarioOpen: new Set(), checkOpen: new Set(),
    assessmentKey: null, scoreFilter: null, scoreLimit: 30, metricsWidth: 50, inputOpen: false, outputOpen: true, closedMessages: new Set(),
  };
  let downloads = [];
  let remote = null;
  let activeResize = null;
  let aggregateViewCache = null;
  const PAGE_SIZE = 25;

  // These disclosures and pane choices are presentation state only.
  const mobileLayout = globalThis.matchMedia?.("(max-width: 760px)");
  function syncDisclosures() {
    if (!mobileLayout) return;
    $("#case-filters").open = false;
    $("#case-list-picker").open = !mobileLayout.matches;
  }
  mobileLayout?.addEventListener("change", syncDisclosures);
  syncDisclosures();

  function focusPane(selector) {
    if (!globalThis.matchMedia?.("(max-width: 1200px)")?.matches) return;
    const pane = $(selector);
    pane.focus({preventScroll: true});
    pane.scrollIntoView({block: "start"});
  }

  function applySplitWidth(width) {
    if (!Number.isFinite(width)) return;
    ui.metricsWidth = Math.round(Math.max(25, Math.min(75, width)) * 10) / 10;
    $(".case-results-split")?.style.setProperty("--case-metrics-width", `${ui.metricsWidth}%`);
    const splitter = $("#case-splitter");
    splitter?.setAttribute("aria-valuenow", String(ui.metricsWidth));
    splitter?.setAttribute("aria-valuetext", `기능·운영 지표 ${ui.metricsWidth}%, 입출력 ${Math.round((100 - ui.metricsWidth) * 10) / 10}%`);
  }

  function stopResize() {
    if (!activeResize) return;
    const {splitter, pane, pointerId} = activeResize;
    activeResize = null;
    pane.classList.remove("is-resizing");
    if (splitter.hasPointerCapture(pointerId)) splitter.releasePointerCapture(pointerId);
  }
  mobileLayout?.addEventListener("change", stopResize);

  document.addEventListener("pointerdown", event => {
    const splitter = event.target.closest?.("#case-splitter");
    if (!splitter || event.button !== 0 || mobileLayout?.matches) return;
    stopResize();
    const pane = $(".case-results-split");
    event.preventDefault();
    splitter.focus({preventScroll: true});
    splitter.setPointerCapture(event.pointerId);
    pane.classList.add("is-resizing");
    activeResize = {splitter, pane, pointerId: event.pointerId};
  });
  document.addEventListener("pointermove", event => {
    if (!activeResize || event.pointerId !== activeResize.pointerId) return;
    if (!activeResize.splitter.isConnected || mobileLayout?.matches) { stopResize(); return; }
    const bounds = activeResize.pane.getBoundingClientRect();
    if (bounds.width > 0) applySplitWidth((event.clientX - bounds.left) / bounds.width * 100);
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
    document.addEventListener(name, event => {
      if (activeResize?.pointerId === event.pointerId) stopResize();
    });
  }

  function info(run) {
    if (run.report) return run.report.run;
    const entry = run.entry || {};
    const prepared = run.case || {};
    return {
      ...entry, id: entry.run_id, case_id: entry.case_id || prepared.id,
      unit: entry.unit || prepared.unit, target: entry.target || prepared.target,
      role: prepared.unit === "agent" ? prepared.target : prepared.role ?? run.role,
      dependencies: run.case ? prepared.dependencies || "real" : null,
    };
  }

  const nodeKey = (node, role, counted = true) => JSON.stringify([counted ? "node" : "selection", node, role ?? null]);
  function targetKey(run) {
    const i = info(run);
    return nodeKey(i.target, i.role, i.unit !== "selection");
  }
  function nodeLabel(node, role) {
    return `${nodeEvaluationIds.get(node) || node} · ${targetNames[node] || node}${role ? " / " + (targetNames[role] || role) : ""}`;
  }
  const roleLabel = role => targetNames[role] || role || "역할 미기록";
  function targetLabel(run) {
    const i = info(run);
    return nodeEvaluationIds.has(i.target) ? nodeLabel(i.target, i.role) : targetNames[i.target] || i.target;
  }
  function appliedChecks(run) {
    return run.report ? run.report.assessment.checks : run.case?.assessment?.checks || [];
  }
  function definition(id) {
    if (remote && currentAssessment() && !currentAssessment().lazy && !currentAssessment().report.criteria) return {name:"기준 자료 미제공",description:"기준 자료를 불러오지 못했습니다. 파일 확인 사항을 확인하세요."};
    const d = currentAssessment()?.report.criteria?.checks?.[id];
    return {
      category: d?.axis,
      name: d?.fields?.["검사 항목"] || d?.rows?.[0]?.fields?.["검사 항목"],
      description: d?.fields?.["검사 내용"] || d?.rows?.[0]?.fields?.["검사 내용"],
    };
  }
  function checkDefinition(run, id) { return definition(id); }
  const checkAxes = ["형식 준수", "필수 내용 충족", "내용 정확성"];
  function axisLabel(axis) {
    const index = checkAxes.indexOf(axis);
    return index < 0 ? text(axis) : `<span class="axis-label axis-${["format", "required", "accuracy"][index]}">${text(axis)}</span>`;
  }
  function orderedChecks(rows) {
    const rank = row => {
      const index = checkAxes.indexOf(row.axis ?? definition(row.check).category);
      return index < 0 ? checkAxes.length : index;
    };
    return [...rows].sort((left, right) => rank(left) - rank(right));
  }
  function time(value) {
    return value == null ? "미기록" : `${metricText(value)}초`;
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
      <div class="raw-tools">${downloadButton(value, filename)}</div>
      <pre>${escape(shortened ? original.slice(0, 24000) : original)}</pre>
      ${shortened ? '<p class="hint">긴 원문은 앞부분만 표시합니다. 내려받기로 전체 내용을 확인할 수 있습니다.</p>' : ""}</details>`;
  }

  function currentBatch() { return ui.catalog?.batches[ui.batch]; }
  const batchName = (batch = currentBatch()) => EvaluationNames.batchName(batch, ui.catalog?.batches);
  const assessmentName = record => record.report.id ? EvaluationNames.assessmentName(record, currentBatch(), ui.catalog?.batches) : `${record.path.split("/").pop()} · 기존 단일 JSON`;
  const assessmentFilename = record => EvaluationNames.assessmentFilename(record, currentBatch(), ui.catalog?.batches);
  function batchOptionLabel(batch) {
    const runs = batch.report?.runs || batch.runs?.map(run => info(run)) || [];
    const indexedTargets = Array.isArray(batch.entry?.node_targets) ? batch.entry.node_targets : [];
    const targets = runs.length ? runs.filter(run => run.unit === "node").map(run => run.target) : indexedTargets;
    const names = [...new Set(targets.filter(node => typeof node === "string" && node))].map(node => targetNames[node] || node).join(" · ") || "노드명 미기록";
    const saved = EvaluationNames.batchName(batch, ui.catalog?.batches).match(/(\d{4}-\d{2}-\d{2}|실행일 미기록) 실행(\d+)$/);
    return saved ? `${names} (${saved[1].replaceAll("-", ".")} - ${saved[2].padStart(2, "0")})` : names;
  }
  function assessmentOptionLabel(record) {
    const number = assessmentFilename(record).match(/_채점(\d+)\.json$/)?.[1];
    return number ? `채점 ${number.padStart(2, "0")}` : "채점 번호 미기록";
  }
  function ordinal(number) {
    const lastTwo = number % 100;
    const suffix = lastTwo >= 11 && lastTwo <= 13 ? "th" : ({1: "st", 2: "nd", 3: "rd"}[number % 10] || "th");
    return `${number}${suffix}`;
  }
  function caseDisplayName(run) {
    const scope = metricScope(run);
    const memberships = NodeScenarios.forCase(ui.scenarios, scope.caseId, scope.node, scope.role);
    return memberships.map(item => {
      const positions = item.steps.flatMap((step, index) => item.stepIds.includes(step.step_id) ? [ordinal(index + 1)] : []);
      return `Scenario ${item.scenario.title || item.scenario.id} - ${positions.join(", ")}`;
    }).join(" / ") || `사례 ${scope.caseId}`;
  }
  function recordLocation(record) {
    return `<details class="section"><summary>저장 위치</summary><code>${text(record.path)}</code></details>${EvaluationNames.legacy(record) ? '<p class="hint">기존 기록의 표시 순번은 불러온 자료의 시간순입니다. 저장된 파일과 원본 내용은 유지하며 내려받기에는 표시 이름을 사용합니다.</p>' : ""}`;
  }


  function currentAssessment() {
    const records = currentBatch()?.assessments || [];
    return records.find(item => item.path === ui.assessmentKey) || records[0];
  }


  function scoredRun(run, record = currentAssessment()) {
    const i = info(run);
    return record?.report.runs?.find(a => a.run_id === i.id && a.case_id === i.case_id && a.repetition === i.repetition);
  }

  function assessmentPicker() {
    const records = currentBatch()?.assessments || [], selected = currentAssessment();
    return `<label class="assessment-picker">채점 기록<select id="assessment-select" ${records.length && !currentBatch()?.lazy ? "" : "disabled"}>${records.length ? records.map(item => `<option value="${escape(item.path)}"${item === selected ? " selected" : ""}>${text(assessmentOptionLabel(item))}</option>`).join("") : '<option>채점 파일 미제공</option>'}</select></label>`;
  }

  function selectedNodes() {
    return (currentAssessment()?.report.nodes || []).filter(n => ui.target === "all" || ui.target === nodeKey(n.node, n.role));
  }
  function inScope(a) {
    return ui.target === "all" || ui.target === nodeKey(a.node, a.role, a.counted);
  }
  function reasonsView(reasons) {
    return reasons.length ? `<ul class="assessment-reasons">${reasons.map(reason => `<li>${text(reason)}</li>`).join("")}</ul>` : "";
  }
  const rate = value => value == null ? "산출 불가" : `${metricText(value * 100)}%`;
  function detailResultView(d) {
    return `<section class="detail-result"><h5>${text(d.id)} · ${badge(d.verdict)}</h5>${facts([["검사 수행", d.executed ? "실행" : "미실행"], ["판정 사유", text(d.reason)], ["근거 경로", d.evidence.map(text).join("<br>") || "미제공"]])}${has(d, "expected") ? raw("기대값", d.expected, true) : ""}${has(d, "actual") ? raw("실제값", d.actual, true) : ""}</section>`;
  }
  function judgeView(judge, downloadable = true) {
    const messageLabel = judge.executed === false ? "평가 모델 메시지 · 준비됨 / 호출 미실행" : judge.executed === true ? (judge.error ? "평가 모델 메시지 · 호출 시도" : "평가 모델 전송 메시지") : "평가 모델 메시지 · 전송 여부 미기록";
    const status = judge.executed === false ? "평가 모델을 호출하지 않았습니다." : judge.error?.type === "CancelledError" ? "평가 모델 호출이 취소됐습니다. 남아 있는 시도 기록을 표시합니다." : judge.error ? `평가 모델 호출 오류: ${text(judge.error.type)}` : "";
    function entry(label, value, filename) {
      if (downloadable) return raw(label, value, false, filename);
      if (value === undefined) return `<p class="hint">${escape(label)}: 파일에 제공되지 않았습니다.</p>`;
      return `<details class="raw"><summary>${escape(label)}</summary><pre>${escape(typeof value === "string" ? value : JSON.stringify(value, null, 2))}</pre></details>`;
    }
    return `<div class="judge-record">${status ? `<p class="hint">${status}</p>` : ""}<p class="hint">평가 모델이 반환한 원응답과 검증·정규화한 세부 판정을 구분해 표시합니다. 저장된 내용을 다시 채점하지 않습니다.</p>${entry(messageLabel, judge.prompt?.messages, "judge-messages.json")}${entry("평가 모델 원응답 · SDK", judge.raw_response, "judge-raw-response.json")}${entry("평가 모델 응답 · 검증 전 JSON 또는 문자열", judge.response, "judge-response.json")}${entry("평가 모델 사용량", judge.model_usage, "judge-usage.json")}${downloadable ? raw("평가 모델 판정·입력·근거 전체 기록", judge, false, "judge.json") : ""}</div>`;
  }
  function modelAssessments(check, downloadable = true) {
    return (check.calls || []).map(call => `<section class="model-assessment"><h4>모델 호출 ${call.index} · ${text(call.name)}</h4>${facts([["호출 ID", text(call.id)], ["적용 기준 행", text(call.row_id)]])}<h5>검증·정규화한 세부 판정</h5>${downloadable ? call.details.map(detailResultView).join("") : call.details.map(d => `<section class="detail-result"><h5>${text(d.id)} · ${badge(d.verdict)}</h5><p>${text(d.reason)}</p><p class="hint">근거: ${d.evidence.map(text).join(", ") || "미제공"}</p></section>`).join("")}${downloadable && has(call, "format_contract") ? raw("적용한 출력 형식 기준", call.format_contract) : ""}${call.judge ? judgeView(call.judge, downloadable) : '<p class="hint">평가 모델 호출 기록 없음</p>'}</section>`).join("");
  }
  function checkResultView(check, caseId) {
    const d = definition(check.check);
    return `<details class="evidence-item"><summary><span>${axisLabel(check.axis)} · ${text(check.check)} · ${text(d.name || "항목명 미기록")}<small>${text(check.method)}</small></span>${badge(check.verdict)}</summary>
      ${facts([["검사 수행", check.executed ? "실행" : "미실행"], ["판정 사유", text(check.reason)], ["관련 검사", check.related_checks.map(text).join(", ") || "없음"]])}
      <h4>세부 항목 판정</h4>${check.details.map(detailResultView).join("") || '<p class="hint">세부 항목 미기록</p>'}
      ${modelAssessments(check)}
      ${raw("검사 기준 원문", currentAssessment()?.report.criteria?.checks?.[check.check])}</details>`;
  }
  function checkRows() {
    return (currentAssessment()?.report.assessments || []).filter(inScope).flatMap(a => a.checks.map(check => ({assessment: a, check})));
  }
  function metricTable(rows, node, detailed = false) {
    return `<div class="table-scroll"><table class="assessment-table check-results-table"><thead><tr><th>${detailed ? "검사 · 세부 항목" : "검사 항목"}</th><th>통과율</th><th>통과</th><th>실패</th><th>미판정</th><th>비적용</th><th>미실행</th><th>선행 실패로 생략</th></tr></thead><tbody>${orderedChecks(rows).map(r => {
      const d = definition(r.check);
      const label = detailed ? `${text(r.check)}<br>${text(r.id)}` : `<strong class="metric-check-name">${text(r.check)} ${text(d.name || "항목명 미기록")}</strong><small>${axisLabel(r.axis)} · ${text(r.method)}</small><p class="metric-check-description">${text(d.description || "검사 내용 미기록")}</p>`;
      return `<tr><td>${label}</td><td>${rate(r.rate)}</td>${[["passed", "통과"], ["failed", "실패"], ["undetermined", "미판정"], ["not_applicable", "비적용"]].map(([key, verdict]) => `<td><button type="button" class="link-button" data-score-check="${escape(JSON.stringify([node.node, node.role, r.check, verdict, detailed ? r.id : null]))}">${r[key]}</button></td>`).join("")}<td>${r.unexecuted}</td><td>${r.skipped_after_failure}</td></tr>`;
    }).join("") || '<tr><td colspan="8">저장된 지표가 없습니다.</td></tr>'}</tbody></table></div>`;
  }
  function functionalView(f, node) {
    const c = f.cases, v = f.verification;
    return `<div class="summary-cards functional-rollup"><div class="summary-card"><span>종합 판정</span><strong class="summary-verdict">${badge(f.verdict)}</strong></div><div class="summary-card"><span>전체 사례 통과율</span><strong>${rate(c.rate)}</strong><div class="case-verdict-counts"><span>통과 ${c.passed}</span><span>실패 ${c.failed}</span><span>미판정 ${c.undetermined}</span></div></div><div class="summary-card"><span>검증 진행</span><p class="verification-progress">검증 완료 ${v.completed_cases} / 전체 ${v.total_cases}</p>${v.missing_repetitions > 0 ? `<span>누락 반복 ${v.missing_repetitions}회</span>` : ""}</div></div>
      <h4>항목별 검사결과</h4>${metricTable(f.checks, node)}
      <h4>세부 항목 통과율</h4><p class="hint">검사별 세부 판정 단위의 저장된 집계입니다. 두 통과율은 진단용이며 합격 판정과 구분합니다.</p>${metricTable(f.details, node, true)}
      <details class="section case-assessment-details"><summary>사례별 판정·반복 충족·미완료 사유 (${c.items.length}사례)</summary><div class="table-scroll"><table class="assessment-table"><thead><tr><th>사례</th><th>필수 여부</th><th>판정·완료</th><th>기록 / 예정 반복</th><th>미완료·제외 사유</th></tr></thead><tbody>${c.items.map(i => `<tr><td>${text(i.case_id)}${node.node === "all" ? `<small>${text(nodeLabel(i.node, i.role))}</small>` : ""}</td><td>${i.required === true ? "필수" : i.required === false ? "선택" : "미지정"}</td><td>${badge(i.verdict)} · ${i.complete ? "완료" : "미완료"}</td><td>${i.recorded_repetitions} / ${i.planned_repetitions}</td><td>누락: ${text(i.missing_repetitions.join(", ") || "없음")}<br>미완료: ${text(i.incomplete_repetitions.join(", ") || "없음")}<br>제외: ${text(i.excluded_repetitions.join(", ") || "없음")}<p>${text(i.reason)}</p>${i.missing_expectations.length || i.missing_checks.length ? raw("누락 기대 항목·검사", {missing_expectations: i.missing_expectations, missing_checks: i.missing_checks}) : ""}</td></tr>`).join("")}</tbody></table></div></details>`;
  }
  function statisticsTable(rows, seconds = false) {
    const value = n => seconds ? time(n) : metricText(n);
    return `<div class="table-scroll"><table class="assessment-table"><thead><tr><th>측정 대상</th><th>표본</th><th>평균</th><th>중앙값</th><th>p95</th><th>누락</th><th>미종료</th></tr></thead><tbody>${rows.map(([label, s]) => `<tr><td>${text(label)}</td><td>${s.sample_count}</td><td>${value(s.mean)}</td><td>${value(s.median)}</td><td>${value(s.p95)}</td><td>${s.missing_count}</td><td>${s.unfinished_count}</td></tr>`).join("")}</tbody></table></div>`;
  }
  function operationalView(node) {
    const o = node.operational, f = o.failure_rate, t = o.response_time;
    const targets = (currentAssessment()?.report.criteria?.node_performance || []).filter(g => node.node === "all" ? selectedNodes().some(n => g.target === n.node && g.role === n.role) : g.target === node.node && g.role === node.role);
    const notices = [f.missing_count > 0 ? `실패 여부 미확인 ${f.missing_count}건` : "", f.unfinished_count > 0 ? `미종료 ${f.unfinished_count}건` : "", ...(o.source_issues || [])].filter(Boolean);
    const goals = `<section class="operational-goals"><h4>운영 목표 충족 여부</h4><div class="table-scroll"><table class="operational-goals-table"><thead><tr><th>목표</th><th>측정값</th><th>기준</th><th>판정</th></tr></thead><tbody>${node.performance.map(g => `<tr><td><details><summary>${g.metric === "failure_rate" ? "기술적 실행 실패율" : `${text(g.group === "normal" ? "정상" : g.group === "error" ? "오류" : g.group)} 응답시간 · ${text(g.statistic)}`}${node.node === "all" ? `<small>${text(nodeLabel(g.node, g.role))}</small>` : ""}</summary>${facts([["측정 완료", g.complete ? "완료" : "미완료"], ["표본 수", String(g.sample_count)], ["대상 사례", g.case_ids.map(text).join(", ")]])}${reasonsView(g.reasons)}</details></td><td>${g.metric === "failure_rate" ? rate(g.value_rate) : time(g.value_seconds)}</td><td>≤ ${g.metric === "failure_rate" ? rate(g.max_rate) : time(g.max_seconds)}</td><td>${badge(g.verdict)}</td></tr>`).join("") || '<tr><td colspan="4" class="dim">등록된 운영 목표가 없습니다.</td></tr>'}</tbody></table></div></section>`;
    return `<div class="summary-cards operational-rollup"><div class="summary-card"><span>운영 종합 판정</span><strong class="summary-verdict">${badge(o.verdict)}</strong></div><div class="summary-card"><span>기술적 실행 실패율</span><strong>${rate(f.rate)}</strong><span>실패 ${f.numerator} / 측정 ${f.denominator}건</span></div><div class="summary-card"><span>측정 확인 사항</span><div class="measurement-notices">${notices.map(notice => `<p>${text(notice)}</p>`).join("")}</div></div></div>${goals}
      <h4>호출 응답시간</h4>${statisticsTable([["정상", t.normal], ["오류", t.error]], true)}
      <h4>토큰·모델 호출·기술적 재시도</h4>${statisticsTable([["입력 토큰", o.tokens.input_tokens], ["출력 토큰", o.tokens.output_tokens], ["모델 호출 수", o.model_calls], ["기술적 재시도 합계", o.technical_retries], ["모델 재시도", o.technical_retries_by_kind.model], ["도구 재시도", o.technical_retries_by_kind.tool], ["하위 에이전트 재시도", o.technical_retries_by_kind.agent]])}
      ${o.unfinished_usage.length ? raw("미종료 실행의 관측 사용량", o.unfinished_usage) : ""}
      ${targets.length ? `<details class="section"><summary>운영 시험 조건</summary>${targets.map(g => facts([["대상 지표", g.metric === "failure_rate" ? "기술적 실행 실패율" : "호출 응답시간"], ["대상 사례", g.case_ids.map(text).join(", ")], ["측정 환경", text(g.environment)], ["입력 규모", text(g.data_size)]])).join("")}${raw("운영 목표 원본", targets)}</details>` : ""}`;
  }
  function scoreEvidenceView(node) {
    let rows = checkRows().filter(({assessment}) => !node || node.node === "all" || (assessment.node === node.node && assessment.role === node.role));
    const filter = ui.scoreFilter;
    if (filter) rows = rows.filter(({assessment: a, check: c}) => a.counted && (filter[0] === "all" || a.node === filter[0] && a.role === filter[1]) && c.check === filter[2] && (filter[4] ? c.details.some(d => d.executed && d.id === filter[4] && d.verdict === filter[3]) : c.executed && c.verdict === filter[3]));
    return `<section id="score-evidence" class="section" tabindex="-1"><h3>개별 판정 근거 · ${rows.length}건</h3>${filter ? `<p>${text(filter[0] === "all" ? "전체" : nodeLabel(filter[0], filter[1]))} / ${text(filter[2])} / ${badge(filter[3])}${filter[4] ? " / " + text(filter[4]) : ""} <button type="button" data-clear-score-filter>전체 근거 보기</button></p>` : ""}
      ${rows.slice(0, ui.scoreLimit).map(({assessment: a, check}) => {
        const run = currentBatch().runs.find(r => info(r).id === a.run_id && info(r).case_id === a.case_id && info(r).repetition === a.repetition);
        return `<div class="score-evidence-row"><p><strong>${text(a.case_id)} · ${a.repetition}회차</strong> · ${text(nodeLabel(a.node, a.role))}</p><p class="hint">${a.counted ? "" : "노드 지표 집계 제외 · "}${run ? `<button type="button" class="link-button" data-open-run="${escape(run.key)}">실행 입출력 확인 ↗</button>` : a.run_id === null ? "계획된 실행 · 실행 ID 없음" : `실행 원본 미제공 · ${text(a.run_id)}`}</p>${checkResultView(check, a.case_id)}</div>`;
      }).join("") || '<p class="hint">해당하는 검사 근거가 없습니다.</p>'}${rows.length > ui.scoreLimit ? `<button type="button" data-more-scores>판정 근거 더 보기 (${ui.scoreLimit} / ${rows.length})</button>` : ""}</section>`;
  }
  function selectionView(a) {
    const s = a.selection;
    return `<details class="section"><summary>평가 범위·선택·제외 사유</summary>${raw("선택한 사례·검사·기준 행", s.filters)}<div class="table-scroll"><table><thead><tr><th>사례 · 반복</th><th>검사 · 기대 항목</th><th>선택 상태</th><th>사유 · 기준 행</th></tr></thead><tbody>${s.decisions.map(d => `<tr><td>${text(d.case_id)} · ${text(d.repetition)}</td><td>${text(d.check)}<br>${text(d.expectation_id)}</td><td>${text({selected: "선택", excluded: "제외", undetermined: "미판정"}[d.status])}</td><td>${text(d.reason)}<br>${d.row_ids.map(text).join("<br>")}</td></tr>`).join("")}</tbody></table></div>${raw("반복별 적용 검사·기대 항목 계획", s.run_cases)}</details>`;
  }
  const aggregateTabLabels = [["functional", "기능 지표"], ["operational", "운영 지표"], ["info", "채점 정보"]];
  function aggregateTabs(contents) {
    return `<div class="aggregate-tabs" role="tablist" aria-label="전체 집계">${aggregateTabLabels.map(([key, label]) => `<button type="button" id="aggregate-tab-${key}" data-aggregate-tab="${key}" role="tab" aria-selected="${ui.aggregateTab === key}" aria-controls="aggregate-panel-${key}" tabindex="${ui.aggregateTab === key ? 0 : -1}">${label}</button>`).join("")}</div>${aggregateTabLabels.map(([key]) => `<section id="aggregate-panel-${key}" class="aggregate-tab-panel" role="tabpanel" aria-labelledby="aggregate-tab-${key}" tabindex="0"${ui.aggregateTab === key ? "" : " hidden"}>${contents[key]}</section>`).join("")}`;
  }
  function aggregateRoleChoices(nodes = selectedNodes()) {
    if (!nodes.length) return [];
    return [{key: "all", label: "전체", node: null}, ...nodes.map(n => ({key: nodeKey(n.node, n.role), node: n,
      label: nodes.filter(other => other.role === n.role).length > 1 ? `${targetNames[n.node] || n.node} / ${roleLabel(n.role)}` : roleLabel(n.role)}))];
  }
  function aggregateAllNodes(nodes) {
    const batch = currentBatch(), evaluation = currentAssessment()?.report;
    if (!remote?.loading && aggregateViewCache?.batch === batch && aggregateViewCache.evaluation === evaluation && aggregateViewCache.target === ui.target) return aggregateViewCache.value;
    const value = NodeAggregateMetrics.forAll(nodes, (batch?.runs || []).map(run => run.report).filter(Boolean), evaluation);
    aggregateViewCache = remote?.loading ? null : {batch, evaluation, target: ui.target, value};
    return value;
  }
  function nodeMetricViews(tab, withDetails = false) {
    const nodes = selectedNodes();
    if (!nodes.length) return '<p class="hint">선택한 대상의 노드 집계가 없습니다. 작업 선택만 실행한 결과는 노드 지표에서 제외됩니다.</p>' + (withDetails && tab === "functional" ? scoreEvidenceView() : "");
    const choices = aggregateRoleChoices(nodes);
    if (!choices.some(choice => choice.key === ui.aggregateRole)) ui.aggregateRole = "all";
    const roleId = index => `aggregate-role-${tab}-${index}`;
    const tabs = `<div class="aggregate-role-tabs" role="tablist" aria-label="${tab === "functional" ? "기능" : "운영"} 지표 역할">${choices.map(({key, label}, index) => {
      const selected = ui.aggregateRole === key;
      return `<button type="button" id="${roleId(index)}" role="tab" data-aggregate-role="${escape(key)}" data-role-metric="${tab}" aria-selected="${selected}" aria-controls="${roleId(index)}-panel" tabindex="${selected ? 0 : -1}">${text(label)}</button>`;
    }).join("")}</div>`;
    return tabs + choices.map((choice, index) => {
      const selected = choice.key === ui.aggregateRole;
      if (!selected) return `<section id="${roleId(index)}-panel" class="node-assessment" role="tabpanel" aria-labelledby="${roleId(index)}" tabindex="0" hidden></section>`;
      const n = choice.node ? NodeAggregateMetrics.forNode(choice.node) : aggregateAllNodes(nodes);
      let content = tab === "operational" ? operationalView(n) : functionalView(n.functional, n);
      if (withDetails && tab === "functional") {
        if (n.conflicting_assessments?.length || n.conflicting_evidence?.length) content += raw("충돌 판정·실행 근거", {assessments: n.conflicting_assessments, evidence: n.conflicting_evidence});
        content += scoreEvidenceView(n);
      }
      return `<section class="node-assessment" aria-label="${text(choice.label)}" id="${roleId(index)}-panel" role="tabpanel" aria-labelledby="${roleId(index)}" tabindex="0">${content}</section>`;
    }).join("");
  }
  function focusAggregateRole(tab) {
    const index = aggregateRoleChoices().findIndex(choice => choice.key === ui.aggregateRole);
    const button = $(`#aggregate-role-${tab}-${index}`);
    button?.focus({preventScroll: true});
    button?.scrollIntoView({block: "nearest", inline: "nearest"});
  }
  function revealAggregateRole() {
    const index = aggregateRoleChoices().findIndex(choice => choice.key === ui.aggregateRole);
    const button = $(`#aggregate-role-${ui.aggregateTab}-${index}`), nav = button?.parentElement;
    if (!nav) return;
    const start = button.offsetLeft - 3, end = button.offsetLeft + button.offsetWidth + 3;
    if (start < nav.scrollLeft) nav.scrollLeft = Math.max(0, start);
    else if (end > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = end - nav.clientWidth;
  }
  function scoringView(tab) {
    const record = currentAssessment();
    if (!record) return '<div class="empty"><h3>노드 채점 결과 미제공</h3><p>노드 채점 파일을 함께 열면 노드·역할별 지표와 검사 근거를 확인할 수 있습니다. 실행 기록만으로 합격 여부를 판정하지 않습니다.</p></div>';
    const a = record.report;
    if (tab !== "info") return nodeMetricViews(tab, true);
    return `<section class="section">${facts([["평가 이름", text(assessmentName(record))], ["채점 일시", dateTime(a.assessed_at)], ["채점 상태", a.status === "cancelled" ? "취소 · 부분 결과" : "채점 처리 완료"], ["채점 방식", a.method === "rules" ? "규칙 검사" : "규칙 검사 + AI 평가"], ["평가 대상 실행", text(batchName())], ["결과 파일", text(record.path.split(/[\\/]/).pop())]])}${recordLocation(record)}${reasonsView(a.limitations)}
      ${selectionView(a)}${raw("반복별 전체 채점 판정·누락 사유", a.runs)}${raw("실행 당시 기준과의 비교", a.provenance)}${raw("평가 모델 호출 기록 · 업무 노드 통계에서 제외", a.judge_trace)}<p class="hint">해시는 채점 당시 기록값이며 다시 계산하지 않습니다.</p>${raw("채점 기준·근거·평가기 해시", {criteria_sha256: a.criteria_sha256, evidence_sha256: a.evidence_sha256, evaluator_sha256: a.evaluator_sha256})}${raw("채점 결과 전체", a, false, assessmentFilename(record))}</section>`;
  }
  function scopedRuns() {
    return (currentBatch()?.runs || []).filter(run => {
      if (ui.target === "all") return true;
      const i = info(run);
      return (["node", "selection"].includes(i.unit) && targetKey(run) === ui.target) ||
        (currentAssessment()?.report.assessments || []).some(a => a.run_id === i.id && a.case_id === i.case_id && a.repetition === i.repetition && inScope(a));
    });
  }

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
      group.prepared = group.runs.find((run) => run.case)?.case || group.runs.find(run=>run.caseMeta)?.caseMeta;
    }
    return [...groups.values()];
  }

  function matchingRuns(group) {
    return group.runs.filter((run) => ui.status === "all" || info(run).status === ui.status);
  }

  function filteredGroups() {
    const references = remote ? remoteChecks() : [];
    return caseGroups().filter((group) => {
      if (remote?.filterCheck && !references.some(ref=>ref.case_id===group.id && ref.check_id===remote.filterCheck)) return false;
      const c = group.prepared;
      const query = ui.query.trim().toLocaleLowerCase();
      const checkTerms = group.runs.flatMap(run => appliedChecks(run).flatMap(id => {
        const definition = checkDefinition(run, id);
        return [id, definition?.category, definition?.name];
      }));
      const searchable = [caseDisplayName(group.runs[0]), ...(remote && !currentBatch().caseIndexLoaded ? [group.id,...references.filter(ref=>ref.case_id===group.id).map(ref=>ref.check_id)] : [group.id, c?.purpose, ...(c?.tags || []), ...checkTerms])].join(" ").toLocaleLowerCase();
      const required = c?.assessment?.required;
      return (!query || searchable.includes(query)) && matchingRuns(group).length > 0 &&
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
    $("#notice").hidden = !message;
  }

  function showIssues(issues) {
    const root = $("#load-issues");
    root.hidden = !issues.length;
    root.innerHTML = issues.length ? `<details class="issues"><summary>파일 확인 사항 ${issues.length}건 · 정상 기록은 계속 확인할 수 있습니다</summary><ul>${issues.map((issue) => `<li class="${issue.severity === "error" ? "error" : ""}"><strong>${escape(issue.path || "선택 파일")}${issue.line ? `:${escape(issue.line)}` : ""}</strong><br>${escape(issue.message)}</li>`).join("")}</ul></details>` : "";
  }

  function resetSelection() {
    if (remote) remote.filterCheck = null;
    aggregateViewCache = null;
    Object.assign(ui, {target: "all", caseKey: null, runKey: null, pageNumber: 0, query: "", status: "all", tag: "all", required: "all", scenarioOpen: new Set(), checkOpen: new Set(), closedMessages: new Set(), caseTab: "functional", scoreFilter: null, scoreLimit: 30});
    $("#case-search").value = "";
    $("#status-filter").value = "all";
    $("#required-filter").value = "all";
    $("#case-list-picker").open = !mobileLayout?.matches;
  }

  async function loadLocalResults() {
    if (typeof EvaluationLazy === "undefined") {
      setNotice("자동 조회 모듈을 읽지 못했습니다. 화면을 새로고침하세요.", true); return;
    }
    if (globalThis.location?.protocol === "file:") {
      setNotice("자동 조회는 로컬 HTTP 주소에서 사용할 수 있습니다. Eumi/ai에서 python -m http.server 8872 --bind 127.0.0.1 실행 후 http://127.0.0.1:8872/eval/viewers/nodes/ 를 여세요."); return;
    }
    const session = {client: EvaluationLazy.create({baseURL: new URL("../../../", document.baseURI)}), checks: new Set(), errors: new Map(), loading: true};
    remote = session;
    setNotice("평가 결과 목록 읽는 중…");
    try {
      session.index = await session.client.catalog();
      if (remote !== session) return;
      session.entries = session.index.batches.filter(entry => entry.units?.includes("node"));
      session.entries.sort((a,b) => Math.max(Date.parse(b.started_at)||0,...b.assessments.map(x=>Date.parse(x.assessed_at)||0))-Math.max(Date.parse(a.started_at)||0,...a.assessments.map(x=>Date.parse(x.assessed_at)||0)));
      ui.catalog = {batches: session.entries.map(EvaluationLazy.batchIndex), issues: session.index.issues || []};
      if (!session.entries.length) { setNotice("조회 목록은 정상적으로 읽었지만 노드 평가 묶음이 없습니다."); return; }
      ui.batch = 0; ui.assessmentKey = null; ui.page = "aggregate";
      $("#welcome").hidden = true; $("#application").hidden = false;
      showIssues(session.index.issues || []);
      await loadRemoteBatch(0);
    } catch (error) {
      if (remote !== session || error.name === "AbortError") return;
      setNotice(error.code === "not-found" ? "자동 조회 목록 파일이 없습니다. python -m eval.viewers.catalog로 목록을 생성하세요." : `자동 조회 목록 로딩 실패: ${error.message}`, true);
    }
  }

  async function loadRemoteBatch(index) {
    const session = remote, gate = session.client.begin("view");
    ui.batch = index; ui.assessmentKey = null; resetSelection(); ui.page = "aggregate";
    session.loading = true; session.checks.clear(); session.errors.clear();
    ui.scenarios = {scenarios: [], issues: []};
    // Release previous evidence; keep only catalog metadata for other batches.
    ui.catalog.batches = session.entries.map(EvaluationLazy.batchIndex);
    setNotice("선택한 묶음의 자료 자동 불러오는 중…"); showIssues([]); render();
    try {
      const batch = await session.client.batch(session.entries[index], {signal: gate.signal});
      if (remote !== session || !gate.current()) return;
      batch.assessments = batch.assessments.filter(a => !a.report.schema_version || a.report.schema_version === "node-evaluation-v1");
      batch.assessments.sort((a,b) => (Date.parse(b.report.assessed_at)||0) - (Date.parse(a.report.assessed_at)||0));
      ui.catalog.batches[index] = batch;
      await loadRemoteAssessment(batch.assessments[0]?.path || null);
    } catch (error) {
      if (remote !== session || !gate.current()) return;
      session.loading = false;
      setNotice(`묶음 자동 불러오기 실패: ${error.message}`, true); render();
    }
  }

  async function loadRemoteAssessment(path) {
    const session = remote, batch = currentBatch(), gate = session.client.begin("view");
    const current = () => remote === session && currentBatch() === batch && gate.current();
    ui.assessmentKey = path; ui.scoreFilter = null; ui.scoreLimit = 30;
    session.loading = true; session.checks.clear(); session.errors.clear();
    for (const item of batch.assessments) if (item.remoteMetadata) {
      item.report = item.remoteMetadata; item.lazy = true; item.partial = true; item.checks = [];
    }
    setNotice("시나리오·검사 결과·입출력 자동 불러오는 중…"); showIssues([]); render();
    const record = currentAssessment(), tasks = [];
    const add = (key, source, read) => tasks.push({key, source, read});
    const failed = (key, source, error) => session.errors.set(key, {path: error.path || source, message: error.message, severity: "error"});
    if (record) {
      try {
        const ref = session.entries[ui.batch].assessments.find(a => a.path === path) || record.ref;
        const loaded = await session.client.assessment(ref, {signal: gate.signal});
        if (!current()) return;
        if (loaded.report.schema_version !== "node-evaluation-v1") throw new Error("노드 평가 채점 형식이 아닙니다.");
        Object.assign(record, loaded, {remoteMetadata: record.remoteMetadata || record.report});
        applyRemoteRoles(batch, record.report);
      } catch (error) {
        if (!current()) return;
        failed("assessment", record.path, error);
      }
    }
    if (!current()) return;
    if (!batch.caseIndexLoaded && batch.entry.suite_path) add("suite", batch.entry.suite_path, async () => {
      const source = await session.client.raw(batch.entry.suite_path, {signal: gate.signal});
      const suite = JSON.parse(source.text.replace(/^\uFEFF/, ""));
      if (suite.schema_version !== "evaluation-suite-v1" || suite.id !== batch.report.suite_id || !Array.isArray(suite.cases)) throw new Error("입력 묶음의 사례 목록 연결이 올바르지 않습니다.");
      if (!current()) return;
      const cases = new Map(suite.cases.map(c => [c.id, {id:c.id, unit:c.unit, target:c.target, role:c.role, purpose:c.purpose, tags:c.tags, assessment:{required:c.assessment?.required, checks:c.assessment?.checks}}]));
      for (const run of batch.runs) {
        run.caseMeta = cases.get(info(run).case_id);
        if (run.caseMeta) run.role = run.caseMeta.role;
      }
      batch.caseIndexLoaded = true;
    });
    for (const run of batch.runs) if (run.lazy !== false || run.availability?.report === "missing" || run.availability?.case === "missing") add(`run:${run.key}`, run.path, async () => {
      const loaded = await session.client.run(batch, run, {signal: gate.signal, includeTrace: true});
      if (current()) Object.assign(run, loaded);
    });
    let scenarioFiles = null;
    if (!batch.scenariosLoaded && session.index.scenario_index) add("scenario-index", session.index.scenario_index, async () => {
      const source = await session.client.raw(session.index.scenario_index, {signal: gate.signal});
      const index = JSON.parse(source.text.replace(/^\uFEFF/, ""));
      if (index.schema_version !== "node-scenarios-v4" || !Array.isArray(index.scenarios) || !index.case_index) throw new Error("노드 시나리오 색인 형식이 올바르지 않습니다.");
      if (!current()) return;
      const caseIds = new Set(batch.runs.map(run => info(run).case_id));
      const wanted = new Set([...caseIds].flatMap(id => index.case_index[id]?.usages?.map(usage => usage.scenario_id) || []));
      const selected = {...index, scenarios:index.scenarios.filter(item => wanted.has(item.id)), case_index:Object.fromEntries(Object.entries(index.case_index).map(([id, value]) => [id, {...value, usages:value.usages.filter(usage => wanted.has(usage.scenario_id))}]))};
      scenarioFiles = [{path:source.path, text:JSON.stringify(selected)}];
      for (const reference of selected.scenarios) {
        const sourcePath = source.path.slice(0, source.path.lastIndexOf("/") + 1) + EvaluationLazy.relative(reference.file);
        add(`scenario:${sourcePath}`, sourcePath, async () => {
          const file = await session.client.raw(sourcePath, {signal:gate.signal});
          if (current()) scenarioFiles.push(file);
        });
      }
    });
    // Two workers bound file requests; each run reads report and case in parallel.
    let next = 0, completed = 0;
    async function readNext() {
      while (current() && next < tasks.length) {
        const task = tasks[next++];
        try { await task.read(); }
        catch (error) { if (current() && error.name !== "AbortError") failed(task.key, task.source, error); }
        if (!current()) return;
        setNotice(`자료 자동 불러오는 중 · ${++completed} / ${tasks.length}`);
      }
    }
    render();
    await Promise.all([readNext(), readNext()]);
    if (!current()) return;
    if (scenarioFiles) {
      ui.scenarios = NodeScenarios.parseFiles(scenarioFiles);
      batch.scenariosLoaded = !ui.scenarios.issues.length;
    }
    session.loading = false;
    showIssues([...(session.index.issues || []), ...session.errors.values(), ...(batch.issues || []), ...batch.runs.flatMap(run => run.issues || []), ...ui.scenarios.issues]);
    setNotice(""); render();
  }

  function remoteLink(path, label) {
    return `<a href="${escape(remote.client.url(path))}" target="_blank" rel="noopener" download>${escape(label)}</a>`;
  }
  function applyRemoteRoles(batch, report) {
    for (const run of batch.runs) {
      const roles = new Set(report.assessments.filter(a => a.run_id === run.entry?.run_id &&
        a.case_id === run.entry?.case_id && a.repetition === run.entry?.repetition &&
        (!["node", "selection"].includes(run.entry?.unit) || a.node === run.entry.target)).map(a => a.role));
      if (roles.size === 1) run.role = [...roles][0];
    }
  }
  function remoteChecks(record = currentAssessment()) {
    if (!record) return [];
    const references = new Map();
    for (const item of record.report.assessments || []) for (const check of item.checks) {
      references.set(JSON.stringify([item.case_id, check.check]), {case_id:item.case_id, check_id:check.check});
    }
    return [...references.values()];
  }
  function missingRemoteChecks() { return []; }
  function remoteAggregate() {
    const record = currentAssessment(), a = record?.report;
    const unavailable = !record ? '<p>이 묶음의 노드 채점 기록이 없습니다.</p>' : record.lazy ? `<p>${remote.loading ? "선택한 채점 자료 자동 불러오는 중…" : "채점 자료를 불러오지 못했습니다. 파일 확인 사항을 확인하세요."}</p>${remoteLink(record.path, "원본 파일 내려받기")}` : "";
    const info = unavailable || facts([["채점 ID", text(a.id)], ["채점 일시", dateTime(a.assessed_at)], ["채점 상태", text(a.status)]]);
    $("#aggregate-page").innerHTML = aggregateTabs({
      functional: unavailable || nodeMetricViews("functional"),
      operational: unavailable || nodeMetricViews("operational"),
      info,
    });
  }

  function renderNavigation() {
    const groups = new Map();
    function add(node, role, counted, caseId) {
      const key = nodeKey(node, role, counted);
      if (!groups.has(key)) groups.set(key, {key, node, role, counted, cases: new Set()});
      groups.get(key).cases.add(caseId);
    }
    for (const run of currentBatch().runs) {
      const i = info(run);
      if (["node", "selection"].includes(i.unit)) add(i.target, i.role, i.unit === "node", i.case_id);
    }
    for (const a of currentAssessment()?.report.assessments || []) add(a.node, a.role, a.counted, a.case_id);
    for (const n of currentAssessment()?.report.nodes || []) for (const c of n.functional.cases.items) add(n.node, n.role, true, c.case_id);
    if (ui.target !== "all" && !groups.has(ui.target)) ui.target = "all";
    const nodes = [...new Set([...groups.values()].map(g => g.node))];
    const allLabel = nodes.map(node => targetNames[node] || node).join(" · ") || "노드 평가";
    const navigationLabel = nodes.map(node => [nodeEvaluationIds.get(node), targetNames[node] || node].filter(Boolean).join(" ")).join(" · ") || "노드 평가";
    $("#target-nav").innerHTML = `<button type="button" class="target-button" data-target="all" aria-pressed="${ui.target === "all"}">${text(navigationLabel)}</button>` + [...groups.values()].map(g => `<button type="button" class="target-button" data-target="${escape(g.key)}" aria-pressed="${ui.target === g.key}"${g.counted ? "" : ` aria-label="${text(roleLabel(g.role))} · 작업 선택 · 집계 제외" title="작업 선택 · 집계 제외"`}><span>${text(roleLabel(g.role))}</span><span>${g.cases.size}</span></button>`).join("");
    const selected = groups.get(ui.target);
    $("#target-title").textContent = selected ? roleLabel(selected.role) : allLabel;
    $("#batch-select").innerHTML = ui.catalog.batches.map((batch, index) => `<option value="${index}"${index === ui.batch ? " selected" : ""}>${text(batchOptionLabel(batch))}</option>`).join("");
    const batch = currentBatch();
    for (const id of ["tag-filter","required-filter"]) $("#"+id).disabled=Boolean(remote && !batch.caseIndexLoaded);
    $("#case-search").placeholder=remote && !batch.caseIndexLoaded ? "사례 ID·검사 ID 검색" : "사례 ID·설명·태그·검사 검색";
    $("#context").textContent = `${caseGroups().length}개 사례 · ${scopedRuns().length}개 등록 실행 · ${batch.report ? `묶음 ${statusNames[batch.report.status]}` : "묶음 파일 미제공"}`;
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
      ui.scenarioOpen.clear();
    }
    $("#case-list-count").textContent = `${groups.length}개`;
    $("#case-list-selection").textContent = selected ? `선택: ${caseDisplayName(selected.runs[0])}` : "표시할 사례 없음";
    $("#case-rows").innerHTML = shown.length ? shown.map(group => {
      const c = group.prepared;
      return `<tr class="${group.key === ui.caseKey ? "selected" : ""}"><td><button type="button" class="case-button" data-case="${escape(group.key)}" aria-pressed="${group.key === ui.caseKey}"><span class="case-id">${text(caseDisplayName(group.runs[0]))}</span>${c?.purpose ? `<span class="case-purpose">${text(c.purpose)}</span>` : ""}</button></td></tr>`;
    }).join("") : '<tr><td><div class="empty"><h3>표시할 사례가 없습니다</h3><p>검색 조건을 바꾸거나 결과 파일이 있는 다른 대상을 선택하세요.</p></div></td></tr>';
    $("#pagination").innerHTML = `<span>${groups.length} / ${caseGroups().length}사례 · ${ui.pageNumber + 1} / ${totalPages}쪽</span><div><button type="button" data-page-step="-1" ${ui.pageNumber === 0 ? "disabled" : ""}>이전</button> <button type="button" data-page-step="1" ${ui.pageNumber + 1 >= totalPages ? "disabled" : ""}>다음</button></div>`;
    if (ui.page === "cases") renderDetail(selected, selectedRun(selected));
  }

  function metricScope(run) {
    const i = info(run), scope = {caseId: i.case_id, repetition: i.repetition, runId: i.id};
    if (ui.target !== "all") {
      const [, node, role] = JSON.parse(ui.target);
      Object.assign(scope, {node, role});
    } else if (["node", "selection"].includes(i.unit)) Object.assign(scope, {node: i.target, role: i.role});
    return scope;
  }

  function scenarioView(run) {
    const scope = metricScope(run);
    const memberships = NodeScenarios.forCase(ui.scenarios, scope.caseId, scope.node, scope.role);
    return `<section class="case-scenario"><h2 class="detail-title">${text(caseDisplayName(run))}</h2>${memberships.map(m => `<details class="scenario-disclosure" data-scenario-path="${escape(m.path)}"${ui.scenarioOpen.has(m.path) ? " open" : ""}><summary>시나리오 도식</summary><ol class="scenario-flow">${m.steps.map((step, index) => {
      const current = m.stepIds.includes(step.step_id);
      return `<li class="scenario-step${current ? " current" : ""}"${current ? ' aria-current="step"' : ""}><span class="step-position">${index + 1}${current ? " · 현재 사례" : ""}</span><strong>${text(targetNames[step.node] || step.node)}</strong><small>${text(targetNames[step.role] || step.role)}</small></li>`;
    }).join("")}</ol></details>`).join("") || '<p class="hint">소속 시나리오 자료가 없거나 사례 위치를 확인할 수 없습니다.</p>'}</section>`;
  }

  const checkKey = check => JSON.stringify([check.check, check.axis ?? null, check.method ?? null]);
  const scopeTitles = ["개별 실행 결과", "사례 반복 집계 결과", "노드·역할 전체 결과"];
  const operationalScopeTitles = ["개별 결과", "반복 결과", "전체 결과"];

  function comparisonGroups(group, run, nodes) {
    const evaluation = currentAssessment()?.report, scope = metricScope(run);
    const repeated = NodeRunMetrics.forCase(group.runs.map(r => r.report).filter(Boolean), evaluation, scope).nodes;
    const groups = new Map();
    function ensure(node, role) {
      const key = nodeKey(node, role);
      if (!groups.has(key)) groups.set(key, {node, role, runs: [], repeated: null, overall: null});
      return groups.get(key);
    }
    for (const n of nodes) ensure(n.node, n.role).runs.push(n);
    for (const n of repeated) ensure(n.node, n.role).repeated = n;
    if (!groups.size && scope.node) ensure(scope.node, scope.role);
    const selectionOnly = info(run).unit === "selection";
    for (const n of (evaluation?.nodes || [])) {
      const g = groups.get(nodeKey(n.node, n.role));
      if (g && !selectionOnly) g.overall = n;
    }
    return [...groups.values()].map(g => ({...g, selectionOnly, missingChecks: missingRemoteChecks(scope.caseId)}));
  }

  function comparisonColumns(contents, verdicts) {
    return `<div class="comparison-scroll"><div class="comparison-grid${verdicts ? " summary-grid" : ""}">${contents.map((content, index) => `<section data-result-scope="${["run", "case", "node"][index]}">${verdicts ? `<header class="scope-heading"><h5>${scopeTitles[index]}</h5><div class="scope-verdict">${verdicts[index]}</div></header><div class="scope-content">${content}</div>` : `<h5>${scopeTitles[index]}</h5>${content}`}</section>`).join("")}</div></div>`;
  }

  function metricValues(rows, caption) {
    return `<table class="metric-values"><caption class="sr-only">${escape(caption)}</caption><tbody>${rows.map(([label, value]) => `<tr><th scope="row">${escape(label)}</th><td>${metricText(value)}</td></tr>`).join("")}</tbody></table>`;
  }

  function rateSummary(row) {
    if (!row) return '<p class="hint">집계 미제공</p>';
    return `<div class="metric-rate"><strong>${rate(row.rate)}</strong></div>${metricValues([["통과", row.numerator], ["평가 대상", row.denominator], ["실패", row.failed], ["미판정", row.undetermined], ["비적용", row.not_applicable], ["미실행", row.unexecuted], ["선행 실패로 생략", row.skipped_after_failure]], "검사 결과 건수")}`;
  }

  function individualCheck(check, index, count) {
    return `<div class="individual-check">${count > 1 ? `<p class="hint">노드 기록 ${index + 1}</p>` : ""}${check ? `<p>${badge(check.verdict)}${check.executed ? "" : " · 미실행"}</p><p class="check-reason">${text(check.reason)}</p>` : '<p class="hint">선택한 실행의 채점 결과 미제공</p>'}</div>`;
  }

  function checkPrompt(individual, method) {
    if (method === "규칙 기반") return "";
    const noPrompt = () => '<p class="hint">선택한 실행에 저장된 평가 프롬프트가 없습니다.</p>';
    const content = individual.map((check, index) => {
      const calls = check?.calls || [];
      return `<section class="prompt-node">${individual.length > 1 ? `<h5>노드 기록 ${index + 1}</h5>` : ""}${calls.length ? calls.map(call => {
        const judge = call.judge, messages = judge?.prompt?.messages;
        const saved = Array.isArray(messages) && messages.length > 0 && messages.every(message => typeof message?.role === "string" && typeof message?.content === "string");
        return `<section class="prompt-call"><h5>모델 호출 ${text(call.index)} · ${text(call.name)}</h5>${saved ? `${judge.executed === false ? `<p class="hint">준비된 평가 프롬프트 · 평가 모델 미실행${judge.reason ? `<br>${text(judge.reason)}` : ""}</p>` : ""}${messages.map(message => {
          const role = {system: "시스템 메시지", user: "사용자 메시지", assistant: "어시스턴트 메시지"}[message.role] || message.role;
          return `<section class="prompt-message"><h6>${text(role)}</h6><pre class="prompt-text">${escape(message.content)}</pre></section>`;
        }).join("")}` : noPrompt()}</section>`;
      }).join("") : noPrompt()}</section>`;
    }).join("") || noPrompt();
    return `<details class="check-prompt"><summary>평가 프롬프트</summary><div class="check-prompt-content" tabindex="0">${content}</div></details>`;
  }

  function checkComparison(g, check) {
    const matches = row => checkKey(row) === checkKey(check);
    const individual = g.runs.map(n => n.checks.find(matches));
    const repeated = g.repeated?.functional.checks.find(matches);
    const overall = g.overall?.functional.checks.find(matches);
    const details = check.check === "N-F.1" ? [...new Set([
      ...individual.flatMap(c => (c?.details || []).map(d => d.id)),
      ...(g.repeated?.functional.details || []).filter(d => d.check === check.check).map(d => d.id),
      ...(g.overall?.functional.details || []).filter(d => d.check === check.check).map(d => d.id),
    ])] : [];
    const d = definition(check.check), metadata = [check.axis ? axisLabel(check.axis) : "", check.method ? text(check.method) : ""].filter(Boolean).join(" · ");
    const unavailable = '<p class="hint">선택한 실행의 채점 결과 미제공</p>';
    const missing = g.missingChecks?.some(ref => ref.check_id === check.check);
    const recorded = individual.filter(Boolean);
    const verdicts = missing ? '<span class="chip error">불러오기 실패</span>' : recorded.length ? recorded.map((result, index) => `${recorded.length > 1 ? `<span class="check-record-label">기록 ${index + 1}</span>` : ""}${badge(result.verdict)}`).join("") : '<span class="chip">판정 미제공</span>';
    const key = JSON.stringify([ui.runKey, g.node, g.role, checkKey(check)]);
    const card = body => `<details class="check-comparison" data-check="${escape(check.check)}" data-axis="${escape(check.axis || "")}" data-method="${escape(check.method || "")}" data-check-key="${escape(key)}"${ui.checkOpen.has(key) ? " open" : ""}><summary><span class="check-title-row"><span class="check-name">${text(check.check)} · ${text(d.name || "항목명 미기록")}</span><span class="check-verdict">${verdicts}</span>${metadata ? `<span class="check-meta">${metadata}</span>` : ""}</span><span class="check-description">${text(d.description || "검사 내용 미기록")}</span></summary><div class="check-comparison-body">${body}</div></details>`;
    if (missing) {
      const message = '<p class="error">검사 자료 불러오기 실패 · 판정과 집계를 표시할 수 없습니다.</p>';
      return card(comparisonColumns([message, message, rateSummary(overall)]));
    }
    return card(`${comparisonColumns([
      individual.length ? individual.map((c, index) => individualCheck(c, index, individual.length)).join("") : unavailable,
      rateSummary(repeated), g.selectionOnly ? '<p class="hint">노드 지표 집계 제외</p>' : rateSummary(overall),
    ])}${details.length ? `<details class="check-details"><summary>세부 항목별 결과·통과율 (${details.length}개)</summary>${details.map(id => {
      const results = individual.map(c => c?.details.find(d => d.id === id));
      return `<div class="detail-comparison"><h5>${text(id)}</h5>${comparisonColumns([
        results.some(Boolean) ? results.map((d, index) => individualCheck(d, index, results.length)).join("") : '<p class="hint">세부 판정 미제공</p>',
        rateSummary(g.repeated?.functional.details.find(d => d.check === check.check && d.id === id)),
        g.selectionOnly ? '<p class="hint">노드 지표 집계 제외</p>' : rateSummary(g.overall?.functional.details.find(d => d.check === check.check && d.id === id)),
      ])}</div>`;
    }).join("")}</details>` : ""}${check.check !== "N-F.1" ? checkPrompt(individual, check.method) : ""}`);
  }

  function functionalSummary(g) {
    const c = g.repeated?.caseSummary, f = g.overall?.functional;
    const runSummary = g.runs.map((n, index) => {
      if (g.missingChecks?.length) return '<p class="error">일부 검사 자료 불러오기 실패 · 검사 건수 미제공</p>';
      if (!n.functional) return '<p class="hint">채점 결과 미제공</p>';
      const counts = n.functional.checks;
      return metricValues([...(g.runs.length > 1 ? [["노드 기록", index + 1]] : []), ["검사 통과", counts.passed], ["검사 실패", counts.failed], ["미판정", counts.undetermined], ["비적용", counts.notApplicable], ["미실행", counts.notExecuted]], "개별 실행 검사 건수");
    }).join("") || '<p class="hint">채점 결과 미제공</p>';
    const repeatSummary = c ? metricValues([["기록 반복", c.recorded_repetitions], ["예정 반복", c.planned_repetitions], ["누락 반복", c.missing_repetitions.join(", ") || "없음"], ["미완료 반복", c.incomplete_repetitions.join(", ") || "없음"], ["제외 반복", c.excluded_repetitions.join(", ") || "없음"]], "사례 반복 완료 현황") : '<p class="hint">사례 판정 미제공</p>';
    const nodeSummary = g.selectionOnly ? '<p class="hint">노드 지표 집계 제외</p>' : f ? metricValues([["통과 사례", f.cases.numerator], ["평가 대상 사례", f.cases.denominator], ["필수 사례 완료", f.verification.completed_cases], ["필수 사례 미완료", f.verification.incomplete_cases]], "노드 역할 전체 완료 현황") : '<p class="hint">노드 집계 미제공</p>';
    const verdicts = [g.runs.map((n, index) => `${g.runs.length > 1 ? `<span class="check-record-label">기록 ${index + 1}</span>` : ""}${badge(n.verdict)}`).join(""), c ? badge(c.verdict) : "", !g.selectionOnly && f ? badge(f.verdict) : ""];
    return `<section class="functional-summary">${comparisonColumns([runSummary, repeatSummary, nodeSummary], verdicts)}</section>`;
  }

  function functionalComparisons(groups, run) {
    return `<div class="functional-overview">${groups.map(g => `<section class="case-node" aria-label="${text(nodeLabel(g.node, g.role))}">${functionalSummary(g)}</section>`).join("")}</div>${groups.map(g => {
      const checks = new Map();
      for (const row of [...g.runs.flatMap(n => n.checks), ...(g.repeated?.functional.checks || [])]) checks.set(checkKey(row), row);
      if (["node", "selection"].includes(info(run).unit)) {
        for (const id of [...appliedChecks(run), ...missingRemoteChecks(info(run).case_id).map(ref => ref.check_id)]) {
          if ([...checks.values()].some(c => c.check === id)) continue;
          const d = currentAssessment()?.report.criteria?.checks?.[id];
          const row = {check: id, axis: d?.axis, method: d?.method};
          checks.set(checkKey(row), row);
        }
      }
      return `<section class="case-node case-checks" aria-label="${text(nodeLabel(g.node, g.role))}">${orderedChecks([...checks.values()]).filter(c => !remote?.filterCheck || c.check === remote.filterCheck).map(c => checkComparison(g, c)).join("") || '<p class="hint">검사 항목 미제공</p>'}</section>`;
    }).join("") || '<p class="hint">선택한 실행의 채점 결과 미제공</p>'}`;
  }

  function statisticSummary(s, seconds = false) {
    if (!s) return '<span class="hint">측정 미제공</span>';
    const value = v => v == null ? "미기록" : seconds ? `${metricNumber(v)}초` : metricNumber(v);
    return metricValues([["표본", s.sample_count], ["평균", value(s.mean)], ["중앙값", value(s.median)], ["p95", value(s.p95)], ["누락", s.missing_count], ["미종료", s.unfinished_count]], "운영 지표 통계");
  }

  function operationalComparisons(groups) {
    const incomplete = groups.some(g => g.missingChecks?.length);
    if (incomplete) groups = groups.map(g => g.missingChecks?.length ? {...g, runs: [], repeated: null} : g);
    const measurements = [["호출 응답시간", "elapsedSeconds", true], ["입력 토큰", "inputTokens"], ["출력 토큰", "outputTokens"], ["모델 호출 수", "modelCalls"], ["기술적 재시도", "technicalRetries"]];
    function observed(g, key, seconds) {
      return g.runs.map((n, index) => {
        const o = n.operational;
        return `${g.runs.length > 1 ? `<p class="hint">노드 기록 ${index + 1}</p>` : ""}<p>${seconds ? time(o[key]) : metricText(o[key])}</p>${o[key] == null && (o.missingReasons?.[key] || o.reason) ? `<small>${text(o.missingReasons?.[key] || o.reason)}</small>` : ""}`;
      }).join("") || "미기록";
    }
    function aggregate(o, key, seconds) {
      if (!o) return "집계 미제공";
      if (key === "elapsedSeconds") return `<strong>정상</strong>${statisticSummary(o.response_time.normal, true)}<strong>오류</strong>${statisticSummary(o.response_time.error, true)}${metricValues([["미분류", o.response_time.unclassified_count], ["미종료", o.response_time.unfinished_count]], "응답시간 집계 상태")}`;
      const s = {inputTokens: o.tokens.input_tokens, outputTokens: o.tokens.output_tokens, modelCalls: o.model_calls, technicalRetries: o.technical_retries}[key];
      return statisticSummary(s, seconds);
    }
    function failure(o) {
      return o ? `<strong>${rate(o.failure_rate.rate)}</strong>${metricValues([["실패", o.failure_rate.numerator], ["평가 대상", o.failure_rate.denominator], ["누락", o.failure_rate.missing_count], ["미종료", o.failure_rate.unfinished_count]], "기술적 실행 실패 건수")}` : "집계 미제공";
    }
    const cells = values => values.map((value, index) => `<td data-result-scope="${["run", "case", "node"][index]}">${value}</td>`).join("");
    return `<h3>운영 지표</h3>${incomplete ? '<p class="error">일부 검사 자료를 불러오지 못해 선택한 모델 호출 전체를 확인할 수 없습니다. 해당 개별·사례 반복 운영 지표는 표시하지 않습니다.</p>' : ""}<p class="hint">선택한 모델 호출의 실측값과 같은 사례의 반복 집계, 노드·역할 전체 집계를 함께 표시합니다.</p>${groups.map(g => {
      const repeated = g.repeated?.operational, overall = g.overall?.operational;
      const caseSummary = g.repeated?.caseSummary;
      const singleRun = caseSummary?.planned_repetitions === 1 && caseSummary.recorded_repetitions === 1 && g.repeated.runs.length === 1;
      const repeatedResult = content => singleRun ? '<span class="hint">반복 해당 없음</span>' : content;
      const excluded = '노드 지표 집계 제외';
      return `<section class="case-node"><h4>${text(nodeLabel(g.node, g.role))}</h4><div class="table-scroll"><table class="operational-comparison"><thead><tr><th>측정 항목</th>${operationalScopeTitles.map(title => `<th>${title}</th>`).join("")}</tr></thead><tbody><tr><th scope="row">기술적 실행 실패</th>${cells([
        g.runs.map((n, index) => `${g.runs.length > 1 ? `<p class="hint">노드 기록 ${index + 1}</p>` : ""}${n.operational.technicalFailure === true ? "실패" : n.operational.technicalFailure === false ? "실패 없음" : "미기록"}`).join("<br>") || "미기록",
        repeatedResult(failure(repeated)), g.selectionOnly ? excluded : failure(overall),
      ])}</tr>${measurements.map(([label, key, seconds]) => `<tr><th scope="row">${label}</th>${cells([observed(g, key, seconds), repeatedResult(aggregate(repeated, key, seconds)), g.selectionOnly ? excluded : aggregate(overall, key, seconds)])}</tr>`).join("")}</tbody></table></div>${g.runs.filter(n => n.operational.unfinished && n.operational.observed).map(n => `<p class="hint">미종료 실행의 관측 사용량</p>${metricValues([["입력 토큰", n.operational.observed.inputTokens], ["출력 토큰", n.operational.observed.outputTokens], ["모델 호출", n.operational.observed.modelCalls]], "미종료 실행 관측 사용량")}`).join("")}</section>`;
    }).join("") || '<p class="hint">선택한 노드의 측정 미제공</p>'}`;
  }

  function structuredValue(label, value, className, hint = "") {
    return `<details class="${className}"${ui.inputOpen ? " open" : ""}><summary>${escape(label)}</summary>${hint ? `<p class="hint">${escape(hint)}</p>` : ""}${NodeValues.render(value)}</details>`;
  }

  function modelInput(calls, hint) {
    const names = {system: "시스템 메시지", developer: "개발자 메시지", user: "사용자 메시지", human: "사용자 메시지", assistant: "어시스턴트 메시지", ai: "어시스턴트 메시지", tool: "도구 메시지", function: "함수 메시지"};
    const content = calls.map((call, callIndex) => {
      const messages = call.input;
      const isMessages = Array.isArray(messages) && messages.length > 0 && messages.every(message =>
        message && typeof message === "object" && has(message, "content") && typeof (message.role ?? message.type) === "string");
      const body = isMessages ? messages.map((message, messageIndex) => {
        const role = message.role ?? message.type;
        const original = typeof message.content === "string" ? message.content : JSON.stringify(message.content, null, 2);
        const key = JSON.stringify([ui.runKey, call.id ?? callIndex, messageIndex]);
        return `<details class="prompt-message input-message" data-message-key="${escape(key)}"${ui.closedMessages.has(key) ? "" : " open"}><summary>${text(names[role] || role)}</summary><pre class="prompt-text">${escape(original)}</pre></details>`;
      }).join("") : NodeValues.render(messages ?? undefined);
      return `<section class="prompt-call">${calls.length > 1 ? `<h5>모델 호출 ${text(call.index)} · ${text(call.name)}</h5>` : ""}${body}</section>`;
    }).join("");
    return `<details class="case-input"${ui.inputOpen ? " open" : ""}><summary>입력</summary>${hint ? `<p class="hint">${escape(hint)}</p>` : ""}${content}</details>`;
  }

  function outputValue(value) {
    if (typeof value !== "string") return value;
    try { return JSON.parse(value); }
    catch { return value; }
  }

  function caseIO(run, nodes) {
    const i = info(run), evaluation = currentAssessment()?.report;
    const calls = nodes.flatMap(n => n.calls);
    let unique = [...new Map(calls.map(c => [c.id, c])).values()], originalBoundary = false;
    const unread = missingRemoteChecks(i.case_id);
    if (!unique.length && unread.length && ["node", "selection"].includes(i.unit)) {
      // Display the standalone execution boundary without changing scored-call metrics.
      unique = NodeRunMetrics.forRun(run.report, null, metricScope(run)).nodes.flatMap(node => node.calls);
      originalBoundary = unique.length > 0;
    }
    const scoringCase = evaluation?.criteria?.effective_cases?.find(c => c.id === i.case_id) || evaluation?.criteria?.cases?.find(c => c.id === i.case_id);
    const hasInput = unique.some(c => c.input != null);
    const input = hasInput ? (unique.length === 1 ? unique[0].input : unique.map(c => ({호출: c.name, 입력: c.input ?? "미제공"}))) : run.case?.initial ?? scoringCase?.initial;
    const callOutput = call => outputValue(call.raw ?? call.output ?? undefined);
    const output = unique.length ? (unique.length === 1 ? callOutput(unique[0]) : unique.map(c => ({호출: c.name, 출력: callOutput(c)}))) : ["node", "selection"].includes(i.unit) ? outputValue(run.report?.output?.raw ?? run.report?.output) : undefined;
    const awaitingSelection = !unique.length && unread.length > 0;
    const inputHint = originalBoundary ? "실행 원본의 단독 모델 호출 입력입니다. 검사 파일을 불러오지 못해 채점 대상 호출과의 연결은 확인할 수 없습니다." :
      awaitingSelection ? "검사 파일을 불러오지 못해 채점 대상 모델 호출을 연결할 수 없습니다. 준비 입력이 있으면 구분해 표시합니다." :
      !hasInput && input !== undefined ? "데이터셋의 준비 입력입니다. 실제 모델 입력은 미제공입니다." : "";
    return `<h3 id="case-io-title">입출력</h3>${hasInput ? modelInput(unique, inputHint) : structuredValue("입력", input, "case-input", inputHint)}<details class="case-output"${ui.outputOpen ? " open" : ""}><summary>출력</summary>${NodeValues.render(output)}</details>`;
  }

  function renderDetail(group, run) {
    stopResize();
    $("#case-detail").setAttribute("aria-busy", String(Boolean(remote?.loading)));
    if (remote?.loading) { $("#case-detail").innerHTML = '<p>시나리오·검사 결과·입출력 자동 불러오는 중…</p>'; return; }
    if (!group || !run) {
      $("#case-detail").innerHTML = '<div class="empty"><h3>사례를 선택하세요</h3><p>목록에서 확인할 사례를 선택하면 검사 결과·지표와 입출력을 볼 수 있습니다.</p></div>';
      return;
    }
    ui.runKey = run.key;
    const i = info(run), evaluation = currentAssessment()?.report;
    const nodes = NodeRunMetrics.forRun(run.report, evaluation, metricScope(run)).nodes;
    const tabs = [["functional", "기능 지표"], ["operational", "운영 지표"]];
    const comparisons = comparisonGroups(group, run, nodes);
    const content = ui.caseTab === "functional" ? functionalComparisons(comparisons, run) : operationalComparisons(comparisons);
    $("#case-detail").innerHTML = `<button type="button" class="back-to-list" data-back-to-list>← 목록으로</button>${scenarioView(run)}
      <div class="selectors"><label>반복 실행<select id="run-select">${matchingRuns(group).map(r => `<option value="${escape(r.key)}"${r.key === run.key ? " selected" : ""}>${text(info(r).repetition)}회차 · ${text(statusNames[info(r).status] || info(r).status)}</option>`).join("")}</select></label></div>
      <div class="case-results-split"><section id="case-metrics-pane" class="case-metrics-pane" aria-label="기능 및 운영 지표" tabindex="0">
        <div class="case-tabs" role="tablist" aria-label="사례 지표 영역">${tabs.map(([key, label]) => `<button type="button" id="case-tab-${key}" data-case-tab="${key}" role="tab" aria-selected="${ui.caseTab === key}" aria-controls="case-tab-panel" tabindex="${ui.caseTab === key ? 0 : -1}">${label}</button>`).join("")}</div>
        <section id="case-tab-panel" class="case-tab-panel" role="tabpanel" aria-labelledby="case-tab-${ui.caseTab}" tabindex="0">${content}</section>
      </section><div id="case-splitter" role="separator" tabindex="0" aria-label="지표와 입출력 영역 너비 조절" aria-orientation="vertical" aria-controls="case-metrics-pane case-io-pane" aria-valuemin="25" aria-valuemax="75" aria-valuenow="${ui.metricsWidth}" title="드래그하거나 방향키로 너비를 조절하세요"></div>
      <section id="case-io-pane" class="case-io-pane" aria-labelledby="case-io-title" tabindex="0">${caseIO(run, nodes)}</section></div>`;
    applySplitWidth(ui.metricsWidth);
  }

  function renderAggregate() {
    if (remote) { remoteAggregate(); return; }
    const batch = currentBatch(), runs = scopedRuns();
    const loaded = runs.filter((run) => run.report).length;
    const b = batch.report;
    const records = `<h2 class="section">선택 범위의 기록 현황</h2><p class="hint">아래 건수는 불러온 파일과 목록의 수입니다. 평가 지표나 합격률이 아닙니다.</p>
      <div class="summary-cards"><div class="summary-card"><span>사례</span><strong>${caseGroups().length}</strong><span>선택한 대상</span></div><div class="summary-card"><span>등록 실행</span><strong>${runs.length}</strong><span>반복 실행 포함</span></div><div class="summary-card"><span>읽은 결과 파일</span><strong>${loaded}</strong><span>누락·오류 ${runs.length - loaded}건</span></div></div>
      <div class="section"><h3>묶음 전체의 저장 정보</h3>${b ? facts([["평가 대상 실행", text(batchName())], ["예정 실행", `${text(b.planned_runs)}회`], ["등록 실행", `${b.runs.length}회`], ["아직 등록되지 않은 예정 실행", `${b.planned_runs - b.runs.length}회`], ["묶음 상태", badge(b.status)], ["시작", dateTime(b.started_at)], ["종료", dateTime(b.ended_at)]]) : '<p class="hint">batch.json이 없어 예정 실행 수와 묶음 종료 상태를 알 수 없습니다.</p>'}${b?.failure ? raw("묶음 중단 오류·취소", b.failure, true, "batch-failure.json") : ""}<p class="hint">목록 필터와 관계없이 묶음 파일의 값을 표시합니다. 예정됐지만 등록되지 않은 실행의 사례 ID·반복 순번은 추정하지 않습니다.</p></div>
      <div class="section"><h3>실행별 관측값·평가 상태</h3><p class="hint">선택한 대상 범위 · 목록 검색·필터와 별도. 실행 관측값과 선택한 채점 기록의 판정을 구분해 표시합니다.</p><div class="table-scroll"><table class="aggregate-table"><thead><tr><th>사례·반복</th><th>대상</th><th>실행 상태</th><th>관측 시간</th><th>채점</th><th>판정</th></tr></thead><tbody>${runs.map((run) => {
      const i = info(run);
      return `<tr><td><button type="button" class="link-button" data-open-run="${escape(run.key)}">${text(i.case_id)} · ${text(i.repetition)}회차 ↗</button></td><td>${escape(targetLabel(run))}</td><td>${badge(i.status)}</td><td>${time(run.report?.run.elapsed_seconds)}</td><td>${scoredRun(run) ? "별도 채점 기록" : "미제공"}</td><td>${scoredRun(run) ? badge(scoredRun(run).verdict) : "미제공"}</td></tr>`;
    }).join("") || '<tr><td colspan="6">등록된 실행이 없습니다.</td></tr>'}</tbody></table></div></div>
      <div class="section">${raw("묶음 결과 원문", b || undefined, false, "batch.json")}${raw("입력 묶음 스냅샷", batch.suite || undefined, false, "suite.json")}</div>`;
    $("#aggregate-page").innerHTML = aggregateTabs({functional: scoringView("functional"), operational: scoringView("operational"), info: scoringView("info") + records});
  }

  function render() {
    if (!ui.catalog) return;
    downloads = [];
    renderNavigation();
    $("#assessment-toolbar").innerHTML = assessmentPicker();
    for (const button of document.querySelectorAll(".page-tabs [data-page]")) button.setAttribute("aria-pressed", String(button.dataset.page === ui.page));
    $("#case-page").hidden = ui.page !== "cases";
    $("#aggregate-page").hidden = ui.page !== "aggregate";
    // Keep sidebar navigation available on both pages.
    renderCases();
    if (ui.page === "aggregate") { renderAggregate(); revealAggregateRole(); }
  }

  function openRun(key) {
    const run = scopedRuns().find((r) => r.key === key);
    if (!run) return;
    const i = info(run);
    ui.caseKey = JSON.stringify([i.case_id, i.unit, i.target]);
    ui.runKey = key;
    ui.page = "cases";
    ui.scenarioOpen.clear();
    ui.query = ""; ui.status = "all"; ui.tag = "all"; ui.required = "all";
    $("#case-search").value = "";
    $("#status-filter").value = "all";
    $("#required-filter").value = "all";
    ui.pageNumber = Math.floor(caseGroups().findIndex((group) => group.key === ui.caseKey) / PAGE_SIZE);
    if (mobileLayout?.matches) $("#case-list-picker").open = false;
    render();
    const pane = $("#case-io-pane");
    pane.focus({preventScroll: true});
    pane.scrollIntoView({block: "start"});
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (has(button.dataset, "download")) {
      const item = downloads[Number(button.dataset.download)];
      if (!item) return;
      const data = item.jsonl ? item.value.map((line) => JSON.stringify(line)).join("\n") + "\n" : JSON.stringify(item.value, null, 2);
      const url = URL.createObjectURL(new Blob([data], {type: item.jsonl ? "application/x-ndjson;charset=utf-8" : "application/json;charset=utf-8"}));
      const link = document.createElement("a");
      link.href = url; link.download = item.name; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return;
    }
    if (button.dataset.openRun) { openRun(button.dataset.openRun); return; }
    if (button.dataset.scoreCheck) {
      if (remote) {
        const [node,role,check]=JSON.parse(button.dataset.scoreCheck);
        if (node !== "all") ui.target=nodeKey(node,role);
        ui.page="cases"; ui.caseKey=null; ui.runKey=null; ui.pageNumber=0; remote.filterCheck=check;
        render(); return;
      }
      ui.aggregateTab = "functional"; ui.scoreFilter = JSON.parse(button.dataset.scoreCheck); ui.aggregateRole = ui.scoreFilter[0] === "all" ? "all" : nodeKey(ui.scoreFilter[0], ui.scoreFilter[1]); ui.scoreLimit = 30; render();
      $("#score-evidence").focus({preventScroll: true}); $("#score-evidence").scrollIntoView({block: "start"}); return;
    }
    if (button.dataset.target) {
      resetSelection(); ui.target = button.dataset.target;
    }
    else if (button.dataset.case) {
      if (ui.caseKey !== button.dataset.case) ui.scenarioOpen.clear();
      ui.caseKey = button.dataset.case; ui.runKey = null; ui.page = "cases";
      if (mobileLayout?.matches) $("#case-list-picker").open = false;
    }
    else if (has(button.dataset, "backToList")) $("#case-list-picker").open = true;
    else if (button.dataset.page) ui.page = button.dataset.page;
    else if (button.dataset.caseTab && ["functional", "operational"].includes(button.dataset.caseTab)) ui.caseTab = button.dataset.caseTab;
    else if (button.dataset.aggregateTab && aggregateTabLabels.some(([key]) => key === button.dataset.aggregateTab)) ui.aggregateTab = button.dataset.aggregateTab;
    else if (button.dataset.aggregateRole && aggregateRoleChoices().some(choice => choice.key === button.dataset.aggregateRole)) { ui.aggregateRole = button.dataset.aggregateRole; ui.scoreFilter = null; ui.scoreLimit = 30; }
    else if (button.dataset.pageStep) {
      ui.pageNumber += Number(button.dataset.pageStep); ui.caseKey = null; ui.runKey = null;
    } else if (has(button.dataset, "moreScores")) ui.scoreLimit += 30;
    else if (has(button.dataset, "clearScoreFilter")) { ui.scoreFilter = null; ui.scoreLimit = 30; }
    else return;
    render();
    if (button.dataset.caseTab) $("#case-tab-" + ui.caseTab).focus({preventScroll: true});
    else if (button.dataset.aggregateTab) $("#aggregate-tab-" + ui.aggregateTab).focus({preventScroll: true});
    else if (button.dataset.aggregateRole) focusAggregateRole(button.dataset.roleMetric);
    else if (button.dataset.case) focusPane("#case-detail");
    else if (has(button.dataset, "backToList")) focusPane("#case-list");
  });
  $("#batch-select").addEventListener("change", (event) => { if (remote) { loadRemoteBatch(Number(event.target.value)); return; } ui.batch = Number(event.target.value); ui.assessmentKey = null; resetSelection(); if (currentBatch().source === "assessment") ui.page = "aggregate"; render(); });
  $("#case-search").addEventListener("input", (event) => { ui.query = event.target.value; ui.pageNumber = 0; render(); });
  for (const [id, key] of [["status-filter", "status"], ["tag-filter", "tag"], ["required-filter", "required"]]) {
    $("#" + id).addEventListener("change", (event) => { ui[key] = event.target.value; ui.pageNumber = 0; render(); });
  }
  document.addEventListener("keydown", event => {
    if (event.target.closest?.("#case-splitter") && !mobileLayout?.matches && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      applySplitWidth(event.key === "Home" ? 25 : event.key === "End" ? 75 : ui.metricsWidth + (event.key === "ArrowRight" ? 2 : -2));
      return;
    }
    const roleButton = event.target.closest?.("[data-aggregate-role]");
    if (roleButton && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      const keys = aggregateRoleChoices().map(choice => choice.key), index = keys.indexOf(roleButton.dataset.aggregateRole);
      if (index < 0) return;
      event.preventDefault();
      ui.aggregateRole = keys[event.key === "Home" ? 0 : event.key === "End" ? keys.length - 1 : (index + (event.key === "ArrowRight" ? 1 : keys.length - 1)) % keys.length];
      ui.scoreFilter = null; ui.scoreLimit = 30;
      render(); focusAggregateRole(roleButton.dataset.roleMetric); return;
    }
    const aggregateButton = event.target.closest?.("[data-aggregate-tab]");
    const button = aggregateButton || event.target.closest?.("[data-case-tab]");
    if (!button || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const stateKey = aggregateButton ? "aggregateTab" : "caseTab";
    const tabs = aggregateButton ? aggregateTabLabels.map(([key]) => key) : ["functional", "operational"];
    const index = tabs.indexOf(button.dataset[stateKey]);
    if (index < 0) return;
    event.preventDefault();
    ui[stateKey] = tabs[event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    render();
    $(`${aggregateButton ? "#aggregate-tab-" : "#case-tab-"}${ui[stateKey]}`).focus({preventScroll: true});
  });
  document.addEventListener("toggle", event => {
    const target = event.target;
    if (target.matches?.(".case-input") && target.isConnected) ui.inputOpen = target.open;
    if (target.matches?.(".case-output") && target.isConnected) ui.outputOpen = target.open;
    if (target.matches?.(".input-message") && target.isConnected) {
      if (target.open) ui.closedMessages.delete(target.dataset.messageKey);
      else ui.closedMessages.add(target.dataset.messageKey);
    }
    if (target.matches?.(".check-comparison") && target.isConnected) {
      if (target.open) ui.checkOpen.add(target.dataset.checkKey);
      else ui.checkOpen.delete(target.dataset.checkKey);
    }
    if (target.matches?.(".scenario-disclosure") && target.isConnected) {
      const wasOpen = ui.scenarioOpen.has(target.dataset.scenarioPath);
      if (target.open) ui.scenarioOpen.add(target.dataset.scenarioPath);
      else ui.scenarioOpen.delete(target.dataset.scenarioPath);
      if (target.open && !wasOpen) target.querySelector(".scenario-step.current")?.scrollIntoView({block: "nearest", inline: "center"});
    }
  }, true);
  document.addEventListener("change", (event) => {
    if (event.target.id === "run-select") { ui.runKey = event.target.value; render(); }
    if (event.target.id === "assessment-select") { if (remote) { loadRemoteAssessment(event.target.value); return; } ui.assessmentKey = event.target.value; ui.scoreFilter = null; ui.scoreLimit = 30; render(); }
  });
  loadLocalResults();
})();
