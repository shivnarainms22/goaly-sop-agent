from datetime import date

import pytest

from sop_agent.config import Settings
from sop_agent.data.repository import Repository
from sop_agent.llm.fake import FakeLLM
from sop_agent.sop.engine import SOPEngine
from sop_agent.sop.extraction import PII, CaseHints, TurnExtraction
from sop_agent.sop.state import SessionState


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch, request):
    """Tests must not depend on a developer's local .env (keys, model or mode overrides)."""
    if request.node.name != "test_default_env_file_is_repo_dotenv":
        monkeypatch.setitem(Settings.model_config, "env_file", None)
    for var in (
        "ANTHROPIC_API_KEY",
        "SOP_RESPONDER_MODE",
        "SOP_EXTRACTOR_MODEL",
        "SOP_RESPONDER_MODEL",
        "SOP_TODAY",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def make_engine():
    def factory(extractions, replies=(), scenario="default", today=date(2026, 11, 7), mode="llm"):
        settings = Settings(SOP_TODAY=today, responder_mode=mode)
        llm = FakeLLM(extractions, replies)
        engine = SOPEngine(Repository.load(settings.fixtures_dir), llm, settings)
        return engine, llm, SessionState.new(consent_scenario=scenario)

    return factory


@pytest.fixture
def P9_DEMO_EXTRACTION():
    return TurnExtraction(
        pii=PII(full_name="Margaret Chen", dob="1985-03-15", id_last4="4472"),
        policy_number="POL-9921",
        caller_role="self",
        intent="denial_question",
        case_hints=CaseHints(case_type="healthcare", month=1, status="denied"),
    )
