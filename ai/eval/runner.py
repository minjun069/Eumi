"""기존 업무 실행과 로거로 단위 평가 증거를 저장한다. 채점은 수행하지 않는다."""

import asyncio
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Literal, NotRequired
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from typing_extensions import TypedDict

from eval.database import DatabaseIdentity, database_identity, verify_fixture
from eval.fixtures import FixtureSummary, StubCalls
from eval.naming import create_batch_folder, korea_timestamp
from eval.nodes.runner import run_model_output
from eval.provenance import code_hashes
from eval.scenario_input import ScenarioSelection
from eval.schema import (
    Case,
    DataSource,
    ProviderFailure,
    Suite,
    Unit,
    suite_adapter,
    validate_initial,
)
from src.agent_nodes import build_nodes, finish
from src.database import Database
from src.execution_trace import (
    ExecutionManifest,
    TraceRecorder,
    error_info,
    execution_manifest,
    recording,
    trace_output,
    trace_span,
    utc_now,
)
from src.gemini import create_model
from src.graph import compile_graph
from src.prompting import Role
from src.report_flow import run_report_flow
from src.runtime import execution_config
from src.settings import Settings
from src.state import State, create_state, state_adapter
from src.tools.data import Dataset
from src.tools.process import process_data
from src.tools.query import DataProvider, query_data
from src.tools.render import render_visualization
from src.tools.tableau import validate_visualization

RunStatus = Literal["running", "returned", "error", "cancelled"]


class AssessmentResult(TypedDict):
    verdict: Literal["미판정"]
    executed: Literal[False]
    reason: str
    checks: list[str]


class EvaluationConditions(TypedDict):
    suite_id: str
    data_source: DataSource
    database_fixture_sha256: str | None
    database: DatabaseIdentity | None
    suite_sha256: str
    source: str | None
    source_sha256: str | None
    runner_sha256: dict[str, str]
    source_files_sha256: NotRequired[dict[str, str]]
    source_selection: NotRequired[list[ScenarioSelection]]


class EvaluationManifest(ExecutionManifest):
    evaluation: EvaluationConditions


class RunInfo(TypedDict):
    id: str
    suite_id: str
    case_id: str
    repetition: int
    unit: Unit
    target: str
    role: Role | None
    dependencies: Literal["real", "stub"]
    evaluation_scope: Literal["model_output", "execution"]
    status: RunStatus
    started_at: str
    ended_at: str | None
    elapsed_seconds: float | None


class RunReport(TypedDict):
    schema_version: Literal["evaluation-run-v1"]
    run: RunInfo
    state: NotRequired[State]
    output: object
    failure: dict | None
    trace: dict
    assessment: AssessmentResult
    fixtures: FixtureSummary
    journal_saved: bool


class BatchRun(TypedDict):
    case_id: str
    run_id: str
    unit: Unit
    target: str
    repetition: int
    status: RunStatus
    path: str


class EvaluationPlan(TypedDict):
    case_ids: list[str]
    repeat: int


class BatchReport(TypedDict):
    schema_version: Literal["evaluation-batch-v1"]
    id: str
    suite_id: str
    status: RunStatus
    started_at: str
    ended_at: str | None
    planned_runs: int
    plan: EvaluationPlan
    runs: list[BatchRun]
    failure: NotRequired[dict]


class BatchContext(TypedDict):
    folder: Path
    writer: TraceRecorder
    batch: BatchReport


def load_suite(path: Path) -> Suite:
    return suite_adapter.validate_python(
        json.loads(path.read_text(encoding="utf-8-sig"))
    )


def prepare_state(case: Case, settings: Settings, run_id: str) -> State | None:
    if "initial" not in case:
        return None
    initial = validate_initial(case["initial"])
    state = create_state(
        initial["request"],
        settings,
        messages=initial["messages"],
        event=initial["event"],
        version=settings.version,
    )
    if "execution" in initial:
        state["execution"] = deepcopy(initial["execution"])
    state["execution"]["run_id"] = run_id
    for key in ("results", "response"):
        if key in initial:
            state[key] = deepcopy(initial[key])
    if "budget" in initial:
        state["execution"]["budget"] = deepcopy(initial["budget"])
    if "execution_error" in initial:
        state["execution"]["error"] = deepcopy(initial["execution_error"])
    return state_adapter.validate_python(state)


