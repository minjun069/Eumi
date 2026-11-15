"""외부 모델·DB만 대체하여 보고서 실제 노드·도구·API 흐름을 검증한다."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from api import (
    create_app,
    create_report_states,
    execute_reports,
    start_month,
)
from experiments.report_roundtrip import FileReportDatabase
from src.database import Database, record_report_source
from src.settings import Settings
from src.state import report_artifact, report_input, state_adapter
from src.tools.data import read_dataset
from tests.api_fixtures import section
from tests.helpers import ScriptedModel, selection

BODY = {"requestId": "report-1", "month": "2025-12", "dongCodes": ["1168066000"]}


class ReportModel:
    def __init__(self, *, reject=None, fail_once=None, entered=None, release=None):
        self.calls = []
        self.reject = reject or {}
        self.fail_once = fail_once
        self.entered, self.release = entered, release
        self.review_failure = None
        self.duplicate_selection = False
        self.empty_selection = False
        self.quick_content = None
        self.forbidden_selection = None

    def bind_tools(self, *args, **kwargs):
        self.kwargs = {}
        return self

    def with_structured_output(self, schema, **kwargs):
        async def invoke(messages, config):
            kind = schema["title"]
            if kind in {"ReportSelection", "ReportText"} or (
                kind == "Verification" and messages[1].content.startswith("{")
            ):
                context = json.loads(messages[1].content)
                records = context["results"]
                current = records[-1]
                view = current["action"]["arguments"]["view_key"]
            else:
                records = (
                    section(messages, "작업 결과와 검증 이력")
                    if kind != "Verification"
                    else []
                )
                view = None
            self.calls.append((kind, view, deepcopy(messages)))
            if kind == "Selection":
                if self.entered:
                    self.entered.set()
                    await self.release.wait()
                value = {
                    "name": "query_data",
                    "arguments_json": '{"target":"public.region_result"}',
                    "reason": "월별 분석 결과 확인",
                }
                if self.forbidden_selection:
                    value = {
                        "name": self.forbidden_selection,
                        "arguments_json": '{"goal":"보고서 해석"}',
                        "reason": "허용 목록 위반 응답",
                    }
                    self.forbidden_selection = None
            elif kind == "Decision":
                available = any(
                    r["decision"] == "call" and r["outcome"] == "success"
                    for r in records
                )
                rejected = next(
                    (
                        r
                        for r in reversed(records)
                        if r["decision"] == "verification"
                        and (r["output"] or {}).get("accepted") is False
                    ),
                    None,
                )
                value = {
                    "next": "compose" if available else "act",
                    "reason": "월별 분석 결과가 필요하다."
                    if not available
                    else "추가 조회 없이 기존 근거로 검토 지적을 수정한다."
                    if rejected
                    else "근거 확보",
                }
            elif kind == "ReportSelection":
                evidence = next(r["id"] for r in records if r["decision"] == "call")
                value = {
                    "views": [
                        {
                            "view_key": key,
                            "reason": "검증 테스트용 선정",
                            "evidence_ids": [evidence],
                        }
                        for key in (
                            "EmbedDetailV01",
                            "EmbedDetailV02",
                            "EmbedDetailV08",
                        )
                    ]
                }
                if self.duplicate_selection:
                    value["views"][1] = deepcopy(value["views"][0])
                    self.duplicate_selection = False
                if self.empty_selection:
                    value["views"] = []
            elif kind == "ReportText":
                if self.fail_once is not None and self.fail_once == view:
                    self.fail_once = "used"
                    raise ConnectionError("temporary model error")
                value = {
                    "content": "확보한 점수의 변화입니다."
                    if view
                    else "첫째 근거입니다.\n둘째 근거입니다.\n셋째 근거입니다."
                }
                if view is None and self.quick_content is not None:
                    value["content"] = self.quick_content
            elif kind == "Verification":
                assert messages[1].content.startswith("{")
                assert current["node"] == "compose"
                if self.review_failure is not None and self.review_failure == view:
                    self.review_failure = None
                    raise ConnectionError("review unavailable")
                rejected = bool(view and self.reject.get(view, 0))
                if rejected:
                    self.reject[view] -= 1
                value = {
                    "accepted": not rejected,
                    "reason": "비교 기간을 바로잡아야 합니다."
                    if rejected
                    else "근거 일치",
                }
            else:
                raise AssertionError(kind)
            return {"raw": AIMessage(json.dumps(value, ensure_ascii=False))}

        return RunnableLambda(invoke)


class ReportDatabase(Database):
    def __init__(self, settings, *, save_failures=0):
        super().__init__(settings)
        self.save_failures = save_failures
        self.saved = []
        self.attempts = []

    def region_results(self):
        return read_dataset(
            {
                "reference": {"id": "public.region_result", "version": "test"},
                "as_of": "2025-12-15",
                "sources": [{"label": "합성 자료", "uri": "test://scores"}],
                "columns": [
                    {
                        "name": "bh_score",
                        "kind": "number",
                        "unit": "점수",
                        "spatial_unit": "행정동",
                        "temporal_unit": "월",
                        "denominator": "해당 없음",
                    }
                ],
                "rows": [{"bh_score": 42.0}],
            }
        )

    async def prepare_report(self, state):
        args = report_input(state)
        record_report_source(
            state,
            {
                "period_start": args["month"] + "-01",
                "adm_cd10": args["dongCode"],
                "updated_at": "2025-12-15T00:00:00",
            },
        )

    async def save_report(self, state):
        self.attempts.append(deepcopy(report_artifact(state)))
        if self.save_failures:
            self.save_failures -= 1
            raise ConnectionError("test DB error")
        self.saved.append(deepcopy(report_artifact(state)))


def setup(tmp_path, **kwargs):
    config = Settings(
        _env_file=None,
        output_dir=tmp_path,
        max_steps=100,
        max_tool_retries=30,
        runtime_timeout=120,
        langfuse_enabled=False,
        backend_url="http://backend.test",
        backend_token="test-token",
    )
    return config, ReportDatabase(config, **kwargs)


async def generate(tmp_path, model, **db_options):
    settings, db = setup(tmp_path, **db_options)
    states = create_report_states(BODY, settings)
    await db.prepare_report(states[0])
    await execute_reports(states, database=db, model=model)
    return states[0], db


def test_month_window(tmp_path):
    assert start_month("2025-12") == "2025-07"
    assert start_month("2026-03") == "2025-10"
    settings, _ = setup(tmp_path)
    state = create_report_states(BODY, settings)[0]
    assert not state["messages"]


@pytest.mark.asyncio
async def test_three_stages_review_feedback_and_save_only_retry(tmp_path):
    model = ReportModel(reject={"EmbedDetailV01": 1})
    state, db = await generate(tmp_path, model, save_failures=2)
    assert state["execution"]["status"] == "completed"
    assert len(db.saved) == 1 and len(db.attempts) == 3
    assert db.attempts[0] == db.attempts[1] == db.attempts[2]
    writes = [c for c in model.calls if c[0] == "ReportText"]
    assert [c[1] for c in writes] == [
        "EmbedDetailV01",
        "EmbedDetailV01",
        "EmbedDetailV02",
        "EmbedDetailV08",
        None,
    ]
    assert "비교 기간을 바로잡아야 합니다." in writes[1][2][1].content
    row = report_artifact(state)
    assert row["result_updated_at"] == "2025-12-15T00:00:00"
    assert len(row["quick_insight"].splitlines()) == 3
    assert state["execution"]["budget"]["retries"]["used"] == 3
    assert (tmp_path / state["execution"]["run_id"] / "report.json").exists()
    report = json.loads(
        (tmp_path / state["execution"]["run_id"] / "report.json").read_text(
            encoding="utf-8"
        )
    )
    spans = report["trace"]["spans"]
    assert report["trace"]["coverage"]["unfinished_spans"] == 0
    models = [s for s in spans if s["kind"] == "model"]
    assert len(models) == len(model.calls)
    assert all(s["input"]["messages"] and s["output"]["sdk_response"] for s in models)
    assert any(s["kind"] == "provider" and s["output"]["rows"] for s in spans)
    assert [s["status"] for s in spans if s["name"] == "save_report"] == [
        "error",
        "error",
        "success",
    ]
    assert (tmp_path / state["execution"]["run_id"] / "report.html").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["interpretation_agent", "visualization_agent"])
async def test_forbidden_selection_uses_existing_retry_without_calling_child(
    tmp_path, name
):
    model = ReportModel()
    model.forbidden_selection = name
    state, db = await generate(tmp_path, model)
    assert state["execution"]["status"] == "completed"
    assert len(db.saved) == 1
    assert [
        r["output"]["error_type"]
        for r in state["results"]
        if r["decision"] == "execution_failed"
    ] == ["ValidationError"]
    assert state["execution"]["budget"]["agent_calls"]["used"] == 0
    assert state["execution"]["budget"]["retries"]["used"] == 1
    assert all(r["action"]["name"] != name for r in state["results"] if r["action"])
    assert len([c for c in model.calls if c[0] == "Selection"]) == 2
    assert len([c for c in model.calls if c[0] == "ReportText"]) == 4


@pytest.mark.asyncio
async def test_three_revisions_then_null_preserves_other_descriptions(tmp_path):
    model = ReportModel(reject={"EmbedDetailV02": 99})
    state, db = await generate(tmp_path, model)
    assert (
        len([c for c in model.calls if c[:2] == ("ReportText", "EmbedDetailV02")]) == 4
    )
    assert db.saved[0]["desc_2"] is None
    assert db.saved[0]["desc_1"] and db.saved[0]["desc_3"]
    assert state["execution"]["status"] == "partial"
    assert not any(r["decision"] == "report_retry" for r in state["results"])


@pytest.mark.asyncio
async def test_transient_description_failure_retries_only_failed_stage(tmp_path):
    model = ReportModel(fail_once="EmbedDetailV02")
    state, db = await generate(tmp_path, model)
    writes = [c[1] for c in model.calls if c[0] == "ReportText"]
    assert writes == [
        "EmbedDetailV01",
        "EmbedDetailV02",
        "EmbedDetailV02",
        "EmbedDetailV08",
        None,
    ]
    assert len([c for c in model.calls if c[0] == "ReportSelection"]) == 1
    assert db.saved and state["execution"]["status"] == "completed"
    assert state["execution"]["budget"]["retries"]["used"] == 1


@pytest.mark.asyncio
async def test_review_failure_preserves_draft_and_retries_review(tmp_path):
    model = ReportModel()
    model.review_failure = "EmbedDetailV02"
    state, db = await generate(tmp_path, model)
    assert (
        len([c for c in model.calls if c[:2] == ("ReportText", "EmbedDetailV02")]) == 1
    )
    assert (
        len([c for c in model.calls if c[:2] == ("Verification", "EmbedDetailV02")])
        == 2
    )
    assert db.saved[0]["desc_2"]
    assert state["execution"]["budget"]["retries"]["used"] == 1


@pytest.mark.asyncio
async def test_duplicate_selection_never_reaches_writing_before_reselection(tmp_path):
    model = ReportModel()
    model.duplicate_selection = True
    state, db = await generate(tmp_path, model)
    sequence = [c[0] for c in model.calls]
    assert sequence[: sequence.index("ReportText")].count("ReportSelection") == 2
    assert len({db.saved[0][f"graph_{n}"] for n in range(1, 4)}) == 3
    assert state["execution"]["budget"]["retries"]["used"] == 1


@pytest.mark.asyncio
async def test_long_report_reselects_supported_scope_and_saves_partial(
    tmp_path, monkeypatch
):
    for name in ("MAX_STEPS", "MAX_TOOL_CALLS", "RUNTIME_TIMEOUT"):
        monkeypatch.delenv(f"SETTINGS_{name}", raising=False)
    settings = Settings(
        _env_file=None, output_dir=tmp_path / "runs", langfuse_enabled=False
    )
    db = FileReportDatabase(settings, tmp_path / "db")
    db.seed(BODY)
    states = create_report_states(BODY, settings)
    await db.prepare_report(states[0])
    states = [state_adapter.validate_json(state_adapter.dump_json(states[0]))]
    scope = "해당 동의 6개월 추이만 설명하고 도시 비교는 제외한다."
    rejection = f"도시 비교와 전월 기여도 차이의 근거가 없다. {scope}"

    def choose_views(messages, *, limited=False):
        records = json.loads(messages[1].content)["results"]
        if limited:
            assert any(r["reason"] == rejection for r in records)
            assert any(
                r["decision"] == "decision"
                and r["output"]["next"] == "compose"
                and r["reason"] == scope
                for r in records
            )
        calls = [r for r in records if r["decision"] == "call"]
        assert {
            row["period_start"]
            for call in calls[:6]
            for row in call["output"]["data"]["rows"]
        } == {f"2025-{month:02d}-01" for month in range(7, 13)}
        return {
            "views": [
                {
                    "view_key": "EmbedDetailV01",
                    "reason": scope
                    if limited
                    else "동 추이와 도시 중앙 범위를 비교한다.",
                    "evidence_ids": [r["id"] for r in calls[:6]],
                },
                {
                    "view_key": "EmbedDetailV02",
                    "reason": "요청 월 구성만 설명하고 전월 변화는 제외한다."
                    if limited
                    else "기여도 구성과 전월 변화를 설명한다.",
                    "evidence_ids": [calls[-1]["id"]],
                },
            ]
        }

    replies = [{"next": "act", "reason": "후보 뷰의 기간별 근거 필요"}]
    for target, months in (
        ("public.region_result", range(7, 13)),
        ("analysis.bh_region_contribution", range(8, 13)),
    ):
        for month in months:
            replies.extend(
                [
                    selection(
                        "query_data",
                        {
                            "target": target,
                            "filters": [
                                {
                                    "field": "adm_cd10",
                                    "operator": "eq",
                                    "value": BODY["dongCodes"][0],
                                },
                                {
                                    "field": "period_start",
                                    "operator": "eq",
                                    "value": f"2025-{month:02d}-01",
                                },
                            ],
                        },
                    ),
                    {"next": "act", "reason": "후보 뷰의 기간별 근거 확보"},
                ]
            )
    replies[-1] = {"next": "compose", "reason": "조회된 근거로 선정 검토"}
    review = {"accepted": True, "reason": "선정된 설명 범위와 근거 일치"}
    replies.extend(
        [
            choose_views,
            {"accepted": False, "reason": rejection},
            {"next": "compose", "reason": scope},
            lambda messages: choose_views(messages, limited=True),
            review,
            {
                "content": "시연용 예시 데이터의 동 점수는 7월 30점, 12월 35점입니다. "
                "도시 비교는 제외했습니다."
            },
            review,
            {
                "content": "시연용 예시 데이터의 12월 기여도는 "
                "SAMPLE_A 15, SAMPLE_B 20입니다. 전월 변화는 제외했습니다."
            },
            review,
            {
                "content": "시연용 예시 데이터의 동 점수는 7월 30점, 12월 35점입니다.\n"
                "12월 기여도는 SAMPLE_A 15, SAMPLE_B 20입니다.\n"
                "도시 비교와 전월 기여도 변화는 설명 범위에서 제외했습니다."
            },
            review,
        ]
    )
    model = ScriptedModel(replies)
    await execute_reports(states, database=db, model=model)

    state = states[0]
    assert state["execution"]["status"] == "partial", state["results"]
    budget = state["execution"]["budget"]
    assert {
        key: budget[key]["limit"] for key in ("steps", "tool_calls", "active_seconds")
    } == {"steps": 50, "tool_calls": 30, "active_seconds": 300}
    assert 20 < budget["steps"]["used"] < budget["steps"]["limit"]
    assert budget["tool_calls"]["used"] == 11
    assert budget["retries"]["used"] == 1
    assert state["execution"]["error"]["code"] == "incomplete"
    assert not any(r["outcome"] == "failure" for r in state["results"])
    row = report_artifact(state)
    assert db.read_reports() == [row]
    assert [row[f"graph_{n}"] for n in range(1, 4)] == [
        "EmbedDetailV01",
        "EmbedDetailV02",
        None,
    ]
    assert row["desc_1"] and row["desc_2"] and row["quick_insight"]
    assert row["desc_3"] is None
    assert model.schemas[-11:] == [
        "ReportSelection",
        "Verification",
        "Decision",
        "ReportSelection",
        "Verification",
        "ReportText",
        "Verification",
        "ReportText",
        "Verification",
        "ReportText",
        "Verification",
    ]
    records = section(model.inputs[-9], "작업 결과와 검증 이력")
    assert any(r["reason"] == rejection for r in records)
    assert records[-1]["reason"] == rejection
    for messages in model.inputs[-7:]:
        records = json.loads(messages[1].content)["results"]
        selected = next(
            r for r in reversed(records) if r["decision"] == "report_selection"
        )
        assert selected["output"]["views"][0]["reason"] == scope


@pytest.mark.asyncio
async def test_invalid_quick_insight_format_cannot_be_accepted(tmp_path):
    model = ReportModel()
    model.quick_content = "한 문장뿐입니다."
    state, db = await generate(tmp_path, model)
    assert len([c for c in model.calls if c[:2] == ("ReportText", None)]) == 4
    assert db.saved[0]["quick_insight"] is None
    assert state["execution"]["status"] == "partial"


@pytest.mark.asyncio
async def test_empty_evidence_selection_stores_nulls_without_inventing_text(tmp_path):
    model = ReportModel()
    model.empty_selection = True
    state, db = await generate(tmp_path, model)
    assert not any(c[0] == "ReportText" for c in model.calls)
    assert all(
        db.saved[0][f"{key}_{n}"] is None
        for n in range(1, 4)
        for key in ("graph", "desc")
    )
    assert db.saved[0]["quick_insight"] is None
    assert state["execution"]["status"] == "failed"


@pytest.mark.asyncio
async def test_failed_save_does_not_regenerate_or_lose_artifact(tmp_path):
    model = ReportModel()
    state, db = await generate(tmp_path, model, save_failures=99)
    assert len(db.attempts) == 3 and not db.saved
    assert state["execution"]["error"]["code"] == "report_save_failed"
    assert report_artifact(state) == db.attempts[0]
    assert len([c for c in model.calls if c[0] == "ReportText"]) == 4


@pytest.mark.asyncio
async def test_api_accepts_concurrent_requests_and_notifies_committed_counts(tmp_path):
    settings, db = setup(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    model = ReportModel(entered=entered, release=release)
    app = create_app(settings, database=db, model=model)
    received = []

    async def receive(request):
        received.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-token"
        assert db.saved
        return httpx.Response(204)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.MockTransport(receive)) as backend,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        app.state.client = backend
        for request_id in ("first", "second"):
            result = await client.post(
                "/internal/insight-reports/runs", json=BODY | {"requestId": request_id}
            )
            assert result.status_code == 202 and not result.content
        await asyncio.wait_for(entered.wait(), 2)
        tasks = list(app.state.report_tasks)
        release.set()
        await asyncio.gather(*tasks)
    assert len(db.saved) == 2
    assert {r["requestId"] for r in received} == {"first", "second"}
    assert all(r["savedCount"] == 1 and not r["failedDongCodes"] for r in received)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"month": "2025-13"},
        {"dongCodes": []},
        {"dongCodes": ["x"]},
        {"dongCodes": ["1168066000", "1168066000"]},
        {"requestId": " "},
        {"unexpected": "value"},
    ],
)
async def test_api_rejects_bad_input_before_execution(tmp_path, change):
    settings, db = setup(tmp_path)
    app = create_app(settings, database=db, model=ReportModel())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        result = await client.post("/internal/insight-reports/runs", json=BODY | change)
        assert result.status_code == 400
        assert not result.content
        assert not app.state.report_tasks and not db.attempts


@pytest.mark.asyncio
async def test_report_prepare_failure_is_reported_after_202(tmp_path):
    settings, db = setup(tmp_path)

    async def unavailable(state):
        raise ConnectionError("DB unavailable")

    db.prepare_report = unavailable
    app = create_app(settings, database=db, model=ReportModel())
    received = []

    async def receive(request):
        received.append(json.loads(request.content))
        return httpx.Response(204)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.MockTransport(receive)) as backend,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client,
    ):
        app.state.client = backend
        result = await client.post("/internal/insight-reports/runs", json=BODY)
        assert result.status_code == 202
        await asyncio.gather(*list(app.state.report_tasks))
    assert received == [
        {
            "requestId": BODY["requestId"],
            "month": BODY["month"],
            "savedCount": 0,
            "failedDongCodes": BODY["dongCodes"],
        }
    ]


@pytest.mark.asyncio
async def test_one_dong_save_failure_preserves_other_dong_and_state_isolation(tmp_path):
    settings, db = setup(tmp_path)
    states = create_report_states(
        BODY | {"dongCodes": ["1168066000", "1168064000"]}, settings
    )
    await asyncio.gather(*(db.prepare_report(state) for state in states))
    original = db.save_report

    async def save_with_failure(state):
        if report_input(state)["dongCode"] == "1168064000":
            raise ConnectionError("one dong unavailable")
        await original(state)

    db.save_report = save_with_failure
    await execute_reports(states, database=db, model=ReportModel())
    assert [s["execution"]["status"] for s in states] == ["completed", "failed"]
    assert [r["adm_cd10"] for r in db.saved] == ["1168066000"]
    assert states[0]["execution"]["budget"]["retries"]["used"] == 0
    assert states[1]["execution"]["budget"]["retries"]["used"] == 2
    assert not (
        {r["id"] for r in states[0]["results"]}
        & {r["id"] for r in states[1]["results"]}
    )
    for state in states:
        report = json.loads(
            (tmp_path / state["execution"]["run_id"] / "report.json").read_text(
                encoding="utf-8"
            )
        )
        attempts = [s for s in report["trace"]["spans"] if s["name"] == "api.report"]
        assert all(
            report_input(s["input"]["initial_state"])["dongCode"]
            == report_input(state)["dongCode"]
            for s in attempts
        )


@pytest.mark.asyncio
async def test_global_budget_stops_revisions_and_preserves_verified_parts(tmp_path):
    settings, db = setup(tmp_path)
    states = create_report_states(BODY, settings)
    states[0]["execution"]["budget"]["retries"]["limit"] = 1
    await db.prepare_report(states[0])
    await execute_reports(
        states, database=db, model=ReportModel(reject={"EmbedDetailV02": 99})
    )
    assert db.saved[0]["desc_1"] and db.saved[0]["desc_2"] is None
    assert states[0]["execution"]["budget"]["retries"]["used"] == 1
    assert states[0]["execution"]["status"] == "partial"
