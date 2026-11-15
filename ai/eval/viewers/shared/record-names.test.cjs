"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const names = require("./record-names.js");

test("saved names retain execution and regrading numbers even when records are opened separately", () => {
  const record = {report: {id: "통합평가_2026-11-12_실행104_채점12", batch_id: "통합평가_2026-11-12_실행104"}};
  const batch = {report: null, assessments: [record]};
  assert.equal(names.batchName(batch), "통합평가 · 2026-11-12 실행104");
  assert.equal(names.assessmentName(record, batch), "통합평가 · 2026-11-12 실행104 · 채점12");
  assert.equal(names.assessmentFilename(record, batch), "통합평가_2026-11-12_실행104_채점12.json");
  assert.equal(names.legacy(record), false);
});

test("quality records coexist with unread legacy metadata without fabricating IDs or changing records", () => {
  const quality = {path: "quality/manifest.json", report: {id: "quality", schema_version: "output-evaluation-v1", assessed_at: "2026-11-13T01:00:00Z"}};
  const unread = {path: "legacy.json", report: {}, lazy: true};
  const batch = {report: {id: "실행평가_2026-11-13_실행01"}, assessments: [quality, unread]};
  const original = structuredClone(batch);
  assert.match(names.assessmentName(quality, batch), /실행평가.*채점/);
  assert.notEqual(names.assessmentFilename(quality, batch), names.assessmentFilename(unread, batch));
  assert.deepEqual(batch, original);
});

test("Korean date and time are independent of the browser timezone and cross midnight correctly", () => {
  assert.equal(names.dateTime("2026-11-12T08:59:01.322553+00:00"), "2026년 11월 12일 17:59:01 (한국시간)");
  assert.equal(names.dateTime("2026-11-12T15:00:00Z"), "2026년 11월 13일 00:00:00 (한국시간)");
  assert.equal(names.dateTime(null), "미기록");
  assert.equal(names.dateTime("invalid"), "시각 확인 불가");
});

test("legacy display names use chronological records without modifying source evidence or colliding with saved numbers", () => {
  const early = {report: {id: "old-first", assessed_at: "2026-11-13T01:00:00Z"}};
  const late = {report: {id: "old-second", assessed_at: "2026-11-13T02:00:00Z"}};
  const saved = {report: {id: "노드평가_2026-11-13_실행01_채점01", assessed_at: "2026-11-13T03:00:00Z"}};
  const batch = {report: {id: "old-batch", started_at: "2026-11-12T23:00:00Z", runs: [{unit: "node"}]}, assessments: [late, saved, early]};
  const other = {report: {id: "노드평가_2026-11-13_실행01", runs: []}};
  const original = structuredClone([batch, other]);
  assert.equal(names.batchName(batch, [batch, other]), "노드평가 · 2026-11-13 실행02");
  assert.equal(names.assessmentName(early, batch, [batch, other]), "노드평가 · 2026-11-13 실행02 · 채점02");
  assert.equal(names.assessmentName(late, batch, [other, batch]), "노드평가 · 2026-11-13 실행02 · 채점03");
  assert.deepEqual([batch, other], original);
});

test("detached legacy assessments do not substitute their grading date for an unknown execution date", () => {
  const record = {report: {id: "old-score", batch_id: "old-batch", schema_version: "node-evaluation-v1", assessed_at: "2026-11-13T01:00:00Z"}};
  const batch = {report: null, assessments: [record]};
  assert.equal(names.assessmentName(record, batch), "노드평가 · 실행일 미기록 실행01 · 채점01");
  assert.equal(names.assessmentFilename(record, batch), "노드평가_실행일미기록_실행01_채점01.json");
});

test("batch choices distinguish equal names from separate output folders", () => {
  const left = {path: "process/도구평가_2026-11-12_실행01/batch.json", report: {id: "도구평가_2026-11-12_실행01", suite_id: "자료 가공"}};
  const right = {path: "query/도구평가_2026-11-12_실행01/batch.json", report: {id: left.report.id, suite_id: "자료 조회"}};
  assert.equal(names.batchLabel(left, [left, right]), "도구평가 · 2026-11-12 실행01 · 자료 가공");
  assert.equal(names.batchLabel(right, [left, right]), "도구평가 · 2026-11-12 실행01 · 자료 조회");
  right.report.suite_id = left.report.suite_id;
  assert.equal(names.batchLabel(left, [left, right]), "도구평가 · 2026-11-12 실행01 · 자료 가공 · process");
  assert.equal(names.batchLabel(right, [left, right]), "도구평가 · 2026-11-12 실행01 · 자료 가공 · query");
});
