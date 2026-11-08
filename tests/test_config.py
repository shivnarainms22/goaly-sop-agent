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


def test_reads_dotenv_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-test-from-file\nSOP_RESPONDER_MODE=template\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.anthropic_api_key == "sk-test-from-file" and s.responder_mode == "template"


def test_default_env_file_is_repo_dotenv():
    from sop_agent.config import REPO_ROOT

    assert Settings.model_config["env_file"] == REPO_ROOT / ".env"


def test_blank_values_in_dotenv_are_ignored(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=\nSOP_TODAY=\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.anthropic_api_key is None and s.today_override is None
