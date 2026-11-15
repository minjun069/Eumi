"""실행 결과와 중단된 누적 기록을 읽는다. 업무 State를 복원·재주입하지 않는다."""

import json
from collections import Counter
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from math import isfinite
from typing import Literal

from pydantic import TypeAdapter, ValidationError
from typing_extensions import TypedDict

from eval.batch_store import _inside, _report
from src.execution_trace import SpanRecord, utc_now

span_adapter = TypeAdapter(SpanRecord)


class ExecutionEvidence(TypedDict):
    source: Literal["trace.jsonl"]
    complete: Literal[False]
    issues: list[str]
    observed_at: str
    last_observed_at: str | None
    entry_observed: bool


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _valid_span(span):
    try:
        span_adapter.validate_python(span, strict=True)
    except ValidationError:
        return False
    elapsed = span.get("elapsed_seconds")
    return (
        all(span[key] for key in ("id", "kind", "name"))
        and span["sequence"] > 0
        and _timestamp(span.get("started_at")) is not None
        and span.get("status") in {"running", "success", "error", "interrupted"}
        and (span.get("ended_at") is None or _timestamp(span["ended_at"]) is not None)
        and (elapsed is None or isfinite(elapsed) and elapsed >= 0)
    )


def _read_journal(raw):
    spans, events, issues, conflicted = {}, {}, [], set()
    lines = raw.splitlines(keepends=True) if isinstance(raw, bytes) else raw
    immutable = ("id", "parent_id", "sequence", "kind", "name", "started_at", "input")
    for index, line in enumerate(lines, 1):
        try:
            event = json.loads(line.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            tail = not line.endswith((b"\n", b"\r"))
            issues.append(
                f"trace.jsonl:{index}: {'잘린 마지막 행' if tail else '손상된 행'}"
            )
            continue
        if not isinstance(event, dict) or event.get("event") not in {
            "start",
            "update",
            "end",
        }:
            issues.append(f"trace.jsonl:{index}: 알 수 없는 기록 종류")
            continue
        span = event.get("span")
        if not _valid_span(span):
            issues.append(f"trace.jsonl:{index}: 호출 기록 필수 정보 누락·손상")
            continue
        key, phase = span["id"], event["event"]
        previous = spans.get(key)
        reason = None
        if previous is None and phase != "start":
            reason = "시작 기록 누락"
        elif previous is not None:
            if any(previous.get(field) != span.get(field) for field in immutable):
                reason = "동일 호출 ID의 입력·식별 정보 충돌"
            elif phase == "start" and previous != span:
                reason = "호출 시작 중복"
            elif events[key] == "end" and previous != span:
                reason = "종료 뒤 상충 기록"
        if (phase == "end") != (span.get("ended_at") is not None):
            reason = "종료 이벤트·시각 불일치"
        if phase == "end" and span.get("status") == "running":
            reason = "종료 이벤트·상태 불일치"
        if phase != "end" and span.get("status") != "running":
            reason = "미종료 이벤트·상태 불일치"
        if reason:
            conflicted.add(key)
            issues.append(f"trace.jsonl:{index}: {reason}: {key}")
        # update/end는 전체 스냅샷이다. 같은 ID를 호출 여러 번으로 세지 않는다.
        spans[key] = deepcopy(span)
        events[key] = phase
    sequences = Counter(span["sequence"] for span in spans.values())
    for key, span in spans.items():
        if sequences[span["sequence"]] > 1:
            conflicted.add(key)
            issues.append(f"호출 순번 중복: {key}")
        if span.get("parent_id") not in {None, *spans}:
            conflicted.add(key)
            issues.append(f"상위 호출 기록 누락: {key}")
        parent = spans.get(span.get("parent_id"))
        if parent is not None and parent["sequence"] >= span["sequence"]:
            conflicted.add(key)
            issues.append(f"상위 호출 순서 역전·순환: {key}")
        if span.get("ended_at") is not None and (
            _timestamp(span["ended_at"]) < _timestamp(span["started_at"])
        ):
            conflicted.add(key)
            issues.append(f"호출 시작·종료 시각 역전: {key}")
        if key in conflicted:
            # 상충 스냅샷을 정상 반환으로 사용하지 않으며 원본은 journal에 보존한다.
            span["status"] = "unknown"
            span["evidence_conflict"] = True
    return sorted(spans.values(), key=lambda item: item["sequence"]), issues


def _check_identity(root_span, entry, case, suite_id):
    inputs = root_span.get("input")
    if not isinstance(inputs, dict):
        return False
    expected = {
        "id": entry["run_id"],
        "suite_id": suite_id,
        "case_id": case["id"],
        "unit": case["unit"],
        "target": case["target"],
        "repetition": entry["repetition"],
        "role": case["target"] if case["unit"] == "agent" else case.get("role"),
        "dependencies": case.get("dependencies", "real"),
    }
    run = inputs.get("run")
    if isinstance(run, dict):
        if any(run.get(key) != value for key, value in expected.items()):
            raise ValueError("사례·묶음 등록과 누적 실행 기록의 식별 정보가 다릅니다")
        return True
    # 이전 기록에는 run 메타데이터가 없다. 실제 진입 State의 실행 ID를 확인한다.
    initial = inputs.get("initial_state") or {}
    execution = initial.get("execution") if isinstance(initial, dict) else None
    execution = execution if isinstance(execution, dict) else {}
    if execution.get("run_id") not in {None, entry["run_id"]}:
        raise ValueError("누적 실행 기록과 State의 실행 ID가 다릅니다")
    if root_span["name"] != case["target"] or inputs.get("unit") != case["unit"]:
        raise ValueError("사례와 누적 실행 기록의 평가 대상이 다릅니다")
    return execution.get("run_id") == entry["run_id"]


def load_execution_report(root, entry, case, suite_id, hashes, *, observed_at=None):
    """정상 결과를 우선 읽고, 없는 경우 journal의 확인 가능한 관측만 반환한다."""
    report = _report(root, entry, case, suite_id, hashes)
    if report is not None:
        return report
    relative = f"runs/{entry['run_id']}/trace.jsonl"
    path = _inside(root, relative)
    if not path.exists():
        return None
    if not path.stat().st_size:
        hashes[relative] = sha256(b"").hexdigest()
        return None
    observed_at = observed_at or utc_now()
    if _timestamp(observed_at) is None:
        raise ValueError("관측 종료 시각은 시간대가 있는 ISO 시각이어야 합니다")
    raw = path.read_bytes()
    hashes[relative] = sha256(raw).hexdigest()
    spans, issues = _read_journal(raw)
    roots = [s for s in spans if s["kind"] == "evaluation" and s["parent_id"] is None]
    identified = (
        len(roots) == 1
        and roots[0]["status"] != "unknown"
        and _check_identity(roots[0], entry, case, suite_id)
    )
    if not identified:
        issues.append("실행 진입 식별 증거가 없거나 중복되었습니다")
    boundaries = [
        s
        for s in spans
        if s["kind"] == "execution"
        and len(roots) == 1
        and s["parent_id"] == roots[0]["id"]
    ]
    boundary = boundaries[0] if len(boundaries) == 1 and identified else None
    if boundary is None:
        issues.append("진입부터 호출자 반환까지의 실행 경계가 없습니다")
    run = {
        "id": entry["run_id"],
        "suite_id": suite_id,
        "case_id": case["id"],
        "unit": case["unit"],
        "target": case["target"],
        "repetition": entry["repetition"],
        "role": case["target"] if case["unit"] == "agent" else case.get("role"),
        "dependencies": case.get("dependencies", "real"),
        "evaluation_scope": "execution",
        "status": "running",
        "started_at": boundary["started_at"] if boundary else None,
        "ended_at": None,
        "elapsed_seconds": None,
    }
    result = {
        "schema_version": "evaluation-run-v1",
        "run": run,
        "output": None,
        "failure": None,
        "assessment": {},
        "fixtures": {},
        "journal_saved": True,
    }
    if boundary and boundary["status"] != "unknown" and boundary.get("ended_at"):
        output = boundary.get("output") or {}
        state = output.get("state") if isinstance(output, dict) else None
        if boundary["status"] == "success" and isinstance(state, dict):
            execution = state.get("execution")
            if (
                not isinstance(execution, dict)
                or execution.get("run_id") != entry["run_id"]
            ):
                issues.append("반환 상태의 실행 ID 불일치")
            else:
                run["status"] = "returned"
                result["state"] = state
        elif boundary["status"] == "error":
            error = boundary.get("error") or {}
            run["status"] = (
                "cancelled" if error.get("type") == "CancelledError" else "error"
            )
            result["failure"] = error
        if run["status"] != "running":
            run["ended_at"] = boundary["ended_at"]
            run["elapsed_seconds"] = boundary.get("elapsed_seconds")
    times = [
        value
        for span in spans
        for value in (span["started_at"], span.get("ended_at"))
        if _timestamp(value) is not None
    ]
    result["evidence"] = ExecutionEvidence(
        source="trace.jsonl",
        complete=False,
        issues=issues,
        observed_at=observed_at,
        last_observed_at=max(times, key=_timestamp) if times else None,
        entry_observed=boundary is not None,
    )
    result["trace"] = {
        "version": "local-execution-trace-v1",
        "spans": spans,
        "counts": dict(Counter(s["kind"] for s in spans)),
        "recovery_issues": issues,
        "coverage": {"unfinished_spans": sum(s.get("ended_at") is None for s in spans)},
    }
    return result
