"use strict";
const copyFiles = files => structuredClone(files);
const assessmentFiles = (score, path = "assessment") => [{path: `${path}.json`, text: JSON.stringify(score)}];
function qualityScore(execution) {
  const source = structuredClone(execution), first = source.runs[0], prepared = source.criteria.cases.find(item => item.id === first.case_id);
  const role = prepared.unit === "workflow" ? "report_description" : prepared.target;
  const detail = {id: "final-content", verdict: "실패", executed: true, reason: "반환된 설명의 근거가 부족함", evidence: ["output.content"]};
  const assessment = {id: "quality-assessment-1", node_id: "original-compose", call_id: "original-call", call_index: 3,
    run_id: first.run_id, case_id: first.case_id, repetition: first.repetition, node: "compose", role, occurrence: 1,
    counted: true, verdict: "실패", complete: true, reason: "작성 내용 검사", checks: [
      {check: "N04-O.1", axis: "output", method: "LLM", executed: true, verdict: "실패", reason: detail.reason,
        details: [detail], related_checks: [], calls: [{id: "original-call", name: "Composition", index: 3,
          details: [detail], judge: {executed: true, prompt: {messages: [{role: "user", content: "품질 평가 입력"}],
            criteria: [{id: "N04-O.1", text: "실제 작성 호출의 내용 검사"}]},
          raw_response: {content: "저장된 평가 원응답"}, response: {verdict: "실패"}, model_usage: null}}]}]};
  return {schema_version: "output-evaluation-v1", id: "quality-1", batch_id: source.batch_id, suite_id: source.suite_id,
    assessed_at: "2026-11-13T12:00:00+09:00", status: "completed", method: "all", judge_model: "test-judge",
    criteria: {cases: [prepared], plan: {case_ids: [prepared.id], repeat: first.repetition}, effective_cases: [prepared],
      documents: {}, checks: {}, selection: {}}, criteria_sha256: "quality-criteria", evidence_sha256: {},
    evaluator_sha256: {}, provenance: [], selection: {}, limitations: ["모의 품질 판정"], assessments: [assessment],
    runs: [{run_id: first.run_id, case_id: first.case_id, repetition: first.repetition, verdict: "실패", complete: true,
      reason: detail.reason, status: "returned", issues: [], connection_checks: [], excluded_calls: [],
      components: [{id: "response-1", role, kind: "response", paths: ["/state/response/content"],
        value: "실제로 반환한 설명", result_id: "result-1", link_status: "matched", issues: [],
        assessment_ids: [assessment.id], verdict: "실패", complete: true, reason: detail.reason}]}],
    summary: {verdict: "실패", complete: true, planned_runs: 1, evaluated_runs: 1, passed: 0, failed: 1,
      undetermined: 0, not_applicable: 0, numerator: 0, denominator: 1, rate: 0, checks: [
        {check: "N04-O.1", axis: "output", method: "LLM", passed: 0, failed: 1, undetermined: 0,
          not_applicable: 0, unexecuted: 0, numerator: 0, denominator: 1, rate: 0}]},
    judge_trace: {version: "local-execution-trace-v1", scope: "test", limitations: [], counts: {},
      coverage: Object.fromEntries(["model_attempts", "model_inputs", "http_requests", "http_responses", "sdk_responses", "model_errors", "unfinished_spans"].map(key => [key, 0])), spans: []}};
}
module.exports = {copyFiles, assessmentFiles, qualityScore};
