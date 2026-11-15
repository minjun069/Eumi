"""평가 입력 양식. 기대 결과는 실행 입력과 분리하며 업무 State를 확장하지 않는다."""

import json
from typing import Annotated, Literal, NotRequired

from langchain_core.messages import AnyMessage
from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    with_config,
)
from typing_extensions import TypedDict

from eval.database import validate_fixture
from eval.execution.schema import (
    ExecutionExpectations,
    ExecutionPrices,
    PerformanceGoal,
    validate_execution_assessment,
    validate_execution_suite,
)
from eval.nodes.schema import (
    NodeExpectations,
    NodePerformanceTarget,
    validate_node_assessment,
)
from eval.tools.assessment import (
    TOOL_TARGETS,
    PerformanceTarget,
    ToolExpectations,
    validate_assessment,
)
from src.agent_nodes import ReportStage
from src.database import REPORT_SOURCES
from src.exceptions import ToolFailure
from src.prompting import REPORT_ROLES, Role
from src.state import (
    Budget,
    Error,
    Execution,
    ExecutionEvent,
    Request,
    Response,
    ResultItem,
    Text,
    report_input_adapter,
)
from src.tools.data import Dataset, read_dataset

ToolName = Literal[
    "query_data", "process_data", "validate_visualization", "render_visualization"
]
NodeName = Literal["interpret", "act", "decide", "compose", "ask"]
Unit = Literal["tool", "node", "selection", "agent", "workflow"]
JsonObject = dict[str, JsonValue]
Identifier = Annotated[
    str, Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
]
PositiveInt = Annotated[int, Field(ge=1, strict=True)]
DataSource = Literal["prepared", "database"]
ProviderFailure = Literal["PermissionError", "TimeoutError", "ConnectionError"]
TOOLS = set(ToolName.__args__)
NODES = set(NodeName.__args__)
ROLES = set(Role.__args__)


def argument_key(arguments: JsonObject) -> str:
    """객체 키 순서를 무시하되 bool/숫자 등 JSON 값의 종류를 구분한다."""
    return json.dumps(arguments, sort_keys=True, ensure_ascii=False, allow_nan=False)


@with_config(ConfigDict(extra="forbid"))
class InitialInput(TypedDict):
    request: Request
    event: ExecutionEvent
    messages: list[AnyMessage]
    results: NotRequired[list[ResultItem]]
    response: NotRequired[Response | None]
    budget: NotRequired[Budget]
    execution_error: NotRequired[Error | None]
    execution: NotRequired[Execution]


def validate_initial(initial: InitialInput) -> InitialInput:
    execution = initial.get("execution")
    if execution is not None:
        if execution["event"] != initial["event"]:
            raise ValueError("initial.event must match initial.execution.event")
        if "budget" in initial or "execution_error" in initial:
            raise ValueError(
                "initial.execution cannot be combined with budget/execution_error"
            )
    return initial


@with_config(ConfigDict(extra="forbid"))
class Assessment(TypedDict, total=False):
    reference: JsonValue
    expected: ToolExpectations | NodeExpectations | ExecutionExpectations | JsonValue
    tolerance: JsonValue
    checks: list[Text]
    required: bool


@with_config(ConfigDict(extra="forbid"))
class StubError(TypedDict):
    code: Text
    details: NotRequired[JsonObject]
    retryable: NotRequired[bool]


@with_config(ConfigDict(extra="forbid"))
class AgentReply(TypedDict):
    response: Response | None
    results: list[ResultItem]
    status: Literal["completed", "partial", "failed", "waiting_input", "cancelled"]
    error: Error | None


agent_reply_adapter = TypeAdapter(AgentReply)


@with_config(ConfigDict(extra="forbid"))
class Stub(TypedDict):
    name: Text
    arguments: JsonObject
    output: NotRequired[JsonObject]
    error: NotRequired[StubError]
    uses: NotRequired[PositiveInt]


