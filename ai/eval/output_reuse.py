"""명시적으로 지정한 같은 조건의 최종 출력 품질 판정만 재사용한다."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Annotated

from pydantic import Field, JsonValue, TypeAdapter, ValidationError
from typing_extensions import TypedDict

from eval.assessment_store import load_assessment


class ReuseSource(TypedDict):
    path: str
    assessment_id: str
    content_sha256: str


class ReuseEvidence(TypedDict):
    source: ReuseSource
    compatible: bool
    reasons: list[str]
    assessments: list[dict[str, JsonValue]]


class ReuseIdentity(TypedDict):
    case_id: Annotated[str, Field(min_length=1)]
    repetition: Annotated[int, Field(ge=1)]
    node_id: Annotated[str, Field(min_length=1)]
    call_id: Annotated[str, Field(min_length=1)]


def load_reuse(
    path: Path,
    *,
    batch_id: str,
    method: str,
    judge_model: str | None,
    criteria_sha256: str,
    evidence_sha256: dict[str, str],
    evaluator_sha256: dict[str, str],
) -> ReuseEvidence:
    """저장한 판정의 조건을 확인하고 다른 기준·증거의 판정은 재사용하지 않는다."""
    original = load_assessment(path)
    if original.get("schema_version") != "output-evaluation-v1":
        raise ValueError("--reuse에는 최종 출력 품질 채점 결과를 지정해야 합니다")
    content_hash = sha256(
        json.dumps(
            original, ensure_ascii=False, sort_keys=True, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    conditions = {
        "batch_id": batch_id,
        "method": method,
        "judge_model": judge_model,
        "criteria_sha256": criteria_sha256,
        "evidence_sha256": evidence_sha256,
        "evaluator_sha256": evaluator_sha256,
    }
    reasons = [
        f"{name}: 이전 판정과 현재 평가 조건이 다릅니다."
        for name, value in conditions.items()
        if original.get(name) != value
    ]
    if original.get("status") != "completed":
        reasons.append("이전 채점이 완료되지 않았습니다.")
    if method == "all" and (
        not isinstance(judge_model, str) or not judge_model.strip()
    ):
        reasons.append(
            "평가 모델 식별자가 없어 동일한 모델의 판정인지 확인할 수 없습니다."
        )
    assessments = original.get("assessments")
    if not isinstance(assessments, list) or any(
        not isinstance(item, dict) for item in assessments
    ):
        raise ValueError("재사용할 품질 판정 목록이 올바르지 않습니다")
    try:
        identities = TypeAdapter(list[ReuseIdentity]).validate_python(
            assessments, strict=True
        )
    except ValidationError as exc:
        raise ValueError(
            "재사용할 판정의 사례·반복·노드·호출 식별자가 올바르지 않습니다"
        ) from exc
    keys = [
        (item["case_id"], item["repetition"], item["node_id"], item["call_id"])
        for item in identities
    ]
    if len(set(keys)) != len(keys):
        raise ValueError("재사용할 판정의 호출 식별자가 중복됐습니다")
    return {
        "source": {
            "path": str(Path(path).resolve()),
            "assessment_id": original["id"],
            "content_sha256": content_hash,
        },
        "compatible": not reasons,
        "reasons": reasons,
        "assessments": deepcopy(assessments) if not reasons else [],
    }


def find_reused(
    pool: ReuseEvidence,
    case_id: str,
    repetition: int,
    node_id: str,
    call_id: str,
) -> dict[str, JsonValue] | None:
    """미판정은 새로 시도하며 한 작성 호출의 완료된 판정을 복사한다."""
    if not pool["compatible"]:
        return None
    for item in pool["assessments"]:
        if (
            item.get("case_id") == case_id
            and item.get("repetition") == repetition
            and item.get("node_id") == node_id
            and item.get("call_id") == call_id
            and item.get("node") == "compose"
            and item.get("complete") is True
            and item.get("verdict") in {"통과", "실패"}
            and item.get("checks")
        ):
            return deepcopy(item)
    return None
