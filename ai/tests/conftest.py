"""시각화 입력 규격 검사는 이벤트 배정과 분리한 테스트 명세를 사용한다."""

import json
from pathlib import Path

import pytest

from src import visualization_instructions
from src.tools import tableau, tableau_catalog


@pytest.fixture
def all_tableau_views(monkeypatch):
    catalog = json.loads(
        Path(tableau_catalog.__file__)
        .with_name("tableau_catalog.json")
        .read_text(encoding="utf-8")
    )
    catalog["event_views"] = {
        event: list(catalog["views"]) for event in ("analysis_pipeline", "user_request")
    }
    catalog = tableau_catalog.validate_catalog(catalog)
    for module in (tableau_catalog, tableau, visualization_instructions):
        monkeypatch.setattr(module, "registered_catalog", lambda: catalog)
    return catalog
