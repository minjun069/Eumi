"""보관 원문과 승인된 문장 분리를 대조한다. 평가 실행에는 사용하지 않는다."""

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

AI = Path(__file__).resolve().parents[2]
NAMES = ("common", "interpret", "act", "decide", "compose", "ask")
CHECK_ID = re.compile(r"N(?:\d{2})?-[A-Z]\.\d+")
CHANGED_COLUMNS = {"적용 노드", "적용 조건", "평가 입력", "측정 방법", "성공 기준"}
ORIGINS = AI / "eval/tests/fixtures/node_criteria_origins.json"


def source_splits():
    return json.loads(ORIGINS.read_text(encoding="utf-8")).get("source_splits", {})


def source_revisions():
    return json.loads(ORIGINS.read_text(encoding="utf-8")).get("source_revisions", {})


def normalized_tables(text):
    """Markdown 표의 정렬 공백만 정규화한다. 셀 내부 문구는 바꾸지 않는다."""
    lines = []
    for line in text.splitlines():
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line[1:-1].split("|")]
            if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                cells = ["---"] * len(cells)
            line = "| " + " | ".join(cells) + " |"
        lines.append(line)
    return "\n".join(lines)


def replace_exact(text, replacements, identity):
    for replacement in replacements:
        before, after = replacement["before"], replacement["after"]
        if text.count(before) != 1:
            raise ValueError(f"{identity}: source changed or ambiguous")
        text = text.replace(before, after, 1)
    return text


def revised_principle(name, key, text, origins=None):
    """명시한 원문 구간만 분리하며, 대응 원문이 달라지면 보존 검사를 중단한다."""
    if origins is None:
        origins = json.loads(ORIGINS.read_text(encoding="utf-8"))
    text = normalized_tables(text)
    revisions = (
        origins.get("source_revisions", {})
        .get("principles", {})
        .get(name, {})
        .get(key, [])
    )
    text = replace_exact(text, revisions, f"{name}/{key} revision")
    replacements = (
        origins.get("source_splits", {})
        .get("principles", {})
        .get(name, {})
        .get(key, [])
    )
    return replace_exact(text, replacements, f"{name}/{key} split")


def rebase_links(text, source, destination):
    if source.parent.name == "originals":
        source = source.parent.parent / source.name

    def replace(match):
        target = urlsplit(match[1])
        if target.scheme or target.netloc:
            return match[0]
        resolved = (source.parent / target.path).resolve() if target.path else source
        relative = Path(os.path.relpath(resolved, destination.parent)).as_posix()
        return "(" + relative + ("#" + target.fragment if target.fragment else "") + ")"

    return re.sub(r"(?<=\])\(([^\s()]+)\)", replace, text)


def arrange_principle(text, layout, documents, identity):
    """원문을 독립 기록으로 배치하며, 빠지거나 중복 사용한 조건을 거부한다."""
    covered = set()

    def consume(fragment):
        if not fragment.strip() or text.count(fragment) != 1:
            raise ValueError(f"{identity}: layout source changed or ambiguous")
        start = text.index(fragment)
        positions = {
            index
            for index in range(start, start + len(fragment))
            if not text[index].isspace()
        }
        if covered & positions:
            raise ValueError(f"{identity}: layout source used more than once")
        covered.update(positions)

    result = {}
    for target in layout["targets"]:
        key, fragments, joiner = target["key"], target["fragments"], target["joiner"]
        if key in result or not fragments or joiner.strip():
            raise ValueError(f"{identity}: invalid layout target or joiner")
        for fragment in fragments:
            consume(fragment)
        result[key] = joiner.join(fragments)
    for removed in layout.get("removed", []):
        consume(removed["text"])
        target = removed["target"]
        principle = documents.get(target["name"], {}).get(target["key"])
        clauses = (
            [
                clause
                for clause in principle["selection"]["clauses"]
                if clause["id"] == target["clause_id"]
            ]
            if principle is not None
            else []
        )
        if len(clauses) != 1:
            raise ValueError(f"{identity}: removed condition has no canonical clause")
        start, end = clauses[0]["start"], clauses[0]["end"]
        canonical = principle["text"]
        if not 0 <= start < end <= len(canonical) or not canonical[start:end].strip():
            raise ValueError(
                f"{identity}: removed condition has invalid canonical clause"
            )
    if any(
        not char.isspace() and index not in covered for index, char in enumerate(text)
    ):
        raise ValueError(f"{identity}: layout source condition omitted")
    return result


