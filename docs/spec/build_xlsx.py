"""docs/spec의 md 원본으로 엑셀(열람·제출용)을 만든다.

사용법 (저장소 어디에서 실행해도 된다):
    python docs/spec/build_xlsx.py            # 엑셀 3개를 docs/spec에 다시 만든다
    python docs/spec/build_xlsx.py --check    # md 형식만 검사하고 파일은 쓰지 않는다

필요한 것: Python 3.10 이상, openpyxl (pip install openpyxl)

md 형식 (README.md 'md 형식' 절):
- `## 시트 이름`으로 시트를 나눈다. 바로 아래 `- 제목:` `- 요약:` `- 출처:` 등 머리 줄을 둔다.
- 표 시트: 마크다운 표 하나. 묶음 열이 있는 시트는 `### 묶음 값` 아래에 표를 나눠 둔다.
- 항목 시트: `### ID 제목` 아래에 `- 열 이름: 값` 줄을 둔다.
- 칸 안의 줄바꿈은 `<br>`, 표 칸 안의 `|`는 `\\|`로 쓴다.
- SQL 원문 시트: sql 코드 블록의 `-- @MIGRATIONS` 줄을 db/migration의 V 파일(버전 순서)로 바꿔 넣는다.

같은 md로 다시 만들면 내용이 같은 엑셀이 나온다 (zip 시각·문서 속성 고정).
내용이 같으면 파일을 다시 쓰지 않으므로, 다른 PC에서 만들어도 git에 변경이 생기지 않는다.
"""
from __future__ import annotations

import argparse
import io
import math
import re
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

try:
    import openpyxl
    from openpyxl.formatting.rule import Rule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.styles.differential import DifferentialStyle
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    sys.exit("openpyxl이 필요합니다: pip install openpyxl")

SPEC_DIR = Path(__file__).resolve().parent
REPO_DIR = SPEC_DIR.parent.parent
MIGRATION_DIR = REPO_DIR / "db" / "migration"

FONT = "맑은 고딕"
TEXT = "FF111111"
DARK = ("FF23475C", "FFFFFFFF")   # 머리 행 채움 · 글자
LIGHT = ("FFC5E9F5", "FF17384C")
LINE = Side(style="thin", color="FFBFC7CF")
FIXED_TIME = datetime(2026, 1, 1)

