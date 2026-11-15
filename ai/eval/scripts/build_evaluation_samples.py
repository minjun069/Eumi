"""Build viewer-only evaluations from saved traces, without running or grading agents.

Execution metadata and observed values are copied from the source report. Quality
verdicts are deliberately varied UI examples; they do not describe real defects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

AI_DIR = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = (
    AI_DIR
    / "outputs/report-improved-20261109-r2/runs"
    / "c697bdf2-a3ac-42a6-a228-8a94c07a4344/report.json"
)
DEFAULT_USER = (
    AI_DIR
    / "outputs/api-roundtrip-file-20261106-r2"
    / "5897f877-1313-42eb-b4b9-ceaefe0ccb5a"
    / "42b48fe3-75bc-4e10-9c5b-b71e9d52c6d8/report.json"
)
NODES = {
    "interpret": ("N01", "작업 목적 파악"),
    "act": ("N02", "작업 선택 및 실행"),
    "decide": ("N03", "작업 진행 판단"),
    "compose": ("N04", "응답 작성"),
    "ask": ("N05", "사용자 정보 요청"),
}
TOOLS = {
    "query_data": ("T01", "데이터 검색·조회"),
    "process_data": ("T02", "데이터 가공"),
    "validate_visualization": ("T03", "시각화 설정 검사"),
}
MOCK_NOTE = (
    "UI 검토용 임시 판정이며 실제 결함을 뜻하지 않음. "
    "입력·관측값·호출 기록은 원본 그대로다."
)
SCOPE = (
    "실행 대상·호출 횟수·입출력·종료 상태·시간은 연결한 report.json의 실제 기록이다. "
    "품질의 통과·실패와 해당 검사 실행 표시는 UI 검토용 모의 상태이며 "
    "실제 품질이나 결함을 뜻하지 않는다. "
    "원본 실행 자체에 포함된 합성 자료·확인 범위·문자열은 변경하지 않았다. "
    "검사 항목 수와 실행 횟수는 서로 다르며, 한 호출의 검사들은 같은 사례로 묶는다."
)


def read_pointer(document: Any, pointer: str) -> Any:
    """Resolve a JSON pointer, including valid null values, without modification."""
    value = document
    for part in pointer.removeprefix("/").split("/") if pointer else []:
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def load_catalog() -> dict[str, Any]:
    source = (AI_DIR / "eval/viewers/report/evaluation-catalog.js").read_text(
        encoding="utf-8"
    )
    payload = source.split("globalThis.EvaluationCatalog =", 1)[1].lstrip()
    return json.JSONDecoder().raw_decode(payload)[0]


class SampleBuilder:
    """Extract source evidence and assemble the viewer's separate JSON artifact."""

    def __init__(self, path: Path) -> None:
        raw = path.read_bytes()
        self.report = json.loads(raw)
        try:
            self.source = path.resolve().relative_to(AI_DIR).as_posix()
        except ValueError:
            self.source = path.resolve().as_posix()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.spans = self.report["trace"]["spans"]
        self.positions = {span["id"]: index for index, span in enumerate(self.spans)}
        self.run_id = self.report["state"]["execution"]["run_id"]
        self.event = self.report["state"]["execution"]["event"]
        self.catalog = load_catalog()

    def ref(self, pointer: str) -> str:
        return f"{self.source}#{pointer}"

    def base(self, span: dict[str, Any]) -> str:
        return f"/trace/spans/{self.positions[span['id']]}"

    def ancestors(self, span: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        parent = span.get("parent_id")
        while parent:
            ancestor = self.spans[self.positions[parent]]
            result.append(ancestor)
            parent = ancestor.get("parent_id")
        return result

    def execution(self, span: dict[str, Any]) -> dict[str, Any]:
        ancestors = self.ancestors(span)
        caller = next(
            (item["name"] for item in ancestors if item["kind"] == "agent"),
            span["name"],
        )
        execution = None
        for item in [span, *ancestors]:
            for key in ("state", "initial_state"):
                execution = item.get("input", {}).get(key, {}).get("execution")
                if execution:
                    break
            if execution:
                break
        if execution is None:
            raise ValueError(f"실행 ID를 확인할 수 없는 호출: {span['id']}")
        return {
            "id": span["id"],
            "name": span["name"],
            "caller": caller,
            "run_id": execution["run_id"],
            "status": span["status"],
            "elapsed_seconds": span["elapsed_seconds"],
            "evidence": self.ref(self.base(span)),
        }

    def unit(
        self,
        kind: str,
        name: str,
        spans: list[dict[str, Any]],
        target_id: str | None = None,
    ) -> dict[str, Any]:
        result = {
            "id": f"source-{kind}-{target_id or spans[0]['name']}",
            "kind": kind,
            "target": name,
            "scope": SCOPE,
            "run_ids": [self.run_id],
            "executions": [self.execution(span) for span in spans],
            "metrics": [],
            "checks": [],
        }
        if target_id:
            result["target_id"] = target_id
        return result

    def check(
        self,
        unit: dict[str, Any],
        span: dict[str, Any],
        check_id: str,
        target: str,
        metric_names: list[str],
        input_pointer: str,
        actual_pointer: str,
        expected: str,
        *,
        verdict: str | None = None,
        executed: bool = True,
        reason: str | None = None,
    ) -> None:
        if verdict is None:
            # A deterministic UI fixture, never an assessment of the observed value.
            verdict = "실패" if len(unit["checks"]) % 4 == 1 else "통과"
        unit["checks"].append(
            {
                "case_id": span["id"],
                "execution_id": span["id"],
                "check_id": check_id,
                "target": target,
                "run_id": self.run_id,
                "executed": executed,
                "verdict": verdict,
                "metrics": metric_names,
                "input": read_pointer(self.report, input_pointer),
                "expected": expected,
                "actual": read_pointer(self.report, actual_pointer),
                "reason": reason
                or (
                    f"UI 검토용 임시 {verdict} 판정. 실제 결함을 뜻하지 않음. "
                    "원문 대조에 의한 품질 채점은 수행하지 않았다."
                ),
                "cause": "실제 결함 원인 미평가"
                if verdict == "실패"
                else "해당 없음 또는 미평가",
                "evidence": {
                    "input": self.ref(input_pointer),
                    "actual": self.ref(actual_pointer),
                    "criterion": f"eval/docs/{unit['kind']}.md · {check_id}",
                },
            }
        )

    def node_checks(self, unit: dict[str, Any], spans: list[dict[str, Any]]) -> None:
        for span in spans:
            base = self.base(span)
            request = f"{base}/input/state/request"
            output = f"{base}/output/node_update"
            first = f"{output}/results/0"
            if span["name"] == "interpret":
                self.check(
                    unit,
                    span,
                    "N01-O.1",
                    "정리한 목표·조건",
                    ["노드 출력 정확도"],
                    request,
                    f"{output}/request",
                    "요청에서 확인된 목표와 조건을 보존한다.",
                )
            elif span["name"] == "act":
                self.check(
                    unit,
                    span,
                    "N02-O.2",
                    "선택한 호출 대상",
                    ["노드 출력 정확도"],
                    request,
                    f"{first}/output/name",
                    "남은 작업에 필요한 기능을 제공하는 대상을 선택한다.",
                )
                self.check(
                    unit,
                    span,
                    "N02-O.3",
                    "선택한 호출 인자",
                    ["노드 출력 정확도"],
                    request,
                    f"{output}/results/1/action/arguments",
                    "호출 입력이 요청 조건과 확보 자료에 맞는다.",
                )
            elif span["name"] == "decide":
                self.check(
                    unit,
                    span,
                    "N03-O.2",
                    "다음 작업 판단 사유",
                    ["노드 출력 정확도"],
                    request,
                    f"{first}/output/reason",
                    "자료·호출 상태·남은 작업이 판단 사유를 뒷받침한다.",
                )
                self.check(
                    unit,
                    span,
                    "N03-O.3",
                    "선택한 다음 단계",
                    ["노드 출력 정확도", "분기 정확도"],
                    request,
                    f"{first}/output/next",
                    "제공된 자료와 남은 작업에 맞는 방향을 선택한다.",
                )
            elif span["name"] == "compose":
                self.check(
                    unit,
                    span,
                    "N04-O.1",
                    "작성한 공개 응답",
                    ["노드 출력 정확도"],
                    request,
                    f"{output}/response/content",
                    "필수 응답·근거·한계·미해결 사항을 포함한다.",
                )
                self.check(
                    unit,
                    span,
                    "N04-O.2",
                    "선택한 공개 산출물",
                    ["노드 출력 정확도"],
                    request,
                    f"{output}/response/artifacts",
                    "유효한 결과를 포함하고 사용할 수 없는 결과를 제외한다.",
                )
            else:
                self.check(
                    unit,
                    span,
                    "N05-O.2",
                    "작성한 질문",
                    ["노드 출력 정확도"],
                    request,
                    f"{output}/response/content",
                    "사용자가 답할 값이나 선택을 명시한다.",
                )
            self.check(
                unit,
                span,
                "N-S.3",
                "첫 기록의 판단 종류",
                ["실행 상태 정확도"],
                request,
                f"{first}/decision",
                "실제 수행·판단을 results 이력에 남긴다. 대표 기록 1개를 표시한다.",
            )

    def tool_checks(self, unit: dict[str, Any], spans: list[dict[str, Any]]) -> None:
        for span in spans:
            base = self.base(span)
            arguments = f"{base}/input/resolved_arguments"
            if span["name"] == "process_data":
                arguments += "/operations"
            self.check(
                unit,
                span,
                "T-I.1",
                "요청한 입력·연산 수용",
                ["입력 처리 정확도"],
                arguments,
                f"{base}/status",
                "계약의 수용 조건을 충족한 입력을 수용한다.",
            )
            if span["name"] == "validate_visualization":
                fields = [
                    ("T03-O.1", "검사한 표시 설정 산출물", "artifact"),
                    ("T-O.6", "설정 적합 여부", "valid"),
                ]
            else:
                count_field = (
                    "returned" if span["name"] == "query_data" else "output_rows"
                )
                fields = [
                    ("T-O.1", "반환한 자료 행", "data/rows"),
                    ("T-O.6", "반환 행 수", count_field),
                ]
            for check_id, target, field in fields:
                self.check(
                    unit,
                    span,
                    check_id,
                    target,
                    ["도구 출력 정확도"],
                    arguments,
                    f"{base}/output/{field}",
                    "실제 처리 결과와 반환값의 내용·단위·건수가 일치한다.",
                )

    def agent_checks(self, unit: dict[str, Any], span: dict[str, Any]) -> None:
        base = self.base(span)
        request = f"{base}/input/initial_state/request"
        output = f"{base}/output"
        self.check(
            unit,
            span,
            "F01-I.1" if unit["kind"] != "report" else "R01-I.1",
            "입력 목적·조건",
            ["입력 정확도"],
            request,
            f"{output}/request",
            "요청에서 정한 대상·목적·조건을 실행에 보존한다.",
        )
        if unit["kind"] == "report":
            artifact = f"{output}/response/artifacts/0/data"
            for number in range(1, 4):
                self.check(
                    unit,
                    span,
                    "R01-O.1",
                    f"선정한 상세 뷰 {number}",
                    ["출력 정확도"],
                    request,
                    f"{artifact}/graph_{number}",
                    "허용된 상세 뷰 중 목적에 맞는 뷰를 선택한다.",
                )
                self.check(
                    unit,
                    span,
                    "R02-O.1",
                    f"상세 뷰 {number} 설명",
                    ["출력 정확도"],
                    request,
                    f"{artifact}/desc_{number}",
                    "설명의 대상·근거·범위가 선정한 뷰와 일치한다.",
                )
            self.check(
                unit,
                span,
                "R03-O.3",
                "퀵 인사이트",
                ["출력 정확도", "근거 일치율"],
                request,
                f"{artifact}/quick_insight",
                "검증된 설명과 선정 범위 밖의 새로운 주장을 추가하지 않는다.",
            )
        else:
            self.check(
                unit,
                span,
                "A-O.1",
                "최종 Tableau 산출물",
                ["출력 정확도"],
                request,
                f"{output}/response/artifacts/0",
                "요청 조건에 맞는 산출물을 제공한다.",
            )
            self.check(
                unit,
                span,
                "A-O.3",
                "확인 범위와 한계 안내",
                ["출력 정확도"],
                request,
                f"{output}/response/content",
                "설정 검사와 실제 데이터·화면 확인 범위를 구분한다.",
            )
            self.check(
                unit,
                span,
                "A-O.7",
                "확인 범위를 표현한 응답",
                ["출력 정확도", "근거 일치율"],
                request,
                f"{output}/response/content",
                "관측 사실과 추정·미확인을 구별한다.",
            )
        self.check(
            unit,
            span,
            "F01-S.1",
            "종료 시 실행 상태·사용량",
            ["상태 정확도"],
            request,
            f"{output}/execution",
            "원본 실행 상태와 사용량을 기록한다.",
        )
        first_node = next(
            item
            for item in self.spans
            if item["kind"] == "node" and item["parent_id"] == span["id"]
        )
        self.check(
            unit,
            span,
            "F01-B.6" if unit["kind"] == "report" else "F01-B.1",
            "실제로 진입한 첫 노드",
            ["행동 준수율"],
            request,
            f"{self.base(first_node)}/name",
            "보고서 생성은 작업 선택, 사용자 요청은 목적 파악에서 시작한다.",
        )
        integration = (
            "화면 연동 준수율" if unit["kind"] == "visualization" else "연동 준수율"
        )
        self.check(
            unit,
            span,
            "S08-O.1",
            "반환 산출물의 실제 화면 로딩 검사",
            [integration],
            request,
            f"{output}/response/artifacts",
            "실제 화면에서 산출물을 열고 로딩 완료·오류를 확인한다.",
            verdict="미판정",
            executed=False,
            reason=(
                "연결한 업무 호출은 실제 실행됐다. "
                "반환 산출물의 별도 화면 로딩 검사는 수행하지 않았으며, "
                "원본에도 화면 확인 증거가 없다."
            ),
        )
        if unit["kind"] == "report":
            save = next(
                item
                for item in self.spans
                if item["kind"] == "database" and item["name"] == "save_report"
            )
            self.check(
                unit,
                span,
                "S04-O.3",
                "보고서 저장 응답",
                ["저장 성공률"],
                f"{output}/response/artifacts/0/data",
                f"{self.base(save)}/output",
                "실제 커밋과 저장 후 재조회값을 확인한다.",
                verdict="미판정",
                reason=(
                    "원본 저장 응답을 표시했다. 저장 후 재조회 자료가 없어 "
                    "최종 저장값 일치 여부는 미판정이다."
                ),
            )

    def operating_metrics(
        self, unit: dict[str, Any], spans: list[dict[str, Any]]
    ) -> None:
        kind = unit["kind"]
        if kind in ("nodes", "tools", "visualization"):
            metric_name = (
                "설정 응답시간" if kind == "visualization" else "호출 응답시간"
            )
            times = [
                span["elapsed_seconds"]
                for span in spans
                if span.get("ended_at") and span["status"] == "success"
            ]
            measurements = []
            if times:
                measurements = [
                    {
                        "label": "성공 호출 중앙값",
                        "value": statistics.median(times),
                        "unit": "초",
                    },
                    {
                        "label": "성공 호출 p95",
                        "value": sorted(times)[math.ceil(len(times) * 0.95) - 1],
                        "unit": "초",
                    },
                ]
            unit["metrics"].append(
                {
                    "name": metric_name,
                    "measurements": measurements,
                    "verdict": "미판정",
                    "required": False,
                    "note": (
                        "원본 span의 시작~반환 시간. "
                        "p95는 정렬한 값의 ceil(0.95×N)번째 값이다. "
                        "하위 호출 시간을 더하지 않았다. 사전 운영 목표는 미확정이다."
                    ),
                    "evidence": [
                        self.ref(f"{self.base(span)}/elapsed_seconds") for span in spans
                    ],
                }
            )
            for span in spans:
                self.check(
                    unit,
                    span,
                    "O01.1",
                    "실제 호출 응답시간",
                    [metric_name],
                    f"{self.base(span)}/started_at",
                    f"{self.base(span)}/elapsed_seconds",
                    "기록된 호출 응답시간을 보존한다. 사전 최대값 미확정.",
                    verdict="미판정",
                    reason=(
                        "실제 측정값이다. 운영 목표가 없어 합격 여부는 판정하지 않았다."
                    ),
                )
        if kind != "visualization":
            failure_name = (
                "기술적 실행 실패율" if kind in ("nodes", "tools") else "기술 실패율"
            )
            finished = [span for span in spans if span.get("ended_at")]
            # These fixtures contain successful spans only. Do not infer a technical
            # failure from an unclassified application error in future source files.
            if any(span["status"] != "success" for span in finished):
                return
            unit["metrics"].append(
                {
                    "name": failure_name,
                    "numerator": 0,
                    "denominator": len(finished),
                    "verdict": "미판정",
                    "required": False,
                    "note": (
                        "실제 종료 기록에서 기술 장애로 실패한 호출은 0건이다. "
                        "임시 품질 실패와 별개이며 사전 허용 비율은 미확정이다."
                    ),
                    "evidence": [
                        self.ref(f"{self.base(span)}/status") for span in finished
                    ],
                }
            )
            for span in finished:
                self.check(
                    unit,
                    span,
                    "O02.1",
                    "실제 호출 종료 상태",
                    [failure_name],
                    f"{self.base(span)}/name",
                    f"{self.base(span)}/status",
                    "종료 상태와 기술 장애를 구분해 기록한다.",
                    verdict="미판정",
                    reason=(
                        "실제 종료 상태는 success다. "
                        "UI용 품질 실패를 기술적 실행 실패로 세지 않았다. "
                        "사전 허용 비율은 미확정이다."
                    ),
                )

    def finalize(self, unit: dict[str, Any]) -> None:
        recorded = {metric["name"] for metric in unit["metrics"]}
        completion_names = {
            "report": "보고서 완성률",
            "user-request": "요청 해결률",
            "visualization": "시각화 설정 완료율",
        }
        for definition in self.catalog[unit["kind"]]["metrics"]:
            name = definition["name"]
            if (
                name in recorded
                or definition.get("target_ids")
                and unit.get("target_id") not in definition["target_ids"]
            ):
                continue
            checks = [check for check in unit["checks"] if name in check["metrics"]]
            metric = {"name": name, "verdict": "미판정", "required": False}
            if name == completion_names.get(unit["kind"]):
                checks = [
                    check
                    for check in unit["checks"]
                    if "출력 정확도" in check["metrics"]
                ]
                for check in checks:
                    check["metrics"].append(name)
                metric.update(
                    numerator=int(all(check["verdict"] == "통과" for check in checks)),
                    denominator=len(unit["executions"]),
                    note=(
                        "UI 검토용 대표 출력 검사를 호출 단위로 묶은 "
                        "임시 완료 비율이다. "
                        "실제 업무 완료·품질을 판정한 값이 아니다."
                    ),
                )
            elif checks:
                judged = [
                    check
                    for check in checks
                    if check["executed"] and check["verdict"] in ("통과", "실패")
                ]
                denominator = len(judged)
                if definition["group"] == "integration":
                    denominator = len({check["case_id"] for check in checks})
                metric.update(
                    numerator=sum(check["verdict"] == "통과" for check in judged),
                    denominator=denominator,
                    unjudged=sum(
                        check["executed"] and check["verdict"] == "미판정"
                        for check in checks
                    ),
                    not_executed=sum(not check["executed"] for check in checks),
                    not_applicable=0,
                    verdict="실패"
                    if any(check["verdict"] == "실패" for check in checks)
                    else "통과"
                    if judged and len(judged) == len(checks)
                    else "미판정",
                    note=MOCK_NOTE
                    if definition["group"] == "functional"
                    else (
                        "별도 연동 검사에 필요한 증거가 부족하다. "
                        "실제 업무 호출의 미실행을 뜻하지 않는다."
                    ),
                )
            else:
                metric["note"] = (
                    "이 실행 기록만으로 기준·독립 정답·시험 조건을 "
                    "확인할 수 없어 미판정이다. "
                    "수치·추가 호출·반복 시험을 임의로 만들지 않았다."
                )
            if checks:
                metric["evidence"] = [check["evidence"]["actual"] for check in checks]
            unit["metrics"].append(metric)
        unit["verdicts"] = {
            "functional": "실패"
            if any(check["verdict"] == "실패" for check in unit["checks"])
            else "미판정",
            "operational": "미판정",
            "integration": "미판정",
        }

    def build(self) -> dict[str, Any]:
        root = next(
            span
            for span in self.spans
            if span["kind"] == "agent" and span["parent_id"] is None
        )
        kind = "report" if self.event == "analysis_pipeline" else "user-request"
        if kind == "report":
            data = self.report["state"]["response"]["artifacts"][0]["data"]
            target = f"{data['adm_cd10']} · {data['period_start'][:7]} 보고서"
        else:
            target = "사용자 질문 · 종합 위험도 지도 요청"
        main = self.unit(kind, target, [root])
        self.agent_checks(main, root)
        self.operating_metrics(main, [root])
        if kind == "report":
            main["metrics"].append(
                {
                    "name": "동별 처리시간",
                    "measurements": [
                        {
                            "label": "실행 기록의 누적 노드 활성 시간",
                            "value": self.report["state"]["execution"]["budget"][
                                "active_seconds"
                            ]["used"],
                            "unit": "초",
                        }
                    ],
                    "verdict": "미판정",
                    "required": False,
                    "note": (
                        "원본 실행 예산의 실제 누적 활성 시간이다. "
                        "실행 자리 대기·최초 분석 확인·요청 전체 시간은 "
                        "추정하지 않았다."
                    ),
                    "evidence": [
                        self.ref("/state/execution/budget/active_seconds/used")
                    ],
                }
            )
        units = [main]
        for span in self.spans:
            if span["kind"] == "agent" and span["name"] == "visualization_agent":
                unit = self.unit(
                    "visualization", "위임한 시각화 · " + span["name"], [span]
                )
                self.agent_checks(unit, span)
                self.operating_metrics(unit, [span])
                units.append(unit)
        for span_kind, mapping, unit_kind in (
            ("node", NODES, "nodes"),
            ("tool", TOOLS, "tools"),
        ):
            for name, (target_id, label) in mapping.items():
                spans = [
                    span
                    for span in self.spans
                    if span["kind"] == span_kind and span["name"] == name
                ]
                if not spans:
                    continue
                unit = self.unit(unit_kind, f"{target_id} · {label}", spans, target_id)
                (self.node_checks if unit_kind == "nodes" else self.tool_checks)(
                    unit, spans
                )
                self.operating_metrics(unit, spans)
                units.append(unit)
        for unit in units:
            self.finalize(unit)
        return {
            "type": "evaluation",
            "schema_version": 1,
            "id": f"sample-{kind}-evaluation-v3",
            "title": "실제 실행 기록 · "
            + ("보고서" if kind == "report" else "사용자 요청")
            + " 평가 UI 예시",
            "sample": True,
            "event": self.event,
            "run_ids": [self.run_id],
            "scope": SCOPE,
            "versions": {
                "evaluation": "docs/eval · 2026-11-09 검토용 명세",
                "data": self.source,
                "source_sha256": self.sha256,
                "code": "build_evaluation_samples.py · source-aligned-v3",
                "model": "원본 실행의 모델 응답 사용 · 추가 호출 없음",
                "settings": "실행 증거 보존 · 품질 판정만 UI 예시",
            },
            "units": units,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, default=DEFAULT_REPORT, help="보고서 실행의 report.json"
    )
    parser.add_argument(
        "--user-request",
        type=Path,
        default=DEFAULT_USER,
        help="사용자 요청 실행의 report.json",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=AI_DIR / "eval/viewers/report"
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path, filename in (
        (args.report, "evaluation-sample.json"),
        (args.user_request, "evaluation-user-request-sample.json"),
    ):
        result = SampleBuilder(path).build()
        output = args.output_dir / filename
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        execution_count = sum(len(unit["executions"]) for unit in result["units"])
        print(f"{filename}: {len(result['units'])} units, {execution_count} executions")


if __name__ == "__main__":
    main()
