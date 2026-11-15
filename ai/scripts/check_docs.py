"""Check indexed AI documents and incoming Markdown links without network access."""

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

AI = Path(__file__).resolve().parents[1]
REPO = AI.parent
DOCS = AI / "docs"
EVAL = AI / "eval"
EVAL_DOCS = EVAL / "docs"
LINK = re.compile(r"!?\[[^\]\n]*\]\((<[^>\n]+>|[^\s)\n]+)(?:\s+\"[^\"\n]*\")?\)")


def prose(path: Path) -> str:
    """Blank fenced code while retaining line numbers for diagnostics."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    marker = ""
    result = []
    for line in lines:
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            token = fence[1]
            if not marker:
                marker = token
            elif token[0] == marker[0] and len(token) >= len(marker):
                marker = ""
            result.append("")
        else:
            result.append("" if marker else line)
    return "\n".join(result)


def local_links(path: Path) -> list[tuple[int, Path, str]]:
    body = prose(path)
    result = []
    # Archived bytes and hashed criterion text retain their original link base.
    archive_directories = {
        EVAL_DOCS / "originals",
        EVAL_DOCS / "nodes" / "originals",
    }
    preserved = path.parent in archive_directories or (
        path.suffix == ".json" and path.parent == EVAL_DOCS / "nodes"
    )
    base = path.parent.parent if path.parent in archive_directories else path.parent
    if preserved:
        base = DOCS / "eval" / base.relative_to(EVAL_DOCS)
    elif (
        path.parent == EVAL / "scenarios/nodes-insight-review/before-activity-revision"
    ):
        preserved = True
        base = AI / "evaluation/scenarios/nodes-insight-review"
    elif path == EVAL / "scenarios/nodes-extended-v2/README.md":
        preserved = True
        base = AI / "evaluation/scenarios/nodes-extended-v2"
    for match in LINK.finditer(body):
        target = urlsplit(match[1].strip("<>"))
        if target.scheme or target.netloc:
            continue
        destination = (base / unquote(target.path)).resolve() if target.path else path
        if preserved and target.path:
            if destination == DOCS / "runtime" / "evaluation-runner.md":
                destination = EVAL_DOCS / "runner.md"
            elif destination.is_relative_to(DOCS / "eval"):
                destination = EVAL_DOCS / destination.relative_to(DOCS / "eval")
            elif destination.is_relative_to(AI / "evaluation"):
                destination = EVAL / destination.relative_to(AI / "evaluation")
            elif destination in {
                AI / "scripts/build_node_dataset.py",
                AI / "scripts/validate_node_dataset.py",
            }:
                destination = EVAL / "scripts" / destination.name
        result.append(
            (
                body.count("\n", 0, match.start()) + 1,
                destination,
                unquote(target.fragment),
            )
        )
    return result


def anchors(path: Path) -> set[str]:
    body = prose(path)
    result = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', body))
    for heading in re.findall(r"^#{1,6}\s+(.+?)(?:\s+#+)?$", body, re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        unique = slug
        suffix = 0
        while unique in result:
            suffix += 1
            unique = f"{slug}-{suffix}"
        result.add(unique)
    return result


def main() -> int:
    index = DOCS / "README.md"
    indexed = {
        target
        for _, target, _ in local_links(index)
        if target.suffix == ".md"
        and (target.is_relative_to(DOCS) or target.is_relative_to(EVAL_DOCS))
    }
    sources = indexed | {
        index,
        AI / "README.md",
        AI / "AGENTS.md",
        REPO.parent / "AGENTS.md",
    }
    errors = []
    checked_links = 0
    anchor_cache = {}
    # Find incoming references; Git excludes ignored generated outputs.
    listing = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "*.md",
        ],
        cwd=REPO,
        capture_output=True,
        check=True,
    )
    candidates = {
        REPO / name.decode("utf-8") for name in listing.stdout.split(b"\0") if name
    }
    sources |= {
        path
        for path in candidates
        if path.is_relative_to(EVAL) and not path.is_relative_to(EVAL / "outputs")
    }
    definitions = set((EVAL_DOCS / "nodes").glob("*.json"))
    for path in sorted(sources | candidates | definitions):
        if not path.exists():
            if path in sources:
                errors.append(f"{path}: missing document")
            continue
        for line, target, anchor in local_links(path):
            if path not in sources | definitions and not (
                target.is_relative_to(DOCS) or target.is_relative_to(EVAL)
            ):
                continue
            checked_links += 1
            location = f"{path}:{line}"
            if not target.exists():
                errors.append(f"{location}: missing target {target}")
            elif anchor and target.suffix == ".md":
                if target not in anchor_cache:
                    anchor_cache[target] = anchors(target)
                if anchor not in anchor_cache[target]:
                    errors.append(f"{location}: missing anchor {target}#{anchor}")
    for path in sorted(definitions):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            bound_rows = set()
            for binding in data["bindings"]:
                row = binding["row"]
                if type(row) is not int or not 0 <= row < len(data["checks"]):
                    raise ValueError(f"invalid binding row {row!r}")
                if row in bound_rows:
                    raise ValueError(f"duplicate binding row {row}")
                bound_rows.add(row)
                for ref in binding["principles"]:
                    target = (AI / ref["path"]).resolve()
                    if target not in definitions:
                        raise ValueError(f"unregistered principle file {target}")
                    values = json.loads(target.read_text(encoding="utf-8"))
                    if ref["key"] not in {p["key"] for p in values["principles"]}:
                        raise ValueError(f"missing principle {ref}")
            if bound_rows != set(range(len(data["checks"]))):
                raise ValueError("missing criterion bindings")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path}: invalid criterion reference: {exc}")
    for path in sorted(indexed):
        if path.name != "README.md" and not re.fullmatch(
            r"[a-z]+(?:-[a-z]+)*\.md", path.name
        ):
            errors.append(f"{path}: use lowercase words separated by hyphens")
        if path.parent not in {
            DOCS,
            DOCS / "agent",
            DOCS / "runtime",
            EVAL_DOCS,
            EVAL_DOCS / "nodes",
            EVAL_DOCS / "execution",
        }:
            errors.append(
                f"{path}: indexed specification is outside the documented layout"
            )
    for error in errors:
        print(error)
    print(
        f"AI docs: {len(sources)} source documents, "
        f"{checked_links} links, {len(errors)} errors"
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
