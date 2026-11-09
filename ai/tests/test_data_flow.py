"""실제 자료·도구·State로 조회 열과 가공 참조·연산 연결을 검증한다."""

import json
from copy import deepcopy

import pytest

from api import create_report_states, execute_reports
from experiments.report_fixtures import datasets
from experiments.report_roundtrip import FileReportDatabase
from src.agent_nodes import build_nodes
from src.database import REPORT_SOURCES, Database
from src.exceptions import ToolFailure
from src.execution import record
from src.prompting import selection_messages
from src.state import report_artifact, state_adapter
from src.tool_specs import selection_tools
from src.tools.interface import create_tools
from src.tools.process import process_data
from src.tools.query import query_data
from tests.helpers import ScriptedModel, section, selection
from tests.test_reports import BODY, setup


def prepared(tmp_path):
    settings, _ = setup(tmp_path)
    state = create_report_states(BODY, settings)[0]
    data = datasets(BODY)
    providers = {
        name: lambda value=value: deepcopy(value) for name, value in data.items()
    }
    _, catalog = Database(settings).report_sources()
    return state, data, providers, catalog


def test_catalog_lists_actual_query_columns_and_types(tmp_path):
    _, data, _, catalog = prepared(tmp_path)
    for name in REPORT_SOURCES:
        assert "조회 가능한 열(이 목록만 사용)" in catalog[name]
        for column in data[name]["columns"]:
            assert (
                f"{column['name']} ({column['kind']}, {column['unit']})"
                in catalog[name]
            )
    assert "indicator_cd" in catalog["analysis.bh_region_contribution"]
    actual_columns = catalog["analysis.flow_detail"].split(
        "조회 가능한 열(이 목록만 사용): "
    )[1]
    assert "activity_daily" in actual_columns
    assert "flow_sum" not in actual_columns and "day_count" not in actual_columns


@pytest.mark.parametrize(
    "target,fields",
    [
        ("analysis.bh_region_contribution", ["indicator", "contribution"]),
        ("analysis.flow_detail", ["flow_sum", "day_count"]),
    ],
)
def test_logged_invalid_query_fields_remain_rejected(tmp_path, target, fields):
    _, _, providers, _ = prepared(tmp_path)
    with pytest.raises(ToolFailure) as caught:
        query_data({"target": target, "fields": fields}, providers)
    assert caught.value.code == "invalid_field"
    # 열을 명시하지 않은 재조회는 실제 열과 출처·페이지 정보를 제공한다.
    result = query_data({"target": target, "limit": 1}, providers)
    assert caught.value.details == {
        "requested": fields,
        "available": [c["name"] for c in result["data"]["columns"]],
    }
    assert all(
        c["name"] not in fields
        for c in result["data"]["columns"]
        if c["name"] != "contribution"
    )
    assert result["next_offset"] == 1
    page = query_data(result["applied"] | {"offset": 1}, providers)
    assert page["applied"]["version"] == result["applied"]["version"]
    assert page["applied"]["version"] != result["data"]["reference"]["version"]


