/* Shared presentation of evaluation records. Never modifies loaded evidence. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.EvaluationNames = api;
})(globalThis, function () {
  "use strict";
  const batchPattern = /^(도구평가|노드평가|실행평가|통합평가)_(\d{4}-\d{2}-\d{2})_실행(\d+)$/;
  const assessmentPattern = /^(도구평가|노드평가|실행평가|통합평가)_(\d{4}-\d{2}-\d{2})_실행(\d+)_채점(\d+)$/;
  const schemaKinds = {"tool-evaluation-v1": "도구평가", "node-evaluation-v1": "노드평가", "execution-evaluation-v1": "실행평가", "output-evaluation-v1": "출력품질평가"};
  const unitKinds = {tool: "도구평가", node: "노드평가", selection: "노드평가", agent: "실행평가", workflow: "실행평가"};
  const formatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
  const sequence = value => String(value).padStart(2, "0");
  function dateParts(value) {
    if (!value || !Number.isFinite(Date.parse(value))) return null;
    return Object.fromEntries(formatter.formatToParts(new Date(value)).map(part => [part.type, part.value]));
  }
  function dateTime(value) {
    if (value == null || value === "") return "미기록";
    const p = dateParts(value);
    return p ? `${p.year}년 ${p.month}월 ${p.day}일 ${p.hour}:${p.minute}:${p.second} (한국시간)` : "시각 확인 불가";
  }
  function batchId(batch) { return batch?.report?.id || batch?.assessments?.[0]?.report.batch_id; }
  function batchKind(batch) {
    const parsed = batchPattern.exec(batchId(batch));
    if (parsed) return parsed[1];
    const entries = batch?.report?.runs || batch?.suite?.cases || batch?.runs?.map(run => run.report?.run || run.entry || run.case) || [];
    const kinds = new Set(entries.map(entry => unitKinds[entry?.unit]).filter(Boolean));
    if (!kinds.size) for (const record of batch?.assessments || []) kinds.add(schemaKinds[record.report.schema_version]);
    return kinds.size === 1 ? [...kinds][0] : "통합평가";
  }
  function batchDate(batch) {
    const parsed = batchPattern.exec(batchId(batch));
    if (parsed) return parsed[2];
    const p = dateParts(batch?.report?.started_at);
    return p ? `${p.year}-${p.month}-${p.day}` : "실행일미기록";
  }
  function batchToken(batch, batches = []) {
    const id = batchId(batch);
    if (batchPattern.test(id)) return id;
    const kind = batchKind(batch), date = batchDate(batch);
    const peers = [...new Set([...batches, batch])].filter(item => batchKind(item) === kind && batchDate(item) === date);
    const reserved = new Set(peers.map(item => batchPattern.exec(batchId(item))).filter(Boolean).map(match => Number(match[3])));
    const legacy = peers.filter(item => !batchPattern.test(batchId(item))).sort((a, b) =>
      (Date.parse(a?.report?.started_at) || 0) - (Date.parse(b?.report?.started_at) || 0) || String(batchId(a) || a?.key).localeCompare(String(batchId(b) || b?.key)));
    let number = 0;
    for (const item of legacy) {
      do { number++; } while (reserved.has(number));
      if (item === batch) break;
    }
    return `${kind}_${date}_실행${sequence(number)}`;
  }
  function assessmentToken(record, batch, batches = []) {
    if (assessmentPattern.test(record.report.id)) return record.report.id;
    const records = [...new Set([...(batch?.assessments || []), record])];
    const reserved = new Set(records.map(item => assessmentPattern.exec(item.report.id)).filter(Boolean).map(match => Number(match[4])));
    const legacy = records.filter(item => !assessmentPattern.test(item.report.id)).sort((a, b) =>
      (Date.parse(a.report.assessed_at) || 0) - (Date.parse(b.report.assessed_at) || 0) || String(a.report.id || a.path).localeCompare(String(b.report.id || b.path)));
    let number = 0;
    for (const item of legacy) {
      do { number++; } while (reserved.has(number));
      if (item === record) break;
    }
    return `${batchToken(batch, batches)}_채점${sequence(number)}`;
  }
  function display(token) { return token.replace("_", " · ").replace("_실행", " 실행").replace("_채점", " · 채점").replace("실행일미기록", "실행일 미기록"); }
  function batchLabel(batch, batches = []) {
    const token = batchToken(batch, batches), label = display(token);
    const peers = batches.filter(item => batchToken(item, batches) === token);
    if (peers.length < 2) return label;
    const suite = item => item.report?.suite_id || item.assessments?.[0]?.report.suite_id || item.runs?.[0]?.report?.run.suite_id || "개별 파일";
    const detail = suite(batch);
    if (peers.filter(item => suite(item) === detail).length === 1) return `${label} · ${detail}`;
    const location = String(batch.path).replaceAll("\\", "/").split("/").slice(0, -2).join("/") || "현재 폴더";
    return `${label} · ${detail} · ${location}`;
  }
  return Object.freeze({
    dateTime,
    batchLabel,
    batchName: (batch, batches) => display(batchToken(batch, batches)),
    assessmentName: (record, batch, batches) => display(assessmentToken(record, batch, batches)),
    assessmentFilename: (record, batch, batches) => `${assessmentToken(record, batch, batches)}.json`,
    legacy: record => !assessmentPattern.test(record.report.id),
  });
});
