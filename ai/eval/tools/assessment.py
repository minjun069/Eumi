"""저장된 도구 실행을 사례의 독립 기준과 비교한다. 업무 코드는 호출하지 않는다."""

import json
import re
from copy import deepcopy
from math import isclose, isfinite
from typing import TYPE_CHECKING, Annotated, Literal, NotRequired

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    with_config,
)
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from eval.runner import RunReport
    from eval.schema import Assessment, Case

ToolTarget = Literal["query_data", "process_data", "validate_visualization"]
CheckId = Literal["T-I.1", "T-O.1", "T-O.2", "T-O.5"]
Verdict = Literal["통과", "실패", "미판정", "비적용"]
TOOL_TARGETS = set(ToolTarget.__args__)
CHECK_IDS = set(CheckId.__args__)
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]


def _pointer(value: str) -> str:
    if not value.startswith("/") or re.search(r"~(?![01])", value):
        raise ValueError("Use an absolute JSON pointer with ~0 and ~1 escaping")
    root = value.split("/", 2)[1]
    if root not in {"output", "failure", "run", "trace", "observations"}:
        raise ValueError("Expectations must address recorded execution evidence")
    return value


Pointer = Annotated[str, AfterValidator(_pointer)]


@with_config(ConfigDict(extra="forbid", strict=True))
class NumericTolerance(TypedDict, total=False):
    absolute: Nonnegative
    relative: Nonnegative


@with_config(ConfigDict(extra="forbid", strict=True))
class Expectation(TypedDict):
    check: CheckId
    path: Pointer
    value: NotRequired[JsonValue]
    match: NotRequired[Literal["equal", "subset", "present", "absent"]]
    tolerance: NotRequired[NumericTolerance]
    applicable: NotRequired[bool]
    reason: NotRequired[Text]


def _expectation(item: Expectation) -> Expectation:
    if item.get("applicable") is False and not item.get("reason"):
        raise ValueError("An inapplicable expectation needs a reason")
    if item.get("match") in {"present", "absent"} and (
        "value" in item or "tolerance" in item
    ):
        raise ValueError("Presence checks do not accept a value or tolerance")
    return item


@with_config(ConfigDict(extra="forbid", strict=True))
class ToolExpectations(TypedDict):
    schema_version: Literal["tool-expectations-v1"]
    items: list[Annotated[Expectation, AfterValidator(_expectation)]]


def _expectations(value: ToolExpectations) -> ToolExpectations:
    keys = [(item["check"], item["path"]) for item in value["items"]]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate check and evidence path")
    return value


expectations_adapter = TypeAdapter(
    Annotated[ToolExpectations, AfterValidator(_expectations)]
)
tolerance_adapter = TypeAdapter(NumericTolerance)


@with_config(ConfigDict(extra="forbid", strict=True))
class PerformanceTarget(TypedDict):
    target: ToolTarget
    group: Literal["normal", "error"]
    case_ids: Annotated[list[Text], Field(min_length=1)]
    statistic: NotRequired[Literal["median", "p95"]]
    max_seconds: NotRequired[Nonnegative]
    environment: NotRequired[Text]
    data_size: NotRequired[Text]


class CheckResult(TypedDict):
    check: str
    target: str
    executed: bool
    verdict: Verdict
    reason: str
    evidence: list[str]
    expected: NotRequired[JsonValue]
    actual: NotRequired[JsonValue]
    match: NotRequired[Literal["equal", "subset", "present", "absent"]]
    tolerance: NotRequired[NumericTolerance]


class RunAssessment(TypedDict):
    run_id: str | None
    case_id: str
    target: str
    repetition: int
    executed: bool
    verdict: Verdict
    reason: str
    checks: list[CheckResult]


def validate_assessment(assessment: "Assessment") -> None:
    """버전을 선언한 기대값만 해석하고 기존 자유 형식의 값은 채점하지 않는다."""
    expected = assessment.get("expected")
    if not isinstance(expected, dict) or "schema_version" not in expected:
        return
    validated = expectations_adapter.validate_python(expected)
    json.dumps(validated, allow_nan=False)
    checks = assessment.get("checks", [])
    if len(checks) != len(set(checks)) or set(checks) - CHECK_IDS:
        raise ValueError("Tool assessment checks must be unique supported check IDs")
    if any(item["check"] not in checks for item in validated["items"]):
        raise ValueError("Every expectation must belong to an applicable check")
    if "tolerance" in assessment:
        tolerance_adapter.validate_python(assessment["tolerance"])


def _read(value, pointer):
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            index = int(token)
            if index >= len(value):
                return False, None
            value = value[index]
        else:
            return False, None
    return True, value