def test_processing_choices_come_only_from_usable_state_results(tmp_path):
    state, _, providers, catalog = prepared(tmp_path)
    output = query_data({"target": "public.region_result"}, providers)
    usable = record("act", "call", "조회", output=output)
    failed = record("act", "call", "실패", output=output, success=False)
    rejected = record("act", "call", "부적합", output=output)
    decision = record("act", "selection", "자료 아님", output={"name": "query_data"})
    child = record("act", "call", "하위 자료", output=output)
    parent = record("act", "call", "하위 실행", output={"results": [child]})
    state["results"].extend(
        [
            usable,
            failed,
            rejected,
            decision,
            parent,
            record(
                "act",
                "verification",
                "거부",
                output={"call_id": rejected["id"], "accepted": False},
            ),
        ]
    )
    state = state_adapter.validate_json(state_adapter.dump_json(state))
    original = deepcopy(state)
    tools = {t.name: t for t in create_tools(providers, state=state)}
    definitions = selection_tools(tools, "report", state=state)
    functions = {d["function"]["name"]: d["function"] for d in definitions}
    ids = functions["process_data"]["parameters"]["properties"]["input_result_id"][
        "enum"
    ]
    assert set(ids) == {usable["id"], child["id"]}
    assert output["data"]["reference"]["id"] not in ids
    join = functions["process_data"]["parameters"]["$defs"]["Join"]
    assert set(join["properties"]["right_result_id"]["enum"]) == set(ids)
    assert "right" not in join["properties"]
    assert "right_result_id" in join["required"]
    assert "right" not in join["required"]
    assert "Dataset" not in functions["process_data"]["parameters"]["$defs"]
    assert "right" in tools["process_data"].args_schema["$defs"]["Join"]["properties"]
    assert set(
        functions["query_data"]["parameters"]["properties"]["target"]["enum"]
    ) == set(providers)
    shown = section(
        selection_messages(state, "report", catalog), "가공 가능한 결과 ID와 열"
    )
    assert set(shown) == set(ids)
    assert shown[usable["id"]] == output["data"]["columns"]
    assert state == original
    other = create_report_states(BODY, setup(tmp_path)[0])[0]
    other_tools = {t.name: t for t in create_tools(providers, state=other)}
    fresh = selection_tools(other_tools, "report", state=other)[1]["function"][
        "parameters"
    ]
    assert "enum" not in fresh["properties"]["input_result_id"]
    assert "먼저 query_data" in fresh["properties"]["input_result_id"]["description"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,invalid,correct",
    [
        ("analysis.bh_region_contribution", "indicator", "indicator_cd"),
        ("analysis.flow_detail", "flow_sum", "activity_daily"),
    ],
)
async def test_query_failure_can_be_corrected_from_actual_catalog(
    tmp_path, target, invalid, correct
):
    state, _, providers, catalog = prepared(tmp_path)

    def repair(messages):
        history = section(messages, "작업 결과와 검증 이력")
        assert history[-1]["output"]["code"] == "invalid_field"
        assert history[-1]["output"]["details"]["requested"] == [invalid]
        assert correct in history[-1]["output"]["details"]["available"]
        assert section(messages, "가공 가능한 결과 ID와 열") == {}
        available = section(messages, "조회 가능한 자료 목록")
        columns = available[target].split("조회 가능한 열(이 목록만 사용): ")[1]
        assert correct in columns and f"{invalid} (" not in columns
        return selection("query_data", {"target": target, "fields": [correct]})

    model = ScriptedModel(
        [selection("query_data", {"target": target, "fields": [invalid]}), repair]
    )
    nodes = build_nodes(model, providers, catalog, role="report")
    await nodes["act"](state, {})
    await nodes["act"](state, {})
    result = state["results"][-1]
    assert result["outcome"] == "success"
    assert [c["name"] for c in result["output"]["data"]["columns"]] == [correct]
    assert state["execution"]["budget"]["retries"]["used"] == 1


@pytest.mark.asyncio
async def test_derived_reference_rejected_then_real_record_id_processed(tmp_path):
    state, _, providers, catalog = prepared(tmp_path)
    output = query_data({"target": "public.region_result"}, providers)
    source = record("act", "call", "조회", output=output)
    state["results"].append(source)
    operation = [
        {
            "operation": "aggregate",
            "method": "mean",
            "field": "bh_score",
            "group_by": [],
            "output": "mean_score",
        }
    ]

    def repair(messages):
        shown = section(messages, "가공 가능한 결과 ID와 열")
        assert list(shown) == [source["id"]]
        history = section(messages, "작업 결과와 검증 이력")
        assert history[-1]["output"]["code"] == "invalid_data_reference"
        assert history[-1]["output"]["details"] == {
            "requested": output["data"]["reference"]["id"],
            "available": [source["id"]],
        }
        return selection(
            "process_data",
            {"input_result_id": next(iter(shown)), "operations": operation},
        )

    model = ScriptedModel(
        [
            selection(
                "process_data",
                {
                    "input_result_id": output["data"]["reference"]["id"],
                    "operations": operation,
                },
            ),
            repair,
        ]
    )
    nodes = build_nodes(model, providers, catalog, role="report")
    await nodes["act"](state, {})
    assert state["results"][-1]["output"]["code"] == "invalid_data_reference"
    await nodes["act"](state, {})
    result = state["results"][-1]
    assert result["outcome"] == "success"
    assert result["output"]["data"]["rows"] == [{"mean_score": 32.5}]
    assert state["execution"]["budget"]["retries"]["used"] == 1
    assert source["output"] == output


