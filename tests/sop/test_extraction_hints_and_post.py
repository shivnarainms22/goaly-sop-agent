import pytest
from pydantic import ValidationError

from sop_agent.sop.extraction import CaseHints, TurnExtraction
from tests.sop.test_engine_verify import kinds


def test_case_type_and_status_are_constrained_to_fixture_values():
    schema = TurnExtraction.model_json_schema()["$defs"]["CaseHints"]["properties"]
    assert set(schema["case_type"]["anyOf"][0]["enum"]) == {"healthcare", "dental", "auto"}
    assert set(schema["status"]["anyOf"][0]["enum"]) == {"denied", "closed", "open"}
    with pytest.raises(ValidationError):
        CaseHints(case_type="car")


def test_new_claim_question_wins_over_email_decision(make_engine, P9_DEMO_EXTRACTION):
    done = TurnExtraction(done_with_case=True)
    switch = TurnExtraction(
        email_decision="skip", intent="status_inquiry", case_hints=CaseHints(case_type="auto")
    )
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION, done, switch], mode="template")
    eng.handle_turn(state, "demo")
    eng.handle_turn(state, "that's all")
    res = eng.handle_turn(state, "Actually, what's happening with my auto claim?")
    assert state.case.selected_case_id == "CL-2102" and state.phase.name == "PROCESS_CASE"
    assert "EMAIL_SKIPPED" not in kinds(res) and state.email.outbox == []
