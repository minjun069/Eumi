/* Read selected saved files only. Never grade or assemble the complete result tree. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.EvaluationLazy = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const nonempty = value => typeof value === "string" && value.length > 0;
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const clone = value => JSON.parse(JSON.stringify(value));
  const dirname = path => path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  const versions = new Set(["node-evaluation-v1", "tool-evaluation-v1", "execution-evaluation-v1", "output-evaluation-v1"]);

  class ReadError extends Error {
    constructor(code, path, message, status) {
      super(message); this.name = "ReadError"; this.code = code; this.path = path;
      if (status !== undefined) this.status = status;
    }
  }
  function requireValue(condition, path, message, code = "invalid") {
    if (!condition) throw new ReadError(code, path, message);
  }
  function relative(path) {
    requireValue(nonempty(path) && !/[\\:\u0000-\u001f\u007f]/.test(path) &&
      path.split("/").every(part => part && part !== "." && part !== ".."),
    typeof path === "string" ? path : "", "안전한 상대 파일 경로가 필요합니다.", "unsafe-path");
    return path;
  }
  const join = (directory, path) => directory ? `${relative(directory)}/${relative(path)}` : relative(path);
  function aborted(signal) {
    if (signal?.aborted) {
      const error = new Error("선택이 바뀌어 파일 읽기를 취소했습니다.");
      error.name = "AbortError"; throw error;
    }
  }
  function assessmentIndex(ref, batch) {
    relative(ref.path);
    const report = Object.fromEntries(["id", "batch_id", "suite_id", "status", "method", "judge_model", "assessed_at"]
      .filter(key => own(ref, key)).map(key => [key, ref[key]]));
    if (ref.report_schema_version) report.schema_version = ref.report_schema_version;
    if (batch?.id && !report.batch_id) report.batch_id = batch.id;
    if (batch?.suite_id && !report.suite_id) report.suite_id = batch.suite_id;
    const expected = {...ref};
    for (const key of ["batch_id", "suite_id"]) if (own(report, key)) expected[key] = report[key];
    return {path: ref.path, report, ref: clone(expected), lazy: true, partial: true};
  }
  function batchIndex(entry) {
    relative(entry.path);
    const report = Object.fromEntries(["id", "suite_id", "status", "started_at", "ended_at", "planned_runs"]
      .filter(key => own(entry, key)).map(key => [key, entry[key]]));
    return {key: entry.path, path: entry.path, source: "batch", report, suite: null, runs: [],
      assessments: (entry.assessments || []).map(ref => assessmentIndex(ref, report)),
      issues: [], lazy: true, entry: clone(entry)};
  }
  function runIndex(batch, entry) {
    const path = join(dirname(batch.path), entry.path);
    return {key: path, path, entry: clone(entry), report: null, case: null, caseSource: null,
      manifest: null, trace: null, journal: [], issues: [], lazy: true,
      availability: {report: "unloaded", case: "unloaded", manifest: "unloaded", journal: "unloaded"}};
  }

  function create(options = {}) {
    const fetcher = options.fetch || globalThis.fetch?.bind(globalThis);
    const base = new URL(options.baseURL || "../../../", globalThis.location?.href || "http://localhost/");
    requireValue(["http:", "https:"].includes(base.protocol), "", "자동 조회는 로컬 HTTP 서버에서 사용할 수 있습니다.", "unsupported-protocol");
    requireValue(typeof fetcher === "function", "", "파일 요청 기능이 없습니다.", "network");
    if (!base.pathname.endsWith("/")) base.pathname += "/";
    base.search = ""; base.hash = "";
    const maxBytes = options.maxBytes ?? 16 * 1024 * 1024;
    const maxEntries = options.maxEntries ?? 24;
    const maxFileBytes = options.maxFileBytes ?? 64 * 1024 * 1024;
    requireValue([maxBytes, maxEntries, maxFileBytes].every(integer) && maxFileBytes > 0, "", "파일·캐시 한도는 유효한 정수여야 합니다.");
    const crypto = options.crypto || globalThis.crypto;
    const cache = new Map(), scopes = new Map(), pending = new Map();
    let cacheBytes = 0;
    function url(path) {
      // Encode each literal filename once; percent-escaped stored IDs are filenames,
      // not URL escapes. This also prevents encoded traversal and query injection.
      const result = new URL(relative(path).split("/").map(encodeURIComponent).join("/"), base);
      requireValue(result.origin === base.origin && result.pathname.startsWith(base.pathname), path, "결과 폴더 밖의 주소는 읽지 않습니다.", "unsafe-path");
      return result.href;
    }
    function remember(key, value, size, digest) {
      if (cache.has(key)) { cacheBytes -= cache.get(key).size; cache.delete(key); }
      if (!maxEntries || size > maxBytes) return;
      while (cache.size >= maxEntries || cacheBytes + size > maxBytes) {
        const first = cache.keys().next().value;
        cacheBytes -= cache.get(first).size; cache.delete(first);
      }
      cache.set(key, {value, size, digest}); cacheBytes += size;
    }
    function begin(scope = "selection") {
      scopes.get(scope)?.abort();
      const controller = new AbortController(); scopes.set(scope, controller);
      return {signal: controller.signal, current: () => scopes.get(scope) === controller && !controller.signal.aborted,
        cancel: () => controller.abort()};
    }
    async function readText(response, path, signal) {
      const tooLarge = () => new ReadError("too-large", path, "파일이 화면 읽기 한도를 초과했습니다. 원본 파일 링크로 내려받으세요.");
      const declared = Number(response.headers?.get?.("content-length"));
      if (Number.isFinite(declared) && declared > maxFileBytes) {
        await response.body?.cancel?.(); throw tooLarge();
      }
      if (!response.body?.getReader) {
        const text = await response.text(); aborted(signal);
        const size = new TextEncoder().encode(text).byteLength;
        if (size > maxFileBytes) throw tooLarge();
        return {text, size};
      }
      const reader = response.body.getReader(), decoder = new TextDecoder("utf-8", {fatal: true, ignoreBOM: true});
      const chunks = []; let size = 0;
      try {
        while (true) {
          const result = await reader.read(); aborted(signal);
          if (result.done) break;
          size += result.value.byteLength;
          if (size > maxFileBytes) throw tooLarge();
          chunks.push(decoder.decode(result.value, {stream: true}));
        }
        chunks.push(decoder.decode());
        return {text: chunks.join(""), size};
      } catch (error) {
        await reader.cancel().catch(() => {});
        if (error.name === "AbortError" || error instanceof ReadError) throw error;
        if (error instanceof TypeError && /encoded|encoding|decode/i.test(error.message))
          throw new ReadError("parse", path, "UTF-8 파일 내용을 읽을 수 없습니다.");
        throw error;
      } finally { reader.releaseLock(); }
    }
    async function digest(text, path) {
      requireValue(crypto?.subtle?.digest, path, "파일 무결성 확인 기능을 사용할 수 없습니다.", "integrity-unavailable");
      return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))))
        .map(value => value.toString(16).padStart(2, "0")).join("");
    }
    async function read(path, opts = {}) {
      if (!options.deduplicate) return readFile(path, opts);
      const key = JSON.stringify([path, Boolean(opts.text), Boolean(opts.stored), Boolean(opts.reload), opts.sha256 || null, opts.omit || null, opts.pick || null]);
      const existing = pending.get(key);
      if (existing && existing.signal === opts.signal) return clone(await existing.promise);
      const item = {signal: opts.signal, promise: readFile(path, opts)};
      pending.set(key, item);
      try { return await item.promise; }
      finally { if (pending.get(key) === item) pending.delete(key); }
    }
    async function readFile(path, opts = {}) {
      relative(path); aborted(opts.signal);
      const key = `${opts.text ? "text" : "json"}:${path}`, cached = cache.get(key);
      if (!opts.reload && cached && (!opts.sha256 || cached.digest === opts.sha256.toLowerCase())) {
        cache.delete(key); cache.set(key, cached);
        return clone(cached.value);
      }
      let response, content;
      try {
        response = await fetcher(url(path), {signal: opts.signal, cache: "no-store", redirect: "error"});
        aborted(opts.signal);
        if (response.status === 404) throw new ReadError("not-found", path, "파일이 없습니다. 저장 중이거나 원본이 누락됐을 수 있습니다.", 404);
        if (!response.ok) throw new ReadError("http", path, `파일 서버가 HTTP ${response.status}를 반환했습니다.`, response.status);
        requireValue(!response.redirected, path, "다른 주소로 이동하는 파일은 읽지 않습니다.", "unsafe-path");
        content = await readText(response, path, opts.signal); aborted(opts.signal);
      } catch (error) {
        aborted(opts.signal);
        if (error.name === "AbortError" || error instanceof ReadError) throw error;
        throw new ReadError("network", path, "파일 서버 연결 또는 응답 읽기에 실패했습니다.");
      }
      const hash = opts.sha256 ? await digest(content.text, path) : null;
      aborted(opts.signal);
      if (opts.sha256) requireValue(hash === opts.sha256.toLowerCase(), path, "저장된 해시와 파일 내용이 다릅니다.", "integrity");
      let value = content.text;
      if (!opts.text) {
        try { value = JSON.parse(content.text.replace(/^\uFEFF/, "")); }
        catch (_) { throw new ReadError("parse", path, "JSON 파일 형식이 올바르지 않습니다."); }
      }
      remember(key, value, content.size, hash); return clone(value);
    }
    async function catalog(path = "eval/outputs/evaluation-viewer/catalog.json", opts = {}) {
      const value = await read(path, {...opts, reload: true});
      requireValue(object(value) && value.version === "evaluation-viewer-local-v2" && Array.isArray(value.batches) && Array.isArray(value.files), path, "지원하는 자동 조회 목록 형식이 아닙니다.");
      const seen = new Set();
      for (const entry of value.batches) {
        requireValue(object(entry) && Array.isArray(entry.assessments), path, "묶음 목록 형식이 올바르지 않습니다.");
        relative(entry.path); requireValue(!seen.has(entry.path), entry.path, "묶음 경로가 중복됐습니다."); seen.add(entry.path);
        if (entry.suite_path !== null && entry.suite_path !== undefined) relative(entry.suite_path);
        for (const ref of entry.assessments) {
          requireValue(object(ref) && ref.format === "legacy", entry.path, "채점 목록 형식이 올바르지 않습니다.");
          relative(ref.path);
          requireValue(ref.path.startsWith(`${dirname(entry.path)}/assessments/`), ref.path, "채점 경로가 해당 묶음에 속하지 않습니다.", "unsafe-path");
          if (own(entry, "id") && own(ref, "batch_id")) requireValue(entry.id === ref.batch_id, ref.path, "묶음과 채점 목록의 식별 정보가 다릅니다.", "identity");
        }
      }
      for (const file of value.files) {
        requireValue(object(file), path, "파일 목록에 객체가 필요합니다.");
        relative(file.path); requireValue(integer(file.size_bytes), path, "파일 크기 기록이 올바르지 않습니다.");
      }
      if (value.scenario_index) relative(value.scenario_index);
      return value;
    }
    async function batch(entry, opts = {}) {
      entry = entry.entry || entry;
      const value = await read(entry.path, {...opts, reload: true});
      requireValue(object(value) && value.schema_version === "evaluation-batch-v1" && nonempty(value.id) && nonempty(value.suite_id) && Array.isArray(value.runs), entry.path, "실행 묶음 형식이 올바르지 않습니다.");
      for (const key of ["id", "suite_id"]) if (own(entry, key)) requireValue(value[key] === entry[key], entry.path, "목록과 실행 묶음의 식별 정보가 다릅니다.", "identity");
      const result = batchIndex(entry); result.report = value; result.lazy = false;
      const ids = new Set(), repetitions = new Set();
      for (const run of value.runs) {
        requireValue(object(run), entry.path, "등록된 실행에 객체가 필요합니다.");
        const repetition = JSON.stringify([run.case_id, run.repetition]);
        requireValue(object(run) && nonempty(run.run_id) && nonempty(run.case_id) && integer(run.repetition) && run.repetition > 0 &&
          relative(run.path) === `runs/${run.run_id}/report.json`, entry.path, "등록된 실행의 식별자·반복·경로가 올바르지 않습니다.");
        requireValue(!ids.has(run.run_id) && !repetitions.has(repetition), entry.path, "실행 ID 또는 사례·반복이 중복됐습니다.", "identity");
        ids.add(run.run_id); repetitions.add(repetition); result.runs.push(runIndex(result, run));
      }
      return result;
    }
    async function assessment(ref, opts = {}) {
      ref = ref.ref || ref;
      const report = await read(ref.path, opts);
      requireValue(object(report) && versions.has(report.schema_version), ref.path, "지원하는 채점 형식이 아닙니다.");
      for (const key of ["id", "batch_id", "suite_id"]) if (own(ref, key))
        requireValue(report[key] === ref[key], ref.path, "목록과 채점의 식별 정보가 다릅니다.", "identity");
      return {path: ref.path, ref, report, lazy: false, partial: false};
    }
    async function run(batchValue, selected, opts = {}) {
      const entry = selected.entry || selected;
      const known = batchValue.report.runs.find(item => item.run_id === entry.run_id);
      requireValue(known && ["case_id", "repetition", "unit", "target", "path"].every(key => known[key] === entry[key]), batchValue.path, "선택한 실행이 해당 묶음에 속하지 않습니다.", "identity");
      const result = runIndex(batchValue, known);
      const optional = async path => {
        try { return await read(path, opts); }
        catch (error) {
          if (error.code !== "not-found" || error.path !== path) throw error;
          result.issues.push({severity: "warning", code: error.code, path, message: error.message}); return null;
        }
      };
      const [report, caseValue] = await Promise.all([optional(result.path), optional(join(dirname(result.path), "case.json"))]);
      aborted(opts.signal);
      if (report !== null) requireValue(object(report) && report.schema_version === "evaluation-run-v1" && object(report.run) &&
        report.run.id === known.run_id && report.run.suite_id === batchValue.report.suite_id &&
        ["case_id", "repetition", "unit", "target"].every(key => report.run[key] === known[key]), result.path, "실행 결과의 묶음·사례·반복 연결이 다릅니다.", "identity");
      if (caseValue !== null) {
        requireValue(object(caseValue) && caseValue.id === known.case_id && ["unit", "target"].every(key => caseValue[key] === known[key]), result.path, "사례 자료와 선택한 실행의 대상이 다릅니다.", "identity");
        if (report !== null) {
          const role = caseValue.unit === "agent" ? caseValue.target : (caseValue.role ?? null);
          requireValue(report.run.role === role && report.run.dependencies === (caseValue.dependencies || "real"), result.path, "사례 자료의 역할·하위 호출 방식이 실행 결과와 다릅니다.", "identity");
        }
      }
      result.report = report; result.case = caseValue;
      result.caseSource = caseValue ? "case" : null;
      result.availability.report = report === null ? "missing" : "loaded";
      result.availability.case = caseValue === null ? "missing" : "loaded";
      result.lazy = false; return result;
    }
    function clear() { cache.clear(); cacheBytes = 0; }
    function dispose() { for (const controller of scopes.values()) controller.abort(); scopes.clear(); clear(); }
    return Object.freeze({catalog, batch, assessment, run, begin, url,
      raw: async (path, opts = {}) => ({path, text: await read(path, {...opts, text: true})}),
      clear, dispose, cacheInfo: () => ({entries: cache.size, bytes: cacheBytes, maxEntries, maxBytes})});
  }
  return Object.freeze({create, batchIndex, assessmentIndex, relative, ReadError});
});
