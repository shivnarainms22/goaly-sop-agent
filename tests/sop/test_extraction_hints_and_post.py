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


def test_skip_with_hints_for_the_same_case_still_skips(make_engine, P9_DEMO_EXTRACTION):
    done = TurnExtraction(done_with_case=True)
    skip = TurnExtraction(
        email_decision="skip", case_hints=CaseHints(case_type="healthcare", status="denied")
    )
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION, done, skip], mode="template")
    eng.handle_turn(state, "demo")
    eng.handle_turn(state, "that's all")
    res = eng.handle_turn(state, "no thanks, skip the email")
    assert kinds(res) == ["EMAIL_SKIPPED"] and state.phase.name == "ENDED" and state.email.outbox == []


def test_appeal_question_always_states_the_deadline_even_if_already_said(make_engine, P9_DEMO_EXTRACTION):
    appeal = TurnExtraction(intent="appeal_question")
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION, appeal], mode="template")
    first = eng.handle_turn(state, "demo").reply
    assert "2026-03-18" in first  # said once already
    reply = eng.handle_turn(state, "Can I still appeal? When is the deadline?").reply
    assert "2026-03-18" in reply and "has passed" in reply and "human representative" in reply


def test_claim_question_at_email_offer_goes_back_to_the_case(make_engine, P9_DEMO_EXTRACTION):
    done = TurnExtraction(done_with_case=True)
    appeal = TurnExtraction(intent="appeal_question")
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION, done, appeal], mode="template")
    eng.handle_turn(state, "demo")
    eng.handle_turn(state, "that's all")
    res = eng.handle_turn(state, "wait, when was the appeal deadline?")
    assert state.phase.name == "PROCESS_CASE" and "ANSWER_CASE" in kinds(res) and "2026-03-18" in res.reply