def audit_principles(root=AI, origins=None):
    """보관 원문→명시된 변경→기록 재배치와 현행 원칙 전체를 대조한다."""
    if origins is None:
        origins = json.loads(ORIGINS.read_text(encoding="utf-8"))
    errors, documents = [], {}
    for name in NAMES:
        document = json.loads(
            (root / f"eval/docs/nodes/{name}.json").read_text(encoding="utf-8")
        )
        documents[name] = {item["key"]: item for item in document["principles"]}
        if len(documents[name]) != len(document["principles"]):
            errors.append(f"{name}: duplicate principle key")
    for name in NAMES:
        expected = {}
        layouts = origins.get("principle_layout", {}).get(name, {})
        if set(layouts) - set(origins["principles"][name]):
            errors.append(f"{name}: unknown layout source principle")
        for key, spans in origins["principles"][name].items():
            identity = f"{name}/{key}"
            try:
                fragments = []
                for span in spans:
                    source = root / span["path"]
                    lines = source.read_text(encoding="utf-8").splitlines()
                    first, last = span["first_line"], span["last_line"]
                    if not 1 <= first <= last <= len(lines):
                        raise ValueError(f"{identity}: invalid source span")
                    raw = "\n".join(lines[first - 1 : last]).strip()
                    fragments.append(
                        rebase_links(raw, source, root / f"eval/docs/nodes/{name}.json")
                    )
                text = fragments[0]
                for fragment in fragments[1:]:
                    adjacent_rows = text.splitlines()[-1].startswith(
                        "|"
                    ) and fragment.startswith("|")
                    text += ("\n" if adjacent_rows else "\n\n") + fragment
                text = revised_principle(name, key, text, origins)
                targets = (
                    arrange_principle(text, layouts[key], documents, identity)
                    if key in layouts
                    else {key: text}
                )
                if set(targets) & set(expected):
                    raise ValueError(f"{identity}: duplicate layout target principle")
                expected.update(targets)
            except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                errors.append(f"{identity}: {exc}")
        if set(expected) != set(documents[name]):
            errors.append(f"{name}: source and current principle keys differ")
        refinements = (
            origins.get("source_refinements", {}).get("principles", {}).get(name, {})
        )
        if set(refinements) - set(expected):
            errors.append(f"{name}: unknown principle refinement target")
        for key, text in expected.items():
            try:
                text = replace_exact(
                    text, refinements.get(key, []), f"{name}/{key} refinement"
                )
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if (
                key in documents[name]
                and normalized_tables(documents[name][key]["text"]) != text
            ):
                errors.append(
                    f"{name}/{key}: principle content differs from mapped source"
                )
    return errors


def original_rows(root=AI):
    result = {}
    for name in NAMES:
        path = f"eval/docs/nodes/originals/{name}.md"
        columns = None
        for number, line in enumerate(
            (root / path).read_text(encoding="utf-8").splitlines(), 1
        ):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells[0] == "검사 ID":
                columns = cells
            elif columns and CHECK_ID.fullmatch(cells[0]):
                if len(cells) != len(columns):
                    raise ValueError(f"{path}:{number}: original column mismatch")
                result[cells[0]] = {
                    "file": name,
                    "path": path,
                    "line": number,
                    "fields": dict(zip(columns, cells, strict=True)),
                }
    return result


def input_parts(value):
    result = {}
    for part in value.split("<br>"):
        category, names = part.removeprefix("- ").split(": ", 1)
        result[category] = names.split(", ")
    return result


