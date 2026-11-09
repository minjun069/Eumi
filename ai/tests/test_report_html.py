"""분리된 소스를 묶은 파일이 오프라인에서 안전하게 열리는지 확인한다."""

import json
from html.parser import HTMLParser

from report_html import build_report


class ReportDocument(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script_ids = []
        self.sources = []
        self.script_data = []
        self.in_data = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.script_ids.append(attrs.get("id"))
            self.in_data = attrs.get("id") == "report-data"
            if "src" in attrs:
                self.sources.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.sources.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_data = False

    def handle_data(self, data):
        if self.in_data:
            self.script_data.append(data)


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
    assert json.loads("".join(document.script_data)) == [
        {"name": f"{tmp_path.name}/report.json", "value": value}
    ]
    assert html.index('id="report-data"') < html.index("globalThis.ReportData")
    assert "script-src 'self'" not in html
