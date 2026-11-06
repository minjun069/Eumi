"""report.json들을 외부 의존성 없는 한 개의 HTML 뷰어로 묶는다."""

import argparse
import json
from pathlib import Path


def build_report(inputs: list[Path], output: Path) -> None:
    paths = []
    for source in inputs:
        if source.is_dir():
            paths.extend(sorted(source.rglob("report.json")))
        else:
            paths.append(source)
    paths = list(dict.fromkeys(p.resolve() for p in paths))
    if not paths:
        raise ValueError("report.json을 찾을 수 없습니다.")
    documents = [
        {
            "name": f"{p.parent.name}/{p.name}",
            "value": json.loads(p.read_text(encoding="utf-8-sig")),
        }
        for p in paths
    ]
    # HTML의 script 종료 태그로 자료가 해석되지 않도록 JSON을 이스케이프한다.
    payload = json.dumps(documents, ensure_ascii=False).replace("&", "\\u0026")
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e")
    template = (
        Path(__file__).with_name("report_viewer.html").read_text(encoding="utf-8")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        template.replace("/*__REPORT_DATA__*/[]", payload), encoding="utf-8"
    )
    print(f"{output.resolve()} ({len(paths)} reports)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+", help="JSON 파일 또는 결과 폴더")
    parser.add_argument("--output", type=Path, required=True, help="생성할 HTML 파일")
    args = parser.parse_args()
    build_report(args.inputs, args.output)
