/* Presentation-only rollups. Loaded assessments and execution artifacts stay unchanged. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./run-metrics.js"));
  else root.NodeAggregateMetrics = factory(root.NodeRunMetrics);
})(typeof globalThis !== "undefined" ? globalThis : this, function (runMetrics) {
  "use strict";
  const list = value => Array.isArray(value) ? value : [];
  const key = (...parts) => JSON.stringify(parts);
  const count = value => Number.isInteger(value) && value >= 0 ? value : 0;
  const number = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const fields = ["passed", "failed", "undetermined", "not_applicable", "unexecuted", "skipped_after_failure"];
  const copy = value => JSON.parse(JSON.stringify(value));
  function canonical(value) {
    if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
    if (value && typeof value === "object") return `{${Object.keys(value).sort().map(name => `${JSON.stringify(name)}:${canonical(value[name])}`).join(",")}}`;
    return JSON.stringify(value);
  }
  function distinct(values) {
    if (values.length < 2) return values.slice();
    return [...new Map(values.map(value => [canonical(value), value])).values()];
  }
  function uniqueNodes(nodes) {
    const groups = new Map();
    for (const node of list(nodes)) {
      const identity = key(node.node, node.role);
      if (!groups.has(identity)) groups.set(identity, node);
      else if (canonical(groups.get(identity)) !== canonical(node)) throw new Error("같은 노드·역할의 집계 자료가 서로 다릅니다.");
    }
    return [...groups.values()];
  }
  function overall(items) {
    const complete = items.length > 0 && items.every(item => item.complete === true);
    return {complete, verdict: items.some(item => item.verdict === "실패") ? "실패"
      : complete && items.every(item => item.verdict === "통과") ? "통과" : "미판정"};
  }
  function cases(nodes) {
    const groups = new Map();
    for (const node of nodes) for (const item of list(node.functional?.cases?.items)) {
      const identity = key(node.node, node.role, item.case_id);
      if (!groups.has(identity)) groups.set(identity, []);
      groups.get(identity).push({...item, node: node.node, role: node.role});
    }
    return [...groups.values()].map(values => {
      const records = distinct(values);
      if (records.length === 1) return copy(records[0]);
      // Conflicting duplicate case summaries cannot prove completion; a recorded failure remains a failure.
      const result = copy(records[0]);
      result.complete = false;
      result.verdict = records.some(item => item.verdict === "실패") ? "실패" : "미판정";
      result.reason = "같은 노드·역할·사례의 집계 기록이 서로 다릅니다.";
      for (const field of ["missing_repetitions", "incomplete_repetitions", "excluded_repetitions", "missing_expectations", "missing_checks"]) {
        result[field] = copy(distinct(records.flatMap(item => list(item[field]))));
      }
      return result;
    });
  }
  function checkTotals(nodes, details) {
    const groups = new Map();
    for (const node of nodes) {
      const checks = list(node.functional?.checks);
      const source = details ? list(node.functional?.details) : checks;
      for (const item of distinct(source)) {
        const metadata = details ? checks.filter(check => check.check === item.check) : [item];
        // Detail IDs belong to their parent check's axis and method, not just its display ID.
        const parent = metadata.length === 1 ? metadata[0] : item;
        const identity = details ? {check: item.check, id: item.id, axis: parent.axis ?? "", method: parent.method ?? ""}
          : {check: item.check, axis: item.axis, method: item.method};
        const id = key(identity.check, identity.axis, identity.method, details ? identity.id : null);
        if (!groups.has(id)) groups.set(id, {...identity, ...Object.fromEntries(fields.map(field => [field, 0]))});
        const target = groups.get(id);
        for (const field of fields) target[field] += count(item[field]);
      }
    }
    return [...groups.values()].map(item => ({...item, numerator: item.passed, denominator: item.passed + item.failed,
      rate: item.passed + item.failed ? item.passed / (item.passed + item.failed) : null}));
  }
  function functional(nodes) {
    const items = cases(nodes);
    const passed = items.filter(item => item.verdict === "통과").length;
    const failed = items.filter(item => item.verdict === "실패").length;
    const completed = items.filter(item => item.complete === true).length;
    return {...overall(items), checks: checkTotals(nodes, false), details: checkTotals(nodes, true),
      cases: {items, total: items.length, numerator: passed, denominator: items.length,
        rate: items.length ? passed / items.length : null, passed, failed, undetermined: items.length - passed - failed,
        excluded: 0, unspecified_required: items.filter(item => item.required == null).length},
      verification: {total_cases: items.length, completed_cases: completed, incomplete_cases: items.length - completed,
        missing_repetitions: items.reduce((sum, item) => sum + new Set(list(item.missing_repetitions)).size, 0)}};
  }
  function observations(nodes, reports, evaluation) {
    const byScope = new Map(nodes.map(node => [key(node.node, node.role), []]));
    const reportGroups = new Map();
    for (const report of list(reports)) {
      const id = key(report?.run?.id, report?.run?.case_id, report?.run?.repetition);
      if (!reportGroups.has(id)) reportGroups.set(id, []);
      const group = reportGroups.get(id);
      if (!group.includes(report)) group.push(report);
    }
    // Traces can be large; compare their contents only when duplicate identities actually exist.
    const originals = [...reportGroups.values()].flatMap(distinct);
    const identities = new Map();
    const conflicts = new Set(nodes.flatMap(node => list(node.conflicting_assessments).concat(list(node.conflicting_evidence))).map(identity => key(...identity)));
    const grouped = new Map();
    for (const item of list(evaluation?.assessments)) {
      if (item.counted === false || !byScope.has(key(item.node, item.role))) continue;
      const id = key(item.run_id, item.node_id);
      if (!grouped.has(id)) grouped.set(id, []);
      grouped.get(id).push(item);
    }
    const assessments = [];
    for (const [id, values] of grouped) {
      const records = distinct(values);
      if (records.length !== 1 || conflicts.has(id)) continue;
      const item = records[0];
      assessments.push(item);
      identities.set(key(item.run_id, item.case_id, item.repetition), item);
    }
    const source = {...evaluation, assessments};
    for (const identity of identities.values()) {
      const candidates = originals.filter(report => report?.run?.id === identity.run_id
        && report.run.case_id === identity.case_id && report.run.repetition === identity.repetition);
      if (candidates.length !== 1) continue;
      const result = runMetrics.forRun(candidates[0], source, {runId: identity.run_id, caseId: identity.case_id, repetition: identity.repetition});
      for (const value of result.nodes) {
        const target = byScope.get(key(value.node, value.role));
        // forRun also supports unscored standalone input; only counted assessment evidence belongs in this rollup.
        if (!target || !value.functional || !value.calls.length) continue;
        target.push(value.operational);
      }
    }
    return byScope;
  }
  function statistics(values, missing, unfinished, rawMissing) {
    const ordered = [...values].sort((a, b) => a - b), size = ordered.length;
    return {sample_count: size, missing_count: missing, unfinished_count: unfinished, raw_missing_count: rawMissing,
      mean: size ? ordered.reduce((sum, value) => sum + value, 0) / size : null,
      median: size ? (size % 2 ? ordered[(size - 1) / 2] : (ordered[size / 2 - 1] + ordered[size / 2]) / 2) : null,
      p95: size ? ordered[Math.ceil(.95 * size) - 1] : null};
  }
  function operational(nodes, reports, evaluation) {
    const observed = observations(nodes, reports, evaluation);
    const sum = get => nodes.reduce((total, node) => total + count(get(node.operational ?? {})), 0);
    function pooled(saved, raw, filter = () => true, integer = true) {
      let missing = 0, unfinished = 0, rawMissing = 0;
      const values = [];
      for (const node of nodes) {
        const expected = saved(node.operational ?? {}) ?? {};
        const sampleCount = count(expected.sample_count);
        let found = list(observed.get(key(node.node, node.role))).filter(value => !value.unfinished && filter(value))
          .map(raw).filter(value => integer ? Number.isInteger(value) && value >= 0 : number(value));
        // A mismatch cannot be fixed by selecting arbitrary observations from a different population.
        if (found.length > sampleCount) found = [];
        values.push(...found);
        rawMissing += sampleCount - found.length;
        missing += count(expected.missing_count) + sampleCount - found.length;
        unfinished += count(expected.unfinished_count);
      }
      return statistics(values, missing, unfinished, rawMissing);
    }
    const numerator = sum(ops => ops.failure_rate?.numerator), denominator = sum(ops => ops.failure_rate?.denominator);
    const retry = pooled(ops => ops.technical_retries, value => value.technicalRetries);
    const result = {...overall(nodes.map(node => node.operational ?? {})), measurement_scope: "selected_model_calls",
      failure_rate: {numerator, denominator, rate: denominator ? numerator / denominator : null,
        missing_count: sum(ops => ops.failure_rate?.missing_count), unfinished_count: sum(ops => ops.failure_rate?.unfinished_count)},
      response_time: {
        normal: pooled(ops => ops.response_time?.normal, value => value.elapsedSeconds, value => value.technicalFailure === false, false),
        error: pooled(ops => ops.response_time?.error, value => value.elapsedSeconds, value => value.technicalFailure === true, false),
        unclassified_count: sum(ops => ops.response_time?.unclassified_count), unfinished_count: sum(ops => ops.response_time?.unfinished_count)},
      tokens: {input_tokens: pooled(ops => ops.tokens?.input_tokens, value => value.inputTokens), output_tokens: pooled(ops => ops.tokens?.output_tokens, value => value.outputTokens)},
      model_calls: pooled(ops => ops.model_calls, value => value.modelCalls), technical_retries: retry,
      technical_retries_by_kind: {
        model: pooled(ops => ops.technical_retries_by_kind?.model, value => value.technicalRetries),
        tool: pooled(ops => ops.technical_retries_by_kind?.tool, () => null),
        agent: pooled(ops => ops.technical_retries_by_kind?.agent, () => null)},
      unfinished_usage: nodes.flatMap(node => list(node.operational?.unfinished_usage).map(item => ({...copy(item), node: node.node, role: node.role})))};
    const distributions = [result.response_time.normal, result.response_time.error, ...Object.values(result.tokens),
      result.model_calls, result.technical_retries, ...Object.values(result.technical_retries_by_kind)];
    result.source_issues = distributions.some(item => item.raw_missing_count > 0)
      ? [distributions.some(item => item.sample_count > 0)
        ? "실행 원본 일부를 확인할 수 없어 운영 통계는 확인된 측정값만 집계했습니다. 확인되지 않은 측정값은 누락으로 표시합니다."
        : "실행 원본을 확인할 수 없어 응답시간·사용량 통계를 계산할 수 없습니다. 저장된 실패율과 운영 판정은 그대로 표시합니다."] : [];
    return result;
  }
  function forNode(node) {
    return {...node, functional: functional([node])};
  }
  function forAll(nodes, reports, evaluation) {
    const unique = uniqueNodes(nodes);
    const f = functional(unique), ops = operational(unique, reports, evaluation);
    return {node: "all", role: "all", runs: unique.reduce((total, node) => total + count(node.runs), 0), functional: f, operational: ops,
      performance: unique.flatMap(node => list(node.performance).map(item => ({...copy(item), node: node.node, role: node.role}))),
      ...overall([f, ops]), verdict_scope: "전체 사례 기능과 지정된 운영 목표", conflicting_assessments: [], conflicting_evidence: []};
  }
  return Object.freeze({forNode, forAll});
});
