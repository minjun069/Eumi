"""한국사회보장정보원 복지서비스 상세 정보 CSV 에서 시연에 쓸 서비스(welfare_picks.PICKS)만 뽑아 source/welfare_services.csv 로 저장한다.

  python data/demo_seed/extract_welfare.py "<내려받은 CSV 경로>" [...]

- 원본은 CP949. 원본에서 가운뎃점(·)이 '?' 로 깨져 있어 글자 사이의 '?' 는 '·' 로, 항목 앞의 '? ' 는 '- ' 로 되돌린다.
- 이미 저장된 행은 서비스ID 기준으로 덮어쓴다 (지역별 파일을 여러 번 넣을 수 있음).
- 결과 파일은 저장소에 커밋한다. 시드 생성(make_demo_seed.py)은 원본 대신 이 파일만 읽는다.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from welfare_picks import PICKS  # noqa: E402

OUT = HERE / "source" / "welfare_services.csv"
COLUMNS = ["서비스ID", "서비스명", "시행시작일자", "시행종료일자", "사업담당부서명", "시도명", "시군구명",
           "생애주기명", "가구상황명", "서비스 요약", "지원대상 내용", "급여서비스 내용", "신청방법 내용", "신청방법명", "최종수정일자"]


def clean(text: str) -> str:
    text = re.sub(r"(?<=\S)\?(?=\S)", "·", text or "")
    text = re.sub(r"(^|\s)\?\s", r"\1- ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def read_raw(path: Path) -> list[dict]:
    for enc in ("utf-8-sig", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[FAIL] 인코딩을 알 수 없음: {path}")


def main(paths: list[str]) -> None:
    if not paths:
        raise SystemExit(__doc__)
    rows: dict[str, dict] = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8", newline="") as f:
            rows = {r["서비스ID"]: r for r in csv.DictReader(f)}
    for p in paths:
        raw = read_raw(Path(p))
        missing = set(COLUMNS) - set(raw[0].keys())
        if missing:
            raise SystemExit(f"[FAIL] {p}: 컬럼 없음 {sorted(missing)}")
        hit = 0
        for r in raw:
            if r["서비스ID"] in PICKS:
                rows[r["서비스ID"]] = {c: clean(r[c]) for c in COLUMNS}
                hit += 1
        print(f"[OK] {p}: {len(raw)}건 중 {hit}건")
    lost = sorted(set(PICKS) - set(rows))
    if lost:
        raise SystemExit(f"[FAIL] 원본에서 못 찾은 서비스: {lost}")
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        for sid in sorted(rows):
            w.writerow(rows[sid])
    print(f"[OK] {OUT.relative_to(HERE.parent.parent)}: {len(rows)}건")


if __name__ == "__main__":
    main(sys.argv[1:])
