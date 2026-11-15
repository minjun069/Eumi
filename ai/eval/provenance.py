"""평가 코드 지문과 이동 전 평가 기준의 원본 해시 조회."""

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent


def code_hashes(*names: str) -> dict[str, str]:
    """실행·채점 코드만 수집하고 eval 기준 상대 경로로 파일을 구분한다."""
    if names:
        paths = [PACKAGE_ROOT / name for name in names]
    else:
        paths = [
            *PACKAGE_ROOT.glob("*.py"),
            *PACKAGE_ROOT.joinpath("tools").rglob("*.py"),
            *PACKAGE_ROOT.joinpath("nodes").rglob("*.py"),
            *PACKAGE_ROOT.joinpath("execution").rglob("*.py"),
        ]
    return {
        path.relative_to(PACKAGE_ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def criterion_document_identity(name: str) -> str:
    """기준의 식별자는 디렉터리 이동 전 키로 유지한다."""
    if name.startswith("eval/docs/"):
        return "docs/eval/" + name.removeprefix("eval/docs/")
    return name


def previous_document_hash(saved: Mapping[str, str], name: str) -> str | None:
    """현재 경로가 없을 때만 이동 전 키를 읽으며 원본 해시는 바꾸지 않는다."""
    if name in saved:
        return saved[name]
    return saved.get(criterion_document_identity(name))
