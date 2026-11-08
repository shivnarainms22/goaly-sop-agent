import re

from fastapi.testclient import TestClient

from sop_agent.api.app import INDEX, create_app
from sop_agent.config import Settings


def test_index_serves_inspector_ui():
    client = TestClient(create_app(Settings(ANTHROPIC_API_KEY=None)))
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    for needle in (
        'id="chat"',
        'id="inspector"',
        "X-Anthropic-Key",
        "sessionStorage",
        "prefers-color-scheme",
    ):
        assert needle in r.text


def test_ui_never_uses_innerhtml_and_loads_no_external_scripts():
    html = INDEX.read_text(encoding="utf-8")
    assert "innerHTML" not in html
    assert not re.search(r"<script[^>]+src=", html)
