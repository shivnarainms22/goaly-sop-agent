import json

from sop_agent.sop.extraction import PII, TurnExtraction, merge_into_state
from sop_agent.sop.state import Memory, Phase, SessionState


def test_new_session_starts_in_verify():
    s = SessionState.new(consent_scenario="default")
    assert s.phase is Phase.VERIFY_ID and s.identity.verified_party_id is None
    assert s.consent.scenario == "default" and s.consent.status == "not_required"


def test_memory_accepts_all_optional_keywords():
    m = Memory(
        intent="denial_question",
        case_type="auto",
        month=2,
        year=2026,
        status="open",
        case_id="CL-1",
        documents_mentioned=["x"],
        notes=["n"],
    )
    assert m.month == 2 and Memory().case_type is None


def test_snapshot_masks_pii_and_is_json_safe():
    s = SessionState.new()
    merge_into_state(s, TurnExtraction(pii=PII(email="margaret@email.com", id_last4="4472")))
    snap = s.snapshot()
    assert "margaret@email.com" not in str(snap) and "4472" not in str(snap)
    assert snap["identity"]["provided_fields"] == ["email", "id_last4"]
    assert snap["phase"] == "VERIFY_ID"
    json.dumps(snap)


def test_sessions_do_not_share_state():
    a, b = SessionState.new(), SessionState.new()
    a.identity.provided["dob"] = "1985-03-15"
    a.memory.documents_mentioned.append("x")
    assert b.identity.provided == {} and b.memory.documents_mentioned == []
