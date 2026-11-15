"""저장된 T03 실행에서 산출물 ID의 형식과 필터 순서 불변성을 확인한다."""

import argparse
import json
from copy import deepcopy
from pathlib import Path

# 기존 61건의 평가 메타데이터를 보존한다. 새 순서 변경은 기준 사례를 명시한다.
LEGACY_PAIR = {"T03-filter-order-reversed": "T03-user-Embed01RiskMap"}


def ordered_filters(arguments):
    normalized = deepcopy(arguments)
    for field, values in normalized["filters"].items():
        normalized["filters"][field] = sorted(values)
    return normalized


def filter_pairs(cases, selected):
    pairs = []
    for case_id in selected:
        case = cases[case_id]
        if "filter-order" not in case["tags"]:
            continue
        base_id = case["assessment"]["reference"].get(
            "equivalent_case", LEGACY_PAIR.get(case_id)
        )
        if base_id not in selected:
            raise ValueError(f"필터 순서 비교의 기준 사례가 빠졌습니다: {case_id}")
        base = cases[base_id]
        if (
            "valid" not in base["tags"]
            or "valid" not in case["tags"]
            or "filter-order" in base["tags"]
            or case["initial"]["event"] != base["initial"]["event"]
            or case["arguments"] == base["arguments"]
            or ordered_filters(case["arguments"]) != ordered_filters(base["arguments"])
        ):
            raise ValueError(f"기준 사례와 필터 순서만 달라야 합니다: {case_id}")
        pairs.append((base_id, case_id))
    if not pairs:
        raise ValueError("필터 순서 비교 사례가 없습니다.")
    return pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    folder = args.batch.resolve()
    batch = json.loads((folder / "batch.json").read_text(encoding="utf-8"))
    suite = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in suite["cases"]}
    selected = batch["plan"]["case_ids"]
    repetitions = set(range(1, batch["plan"]["repeat"] + 1))
    if (
        len(cases) != len(suite["cases"])
        or len(set(selected)) != len(selected)
        or not set(selected) <= cases.keys()
        or not repetitions
        or batch["suite_id"] != suite["id"]
    ):
        raise ValueError("저장된 사례와 실행 계획이 일치하지 않습니다.")
    pairs = filter_pairs(cases, selected)
    ids = {key: {} for key in selected if "valid" in cases[key]["tags"]}
    planned = {(case_id, repeat) for case_id in selected for repeat in repetitions}
    seen = set()
    for run in batch["runs"]:
        key = (run["case_id"], run["repetition"])
        if key not in planned or key in seen:
            raise ValueError(f"예정에 없거나 중복된 실행 결과입니다: {key}")
        seen.add(key)
        report_path = (folder / run["path"]).resolve()
        if not report_path.is_relative_to(folder):
            raise ValueError("실행 결과 경로가 묶음 폴더를 벗어났습니다.")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (
            any(
                report["run"][field] != run[field]
                for field in ("case_id", "repetition", "target")
            )
            or report["run"]["id"] != run["run_id"]
        ):
            raise ValueError(f"실행 목록과 보고서의 식별 정보가 다릅니다: {key}")
        output = report.get("output")
        if run["case_id"] in ids:
            if not output or output.get("valid") is not True:
                raise ValueError(f"적합 사례의 산출물이 없습니다: {key}")
            identity = output["artifact"]["data"]["artifact_id"]
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError(
                    f"산출물 ID가 비어 있거나 문자열이 아닙니다: {run['case_id']}"
                )
            ids[run["case_id"]][run["repetition"]] = identity
    if seen != planned or batch["planned_runs"] != len(planned):
        raise ValueError("예정한 반복 실행의 결과가 부족합니다.")
    for case_id, identities in ids.items():
        if set(identities) != repetitions or len(set(identities.values())) != 1:
            raise ValueError(
                f"반복 실행의 산출물 ID가 다르거나 누락됐습니다: {case_id}"
            )
    for base_id, case_id in pairs:
        if ids[base_id] != ids[case_id]:
            raise ValueError(f"필터 순서 변경 후 산출물 ID가 달라졌습니다: {case_id}")
    print(
        f"적합 산출물 ID {sum(len(values) for values in ids.values())}개 확인; "
        f"필터 순서 {len(pairs)}개 기준 쌍 × {len(repetitions)}회 "
        f"= {len(pairs) * len(repetitions)}쌍 및 적합 사례 전체의 반복 동일성 확인"
    )


if __name__ == "__main__":
    main()
