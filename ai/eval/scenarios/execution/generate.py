"""실행 연결 평가용 합성 입력. 실행 결과·평가 정답을 업무에 주입하지 않는다."""

import json
from copy import deepcopy
from pathlib import Path

from eval.execution.schema import COMMON_CHECKS, REPORT_CHECKS
from eval.schema import suite_adapter
from src.execution import record
from src.settings import Settings
from src.state import create_state
from src.tools.query import query_data


def assessment(*, report=False, entry="initial", situation="normal", **expected):
    return {
        "required": True,
        "checks": list(COMMON_CHECKS + (REPORT_CHECKS if report else ())),
        "expected": {
            "schema_version": "execution-expectations-v1",
            "situation": situation,
            "entry": entry,
            "environment": "prepared synthetic data / configured model",
            "data_size": "one request or one dong-month; one source row",
            **expected,
        },
    }


def item(identifier, *args, **kwargs):
    return record(*args, **kwargs) | {"id": identifier}


def build_suite():
    initial = {
        "request": {"goal": "제공된 범위와 한계를 설명한다."},
        "event": "user_request",
        "messages": [
            {
                "type": "human",
                "id": "question",
                "content": "제공된 분석은 행정동의 월별 집계입니다. "
                "개인 상태를 판정할 수 있는지 이 범위만으로 설명해주세요.",
            }
        ],
    }
    request = {
        "id": "request-context",
        "unit": "agent",
        "target": "request",
        "purpose": "사용자 요청의 목적 파악·진행 판단·최종 반환 연결을 확인한다.",
        "initial": initial,
        "providers": [],
        "assessment": assessment(run_status="returned", response_kind="final"),
    }
    limited = deepcopy(request)
    limited.update(
        id="request-exhausted",
        purpose="공유 종료 예산까지 소진된 진입에서 새 호출 없이 반환한다.",
    )
    state = create_state(
        initial["request"],
        Settings(_env_file=None),
        messages=[],
        version="fixture-v1",
        event="user_request",
    )
    state["execution"]["budget"]["steps"]["limit"] = 0
    state["execution"]["budget"]["final_model_calls"]["used"] = 1
    limited["initial"]["budget"] = state["execution"]["budget"]
    limited["assessment"] = assessment(
        situation="limit_cancel",
        run_status="returned",
        error_code="execution_limit_exceeded",
    )
    dataset = {
        "reference": {"id": "public.region_result", "version": "synthetic-v1"},
        "as_of": "2025-12-15",
        "sources": [{"label": "합성 점수", "uri": "fixture://execution/scores"}],
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
    inputs = {
        "requestId": "execution-synthetic",
        "month": "2025-12",
        "dongCodes": ["1168066000"],
        "dongCode": "1168066000",
    }
    records = [
        item(
            "report-input", "report", "report_input", "합성 보고서 요청", output=inputs
        ),
        item(
            "report-source",
            "report",
            "report_source",
            "합성 자료 시점",
            output={
                "period_start": "2025-12-01",
                "adm_cd10": "1168066000",
                "updated_at": "2025-12-15T00:00:00",
            },
        ),
    ]
    report = {
        "id": "report-start",
        "unit": "workflow",
        "target": "report",
        "purpose": "한 동의 역할 순서·승인 결과 전달·보고서 구성을 확인한다.",
        "initial": {
            "request": {"goal": "합성 자료로 대치2동 2025년 12월 보고서를 작성한다."},
            "event": "analysis_pipeline",
            "messages": [],
            "results": records,
        },
        "assessment": assessment(report=True, run_status="returned"),
    }
    resume = deepcopy(report)
    resume.update(
        id="report-reentry",
        purpose="준비된 선정 승인과 설명 오류 이력에서 설명 역할부터 재진입한다.",
    )
    values = resume["initial"]["results"]
    values.extend(
        [
            item(
                "source-call",
                "act",
                "call",
                "이전 진입의 합성 자료 조회",
                action={
                    "name": "query_data",
                    "arguments": {"target": "public.region_result"},
                },
                output=query_data(
                    {"target": "public.region_result"},
                    {"public.region_result": lambda: deepcopy(dataset)},
                ),
            ),
            item(
                "selected",
                "compose",
                "report_selection",
                "이전 진입의 선정 결과",
                action={
                    "name": "select_report_views",
                    "arguments": {"view_key": None, "result_ids": ["source-call"]},
                },
                output={
                    "views": [
                        {
                            "view_key": "EmbedDetailV01",
                            "reason": "합성 점수의 관측 범위만 설명",
                            "evidence_ids": ["source-call"],
                        }
                    ]
                },
            ),
            item(
                "selection-review",
                "compose",
                "verification",
                "준비된 선정 승인",
                action={
                    "name": "review_report",
                    "arguments": {"view_key": None, "result_ids": ["selected"]},
                },
                output={
                    "call_id": "selected",
                    "accepted": True,
                    "reason": "연결 시험용 승인",
                },
            ),
            item(
                "selection-done",
                "compose",
                "composition",
                "선정 역할 완료",
                action={
                    "name": "report_selection_agent",
                    "arguments": {"view_key": None, "result_ids": ["selected"]},
                },
                output={
                    "content": "선정 완료",
                    "artifact_ids": [],
                    "status": "partial",
                    "reason": "한 뷰만 선정",
                },
            ),
            item(
                "description-stage",
                "report",
                "report_stage",
                "이전 설명 역할 진입",
                action={
                    "name": "report_description_agent",
                    "arguments": {
                        "view_key": None,
                        "result_ids": ["selected", "source-call"],
                    },
                },
            ),
            item(
                "description-error",
                "compose",
                "execution_failed",
                "이전 진입 설명 호출 오류",
                output={"code": "runtime_error", "error_type": "ConnectionError"},
                success=False,
            ),
        ]
    )
    prior = create_state(
        resume["initial"]["request"],
        Settings(_env_file=None),
        messages=[],
        version="fixture-v1",
        event="analysis_pipeline",
    )["execution"]
    prior.update(
        run_id="synthetic-previous-run",
        status="partial",
        error={"code": "runtime_error", "cause": "준비된 이전 설명 호출 오류"},
    )
    for key, used in {"steps": 5, "tool_calls": 1, "active_seconds": 2.0}.items():
        prior["budget"][key]["used"] = used
    resume["initial"]["execution"] = prior
    resume["assessment"] = assessment(
        report=True,
        entry="reentry",
        situation="fault",
        role_path=["report_description", "report_insight"],
        run_status="returned",
    )
    suite = {
        "schema_version": "evaluation-suite-v1",
        "id": "execution-synthetic-v1",
        "datasets": {"public.region_result": dataset},
        "cases": [request, limited, report, resume],
    }
    return suite_adapter.validate_python(suite)


if __name__ == "__main__":
    target = Path(__file__).with_name("basic.json")
    target.write_text(
        json.dumps(
            suite_adapter.dump_python(build_suite(), mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(target)
