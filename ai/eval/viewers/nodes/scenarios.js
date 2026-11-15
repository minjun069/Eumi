(function (root) {
  "use strict";
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const text = value => typeof value === "string" && value.length > 0;
  const nodes = new Set(["interpret", "decide", "act", "compose", "ask"]);
  const roles = new Set(["request", "interpretation", "visualization", "report_selection", "report_description", "report_insight"]);
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  function relativePath(value) {
    check(text(value) && !value.includes("\\") && !value.includes(":") &&
      value.split("/").every(part => part && part !== "." && part !== ".."), "안전한 상대 경로가 필요합니다.");
    return value;
  }
  const sibling = (path, reference) => {
    relativePath(reference);
    const slash = path.lastIndexOf("/");
    return slash < 0 ? reference : `${path.slice(0, slash)}/${reference}`;
  };
  const usageKey = usage => JSON.stringify([usage.scenario_id, usage.step_id]);

  function validateIndex(index) {
    check(object(index) && index.schema_version === "node-scenarios-v4", "지원하는 노드 시나리오 색인이 아닙니다.");
    check(Array.isArray(index.scenarios) && object(index.case_index), "시나리오 목록과 사례 색인이 필요합니다.");
    const ids = new Set(), paths = new Set();
    for (const item of index.scenarios) {
      check(object(item) && text(item.id) && text(item.title), "시나리오 식별자와 제목이 필요합니다.");
      relativePath(item.file);
      check(!ids.has(item.id) && !paths.has(item.file), "시나리오 식별자 또는 파일 참조가 중복됩니다.");
      ids.add(item.id); paths.add(item.file);
    }
    for (const [caseId, entry] of Object.entries(index.case_index)) {
      check(text(caseId) && object(entry) && nodes.has(entry.node) && roles.has(entry.role) && Array.isArray(entry.usages), "사례의 노드·역할·사용 위치가 올바르지 않습니다.");
      const usages = new Set();
      for (const usage of entry.usages) {
        check(object(usage) && ids.has(usage.scenario_id) && text(usage.step_id), "사례가 색인에 없는 시나리오 또는 단계 위치를 참조합니다.");
        const key = usageKey(usage);
        check(!usages.has(key), "동일 사례의 시나리오 사용 위치가 중복됩니다.");
        usages.add(key);
      }
    }
  }

  function validateScenario(record, reference, index) {
    check(object(record) && record.id === reference.id && record.title === reference.title, "시나리오 원문과 색인의 식별자 또는 제목이 다릅니다.");
    check(Array.isArray(record.steps) && record.steps.length > 0, "시나리오의 순서 있는 노드 목록이 필요합니다.");
    const steps = new Map();
    for (const step of record.steps) {
      check(object(step) && text(step.step_id) && text(step.case_id) && nodes.has(step.node) && roles.has(step.role) && text(step.frame), "시나리오 노드의 식별자·사례·역할·실행 위치가 올바르지 않습니다.");
      check(!steps.has(step.step_id), "시나리오의 단계 식별자가 중복됩니다.");
      const boundary = step.boundary_before;
      check(object(boundary) && ["entry", "next", "call", "return"].includes(boundary.kind), "시나리오의 노드 연결 종류가 올바르지 않습니다.");
      check(boundary.kind === "entry" ? boundary.from_step === null && steps.size === 0 : text(boundary.from_step) && steps.has(boundary.from_step), "시나리오의 노드 연결이 앞 단계와 맞지 않습니다.");
      const entry = index.case_index[step.case_id];
      check(object(entry) && entry.node === step.node && entry.role === step.role && entry.usages.some(usage => usage.scenario_id === record.id && usage.step_id === step.step_id), "시나리오 노드와 사례 색인의 노드·역할·사용 위치가 다릅니다.");
      steps.set(step.step_id, step);
    }
    for (const [caseId, entry] of Object.entries(index.case_index)) {
      for (const usage of entry.usages.filter(item => item.scenario_id === record.id)) {
        check(steps.get(usage.step_id)?.case_id === caseId, "사례 색인의 사용 위치가 실제 시나리오 노드를 가리키지 않습니다.");
      }
    }
  }

  /** Read original index/scenario JSON without creating evaluation or State fields. */
  function parseFiles(files) {
    const scenarios = [], issues = [], records = new Map(), documents = new Map();
    const issue = (code, path, message) => issues.push({severity: "error", code, path, message});
    if (!Array.isArray(files)) return {scenarios, issues: [{severity: "error", code: "invalid-files", path: "", message: "시나리오 파일 목록이 필요합니다."}]};
    for (const file of files) {
      let path;
      try { path = relativePath(file?.path); }
      catch (error) { issue("unsafe-scenario-path", typeof file?.path === "string" ? file.path : "", error.message); continue; }
      if (records.has(path)) records.set(path, null);
      else records.set(path, file);
    }
    function read(path) {
      if (documents.has(path)) return documents.get(path);
      check(records.has(path), "시나리오 색인이 참조하는 원본 파일이 없습니다.");
      const file = records.get(path);
      check(file !== null, "같은 경로의 파일이 중복되어 시나리오 원본을 선택할 수 없습니다.");
      check(typeof file.text === "string", "시나리오 파일의 텍스트가 필요합니다.");
      const value = JSON.parse(file.text.replace(/^\uFEFF/, ""));
      documents.set(path, value);
      return value;
    }
    for (const [indexPath, file] of records) {
      if (!/\.json$/i.test(indexPath)) continue;
      let index;
      try { index = read(indexPath); }
      catch (error) {
        if (/(?:^|\/)scenarios\.json$/i.test(indexPath)) issue("invalid-scenario-index", indexPath, error.message);
        continue;
      }
      if (!object(index) || index.schema_version !== "node-scenarios-v4") continue;
      try { validateIndex(index); }
      catch (error) { issue("invalid-scenario-index", indexPath, error.message); continue; }
      for (const reference of index.scenarios) {
        const path = sibling(indexPath, reference.file);
        try {
          const record = read(path);
          validateScenario(record, reference, index);
          scenarios.push({indexPath, path, index, record});
        } catch (error) { issue("invalid-scenario", path, error.message); }
      }
    }
    const sources = new Map();
    for (const item of scenarios) {
      for (const step of item.record.steps) {
        if (!sources.has(step.case_id)) sources.set(step.case_id, new Set());
        sources.get(step.case_id).add(item.indexPath);
      }
    }
    for (const [caseId, paths] of sources) {
      if (paths.size > 1) issue("ambiguous-scenario-case", [...paths].join(", "), `여러 시나리오 색인에 같은 사례(${caseId})가 있어 연결하지 않습니다.`);
    }
    return {scenarios, issues};
  }

  function forCase(catalog, caseId, node, role) {
    if (!catalog || !Array.isArray(catalog.scenarios) || !text(caseId) || !nodes.has(node) || !roles.has(role)) return [];
    const candidates = catalog.scenarios.filter(item => Object.hasOwn(item.index.case_index, caseId) &&
      item.index.case_index[caseId].usages.some(usage => usage.scenario_id === item.record.id));
    if (new Set(candidates.map(item => item.indexPath)).size > 1) return [];
    return candidates.filter(item => item.index.case_index[caseId].node === node && item.index.case_index[caseId].role === role).map(item => ({
      indexPath: item.indexPath, path: item.path, scenario: item.record, steps: item.record.steps,
      stepIds: item.record.steps.filter(step => step.case_id === caseId && step.node === node && step.role === role).map(step => step.step_id),
    })).filter(item => item.stepIds.length > 0);
  }

  const api = {parseFiles, forCase};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.NodeScenarios = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
