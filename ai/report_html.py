"""분리된 뷰어 소스와 report.json을 외부 의존성 없는 HTML 한 개로 묶는다."""

import argparse
import json
import re
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
    source_dir = Path(__file__).parent
    template = (source_dir / "report_viewer.html").read_text(encoding="utf-8")
    css = (source_dir / "report_viewer/styles.css").read_text(encoding="utf-8")
    template = re.sub(
        r'<link\s+rel="stylesheet"\s+href="report_viewer/styles\.css"\s*/?>',
        lambda _: "<style>\n" + css + "\n</style>",
        template,
    )
    scripts = []
    for name in ("data", "components", "app"):
        source = (source_dir / f"report_viewer/{name}.js").read_text(encoding="utf-8")
        template = template.replace(
            f'<script defer src="report_viewer/{name}.js"></script>', ""
        )
        scripts.append("<script>\n" + source + "\n</script>")
    # defer는 인라인 스크립트에 적용되지 않으므로 DOM·보고서 데이터 뒤에 넣는다.
    template = template.replace("</body>", "\n".join(scripts) + "\n  </body>")
    template = template.replace(
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
        "script-src 'unsafe-inline'; style-src 'unsafe-inline'",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        re.sub(r"/\*__REPORT_DATA__\*/\s*\[\]", lambda _: payload, template),
        encoding="utf-8",
    )
    print(f"{output.resolve()} ({len(paths)} reports)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+", help="JSON 파일 또는 결과 폴더")
    parser.add_argument("--output", type=Path, required=True, help="생성할 HTML 파일")
    args = parser.parse_args()
    build_report(args.inputs, args.output)
