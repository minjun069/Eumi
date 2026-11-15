/* 외부 평가 결과의 입력 검사와 표시값. 실행 State와 평가 원본은 변경하지 않습니다. */
"use strict";

globalThis.ReportEvaluation = (() => {
  const verdicts = ["통과", "실패", "미판정", "비적용"];
  const groups = { functional: "기능", operational: "운영", integration: "연동" };
  const events = ["analysis_pipeline", "user_request"];
  const targets = { tools: ["T01", "T02", "T03", "T04"], nodes: ["N01", "N02", "N03", "N04", "N05"] };
  const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const count = (value) => Number.isSafeInteger(value) && value >= 0;
  const string = (value) => typeof value === "string" && value.trim().length > 0;
  const present = (value) => value !== undefined && value !== null;
  function requireValue(valid, message) {
    if (!valid) throw new Error(message);
  }
  function validRunIds(value) {
    return Array.isArray(value) && value.length > 0 && value.every(string) && new Set(value).size === value.length;
  }
  function targetId(unit) {
    return unit.target_id || unit.target.match(/^([TN]\d{2})(?=$|[\s·:：\-])/u)?.[1];
  }
  function normalize(value) {
    requireValue(object(value) && value.type === "evaluation" && value.schema_version === 1,
      "평가 파일은 type: evaluation, schema_version: 1 형식이어야 합니다.");
    requireValue(string(value.id) && string(value.title), "평가 id와 title이 필요합니다.");
    requireValue(typeof value.sample === "boolean", "임시 결과 여부를 sample에 true 또는 false로 기록하세요.");
    requireValue(validRunIds(value.run_ids),
      "평가 대상 실행 ID 목록(run_ids)이 필요합니다.");
    if (value.event !== undefined)
      requireValue(events.includes(value.event), "평가 event는 analysis_pipeline 또는 user_request여야 합니다.");
    requireValue(Array.isArray(value.units), "평가 단위 목록(units)이 필요합니다.");
    const unitIds = new Set();
    for (const unit of value.units) {
      requireValue(object(unit) && string(unit.id) && string(unit.target) &&
        Object.hasOwn(EvaluationCatalog, unit.kind), "평가 단위의 id, kind, target을 확인하세요.");
      requireValue(!unitIds.has(unit.id), `평가 단위 ID 중복: ${unit.id}`);
      unitIds.add(unit.id);
      if (unit.run_ids !== undefined)
        requireValue(validRunIds(unit.run_ids) && unit.run_ids.every((runId) => value.run_ids.includes(runId)),
          `${unit.target}: 단위 run_ids는 평가 파일의 실행 ID에서 중복 없이 지정하세요.`);
      if (unit.target_id !== undefined)
        requireValue(targets[unit.kind]?.includes(unit.target_id),
          `${unit.target}: target_id는 도구 T01~T04 또는 노드 N01~N05여야 합니다.`);
      requireValue(unit.executions === undefined || Array.isArray(unit.executions),
        `${unit.target}: executions 목록을 확인하세요.`);
      const executionIds = new Set();
      for (const execution of unit.executions || []) {
        requireValue(object(execution) && ["id", "name", "caller", "run_id", "status", "evidence"].every((key) => string(execution[key])),
          `${unit.target}: 실행 기록에는 id, name, caller, run_id, status, evidence가 필요합니다.`);
        requireValue(!executionIds.has(execution.id), `${unit.target}: 실행 ID 중복: ${execution.id}`);
        executionIds.add(execution.id);
        if (execution.elapsed_seconds !== undefined)
          requireValue(typeof execution.elapsed_seconds === "number" && Number.isFinite(execution.elapsed_seconds) && execution.elapsed_seconds >= 0,
            `${unit.target}: elapsed_seconds는 0 이상의 유한한 수치여야 합니다.`);
      }
      if (unit.verdicts !== undefined) {
        requireValue(object(unit.verdicts), `${unit.target}: 종합 판정 형식을 확인하세요.`);
        for (const [key, verdict] of Object.entries(unit.verdicts))
          requireValue(Object.hasOwn(groups, key) && verdicts.includes(verdict),
            `${unit.target}: 기능·운영·연동 판정은 통과·실패·미판정·비적용 중 하나입니다.`);
      }
      requireValue(Array.isArray(unit.metrics), `${unit.target}: metrics 목록이 필요합니다.`);
      const metricNames = new Set();
      for (const metric of unit.metrics) {
        const definition = EvaluationCatalog[unit.kind].metrics.find((item) => item.name === metric?.name);
        requireValue(object(metric) && definition, `${unit.target}: 평가 문서에 없는 지표 ${metric?.name || "(이름 없음)"}`);
        const prefix = `${unit.target} · ${metric.name}`;
        requireValue(!metricNames.has(metric.name), `${prefix}: 지표가 중복되었습니다.`);
        metricNames.add(metric.name);
        if (metric.verdict !== undefined)
          requireValue(verdicts.includes(metric.verdict), `${prefix}: 판정 값을 확인하세요.`);
        if (metric.required !== undefined)
          requireValue(typeof metric.required === "boolean", `${prefix}: required는 true 또는 false여야 합니다.`);
        for (const key of ["unjudged", "not_applicable", "not_executed"])
          if (present(metric[key])) requireValue(count(metric[key]), `${prefix}: ${key}는 0 이상의 정수여야 합니다.`);
        if (definition.kind === "ratio") {
          const hasCounts = present(metric.numerator) || present(metric.denominator);
          requireValue(!hasCounts || (count(metric.numerator) && count(metric.denominator) &&
            metric.numerator <= metric.denominator), `${prefix}: 분자·분모는 0 이상의 정수이며 분자가 분모보다 클 수 없습니다.`);
          requireValue(metric.verdict !== "통과" || (hasCounts && metric.denominator > 0),
            `${prefix}: 측정값이 없거나 분모가 0이면 통과로 기록할 수 없습니다.`);
        } else {
          requireValue(metric.measurements === undefined || Array.isArray(metric.measurements),
            `${prefix}: measurements 목록을 확인하세요.`);
          for (const measurement of metric.measurements || [])
            requireValue(object(measurement) && string(measurement.label) && string(measurement.unit) &&
              (!present(measurement.value) || (typeof measurement.value === "number" &&
                Number.isFinite(measurement.value) && measurement.value >= 0)),
            `${prefix}: 측정 항목에는 이름·단위·0 이상의 수치가 필요합니다.`);
          requireValue(metric.verdict !== "통과" || metric.measurements?.some((item) => present(item.value)),
            `${prefix}: 측정값 없이 통과로 기록할 수 없습니다.`);
        }
      }
      requireValue(unit.checks === undefined || Array.isArray(unit.checks), `${unit.target}: checks 목록을 확인하세요.`);
      for (const check of unit.checks || []) {
        requireValue(object(check) && string(check.case_id) && string(check.check_id) &&
          string(check.target) && typeof check.executed === "boolean" && verdicts.includes(check.verdict),
        `${unit.target}: 사례·검사 ID, 판정 대상, 실행 여부와 판정이 필요합니다.`);
        requireValue(check.executed || !["통과", "실패"].includes(check.verdict),
          `${unit.target} · ${check.check_id}: 미실행 검사를 통과·실패로 기록할 수 없습니다.`);
        if (check.run_id !== undefined)
          requireValue((unit.run_ids || value.run_ids).includes(check.run_id),
            `${unit.target}: 검사 실행 ID가 해당 단위 run_ids에 없습니다.`);
        if (check.execution_id !== undefined)
          requireValue(string(check.execution_id) && executionIds.has(check.execution_id),
            `${unit.target} · ${check.check_id}: execution_id가 해당 단위 executions에 없습니다.`);
        if (check.metrics !== undefined)
          requireValue(Array.isArray(check.metrics) && new Set(check.metrics).size === check.metrics.length &&
            check.metrics.every((name) => EvaluationCatalog[unit.kind].metrics.some((metric) => metric.name === name)),
            `${unit.target} · ${check.check_id}: metrics에는 해당 평가 단위의 지표명을 중복 없이 기록하세요.`);
      }
    }
    return value;
  }

  function matches(evaluation, runId) {
    return !!runId && evaluation.run_ids.includes(runId);
  }

  // 집계값은 쪼개거나 재계산하지 않는다. 실행별 원본 단위만 현재 실행에 연결한다.
  function scopeUnits(evaluation, report) {
    const execution = report?.state?.execution;
    const runId = execution?.run_id;
    const event = execution?.event || evaluation.event;
    const result = { units: [], excluded: [], warnings: [] };
    for (const unit of evaluation.units) {
      const runIds = unit.run_ids || evaluation.run_ids;
      let reason;
      if (runId && !runIds.includes(runId)) reason = "run-mismatch";
      else if (runId && runIds.length !== 1) reason = "mixed-runs";
      else if (execution?.event && evaluation.event && execution.event !== evaluation.event) reason = "event-mismatch";
      else if ((event === "user_request" && unit.kind === "report") ||
        (event === "analysis_pipeline" && (unit.kind === "user-request" ||
          (unit.kind === "nodes" && targetId(unit) === "N01")))) reason = "event-not-applicable";
      else if (unit.kind === "nodes" && !targets.nodes.includes(targetId(unit))) reason = "target-unidentified";
      if (reason) {
        result.excluded.push({ unit, reason });
        continue;
      }
      result.units.push(unit);
      if (unit.kind === "tools" && !targets.tools.includes(targetId(unit)))
        result.warnings.push({ unit, reason: "target-unidentified" });
    }
    return result;
  }

  function visibleUnits(evaluation, report) {
    return scopeUnits(evaluation, report).units;
  }

  function metricRows(unit) {
    return EvaluationCatalog[unit.kind].metrics.filter((definition) =>
      !definition.target_ids || definition.target_ids.includes(targetId(unit))).map((definition) => ({
      definition,
      result: unit.metrics.find((metric) => metric.name === definition.name),
    })).filter(({ result }) => result?.verdict !== "비적용");
  }

  function casesForMetric(unit, metricName) {
    return (unit.checks || []).filter((check) => check.metrics?.includes(metricName));
  }

  // 검사 항목 수와 실제 호출 횟수는 다르다. 명시된 실행 기록만 집계한다.
  function executionSummary(units) {
    const recorded = units.every((unit) => Array.isArray(unit.executions));
    return {
      recorded,
      targetCount: new Set(units.map((unit) => targetId(unit) || unit.id)).size,
      executionCount: recorded ? new Set(units.flatMap((unit) => unit.executions.map((execution) => execution.id))).size : null,
    };
  }

  function ratio(metric) {
    if (!metric || !present(metric.numerator) || !present(metric.denominator)) return null;
    if (metric.denominator === 0) return null;
    return metric.numerator / metric.denominator * 100;
  }

  return { verdicts, groups, normalize, matches, targetId, scopeUnits, visibleUnits, metricRows, casesForMetric, executionSummary, ratio };
})();

if (typeof module !== "undefined") module.exports = globalThis.ReportEvaluation;
