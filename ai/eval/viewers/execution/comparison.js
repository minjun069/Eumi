/* Match stored execution expectations to their observed fields; never grade. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ExecutionComparison = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const own = (value, key) => object(value) && Object.hasOwn(value, key);
  const roles = new Set(["report_selection", "report_description", "report_insight"]);
  const fields = [
    ["node_path", "노드 실행 순서"], ["run_status", "실행 반환 상태"],
    ["execution_status", "최종 실행 상태"], ["response_kind", "응답 종류"], ["error_code", "오류 코드"],
  ];
  const missing = unavailable => ({actual: undefined, unavailable});

  function read(source, key, label) {
    return own(source, key) ? {actual: source[key]} : missing(`${label} 기록이 없습니다.`);
  }

  function paths(report) {
    const trace = report?.trace;
    if (!Array.isArray(trace?.spans)) return missing("실행 추적이 제공되지 않았습니다.");
    if (trace.recovery_issues?.length || report.evidence?.issues?.length || report.evidence?.complete === false) {
      return missing("실행 추적의 누락·손상으로 경로를 확인할 수 없습니다.");
    }
    const spans = [...trace.spans].sort((left, right) => (left?.sequence || 0) - (right?.sequence || 0));
    const byId = new Map(), sequences = new Set(), counts = Object.create(null);
    for (const span of spans) {
      if (!object(span) || typeof span.id !== "string" || !span.id || typeof span.name !== "string" ||
          typeof span.kind !== "string" || !Number.isFinite(span.sequence) || !object(span.input) ||
          !own(span, "parent_id") || byId.has(span.id) || sequences.has(span.sequence) ||
          span.status === "unknown" || span.evidence_conflict) {
        return missing("실행 추적의 중복·충돌 또는 필수 정보 누락으로 경로를 확인할 수 없습니다.");
      }
      byId.set(span.id, span); sequences.add(span.sequence);
      counts[span.kind] = (counts[span.kind] || 0) + 1;
    }
    const roots = spans.filter(span => span.parent_id === null);
    if (roots.length !== 1 || !["evaluation", "execution"].includes(roots[0].kind)) {
      return missing("실행 진입 경계를 확인할 수 없습니다.");
    }
    for (const span of spans) {
      if (span.parent_id !== null && (!byId.has(span.parent_id) || byId.get(span.parent_id).sequence >= span.sequence)) {
        return missing("상위 호출 기록의 누락·순서 충돌로 경로를 확인할 수 없습니다.");
      }
    }
    if (object(trace.counts) && (Object.keys(trace.counts).length !== Object.keys(counts).length ||
        Object.entries(counts).some(([kind, count]) => trace.counts[kind] !== count))) {
      return missing("실행 추적의 호출 개수가 일치하지 않아 경로를 확인할 수 없습니다.");
    }
    if (own(trace.coverage, "unfinished_spans") && trace.coverage.unfinished_spans !== spans.filter(span => span.ended_at == null).length) {
      return missing("실행 추적의 종료 기록이 일치하지 않아 경로를 확인할 수 없습니다.");
    }
    const isReportRole = span => span.kind === "agent" && roles.has(span.input.role);
    const visible = span => {
      let parent = byId.get(span.parent_id);
      while (parent) {
        if (parent.kind === "agent" && !isReportRole(parent)) return false;
        parent = byId.get(parent.parent_id);
      }
      return true;
    };
    return {node_path: spans.filter(span => span.kind === "node" && span.name !== "wait" && visible(span)).map(span => span.name),
      role_path: spans.filter(isReportRole).map(span => span.input.role)};
  }

  function rows(report, expected, scored, runInfo = report?.run) {
    const selected = [...fields];
    if ((runInfo?.unit === "workflow" && runInfo.target === "report") || own(expected, "role_path") || own(expected, "report_completeness")) {
      selected.push(["role_path", "보고서 역할 순서"], ["report_completeness", "보고서 완성 범위"]);
    }
    const observedPaths = report ? paths(report) : missing("실행 결과가 제공되지 않았습니다.");
    const state = object(report?.state) && object(report.state.execution) ? report.state : null;
    function actual(key) {
      if (key === "report_completeness") {
        if (!own(scored, key)) return missing("선택한 채점 기록에 보고서 완성 범위가 없습니다.");
        return scored[key] === null ? missing("보고서 완성 범위를 확인할 수 없습니다.") : {actual: scored[key]};
      }
      if (!report) return missing("실행 결과가 제공되지 않았습니다.");
      if (key === "node_path" || key === "role_path") return observedPaths.unavailable ? observedPaths : {actual: observedPaths[key]};
      if (key === "run_status") return read(report.run, "status", "실행 반환 상태");
      if (!state) return missing("최종 실행 상태가 제공되지 않았습니다.");
      if (key === "execution_status") return read(state.execution, "status", "최종 실행 상태");
      const source = key === "response_kind" ? state.response : state.execution.error;
      if (source === null) return {actual: null};
      return read(source, key === "response_kind" ? "kind" : "code", key === "response_kind" ? "응답 종류" : "오류 코드");
    }
    return selected.map(([key, label]) => ({key, label, expected: own(expected, key) ? expected[key] : undefined, ...actual(key)}));
  }

  return {rows};
});