def _matches(actual, expected, tolerance, subset=False):
    # bool is a JSON logical value, even though Python makes it an int subclass.
    if type(actual) in (int, float) and type(expected) in (int, float):
        if any(
            type(value) is float and not isfinite(value) for value in (actual, expected)
        ):
            return False
        if not tolerance.get("relative", 0) and not tolerance.get("absolute", 0):
            return actual == expected
        if type(actual) is int and type(expected) is int:
            difference = abs(actual - expected)
            return difference <= tolerance.get("absolute", 0) or (
                tolerance.get("relative", 0) > 0
                and difference / max(abs(actual), abs(expected))
                <= tolerance["relative"]
            )
        try:
            return isclose(
                actual,
                expected,
                rel_tol=tolerance.get("relative", 0),
                abs_tol=tolerance.get("absolute", 0),
            )
        except OverflowError:
            return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        if (not subset and actual.keys() != expected.keys()) or not (
            expected.keys() <= actual.keys()
        ):
            return False
        return all(
            _matches(actual[key], item, tolerance, subset)
            for key, item in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _matches(left, right, tolerance, subset)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def combine_verdicts(verdicts: list[Verdict]) -> Verdict:
    if "실패" in verdicts:
        return "실패"
    if not verdicts or "미판정" in verdicts:
        return "미판정"
    if all(verdict == "비적용" for verdict in verdicts):
        return "비적용"
    return "통과"


def _result(check, path, reason, *, verdict="미판정", executed=False):
    return CheckResult(
        check=check,
        target=path,
        executed=executed,
        verdict=verdict,
        reason=reason,
        evidence=[],
    )


def _compare(item, assessment, report, facts):
    check, path = item["check"], item["path"]
    if item.get("applicable") is False:
        return _result(check, path, item["reason"], verdict="비적용")
    if report is None:
        return _result(check, path, "실행 결과가 없어 비교하지 못했습니다.")
    if report.get("run", {}).get("status") not in {"returned", "error", "cancelled"}:
        return _result(check, path, "종료된 실행 결과가 없어 비교하지 못했습니다.")
    if not assessment.get("reference"):
        return _result(check, path, "독립 기준 자료가 지정되지 않았습니다.")
    mode = item.get("match", "equal")
    if mode in {"equal", "subset"} and "value" not in item:
        return _result(check, path, "기대값이 지정되지 않았습니다.")
    # A failed call has no evidence about result fields it never produced.
    # The recorded null /output itself is still observable (e.g. expected refusal).
    if (
        path.startswith("/output/")
        and report.get("output") is None
        and (report.get("run", {}).get("status") != "returned")
    ):
        return _result(
            check, path, "호출이 결과를 반환하지 않아 해당 값은 확인 불가입니다."
        )
    if path == "/trace" or path.startswith("/trace/"):
        if "observations" not in facts:
            return _result(check, path, "완료한 도구의 추적 증거가 없습니다.")
    if (path == "/observations" or path.startswith("/observations/")) and (
        "observations" not in facts
    ):
        return _result(
            check, path, "완료한 도구 호출 추적이 없어 수행 여부를 확인할 수 없습니다."
        )
    exists, actual = _read(facts, path)
    tolerance = item.get("tolerance", assessment.get("tolerance", {}))
    if mode == "present":
        passed = exists
    elif mode == "absent":
        passed = not exists
    else:
        passed = exists and _matches(actual, item["value"], tolerance, mode == "subset")
    result = _result(
        check,
        path,
        "기대 조건과 일치합니다."
        if passed
        else (
            "기대 조건과 다릅니다." if exists else "필수 비교 대상이 누락되었습니다."
        ),
        verdict="통과" if passed else "실패",
        executed=True,
    )
    result["evidence"] = [f"report.json#{path}"]
    result["match"] = mode
    if mode in {"equal", "subset"}:
        result["tolerance"] = {
            "absolute": tolerance.get("absolute", 0),
            "relative": tolerance.get("relative", 0),
        }
    if path == "/observations" or path.startswith("/observations/"):
        result["evidence"] = ["report.json#/trace/spans"]
    if "value" in item:
        result["expected"] = deepcopy(item["value"])
    if exists:
        result["actual"] = deepcopy(actual)
    return result


def assess_run(
    case: "Case", report: "RunReport | None", repetition: int = 1
) -> RunAssessment:
    """사례의 선언된 검사만 판정한다. 기준 누락과 실행 실패를 통과로 바꾸지 않는다."""
    assessment = case.get("assessment", {})
    supported = case["unit"] == "tool" and case["target"] in TOOL_TARGETS
    if supported:
        validate_assessment(assessment)
    checks = assessment.get("checks", [])
    expected = assessment.get("expected", {})
    versioned = isinstance(expected, dict) and (
        expected.get("schema_version") == "tool-expectations-v1"
    )
    facts = dict(report or {})
    facts.pop("observations", None)
    trace = facts.get("trace")
    raw_spans = trace.get("spans") if isinstance(trace, dict) else None
    spans = []
    if isinstance(raw_spans, list):
        by_id = {}
        for span in raw_spans:
            if not isinstance(span, dict) or not isinstance(span.get("id"), str):
                break
            if not span["id"] or (span["id"] in by_id and by_id[span["id"]] != span):
                break
            by_id[span["id"]] = span
        else:
            spans = list(by_id.values())
    tools = [
        span
        for span in spans
        if span.get("kind") == "tool" and span.get("name") == case["target"]
    ]
    if (
        len(tools) == 1
        and tools[0].get("ended_at")
        and tools[0].get("status") in {"success", "error"}
    ):
        facts["observations"] = {
            "provider_calls": sum(
                span.get("kind") == "provider"
                and span.get("parent_id") == tools[0]["id"]
                for span in spans
            ),
        }
    results = []
    for check in dict.fromkeys(checks):
        items = (
            [item for item in expected["items"] if item["check"] == check]
            if supported and versioned
            else []
        )
        if items:
            results.extend(_compare(item, assessment, report, facts) for item in items)
        else:
            results.append(
                _result(
                    check,
                    "",
                    "이 단위의 자동 채점을 지원하지 않습니다."
                    if not supported
                    else "해당 검사의 비교 기준이 지정되지 않았습니다.",
                )
            )
    verdict = combine_verdicts([result["verdict"] for result in results])
    # Only inapplicable checks do not establish a passing tool case.
    if verdict == "비적용":
        verdict = "미판정"
    return RunAssessment(
        run_id=report["run"]["id"] if report else None,
        case_id=case["id"],
        target=case["target"],
        repetition=repetition,
        executed=any(item["executed"] for item in results),
        verdict=verdict,
        reason=(
            "지정한 검사별 판정을 종합했습니다."
            if results
            else "적용 검사가 지정되지 않았습니다."
        ),
        checks=results,
    )
