from sop_agent.sop.extraction import Emotion, TurnExtraction
from sop_agent.sop.policies import disclosure_allowed, should_escalate
from sop_agent.sop.state import Phase, SessionState


def test_disclosure_needs_verification_and_consent():
    state = SessionState.new()
    assert not disclosure_allowed(state)
    state.identity.verified_party_id = "P9"
    assert disclosure_allowed(state)
    state.consent.status = "pending"
    assert not disclosure_allowed(state)
    state.consent.status = "approved"
    assert disclosure_allowed(state)


def test_escalates_on_second_refusal_in_same_phase_or_very_angry_caller():
    state = SessionState.new()
    calm = TurnExtraction()
    state.counters.refusals = {Phase.VERIFY_ID.value: 1}
    assert not should_escalate(state, calm)
    state.counters.refusals = {Phase.VERIFY_ID.value: 2}
    assert should_escalate(state, calm)
    state.counters.refusals = {Phase.RESOLVE_INTENT.value: 2}  # refusals elsewhere do not count here
    assert not should_escalate(state, calm)
    assert should_escalate(state, TurnExtraction(emotion=Emotion(label="angry", intensity=3)))
    assert not should_escalate(state, TurnExtraction(emotion=Emotion(label="angry", intensity=2)))
