/* Read-only per-run observations from saved node scoring and model traces. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.NodeRunMetrics = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  const nodes = new Set(["interpret", "act", "decide", "compose", "ask"]);
  const roles = new Set(["request", "interpretation", "visualization", "report_selection", "report_description", "report_insight"]);
  const fields = ["elapsedSeconds", "inputTokens", "outputTokens", "modelCalls", "technicalRetries"];
  const list = value => Array.isArray(value) ? value : [];
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value || {}, key);
  const number = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const integer = value => number(value) && Number.isInteger(value);
  const same = (left, right) => {
    if (left === right) return true;
    if (!left || !right || typeof left !== "object" || typeof right !== "object" || Array.isArray(left) !== Array.isArray(right)) return false;
    const keys = Object.keys(left);
    return keys.length === Object.keys(right).length && keys.every(key => own(right, key) && same(left[key], right[key]));
  };
  const key = (node, role) => JSON.stringify([node, role]);
  const matches = (item, scope) => (!own(scope, "node") || item.node === scope.node) && (!own(scope, "role") || item.role === scope.role);
  const sameRun = (item, identity) => item.case_id === identity.caseId && item.repetition === identity.repetition && item.run_id === identity.runId;
  const technicalErrors = new Set(["TimeoutError", "ConnectionError", "ConnectionResetError", "ConnectionRefusedError", "APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError", "CancelledError", "LimitReached", "RuntimeError", "OSError"]);
  const technicalCodes = new Set(["execution_limit_exceeded", "timeout", "connection_error", "connection_failed", "provider_timeout", "provider_unavailable", "service_unavailable"]);
  const reportModels = {select_report_views: "ReportSelection", write_report: "ReportText", review_report: "Verification"};

  function technical(error) {
    if (!error || typeof error !== "object") return null;
    const type = error.type ?? error.error_type;
    if (technicalErrors.has(type) || technicalCodes.has(error.code)) return true;
    if (["ValidationError", "JSONDecodeError", "InvalidModelJSON"].includes(type) || ["invalid_input", "invalid_data_reference"].includes(error.code)) return false;
    return technical(error.cause);
  }

  function rawResponse(span) {
    const response = span.output?.sdk_response;
    if (typeof response?.text === "string") return response.text;
    if (typeof response?.content === "string") return response.content;
    const parts = list(response?.content).filter(item => ["text", "output_text"].includes(item?.type) && typeof item.text === "string").map(item => item.text);
    return parts.length ? parts.join("") : null;
  }

  function traceGraph(report) {
    const byId = new Map(), conflicts = new Set();
    for (const span of list(report?.trace?.spans)) {
      if (!span || typeof span.id !== "string" || !span.id) continue;
      if (byId.has(span.id)) {
        if (!same(byId.get(span.id), span)) conflicts.add(span.id);
      } else byId.set(span.id, span);
    }
    const chains = new Map();
    for (const span of byId.values()) {
      const seen = new Set([span.id]), chain = [];
      let parent = span.parent_id, valid = !conflicts.has(span.id);
      while (parent != null) {
        if (seen.has(parent) || !byId.has(parent)) { valid = false; break; }
        seen.add(parent);
        const ancestor = byId.get(parent);
        chain.push(ancestor);
        if (conflicts.has(parent)) valid = false;
        parent = ancestor.parent_id;
      }
      chains.set(span.id, {chain, valid});
    }
    const nearest = span => chains.get(span.id)?.chain.find(item => item.kind === "node" && nodes.has(item.name));
    const owned = node => [...byId.values()].filter(span => nearest(span)?.id === node.id);
    return {byId, chains, owned};
  }

  function roleOf(node, graph, report) {
    if (roles.has(node.input?.role)) return node.input.role;
    const agents = (graph.chains.get(node.id)?.chain || []).filter(item => item.kind === "agent");
    const ancestor = agents.find(item => roles.has(item.input?.role));
    if (ancestor) return ancestor.input.role;
    const name = agents.map(item => item.name?.replace(/_agent$/, "")).find(item => roles.has(item));
    if (name) return name;
    const labels = {"행정동 보고서의 시각화 선정·근거 확보 역할이다.": "report_selection", "현재 역할은 시각화 설명 에이전트다.": "report_description", "현재 역할은 퀵 인사이트 에이전트다.": "report_insight", "현재 역할은 사용자 요청 처리 Agent다.": "request", "현재 역할은 데이터 분석 결과 해석 Agent다.": "interpretation", "현재 역할은 데이터 시각화 Agent다.": "visualization"};
    const found = new Set();
    for (const call of graph.owned(node).filter(item => item.kind === "model")) {
      for (const message of list(call.input?.messages)) {
        if (message?.type !== "system" || typeof message.content !== "string") continue;
        for (const [phrase, role] of Object.entries(labels)) if (message.content.includes(phrase)) found.add(role);
      }
    }
    if (found.size === 1) return [...found][0];
    return roles.has(report?.run?.role) ? report.run.role : null;
  }

  function rate(items) {
    const result = {numerator: 0, denominator: 0, rate: null, passed: 0, failed: 0, undetermined: 0, not_applicable: 0, unexecuted: 0, skipped_after_failure: 0};
    const verdicts = {"통과": "passed", "실패": "failed", "미판정": "undetermined", "비적용": "not_applicable"};
    for (const item of items) {
      if (!item.executed) {
        result.unexecuted++;
        if (String(item.reason || "").includes("선행 단계 실패")) result.skipped_after_failure++;
      } else result[verdicts[item.verdict] || "undetermined"]++;
    }
    result.numerator = result.passed;
    result.denominator = result.passed + result.failed;
    result.rate = result.denominator ? result.numerator / result.denominator : null;
    return result;
  }

  function distinctChecks(assessment) {
    const seen = new Set();
    return list(assessment?.checks).filter(check => !seen.has(check.check) && seen.add(check.check));
  }

  function distinctDetails(check) {
    const seen = new Set();
    return list(check.details).filter(detail => !seen.has(detail.id) && seen.add(detail.id));
  }

  function counts(items) {
    const r = rate(items);
    return {passed: r.passed, failed: r.failed, undetermined: r.undetermined, notApplicable: r.not_applicable, notExecuted: r.unexecuted, skippedAfterFailure: r.skipped_after_failure, total: items.length};
  }

  function unavailable(reason) {
    return {...Object.fromEntries(fields.map(field => [field, null])), technicalFailure: null, unfinished: false, observed: null, reason,
      missingReasons: Object.fromEntries(fields.map(field => [field, reason]))};
  }

  function savedObservation(evaluation, entry, identity) {
    const values = list(evaluation?.nodes).filter(item => item.node === entry.node && item.role === entry.role)
      .flatMap(item => list(item.operational?.unfinished_usage)).filter(item => item.node_id === entry.nodeId && sameRun(item, identity));
    if (values.length !== 1) return null;
    const value = values[0];
    return {inputTokens: integer(value.usage?.input_tokens) ? value.usage.input_tokens : null,
      outputTokens: integer(value.usage?.output_tokens) ? value.usage.output_tokens : null,
      inputMissingCalls: integer(value.usage_missing_calls?.input_tokens) ? value.usage_missing_calls.input_tokens : null,
      outputMissingCalls: integer(value.usage_missing_calls?.output_tokens) ? value.usage_missing_calls.output_tokens : null,
      modelCalls: integer(value.model_calls) ? value.model_calls : null};
  }

  function retries(node, owned, graph) {
    // Same records and action-kind boundary as node_evidence._retries.
    const before = node.input?.state?.results, after = node.output?.applied_update?.results;
    if (!node.ended_at || !Array.isArray(before) || !Array.isArray(after) || owned.some(span => !span.ended_at || !graph.chains.get(span.id)?.valid)) return null;
    const old = new Set(before.map(item => item.id)), byId = new Map(after.map(item => [item.id, item]));
    let count = 0;
    function add(record, isTechnical) {
      if (isTechnical === false) return;
      const name = record?.action?.name;
      const kinds = new Set(owned.filter(span => ["model", "tool", "agent"].includes(span.kind) && (span.name === name || span.kind === "model" && span.name === reportModels[name])).map(span => span.kind));
      if (kinds.size !== 1) count = null;
      else if (kinds.has("model")) {
        if (isTechnical == null) count = null;
        else if (count != null) count++;
      }
    }
    for (let index = 0; index < after.length; index++) {
      const item = after[index];
      if (old.has(item.id)) continue;
      if (item.decision === "retry") {
        const previous = byId.get(item.output?.call_id);
        if (!previous) { add(null, null); continue; }
        if (previous.outcome === "success") continue;
        const failed = technical(previous.output);
        if (failed == null) { add(previous, null); continue; }
        const following = after.slice(index + 1).find(record => record.action);
        if (!following) { add(previous, null); continue; }
        if (failed && same(following.action, previous.action)) add(following, true);
      }
      if (item.decision === "verification" && item.action) {
        const prior = after.slice(0, index).reverse().find(record => record.decision === "verification" && same(record.action, item.action));
        if (prior?.outcome === "failure") add(item, technical(prior.output));
      }
    }
    return count;
  }

  function observations(selected, node, owned, graph) {
    const result = unavailable("");
    result.missingReasons = {};
    result.unfinished = selected.some(span => !span.ended_at);
    const usage = (span, field) => {
      const value = span.output?.sdk_response?.usage_metadata?.[field];
      return integer(value) ? value : null;
    };
    if (result.unfinished) {
      const observed = {modelCalls: selected.length};
      for (const [field, api, missing] of [["input_tokens", "inputTokens", "inputMissingCalls"], ["output_tokens", "outputTokens", "outputMissingCalls"]]) {
        const values = selected.map(span => usage(span, field)), measured = values.filter(value => value != null);
        observed[api] = measured.length ? measured.reduce((a, b) => a + b, 0) : null;
        observed[missing] = values.length - measured.length;
      }
      result.observed = observed;
      result.reason = "선택한 모델 호출이 아직 종료되지 않아 관측량만 제공합니다.";
      result.missingReasons = Object.fromEntries(fields.map(field => [field, result.reason]));
      return result;
    }
    const failures = selected.map(span => rawResponse(span) !== null ? false : technical(span.error) === true ? true : null);
    result.technicalFailure = failures.includes(true) ? true : failures.includes(null) ? null : false;
    result.elapsedSeconds = selected.every(span => number(span.elapsed_seconds)) ? selected.reduce((sum, span) => sum + span.elapsed_seconds, 0) : null;
    if (result.elapsedSeconds == null) result.missingReasons.elapsedSeconds = "선택한 모델 호출의 응답시간 기록이 누락됐습니다.";
    for (const [field, api] of [["input_tokens", "inputTokens"], ["output_tokens", "outputTokens"]]) {
      const values = selected.map(span => usage(span, field));
      result[api] = values.every(value => value != null) ? values.reduce((a, b) => a + b, 0) : null;
      if (result[api] == null) result.missingReasons[api] = "선택한 모델 호출 중 토큰 사용량이 기록되지 않은 호출이 있습니다.";
    }
    result.modelCalls = selected.length;
    const allModels = owned.filter(span => span.kind === "model");
    result.technicalRetries = node.input?.evaluation_scope === "model_output" && selected.length === 1 ? 0 : selected.length === allModels.length ? retries(node, owned, graph) : null;
    if (result.technicalRetries == null) result.missingReasons.technicalRetries = selected.length !== allModels.length ? "일부 모델 호출만 선택되어 기술적 재시도 횟수를 확정할 수 없습니다." : "기술적 재시도를 확인할 작업 이력·호출 연결이 부족합니다.";
    return result;
  }

  function callView(span, index) {
    const raw = rawResponse(span);
    let output = null;
    if (raw !== null) { try { output = JSON.parse(raw); } catch (_) { /* Preserve invalid raw output. */ } }
    return {id: span.id, name: span.name, index, input: Array.isArray(span.input?.messages) ? span.input.messages : null, output, raw, error: span.error || null};
  }

  function forRun(report, evaluation, scope = {}) {
    const identity = {caseId: scope.caseId ?? report?.run?.case_id, repetition: scope.repetition ?? report?.run?.repetition, runId: own(scope, "runId") ? scope.runId : report?.run?.id};
    const candidate = list(evaluation?.runs).filter(item => (!identity.caseId || item.case_id === identity.caseId) && (identity.repetition == null || item.repetition === identity.repetition) && (identity.runId === undefined || item.run_id === identity.runId));
    if (candidate.length === 1) {
      identity.caseId ??= candidate[0].case_id;
      identity.repetition ??= candidate[0].repetition;
      if (identity.runId === undefined) identity.runId = candidate[0].run_id;
    }
    const original = report;
    if (report && (report.run?.id !== identity.runId || report.run?.case_id !== identity.caseId || report.run?.repetition !== identity.repetition)) report = null;
    const graph = traceGraph(report), standalone = ["node", "selection"].includes(report?.run?.unit);
    const scored = list(evaluation?.assessments).filter(item => sameRun(item, identity) && matches(item, scope));
    const entries = scored.map(assessment => ({assessment, nodeId: assessment.node_id, node: assessment.node, role: assessment.role}));
    if (!scored.length && standalone && matches({node: report.run.target, role: report.run.role}, scope)) {
      const found = [...graph.byId.values()].filter(span => span.kind === "node" && span.name === report.run.target && roleOf(span, graph, report) === report.run.role);
      entries.push({assessment: null, nodeId: found[0]?.id || null, node: report.run.target, role: report.run.role});
    }
    return {nodes: entries.map(entry => {
      const checks = distinctChecks(entry.assessment);
      const result = {...entry, verdict: entry.assessment?.verdict ?? null, complete: entry.assessment?.complete ?? null, checks,
        functional: entry.assessment ? {checks: counts(checks), details: counts(checks.flatMap(distinctDetails))} : null,
        operational: unavailable(original && !report ? "실행 원본의 사례·실행 식별자·반복 순번이 선택한 기록과 다릅니다." : "실행 원본이 제공되지 않았습니다."), calls: []};
      delete result.assessment;
      if (!report) {
        const observed = savedObservation(evaluation, entry, identity);
        if (observed && !original) {
          result.operational.unfinished = true;
          result.operational.observed = observed;
          result.operational.reason = "실행 원본 없이 채점에 저장된 미종료 관측량을 표시합니다.";
        }
        return result;
      }
      const node = graph.byId.get(entry.nodeId);
      if (!node || node.kind !== "node" || node.name !== entry.node || roleOf(node, graph, report) !== entry.role || !graph.chains.get(node.id)?.valid) {
        result.operational = unavailable("선택한 노드·역할과 원본 실행 추적을 연결할 수 없습니다.");
        return result;
      }
      const owned = graph.owned(node), allModels = owned.filter(span => span.kind === "model");
      const refs = new Map();
      let conflict = false;
      for (const call of checks.flatMap(check => list(check.calls))) {
        const previous = refs.get(call.id);
        if (previous && (previous.name !== call.name || previous.index !== call.index)) conflict = true;
        else refs.set(call.id, call);
      }
      // A standalone node always evaluates its first original model boundary.
      if (!entry.assessment && standalone && allModels.length) refs.set(allModels[0].id, {id: allModels[0].id, name: allModels[0].name, index: 1});
      const selected = [...refs.values()].map(ref => allModels.find((span, index) => span.id === ref.id && span.name === ref.name && index + 1 === ref.index));
      const cancelled = evaluation?.status === "cancelled" && !entry.assessment?.complete && !standalone;
      if (conflict || !selected.length || selected.some(span => !span || !graph.chains.get(span.id)?.valid) || cancelled) {
        result.operational = unavailable(cancelled ? "채점 취소로 선택한 모델 호출의 전체 범위를 확정할 수 없습니다." : "선택한 모델 호출의 원본 연결·순번·범위를 확정할 수 없습니다.");
        return result;
      }
      result.calls = selected.map(span => callView(span, allModels.indexOf(span) + 1));
      result.operational = observations(selected, node, owned, graph);
      return result;
    })};
  }

  function statistics(values, missing = 0, unfinished = 0) {
    const sorted = values.slice().sort((a, b) => a - b), count = sorted.length;
    return {sample_count: count, missing_count: missing, unfinished_count: unfinished,
      mean: count ? sorted.reduce((a, b) => a + b, 0) / count : null,
      median: count ? (sorted[Math.floor((count - 1) / 2)] + sorted[Math.floor(count / 2)]) / 2 : null,
      p95: count ? sorted[Math.ceil(0.95 * count) - 1] : null};
  }

  function summarizeOperational(values) {
    const pending = values.filter(item => item.operational.unfinished), finished = values.filter(item => !item.operational.unfinished);
    const known = finished.filter(item => typeof item.operational.technicalFailure === "boolean");
    const failed = known.filter(item => item.operational.technicalFailure).length;
    const result = {measurement_scope: "selected_model_calls", failure_rate: {numerator: failed, denominator: known.length, rate: known.length ? failed / known.length : null, missing_count: finished.length - known.length, unfinished_count: pending.length}, response_time: {unclassified_count: finished.length - known.length, unfinished_count: pending.length}, tokens: {}, unfinished_usage: []};
    for (const [group, failure] of [["normal", false], ["error", true]]) {
      const rows = known.filter(item => item.operational.technicalFailure === failure), measured = rows.map(item => item.operational.elapsedSeconds).filter(number);
      result.response_time[group] = statistics(measured, rows.length - measured.length);
    }
    for (const [field, saved] of [["inputTokens", "input_tokens"], ["outputTokens", "output_tokens"], ["modelCalls", "model_calls"], ["technicalRetries", "technical_retries"]]) {
      const measured = finished.map(item => item.operational[field]).filter(integer), summary = statistics(measured, finished.length - measured.length, pending.length);
      if (saved.endsWith("_tokens")) result.tokens[saved] = summary;
      else result[saved] = summary;
    }
    result.unfinished_usage = pending.map(item => ({node_id: item.nodeId, run_id: item.runId, case_id: item.caseId, repetition: item.repetition,
      usage: {input_tokens: item.operational.observed?.inputTokens ?? null, output_tokens: item.operational.observed?.outputTokens ?? null},
      usage_missing_calls: {input_tokens: item.operational.observed?.inputMissingCalls ?? null, output_tokens: item.operational.observed?.outputMissingCalls ?? null}, model_calls: item.operational.observed?.modelCalls ?? null, technical_retries: null}));
    return result;
  }

  function forCase(reports, evaluation, scope = {}) {
    const originals = list(reports), identities = evaluation ? list(evaluation.runs).filter(item => item.case_id === scope.caseId) : originals.filter(report => report.run.case_id === scope.caseId).map(report => ({case_id: report.run.case_id, repetition: report.run.repetition, run_id: report.run.id}));
    const groups = new Map();
    function group(node, role) {
      const identity = key(node, role);
      if (!groups.has(identity)) groups.set(identity, {node, role, caseSummary: null, runs: [], functional: {checks: [], details: []}, operational: null, values: []});
      return groups.get(identity);
    }
    for (const summary of list(evaluation?.nodes).filter(item => matches(item, scope))) {
      const saved = list(summary.functional?.cases?.items).find(item => item.case_id === scope.caseId);
      if (saved) group(summary.node, summary.role).caseSummary = saved;
    }
    for (const identity of identities) {
      const found = originals.filter(report => report.run.id === identity.run_id && report.run.case_id === identity.case_id && report.run.repetition === identity.repetition);
      const view = forRun(found.length === 1 ? found[0] : null, evaluation, {...scope, caseId: identity.case_id, repetition: identity.repetition, runId: identity.run_id});
      for (const value of view.nodes) {
        const target = group(value.node, value.role);
        target.values.push({...value, runId: identity.run_id, caseId: identity.case_id, repetition: identity.repetition});
      }
    }
    for (const target of groups.values()) {
      const checks = new Map(), details = new Map();
      for (const value of target.values) {
        for (const check of value.checks) {
          const identity = JSON.stringify([check.check, check.axis, check.method]);
          if (!checks.has(identity)) checks.set(identity, {check: check.check, axis: check.axis, method: check.method, items: []});
          checks.get(identity).items.push(check);
          for (const detail of distinctDetails(check)) {
            const detailKey = JSON.stringify([check.check, detail.id]);
            if (!details.has(detailKey)) details.set(detailKey, {check: check.check, id: detail.id, items: []});
            details.get(detailKey).items.push(detail);
          }
        }
      }
      const summarize = collection => [...collection.entries()].sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
        .map(([, {items, ...identity}]) => ({...identity, ...rate(items)}));
      target.functional = {checks: summarize(checks), details: summarize(details)};
      target.operational = summarizeOperational(target.values);
      target.runs = identities.map(identity => ({runId: identity.run_id, repetition: identity.repetition, verdict: identity.verdict ?? null, complete: identity.complete ?? null}));
      delete target.values;
    }
    return {nodes: [...groups.values()]};
  }

  return Object.freeze({forRun, forCase});
});
