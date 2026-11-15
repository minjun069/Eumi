"""업무 State와 분리한 실행 평가의 기대 경로·시험 조건·운영 목표."""

from typing import Annotated, Literal, NotRequired

from pydantic import AfterValidator, ConfigDict, Field, TypeAdapter, with_config
from typing_extensions import TypedDict

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Number = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Node = Literal["interpret", "decide", "act", "compose", "ask"]
ReportRole = Literal["report_selection", "report_description", "report_insight"]
COMMON_CHECKS = ("EX-1", "EX-2", "EX-3", "EX-4", "EX-5")
REPORT_CHECKS = ("EX-R1", "EX-R2", "EX-R3", "EX-R4", "EX-R5")


def supported(case: dict) -> bool:
    return (case.get("unit"), case.get("target")) in {
        ("agent", "request"),
        ("workflow", "report"),
    }


@with_config(ConfigDict(extra="forbid", strict=True))
class ExecutionExpectations(TypedDict):
    schema_version: Literal["execution-expectations-v1"]
    situation: Literal["normal", "data_shortage", "fault", "limit_cancel"]
    entry: Literal["initial", "reentry"]
    environment: NotRequired[Text]
    data_size: NotRequired[Text]
    node_path: NotRequired[list[Node]]
    role_path: NotRequired[list[ReportRole]]
    run_status: NotRequired[Literal["running", "returned", "error", "cancelled"]]
    execution_status: NotRequired[
        Literal[
            "queued",
            "running",
            "waiting_input",
            "completed",
            "partial",
            "failed",
            "cancelled",
        ]
    ]
    response_kind: NotRequired[
        Literal["progress", "intermediate", "final", "question"] | None
    ]
    error_code: NotRequired[Text | None]
    report_completeness: NotRequired[Literal["complete", "partial", "none"]]


expectations_adapter = TypeAdapter(ExecutionExpectations)


def validate_execution_assessment(case: dict) -> None:
    assessment = case.get("assessment", {})
    expected = assessment.get("expected", {})
    checks = assessment.get("checks", [])
    marked = (
        isinstance(expected, dict)
        and expected.get("schema_version") == "execution-expectations-v1"
    )
    if not marked and not any(check.startswith("EX-") for check in checks):
        return
    if not supported(case):
        raise ValueError("실행 평가는 agent/request 또는 workflow/report에 적용합니다")
    expectations_adapter.validate_python(expected)
    allowed = set(COMMON_CHECKS + (REPORT_CHECKS if case["target"] == "report" else ()))
    if not checks or len(checks) != len(set(checks)) or set(checks) - allowed:
        raise ValueError(
            "실행 검사는 해당 업무의 EX 검사 ID를 중복 없이 지정해야 합니다"
        )
    if (
        case["target"] != "report"
        and {"role_path", "report_completeness"} & expected.keys()
    ):
        raise ValueError("보고서 기대 경로·완성 범위는 workflow/report에만 지정합니다")


@with_config(ConfigDict(extra="forbid", strict=True))
class ExecutionPerformanceTarget(TypedDict):
    target: Literal["request", "report"]
    case_ids: Annotated[list[Text], Field(min_length=1)]
    metric: Literal["latency", "failure_rate", "cost", "repeat_spread"]
    statistic: NotRequired[Literal["median", "p95", "mean"]]
    group: NotRequired[Literal["normal", "technical_failure", "cancelled"]]
    max_seconds: NotRequired[Number]
    max_rate: NotRequired[Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]]
    max_cost: NotRequired[Number]
    environment: NotRequired[Text]
    data_size: NotRequired[Text]
    measure: NotRequired[
        Literal[
            "elapsed_seconds",
            "model_calls",
            "tool_calls",
            "agent_calls",
            "node_entries",
            "retries",
            "input_tokens",
            "output_tokens",
            "cost",
        ]
    ]
    max_spread: NotRequired[Number]


def validate_goal(goal: ExecutionPerformanceTarget) -> ExecutionPerformanceTarget:
    if len(goal["case_ids"]) != len(set(goal["case_ids"])):
        raise ValueError("실행 운영 목표의 사례 ID가 중복되었습니다")
    fields = {
        "latency": {"statistic", "max_seconds", "group"},
        "failure_rate": {"max_rate"},
        "cost": {"statistic", "max_cost", "group"},
        "repeat_spread": {"measure", "max_spread", "group"},
    }
    measurement = {
        "statistic",
        "max_seconds",
        "max_rate",
        "max_cost",
        "group",
        "measure",
        "max_spread",
    }
    if (goal.keys() & measurement) - fields[goal["metric"]]:
        raise ValueError("운영 목표의 지표와 측정 조건이 맞지 않습니다")
    return goal


PerformanceGoal = Annotated[ExecutionPerformanceTarget, AfterValidator(validate_goal)]


@with_config(ConfigDict(extra="forbid", strict=True))
class ModelPrice(TypedDict):
    input_per_million: Number
    output_per_million: Number


@with_config(ConfigDict(extra="forbid", strict=True))
class ToolPrice(TypedDict):
    per_call: Number


@with_config(ConfigDict(extra="forbid", strict=True))
class ExecutionPrices(TypedDict):
    version: Text
    currency: Text
    models: dict[Text, ModelPrice]
    tools: dict[Text, ToolPrice]


def validate_execution_suite(suite: dict) -> None:
    cases = {case["id"]: case for case in suite["cases"]}
    for goal in suite.get("execution_performance", []):
        for case_id in goal["case_ids"]:
            case = cases.get(case_id)
            if not case or not supported(case) or case["target"] != goal["target"]:
                raise ValueError("실행 운영 목표의 사례와 실행 대상이 다릅니다")
