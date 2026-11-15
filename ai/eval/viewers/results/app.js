/* UI state and rendering only. Artifact validation/linking lives in data.js.
 * No execution, grading, metric calculation, or persistence of loaded files. */
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
  const units = {tool: "도구", node: "노드", selection: "작업 선택", agent: "에이전트", workflow: "생성 흐름"};
  const targetNames = {
    query_data: "데이터 검색 및 조회", process_data: "데이터 가공",
    validate_visualization: "시각화 설정 검사", render_visualization: "표 렌더링",
    interpret: "작업 목적 파악", act: "작업 선택 및 실행", decide: "작업 진행 판단",
    compose: "응답 작성", ask: "사용자 정보 요청", request: "사용자 요청 처리",
    interpretation: "분석 결과 해석", visualization: "데이터 시각화", report: "대시보드 보고서 생성",
    report_selection: "보고서 시각화 선정", report_description: "보고서 시각화 설명", report_insight: "보고서 퀵 인사이트",
  };
  // Display names from eval/docs/tools.md; these do not supply assessment results.
  const toolEvaluationIds = new Map([
    ["query_data", "T01"], ["process_data", "T02"], ["validate_visualization", "T03"],
  ]);
  const toolChecks = new Map([
    ["T-I.1", {category: "입력", name: "입력 처리 적합성"}],
    ["T-O.1", {category: "출력", name: "처리 결과 정확성"}],
    ["T-O.2", {category: "출력", name: "처리 상태 구분"}],
    ["T-O.5", {category: "출력", name: "출처 정보 정확성"}],
  ]);
  const availabilityNames = {loaded: "불러옴", missing: "없음", invalid: "형식 오류", mismatch: "연결 불일치", duplicate: "중복", partial: "일부 읽음", unloaded: "미로딩"};
  const ui = {
    catalog: null, batch: 0, target: "all", caseKey: null, runKey: null,
    page: "cases", detail: "assessment", query: "", status: "all", tag: "all",
    required: "all", pageNumber: 0, wide: false, detailOpen: false, sample: false, loading: false, traceLimit: 30,
    assessmentKey: null, scoreFilter: null, scoreLimit: 30,
  };
  let downloads = [];
  const PAGE_SIZE = 25;

  // These disclosures and pane choices are presentation state only.
  const mobileLayout = globalThis.matchMedia?.("(max-width: 760px)");
  function syncDisclosures() {
    if (!mobileLayout) return;
    $("#target-picker").open = !mobileLayout.matches;
    $("#case-filters").open = false;
  }
  mobileLayout?.addEventListener("change", syncDisclosures);
  syncDisclosures();

  function focusPane(selector) {
    if (!globalThis.matchMedia?.("(max-width: 1200px)")?.matches) return;
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

  function targetKey(run) {
    if (remote && run.entry) {
      const entry = run.entry;
      return JSON.stringify([entry.unit, entry.target, entry.role ?? (entry.unit === "agent" ? entry.target : null), entry.unit === "tool" ? "real" : entry.dependencies ?? null]);
    }
    const i = info(run);
    return JSON.stringify([i.unit, i.target, i.role ?? null, i.dependencies ?? null]);
  }

  function targetLabel(run) {
    const i = info(run);
    const name = i.unit === "selection" ? "작업 선택만" : targetNames[i.target] || i.target || "대상 미기록";
    const id = i.unit === "tool" && toolEvaluationIds.get(i.target);
    return id ? `${id} · ${name}` : name;
  }

  function appliedChecks(run) {
    return run.report ? run.report.assessment.checks : run.case?.assessment?.checks || [];
  }

  function checkDefinition(run, id) {
    return info(run).unit === "tool" ? toolChecks.get(id) : undefined;
  }

  function checksView(run) {
    const checks = appliedChecks(run);
    return `<section class="applied-checks" aria-label="적용 검사 항목"><h3>적용 검사 항목</h3>
      <p class="hint">이 사례에 지정된 검사입니다. 분류와 항목명은 검사 정의이며, 검사 수행이나 통과를 뜻하지 않습니다.</p>
      ${checks.length ? `<div class="table-scroll"><table class="checks-table"><caption class="sr-only">적용 검사의 분류, ID와 항목명</caption><thead><tr><th scope="col">검사 분류</th><th scope="col">검사 ID</th><th scope="col">검사 항목명</th></tr></thead><tbody>${checks.map(id => {
        const definition = checkDefinition(run, id);
        return `<tr><td>${text(definition?.category || "미등록")}</td><td><code>${escape(id)}</code></td><td>${text(definition?.name || "항목명 미등록")}</td></tr>`;
      }).join("")}</tbody></table></div>` : '<p class="hint">지정한 검사 ID가 없습니다.</p>'}
      ${info(run).unit === "tool" ? '<p class="hint"><a href="../../docs/tools.md#2-기능-평가" target="_blank" rel="noopener">도구 검사 분류·항목명 기준 ↗</a></p>' : ""}</section>`;
  }

  function dependencyLabel(run) {
    const i = info(run);
    if (i.unit === "selection") return "하위 호출 없음";
    if (i.unit === "tool") return "실제 도구 실행";
    return i.dependencies === "stub" ? "모의 하위 응답" : i.dependencies === "real" ? "실제 하위 호출" : "하위 호출 방식 미기록";
  }

  function time(value) {
    return value == null ? "미기록" : `${escape(value)}초`;
  }

  function scopeHint(run) {
    const i = info(run);
    if (i.unit === "selection") return "작업 선택 모델까지 실행한 범위입니다. 도구·하위 에이전트는 호출하지 않습니다.";
    if (i.unit === "node") return "노드 한 개의 실행 결과입니다. 반환한 다음 경로의 실행은 포함하지 않습니다.";
    if (i.unit === "workflow" && i.target === "report") return "한 동의 선정 → 설명 → 인사이트 순차 생성 흐름입니다. HTTP 접수·DB 저장·요청 전체의 재처리·완료 알림은 포함하지 않습니다.";
    if (i.unit === "agent" && i.target.startsWith("report_")) return "보고서 에이전트 한 역할의 공통 실행 흐름과 산출물입니다. 다른 역할과 전체 생성 흐름의 평가는 별도로 확인합니다.";
    if (i.dependencies === "real") return "준비된 자료를 사용하는 실제 구현의 기록입니다. 운영 데이터베이스 연결의 증거는 아닙니다.";
    return "하위 호출에는 준비된 응답을 사용했습니다. 실제 하위 구현·서비스 연동의 증거와 구분합니다.";
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
  const assessmentName = record => record.lazy && !record.report.id ? "기존 단일 JSON · " + record.path.split("/").at(-1) + " · " + fileSize(record.path) + " · 원문 미로딩" : EvaluationNames.assessmentName(record, currentBatch(), ui.catalog?.batches);
  const assessmentFilename = record => EvaluationNames.assessmentFilename(record, currentBatch(), ui.catalog?.batches);
  function recordLocation(record) {
    return `<details class="section"><summary>저장 위치</summary><code>${text(record.path)}</code></details>${EvaluationNames.legacy(record) ? '<p class="hint">기존 기록의 표시 순번은 불러온 자료의 시간순입니다. 저장된 파일과 원본 내용은 유지하며 내려받기에는 표시 이름을 사용합니다.</p>' : ""}`;
  }


  function currentAssessment() {
    const records = currentBatch()?.assessments || [];
    return records.find(item => item.path === ui.assessmentKey) || records[0];
  }


  function scoredRun(run, record = currentAssessment()) {
    const i = info(run);
    return record?.report.runs?.find(a => a.run_id === i.id && a.case_id === i.case_id && a.target === i.target && a.repetition === i.repetition);
  }

  function assessmentPicker() {
    const records = currentBatch()?.assessments || [], selected = currentAssessment();
    return `<label class="assessment-picker">채점 기록<select id="assessment-select" ${records.length ? "" : "disabled"}>${records.length ? records.map(item => `<option value="${escape(item.path)}"${item === selected ? " selected" : ""}>${text(assessmentName(item))} · ${dateTime(item.report.assessed_at)}</option>`).join("") : '<option>채점 파일 미제공</option>'}</select></label>`;
  }

  function toolLabel(target) {
    return `${toolEvaluationIds.has(target) ? toolEvaluationIds.get(target) + " · " : ""}${targetNames[target] || target}`;
  }

  function selectedTools() {
    return (currentAssessment()?.report.tools || []).filter(tool => ui.target === "all" || ui.target === JSON.stringify(["tool", tool.target, null, "real"]));
  }

  function reasonsView(reasons) {
    return reasons.length ? `<ul class="assessment-reasons">${reasons.map(reason => `<li>${text(reason)}</li>`).join("")}</ul>` : "";
  }

  function checkResultView(check, caseId) {
    const definition = toolChecks.get(check.check);
    return `<details class="evidence-item"><summary><span>${text(definition?.category || "미등록")} · ${text(check.check)} · ${text(definition?.name || "항목명 미등록")}<small>${text(check.target || "비교 경로 미제공")}</small></span>${badge(check.verdict)}</summary>
      ${facts([["검사 수행", check.executed ? "실행" : "미실행"], ["판정 사유", text(check.reason)], ["비교 방식", text(check.match)], ["근거 경로", check.evidence.map(text).join("<br>") || "미제공"]])}
      ${raw("기대값", has(check, "expected") ? check.expected : undefined, true, "check-expected.json")}${raw("실제값", has(check, "actual") ? check.actual : undefined, true, "check-actual.json")}${has(check, "tolerance") ? raw("허용 오차", check.tolerance, true, "check-tolerance.json") : ""}</details>`;
  }

  function scoredRunView(scored) {
    return `${facts([["선택 기록의 판정", badge(scored.verdict)], ["검사 수행", scored.executed ? "수행한 검사 있음" : "미실행"], ["사유", text(scored.reason)]])}
      <div class="evidence-list">${scored.checks.map(check => checkResultView(check, scored.case_id)).join("") || '<p class="hint">개별 검사 결과가 없습니다.</p>'}</div>`;
  }

  function checkRows(target) {
    // Count saved comparison verdicts, not pass rates. The same run/path/verdict
    // is counted once; the original check records remain available as evidence.
    const rows = new Map();
    for (const run of currentAssessment()?.report.runs || []) {
      if (run.target !== target) continue;
      for (const check of run.checks) {
        const key = JSON.stringify([run.run_id, run.case_id, run.repetition, check.check, check.target, check.verdict]);
        if (!rows.has(key)) rows.set(key, {run, check, originals: []});
        rows.get(key).originals.push(check);
      }
    }
    return [...rows.values()];
  }

  function checkSummaryView(tool) {
    if (currentAssessment()?.partial) return '<h4>검사 항목별 근거</h4><p class="hint">개별 검사 원문은 아직 읽지 않았습니다. 아래 사례·검사를 선택하면 해당 파일만 읽습니다. 일부 읽은 결과로 전체 검사 건수를 계산하지 않습니다.</p>';
    const groups = new Map();
    for (const row of checkRows(tool.target)) {
      if (!groups.has(row.check.check)) groups.set(row.check.check, {통과: 0, 실패: 0, 미판정: 0, 비적용: 0});
      groups.get(row.check.check)[row.check.verdict]++;
    }
    return `<h4>검사 항목별 집계</h4><p class="hint">비교 항목의 판정 건수입니다. 같은 실행·검사·비교 경로·판정은 한 번만 셉니다. 한 사례에 여러 비교 항목과 반복 실행이 포함될 수 있습니다. 건수를 누르면 개별 근거를 확인할 수 있습니다.</p>
      <div class="table-scroll"><table class="assessment-table"><thead><tr><th>분류</th><th>검사 ID · 항목명</th><th>통과</th><th>실패</th><th>미판정</th><th>비적용</th></tr></thead><tbody>${[...groups].sort(([a], [b]) => a.localeCompare(b, "en", {numeric: true})).map(([id, counts]) => `<tr><td>${text(toolChecks.get(id)?.category || "미등록")}</td><td>${text(id)} · ${text(toolChecks.get(id)?.name || "항목명 미등록")}</td>${Object.entries(counts).map(([verdict, count]) => `<td><button type="button" class="link-button" data-score-check="${escape(JSON.stringify([tool.target, id, verdict]))}" aria-label="${escape(toolLabel(tool.target) + ' ' + id + ' ' + verdict + ' 근거 ' + count + '건')}">${count}</button></td>`).join("")}</tr>`).join("") || '<tr><td colspan="6">저장된 개별 검사 결과가 없습니다.</td></tr>'}</tbody></table></div>`;
  }

  function functionalView(f) {
    const rate = f.rate === null ? "미제공" : `${Number((f.rate * 100).toFixed(2))}%`;
    return `<h4>기능 지표</h4><div class="summary-cards"><div class="summary-card"><span>필수 사례 통과율</span><strong>${rate}</strong><span>통과 ${f.numerator} / 분모 ${f.denominator}사례</span></div><div class="summary-card"><span>기능 합격 여부</span><strong>${badge(f.verdict)}</strong><span>필수 검사 ${f.complete ? "완료" : "미완료"}</span></div><div class="summary-card"><span>완료 / 미완료 사례</span><strong>${f.completed_cases} / ${f.incomplete_cases}</strong><span>완료 통과 ${f.completed_passed_cases} · 완료 실패 ${f.completed_failed_cases}</span></div></div>
      <p class="hint">채점 파일에 저장된 사례 단위 지표입니다. 누락·미판정 필수 사례도 분모에 남으며, 목록 검색·필터로 분모를 바꾸지 않습니다.</p>
      ${facts([["통과 / 실패 사례", `${f.passed_cases} / ${f.failed_cases}`], ["누락 / 미판정 사례", `${f.missing_cases} / ${f.undetermined_cases}`], ["필수 여부 미지정 / 제외 사례", `${f.unspecified_required_cases} / ${f.excluded_cases}`]])}
      <details class="section"><summary>사례별 판정·반복 충족·미완료 사유 (${f.cases.length}사례)</summary><div class="table-scroll"><table class="assessment-table"><thead><tr><th>사례</th><th>필수 여부</th><th>판정·완료 여부</th><th>기록 / 예정 반복</th><th>누락·미판정·사유</th></tr></thead><tbody>${f.cases.map(c => `<tr><td>${text(c.case_id)}</td><td>${c.required === true ? "필수" : c.required === false ? "제외" : "미지정"}</td><td>${badge(c.verdict)} · ${c.complete ? "완료" : "미완료"}</td><td>${c.recorded_repetitions} / ${c.planned_repetitions}</td><td>누락: ${c.missing_repetitions.join(", ") || "없음"}<br>미판정: ${c.undetermined_repetitions.join(", ") || "없음"}${reasonsView(c.reasons)}${c.checks.filter(check => check.unexecuted || check.undetermined || check.reasons.length).map(check => `<p>${text(check.check)} · 미실행 ${check.unexecuted} · 미판정 ${check.undetermined}</p>${reasonsView(check.reasons)}`).join("")}</td></tr>`).join("")}</tbody></table></div></details>`;
  }

  function latencyView(tool) {
    const l = tool.latency;
    return `<h4>운영 지표 · 도구 호출 응답시간</h4><p class="hint">정상·오류 호출의 저장된 통계입니다. 사례 전체의 실행 관측 시간과 구분합니다.</p><div class="table-scroll"><table><thead><tr><th>호출 구분</th><th>표본 수</th><th>중앙값</th><th>p95</th></tr></thead><tbody>${["normal", "error"].map(group => `<tr><td>${group === "normal" ? "정상" : "오류"}</td><td>${l[group].sample_count}</td><td>${time(l[group].median_seconds)}</td><td>${time(l[group].p95_seconds)}</td></tr>`).join("")}</tbody></table></div>
      ${facts([["미종료 호출", String(l.unfinished_count)], ["유효하지 않은 측정", String(l.invalid_measurements)], ["충돌 호출 ID 수", String(l.conflicting_span_ids.length)], ["실행 한도 초과", String(l.execution_limit_exceeded)]])}${reasonsView(l.reasons)}
      ${l.unfinished.length || l.conflicting_span_ids.length ? raw("미종료·충돌 호출 근거", {unfinished: l.unfinished, conflicting_span_ids: l.conflicting_span_ids}) : ""}
      <h4>운영 목표 충족 여부</h4>${tool.performance.length ? tool.performance.map(goal => `<section class="performance-goal">${facts([["호출 구분", goal.group === "normal" ? "정상" : "오류"], ["목표 충족 판정", badge(goal.verdict)], ["측정 완료", goal.complete ? "완료" : "미완료"], ["평가 통계", text(goal.statistic === "median" ? "중앙값" : goal.statistic)], ["측정값 / 목표 상한", `${time(goal.value_seconds)} / ${time(goal.max_seconds)}`], ["표본 수", String(goal.sample_count)], ["측정 환경", text(goal.environment)], ["자료 크기", text(goal.data_size)], ["대상 사례", goal.case_ids.map(text).join(", ") || "미지정"]])}${reasonsView(goal.reasons)}</section>`).join("") : '<p class="hint">운영 목표 미제공 · 목표 충족 여부는 미판정입니다.</p>'}`;
  }

  function scoreEvidenceView(tools) {
    let rows = tools.flatMap(tool => checkRows(tool.target));
    const filter = ui.scoreFilter;
    if (filter) rows = rows.filter(row => row.run.target === filter[0] && row.check.check === filter[1] && row.check.verdict === filter[2]);
    return `<section id="score-evidence" class="section" tabindex="-1"><h3>개별 판정 근거 · ${rows.length}건</h3>${filter ? `<p>${text(toolLabel(filter[0]))} / ${text(filter[1])} / ${badge(filter[2])} <button type="button" data-clear-score-filter>전체 근거 보기</button></p>` : ""}
      ${rows.slice(0, ui.scoreLimit).map(row => {
        const run = currentBatch().runs.find(r => info(r).id === row.run.run_id && info(r).case_id === row.run.case_id && info(r).target === row.run.target && info(r).repetition === row.run.repetition);
        return `<div class="score-evidence-row"><p><strong>${text(row.run.case_id)} · ${row.run.repetition}회차</strong> · ${text(toolLabel(row.run.target))}</p><p class="hint">${run ? `<button type="button" class="link-button" data-open-run="${escape(run.key)}">실행 입출력 확인 ↗</button>` : row.run.run_id === null ? "계획된 실행 · 실행 ID 없음" : `실행 원본 미제공 · ${text(row.run.run_id)}`}</p>${row.originals.map(check => checkResultView(check, row.run.case_id)).join("")}</div>`;
      }).join("") || '<p class="hint">해당하는 검사 근거가 없습니다.</p>'}
      ${rows.length > ui.scoreLimit ? `<button type="button" data-more-scores>판정 근거 더 보기 (${ui.scoreLimit} / ${rows.length})</button>` : ""}</section>`;
  }

  function scoringView() {
    const record = currentAssessment();
    if (!record) return '<div class="empty"><h3>지표 집계·통계 미제공</h3><p>도구 채점 파일을 함께 열면 검사별 판정, 필수 사례 통과율과 도구 호출 시간 통계를 확인할 수 있습니다. 합격률과 시간 통계를 이 화면에서 계산하지 않습니다.</p></div>';
    if (record.lazy) return lazyAssessmentNotice(record);
    const a = record.report, tools = selectedTools();
    return `<section class="section"><h2>도구별 평가 결과</h2>${facts([["평가 이름", text(assessmentName(record))], ["채점 일시", dateTime(a.assessed_at)], ["평가 대상 실행", text(batchName())], ["결과 파일", text(record.path.split(/[\\/]/).pop())]])}${recordLocation(record)}<p class="hint">선택한 채점 기록 하나의 결과를 표시합니다. 기능·운영 지표와 합격 판정은 저장값이며, 원본 실행 결과의 미판정 상태와 별도로 보존합니다.</p>${reasonsView(a.limitations)}
      ${tools.map(tool => `<section class="tool-assessment"><h3>${text(toolLabel(tool.target))}</h3>${functionalView(tool.functional)}${checkSummaryView(tool)}${latencyView(tool)}</section>`).join("") || '<p class="hint">선택한 대상의 도구 지표가 이 채점 기록에 없습니다.</p>'}
      ${scoreEvidenceView(tools)}${raw("선택한 채점 기준", a.criteria, false, "criteria.json")}<p class="hint">아래 해시는 채점 당시의 기록값입니다. 이 화면에서 파일 해시를 재계산하지 않습니다.</p>${raw("채점 기준·근거·평가기 해시", {criteria_sha256: a.criteria_sha256, evidence_sha256: a.evidence_sha256, evaluator_sha256: a.evaluator_sha256})}${raw("채점 결과 전체", a, false, assessmentFilename(record))}</section>`;
  }

  function scopedRuns() {
    return (currentBatch()?.runs || []).filter((run) => ui.target === "all" || targetKey(run) === ui.target);
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
      group.prepared = group.runs.find((run) => run.case)?.case;
    }
    return [...groups.values()];
  }

  function matchingRuns(group) {
    return group.runs.filter((run) => ui.status === "all" || info(run).status === ui.status);
  }

  function filteredGroups() {
    return caseGroups().filter((group) => {
      const c = group.prepared;
      const query = ui.query.trim().toLocaleLowerCase();
      const checkTerms = group.runs.flatMap(run => appliedChecks(run).flatMap(id => {
        const definition = checkDefinition(run, id);
        return [id, definition?.category, definition?.name];
      }));
      const searchable = [group.id, c?.purpose, ...(c?.tags || []), ...checkTerms].join(" ").toLocaleLowerCase();
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
    Object.assign(ui, {target: "all", caseKey: null, runKey: null, pageNumber: 0, query: "", status: "all", tag: "all", required: "all", wide: false, detailOpen: false, traceLimit: 30, scoreFilter: null, scoreLimit: 30});
    $("#case-search").value = "";
    $("#status-filter").value = "all";
    $("#required-filter").value = "all";
  }

  function acceptFiles(files, sample, readIssues = []) {
    const catalog = EvaluationData.parseFiles(files);
    showIssues([...readIssues, ...catalog.issues]);
    if (!catalog.batches.length) {
      setNotice("지원하는 실행·채점 결과를 찾지 못했습니다. 결과 폴더 또는 evaluation-run-v1·tool-evaluation-v1 파일을 선택하세요. 기존 화면은 유지됩니다.", true);
      return false;
    }

    remoteEpoch++; remote?.dispose(); remote = null; remoteRaw = null;
    ui.catalog = catalog;
    ui.batch = 0;
    ui.assessmentKey = null;
    ui.page = catalog.batches[0].source === "assessment" ? "aggregate" : "cases";
    ui.sample = sample;
    resetSelection();
    $("#welcome").hidden = true;
    $("#application").hidden = false;
    $("#sample-notice").hidden = !sample;
    $("#local-status").hidden = true;

    $("#batch-select").innerHTML = catalog.batches.map((batch, index) => {
      const label = EvaluationNames.batchLabel(batch, catalog.batches);
      return `<option value="${index}">${escape(label)}</option>`;
    }).join("");
    setNotice(sample ? "" : `${catalog.batches.length}개 묶음을 불러왔습니다. 새 파일을 열면 현재 자료를 교체합니다.`);
    render();
    return true;
  }

  let remote = null, remoteIndex = null, remoteEpoch = 0, remoteRaw = null;
  function fileSize(path) {
    const size = remoteIndex?.files.find(file => file.path === path)?.size_bytes;
    return size == null ? "크기 미기록" : (size / 1048576).toFixed(1) + " MB";
  }
  function lazyAssessmentNotice(record) {
    const size = remoteIndex?.files.find(file => file.path === record.path)?.size_bytes;
    return '<section class="empty"><h3>채점 원문 미로딩</h3><p>기존 단일 JSON은 전체를 읽어야 합니다. ' + text(size == null ? "파일 크기 미기록" : (size / 1048576).toFixed(1) + " MB") + ' · 선택하기 전에는 읽지 않습니다. 64 MB를 넘는 원문은 브라우저에서 읽지 않습니다.</p><a href="' + escape(remote.url(record.path)) + '" download>원본 파일 내려받기</a><button type="button" data-lazy-assessment>이 채점 원문 읽기</button></section>';
  }
  function lazyRawControl(label, path) {
    return '<section class="section"><p class="hint">' + text(label) + ' · 명시적으로 읽기 전에는 요청하지 않습니다.</p><button type="button" data-lazy-raw="' + escape(path) + '">' + text(label) + ' 원문 읽기</button> <a href="' + escape(remote.url(path)) + '" download>파일 내려받기</a>' + (remoteRaw?.path === path ? raw(label, remoteRaw.text, true, path.split("/").at(-1)) : "") + '</section>';
  }
  function lazyRunNotice(run) {
    if (!run.loading && !run.loadError) void loadRemoteRun(run);
    return '<section class="empty"><h3>' + (run.loading ? "선택한 실행 원문 읽는 중" : "실행 원문 읽기 오류") + '</h3><p>' + text(run.loadError || "선택한 사례와 반복의 case.json·report.json만 읽습니다. 아직 읽지 않은 값을 판정으로 바꾸지 않습니다.") + '</p>' + (run.loadError ? '<button type="button" data-lazy-run="' + escape(run.key) + '">다시 읽기</button>' : "") + '</section>';
  }
  async function loadRemoteRun(run) {
    const epoch = remoteEpoch, batch = currentBatch(), request = remote.begin("run");
    run.loading = true; remoteRaw = null;
    try {
      const loaded = await remote.run(batch, run, {signal: request.signal});
      if (epoch !== remoteEpoch || batch !== currentBatch() || !request.current() || run.key !== ui.runKey) return;
      for (const previous of batch.runs) if (previous !== run && !previous.lazy) {
        previous.report = null; previous.case = null; previous.manifest = null; previous.journal = []; previous.lazy = true;
      }
      Object.assign(run, loaded, {lazy: false, loading: false, loadError: null,
        availability: {report: loaded.report ? "loaded" : "missing", case: loaded.case ? "loaded" : "missing", manifest: "unloaded", journal: "unloaded"}});
    } catch (error) { if (epoch === remoteEpoch && request.current()) run.loadError = error.message; }
    finally { run.loading = false; if (epoch === remoteEpoch && batch === currentBatch() && request.current() && run.key === ui.runKey) render(); }
  }
  async function loadRemoteAssessment(record, explicit = false) {
    const epoch = ++remoteEpoch, batch = currentBatch();
    remoteRaw = null;
    const request = remote.begin("assessment");
    for (const previous of batch.assessments) if (previous !== record && !previous.lazy) {
      const placeholder = EvaluationLazy.assessmentIndex(previous.ref, batch.report);
      for (const key of Object.keys(previous)) delete previous[key];
      Object.assign(previous, placeholder);
    }
    ui.assessmentKey = record.path;
    if (!record.report.schema_version && !explicit) { render(); return; }
    setNotice("선택한 채점 결과 읽는 중…");
    try {
      let loaded;
      if (!record.report.schema_version) {
        const source = await remote.raw(record.path, {signal: request.signal});
        const parsed = EvaluationData.parseFiles([{path: record.path, text: source.text}]);
        loaded = parsed.batches.flatMap(item => item.assessments).find(item => item.report.schema_version === "tool-evaluation-v1");
        if (!loaded) throw new Error("이 뷰어의 채점 형식이 아니거나 원문 형식이 올바르지 않습니다.");
        if (loaded.report.batch_id !== batch.report.id || loaded.report.suite_id !== batch.report.suite_id) throw new Error("선택한 실행 묶음과 채점 원문의 식별자가 다릅니다.");
      } else loaded = await remote.assessment(record.ref || {path: record.path}, {signal: request.signal});
      if (epoch !== remoteEpoch || batch !== currentBatch()) return;
      Object.assign(record, loaded, {lazy: false, partial: loaded.partial ?? false});
      setNotice("선택한 채점 집계를 읽었습니다. 사례·검사 원문을 함께 불러왔습니다.");
    } catch (error) { if (epoch === remoteEpoch) setNotice("채점 읽기 오류: " + error.message, true); }
    if (epoch === remoteEpoch) render();
  }
  async function loadRemoteBatch(index) {
    const epoch = ++remoteEpoch, request = remote.begin("batch");
    if (currentBatch() && remoteIndex.batches[ui.batch]) ui.catalog.batches[ui.batch] = EvaluationLazy.batchIndex(remoteIndex.batches[ui.batch]);
    remoteRaw = null;
    ui.batch = index; ui.assessmentKey = null; resetSelection(); ui.page = "aggregate";
    setNotice("선택한 실행 묶음 목록 읽는 중…");
    $("#aggregate-page").innerHTML = '<p class="hint">선택한 실행 묶음 목록 읽는 중…</p>';
    try {
      const batch = await remote.batch(remoteIndex.batches[index], {signal: request.signal});
      if (epoch !== remoteEpoch) return;
      batch.assessments = batch.assessments.filter(item => item.ref?.format === "legacy" || item.report.schema_version === "tool-evaluation-v1");
      batch.assessments.sort((a, b) => Number(a.ref?.format === "legacy") - Number(b.ref?.format === "legacy") || (Date.parse(b.report.assessed_at) || 0) - (Date.parse(a.report.assessed_at) || 0));
      ui.catalog.batches[index] = batch;
      if (batch.assessments.length && batch.assessments[0].report.schema_version) await loadRemoteAssessment(batch.assessments[0]);
      else { setNotice("목록을 읽었습니다. 선택한 사례 또는 채점만 읽습니다."); render(); }
    } catch (error) { if (epoch === remoteEpoch) setNotice("묶음 읽기 오류: " + error.message, true); }
  }
  async function loadRemoteCatalog() {
    try {
      const epoch = remoteEpoch, client = EvaluationLazy.create({baseURL: new URL("../../../", location.href)});
      remote = client;
      const index = await client.catalog("eval/outputs/evaluation-viewer/catalog.json");
      if (remote !== client || epoch !== remoteEpoch) return;
      remoteIndex = index;
      const preferred = entry => entry.assessments.some(item => item.report_schema_version === "tool-evaluation-v1") || (entry.units || []).some(unit => ["tool"].includes(unit));
      remoteIndex.batches.sort((a, b) => Number(preferred(b)) - Number(preferred(a)));
      if (!remoteIndex.batches.length) { setNotice("저장된 실행 묶음이 없습니다."); return; }
      ui.catalog = {batches: remoteIndex.batches.map(EvaluationLazy.batchIndex), issues: remoteIndex.issues || []};
      ui.sample = false;
      $("#welcome").hidden = true; $("#application").hidden = false; $("#sample-notice").hidden = true;
      $("#local-status").hidden = false;
      $("#local-status").textContent = "작은 목록을 읽었습니다. 선택한 묶음·사례·검사 원본만 요청합니다.";
      $("#batch-select").innerHTML = remoteIndex.batches.map((batch, index) => '<option value="' + index + '">' + text(batch.id || batch.path) + '</option>').join("");
      showIssues(remoteIndex.issues || []);
      await loadRemoteBatch(0);
    } catch (error) { setNotice("목록 읽기 오류: " + error.message + " HTTP 주소에서 열거나 결과 파일을 직접 선택하세요.", true); }
  }
  async function lazyAction(button) {
    if (has(button.dataset, "lazyAssessment")) { await loadRemoteAssessment(currentAssessment(), true); return true; }
    if (button.dataset.lazyRun) { const run = currentBatch().runs.find(item => item.key === button.dataset.lazyRun); if (run) { run.loadError = null; await loadRemoteRun(run); } return true; }
    if (!has(button.dataset, "lazyRaw")) return false;
    const epoch = remoteEpoch, request = remote.begin("detail");
    setNotice("선택한 원본 읽는 중…");
    try {
        const loaded = await remote.raw(button.dataset.lazyRaw, {signal: request.signal});
        if (epoch !== remoteEpoch || !request.current()) return true;
        remoteRaw = loaded;
      setNotice(""); render();
    } catch (error) { if (epoch === remoteEpoch && request.current()) setNotice("원본 읽기 오류: " + error.message + " 저장된 판정은 변경하지 않았습니다.", true); }
    return true;
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
      setNotice("수동으로 선택한 파일은 전체를 읽습니다. 합계 64 MB를 넘어서 읽지 않았습니다. HTTP 조회에서 묶음·사례·검사를 선택해 필요한 파일만 읽으세요.", true);
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
    for (const id of ["folder-button", "files-button", "sample-button", "welcome-open"]) $("#" + id).disabled = value;
  }

  function renderNavigation() {
    const groups = new Map();
    for (const run of currentBatch().runs) {
      const key = targetKey(run);
      if (!groups.has(key)) groups.set(key, {key, ...info(run), label: targetLabel(run), dependency: dependencyLabel(run), cases: new Set()});
      groups.get(key).cases.add(info(run).case_id);
    }
    for (const tool of currentAssessment()?.report.tools || []) {
      const key = JSON.stringify(["tool", tool.target, null, "real"]);
      if (!groups.has(key)) groups.set(key, {key, unit: "tool", target: tool.target, label: toolLabel(tool.target), dependency: "저장된 도구 채점", cases: new Set()});
      for (const c of tool.functional.cases) groups.get(key).cases.add(c.case_id);
    }
    $("#target-count").textContent = `${groups.size}종`;
    let html = `<button type="button" class="target-button" data-target="all" aria-pressed="${ui.target === "all"}">전체 대상</button>`;
    for (const unit of ["tool", "node", "selection", "agent", "workflow"]) {
      const targets = [...groups.values()].filter((group) => group.unit === unit);
      if (!targets.length) continue;
      html += `<div class="nav-group">${units[unit]}</div>`;
      for (const target of targets) {
        const i = target;
        html += `<button type="button" class="target-button" data-target="${escape(target.key)}" aria-pressed="${ui.target === target.key}"><span>${escape(target.label)}<small>${escape(i.role ? targetNames[i.role] || i.role : i.unit === "workflow" ? "세 에이전트 순차 실행" : "도구 직접 실행")} · ${escape(target.dependency)}</small></span><span>${target.cases.size}</span></button>`;
      }
    }
    $("#target-nav").innerHTML = html;
    const selected = groups.get(ui.target);
    $("#breadcrumb").textContent = selected ? `${units[selected.unit]} / ${selected.target}` : "평가 묶음 / 모든 대상";
    $("#target-title").textContent = selected ? selected.label : "사례별 결과 검토";
    $("#scope").innerHTML = selected ? `<span class="chip">${escape(units[selected.unit])} 단위</span><span class="chip">${escape(selected.dependency)}</span>${selected.role ? `<span class="chip">역할: ${text(targetNames[selected.role] || selected.role)}</span>` : ""}` : '<span class="chip">도구·노드·작업 선택·에이전트·생성 흐름</span><span class="chip">대상별 실행 범위를 별도로 표시</span>';
    const batch = currentBatch();
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
    }
    $("#case-rows").innerHTML = shown.length ? shown.map((group) => {
      const run = selectedRun(group), i = info(run);
      const c = group.prepared;
      const checks = appliedChecks(run);
      return `<tr class="${group.key === ui.caseKey ? "selected" : ""}"><td><button type="button" class="case-button" data-case="${escape(group.key)}" aria-pressed="${group.key === ui.caseKey}"><span class="case-id">${text(group.id)}</span><span class="case-purpose"><span class="case-label">사례 설명</span>${text(c?.purpose || "사례 설명 미제공")}</span><span class="case-checks"><span class="case-label">적용 검사</span>${checks.length ? checks.map(escape).join(" · ") : "지정 없음"}</span><span class="case-tags">${escape(targetLabel(run))}${c?.tags?.length ? `<br>사례 태그: ${escape(c.tags.join(" · "))}` : ""}</span></button></td><td>${text(i.repetition)}회차<small class="dim"> / ${group.runs.length}기록</small></td><td>${badge(i.status)}${run.report ? "" : '<div class="hint">결과 파일 없음·오류</div>'}</td><td class="nowrap">${run.lazy ? "미로딩" : time(run.report?.run.elapsed_seconds)}</td><td>${scoredRun(run) ? badge(scoredRun(run).verdict) : "미제공"}</td></tr>`;
    }).join("") : '<tr><td colspan="5"><div class="empty"><h3>표시할 사례가 없습니다</h3><p>검색 조건을 바꾸거나 결과 파일이 있는 다른 대상을 선택하세요.</p></div></td></tr>';
    $("#pagination").innerHTML = `<span>${groups.length} / ${caseGroups().length}사례 · ${ui.pageNumber + 1} / ${totalPages}쪽</span><div><button type="button" data-page-step="-1" ${ui.pageNumber === 0 ? "disabled" : ""}>이전</button> <button type="button" data-page-step="1" ${ui.pageNumber + 1 >= totalPages ? "disabled" : ""}>다음</button></div>`;
    $("#case-browser").classList.toggle("wide", ui.wide);
    $("#case-browser").classList.toggle("detail-open", ui.detailOpen);
    $("#wide-button").textContent = ui.wide ? "상세 함께 보기" : "목록 넓게";
    renderDetail(selected, selectedRun(selected));
  }

  function assessmentView(run) {
    if (currentAssessment()?.lazy) return lazyAssessmentNotice(currentAssessment());
    const report = run.report;
    const scored = scoredRun(run);
    if (scored) return `<h3>선택한 채점 기록의 검사·판정</h3>${scoredRunView(scored)}${raw("이 평가에 사용한 사례 기준", currentAssessment().report.criteria.cases.find(c => c.id === scored.case_id && c.target === scored.target), false, "scoring-case.json")}<div class="section"><button type="button" data-page="aggregate" class="link-button">도구별 지표·검사 집계 ↗</button></div><details class="section"><summary>실행 당시 적용 검사·평가 상태</summary>${checksView(run)}${raw("실행 원본의 평가 상태", report?.assessment)}</details>`;
    if (!report) return checksView(run) + missingReport(run);
    const a = report.assessment;
    return `${checksView(run)}<div class="section empty"><h3>사례별 평가 지표 미제공</h3><p>${currentAssessment() ? "선택한 채점 기록에 이 실행의 판정이 없습니다." : "이 파일에는 지표 정의·측정값·분자·분모가 없습니다."} 실행 상태나 기대 결과로 점수와 합격 여부를 만들지 않습니다.</p></div>
      <div class="section"><h3>저장된 평가 상태</h3>${facts([["채점 수행", a.executed ? "실행" : "미실행"], ["판정", badge(a.verdict)], ["사유", text(a.reason)]])}</div>
      <div class="section row"><button type="button" data-detail="io">입력·기대·실제 결과 확인 →</button><button type="button" data-page="aggregate" class="link-button">전체 집계·통계 ↗</button></div>`;
  }

  function missingReport(run) {
    return `<div class="empty"><h3>실행 결과 파일을 확인할 수 없습니다</h3><p>${text(availabilityNames[run.availability.report] || run.availability.report)} · 진행 중이거나 저장 전에 중단됐을 수 있습니다. 이 상태를 평가 실패로 바꾸지 않습니다.</p><p><code>${escape(run.path)}</code></p></div>`;
  }

  function ioView(run) {
    const c = run.case, report = run.report, i = info(run);
    const assessment = c?.assessment;
    let html = c ? raw("실행 입력", c.unit === "tool" ? {arguments: c.arguments, ...(c.initial ? {initial: c.initial} : {})} : c.initial, true, "input.json") : '<div class="empty"><h3>사례 준비 자료 미제공</h3><p>case.json 또는 연결 가능한 suite.json을 함께 열면 입력과 기대 결과를 확인할 수 있습니다.</p></div>';
    if (run.caseSource === "suite") html = '<p class="hint">case.json이 없어 같은 묶음의 suite.json에 보존된 사례 입력을 표시합니다.</p>' + html;
    html += raw("실행 당시 기대 결과", has(assessment, "expected") ? assessment.expected : undefined, true, "expected.json");
    html += raw("독립 기준 자료", has(assessment, "reference") ? assessment.reference : undefined, false, "reference.json");
    html += raw("허용 범위", has(assessment, "tolerance") ? assessment.tolerance : undefined, false, "tolerance.json");
    if (!report) return html + missingReport(run);
    if (i.unit === "selection") {
      html += '<p class="hint">선택 결과입니다. 인자 원문을 도구 인자로 해석하거나 하위 작업을 실행한 결과가 아닙니다.</p>';
      html += raw("선택 결과 · 인자 문자열 원문 보존", report.output, true, "selection.json");
    } else if (i.unit === "node") {
      html += '<p class="hint">다음 경로는 이 노드가 반환한 값이며, 해당 경로를 실행했다는 뜻이 아닙니다.</p>';
      html += raw("노드 반환값", report.output, true, "output.json");
    } else if (["agent", "workflow"].includes(i.unit)) {
      html += raw("공개 응답", report.state?.response, true, "response.json");
      html += raw("업무 결과·작업 이력", report.state?.results, false, "results.json");
    } else html += raw("도구 직접 반환값", report.output, true, "output.json");
    if (has(report, "state")) {
      html += raw("실행 후 State", report.state, false, "state.json");
      html += raw("실행 전 준비 입력", c?.initial, false, "initial.json");
    } else html += '<p class="hint">이 도구 실행에는 State가 저장되지 않았습니다.</p>';
    if (report.failure !== null) html += raw("실행기 오류·취소 정보", report.failure, true, "failure.json");
    if (report.state?.execution?.error) html += raw("업무 State의 오류", report.state.execution.error, false, "state-error.json");
    return html;
  }

  function historyView(group, run) {
    return `<h3>같은 사례의 반복 실행</h3><p class="hint">각 행은 별도 실행입니다. 선택한 채점 기록의 사례별 반복 충족 여부는 전체 집계에서 확인할 수 있습니다.</p><div class="table-scroll"><table><thead><tr><th>실행</th><th>실행 상태</th><th>업무 상태</th><th>관측 시간</th></tr></thead><tbody>${group.runs.map((r) => {
      const i = info(r);
      return `<tr><td><button type="button" class="link-button" data-run-key="${escape(r.key)}">${text(i.repetition)}회차${r.key === run.key ? " · 선택" : ""}</button><div class="hint">${text(i.id)}</div></td><td>${badge(i.status)}</td><td>${text(statusNames[r.report?.state?.execution?.status] || r.report?.state?.execution?.status)}</td><td>${r.lazy ? "미로딩" : time(r.report?.run.elapsed_seconds)}</td></tr>`;
    }).join("")}</tbody></table></div>${assessmentHistory(run)}`;
  }

  function assessmentHistory(run) {
    const records = currentBatch().assessments || [];
    return `<section class="section"><h3>동일 실행의 채점·재평가 기록</h3>${records.length ? `<p class="hint">기록을 선택하면 사례 판정과 도구 지표가 함께 전환됩니다.</p><div class="table-scroll"><table><thead><tr><th>채점 일시 · 평가 이름</th><th>판정</th><th>사유</th></tr></thead><tbody>${records.map(record => {
      const a = scoredRun(run, record);
      return `<tr><td><button type="button" class="link-button" data-assessment-key="${escape(record.path)}">${dateTime(record.report.assessed_at)}<br>${text(assessmentName(record))}</button></td><td>${record.lazy ? "미로딩" : a ? badge(a.verdict) : "대상 실행 미포함"}</td><td>${record.lazy ? "선택하면 채점 원문을 읽습니다." : a ? text(a.reason) : "이 기록에 실행 판정이 없습니다."}</td></tr>`;
    }).join("")}</tbody></table></div>` : '<p class="hint">동일 결과의 재평가 기록 미제공 · 별도 채점 파일을 함께 열어 확인하세요.</p>'}</section>`;
  }

  function evidenceView(run) {
    if (remote) {
      const path = run.path.replace(/[^/]+$/, "trace.jsonl");
      return lazyRawControl("실행 추적", path);
    }
    const report = run.report, trace = report?.trace;
    const spans = trace?.spans || [];
    const journal = run.journal || [];
    let html = !report ? missingReport(run) : "";
    if (trace) {
      html += `<h3>직접 실행·호출 근거</h3><p class="hint">${text(trace.scope)} · ${spans.length}개 기록</p>${raw("추적 수집 범위·한계", {limitations: trace.limitations, counts: trace.counts, coverage: trace.coverage})}`;
      html += '<div class="evidence-list">' + spans.slice(0, ui.traceLimit).map((span) => `<details class="evidence-item"><summary><span>${escape(span.kind)} · ${escape(span.name)}</span><span>${escape(span.status)} · ${time(span.elapsed_seconds)}</span></summary>${facts([["호출 ID", text(span.id)], ["상위 호출", text(span.parent_id)], ["시작", dateTime(span.started_at)], ["종료", dateTime(span.ended_at)]])}${raw("호출 입력", span.input)}${raw("호출 출력", span.output)}${has(span, "error") ? raw("호출 오류", span.error) : ""}${raw("호출 기록 전체", span)}</details>`).join("") + '</div>';
      if (spans.length > ui.traceLimit) html += `<button type="button" data-more-trace>호출 기록 더 보기 (${ui.traceLimit} / ${spans.length})</button>`;
      html += `<p class="hint">누적 추적 저장 활성: ${report.journal_saved ? "예" : "아니요"}. 메모리의 trace 스냅샷과 누적 파일의 수집 범위가 다를 수 있습니다.</p>`;
      html += raw("모의 응답 사용·예상 밖 호출·잔여 응답", report.fixtures, false, "fixtures.json");
      html += raw("준비한 모의 응답", run.case?.stubs, false, "stubs.json");
    }
    html += `<div class="section"><h3>누적 추적 파일</h3><p class="hint">${text(availabilityNames[run.availability.journal] || run.availability.journal)} · ${journal.length}개 이벤트. 같은 호출의 start·update·end는 서로 다른 실행이 아닙니다.</p>`;
    if (journal.length) {
      html += downloadButton(journal, "trace.jsonl", "trace.jsonl 내려받기", true);
      html += raw("추적 이벤트 원문", journal, false, "trace-events.json");
    }
    html += '</div><div class="section"><a href="../../../report_viewer.html" target="_blank" rel="noopener">기존 실행 모니터 열기 ↗</a><p class="hint">별도 화면을 엽니다. 현재 단위 평가 형식의 자동 전달·호환 계약은 제공되지 않아 이 실행을 자동 연결하지 않습니다.</p></div>';
    return html;
  }

  function conditionsView(run) {
    if (remote) return lazyRawControl("실행 조건", run.path.replace(/[^/]+$/, "manifest.json")) + raw("선택한 사례 원문", run.case, false, "case.json") + raw("선택한 실행 원문", run.report, false, "report.json");
    const i = info(run), m = run.manifest;
    return facts([["실행 ID", text(i.id)], ["사례 ID", text(i.case_id)], ["입력 묶음", text(run.report?.run.suite_id || currentBatch().report?.suite_id)], ["시작", dateTime(i.started_at)], ["종료", dateTime(i.ended_at)], ["결과 경로", `<code>${text(run.path)}</code>`], ["사례 자료 출처", run.caseSource === "suite" ? "같은 묶음의 suite.json (case.json 누락)" : run.caseSource === "case" ? "이 실행의 case.json" : "미제공"]]) +
      raw("실행 조건·코드·설정·해시", m || undefined, true, "manifest.json") +
      raw("사례 준비 자료 전체", run.case || undefined, false, "case.json") +
      raw("실행 결과 전체", run.report || undefined, false, "report.json") +
      `<div class="section"><h3>파일 연결 상태</h3>${facts(Object.entries(run.availability).map(([key, value]) => [key, text(availabilityNames[value] || value)]))}</div>`;
  }

  function renderDetail(group, run) {
    if (!group || !run) {
      $("#case-detail").innerHTML = '<div class="empty"><h3>사례를 선택하세요</h3><p>목록에서 확인할 사례를 선택하면 입력·결과·근거를 볼 수 있습니다.</p></div>';
      return;
    }
    ui.runKey = run.key;
    if (remote && run.lazy) {
      $("#case-detail").innerHTML = '<h2>사례 ' + text(info(run).case_id) + '</h2>' + lazyRunNotice(run);
      return;
    }
    const i = info(run), c = run.case;
    const status = run.report?.state?.execution?.status;
    const tabs = [["assessment", "검사·판정"], ["io", "입력·결과"], ["history", "반복·재평가"], ["evidence", "실행 근거"], ["conditions", "실행 조건"]];
    let content;
    if (ui.detail === "io") content = ioView(run);
    else if (ui.detail === "history") content = historyView(group, run);
    else if (ui.detail === "evidence") content = evidenceView(run);
    else if (ui.detail === "conditions") content = conditionsView(run);
    else content = assessmentView(run);
    $("#case-detail").innerHTML = `<div class="detail-heading"><span>사례 상세</span><button type="button" class="back-to-list" data-back-to-list>← 목록으로</button></div><div class="row"><span class="dim small">평가 대상: ${escape(targetLabel(run))}</span>${badge(i.status)}</div><h2 class="detail-title">사례 ${text(i.case_id)}</h2>
      <div class="case-description"><h3>사례 설명</h3><p>${text(c?.purpose || group.prepared?.purpose || "사례 설명 미제공")}</p>${c?.tags?.length ? `<p class="hint">사례 태그: ${escape(c.tags.join(" · "))}</p>` : ""}</div>
      <div class="chips"><span class="chip">${escape(units[i.unit] || i.unit)}</span><span class="chip">${escape(dependencyLabel(run))}</span>${status ? `<span class="chip">업무 상태: ${text(statusNames[status] || status)}</span>` : ""}<span class="chip">${c?.assessment?.required === true ? "필수 사례" : c?.assessment?.required === false ? "선택 사례" : "필수 여부 미기록"}</span></div>
      <div class="selectors"><label>반복 실행<select id="run-select">${matchingRuns(group).map((r) => `<option value="${escape(r.key)}"${r.key === run.key ? " selected" : ""}>${text(info(r).repetition)}회차 · ${text(statusNames[info(r).status])} · ${text(info(r).id)}</option>`).join("")}</select></label></div>
      <p class="hint">${escape(scopeHint(run))}</p>${facts([["실행 관측 시간", time(run.report?.run.elapsed_seconds)], ["선택 기록의 평가 판정", scoredRun(run) ? badge(scoredRun(run).verdict) : "채점 결과 미제공"]])}
      <nav class="detail-tabs" aria-label="사례 상세 영역">${tabs.map(([key, label]) => `<button type="button" data-detail="${key}" aria-pressed="${ui.detail === key}">${label}</button>`).join("")}</nav>${content}`;
  }

  function renderAggregate() {
    const batch = currentBatch(), runs = scopedRuns();
    const loaded = runs.filter((run) => run.report).length;
    const unread = runs.filter(run => run.lazy && !run.loadError).length;
    const b = batch.report;
    $("#aggregate-page").innerHTML = `${scoringView()}<h2 class="section">선택 범위의 기록 현황</h2><p class="hint">아래 건수는 불러온 파일과 목록의 수입니다. 평가 지표나 합격률이 아닙니다.</p>
      <div class="summary-cards"><div class="summary-card"><span>사례</span><strong>${caseGroups().length}</strong><span>선택한 대상</span></div><div class="summary-card"><span>등록 실행</span><strong>${runs.length}</strong><span>반복 실행 포함</span></div><div class="summary-card"><span>읽은 결과 파일</span><strong>${loaded}</strong><span>${remote ? `미로딩 ${unread}건 · 읽기 오류·누락 ${runs.length - loaded - unread}건` : `누락·오류 ${runs.length - loaded}건`}</span></div></div>
      <div class="section"><h3>묶음 전체의 저장 정보</h3>${b ? facts([["평가 대상 실행", text(batchName())], ["예정 실행", `${text(b.planned_runs)}회`], ["등록 실행", `${b.runs.length}회`], ["아직 등록되지 않은 예정 실행", `${b.planned_runs - b.runs.length}회`], ["묶음 상태", badge(b.status)], ["시작", dateTime(b.started_at)], ["종료", dateTime(b.ended_at)]]) : '<p class="hint">batch.json이 없어 예정 실행 수와 묶음 종료 상태를 알 수 없습니다.</p>'}${b?.failure ? raw("묶음 중단 오류·취소", b.failure, true, "batch-failure.json") : ""}<p class="hint">목록 필터와 관계없이 묶음 파일의 값을 표시합니다. 예정됐지만 등록되지 않은 실행의 사례 ID·반복 순번은 추정하지 않습니다.</p></div>
      <div class="section"><h3>실행별 관측값·평가 상태</h3><p class="hint">선택한 대상 범위 · 목록 검색·필터와 별도. 실행 관측값과 선택한 채점 기록의 판정을 구분해 표시합니다.</p><div class="table-scroll"><table class="aggregate-table"><thead><tr><th>사례·반복</th><th>대상</th><th>실행 상태</th><th>관측 시간</th><th>채점</th><th>판정</th></tr></thead><tbody>${runs.map((run) => {
      const i = info(run);
      return `<tr><td><button type="button" class="link-button" data-open-run="${escape(run.key)}">${text(i.case_id)} · ${text(i.repetition)}회차 ↗</button></td><td>${escape(targetLabel(run))}</td><td>${badge(i.status)}</td><td>${run.lazy ? "미로딩" : time(run.report?.run.elapsed_seconds)}</td><td>${scoredRun(run) ? "별도 채점 기록" : "미제공"}</td><td>${scoredRun(run) ? badge(scoredRun(run).verdict) : "미제공"}</td></tr>`;
    }).join("") || '<tr><td colspan="6">등록된 실행이 없습니다.</td></tr>'}</tbody></table></div></div>
      <div class="section">${raw("묶음 결과 원문", b || undefined, false, "batch.json")}${remote ? '<p class="hint">입력 묶음 전체는 읽지 않았습니다. 사례 입력은 해당 사례를 선택하면 읽습니다.</p>' : raw("입력 묶음 스냅샷", batch.suite || undefined, false, "suite.json")}</div>`;
  }

  function render() {
    if (!ui.catalog) return;
    if (remote && (!currentBatch()?.report || currentBatch().lazy)) return;
    downloads = [];
    renderNavigation();
    $("#assessment-toolbar").innerHTML = assessmentPicker() + '<p class="hint">도구 지표와 개별 판정에 함께 적용됩니다. 처음에는 가장 최근 채점 기록을 표시합니다.</p>';
    for (const button of document.querySelectorAll(".page-tabs [data-page]")) button.setAttribute("aria-pressed", String(button.dataset.page === ui.page));
    $("#case-page").hidden = ui.page !== "cases";
    $("#aggregate-page").hidden = ui.page !== "aggregate";
    // Build only the visible page so large raw evidence is not duplicated in the DOM.
    if (ui.page === "aggregate") renderAggregate();
    else renderCases();
  }

  function openRun(key) {
    const run = scopedRuns().find((r) => r.key === key);
    if (!run) return;
    const i = info(run);
    ui.caseKey = JSON.stringify([i.case_id, i.unit, i.target]);
    ui.runKey = key;
    ui.page = "cases";
    ui.detail = "io";
    ui.detailOpen = true;
    ui.query = ""; ui.status = "all"; ui.tag = "all"; ui.required = "all"; ui.wide = false;
    $("#case-search").value = "";
    $("#status-filter").value = "all";
    $("#required-filter").value = "all";
    ui.pageNumber = Math.floor(caseGroups().findIndex((group) => group.key === ui.caseKey) / PAGE_SIZE);
    render();
    focusPane("#case-detail");
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (remote && Object.keys(button.dataset).some(key => key.startsWith("lazy"))) { await lazyAction(button); return; }
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
      ui.scoreFilter = JSON.parse(button.dataset.scoreCheck); ui.scoreLimit = 30; render();
      $("#score-evidence").focus({preventScroll: true}); $("#score-evidence").scrollIntoView({block: "start"}); return;
    }
    if (button.dataset.assessmentKey) { if (remote) return loadRemoteAssessment(currentBatch().assessments.find(record => record.path === button.dataset.assessmentKey)); ui.assessmentKey = button.dataset.assessmentKey; ui.scoreFilter = null; ui.scoreLimit = 30; render(); return; }
    if (button.dataset.target) {
      resetSelection(); ui.target = button.dataset.target;
      if (mobileLayout?.matches) $("#target-picker").open = false;
    }
    else if (button.dataset.case) { ui.caseKey = button.dataset.case; ui.runKey = null; ui.wide = false; ui.detailOpen = true; ui.traceLimit = 30; }
    else if (has(button.dataset, "backToList")) ui.detailOpen = false;
    else if (button.dataset.page) ui.page = button.dataset.page;
    else if (button.dataset.detail) ui.detail = button.dataset.detail;
    else if (button.dataset.runKey) {
      ui.runKey = button.dataset.runKey; ui.traceLimit = 30;
      ui.status = "all";
      $("#status-filter").value = "all";
    }
    else if (button.dataset.pageStep) {
      ui.pageNumber += Number(button.dataset.pageStep); ui.caseKey = null; ui.runKey = null;
    } else if (has(button.dataset, "moreTrace")) ui.traceLimit += 30;
    else if (has(button.dataset, "moreScores")) ui.scoreLimit += 30;
    else if (has(button.dataset, "clearScoreFilter")) { ui.scoreFilter = null; ui.scoreLimit = 30; }
    else return;
    render();
    if (button.dataset.case) focusPane("#case-detail");
    else if (has(button.dataset, "backToList")) focusPane("#case-list");
  });
  $("#folder-button").addEventListener("click", () => $("#folder-input").click());
  $("#welcome-open").addEventListener("click", () => $("#folder-input").click());
  $("#files-button").addEventListener("click", () => $("#files-input").click());
  $("#folder-input").addEventListener("change", (event) => loadFiles(event.target.files));
  $("#files-input").addEventListener("change", (event) => loadFiles(event.target.files));
  $("#sample-button").addEventListener("click", async () => {
    if (typeof EvaluationSamples === "undefined") {
      try { await new Promise((resolve, reject) => { const script = document.createElement("script"); script.src = "samples.js"; script.onload = resolve; script.onerror = reject; document.head.append(script); }); }
      catch { setNotice("화면 샘플을 읽을 수 없습니다.", true); return; }
    }
    acceptFiles(EvaluationSamples.files, true);
  });
  $("#batch-select").addEventListener("change", (event) => { if (remote) return loadRemoteBatch(Number(event.target.value)); ui.batch = Number(event.target.value); ui.assessmentKey = null; resetSelection(); if (currentBatch().source === "assessment") ui.page = "aggregate"; render(); });
  $("#case-search").addEventListener("input", (event) => { ui.query = event.target.value; ui.pageNumber = 0; render(); });
  for (const [id, key] of [["status-filter", "status"], ["tag-filter", "tag"], ["required-filter", "required"]]) {
    $("#" + id).addEventListener("change", (event) => { ui[key] = event.target.value; ui.pageNumber = 0; render(); });
  }
  $("#wide-button").addEventListener("click", () => { ui.wide = !ui.wide; render(); });
  document.addEventListener("change", (event) => {
    if (event.target.id === "run-select") { ui.runKey = event.target.value; ui.traceLimit = 30; render(); }
    if (event.target.id === "assessment-select") { if (remote) return loadRemoteAssessment(currentBatch().assessments.find(record => record.path === event.target.value)); ui.assessmentKey = event.target.value; ui.scoreFilter = null; ui.scoreLimit = 30; render(); }
  });
  loadLocalResults();
})();