def validate_stub(stub: Stub) -> Stub:
    if stub["name"] not in TOOLS | {"interpretation_agent", "visualization_agent"}:
        raise ValueError("Unknown stub target")
    if ("output" in stub) == ("error" in stub):
        raise ValueError("A stub requires exactly one of output or error")
    if stub["name"].endswith("_agent") and "output" in stub:
        agent_reply_adapter.validate_python(stub["output"])
    return stub


@with_config(ConfigDict(extra="forbid"))
class Case(TypedDict):
    id: Identifier
    unit: Unit
    target: Text
    purpose: Text
    role: NotRequired[Role]
    model_call: NotRequired[ReportStage]
    initial: NotRequired[Annotated[InitialInput, AfterValidator(validate_initial)]]
    arguments: NotRequired[JsonObject]
    providers: NotRequired[list[Text]]
    provider_failures: NotRequired[dict[Text, ProviderFailure]]
    dependencies: NotRequired[Literal["real", "stub"]]
    stubs: NotRequired[list[Annotated[Stub, AfterValidator(validate_stub)]]]
    assessment: NotRequired[Assessment]
    tags: NotRequired[list[Text]]


def validate_case(case: Case) -> Case:
    unit, target = case["unit"], case["target"]
    validate_execution_assessment(case)
    targets = {
        "tool": TOOLS,
        "node": NODES,
        "selection": {"act"},
        "agent": ROLES,
        "workflow": {"report"},
    }
    if target not in targets[unit]:
        raise ValueError(f"Unknown {unit} target: {target}")
    if "model_call" in case and not (
        unit == "node" and target == "compose" and case.get("role") in REPORT_ROLES
    ):
        raise ValueError("model_call selects a report compose model call only")
    if "model_call" in case:
        stage = case["model_call"]
        selection_stage = stage in {"selection", "selection_review"}
        if selection_stage != (case["role"] == "report_selection"):
            raise ValueError("model_call must match the report role")
    if unit == "tool" and target in TOOL_TARGETS:
        validate_assessment(case.get("assessment", {}))
    if unit == "tool":
        if "arguments" not in case:
            raise ValueError("Tool execution requires arguments")
        if "role" in case or case.get("dependencies", "real") != "real":
            raise ValueError("The evaluated tool must use its real implementation")
        if target == "validate_visualization" and "initial" not in case:
            raise ValueError("Tableau validation requires initial.event via initial")
    else:
        validate_node_assessment(case.get("assessment", {}))
        if "initial" not in case or "arguments" in case:
            raise ValueError(
                "Node/selection/agent/workflow requires initial, not arguments"
            )
        if unit in {"node", "selection"} and "role" not in case:
            raise ValueError("Node/selection requires an agent role")
        if unit in {"agent", "workflow"} and "role" in case:
            raise ValueError("Agent/workflow execution does not accept a role")
    if case.get("stubs") and (
        case.get("dependencies", "real") != "stub" or unit in {"tool", "selection"}
    ):
        raise ValueError(
            "Stubs apply only to node/agent/workflow with dependencies=stub"
        )
    if unit == "selection" and case.get("dependencies", "real") != "real":
        raise ValueError("Selection executes no dependencies; omit dependencies")
    if len(case.get("providers", [])) != len(set(case.get("providers", []))):
        raise ValueError("Duplicate provider names")
    signatures = [
        (s["name"], argument_key(s["arguments"])) for s in case.get("stubs", [])
    ]
    for i, signature in enumerate(signatures):
        if signature in signatures[:i]:
            raise ValueError("Duplicate stub match; increase uses instead")
    role = target if unit == "agent" else case.get("role")
    if role in REPORT_ROLES or unit == "workflow":
        initial = case["initial"]
        records = initial.get("results", [])
        inputs = next(
            (r["output"] for r in records if r["decision"] == "report_input"), None
        )
        source = next(
            (r["output"] for r in records if r["decision"] == "report_source"), None
        )
        if initial["event"] != "analysis_pipeline":
            raise ValueError("Report generation requires analysis_pipeline")
        report_input_adapter.validate_python(inputs)
        if not source or not isinstance(source.get("updated_at"), str):
            raise ValueError("Report generation requires report_source.updated_at")
    return case