def _provider(data: Dataset, failure: ProviderFailure | None) -> DataProvider:
    """사례의 자료원 경계에서만 장애를 발생시키고 도구의 오류 처리는 유지한다."""
    error = {
        "PermissionError": PermissionError,
        "TimeoutError": TimeoutError,
        "ConnectionError": ConnectionError,
    }.get(failure)

    def provide():
        if error is not None:
            raise error()
        return deepcopy(data)

    return provide


def _sources(case: Case, suite: Suite, settings: Settings):
    if suite.get("data_source", "prepared") == "database":
        providers, catalog = Database(settings).report_sources()
        names = case.get("providers", list(providers))
        return (
            {name: providers[name] for name in names},
            {name: catalog[name] for name in names},
        )
    datasets = suite.get("datasets", {})
    names = case.get("providers", list(datasets))
    failures = case.get("provider_failures", {})
    providers = {name: _provider(datasets[name], failures.get(name)) for name in names}
    catalog = {
        name: deepcopy(
            suite.get("catalog", {}).get(
                name,
                {key: value for key, value in datasets[name].items() if key != "rows"},
            )
        )
        for name in names
    }
    return providers, catalog


def _tool(case, state, providers):
    arguments = deepcopy(case["arguments"])
    match case["target"]:
        case "query_data":
            return query_data(arguments, providers)
        case "process_data":
            return process_data(arguments)
        case "validate_visualization":
            return validate_visualization(arguments, state=state)
        case "render_visualization":
            return render_visualization(arguments)
    raise ValueError("Unknown tool")