@pytest.mark.asyncio
@pytest.mark.parametrize("source_id", [None, [], {}, 123, "missing"])
async def test_invalid_reference_is_recorded_without_breaking_the_node(
    tmp_path, source_id
):
    state, _, providers, catalog = prepared(tmp_path)
    model = ScriptedModel(
        [selection("process_data", {"input_result_id": source_id, "operations": []})]
    )
    await build_nodes(model, providers, catalog, role="report")["act"](state, {})
    failure = state["results"][-1]
    assert failure["outcome"] == "failure"
    assert failure["output"]["code"] == "invalid_data_reference"
    assert failure["output"]["details"] == {"requested": source_id, "available": []}


def test_aggregate_replaces_columns_and_separate_calls_keep_original(tmp_path):
    _, data, _, _ = prepared(tmp_path)
    original = deepcopy(data["public.region_result"])
    minimum = {
        "operation": "aggregate",
        "method": "min",
        "field": "bh_score",
        "group_by": [],
        "output": "bh_score_min",
    }
    maximum = minimum | {"method": "max", "output": "bh_score_max"}
    with pytest.raises(ToolFailure) as caught:
        process_data({"data": original, "operations": [minimum, maximum]})
    assert caught.value.code == "invalid_field"
    assert caught.value.details == {
        "requested": ["bh_score"],
        "available": ["bh_score_min"],
        "operation_index": 1,
    }
    assert original == data["public.region_result"]
    for operation, expected in ((minimum, 30.0), (maximum, 35.0)):
        result = process_data({"data": original, "operations": [operation]})
        assert result["data"]["rows"] == [{operation["output"]: expected}]
        assert [c["name"] for c in result["data"]["columns"]] == [operation["output"]]


def test_final_projection_failure_reports_final_columns_without_operation_index(
    tmp_path,
):
    _, data, _, _ = prepared(tmp_path)
    with pytest.raises(ToolFailure) as caught:
        process_data(
            {
                "data": data["public.region_result"],
                "operations": [
                    {
                        "operation": "aggregate",
                        "method": "min",
                        "field": "bh_score",
                        "group_by": [],
                        "output": "minimum",
                    }
                ],
                "fields": ["bh_score"],
            }
        )
    assert caught.value.code == "invalid_field"
    assert caught.value.details == {"requested": ["bh_score"], "available": ["minimum"]}


def test_join_maps_existing_right_column_to_new_result_column(tmp_path):
    _, data, _, _ = prepared(tmp_path)
    original = deepcopy(data["public.region_result"])
    right = process_data(
        {
            "data": original,
            "operations": [
                {
                    "operation": "filter",
                    "conditions": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": "2025-12-01",
                        }
                    ],
                }
            ],
        }
    )["data"]
    join = {
        "operation": "join",
        "right": right,
        "keys": ["adm_cd10"],
        "how": "left",
        "fields": {"bh_score_end": "bh_score"},
    }
    with pytest.raises(ToolFailure) as caught:
        process_data({"data": original, "operations": [join]})
    assert caught.value.code == "invalid_field"
    result = process_data(
        {
            "data": original,
            "operations": [
                join | {"fields": {"bh_score": "bh_score_end"}},
                {
                    "operation": "filter",
                    "conditions": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": "2025-07-01",
                        }
                    ],
                },
                {
                    "operation": "calculate",
                    "method": "difference",
                    "before": "bh_score",
                    "after": "bh_score_end",
                    "output": "change",
                },
            ],
            "fields": ["bh_score", "bh_score_end", "change"],
        }
    )
    assert result["data"]["rows"] == [
        {"bh_score": 30.0, "bh_score_end": 35.0, "change": 5.0}
    ]
    assert original == data["public.region_result"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition",
    [
        "missing",
        "derived",
        "failed",
        "rejected",
        "selection",
        "foreign",
        "malformed",
        "inline_only",
        "inline_with_id",
    ],
)
async def test_join_rejects_unusable_or_inline_right_data(tmp_path, condition):
    state, _, providers, catalog = prepared(tmp_path)
    output = query_data({"target": "public.region_result"}, providers)
    left = record("act", "call", "왼쪽 자료", output=output)
    right = record("act", "call", "오른쪽 자료", output=deepcopy(output))
    state["results"].append(left)
    if condition != "foreign":
        state["results"].append(right)
    if condition == "failed":
        right["outcome"] = "failure"
    elif condition == "selection":
        right["decision"] = "selection"
    elif condition == "rejected":
        state["results"].append(
            record(
                "act",
                "verification",
                "거부",
                output={
                    "call_id": right["id"],
                    "accepted": False,
                },
            )
        )
    source_id = {
        "missing": "missing",
        "derived": output["data"]["reference"]["id"],
        "malformed": [],
        "inline_only": None,
    }.get(condition, right["id"])
    operation = {
        "operation": "join",
        "right_result_id": source_id,
        "keys": ["period_start", "adm_cd10"],
        "how": "left",
        "fields": {"bh_score": "other_score"},
    }
    if condition.startswith("inline"):
        operation["right"] = output["data"]
        if condition == "inline_only":
            del operation["right_result_id"]
    original = deepcopy(state["results"])
    model = ScriptedModel(
        [
            selection(
                "process_data",
                {
                    "input_result_id": left["id"],
                    "operations": [
                        {"operation": "filter", "conditions": []},
                        operation,
                    ],
                },
            )
        ]
    )
    await build_nodes(model, providers, catalog, role="report")["act"](state, {})
    failure = state["results"][-1]
    assert failure["outcome"] == "failure"
    assert failure["output"]["code"] == "invalid_data_reference"
    available = [left["id"]]
    if condition not in {"foreign", "failed", "selection", "rejected"}:
        available.append(right["id"])
    assert failure["output"]["details"] == {
        "requested": source_id,
        "available": available,
        "operation_index": 1,
    }
    assert state["results"][: len(original)] == original