case_adapter = TypeAdapter(Annotated[Case, AfterValidator(validate_case)])


@with_config(ConfigDict(extra="forbid"))
class Suite(TypedDict):
    schema_version: Literal["evaluation-suite-v1"]
    id: Identifier
    data_source: NotRequired[DataSource]
    database_fixture: NotRequired[dict[Text, list[JsonObject]]]
    datasets: NotRequired[dict[Text, Dataset]]
    catalog: NotRequired[JsonObject]
    cases: list[Annotated[Case, AfterValidator(validate_case)]]
    performance: NotRequired[list[PerformanceTarget]]
    node_performance: NotRequired[list[NodePerformanceTarget]]
    execution_performance: NotRequired[list[PerformanceGoal]]
    execution_prices: NotRequired[ExecutionPrices]


def validate_suite(suite: Suite) -> Suite:
    validate_execution_suite(suite)
    ids = [case["id"] for case in suite["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case IDs")
    database = suite.get("data_source", "prepared") == "database"
    if database:
        if "datasets" in suite or "catalog" in suite:
            raise ValueError("Database suites cannot include datasets or catalog")
        if "database_fixture" not in suite:
            raise ValueError("Database suites require database_fixture")
        validate_fixture(suite["database_fixture"])
    elif "database_fixture" in suite:
        raise ValueError("database_fixture requires data_source=database")
    datasets = suite.get("datasets", {})
    for name, dataset in datasets.items():
        try:
            read_dataset(dataset)
        except ToolFailure as exc:
            raise ValueError(f"Invalid dataset: {name}") from exc
        if dataset["reference"]["id"] != name:
            raise ValueError("Dataset key must match its reference.id")
    registered = (
        {"public.region_result", *REPORT_SOURCES} if database else set(datasets)
    )
    for case in suite["cases"]:
        provided = set(case.get("providers", registered))
        if provided - registered:
            raise ValueError(f"Unknown provider in case {case['id']}")
        if database and "provider_failures" in case:
            raise ValueError("Database cases cannot include provider_failures")
        if set(case.get("provider_failures", {})) - provided:
            raise ValueError(
                f"Provider failure requires a provided dataset in case {case['id']}"
            )
    if set(suite.get("catalog", {})) - datasets.keys():
        raise ValueError("Catalog keys must identify prepared datasets")
    cases = {case["id"]: case for case in suite["cases"]}
    performance_keys = set()
    for goal in suite.get("performance", []):
        key = (goal["target"], goal["group"])
        if key in performance_keys:
            raise ValueError("Duplicate performance target and group")
        performance_keys.add(key)
        if len(goal["case_ids"]) != len(set(goal["case_ids"])):
            raise ValueError("Duplicate performance case IDs")
        for case_id in goal["case_ids"]:
            case = cases.get(case_id)
            if (
                case is None
                or case["unit"] != "tool"
                or case["target"] != goal["target"]
            ):
                raise ValueError("Performance cases must identify the target tool")
    node_goals = set()
    for goal in suite.get("node_performance", []):
        key = (goal["target"], goal["role"], goal["metric"], goal.get("group"))
        if key in node_goals:
            raise ValueError("Duplicate node performance target")
        node_goals.add(key)
        if len(goal["case_ids"]) != len(set(goal["case_ids"])):
            raise ValueError("Duplicate node performance case IDs")
        for case_id in goal["case_ids"]:
            case = cases.get(case_id)
            if case is None or case["unit"] in {"tool", "selection"}:
                raise ValueError("Node performance requires node/agent/workflow cases")
            if case["unit"] == "node" and (
                case["target"] != goal["target"] or case["role"] != goal["role"]
            ):
                raise ValueError("Node performance case target and role differ")
    return suite


suite_adapter = TypeAdapter(Annotated[Suite, AfterValidator(validate_suite)])
