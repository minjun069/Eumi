/* 평가 지표 선택 → 연결 사례 → 검사 근거. 평가 원본과 실행 State는 수정하지 않는다. */
"use strict";

globalThis.ReportEvaluationView = (() => {
  const E = ReportEvaluation;
  const U = ReportUI;
  const { el, button, badge, empty, details, json } = U;
  let selection = {};
  const eventLabels = { user_request: "사용자 요청", analysis_pipeline: "세부 대시보드 보고서 작성" };
  const scopeReasons = {
    "run-mismatch": "다른 실행의 평가",
    "mixed-runs": "여러 실행의 집계값으로, 현재 실행의 값으로 분리할 수 없음",
    "event-mismatch": "평가 파일과 실행 기록의 트리거가 다름",
    "event-not-applicable": "이 트리거에 적용하지 않는 평가 대상",
    "target-unidentified": "평가 대상 식별 정보가 없어 적용 범위를 확인할 수 없음",
  };

  function verdict(value) {
    return badge(value || "미기록", value === "통과" ? "good" : value === "실패" ? "bad" : "neutral");
  }

  function valueOf({ definition, result }) {
    const value = el("div", "evaluation-measure");
    if (definition.kind === "ratio") {
      const ratio = E.ratio(result);
      value.append(el("strong", "", result?.denominator === 0 ? "산출 불가" : ratio === null ? "미기록" : `${U.format(ratio)}%`));
      value.append(el("small", "", `${U.format(result?.numerator)} / ${U.format(result?.denominator)}`));
    } else if (result?.measurements?.length) {
      for (const item of result.measurements) {
        const line = el("div");
        line.append(el("strong", "", `${U.format(item.value)}${item.value == null ? "" : ` ${item.unit}`}`), el("small", "", item.label));
        value.append(line);
      }
    } else value.append(el("strong", "", "미기록"));
    return value;
  }

  function fields(entries) {
    const list = el("dl", "evaluation-fields");
    for (const [label, value] of entries) {
      list.append(el("dt", "", label), el("dd", "", U.text(value)));
    }
    return list;
  }

  function executionFields(execution) {
    return fields([
      ["실행 이름", execution.name],
      ["호출자", execution.caller],
      ["실제 실행 상태", execution.status],
      ["실제 실행 시간", execution.elapsed_seconds === undefined ? "미기록" : `${execution.elapsed_seconds}초`],
      ["호출 기록 ID", execution.id],
      ["실행 run_id", execution.run_id],
      ["실행 증거 위치", execution.evidence],
    ]);
  }

  function categoryCount(kind, units) {
    const summary = E.executionSummary(units);
    if (!units.length || !summary.recorded) return `${units.length}개 대상 · 횟수 미기록`;
    if (["nodes", "tools"].includes(kind)) return units.every((unit) => E.targetId(unit))
      ? `${summary.targetCount}종 · ${summary.executionCount}회` : `${units.length}개 대상 · ${summary.executionCount}회`;
    return `${summary.executionCount}${["user-request", "report"].includes(kind) ? "건" : "회"}`;
  }

  // 검사 판정은 선택한 지표 안에서만 묶는다. 사례 전체의 종합 판정을 만들지 않는다.
  function caseGroups(checks) {
    const groups = new Map();
    for (const check of checks) {
      const key = JSON.stringify([check.run_id || "", check.case_id]);
      if (!groups.has(key)) groups.set(key, { key, id: check.case_id, checks: [] });
      groups.get(key).checks.push(check);
    }
    return [...groups.values()].map((item) => ({
      ...item,
      status: item.checks.some((check) => check.verdict === "실패") ? "실패"
        : item.checks.some((check) => !check.executed) ? "미실행"
          : item.checks.some((check) => check.verdict === "미판정") ? "미판정"
            : item.checks.every((check) => check.verdict === "비적용") ? "비적용" : "통과",
    }));
  }

  function renderCases(unit, metricName) {
    const root = el("div", "evaluation-cases");
    const cases = caseGroups(E.casesForMetric(unit, metricName));
    root.append(el("h4", "", `지표별 사례 · ${cases.length}건`));
    root.append(el("p", "evaluation-caption", "이 지표에 연결된 검사만 표시합니다. 사례 수는 지표의 분모와 다를 수 있습니다."));
    if (!cases.length) {
      root.append(empty("이 지표에 연결된 사례 기록이 없습니다. 집계값만으로 성공·실패 사례를 추정하지 않습니다."));
      return root;
    }
    let filter = "전체";
    let selectedCase = cases.find((item) => item.status === "실패")?.key || cases[0].key;
    const filters = el("div", "evaluation-case-filters");
    filters.setAttribute("aria-label", "사례 판정 필터");
    const list = el("div", "evaluation-case-list");
    const detail = el("div", "evaluation-case-detail");
    detail.setAttribute("aria-live", "polite");
    const statuses = ["전체", "통과", "실패", "미판정", "미실행", "비적용"];
    for (const status of statuses) {
      const count = status === "전체" ? cases.length : cases.filter((item) => item.status === status).length;
      if (!count && !["전체", "통과", "실패"].includes(status)) continue;
      const control = button(`${status} ${count}`, () => { filter = status; draw(); });
      control.dataset.caseFilter = status;
      filters.append(control);
    }
    function draw(focusCase = false) {
      const visible = cases.filter((item) => filter === "전체" || item.status === filter);
      if (!visible.some((item) => item.key === selectedCase)) selectedCase = visible[0]?.key;
      for (const control of filters.children) control.setAttribute("aria-pressed", String(control.dataset.caseFilter === filter));
      list.replaceChildren();
      detail.replaceChildren();
      if (!visible.length) { list.append(empty(`${filter} 사례가 없습니다.`)); return; }
      let focusTarget;
      for (const item of visible) {
        const control = button("", () => { selectedCase = item.key; draw(true); }, "evaluation-case-button");
        control.dataset.caseId = item.id;
        control.setAttribute("aria-pressed", String(item.key === selectedCase));
        const title = el("span");
        title.append(el("strong", "", item.id), el("small", "", `${item.checks[0].target} · 검사 ${item.checks.length}건`));
        control.append(title, verdict(item.status));
        list.append(control);
        if (item.key === selectedCase) focusTarget = control;
      }
      const selected = visible.find((item) => item.key === selectedCase);
      detail.append(el("h4", "", `${selected.id} · 검사 상세`));
      selected.checks.forEach((check, index) => {
        const block = details(`${check.check_id} · ${check.executed ? check.verdict : "미실행"} · ${check.target}`, () => {
          const body = el("div");
          const execution = unit.executions?.find((item) => item.id === check.execution_id);
          if (execution) {
            const duration = execution.elapsed_seconds === undefined ? "시간 미기록" : `${execution.elapsed_seconds}초`;
            body.append(details(`실제 실행 정보 · ${execution.status} · ${duration}`, () => executionFields(execution)));
          }
          body.append(fields([
            ["검사 실행 여부", check.executed ? "실행" : "미실행"],
            ["평가 판정", check.verdict],
            ["입력", check.input],
          ]));
          const comparison = el("div", "evaluation-case-comparison");
          comparison.append(fields([["기대 결과", check.expected]]), fields([["실제 결과", check.actual]]));
          body.append(comparison, fields([
            ["판정 근거", check.reason],
            ["증거 위치", check.evidence],
          ]));
          if (check.cause) body.append(fields([["원인", check.cause]]));
          if (check.run_id) body.append(el("p", "evaluation-caption mono", `실행 ${check.run_id}`));
          body.append(json("검사 원본", check));
          return body;
        }, index === 0);
        detail.append(block);
      });
      if (focusCase) focusTarget.focus({ preventScroll: true });
    }
    root.append(filters, list, detail);
    draw();
    return root;
  }

  function renderMetricDetail(unit, row) {
    const { definition, result } = row;
    const panel = el("aside", "evaluation-detail");
    panel.setAttribute("aria-label", `${definition.name} 상세`);
    const head = el("div", "evaluation-detail-head");
    head.append(el("p", "evaluation-caption", "선택 지표"), el("h3", "", definition.name));
    const value = el("div", "evaluation-detail-value");
    value.append(valueOf(row), verdict(result?.verdict));
    head.append(value);
    if (result?.required === false) head.append(el("p", "evaluation-caption", "별도 보고·진단용 지표"));
    if (result) head.append(el("p", "evaluation-caption", `미판정 ${U.format(result.unjudged)} · 미실행 ${U.format(result.not_executed)} · 비적용 ${U.format(result.not_applicable)}`));
    panel.append(head);
    const tabs = el("div", "evaluation-detail-tabs");
    const content = el("div", "evaluation-detail-body");
    const casesControl = button("사례 확인", () => choose("cases"));
    const criteriaControl = button("집계·판정 기준", () => choose("criteria"));
    tabs.append(casesControl, criteriaControl);
    function choose(mode) {
      casesControl.setAttribute("aria-pressed", String(mode === "cases"));
      criteriaControl.setAttribute("aria-pressed", String(mode === "criteria"));
      content.replaceChildren();
      if (mode === "cases") content.append(renderCases(unit, definition.name));
      else {
        const entries = [["적용 검사", definition.checks], ["측정 단위", definition.unit]];
        if (definition.kind === "ratio") entries.push(["분자", definition.numerator], ["분모", definition.denominator]);
        entries.push(["문서의 합격 기준", definition.criterion], ["집계 시 주의", definition.note]);
        if (result?.criterion) entries.push(["시험에서 정한 기준", result.criterion]);
        if (result?.reason) entries.push(["판정 근거", result.reason]);
        if (result?.note) entries.push(["집계 설명", result.note]);
        content.append(fields(entries), json("지표 증거 위치", result?.evidence), json("지표 원본", result));
      }
    }
    panel.append(tabs, content);
    choose("cases");
    return panel;
  }

  function renderUnit(unit) {
    const root = el("article", "evaluation-unit");
    const head = el("div", "evaluation-unit-head");
    head.append(el("h3", "", unit.target));
    if (unit.scope) head.append(el("p", "evaluation-caption", unit.scope));
    if (Array.isArray(unit.executions)) {
      head.append(details(`실행 기록 · ${unit.executions.length}회`, () => {
        const inventory = el("div", "evaluation-executions");
        for (const execution of unit.executions) inventory.append(executionFields(execution));
        if (!unit.executions.length) inventory.append(empty("이 평가 대상의 실행 기록이 없습니다."));
        return inventory;
      }));
    } else head.append(el("p", "evaluation-caption", "실행 횟수 미기록 · 검사 사례 수로 호출 횟수를 추정하지 않습니다."));
    const rows = E.metricRows(unit);
    const groups = Object.entries(E.groups).filter(([key]) => rows.some((row) => row.definition.group === key));
    const judgments = el("div", "evaluation-verdicts");
    for (const [key, label] of groups) {
      const item = el("span");
      item.append(el("span", "", `${label} `), verdict(unit.verdicts?.[key]));
      judgments.append(item);
    }
    head.append(judgments);
    root.append(head);
    if (!rows.length) { root.append(empty("이 대상에 적용되는 지표가 없습니다.")); return root; }
    if (!groups.some(([key]) => key === selection.group)) selection.group = groups[0][0];
    const layout = el("div", "evaluation-layout");
    const left = el("section", "evaluation-metrics");
    left.setAttribute("aria-label", "평가 지표");
    const groupControls = el("div", "evaluation-groups");
    groupControls.setAttribute("aria-label", "지표 분류");
    const grid = el("table", "evaluation-metric-table");
    const tableHead = el("thead");
    const line = el("tr");
    for (const name of ["지표", "실측값", "판정", "사례"]) {
      const cell = el("th", "", name); cell.scope = "col"; line.append(cell);
    }
    tableHead.append(line);
    const body = el("tbody");
    grid.append(tableHead, body);
    const right = el("div", "evaluation-detail-slot");
    right.setAttribute("aria-live", "polite");
    for (const [key, label] of groups) {
      const control = button(label, () => { selection.group = key; selection.metric = undefined; draw(); });
      control.dataset.group = key;
      groupControls.append(control);
    }
    function draw(focusMetric = false) {
      const filtered = rows.filter((row) => row.definition.group === selection.group);
      if (!filtered.some((row) => row.definition.name === selection.metric))
        selection.metric = filtered.find((row) => row.result?.verdict === "실패")?.definition.name || filtered[0].definition.name;
      for (const control of groupControls.children) control.setAttribute("aria-pressed", String(control.dataset.group === selection.group));
      body.replaceChildren();
      let focusTarget;
      for (const row of filtered) {
        const selected = row.definition.name === selection.metric;
        const line = el("tr", selected ? "is-selected" : "");
        const name = el("td");
        const control = button(row.definition.name, () => { selection.metric = row.definition.name; draw(true); }, "evaluation-metric-button");
        control.dataset.metric = row.definition.name;
        control.setAttribute("aria-pressed", String(selected));
        name.append(control);
        if (row.result?.required === false) name.append(el("small", "evaluation-caption", "별도 보고"));
        const value = el("td"); value.append(valueOf(row));
        const status = el("td"); status.append(verdict(row.result?.verdict));
        const count = el("td", "evaluation-case-count", String(caseGroups(E.casesForMetric(unit, row.definition.name)).length));
        line.append(name, value, status, count);
        body.append(line);
        if (selected) focusTarget = control;
      }
      right.replaceChildren(renderMetricDetail(unit, filtered.find((row) => row.definition.name === selection.metric)));
      if (focusMetric) focusTarget.focus({ preventScroll: true });
    }
    left.append(groupControls, grid, el("p", "evaluation-caption", "실측값 아래에 분자 / 분모를 표시합니다. 판정은 평가 파일의 기록입니다."));
    layout.append(left, right);
    root.append(layout);
    const nonApplicable = unit.metrics.filter((metric) => metric.verdict === "비적용");
    if (nonApplicable.length) root.append(details(`비적용 지표 · ${nonApplicable.length}개`, () => fields(nonApplicable.map((metric) => [metric.name, metric.reason || metric.note || "비적용 사유 미기록"]))));
    const unlinked = (unit.checks || []).filter((check) => !check.metrics?.length);
    if (unlinked.length) root.append(json(`지표 연결이 없는 검사 · ${unlinked.length}건`, unlinked));
    draw();
    return root;
  }

  function render(panel, evaluation, report, filename) {
    panel.replaceChildren();
    const event = report?.state.execution.event || evaluation.event;
    const context = JSON.stringify([evaluation.id, report?.state.execution.run_id]);
    const primary = event === "analysis_pipeline" ? "report" : event === "user_request" ? "user-request" : undefined;
    if (selection.context !== context) selection = { context, kind: primary, group: "functional" };
    const scope = E.scopeUnits(evaluation, report);
    if (evaluation.sample) panel.append(el("p", "notice evaluation-sample", "임시 평가 · 통과·실패는 UI 검토용 판정입니다. 실행 대상·횟수·입출력은 연결된 기록에서 확인하세요."));
    const summary = el("div", "evaluation-summary");
    summary.append(el("h3", "", evaluation.title));
    summary.append(el("p", "evaluation-context", `트리거 · ${eventLabels[event] || "미기록"}  /  ${report ? "선택 실행의 평가" : `평가 파일 전체 · ${evaluation.run_ids.length}개 실행`}`));
    summary.append(details("평가 조건·연결된 실행", () => {
      const content = el("div");
      content.append(fields([["평가 범위", evaluation.scope], ["생성 시각", evaluation.generated_at], ["불러온 파일", filename]]), json("평가 대상 실행 ID", evaluation.run_ids, true), json("기준·코드·자료·모델·설정 버전", evaluation.versions));
      return content;
    }));
    panel.append(summary);
    const issues = [...scope.excluded, ...(scope.warnings || [])];
    if (issues.length) panel.append(details(`표시 범위 확인 · ${issues.length}개 대상`, () => fields(issues.map(({ unit, reason }) => [unit.target, scopeReasons[reason] || reason]))));
    const kinds = [...new Set([primary, ...scope.units.map((unit) => unit.kind)].filter(Boolean))];
    if (!kinds.includes(selection.kind)) selection.kind = kinds[0];
    if (!kinds.length) { panel.append(empty("표시할 평가 대상이 없습니다. 평가 대상과 실행별 집계 범위를 확인하세요.")); return; }
    const categories = el("nav", "evaluation-kinds");
    categories.setAttribute("aria-label", "평가 단위 선택");
    const unitChoice = el("div", "evaluation-unit-choice");
    const content = el("div");
    for (const kind of kinds) {
      const units = scope.units.filter((unit) => unit.kind === kind);
      const control = button(`${EvaluationCatalog[kind].label} · ${categoryCount(kind, units)}`, () => {
        selection.kind = kind; selection.unit = undefined; selection.metric = undefined; chooseKind();
      });
      control.dataset.kind = kind;
      categories.append(control);
    }
    function chooseKind() {
      for (const control of categories.children) control.setAttribute("aria-pressed", String(control.dataset.kind === selection.kind));
      const units = scope.units.filter((unit) => unit.kind === selection.kind);
      unitChoice.replaceChildren(); content.replaceChildren();
      if (!units.length) { content.append(empty("이 실행에 필요한 평가 결과가 기록되지 않았습니다. 미기록을 비적용으로 판단하지 않습니다.")); return; }
      if (!units.some((unit) => unit.id === selection.unit)) selection.unit = units[0].id;
      if (units.length > 1) {
        const label = el("label", "", "평가 대상");
        const picker = el("select");
        picker.setAttribute("aria-label", "평가 대상 선택");
        for (const unit of units) { const option = el("option", "", unit.target); option.value = unit.id; option.selected = unit.id === selection.unit; picker.append(option); }
        picker.addEventListener("change", () => { selection.unit = picker.value; selection.metric = undefined; chooseKind(); });
        label.append(picker); unitChoice.append(label);
      }
      content.append(renderUnit(units.find((unit) => unit.id === selection.unit)));
    }
    panel.append(categories, unitChoice, content, json("평가 파일 전체 원본", evaluation));
    chooseKind();
  }

  return { render };
})();