@pytest.mark.asyncio
async def test_join_retry_uses_restored_state_and_actual_right_columns(tmp_path):
    state, _, providers, catalog = prepared(tmp_path)
    queried = query_data({"target": "public.region_result"}, providers)
    left = record("act", "call", "원본 조회", output=queried)
    filtered = process_data(
        {
            "data": queried["data"],
            "operations": [
                {
                    "operation": "filter",
                    "conditions": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": "2025-12-01",
                        }
                    ],
                }
            ],
            "fields": ["adm_cd10", "bh_score"],
        }
    )
    right = record("act", "call", "오른쪽 가공 자료", output=filtered)
    state["results"].extend(
        [
            left,
            record("act", "call", "하위 결과", output={"results": [right]}),
        ]
    )
    state = state_adapter.validate_json(state_adapter.dump_json(state))
    original = deepcopy(state["results"])
    operations = [
        {
            "operation": "filter",
            "conditions": [
                {
                    "field": "period_start",
                    "operator": "eq",
                    "value": "2025-07-01",
                }
            ],
        },
        {
            "operation": "join",
            "right_result_id": right["id"],
            "keys": ["adm_cd10"],
            "how": "left",
            "fields": {"end_score": "bh_score"},
        },
        {
            "operation": "calculate",
            "method": "difference",
            "before": "bh_score",
            "after": "end_score",
            "output": "change",
        },
    ]
    arguments = {"input_result_id": left["id"], "operations": operations}

    def repair(messages):
        failure = section(messages, "작업 결과와 검증 이력")[-1]["output"]
        assert failure["code"] == "invalid_field"
        assert failure["details"] == {
            "requested": ["end_score"],
            "available": ["adm_cd10", "bh_score"],
            "operation_index": 1,
        }
        corrected = deepcopy(arguments)
        corrected["operations"][1]["fields"] = {"bh_score": "end_score"}
        return selection("process_data", corrected)

    model = ScriptedModel([selection("process_data", arguments), repair])
    nodes = build_nodes(model, providers, catalog, role="report")
    await nodes["act"](state, {})
    await nodes["act"](state, {})
    result = state["results"][-1]
    assert result["outcome"] == "success"
    assert result["output"]["data"]["rows"][0]["change"] == 5.0
    assert filtered["data"]["reference"] in result["output"]["data"]["inputs"]
    selected = result["action"]["arguments"]["operations"][1]
    assert selected["right_result_id"] == right["id"] and "right" not in selected
    assert result["output"]["operations"][1]["right"] == filtered["data"]
    assert state["results"][: len(original)] == original
    assert state["execution"]["budget"]["retries"]["used"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("filter_previous", [True, False])
async def test_month_comparison_preserves_periods_and_matches_each_dong(
    tmp_path, filter_previous
):
    state, data, providers, catalog = prepared(tmp_path)
    target = "analysis.bh_region_contribution"
    rows = data[target]["rows"]
    other_dong = "1168067000"
    rows.extend(
        row | {"adm_cd10": other_dong, "contribution": row["contribution"] + 100}
        for row in deepcopy(rows)
    )

    def compare(messages):
        left, right = section(messages, "가공 가능한 결과 ID와 열")
        operations = []
        if filter_previous:
            operations.append(
                {
                    "operation": "filter",
                    "conditions": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": "2025-11-01",
                        }
                    ],
                }
            )
        operations.extend(
            [
                {
                    "operation": "join",
                    "right_result_id": right,
                    "keys": ["adm_cd10", "indicator_cd"],
                    "how": "inner",
                    "fields": {
                        "period_start": "comparison_month",
                        "contribution": "comparison_contribution",
                    },
                },
                {
                    "operation": "calculate",
                    "method": "difference",
                    "before": "contribution",
                    "after": "comparison_contribution",
                    "output": "change",
                },
            ]
        )
        return selection(
            "process_data", {"input_result_id": left, "operations": operations}
        )

    model = ScriptedModel(
        [
            selection(
                "query_data",
                {
                    "target": target,
                    "filters": [
                        {"field": "period_start", "operator": op, "value": month}
                    ],
                },
            )
            for op, month in (("ge", "2025-11-01"), ("eq", "2025-12-01"))
        ]
        + [compare]
    )
    nodes = build_nodes(model, providers, catalog, role="report")
    await nodes["act"](state, {})
    await nodes["act"](state, {})
    original = deepcopy(state["results"])
    await nodes["act"](state, {})
    result = state["results"][-1]
    assert result["outcome"] == "success"
    compared = result["output"]["data"]["rows"]
    for dong, offset in ((BODY["dongCodes"][0], 0), (other_dong, 100)):
        actual = [row for row in compared if row["adm_cd10"] == dong]
        assert len(actual) == (2 if filter_previous else 4)
        previous = [row for row in actual if row["period_start"] == "2025-11-01"]
        assert {row["indicator_cd"]: row["change"] for row in previous} == {
            "SAMPLE_A": 1.0,
            "SAMPLE_B": 0.0,
        }
        assert {row["comparison_contribution"] for row in actual} == {
            15.0 + offset,
            20.0 + offset,
        }
        assert {row["comparison_month"] for row in actual} == {"2025-12-01"}
        if not filter_previous:
            # 여러 왼쪽 행의 결합은 합법이지만, 같은 달끼리의 차이는 전월 비교가 아니다.
            current = [row for row in actual if row["period_start"] == "2025-12-01"]
            assert len(current) == 2 and all(row["change"] == 0 for row in current)
    assert state["results"][: len(original)] == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,expected,excluded", [("anomaly_score", 3, 1), ("grid_cd", 4, 0)]
)
async def test_valid_grid_count_uses_score_presence(
    tmp_path, field, expected, excluded
):
    state, data, providers, catalog = prepared(tmp_path)
    target = "analysis.bh_grid_anomaly"
    data[target]["rows"][-1]["anomaly_score"] = None

    def count(messages):
        source_id = next(iter(section(messages, "가공 가능한 결과 ID와 열")))
        return selection(
            "process_data",
            {
                "input_result_id": source_id,
                "operations": [
                    {
                        "operation": "aggregate",
                        "method": "count",
                        "field": field,
                        "group_by": ["period_start", "adm_cd10"],
                        "output": "count",
                    }
                ],
                "missing": "drop",
            },
        )

    model = ScriptedModel(
        [
            selection(
                "query_data",
                {
                    "target": target,
                    "filters": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": "2025-12-01",
                        }
                    ],
                },
            ),
            count,
        ]
    )
    nodes = build_nodes(model, providers, catalog, role="report")
    await nodes["act"](state, {})
    await nodes["act"](state, {})
    result = state["results"][-1]
    assert result["outcome"] == "success"
    assert result["output"]["data"]["rows"] == [
        {
            "period_start": "2025-12-01",
            "adm_cd10": BODY["dongCodes"][0],
            "count": expected,
        }
    ]
    assert result["output"]["excluded_rows"] == excluded
    assert data[target]["rows"][-1]["anomaly_score"] is None


