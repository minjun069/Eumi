"""현행 실행기로 만든 파일을 과거 혼합 묶음의 저장 형태로 준비한다."""

import json
import shutil
from copy import deepcopy


def read_document(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def encoded_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def combine_batches(folders, destination):
    destination.mkdir(parents=True)
    batches = [read_document(folder / "batch.json") for folder in folders]
    suite = read_document(folders[0] / "suite.json")
    selected = {case_id for batch in batches for case_id in batch["plan"]["case_ids"]}
    batch = deepcopy(batches[0])
    batch["id"] = destination.name
    batch["plan"]["case_ids"] = [
        case["id"] for case in suite["cases"] if case["id"] in selected
    ]
    order = {case_id: i for i, case_id in enumerate(batch["plan"]["case_ids"])}
    batch["runs"] = sorted(
        [run for item in batches for run in item["runs"]],
        key=lambda run: (order[run["case_id"]], run["repetition"]),
    )
    batch["planned_runs"] = sum(item["planned_runs"] for item in batches)
    for folder in folders:
        for name in ("runs",):
            if (folder / name).exists():
                shutil.copytree(folder / name, destination / name, dirs_exist_ok=True)
    shutil.copy2(folders[0] / "suite.json", destination / "suite.json")
    (destination / "batch.json").write_bytes(encoded_bytes(batch))
    return destination
