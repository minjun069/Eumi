"""모델·외부 API 없이 노드 사례의 입력·출처·단계 연결을 검사한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, TypedDict
from unittest.mock import patch
from uuid import UUID

from pydantic import TypeAdapter

AI_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AI_ROOT))

from eval.nodes.rules import _compare  # noqa: E402
from eval.runner import _sources, load_suite, prepare_state  # noqa: E402
from eval.scripts.node_dataset_storage import load_scenarios  # noqa: E402
from src.agent_nodes import NoModelCall, prepare_model_call, process_arguments  # noqa: E402
from src.graph import DESTINATIONS  # noqa: E402
from src.settings import Settings  # noqa: E402
from src.state import state_adapter  # noqa: E402
from src.tools.data import read_dataset  # noqa: E402
from src.tools.interface import create_tools  # noqa: E402
from src.tools.process import process_data  # noqa: E402
from src.tools.query import query_data  # noqa: E402


class ValidationReport(TypedDict):
    schema_version: str
    valid: bool
    checked_at: str
    checks: dict[str, int]
    errors: list[dict[str, str]]
    prompt_boundaries: list[dict[str, Any]]
    files_sha256: dict[str, str]
    unverified: list[str]
    summary: dict[str, Any]
    semantic_review: dict[str, Any]


def _digest(value):
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _source_hash_matches(path: Path, expected: str) -> bool:
    """Git의 LF/CRLF 변환만 허용하며 저장한 출처 해시는 변경하지 않는다."""
    raw = path.read_bytes()
    if sha256(raw).hexdigest() == expected:
        return True
    lf = raw.replace(b"\r\n", b"\n")
    # 단독 CR은 일반 줄바꿈 변환과 구분하며 임의로 삭제·변환하지 않는다.
    if b"\r" in lf:
        return False
    return expected in {
        sha256(lf).hexdigest(),
        sha256(lf.replace(b"\n", b"\r\n")).hexdigest(),
    }


def _shift_month(value, months):
    observed = date.fromisoformat(value)
    year, month = divmod(observed.year * 12 + observed.month - 1 + months, 12)
    return date(year, month + 1, observed.day).isoformat()


async def _prompt(case, suite, settings):
    """서비스 공통 입력 준비만 사용한다. 모델·업무 실행·완료 처리는 하지 않는다."""
    state = prepare_state(case, settings, "00000000-0000-0000-0000-000000000001")
    before = state_adapter.dump_python(state, mode="json")
    providers, catalog = _sources(case, suite, settings)
    prepared, terminal = None, None
    tools = (
        {tool.name: tool for tool in create_tools(providers, state=state)}
        if case["target"] == "act"
        else None
    )
    with patch("src.execution.uuid4", return_value=UUID(int=2)):
        try:
            prepared = prepare_model_call(
                case["target"],
                state,
                role=case["role"],
                catalog=catalog,
                tools=tools,
                report_stage=case.get("model_call"),
            )
        except NoModelCall:
            terminal = "no_model_call"
    return {
        "initial_state": before,
        "messages": [
            message.model_dump(mode="json") for message in prepared["messages"]
        ]
        if prepared
        else None,
        "schema": TypeAdapter(prepared["schema"]).json_schema() if prepared else None,
        "terminal": terminal,
    }


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _validate_process_history(history, identity, check, replay_cache):
    """각 호출 직전 이력으로 참조를 해석하고 실제 가공 도구의 전체 출력을 대조한다."""
    for index, item in enumerate(history):
        record_id = f"{identity}/results/{index}:{item['id']}"
        action = item.get("action") or {}
        output = item.get("output")
        if action.get("name") == "process_data" and item.get("outcome") == "success":
            try:
                # 뒤에 추가된 자료나 자기 자신을 입력 근거로 사용할 수 없다.
                actual = process_arguments(
                    {"results": history[:index]}, action["arguments"]
                )
                check(True, "history_process_references_resolved", record_id)
                key = _digest(actual)
                if key not in replay_cache:
                    replay_cache[key] = process_data(actual)
                expected = replay_cache[key]
                check(
                    expected == output,
                    "history_process_output_matches_replay",
                    record_id,
                )
            except Exception as exc:
                check(
                    False,
                    "history_process_replay",
                    record_id,
                    type(exc).__name__,
                )
        if isinstance(output, dict) and isinstance(output.get("results"), list):
            _validate_process_history(
                output["results"], record_id + "/output", check, replay_cache
            )


def _snapshot_checks(root, report, check):
    path = root / "snapshots/data.json"
    raw_path = root / "snapshots/raw-query-results.json"
    snapshot, raw = _read(path), _read(raw_path)
    provenance = snapshot["provenance"]
    check(
        provenance["origin"] == "configured_service_database_read_only_snapshot"
        and not provenance["database"].startswith("eumi_eval"),
        "service_database_origin",
        "snapshot",
    )
    check(
        provenance["transaction"]["read_only"] == "on"
        and provenance["transaction"]["isolation"] == "repeatable read",
        "read_only_capture",
        "snapshot",
    )
    for name, dataset in snapshot["datasets"].items():
        read_dataset(dataset)
        check(
            _digest(dataset) == provenance["dataset_sha256"][name],
            "snapshot_dataset_hash",
            name,
        )
        exact = raw["sources"][name]
        check(
            _digest(exact) == provenance["sources"][name]["query_result_sha256"],
            "raw_query_hash",
            name,
        )
        kinds = {column["name"]: column["kind"] for column in dataset["columns"]}
        converted = [
            {
                key: float(Decimal(value))
                if kinds[key] == "number" and isinstance(value, str)
                else value
                for key, value in row.items()
            }
            for row in exact
        ]
        check(converted == dataset["rows"], "raw_to_dataset_rows", name)
        check(
            len(exact) == provenance["sources"][name]["row_count"],
            "captured_row_count",
            name,
        )
    check(
        _digest(raw["regions"]) == provenance["region_query"]["query_result_sha256"],
        "region_map_hash",
        "snapshot",
    )
    for key, source in (
        ("capture_script_sha256", root / "capture_snapshot.py"),
        ("service_provider_sha256", AI_ROOT / "src/database.py"),
    ):
        check(_source_hash_matches(source, provenance[key]), key, "snapshot")
    for item in (path, raw_path):
        report["files_sha256"][item.relative_to(root).as_posix()] = sha256(
            item.read_bytes()
        ).hexdigest()
    return snapshot


def _resolve_ref(reference, documents):
    filename, pointer = reference.split("#", 1)
    value = documents[filename]
    for part in pointer.strip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _load_scenario_files(index_path, index, report, check):
    """시나리오 본문을 복원하고 실제 검사한 파일을 해시 목록에 남긴다."""
    try:
        sidecar = load_scenarios(index_path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        check(False, "scenario_files_loaded", index_path.name, str(exc))
        return None
    check(True, "scenario_files_loaded", index_path.name)
    for entry, scenario in zip(index["scenarios"], sidecar["scenarios"], strict=True):
        path = index_path.parent / entry["file"]
        raw = path.read_bytes()
        report["files_sha256"][entry["file"]] = sha256(raw).hexdigest()
        check(
            json.loads(raw.decode("utf-8-sig")) == scenario,
            "scenario_file_content_matches_loaded",
            entry["file"],
        )
    return sidecar


def _validate_links(suites, sidecar, report, check):
    """경로의 모든 등장과 고유 사례의 역색인을 양방향으로 대조한다."""
    cases = [case for suite in suites for case in suite["cases"]]
    by_id = {case["id"]: case for case in cases}
    documents = {
        suite["cases"][0]["target"] + ".json": suite
        for suite in suites
        if suite["cases"]
    }
    index = sidecar.get("case_index", {})
    check(set(index) == set(by_id), "case_index_complete", "dataset")
    references = {identity: [] for identity in by_id}
    forward = {identity: {"usages": [], "partial_usages": []} for identity in by_id}
    for collection, usage_key in (
        ("scenarios", "usages"),
        ("partial_groups", "partial_usages"),
    ):
        groups = sidecar.get(collection, [])
        check(
            len({group["id"] for group in groups}) == len(groups),
            collection + "_identities_unique",
            "dataset",
        )
        for group in groups:
            steps = group.get("steps", [])
            check(
                len({step["step_id"] for step in steps}) == len(steps),
                "step_id_unique",
                group["id"],
            )
            for step in steps:
                identity = step["case_id"]
                location = group["id"] + "/" + step["step_id"]
                check(identity in by_id, "step_case_present", location)
                if identity not in by_id:
                    continue
                case = by_id[identity]
                references[identity].append((group, step))
                forward[identity][usage_key].append((group["id"], step["step_id"]))
                check(
                    (step.get("node"), step.get("role"))
                    == (case["target"], case["role"]),
                    "sidecar_node_role_equal",
                    location,
                )
                check(
                    group.get("event") == case["initial"]["event"],
                    "sidecar_event_equal",
                    location,
                )
                for field, target in (
                    ("input_ref", "initial"),
                    ("expectation_ref", "assessment"),
                ):
                    try:
                        matches = _resolve_ref(step[field], documents) == case[target]
                    except (KeyError, IndexError, TypeError, ValueError):
                        matches = False
                    check(matches, "step_" + field + "_resolves", location)
                expected_nodes = step.get("expected_next_nodes")
                if collection == "scenarios" or expected_nodes is not None:
                    check(
                        step.get("node") in DESTINATIONS
                        and isinstance(expected_nodes, list)
                        and all(
                            item in DESTINATIONS[step["node"]]
                            for item in expected_nodes
                        ),
                        "expected_runtime_node_allowed",
                        location,
                    )
                if collection == "scenarios":
                    check(
                        "expected_next" not in step,
                        "legacy_next_field_removed",
                        location,
                    )
    aliases = []
    for identity, case in by_id.items():
        entry = index.get(identity, {})
        check(bool(references[identity]), "sidecar_case_present", identity)
        check(
            (entry.get("node"), entry.get("role")) == (case["target"], case["role"]),
            "case_index_node_role_equal",
            identity,
        )
        aliases.extend(entry.get("aliases", []))
        for usage_key, identity_key in (
            ("usages", "scenario_id"),
            ("partial_usages", "group_id"),
        ):
            declared = [
                (usage.get(identity_key), usage.get("step_id"))
                for usage in entry.get(usage_key, [])
            ]
            check(
                Counter(declared) == Counter(forward[identity][usage_key]),
                "bidirectional_" + usage_key,
                identity,
            )
        for field, target in (
            ("input_ref", "initial"),
            ("expectation_ref", "assessment"),
        ):
            try:
                matches = _resolve_ref(entry[field], documents) == case[target]
            except (KeyError, IndexError, TypeError, ValueError):
                matches = False
            check(matches, "case_index_" + field + "_resolves", identity)
        full_steps = [
            step for _, step in references[identity] if "model_outputs" in step
        ]
        if full_steps:
            lengths = sorted({len(step["model_outputs"]) for step in full_steps})
            check(
                lengths == entry.get("model_call_counts")
                and entry.get("model_call_count")
                == (lengths[0] if len(lengths) == 1 else None),
                "shared_model_call_count_equal",
                identity,
            )
            if lengths == [0]:
                check(
                    case.get("assessment", {}).get("required") is False
                    and "runtime-only" in case.get("tags", [])
                    and not any(
                        item.get("applicable") is not False
                        for item in case.get("assessment", {})
                        .get("expected", {})
                        .get("items", [])
                    ),
                    "runtime_only_quality_scope",
                    identity,
                )
        transformations = {
            _digest(group.get("provenance", {}).get("transformation"))
            for group, _ in references[identity]
        }
        check(
            len(transformations) == 1,
            "shared_source_transformation_equal",
            identity,
        )
    check(len(set(aliases)) == len(aliases), "case_alias_unique", "dataset")
    summary = {
        "complete_scenario_count": len(sidecar.get("scenarios", [])),
        "unique_node_case_count": len(by_id),
        "path_node_execution_count": sum(
            len(item["usages"]) for item in forward.values()
        ),
        "preparation_node_execution_count": sum(
            len(path.get("entry_transition", {}).get("parent_steps", []))
            for path in sidecar.get("scenarios", [])
            if path.get("entry_transition", {}).get("kind") == "agent_call"
        ),
        "partial_group_count": len(sidecar.get("partial_groups", [])),
        "partial_only_node_case_count": sum(
            not item["usages"] and bool(item["partial_usages"])
            for item in forward.values()
        ),
        "shared_node_case_count": sum(
            len(item["usages"]) > 1 for item in forward.values()
        ),
        "runtime_only_node_case_count": sum(
            index.get(identity, {}).get("model_call_counts") == [0]
            for identity in by_id
        ),
        "path_runtime_only_execution_count": sum(
            not step["model_outputs"]
            for path in sidecar.get("scenarios", [])
            for step in path["steps"]
        ),
        "by_node": dict(Counter(case["target"] for case in cases)),
        "by_role": dict(Counter(case["role"] for case in cases)),
        "by_event": dict(Counter(case["initial"]["event"] for case in cases)),
        "scenarios_by_event": dict(
            Counter(path["event"] for path in sidecar.get("scenarios", []))
        ),
    }
    for key, value in summary.items():
        check(sidecar.get("summary", {}).get(key) == value, "summary_recomputed", key)
    report["summary"] = summary
    return references


def _validate_basic_scope(sidecar, snapshot, check):
    """이번 기본 묶음의 역할·대화 조건·지역 조합을 확인한다."""
    scenarios = sidecar.get("scenarios", [])
    check(
        sidecar.get("dataset_scope") == "basic-agent-paths",
        "basic_dataset_scope",
        "dataset",
    )
    check(not sidecar.get("partial_groups"), "basic_no_partial_groups", "dataset")
    user_roles = {"request", "interpretation", "visualization"}
    report_roles = {"report_selection", "report_description", "report_insight"}
    conditions = {"none", "new_topic", "revision", "clarification_complete"}
    user_paths = [path for path in scenarios if path.get("event") == "user_request"]
    report_paths = [
        path for path in scenarios if path.get("event") == "analysis_pipeline"
    ]
    check(len(scenarios) == 21, "basic_twenty_one_agent_paths", "dataset")
    check(
        Counter(
            (path.get("agent_role"), path.get("conversation_condition"))
            for path in user_paths
        )
        == Counter(
            (role, condition) for role in user_roles for condition in conditions
        ),
        "basic_user_role_conversation_matrix",
        "dataset",
    )
    region_codes = {path.get("region_code") for path in report_paths}
    check(
        len(region_codes) == 3
        and all(isinstance(code, str) and code for code in region_codes)
        and Counter(
            (path.get("agent_role"), path.get("region_code")) for path in report_paths
        )
        == Counter((role, code) for role in report_roles for code in region_codes),
        "basic_report_role_region_matrix",
        "dataset",
    )
    names = {row["adm_cd10"]: row["adm_nm"] for row in snapshot.get("regions", [])}
    for path in scenarios:
        identity = path["id"]
        check(path.get("scope") == "agent", "basic_agent_scope", identity)
        check(
            path.get("agent_role") in user_roles | report_roles,
            "basic_agent_role",
            identity,
        )
        if path["event"] == "analysis_pipeline":
            check(
                names.get(path.get("region_code")) == path.get("region_name")
                and path.get("region_name") is not None,
                "basic_report_region_source",
                identity,
            )
        else:
            state = path["start_state"]
            messages = state.get("messages", [])
            condition = path.get("conversation_condition")
            check(
                len(messages) == 1 if condition == "none" else len(messages) >= 3,
                "basic_user_conversation_context",
                identity,
            )
            # 최상위 요청과 실제 하위 생성 모두 내부 이력은 비워서 시작한다.
            # 하위의 누적 예산 상속은 경로 검증기가 실제 부모와 대조한다.
            check(
                not state.get("results") and state.get("response") is None,
                "basic_user_empty_agent_history",
                identity,
            )
            entry = path.get("entry_transition", {})
            if path["agent_role"] == "request":
                check(not entry, "basic_request_top_level_entry", identity)
            elif path["agent_role"] in {"interpretation", "visualization"}:
                check(
                    entry.get("kind") == "agent_call"
                    and entry.get("parent_role") == "request"
                    and isinstance(entry.get("parent_start_state"), dict)
                    and isinstance(entry.get("after_state"), dict)
                    and isinstance(entry.get("parent_return_record_id"), str)
                    and bool(entry.get("parent_return_record_id")),
                    "basic_specialist_delegated_entry",
                    identity,
                )
                preparation = entry.get("parent_steps", [])
                check(
                    [step.get("node") for step in preparation]
                    == ["interpret", "decide", "act"]
                    and all(step.get("role") == "request" for step in preparation)
                    and bool(preparation)
                    and entry.get("call_step_id") == preparation[-1].get("step_id")
                    and all(
                        not {"case_id", "input_ref", "expectation_ref"} & step.keys()
                        for step in preparation
                    ),
                    "basic_parent_preparation_scope",
                    identity,
                )
            states = [state, path.get("terminal", {}).get("state", {})]
            states.extend(
                step.get(key, {})
                for step in path.get("steps", []) + entry.get("parent_steps", [])
                for key in ("before_state", "after_state")
            )
            states.extend(
                entry.get(key, {}) for key in ("parent_start_state", "after_state")
            )
            check(
                all(
                    not {
                        "entry_transition",
                        "parent_start_state",
                        "parent_steps",
                        "call_step_id",
                        "parent_return_record_id",
                    }
                    & value.keys()
                    for state_value in states
                    for value in _walk(state_value)
                ),
                "basic_preparation_metadata_outside_state",
                identity,
            )
        for step in path.get("steps", []):
            location = identity + "/" + step["step_id"]
            for output in step.get("model_outputs", []):
                check(
                    output.get("accepted", True) is True
                    and output.get("status", "completed") == "completed"
                    and output.get("needs_input", False) is False,
                    "basic_authored_normal_outcome",
                    location,
                )


def _numeric_reference_review(case, snapshot):
    """사례가 특정한 점수·전월 차이의 기대 수치를 불변 자료에서 다시 구한다."""
    from eval.scripts.node_dataset_coverage import _items

    source = "public.region_result"
    rows = snapshot.get("datasets", {}).get(source, {}).get("rows", [])
    points = {
        (row["adm_cd10"], row["period_start"]): (index, row)
        for index, row in enumerate(rows)
    }
    results = []
    for item in _items(case):
        if (
            item["check"] != "N-O.1"
            or item.get("applicable") is False
            or item.get("extract") != "number"
            or type(item.get("value")) not in {int, float}
        ):
            continue
        ref = case.get("assessment", {}).get("reference", {}).get("N-O.1", {})
        basis = ref.get("evidence_basis", {})
        observation = ref.get("observations", {})
        selected, expected, measurement = [], None, None
        reference_facts = []
        if "independent_value" in ref and basis.get("region") and basis.get("month"):
            point = points.get((basis["region"], basis["month"] + "-01"))
            if point:
                selected = [point]
                expected = Decimal(str(point[1]["bh_score"]))
                measurement = "current_bh_score"
                reference_facts.append(
                    ("independent_value", ref["independent_value"], expected)
                )
        elif "difference" in observation:
            target = ref.get("target", {})
            coordinates = set()
            if target.get("dong_code") and len(target.get("months", [])) == 2:
                coordinates = {
                    (target["dong_code"], month + "-01") for month in target["months"]
                }
            else:
                for record in _walk(case.get("initial", {}).get("results", [])):
                    output = record.get("output")
                    if not isinstance(output, dict):
                        continue
                    if output.get("applied", {}).get("target") == source:
                        coordinates.update(
                            (row["adm_cd10"], row["period_start"])
                            for row in output["data"]["rows"]
                        )
            if len(coordinates) == 2 and len({code for code, _ in coordinates}) == 1:
                selected = [points[key] for key in sorted(coordinates) if key in points]
                if len(selected) == 2:
                    before, after = (
                        Decimal(str(row["bh_score"])) for _, row in selected
                    )
                    expected = after - before
                    reference_facts.extend(
                        ("observations/" + key, observation[key], value)
                        for key, value in {
                            "before": before,
                            "after": after,
                            "difference": expected,
                        }.items()
                        if key in observation
                    )
                    # 이 정규식은 부호 밖의 크기만 캡처하도록 사례가 명시했다.
                    if "[+-]?(" in item.get("pattern", ""):
                        expected = abs(expected)
                    measurement = "month_to_month_bh_score_difference"
        elif "after" in observation:
            target = ref.get("target", {})
            months = target.get("months", [])
            # 단일 시점 요청은 명시한 한 달의 값만 대조한다. 여러 달 중
            # 최신 값을 임의로 고르면 비교 요청과 단일 값 요청이 섞인다.
            if target.get("dong_code") and len(months) == 1:
                point = points.get((target["dong_code"], months[0] + "-01"))
                if point:
                    selected = [point]
                    expected = Decimal(str(point[1]["bh_score"]))
                    measurement = "current_bh_score"
                    reference_facts.append(
                        ("observations/after", observation["after"], expected)
                    )
        evidence = [
            f"snapshots/data.json#/datasets/{source}/rows/{index}"
            for index, _ in selected
        ]
        actual = Decimal(str(item["value"]))
        tolerance = Decimal(str(item.get("tolerance", {}).get("absolute", 0)))
        status = (
            "requires_content_review"
            if expected is None
            else "verified"
            if abs(actual - expected) <= tolerance
            else "mismatch"
        )
        checked_facts = [
            {
                "path": "/reference/N-O.1/" + key,
                "value": value,
                "source_value": str(source_value),
                "matches": type(value) in {int, float}
                and abs(Decimal(str(value)) - source_value) <= tolerance,
            }
            for key, value, source_value in reference_facts
        ]
        if any(not fact["matches"] for fact in checked_facts):
            status = "mismatch"
        results.append(
            {
                "item_id": item["id"],
                "measurement": measurement,
                "expected_value": item["value"],
                "source_value": str(expected) if expected is not None else None,
                "source_refs": evidence,
                "reference_facts": checked_facts,
                "status": status,
            }
        )
    return results


def _semantic_review(cases, sidecar, check, snapshot=None):
    """구조화된 기대값과 작성한 경로 응답을 대조하고 의미 검토 근거를 연결한다.

    서비스 모델을 실행한 채점이 아니다. 자연어 판단·설명의 타당성은 검토할
    입력과 기대값을 함께 제시하고 자동 비교 결과와 구분한다.
    """
    from eval.scripts.node_dataset_coverage import _items

    references = {}
    for path in sidecar.get("scenarios", []):
        for step in path["steps"]:
            references.setdefault(step["case_id"], []).append((path, step))
    entries = []
    for case in cases:
        identity = case["id"]
        assessment = case.get("assessment", {})
        items = _items(case)
        active = [item for item in items if item.get("applicable") is not False]
        structured = [item for item in active if "path" in item]
        semantic = [item for item in active if "path" not in item]
        source_comparisons = _numeric_reference_review(case, snapshot or {})
        for comparison in source_comparisons:
            check(
                comparison["status"] != "mismatch",
                "numeric_expectation_matches_source",
                identity + "/" + comparison["item_id"],
            )
        comparisons = []
        for path, step in references.get(identity, []):
            if not step["model_outputs"]:
                continue
            output = step["model_outputs"][0]
            location = path["id"] + "/" + step["step_id"]
            for item in structured:
                reference = assessment.get("reference", {}).get(item["check"])
                detail = _compare(
                    item["check"],
                    item,
                    {"call": {"path": location + "/model_outputs/0"}},
                    output,
                    reference,
                    None,
                )
                comparisons.append(
                    {"usage": location, "check": item["check"], **detail}
                )
                check(
                    detail["verdict"] != "실패",
                    "authored_output_matches_structured_expectation",
                    location + "/" + item["id"],
                    detail["reason"],
                )
        entry = sidecar.get("case_index", {}).get(identity, {})
        entries.append(
            {
                "case_id": identity,
                "node": case["target"],
                "role": case["role"],
                "input_ref": entry.get("input_ref"),
                "expectation_ref": entry.get("expectation_ref"),
                "structured_comparisons": comparisons,
                "numeric_source_comparisons": source_comparisons,
                "judgment_review_items": [
                    {
                        "item_id": item["id"],
                        "check": item["check"],
                        "reference_pointer": "/reference/" + item["check"],
                        "status": "requires_content_review",
                    }
                    for item in semantic
                ],
                "outside_first_call_item_ids": [
                    item["id"]
                    for item in assessment.get("expected", {}).get("items", [])
                    if item not in items
                ],
            }
        )
    return {
        "scope": (
            "작성한 정상 경로 응답과 구조화된 기대값의 일관성을 확인한다. "
            "업무 모델 품질 채점·자연어 의미 검토의 통과를 뜻하지 않는다. "
            "노드 단독 평가와 같은 첫 모델 호출 범위를 사용한다."
        ),
        "summary": {
            "case_count": len(entries),
            "structured_comparison_count": sum(
                len(entry["structured_comparisons"]) for entry in entries
            ),
            "judgment_review_item_count": sum(
                len(entry["judgment_review_items"]) for entry in entries
            ),
            "numeric_source_statuses": dict(
                Counter(
                    item["status"]
                    for entry in entries
                    for item in entry["numeric_source_comparisons"]
                )
            ),
            "structured_verdicts": dict(
                Counter(
                    item["verdict"]
                    for entry in entries
                    for item in entry["structured_comparisons"]
                )
            ),
        },
        "cases": entries,
    }


async def _validate_cases(suites, sidecar, snapshot, report, check):
    settings = Settings(
        _env_file=None, database_url=None, api_key=None, LANGFUSE_ENABLED=False
    )
    references = _validate_links(suites, sidecar, report, check)
    all_ids = set()
    checked_queries = set()
    process_replay_cache = {}
    for suite in suites:
        check(
            suite.get("data_source", "prepared") == "prepared",
            "offline_data_source",
            suite["id"],
        )
        for name, dataset in suite.get("datasets", {}).items():
            check(
                dataset == snapshot["datasets"].get(name),
                "suite_snapshot_equal",
                f"{suite['id']}:{name}",
            )
        for case in suite["cases"]:
            identity = case["id"]
            check(identity not in all_ids, "case_id_unique", identity)
            all_ids.add(identity)
            if not references[identity]:
                continue
            scenario = references[identity][0][0]
            families = {group.get("family") for group, _ in references[identity]}
            if families & {"U5", "U6"} and case["target"] == "interpret":
                check(
                    not case["initial"].get("results")
                    and case["initial"].get("response") is None,
                    "clarification_empty_agent_history",
                    identity,
                )
            # 초기 이력의 조회 행은 원본 스냅샷에 같은 조건을 적용해 대조한다.
            for item in _walk(case["initial"].get("results", [])):
                action = item.get("action") or {}
                output = item.get("output") or {}
                if action.get("name") != "query_data" or not isinstance(output, dict):
                    continue
                if "data" not in output or "applied" not in output:
                    continue
                query_key = _digest(output)
                if query_key in checked_queries:
                    continue
                checked_queries.add(query_key)
                target = output["applied"]["target"]
                arguments = deepcopy(output["applied"])
                observed_rows = deepcopy(output["data"]["rows"])
                transformation = scenario.get("provenance", {}).get("transformation")
                if transformation:
                    check(
                        transformation.get("kind") == "calendar_shift"
                        and transformation.get("numeric_values") == "unchanged"
                        and type(transformation.get("months")) is int
                        and "data:controlled-transformation" in case.get("tags", []),
                        "controlled_date_shift_declared",
                        identity,
                    )
                    month_map = transformation["period_start_map"]
                    reverse = {value: key for key, value in month_map.items()}
                    check(
                        len(reverse) == len(month_map),
                        "controlled_date_shift_bijective",
                        identity,
                    )
                    check(
                        all(
                            _shift_month(before, transformation["months"]) == after
                            for before, after in month_map.items()
                        ),
                        "controlled_date_shift_matches_calendar",
                        identity,
                    )
                    original = snapshot["datasets"][target]["reference"]
                    check(
                        transformation["original_dataset_versions"][target]
                        == original["version"],
                        "controlled_original_version",
                        identity,
                    )
                    for row in observed_rows:
                        if "period_start" in row:
                            row["period_start"] = reverse[row["period_start"]]
                    for condition in arguments.get("filters", []):
                        if condition["field"] == "period_start":
                            # 조회 경계는 관측 월 목록 밖일 수도 있다.
                            condition["value"] = _shift_month(
                                condition["value"], -transformation["months"]
                            )
                    arguments["version"] = original["version"]
                expected = query_data(
                    arguments,
                    {target: lambda name=target: deepcopy(snapshot["datasets"][name])},
                )
                check(
                    expected["data"]["rows"] == observed_rows,
                    "history_query_rows_match_snapshot",
                    identity,
                )
                check(
                    all(
                        ref in output["data"].get("inputs", [])
                        for ref in expected["data"]["inputs"]
                    )
                    if transformation
                    else expected["data"]["inputs"] == output["data"].get("inputs"),
                    "history_query_source_references",
                    identity,
                )
            _validate_process_history(
                case["initial"].get("results", []),
                identity + "/initial",
                check,
                process_replay_cache,
            )
            try:
                baseline = await _prompt(case, suite, settings)
                for group, step in references[identity]:
                    if "before_state" not in step:
                        continue
                    expected_state = deepcopy(step["before_state"])
                    expected_state["execution"]["run_id"] = baseline["initial_state"][
                        "execution"
                    ]["run_id"]
                    check(
                        baseline["initial_state"] == expected_state,
                        "path_node_state_restored",
                        group["id"] + "/" + step["step_id"],
                    )
                poisoned = deepcopy(case)
                sentinel = "EVAL_ONLY_CANARY_" + identity
                poisoned["assessment"] = {"reference": {"canary": sentinel}}
                poisoned["purpose"] = sentinel
                poisoned["tags"] = [sentinel]
                changed = await _prompt(poisoned, suite, settings)
                check(
                    baseline == changed,
                    "assessment_metadata_input_independence",
                    identity,
                )
                check(
                    sentinel not in json.dumps(changed, ensure_ascii=False),
                    "assessment_metadata_canary_absent",
                    identity,
                )
                has_prompt = baseline["messages"] is not None
                no_model = sidecar["case_index"][identity].get("model_call_counts") == [
                    0
                ]
                if no_model:
                    check(
                        not has_prompt and baseline["terminal"] is not None,
                        "terminal_without_model_prepared",
                        identity,
                    )
                else:
                    check(has_prompt, "first_model_input_prepared", identity)
                first_calls = {
                    item["call"]
                    for item in case.get("assessment", {})
                    .get("expected", {})
                    .get("items", [])
                    if item.get("call") and item.get("call_index", 1) == 1
                }
                if first_calls and not no_model:
                    check(
                        (baseline["schema"] or {}).get("title") in first_calls,
                        "first_model_call_matches_expected_scope",
                        identity,
                    )
                report["prompt_boundaries"].append(
                    {
                        "case_id": identity,
                        "node": case["target"],
                        "role": case["role"],
                        "prepared": has_prompt,
                        "model_call_count": 0 if no_model else 1,
                        "model_called": False,
                        "schema": (baseline["schema"] or {}).get("title"),
                        "prompt_sha256": _digest(baseline["messages"]),
                        "terminal_without_model": baseline["terminal"],
                    }
                )
            except Exception as exc:
                check(False, "prompt_preparation", identity, type(exc).__name__)
    check(
        all_ids == set(sidecar["case_index"]) and all(references.values()),
        "sidecar_all_cases_linked",
        "dataset",
    )


def validate_dataset(root: Path) -> ValidationReport:
    """기존 파일을 읽고 모델·외부 API 호출 없이 검증 결과를 반환한다."""
    root = Path(root).resolve()
    report: ValidationReport = {
        "schema_version": "node-dataset-validation-v3",
        "valid": False,
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": {},
        "errors": [],
        "prompt_boundaries": [],
        "files_sha256": {},
        "summary": {},
        "semantic_review": {},
        "unverified": [
            "업무 모델 출력·평가 모델 판정·사람 기준 검토는 실행하지 않음",
            "각 노드의 첫 모델 입력까지 확인. 후속 작성·검토 호출 입력은 미실행",
            "원자료 수집 과정·운영 자료 최신성은 검증하지 않음",
            "DB 재접속·HTTP·Tableau 화면·저장·알림은 실행하지 않음",
            "가공 인자·출력은 실제 도구로 재계산하나 연산 선택·직접 작성한 설명의 "
            "의미 정확성은 판정하지 않음",
        ],
    }
    counts = Counter()

    def check(condition, name, identity, detail=""):
        counts[name] += 1
        if not condition:
            report["errors"].append(
                {"check": name, "id": identity, "detail": detail or "condition_failed"}
            )

    try:
        snapshot = _snapshot_checks(root, report, check)
        suites, sidecar, coverage = [], None, None
        suite_names = set()
        for path in sorted(root.glob("*.json")):
            if path.name == "validation.json":
                continue
            document = _read(path)
            if document.get("schema_version") == "evaluation-suite-v1":
                load_suite(path)
                # 해시·포인터는 저장된 JSON으로 대조하고 메시지 객체화는
                # 실제 입력을 만드는 prepare_state에 맡긴다.
                suites.append(document)
                suite_names.add(path.name)
                counts["suite_schema_validated"] += 1
                check(
                    all(case["target"] == path.stem for case in suites[-1]["cases"]),
                    "node_file_target_equal",
                    path.name,
                )
            elif path.name == "scenarios.json":
                check(
                    document.get("schema_version") == "node-scenarios-v4",
                    "sidecar_schema_version",
                    path.name,
                )
                sidecar = _load_scenario_files(path, document, report, check)
                check(
                    document.get("source_snapshot") == "snapshots/data.json"
                    and document.get("source_snapshot_sha256")
                    == report["files_sha256"]["snapshots/data.json"],
                    "sidecar_snapshot_reference",
                    path.name,
                )
                for source, expected in document.get("runtime_sources", {}).items():
                    source_path = (AI_ROOT / source).resolve()
                    check(
                        source_path.is_relative_to(AI_ROOT)
                        and source_path.is_file()
                        and _source_hash_matches(source_path, expected),
                        "path_runtime_source_sha256",
                        source,
                    )
            elif path.name == "coverage.json":
                coverage = document
            else:
                continue
            report["files_sha256"][path.name] = sha256(path.read_bytes()).hexdigest()
        check(len(suites) == 5, "five_node_suite_files", "dataset")
        check(
            suite_names
            == {
                name + ".json"
                for name in ("interpret", "act", "decide", "compose", "ask")
            },
            "node_suite_filenames",
            "dataset",
        )
        check(bool(sidecar), "scenario_sidecar_present", "dataset")
        if sidecar:
            from eval.scripts.node_dataset_coverage import build_coverage
            from eval.scripts.node_dataset_paths import validate_paths

            cases = [case for suite in suites for case in suite["cases"]]
            _validate_basic_scope(sidecar, snapshot, check)
            for error in validate_paths(sidecar, cases):
                if isinstance(error, dict):
                    check(
                        False,
                        error.get("check", "complete_path"),
                        error.get("id", error.get("identity", "dataset")),
                        error.get("detail", json.dumps(error, ensure_ascii=False)),
                    )
                else:
                    check(False, "complete_path", "dataset", str(error))
            computed_coverage = build_coverage(cases, sidecar)
            check(
                coverage == computed_coverage,
                "coverage_recomputed",
                "dataset",
            )
            check(
                not computed_coverage["gaps"],
                "in_scope_assessment_coverage",
                "dataset",
                json.dumps(computed_coverage["gaps"][:5], ensure_ascii=False),
            )
            report["semantic_review"] = _semantic_review(
                cases, sidecar, check, snapshot
            )
            asyncio.run(_validate_cases(suites, sidecar, snapshot, report, check))
    except Exception as exc:
        report["errors"].append(
            {"check": "validation_setup", "id": "dataset", "detail": type(exc).__name__}
        )
    report["checks"] = dict(counts)
    report["valid"] = not report["errors"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root", nargs="?", type=Path, default=AI_ROOT / "eval/scenarios/nodes"
    )
    args = parser.parse_args()
    report = validate_dataset(args.root)
    output = args.root / "validation.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "errors": report["errors"],
                "checks": report["checks"],
            },
            ensure_ascii=True,
        )
    )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
