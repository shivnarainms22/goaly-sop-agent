from datetime import date

from sop_agent.config import Settings


def test_defaults():
    s = Settings()
    assert s.extractor_model == "claude-haiku-5-5"
    assert s.responder_model == "claude-sonnet-5-5"
    assert s.fixtures_dir.joinpath("claims.json").exists()


def test_today_override(monkeypatch):
    monkeypatch.setenv("SOP_TODAY", "2026-02-01")
    assert Settings().today() == date(2026, 2, 1)