# 시트마다: 배치(table · items · sql), 열, 너비, 정렬, 머리 행 색, 탭 색, 틀 고정
# table: group = 묶음 열(### 제목으로 나눔), int_cols = 숫자로 쓸 열
# items: id = 제목 줄 첫 단어 열, title = 제목 줄 나머지 열(없으면 제목 줄 전체가 id)
DOCS = {
    "table-definition.md": {
        "xlsx": "이음이_테이블_정의서.xlsx",
        "sheets": {
            "테이블 목록": dict(layout="table", group="영역",
                cols=["영역", "테이블", "논리명", "컬럼 수", "PK", "용도", "기준 파일"],
                widths=[14.4, 41.2, 46.2, 11.2, 50.0, 56.2, 32.5], int_cols=["컬럼 수"],
                head=DARK, tab="FF808080", freeze="C7"),
            "컬럼 정의": dict(layout="table", group="테이블",
                cols=["테이블", "순번", "컬럼", "논리명", "타입", "필수", "PK", "FK 대상", "기본값", "정의 원문", "기준 파일"],
                widths=[41.2, 8.2, 41.2, 65.0, 21.2, 9.4, 8.2, 41.2, 33.8, 81.2, 32.5], int_cols=["순번"],
                head=DARK, tab="FF808080", freeze="D7"),
            "관계": dict(layout="table",
                cols=["관계명", "자식 테이블", "자식 컬럼", "부모 테이블", "부모 컬럼", "삭제 규칙", "스키마 경계", "기준 파일"],
                widths=[45.0, 40.0, 37.5, 40.0, 37.5, 16.2, 18.8, 32.5],
                head=DARK, tab="FFFBE3D6", freeze="B7"),
            "제약조건": dict(layout="table", group="테이블",
                cols=["테이블", "종류", "제약명", "정의", "기준 파일"],
                widths=[40.0, 18.8, 50.0, 122.5, 32.5],
                head=DARK, tab="FFFBE3D6", freeze="C7"),
            "인덱스": dict(layout="table", group="테이블",
                cols=["테이블", "인덱스명", "정의", "기준 파일"],
                widths=[42.5, 53.8, 112.5, 33.8],
                head=DARK, tab="FFCAEEFB", freeze="C7"),
            "뷰": dict(layout="table",
                cols=["뷰", "용도", "기준 파일"],
                widths=[48.8, 125.0, 35.0],
                head=DARK, tab="FFCAEEFB", freeze="B7"),
            "뷰 컬럼": dict(layout="table", group="뷰",
                cols=["뷰", "출력 컬럼", "SELECT 표현식", "NULL 처리", "기준 파일"],
                widths=[42.5, 35.0, 137.5, 46.2, 33.8],
                head=DARK, tab="FFCAEEFB", freeze="C7"),
            "함수": dict(layout="items", id="함수",
                cols=["함수", "인자", "반환", "언어", "목적", "잠금", "주의", "기준 파일"],
                widths=[42.5, 53.8, 17.5, 16.2, 48.8, 42.5, 75.0, 33.8],
                head=DARK, tab="FFF2CFEE", freeze="B7"),
            "트리거": dict(layout="items", id="트리거",
                cols=["트리거", "테이블", "이벤트", "시점", "행 수준", "함수", "목적", "상태", "기준 파일"],
                widths=[28.8, 30.0, 17.5, 13.0, 13.0, 32.5, 50.0, 28.8, 32.5],
                head=DARK, tab="FFF2CFEE", freeze="B7"),
            "SQL 원문": dict(layout="sql", cols=["줄", "SQL"], widths=[10.0, 231.2],
                align="left", head=DARK, tab="FF000000", freeze="B7"),
        },
    },
    "api-spec.md": {
        "xlsx": "이음이_API_명세표.xlsx",
        "sheets": {
            "API 목록": dict(layout="items", id="ID", title="기능",
                cols=["ID", "페이지 범위", "기능", "요청 경로", "요청 형식", "응답 형식", "구현 (11/6)"],
                widths=[13.2, 31.2, 28.8, 56.2, 76.2, 81.2, 24.0],
                head=LIGHT, tab="FF23475C", freeze="C7"),
            "내부 AI API": dict(layout="items", id="ID", title="기능",
                cols=["ID", "구간", "기능", "요청 경로", "요청 형식", "응답 형식"],
                widths=[13.2, 31.2, 28.8, 56.2, 76.2, 81.2],
                head=LIGHT, tab="FF23475C", freeze="C7"),
            "별도 범위": dict(layout="items", id="구분",
                cols=["구분", "대상", "현재 근거", "경계", "선행 조건", "검증"],
                widths=[16.2, 30.0, 38.8, 36.2, 58.8, 40.0],
                head=DARK, tab="FF6D91A8", freeze="C7"),
        },
    },
    "requirements.md": {
        "xlsx": "이음이_기능명세표.xlsx",
        "sheets": {
            name: dict(layout="items", id="요구사항 ID", title="요구사항명",
                cols=["요구사항 ID", "영역", "요구사항명", "요구사항 상세와 처리 결과", "대상 및 입력 조건",
                      "검증 기준", "기능 및 API와 작업", "정의 상태", "데이터와 저장 경계"],
                widths=[18.8, 17.5, 51.2, 81.2, 65.0, 75.0, 55.0, 21.2, 50.0],
                align="left", head=DARK, tab=tab, freeze="C7", waiting_col="정의 상태")
            for name, tab in (("기능 요구사항", "FF23475C"), ("비기능 요구사항", "FF606B76"))
        },
    },
}


class SpecError(Exception):
    pass


# ---------- md 읽기 ----------

def unescape(text: str, table: bool) -> str | None:
    if table:
        text = text.replace("\\|", "|")
    text = text.replace("<br>", "\n")
    return text if text != "" else None


def split_row(line: str) -> list[str]:
    body = line.strip()
    if not (body.startswith("|") and body.endswith("|")):
        raise SpecError(f"표 줄 형식이 아닙니다: {line[:80]}")
    cells, cur, i = [], "", 1
    while i < len(body) - 1:
        if body[i] == "\\" and body[i + 1] == "|":
            cur += "\\|"
            i += 2
            continue
        if body[i] == "|":
            cells.append(cur)
            cur = ""
        else:
            cur += body[i]
        i += 1
    cells.append(cur)
    return [c.strip() for c in cells]


