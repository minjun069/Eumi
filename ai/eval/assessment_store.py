"""채점 결과 전체를 하나의 JSON 파일로 저장하고 읽는다."""

import json
from pathlib import Path

from src.execution_trace import TraceRecorder


def load_assessment(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("채점 JSON 객체가 필요합니다")
    return value


def write_assessment(path: Path, result: dict, *, source_batch: Path) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError("채점 결과는 기존 파일을 덮어쓸 수 없습니다")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(TraceRecorder().snapshot(result), ensure_ascii=False, indent=2)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload + "\n")
