from copy import deepcopy


def report():
    prompt = {
        "messages": [
            {"role": "system", "content": "평가 기준"},
            {"role": "user", "content": "실행 당시 입력과 원본 출력"},
        ],
        "criteria": [
            {"path": "docs/check.json", "text": "기준 원문", "sha256": "source-hash"}
        ],
        "payload": {"value": 1},
    }
    check = {
        "check": "N04-B.1",
        "verdict": "실패",
        "reason": "새 주장",
        "calls": [
            {
                "id": "same-call-id",
                "name": "ReportText",
                "index": 1,
                "row_id": "N04-B.1/report-insight",
                "details": [{"value": "그대로"}],
                "judge": {
                    "prompt": prompt,
                    "response": {"details": [{"verdict": "실패"}]},
                    "raw_response": {"content": "평가 모델 응답"},
                    "model_usage": {"input_tokens": 25},
                },
            }
        ],
    }
    return {
        "schema_version": "node-evaluation-v1",
        "id": "score-1",
        "batch_id": "batch",
        "suite_id": "suite",
        "assessed_at": "2026-11-13T10:00:00+09:00",
        "method": "all",
        "judge_model": "judge-model",
        "status": "cancelled",
        "criteria": {"documents": {"check": {"text": "기준 원문"}}},
        "criteria_sha256": "original-digest",
        "evidence_sha256": {"batch.json": "original"},
        "nodes": [{"node": "compose", "functional": {"rate": 0}}],
        "runs": [
            {
                "case_id": "case-a",
                "repetition": 3,
                "run_id": None,
                "unmatched_checks": ["N04-B.1"],
                "complete": False,
            }
        ],
        "assessments": [
            {
                "case_id": "case-a",
                "repetition": rep,
                "run_id": f"run-{rep}",
                "node_id": f"node-{rep}",
                "node": "compose",
                "role": "report_insight",
                "occurrence": 1,
                "checks": [deepcopy(check), deepcopy(check)],
            }
            for rep in (1, 2)
        ],
        "judge_trace": {"spans": [{"input": {"messages": ["원본 추적"]}}]},
    }