def _manifest(
    settings, suite, source_path, *, source_files_sha256=None, source_selection=None
) -> EvaluationManifest:
    manifest = execution_manifest(settings)
    encoded = suite_adapter.dump_json(suite)
    conditions: EvaluationConditions = {
        "suite_id": suite["id"],
        "data_source": suite.get("data_source", "prepared"),
        "database_fixture_sha256": None,
        "database": None,
        "suite_sha256": sha256(encoded).hexdigest(),
        "source": str(source_path.resolve()) if source_path else None,
        "source_sha256": sha256(source_path.read_bytes()).hexdigest()
        if source_path
        else None,
        "runner_sha256": code_hashes(),
    }
    if source_files_sha256 is not None:
        conditions["source_files_sha256"] = deepcopy(source_files_sha256)
    if source_selection is not None:
        conditions["source_selection"] = deepcopy(source_selection)
    if conditions["data_source"] == "database":
        conditions["database"] = database_identity(settings)
        conditions["database_fixture_sha256"] = sha256(
            json.dumps(
                suite["database_fixture"],
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    return EvaluationManifest(**manifest, evaluation=conditions)


async def _attempt(case, suite, settings, folder, run_id, repetition, model, manifest):
    folder.mkdir(parents=True, exist_ok=False)
    recorder = TraceRecorder.from_settings(settings, journal=folder / "trace.jsonl")
    recorder.write_json(folder / "manifest.json", manifest, strict=True)
    recorder.write_json(folder / "case.json", case, strict=True)
    # 자료는 결과와 독립된 실행 입력이며 기대값은 모델/State에 전달하지 않는다.
    providers, catalog = _sources(case, suite, settings)
    state = prepare_state(case, settings, run_id)
    model_only = case["unit"] in {"node", "selection"}
    stubs = StubCalls([] if model_only else case.get("stubs", []))
    role = case["target"] if case["unit"] == "agent" else case.get("role")
    run = RunInfo(
        id=run_id,
        suite_id=suite["id"],
        case_id=case["id"],
        repetition=repetition,
        unit=case["unit"],
        target=case["target"],
        role=role,
        dependencies=case.get("dependencies", "real"),
        evaluation_scope="model_output" if model_only else "execution",
        status="running",
        started_at=utc_now(),
        ended_at=None,
        elapsed_seconds=None,
    )
    report = RunReport(
        schema_version="evaluation-run-v1",
        run=run,
        output=None,
        failure=None,
        trace={},
        fixtures=stubs.summary(),
        journal_saved=False,
        assessment={
            "verdict": "미판정",
            "executed": False,
            "reason": "실행 증거만 수집함. 자동 채점은 수행하지 않음.",
            "checks": case.get("assessment", {}).get("checks", []),
        },
    )
    started = monotonic()
    try:
        with (
            recording(recorder),
            trace_span(
                "evaluation",
                case["target"],
                {
                    "run": run,
                    "unit": case["unit"],
                    "role": role,
                    "dependencies": run["dependencies"],
                    "initial_state": state,
                    "arguments": case.get("arguments"),
                },
            ),
        ):
            if case["unit"] == "tool":
                # 로컬 동기 도구에는 새 비동기 취소·재시도 의미를 부여하지 않는다.
                report["output"] = _tool(case, state, providers)
            elif model_only:
                report["output"] = await run_model_output(
                    case,
                    state,
                    model,
                    providers,
                    catalog,
                    execution_config(run_id),
                    timeout_seconds=settings.llm_timeout,
                )
            else:
                callbacks = {}
                if run["dependencies"] == "stub":
                    callbacks = {
                        "tool_runner": stubs.tool,
                        "agent_runner": stubs.agent,
                        "renderer": stubs.renderer,
                    }
                if case["unit"] == "workflow":

                    async def preserve_progress(current, _node):
                        nonlocal state
                        state = state_adapter.validate_python(deepcopy(current))

                    with trace_span(
                        "execution", case["target"], {"initial_state": state}
                    ):
                        try:
                            state = await run_report_flow(
                                state,
                                model=model,
                                providers=providers,
                                catalog=catalog,
                                config=execution_config(run_id),
                                publish=preserve_progress,
                                **callbacks,
                            )
                        except BaseException:
                            trace_output({"observed_state": state})
                            raise
                        trace_output({"state": state})
                else:
                    nodes = build_nodes(
                        model, providers, catalog, role=role, **callbacks
                    )
                    graph = compile_graph(
                        nodes, finish=finish, checkpointer=InMemorySaver()
                    )
                    # 그래프 준비는 제외하고 진입부터 반환까지를 측정한다.
                    with trace_span(
                        "execution", case["target"], {"initial_state": state}
                    ):
                        try:
                            # 취소 시 결과 State에는 완료한 노드만 반영한다.
                            async for value in graph.astream(
                                state, execution_config(run_id), stream_mode="values"
                            ):
                                state = state_adapter.validate_python(
                                    {
                                        key: item
                                        for key, item in value.items()
                                        if key != "__interrupt__"
                                    }
                                )
                        except BaseException:
                            trace_output({"observed_state": state})
                            raise
                        trace_output({"state": state})
            run["status"] = "returned"
            trace_output({"output": report["output"], "state": state})
    except asyncio.CancelledError as exc:
        run["status"] = "cancelled"
        report["failure"] = error_info(exc)
        raise
    except Exception as exc:
        run["status"] = "error"
        report["failure"] = error_info(exc)
    finally:
        if stubs.unexpected:
            run["status"] = "error" if run["status"] != "cancelled" else "cancelled"
            report["failure"] = report["failure"] or {
                "type": "UnexpectedStubCall",
                "code": "unexpected_stub_call",
            }
        run["ended_at"] = utc_now()
        run["elapsed_seconds"] = round(monotonic() - started, 6)
        if state is not None:
            report["state"] = state
        report["trace"] = recorder.export()
        report["fixtures"] = stubs.summary()
        report["journal_saved"] = recorder.journal is not None
        recorder.write_json(folder / "report.json", report, strict=True)
    return report


def select_cases(
    suite: Suite, *, case_ids=None, unit: Unit | None = None, target: str | None = None
) -> list[Case]:
    ids = {case["id"] for case in suite["cases"]}
    if set(case_ids or []) - ids:
        raise ValueError("Unknown case IDs")
    cases = [
        case
        for case in suite["cases"]
        if (not case_ids or case["id"] in case_ids)
        and (unit is None or case["unit"] == unit)
        and (target is None or case["target"] == target)
    ]
    if not cases:
        raise ValueError("No cases selected")
    return cases


async def run_suite(
    suite: Suite,
    settings: Settings,
    output: Path,
    *,
    model=None,
    case_ids: list[str] | None = None,
    unit: Unit | None = None,
    target: str | None = None,
    repeat: int = 1,
    source_path: Path | None = None,
    source_files_sha256: dict[str, str] | None = None,
    source_selection: list[ScenarioSelection] | None = None,
) -> Path | list[Path]:
    """사례 순서를 유지하며 노드·에이전트별로 저장한다. 복수 묶음은 경로 목록이다."""
    suite = suite_adapter.validate_python(suite)
    if type(repeat) is not int or repeat < 1:
        raise ValueError("repeat must be a positive integer")
    cases = select_cases(suite, case_ids=case_ids, unit=unit, target=target)
    # 모든 초기 상태를 모델 생성·실행 전에 검사한다.
    for case in cases:
        prepare_state(case, settings, "validation-only")
    if suite.get("data_source", "prepared") == "database":
        if settings.database_url is None:
            raise ValueError("Database evaluation requires SETTINGS_DATABASE_URL")
        verify_fixture(settings, suite["database_fixture"])
    own_model = model is None and any(case["unit"] != "tool" for case in cases)
    started_at = korea_timestamp()
    groups: dict[str | None, list[Case]] = {}
    for case in cases:
        key = case["target"] if case["unit"] in {"node", "selection", "agent"} else None
        groups.setdefault(key, []).append(case)
    contexts: dict[str | None, BatchContext] = {}
    try:
        for key, selected in groups.items():
            folder = create_batch_folder(output, selected, started_at)
            writer = TraceRecorder.from_settings(settings)
            batch = BatchReport(
                schema_version="evaluation-batch-v1",
                id=folder.name,
                suite_id=suite["id"],
                status="running",
                started_at=started_at,
                ended_at=None,
                planned_runs=len(selected) * repeat,
                plan={"case_ids": [case["id"] for case in selected], "repeat": repeat},
                runs=[],
            )
            contexts[key] = BatchContext(folder=folder, writer=writer, batch=batch)
            writer.write_json(folder / "suite.json", suite, strict=True)
            writer.write_json(folder / "batch.json", batch, strict=True)
        manifest = _manifest(
            settings,
            suite,
            source_path,
            source_files_sha256=source_files_sha256,
            source_selection=source_selection,
        )
        if own_model:
            model = create_model(settings)
        for case in cases:
            key = (
                case["target"]
                if case["unit"] in {"node", "selection", "agent"}
                else None
            )
            context = contexts[key]
            folder, writer, batch = (
                context["folder"],
                context["writer"],
                context["batch"],
            )
            for repetition in range(1, repeat + 1):
                run_id = str(uuid4())
                relative = Path("runs") / run_id / "report.json"
                entry = BatchRun(
                    case_id=case["id"],
                    run_id=run_id,
                    unit=case["unit"],
                    target=case["target"],
                    repetition=repetition,
                    status="running",
                    path=relative.as_posix(),
                )
                batch["runs"].append(entry)
                writer.write_json(folder / "batch.json", batch, strict=True)
                try:
                    report = await _attempt(
                        case,
                        suite,
                        settings,
                        (folder / relative).parent,
                        run_id,
                        repetition,
                        model,
                        manifest,
                    )
                    entry["status"] = report["run"]["status"]
                except asyncio.CancelledError:
                    entry["status"] = "cancelled"
                    raise
                except Exception:
                    entry["status"] = "error"
                    raise
                finally:
                    writer.write_json(folder / "batch.json", batch, strict=True)
            if len(batch["runs"]) == batch["planned_runs"]:
                batch["status"] = (
                    "error"
                    if any(r["status"] == "error" for r in batch["runs"])
                    else "returned"
                )
                batch["ended_at"] = korea_timestamp()
                writer.write_json(folder / "batch.json", batch, strict=True)
    except asyncio.CancelledError as exc:
        for context in contexts.values():
            if context["batch"]["status"] == "running":
                context["batch"].update(status="cancelled", failure=error_info(exc))
        raise
    except Exception as exc:
        for context in contexts.values():
            if context["batch"]["status"] == "running":
                context["batch"].update(status="error", failure=error_info(exc))
        raise
    finally:
        save_error = None
        try:
            for context in contexts.values():
                batch = context["batch"]
                batch["ended_at"] = batch["ended_at"] or korea_timestamp()
                try:
                    context["writer"].write_json(
                        context["folder"] / "batch.json", batch, strict=True
                    )
                except OSError as exc:
                    save_error = save_error or exc
        finally:
            from eval.viewers.catalog import refresh_for

            if contexts:
                refresh_for(next(iter(contexts.values()))["folder"])
            if own_model and model is not None:
                await model.http_async_client.aclose()
        if save_error is not None:
            raise save_error
    folders = [context["folder"] for context in contexts.values()]
    return folders[0] if len(folders) == 1 else folders
