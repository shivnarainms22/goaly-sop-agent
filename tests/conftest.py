from datetime import date

import pytest

from sop_agent.config import Settings
from sop_agent.data.repository import Repository
from sop_agent.llm.fake import FakeLLM
from sop_agent.sop.engine import SOPEngine
from sop_agent.sop.extraction import PII, CaseHints, TurnExtraction
from sop_agent.sop.state import SessionState


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