@pytest.mark.asyncio
async def test_real_query_process_report_and_file_save_flow(tmp_path):
    settings, _ = setup(tmp_path / "runs")
    db = FileReportDatabase(settings, tmp_path / "db")
    db.seed(BODY)
    states = create_report_states(BODY, settings)
    await db.prepare_report(states[0])

    def query(target, fields, month="2025-12-01"):
        def choose(messages):
            catalog = section(messages, "조회 가능한 자료 목록")
            assert all(field in catalog[target] for field in fields)
            return selection(
                "query_data",
                {
                    "target": target,
                    "fields": fields,
                    "filters": [
                        {
                            "field": "period_start",
                            "operator": "eq",
                            "value": month,
                        }
                    ],
                },
            )

        return choose

    def process(messages):
        ids = section(messages, "가공 가능한 결과 ID와 열")
        return selection(
            "process_data",
            {
                "input_result_id": list(ids)[-1],
                "operations": [
                    {
                        "operation": "join",
                        "right_result_id": list(ids)[0],
                        "keys": ["indicator_cd"],
                        "how": "left",
                        "fields": {"contribution": "previous"},
                    },
                    {
                        "operation": "calculate",
                        "method": "difference",
                        "before": "previous",
                        "after": "contribution",
                        "output": "change",
                    },
                    {
                        "operation": "sort",
                        "by": [{"field": "contribution", "descending": True}],
                    },
                ],
            },
        )

    def views(messages):
        records = json.loads(messages[1].content)["results"]
        calls = [
            r["id"]
            for r in records
            if r["decision"] == "call" and r["outcome"] == "success"
        ]
        return {
            "views": [
                {"view_key": key, "reason": "합성 근거", "evidence_ids": [ref]}
                for key, ref in zip(
                    ("EmbedDetailV02", "EmbedDetailV04", "EmbedDetailV08"),
                    calls[-3:],
                    strict=True,
                )
            ]
        }

    again = {"next": "act", "reason": "다음 근거"}
    review = {"accepted": True, "reason": "합성 근거 일치"}
    model = ScriptedModel(
        [
            query(
                "analysis.bh_region_contribution",
                ["indicator_cd", "contribution"],
                "2025-11-01",
            ),
            again,
            query("analysis.bh_region_contribution", ["indicator_cd", "contribution"]),
            again,
            process,
            again,
            query("analysis.flow_detail", ["dim_type", "dim_value", "activity_daily"]),
            again,
            query("analysis.bh_grid_anomaly", ["grid_cd", "anomaly_score"]),
            {"next": "compose", "reason": "근거 확보"},
            views,
            review,
            {"content": "합성 기여도 설명입니다."},
            review,
            {"content": "합성 활동량 설명입니다."},
            review,
            {"content": "합성 격자 설명입니다."},
            review,
            {"content": "합성 기여도입니다.\n합성 활동량입니다.\n합성 격자입니다."},
            review,
        ]
    )
    await execute_reports(states, database=db, model=model)
    state = states[0]
    assert state["execution"]["status"] == "completed", state["results"]
    assert db.read_reports() == [report_artifact(state)]
    assert state["execution"]["budget"]["retries"]["used"] == 0
    assert not any(r["outcome"] == "failure" for r in state["results"])
    processed = next(
        r
        for r in state["results"]
        if r["decision"] == "call" and r["action"]["name"] == "process_data"
    )
    assert {
        r["indicator_cd"]: r["change"] for r in processed["output"]["data"]["rows"]
    } == {
        "SAMPLE_A": 1.0,
        "SAMPLE_B": 0.0,
    }
    _, catalog = db.report_sources()
    for schema, messages in zip(model.schemas, model.inputs, strict=True):
        if schema == "Decision":
            assert section(messages, "조회 가능한 자료 목록") == catalog
            views = section(messages, "상세 뷰의 표현 범위")["views"]
            assert {"EmbedDetailV02", "EmbedDetailV04", "EmbedDetailV08"} <= set(views)
        elif schema in {"ReportSelection", "ReportText", "Verification"}:
            assert "[조회 가능한 자료 목록]" in messages[0].content
            assert catalog["public.region_result"] in messages[0].content
