/* Dataset references and recorded execution steps are displayed separately. */
(function (root, factory) {
  const catalog = typeof module === "object" && module.exports ? require("./scenarios.js") : root.ExecutionScenarioCatalog;
  const api = factory(catalog);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ExecutionScenarios = api;
})(typeof globalThis === "object" ? globalThis : this, function (catalog) {
  "use strict";
  const roles = {
    request: "사용자 요청 처리", interpretation: "데이터 분석 결과 해석", visualization: "데이터 시각화",
    report_selection: "보고서 시각화 선정", report_description: "보고서 시각화 설명", report_insight: "보고서 퀵 인사이트",
  };
  const nodes = {interpret: "작업 목적 파악", decide: "작업 진행 판단", act: "작업 선택·실행", compose: "응답 작성", ask: "사용자 정보 요청", wait: "사용자 응답 대기"};
  const actions = {
    interpretation_agent: "해석 역할 호출", visualization_agent: "시각화 역할 호출",
    query_data: "자료 조회", process_data: "자료 계산", validate_visualization: "시각화 설정 검사", render_visualization: "시각화 생성",
  };
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const escape = value => String(value).replace(/[&<>"']/g, character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character]));
  const scenarios = new Map((catalog?.scenarios || []).map(item => [item.id, item]));

  function reference(run, batch) {
    const conditions = run?.manifest?.evaluation;
    if (!conditions || !Array.isArray(conditions.source_selection) || !conditions.source_files_sha256 || !catalog) return null;
    const identities = [run.report?.run, run.entry, run.case && {case_id: run.case.id, unit: run.case.unit, target: run.case.target}].filter(Boolean);
    if (!identities.length) return null;
    const identity = identities[0];
    if (identities.some(item => ["case_id", "unit", "target"].some(key => item[key] !== identity[key]))) return null;
    if (run.report?.run && run.report.run.role !== (identity.unit === "agent" ? identity.target : null)) return null;
    const suiteIds = [run.report?.run?.suite_id, batch?.report?.suite_id, batch?.suite?.id].filter(Boolean);
    if (suiteIds.some(id => id !== conditions.suite_id)) return null;
    const selections = conditions.source_selection.filter(item => item?.scenario_id === identity.case_id);
    if (selections.length !== 1) return null;
    const selection = selections[0], scenario = scenarios.get(identity.case_id);
    if (!scenario || selection.unit !== identity.unit || selection.target !== identity.target || selection.scenario_file !== scenario.file) return null;
    // Unrelated index edits do not change the selected scenario's saved source bytes.
    if (conditions.source_files_sha256[scenario.file] !== scenario.sha256) return null;
    const selected = [scenario];
    if (identity.unit === "agent") {
      if (identity.target !== scenario.role || selection.entry_state !== "start_state") return null;
    } else if (identity.unit === "workflow" && identity.target === "report") {
      if (scenario.role !== "report_selection" || selection.entry_state !== "entry_transition.before_state") return null;
      for (const role of ["report_description", "report_insight"]) {
        const previous = selected[selected.length - 1];
        const next = [...scenarios.values()].filter(item => item.upstream === previous.id && item.role === role);
        if (next.length !== 1 || conditions.source_files_sha256[next[0].file] !== next[0].sha256) return null;
        selected.push(next[0]);
      }
    } else return null;
    return {name: identity.unit === "workflow" ? `${scenario.title} · 보고서 전체` : scenario.title,
      description: scenario.description, steps: selected.flatMap(item => item.steps)};
  }

  function actual(run) {
    const missing = reason => ({steps: null, reason});
    let trace = run?.report?.trace;
    if (trace?.recovery_issues?.length || run?.report?.evidence?.issues?.length || run?.report?.evidence?.complete === false) {
      return missing("실행 추적의 누락·손상으로 순서를 확인할 수 없습니다.");
    }
    // Journals contain repeated snapshots, not repeated calls. Keep each call's latest snapshot.
    if (!Array.isArray(trace?.spans) || !trace.spans.length) {
      if (!run?.journal?.length) return missing("실제 실행 기록 미제공");
      if (run.availability?.journal === "invalid" || run.issues?.some(issue => issue.code === "invalid-journal-line")) {
        return missing("시간순 실행 기록의 손상으로 순서를 확인할 수 없습니다.");
      }
      const latest = new Map();
      for (const event of run.journal) {
        const span = event?.span, previous = latest.get(span?.id);
        if (!object(span) || !["start", "update", "end"].includes(event.event) ||
            (previous && ["parent_id", "sequence", "kind", "name"].some(key => previous[key] !== span[key]))) {
          return missing("시간순 실행 기록의 호출 정보가 서로 일치하지 않습니다.");
        }
        latest.set(span.id, span);
      }
      trace = {spans: [...latest.values()]};
    }
    const spans = [...trace.spans].sort((a, b) => (a?.sequence || 0) - (b?.sequence || 0));
    const byId = new Map(), sequences = new Set(), counts = new Map();
    for (const span of spans) {
      if (!object(span) || typeof span.id !== "string" || !span.id || typeof span.name !== "string" ||
          typeof span.kind !== "string" || !Number.isInteger(span.sequence) || span.sequence < 1 ||
          !Object.hasOwn(span, "parent_id") || byId.has(span.id) || sequences.has(span.sequence) ||
          span.status === "unknown" || span.evidence_conflict) {
        return missing("실행 추적의 중복·충돌 또는 필수 정보 누락으로 순서를 확인할 수 없습니다.");
      }
      byId.set(span.id, span); sequences.add(span.sequence);
      counts.set(span.kind, (counts.get(span.kind) || 0) + 1);
    }
    const roots = spans.filter(span => span.parent_id === null);
    if (roots.length !== 1 || !["evaluation", "execution"].includes(roots[0].kind)) return missing("실행 진입 기록을 확인할 수 없습니다.");
    for (const span of spans) {
      if (span.parent_id !== null && (!byId.has(span.parent_id) || byId.get(span.parent_id).sequence >= span.sequence)) {
        return missing("상위 호출 기록의 누락·순서 충돌로 실행 순서를 확인할 수 없습니다.");
      }
    }
    if (object(trace.counts) && (Object.keys(trace.counts).length !== counts.size || [...counts].some(([kind, count]) => trace.counts[kind] !== count))) {
      return missing("실행 추적의 호출 개수가 일치하지 않습니다.");
    }
    const ancestor = (span, predicate) => {
      let parent = byId.get(span.parent_id);
      while (parent && !predicate(parent)) parent = byId.get(parent.parent_id);
      return parent;
    };
    const frames = spans.filter(span => ["agent", "execution"].includes(span.kind));
    const frameNumbers = new Map(frames.map((span, index) => [span.id, index + 1]));
    const calls = new Map();
    for (const call of spans.filter(span => ["agent", "tool"].includes(span.kind))) {
      const node = ancestor(call, parent => parent.kind === "node");
      if (node) {
        if (!calls.has(node.id)) calls.set(node.id, []);
        calls.get(node.id).push(call.name);
      }
    }
    const steps = spans.filter(span => span.kind === "node").map(span => {
      const frame = ancestor(span, parent => frameNumbers.has(parent.id));
      const owner = ancestor(span, parent => parent.kind === "agent" || typeof parent.input?.role === "string" || (parent.kind === "execution" && roles[parent.name]));
      const role = owner ? owner.input?.role || (owner.kind === "execution" ? owner.name : null) : run.report?.run?.role;
      const parentFrame = frame && ancestor(frame, parent => frameNumbers.has(parent.id));
      const frameLabel = frame ? `${frame.kind === "agent" ? "하위 호출" : "실행"} ${frameNumbers.get(frame.id)}` +
        (parentFrame ? ` · 상위 ${frameNumbers.get(parentFrame.id)}` : "") : "";
      return {node: span.name, role, frameLabel, calls: calls.get(span.id) || [], sequence: span.sequence};
    });
    return steps.length ? {steps} : missing("기록된 실행 노드가 없습니다.");
  }

  function diagram(steps, kind, reason) {
    const isReference = kind === "reference";
    const title = isReference ? "이상적인 시나리오" : "실제 실행 결과";
    const note = isReference ? "데이터셋 기준 도식" : "실행 추적에 기록된 노드 시작 순서";
    return `<section class="scenario-diagram scenario-${kind}"><h3>${title}${steps ? `<small>${note}</small>` : ""}</h3>` +
      (steps ? `<ol class="scenario-flow">${steps.map((step, index) => {
        const calls = step.calls || (step.action ? [step.action] : []);
        return `<li class="scenario-step"${step.sequence ? ` data-sequence="${step.sequence}"` : ""}><span class="step-position">${index + 1}</span>` +
          `<strong>${escape(nodes[step.node] || step.node)}</strong><small>${escape(roles[step.role] || step.role || "역할 미기록")}</small>` +
          (step.frameLabel ? `<small>${escape(step.frameLabel)}</small>` : "") +
          calls.map(call => `<small>호출: ${escape(actions[call] || call)}</small>`).join("") + "</li>";
      }).join("")}</ol>` : `<p class="hint">${escape(reason)}</p>`) + "</section>";
  }

  function resolve(run, batch) {
    const ideal = reference(run, batch), observed = actual(run);
    if (!ideal && !observed.steps) return null;
    return {name: ideal?.name || run?.case?.purpose || run?.report?.run?.case_id || run?.entry?.case_id || run?.case?.id,
      description: ideal?.description || "",
      html: diagram(ideal?.steps, "reference", "이상적인 시나리오 미제공 · 실행 당시 시나리오 본문을 확인할 수 없습니다.") +
        diagram(observed.steps, "actual", observed.reason)};
  }
  return {resolve};
});