def parse_meta(lines: list[str], i: int) -> tuple[dict, int]:
    """시트 머리의 '- 이름: 값' 줄을 읽는다. 처음 나오는 빈 줄 아닌 다른 줄에서 멈춘다."""
    meta = {}
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    while i < len(lines) and lines[i].startswith("- "):
        key, sep, value = lines[i][2:].partition(":")
        if not sep:
            raise SpecError(f"머리 줄은 '- 이름: 값' 형식이어야 합니다: {lines[i]}")
        meta[key.strip()] = value.strip()
        i += 1
    return meta, i


def parse_table(lines: list[str], i: int, cols: list[str], sheet: str) -> tuple[list[list], int]:
    while i < len(lines) and not lines[i].startswith("|"):
        if lines[i].startswith("#"):
            raise SpecError(f"[{sheet}] 표가 없습니다")
        i += 1
    header = split_row(lines[i])
    if header != cols:
        raise SpecError(f"[{sheet}] 표 머리 열이 다릅니다: {header} (기대: {cols})")
    rows = []
    i += 2  # 구분 줄
    while i < len(lines) and lines[i].startswith("|"):
        cells = split_row(lines[i])
        if len(cells) != len(cols):
            raise SpecError(f"[{sheet}] 칸 수가 다릅니다 ({len(cells)}/{len(cols)}): {lines[i][:80]}")
        rows.append([unescape(c, True) for c in cells])
        i += 1
    return rows, i


def parse_sheet(name: str, cfg: dict, body: list[str]) -> dict:
    meta, i = parse_meta(body, 0)
    if "제목" not in meta:
        raise SpecError(f"[{name}] '- 제목:' 줄이 없습니다")
    cols = cfg["cols"]
    rows: list[list] = []
    layout = cfg["layout"]
    if layout == "table" and "group" not in cfg:
        rows, i = parse_table(body, i, cols, name)
    elif layout == "table":
        gi = cols.index(cfg["group"])
        sub = [c for c in cols if c != cfg["group"]]
        while i < len(body):
            line = body[i]
            if line.startswith("### "):
                group = line[4:].strip()
                part, i = parse_table(body, i + 1, sub, name)
                for r in part:
                    rows.append(r[:gi] + [group] + r[gi:])
            else:
                i += 1
    elif layout == "items":
        id_col, title_col = cfg["id"], cfg.get("title")
        keys = [c for c in cols if c not in (id_col, title_col)]
        item = None
        for line in body[i:]:
            if line.startswith("### "):
                if item is not None:
                    rows.append([item.get(c) for c in cols])
                head = line[4:].strip()
                if title_col:
                    ident, _, title = head.partition(" ")
                    item = {id_col: ident, title_col: unescape(title, False)}
                else:
                    item = {id_col: unescape(head, False)}
            elif line.startswith("- ") and item is not None:
                for key in sorted(keys, key=len, reverse=True):
                    if line.startswith(f"- {key}:"):
                        value = line[len(key) + 3:]
                        item[key] = unescape(value[1:] if value.startswith(" ") else value, False)
                        break
                else:
                    raise SpecError(f"[{name}] 모르는 열 이름입니다: {line[:60]}")
            elif line.strip() and item is not None and not line.startswith("<!--"):
                raise SpecError(f"[{name}] 항목 안에는 '- 열 이름: 값' 줄만 둡니다: {line[:60]}")
        if item is not None:
            rows.append([item.get(c) for c in cols])
    elif layout == "sql":
        block = "\n".join(body[i:])
        m = re.search(r"```sql\n(.*?)\n```", block, re.S)
        if not m:
            raise SpecError(f"[{name}] sql 코드 블록이 없습니다")
        sql_lines = []
        for line in m.group(1).split("\n"):
            if line.strip() == "-- @MIGRATIONS":
                sql_lines.extend(migration_lines())
            else:
                sql_lines.append(line)
        rows = [[n, (s if s != "" else None)] for n, s in enumerate(sql_lines, 1)]
    for col in cfg.get("int_cols", []):
        ci = cols.index(col)
        for r in rows:
            if r[ci] is not None:
                if not re.fullmatch(r"\d+", r[ci]):
                    raise SpecError(f"[{name}] '{col}'은 숫자여야 합니다: {r[ci]}")
                r[ci] = int(r[ci])
    if layout != "sql":
        seen = set()
        for r in rows:
            if r[0] is None:
                raise SpecError(f"[{name}] 첫 열이 빈 행이 있습니다")
        if layout == "items":
            for r in rows:
                if r[0] in seen:
                    raise SpecError(f"[{name}] ID가 겹칩니다: {r[0]}")
                seen.add(r[0])
    return {"meta": meta, "rows": rows}


