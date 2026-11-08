import pytest
from pydantic import ValidationError

from sop_agent.sop.extraction import PII, CaseHints, TurnExtraction, merge_into_state
from sop_agent.sop.state import Phase, SessionState


def test_hints_remembered_during_verify():
    s = SessionState.new()
    ex = TurnExtraction(
        pii=PII(full_name="Margaret Chen", dob="1985-03-15", id_last4="4472"),
        policy_number="POL-9921",
        caller_role="self",
        intent="denial_question",
        case_hints=CaseHints(case_type="healthcare", month=1, status="denied"),
    )
    merge_into_state(s, ex)
    assert s.phase is Phase.VERIFY_ID  # merging never changes phase
    assert s.memory.intent == "denial_question"
    assert (s.memory.case_type, s.memory.month, s.memory.status) == ("healthcare", 1, "denied")
    assert s.identity.provided["dob"] == "1985-03-15"  # normalized
    assert s.identity.policy_number == "POL-9921"


def test_later_value_overrides_and_empty_does_not_erase():
    s = SessionState.new()
    merge_into_state(s, TurnExtraction(pii=PII(dob="03/15/1984")))
    merge_into_state(s, TurnExtraction(pii=PII(dob="1985-03-15")))
    merge_into_state(s, TurnExtraction())
    assert s.identity.provided["dob"] == "1985-03-15"


def test_invalid_pii_value_ignored():
    s = SessionState.new()
    merge_into_state(s, TurnExtraction(pii=PII(phone="12")))
    assert "phone" not in s.identity.provided


def test_empty_extraction_defaults_and_no_hint_erasure():
    ex = TurnExtraction()
    assert (ex.intent, ex.scope, ex.email_decision, ex.caller_role) == ("none", "in_scope", "none", "unknown")
    assert ex.emotion.label == "neutral" and ex.refusal is False
    s = SessionState.new()
    merge_into_state(s, TurnExtraction(intent="status_inquiry", case_hints=CaseHints(year=2026)))
    merge_into_state(s, TurnExtraction())
    assert (s.memory.intent, s.memory.year) == ("status_inquiry", 2026)


def test_documents_deduplicated_and_representative_stored():
    s = SessionState.new()
    merge_into_state(s, TurnExtraction(documents_mentioned=["pathology report"]))
    merge_into_state(
        s,
        TurnExtraction(
            documents_mentioned=["pathology report", "office note"],
            caller_role="representative",
            rep_name="David Chen",
            relationship="son",
        ),
    )
    assert s.memory.documents_mentioned == ["pathology report", "office note"]
    assert (s.identity.caller_role, s.identity.rep_name, s.identity.relationship) == (
        "representative",
        "David Chen",
        "son",
    )


def test_invalid_enum_rejected():
    with pytest.raises(ValidationError):
        TurnExtraction(intent="make_me_rich")


def test_intent_other_does_not_overwrite_remembered_intent():
    s = SessionState.new()
    merge_into_state(s, TurnExtraction(intent="other"))
    assert s.memory.intent == "other"
    merge_into_state(s, TurnExtraction(intent="denial_question"))
    merge_into_state(s, TurnExtraction(intent="other"))
    assert s.memory.intent == "denial_question"
