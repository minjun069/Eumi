"""분리된 소스를 묶은 파일이 오프라인에서 안전하게 열리는지 확인한다."""

import base64
import hashlib
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

import report_html
from report_html import _render_report, build_report


class ReportDocument(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script_ids = []
        self.sources = []
        self.script_data = {}
        self.data_id = None
        self.styles = []
        self.in_style = False
        self.license_data = []
        self.in_license = False
        self.csp = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.script_ids.append(attrs.get("id"))
            self.data_id = attrs.get("id")
            if self.data_id in ("report-data", "evaluation-data"):
                self.script_data[self.data_id] = []
            else:
                self.data_id = None
            if "src" in attrs:
                self.sources.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.sources.append(attrs["href"])
        if tag == "style":
            self.in_style = True
        if tag == "template" and attrs.get("id") == "pretendard-license":
            self.in_license = True
        if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy":
            self.csp = attrs["content"]

    def handle_endtag(self, tag):
        if tag == "script":
            self.data_id = None
        if tag == "style":
            self.in_style = False
        if tag == "template":
            self.in_license = False

    def handle_data(self, data):
        if self.data_id:
            self.script_data[self.data_id].append(data)
        if self.in_style:
            self.styles.append(data)
        if self.in_license:
            self.license_data.append(data)

    def payload(self, element_id):
        return json.loads("".join(self.script_data[element_id]))


def test_offline_bundle_preserves_payload_without_script_injection(tmp_path):
    source = tmp_path / "report.json"
    value = {"state": {"request": {"goal": '</script><script id="injected">&'}}}
    source.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8-sig")
    output = tmp_path / "nested" / "report.html"
    build_report([source, source], output)
    document = ReportDocument()
    html = output.read_text(encoding="utf-8")
    document.feed(html)
    assert not document.sources
    assert document.script_ids.count("report-data") == 1
    assert "injected" not in document.script_ids
    assert document.payload("report-data") == [
        {"name": f"{tmp_path.name}/report.json", "value": value}
    ]
    assert document.payload("evaluation-data") == []
    assert html.index('id="report-data"') < html.index("globalThis.ReportData")
    assert "script-src 'self'" not in html


def test_render_preserves_existing_embedded_payload_text_and_hashes():
    payloads = {
        "report-data": (
            '\r\n  [{"name":"original/run.json", "value":'
            '{"text":"\\u003c/script\\u003e & \\u0026",'
            '"marker":"/*__EVALUATION_DATA__*/ []", "zero":0, "unknown":null}}]\n'
        ),
        "evaluation-data": (
            '\n[ {"name":"same/evaluation.json","value":{"id":"second", "value":1.00}},'
            '{"name":"same/evaluation.json",'
            '"value":{"id":"first", "sample":true}} ]\r\n'
        ),
    }
    document = ReportDocument()
    document.feed(_render_report(payloads["report-data"], payloads["evaluation-data"]))
    for element_id, original in payloads.items():
        actual = "".join(document.script_data[element_id])
        assert actual == original
        assert (
            hashlib.sha256(actual.encode()).digest()
            == hashlib.sha256(original.encode()).digest()
        )
        assert document.payload(element_id) == json.loads(original)


def test_bundle_embeds_exact_font_bytes_and_license_with_offline_csp():
    document = ReportDocument()
    document.feed(_render_report("[]", "[]"))
    css = "".join(document.styles)
    urls = re.findall(r"url\(\s*['\"]?([^'\")\s]+)", css)
    font_urls = [url for url in urls if url.startswith("data:font/woff2;base64,")]
    assert len(font_urls) == 1
    assets = Path(report_html.__file__).parent / "report_viewer/assets"
    assert (
        base64.b64decode(font_urls[0].split(",", 1)[1], validate=True)
        == (assets / "PretendardVariable.woff2").read_bytes()
    )
    assert all(url.startswith("data:") for url in urls)
    assert "@import" not in css
    assert not document.sources
    policies = dict(
        part.strip().split(maxsplit=1)
        for part in document.csp.split(";")
        if part.strip()
    )
    assert policies["font-src"] == "data:"
    assert policies["script-src"] == "'unsafe-inline'"
    assert policies["style-src"] == "'unsafe-inline'"
    assert policies["connect-src"] == "'none'"
    license_text = (assets / "Pretendard.LICENSE.txt").read_text(encoding="utf-8")
    assert "".join(document.license_data) == license_text


def test_license_text_cannot_escape_its_inert_template(tmp_path, monkeypatch):
    source_dir = Path(report_html.__file__).parent
    viewer = tmp_path / "report_viewer"
    assets = viewer / "assets"
    assets.mkdir(parents=True)
    (tmp_path / "report_viewer.html").write_text(
        (source_dir / "report_viewer.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (viewer / "styles.css").write_text(
        '@font-face {src: url("assets/PretendardVariable.woff2")}', encoding="utf-8"
    )
    for script in ("data", "components", "app"):
        (viewer / f"{script}.js").write_text("", encoding="utf-8")
    evaluation_viewer = tmp_path / "eval" / "viewers" / "report"
    evaluation_viewer.mkdir(parents=True)
    for script in ("evaluation-catalog", "evaluation", "evaluation-view"):
        (evaluation_viewer / f"{script}.js").write_text("", encoding="utf-8")
    (assets / "PretendardVariable.woff2").write_bytes(b"font fixture")
    license_text = '</template><script id="license-injection">& license text</script>\n'
    (assets / "Pretendard.LICENSE.txt").write_text(license_text, encoding="utf-8")
    monkeypatch.setattr(report_html, "__file__", str(tmp_path / "report_html.py"))
    document = ReportDocument()
    document.feed(_render_report("[]", "[]"))
    assert "license-injection" not in document.script_ids
    assert "".join(document.license_data) == license_text


def test_evaluation_inputs_are_embedded_separately_and_safely(tmp_path):
    report = tmp_path / "report.json"
    report_value = {"state": {"request": {"goal": "/*__EVALUATION_DATA__*/ []"}}}
    report.write_text(json.dumps(report_value), encoding="utf-8")
    evaluation = tmp_path / "evaluation.json"
    evaluation_value = {
        "type": "evaluation",
        "schema_version": 1,
        "id": "sample",
        "title": '</script><script id="injected-evaluation">&',
        "sample": True,
        "run_ids": [],
        "units": [],
    }
    evaluation.write_text(json.dumps(evaluation_value), encoding="utf-8-sig")
    output = tmp_path / "report.html"

    build_report([report], output, [evaluation, evaluation])

    html = output.read_text(encoding="utf-8")
    document = ReportDocument()
    document.feed(html)
    assert not document.sources
    assert "injected-evaluation" not in document.script_ids
    assert document.script_ids.count("evaluation-data") == 1
    assert document.payload("report-data") == [
        {"name": f"{tmp_path.name}/report.json", "value": report_value}
    ]
    assert document.payload("evaluation-data") == [
        {"name": f"{tmp_path.name}/evaluation.json", "value": evaluation_value}
    ]
    assert html.index('id="evaluation-data"') < html.index("globalThis.ReportData")


def test_directory_inputs_only_discover_reports(tmp_path):
    directory = tmp_path / "run"
    directory.mkdir()
    (directory / "report.json").write_text('{"state": {}}', encoding="utf-8")
    (directory / "evaluation.json").write_text(
        '{"type": "evaluation"}', encoding="utf-8"
    )
    output = tmp_path / "report.html"

    build_report([tmp_path], output)

    document = ReportDocument()
    document.feed(output.read_text(encoding="utf-8"))
    assert document.payload("report-data") == [
        {"name": "run/report.json", "value": {"state": {}}}
    ]
    assert document.payload("evaluation-data") == []


def test_no_report_inputs_still_require_a_report(tmp_path):
    with pytest.raises(ValueError, match="report.json"):
        build_report([tmp_path], tmp_path / "report.html")


def test_cli_accepts_multiple_evaluation_files(tmp_path):
    source = tmp_path / "report.json"
    source.write_text('{"state": {}}', encoding="utf-8")
    evaluations = [tmp_path / f"evaluation-{index}.json" for index in range(3)]
    for index, evaluation in enumerate(evaluations):
        evaluation.write_text(json.dumps({"id": str(index)}), encoding="utf-8")
    output = tmp_path / "report.html"
    builder = Path(__file__).resolve().parents[1] / "report_html.py"

    subprocess.run(
        [
            sys.executable,
            str(builder),
            str(source),
            "--output",
            str(output),
            "--evaluation",
            *map(str, evaluations[:2]),
            "--evaluation",
            str(evaluations[2]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    document = ReportDocument()
    document.feed(output.read_text(encoding="utf-8"))
    assert [item["value"] for item in document.payload("evaluation-data")] == [
        {"id": "0"},
        {"id": "1"},
        {"id": "2"},
    ]
    assert not document.sources