def flyway_key(path: Path) -> tuple:
    m = re.match(r"V(\d+)(?:_(\d+))?__", path.name)
    return (int(m.group(1)), int(m.group(2) or 0))


def migration_lines() -> list[str]:
    files = sorted(MIGRATION_DIR.glob("V*__*.sql"), key=flyway_key)
    if not files:
        raise SpecError(f"V 파일을 찾지 못했습니다: {MIGRATION_DIR}")
    out = []
    for f in files:
        text = f.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n")
        out.append(f"-- SOURCE {f.name}")
        out.extend(text.split("\n"))
        out.append("")
    return out


def parse_doc(md_name: str) -> dict:
    spec = DOCS[md_name]
    text = (SPEC_DIR / md_name).read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    first = next((k for k, l in enumerate(lines) if l.startswith("## ")), len(lines))
    doc_meta = {}
    for line in lines[:first]:
        key, sep, value = line[2:].partition(":") if line.startswith("- ") else ("", "", "")
        if sep:
            doc_meta[key.strip()] = value.strip()
    sections: dict[str, list[str]] = {}
    current = None
    in_code = False
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    missing = [s for s in spec["sheets"] if s not in sections]
    extra = [s for s in sections if s not in spec["sheets"]]
    if missing or extra:
        raise SpecError(f"{md_name}: 시트가 맞지 않습니다 (빠짐 {missing}, 모르는 시트 {extra})")
    sheets = {name: parse_sheet(name, cfg, sections[name]) for name, cfg in spec["sheets"].items()}
    if "테이블 목록" in sheets and "컬럼 정의" in sheets:
        counts: dict[str, int] = {}
        for r in sheets["컬럼 정의"]["rows"]:
            counts[r[0]] = counts.get(r[0], 0) + 1
        for r in sheets["테이블 목록"]["rows"]:
            if r[3] != counts.get(r[1], 0):
                raise SpecError(f"[테이블 목록] {r[1]}의 컬럼 수 {r[3]}이 컬럼 정의 행 수 {counts.get(r[1], 0)}와 다릅니다")
    return {"meta": doc_meta, "sheets": sheets}


# ---------- 엑셀 쓰기 ----------

def text_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def row_height(values: list, widths: list[float]) -> float:
    lines = 1
    for v, w in zip(values, widths):
        if v is None:
            continue
        per = max(int(w * 1.1) - 2, 4)
        need = sum(max(1, math.ceil(text_width(part) / per)) for part in str(v).split("\n"))
        lines = max(lines, need)
    return max(25.5, round(lines * 15.5 + 9, 1))


