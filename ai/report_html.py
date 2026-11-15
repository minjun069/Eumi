"""뷰어 소스와 실행·평가 결과 JSON을 외부 의존성 없는 HTML 한 개로 묶는다."""

import argparse
import base64
import json
import re
from html import escape
from pathlib import Path


def _data_payload(paths: list[Path]) -> str:
    documents = [
        {
            "name": f"{p.parent.name}/{p.name}",
            "value": json.loads(p.read_text(encoding="utf-8-sig")),
        }
        for p in dict.fromkeys(p.resolve() for p in paths)
    ]
    # HTML의 script 종료 태그로 자료가 해석되지 않도록 JSON을 이스케이프한다.
    payload = json.dumps(documents, ensure_ascii=False).replace("&", "\\u0026")
    return payload.replace("<", "\\u003c").replace(">", "\\u003e")


def _render_report(payload: str, evaluation_payload: str) -> str:
    """이미 HTML에 안전하게 이스케이프한 JSON 본문을 재직렬화 없이 묶는다.

    기존 보고서 갱신 시 두 application/json script의 내부 문자열을 그대로
    전달하면 이름·순서·값뿐 아니라 공백과 이스케이프 표기도 보존한다.
    """
    source_dir = Path(__file__).parent
    template = (source_dir / "report_viewer.html").read_text(encoding="utf-8")
    css = (source_dir / "report_viewer/styles.css").read_text(encoding="utf-8")
    assets = source_dir / "report_viewer/assets"
    font = base64.b64encode((assets / "PretendardVariable.woff2").read_bytes()).decode(
        "ascii"
    )
    css = re.sub(
        r"url\(\s*([\"']?)assets/PretendardVariable\.woff2\1\s*\)",
        lambda _: f'url("data:font/woff2;base64,{font}")',
        css,
    )
    license_text = (assets / "Pretendard.LICENSE.txt").read_text(encoding="utf-8")
    template = re.sub(
        r'<link\s+rel="stylesheet"\s+href="report_viewer/styles\.css"\s*/?>',
        lambda _: "<style>\n" + css + "\n</style>",
        template,
    )
    scripts = []
    for script_path in (
        "report_viewer/data.js",
        "eval/viewers/report/evaluation-catalog.js",
        "eval/viewers/report/evaluation.js",
        "report_viewer/components.js",
        "eval/viewers/report/evaluation-view.js",
        "report_viewer/app.js",
    ):
        source = (source_dir / script_path).read_text(encoding="utf-8")
        template = template.replace(f'<script defer src="{script_path}"></script>', "")
        scripts.append("<script>\n" + source + "\n</script>")
    # defer는 인라인 스크립트에 적용되지 않으므로 DOM·보고서 데이터 뒤에 넣는다.
    license_template = (
        '<template id="pretendard-license">' + escape(license_text) + "</template>"
    )
    template = template.replace(
        "</body>", license_template + "\n" + "\n".join(scripts) + "\n  </body>"
    )
    template = template.replace(
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
        "script-src 'unsafe-inline'; style-src 'unsafe-inline'",
    )
    template = template.replace("font-src 'self' data:", "font-src data:")
    payloads = {"report-data": payload, "evaluation-data": evaluation_payload}
    # placeholder 바깥의 템플릿 공백도 치환해야 기존 script 본문의 해시가 유지된다.
    template = re.sub(
        r'(<script\b[^>]*\bid="(report-data|evaluation-data)"[^>]*>).*?(</script\s*>)',
        lambda match: match[1] + payloads[match[2]] + match[3],
        template,
        flags=re.DOTALL,
    )
    return template


def build_report(
    inputs: list[Path], output: Path, evaluations: list[Path] | None = None
) -> None:
    paths = []
    for source in inputs:
        if source.is_dir():
            paths.extend(sorted(source.rglob("report.json")))
        else:
            paths.append(source)
    paths = list(dict.fromkeys(p.resolve() for p in paths))
    if not paths:
        raise ValueError("report.json을 찾을 수 없습니다.")
    template = _render_report(_data_payload(paths), _data_payload(evaluations or []))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template, encoding="utf-8")
    print(f"{output.resolve()} ({len(paths)} reports)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+", help="JSON 파일 또는 결과 폴더")
    parser.add_argument("--output", type=Path, required=True, help="생성할 HTML 파일")
    parser.add_argument(
        "--evaluation",
        type=Path,
        nargs="+",
        action="extend",
        help="평가 결과 JSON 파일",
    )
    args = parser.parse_args()
    build_report(args.inputs, args.output, args.evaluation)