def audit(root=AI):
    originals = original_rows(root)
    revisions = source_revisions()
    splits = source_splits().get("checks", {})
    refinements = (
        json.loads(ORIGINS.read_text(encoding="utf-8"))
        .get("source_refinements", {})
        .get("checks", {})
    )
    errors, records = audit_principles(root), []
    for key, basis in revisions.get("basis", {}).items():
        if basis["text"] not in (root / basis["path"]).read_text(encoding="utf-8"):
            errors.append(f"{key}: revision basis changed")
    for identifier, revision in revisions.get("checks", {}).items():
        if identifier not in originals or revision["basis"] not in revisions["basis"]:
            errors.append(f"{identifier}: unknown revision target or basis")
            continue
        fields = originals[identifier]["fields"]
        for column, change in revision.get("fields", {}).items():
            if fields.get(column) != change["before"]:
                errors.append(f"{identifier}: {column} revision source changed")
            else:
                fields[column] = change["after"]
    grouped = {}
    for name in NAMES:
        path = f"eval/docs/nodes/{name}.json"
        document = json.loads((root / path).read_text(encoding="utf-8"))
        bindings = {binding["row"]: binding for binding in document["bindings"]}
        for index, fields in enumerate(document["checks"]):
            identifier = fields["검사 ID"]
            source = originals.get(identifier)
            if source is None or source["file"] != name:
                errors.append(f"{path}:{index}: unknown original check {identifier}")
                continue
            original = source["fields"]
            identity = bindings[index]["row_id"]
            current_fields = fields
            fields = dict(fields)
            for column, changes in refinements.get(identity, {}).items():
                for change in reversed(changes):
                    if fields.get(column) != change["after"]:
                        errors.append(f"{identity}: {column} refinement target changed")
                        break
                    fields[column] = change["before"]
            if list(fields) != list(original):
                errors.append(f"{identity}: original column names/order changed")
            for column, value in original.items():
                if column not in CHANGED_COLUMNS and fields.get(column) != value:
                    errors.append(f"{identity}: {column} differs from original")
            if "적용 노드" in original and any(
                node not in original["적용 노드"].split("<br>")
                for node in fields["적용 노드"].split("<br>")
            ):
                errors.append(f"{identity}: 적용 노드 contains a value not in original")
            for column in ("측정 방법", "성공 기준"):
                available = original[column].split("<br>")
                selected = fields[column].split("<br>")
                for split in splits.get(identifier, {}).get(column, []):
                    if split["source"] not in original[column].split("<br>"):
                        errors.append(f"{identifier}: {column} split source changed")
                        continue
                    available.remove(split["source"])
                    parts = split["rows"].get(identity, [])
                    available.extend(parts)
                    if any(part not in selected for part in parts):
                        errors.append(f"{identity}: {column} split condition omitted")
                if any(sentence not in available for sentence in selected):
                    errors.append(f"{identity}: {column} contains rewritten text")
                if len(selected) != len(set(selected)):
                    errors.append(f"{identity}: {column} repeats a sentence")
            original_inputs = input_parts(original["평가 입력"])
            for category, labels in input_parts(fields["평가 입력"]).items():
                if any(
                    label not in original_inputs.get(category, []) for label in labels
                ):
                    errors.append(f"{identity}: evaluation input not in original cell")
            condition = fields["적용 조건"]
            revised_conditions = (
                revisions.get("checks", {}).get(identifier, {}).get("conditions", {})
            )
            if identity in revised_conditions:
                valid_condition = condition == revised_conditions[identity]
            else:
                valid_condition = condition == original[
                    "적용 조건"
                ] or condition.endswith(": " + original["적용 조건"])
            if not valid_condition:
                errors.append(f"{identity}: original applicability wording lost")
            grouped.setdefault(identifier, []).append((identity, fields))
            records.append(
                {
                    "row_id": identity,
                    "path": path,
                    "index": index,
                    "original": source,
                    "fields": current_fields,
                    "when": bindings[index]["when"],
                    "input_scopes": bindings[index].get("input_scopes", {}),
                }
            )
    if set(refinements) - {record["row_id"] for record in records}:
        errors.append("unknown refined check row")
    for identifier, source in originals.items():
        entries = grouped.get(identifier, [])
        if not entries:
            errors.append(f"{identifier}: missing original check")
            continue
        conditions = (
            revisions.get("checks", {}).get(identifier, {}).get("conditions", {})
        )
        if set(conditions) - {identity for identity, _ in entries}:
            errors.append(f"{identifier}: revision condition row missing")
        rows = [fields for _, fields in entries]
        original_inputs = input_parts(source["fields"]["평가 입력"])
        retained_inputs = {}
        for fields in rows:
            for category, labels in input_parts(fields["평가 입력"]).items():
                retained_inputs.setdefault(category, set()).update(labels)
        for category, labels in original_inputs.items():
            if missing := set(labels) - retained_inputs.get(category, set()):
                errors.append(
                    f"{identifier}: original input omitted: {sorted(missing)}"
                )
        if "적용 노드" in source["fields"]:
            original_nodes = set(source["fields"]["적용 노드"].split("<br>"))
            retained_nodes = {
                node for fields in rows for node in fields["적용 노드"].split("<br>")
            }
            if original_nodes != retained_nodes:
                errors.append(f"{identifier}: original node scope lost")
        for column in ("측정 방법", "성공 기준"):
            retained = {
                sentence for fields in rows for sentence in fields[column].split("<br>")
            }
            for sentence in source["fields"][column].split("<br>"):
                split = next(
                    (
                        item
                        for item in splits.get(identifier, {}).get(column, [])
                        if item["source"] == sentence
                    ),
                    None,
                )
                if split is not None:
                    row_ids = {identity for identity, _ in entries}
                    if not split["rows"] or set(split["rows"]) - row_ids:
                        errors.append(f"{identifier}: {column} split row missing")
                    if any(not parts for parts in split["rows"].values()):
                        errors.append(f"{identifier}: {column} empty split conditions")
                    continue
                if sentence not in retained:
                    errors.append(
                        f"{identifier}: original {column} sentence omitted: {sentence}"
                    )
    return errors, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    errors, records = audit()
    for error in errors:
        print(error)
    print(
        f"Node criteria migration: {len(original_rows())} original checks, "
        f"{len(records)} rows, {len(errors)} errors"
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