def build_workbook(md_name: str, doc: dict) -> bytes:
    spec = DOCS[md_name]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    version = doc["meta"].get("판", "")
    for name, cfg in spec["sheets"].items():
        data = doc["sheets"][name]
        meta, rows, cols, widths = data["meta"], data["rows"], cfg["cols"], cfg["widths"]
        ws = wb.create_sheet(name)
        ncol = len(cols)
        last = get_column_letter(ncol)
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = cfg["tab"]
        for ci, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(ci)].width = w
        note = f"원본: docs/spec/{md_name}" + (f" · 판 {version}" if version else "") + " · 이 엑셀은 build_xlsx.py로 만든 파일이라 직접 고치지 않는다"
        summary = "  ".join(v for v in (meta.get("판"), meta.get("요약")) if v)
        source_key = next((k for k in meta if k not in ("제목", "요약", "판")), None)
        source = f"{source_key}: {meta[source_key]}" if source_key else None
        heads = [(1, note, Font(name=FONT, sz=9, color="FF6B7785"), 16.5),
                 (2, meta["제목"], Font(name=FONT, sz=15, b=True, color="FF000000"), 27.0),
                 (3, summary or None, Font(name=FONT, sz=11, color=TEXT), 22.5),
                 (4, source, Font(name=FONT, sz=11, color=TEXT), 22.5)]
        for r, value, font, height in heads:
            c = ws.cell(r, 1, value)
            c.font = font
            c.alignment = Alignment(vertical="center")
            ws.row_dimensions[r].height = height
            if r > 1:
                ws.merge_cells(f"A{r}:{last}{r}")
        ws.row_dimensions[5].height = 16.5
        fill, color = cfg["head"]
        for ci, col in enumerate(cols, 1):
            c = ws.cell(6, ci, col)
            c.font = Font(name=FONT, sz=11, b=True, color=color)
            c.fill = PatternFill("solid", fgColor=fill)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = Border(left=LINE, right=LINE, top=LINE, bottom=LINE)
        ws.row_dimensions[6].height = 31.0
        horizontal = cfg.get("align", "center")
        body_font = Font(name=FONT, sz=11, color=TEXT)
        for ri, row in enumerate(rows, 7):
            for ci, value in enumerate(row, 1):
                c = ws.cell(ri, ci, value)
                c.font = body_font
                c.alignment = Alignment(horizontal=horizontal, vertical="center", wrap_text=True)
                c.border = Border(left=LINE, right=LINE, top=LINE, bottom=LINE)
            ws.row_dimensions[ri].height = 18.0 if cfg["layout"] == "sql" else row_height(row, widths)
        ws.freeze_panes = cfg["freeze"]
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = "6:6"
        if cfg.get("waiting_col") and rows:
            col = get_column_letter(cols.index(cfg["waiting_col"]) + 1)
            rng = f"{col}7:{col}{6 + len(rows)}"
            dxf = DifferentialStyle(font=Font(color="FF7A4900"), fill=PatternFill(bgColor="FFFFF0D4"))
            rule = Rule(type="containsText", operator="containsText", text="대기", dxf=dxf)
            rule.formula = [f'NOT(ISERROR(SEARCH("대기",{col}7)))']
            ws.conditional_formatting.add(rng, rule)
    wb.properties.creator = "docs/spec/build_xlsx.py"
    wb.properties.lastModifiedBy = "docs/spec/build_xlsx.py"
    wb.properties.created = FIXED_TIME
    wb.properties.modified = FIXED_TIME
    raw = io.BytesIO()
    wb.save(raw)
    return fix_zip(raw.getvalue())


def fix_zip(data: bytes) -> bytes:
    """zip 항목 시각과 문서 속성 시각을 고정해 같은 입력이면 같은 바이트가 나오게 한다."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            body = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                body = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*", rb"\g<1>2026-01-01T00:00:00Z", body)
            item = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o600 << 16
            dst.writestr(item, body)
    return out.getvalue()


def zip_content(data: bytes) -> list[tuple[str, bytes]]:
    """압축 방식(zlib 판)과 상관없이 엑셀 안의 내용만 비교하려고 풀어 둔다."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return []
    return [(n, z.read(n)) for n in z.namelist()]


def main() -> int:
    ap = argparse.ArgumentParser(description="docs/spec md 원본으로 엑셀을 만든다")
    ap.add_argument("--check", action="store_true", help="형식만 검사하고 파일은 쓰지 않는다")
    ap.add_argument("--out", type=Path, default=SPEC_DIR, help="엑셀을 쓸 폴더 (기본: docs/spec)")
    args = ap.parse_args()
    try:
        for md_name, spec in DOCS.items():
            doc = parse_doc(md_name)
            counts = ", ".join(f"{n} {len(s['rows'])}" for n, s in doc["sheets"].items())
            if args.check:
                print(f"OK  {md_name}: {counts}")
                continue
            data = build_workbook(md_name, doc)
            args.out.mkdir(parents=True, exist_ok=True)
            target = args.out / spec["xlsx"]
            changed = not target.exists() or zip_content(target.read_bytes()) != zip_content(data)
            if changed:
                target.write_bytes(data)
            print(f"{'만듦' if changed else '같음'}  {spec['xlsx']} ← {md_name}: {counts}")
    except SpecError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
