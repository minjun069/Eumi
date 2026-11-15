/* Load the selected execution batch completely; never grade or change saved results. */
(function (root, factory) {
  const api = factory(typeof module === "object" && module.exports ? require("./data.js") : root.ExecutionEvaluationData);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ExecutionAutomatic = api;
})(typeof globalThis === "object" ? globalThis : this, function (Data) {
  "use strict";
  const supported = schema => ["execution-evaluation-v1", "output-evaluation-v1"].includes(schema);
  const directory = path => path.replace(/[^/]+$/, "");
  function cancelled(signal) {
    if (signal?.aborted) { const error = new Error("평가 묶음 선택이 바뀌었습니다."); error.name = "AbortError"; throw error; }
  }
  async function load(client, entry, {files = [], signal, onProgress = () => {}} = {}) {
    const batch = await client.batch(entry, {signal});
    cancelled(signal);
    batch.readErrors = []; batch.rawFiles = new Map();
    batch.runs = batch.runs.filter(run => ["agent", "workflow"].includes(run.entry.unit));
    batch.assessments = batch.assessments.filter(record => record.ref.format === "legacy" || supported(record.report.schema_version));
    const knownFiles = new Set(files.map(file => file.path));
    function failed(error, path, owner = batch) {
      cancelled(signal);
      if (error.name === "AbortError") throw error;
      const issue = {severity: "error", code: error.code || "read-error", path: error.path || path, message: error.message};
      batch.readErrors.push(issue);
      (owner.issues ||= []).push(issue);
      return issue;
    }
    async function original(path, opts = {}) {
      const value = await client.raw(path, {...opts, signal});
      cancelled(signal);
      return value;
    }
    async function loadRun(run) {
      try { Object.assign(run, await client.run(batch, run, {signal, includeTrace: true})); }
      catch (error) { run.loadError = failed(error, run.path, run).message; }
      cancelled(signal);
      run.lazy = false;
      for (const issue of run.issues) if (!batch.readErrors.includes(issue)) batch.readErrors.push(issue);
      const folder = directory(run.path), manifestPath = folder + "manifest.json";
      if (knownFiles.has(manifestPath)) {
        try {
          const source = await original(manifestPath), value = JSON.parse(source.text);
          if (value.evaluation?.suite_id !== batch.report.suite_id) throw new Error("실행 조건과 입력 묶음 ID가 다릅니다.");
          run.manifest = value; run.availability.manifest = "loaded";
          batch.rawFiles.set(manifestPath, source);
        } catch (error) { failed(error, manifestPath, run); run.availability.manifest = "invalid"; }
      } else run.availability.manifest = "missing";
      const parts = files.map(file => file.path).filter(path => directory(path) === folder && /^trace\.jsonl$/.test(path.slice(folder.length)))
        .sort((a, b) => Number(b.endsWith("/trace.jsonl")) - Number(a.endsWith("/trace.jsonl")) || a.localeCompare(b));
      let read = 0;
      for (const path of parts) {
        try { batch.rawFiles.set(path, await original(path)); read++; }
        catch (error) { failed(error, path, run); }
      }
      // Keep the original full event records for display and download.
      run.availability.journal = !parts.length ? "missing" : read === parts.length ? "loaded" : "partial";
    }
    async function loadAssessment(record) {
      try {
        const loaded = await client.assessment(record.ref, {signal});
        cancelled(signal);
        if (!supported(loaded.report.schema_version)) { record.excluded = true; return; }
        Object.assign(record, loaded);
        const parsed = Data.parseFiles([{path: record.path, text: JSON.stringify(record.report)}]);
        const valid = parsed.batches.flatMap(item => item.assessments).find(item => item.path === record.path);
        if (!valid) throw new Error(parsed.issues.map(issue => issue.message).join(" · ") || "채점 형식이 올바르지 않습니다.");
        record.report = valid.report; record.partial = false;
      } catch (error) {
        record.loadError = failed(error, record.path, record).message;
        record.partial = true;
        if (!supported(record.report.schema_version)) record.excluded = true;
      } finally { record.lazy = false; }
    }
    const suitePath = entry.suite_path || directory(entry.path) + "suite.json";
    const tasks = [...batch.runs.map(run => () => loadRun(run)), ...batch.assessments.map(record => () => loadAssessment(record))];
    if (entry.suite_path || knownFiles.has(suitePath)) tasks.unshift(async () => {
      try {
        const source = await original(suitePath), suite = JSON.parse(source.text);
        if (suite.id !== batch.report.suite_id || !Array.isArray(suite.cases)) throw new Error("입력 묶음의 식별 정보·사례 목록이 다릅니다.");
        batch.suite = suite;
      } catch (error) { failed(error, suitePath); }
    });
    let next = 0, completed = 0;
    onProgress({completed, total: tasks.length});
    // Two top-level jobs bound large legacy report/trace reads; a run reads case+report together.
    await Promise.all(Array.from({length: Math.min(2, tasks.length)}, async () => {
      while (next < tasks.length) {
        cancelled(signal);
        await tasks[next++]();
        cancelled(signal);
        onProgress({completed: ++completed, total: tasks.length});
      }
    }));
    cancelled(signal);
    batch.assessments = batch.assessments.filter(record => !record.excluded);
    batch.assessments.sort((a, b) => (Date.parse(b.report.assessed_at) || 0) - (Date.parse(a.report.assessed_at) || 0));
    return batch;
  }
  return Object.freeze({load});
});
