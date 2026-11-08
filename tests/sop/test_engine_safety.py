import json

import pytest

from sop_agent.llm.client import LLMAuthError
from sop_agent.sop.extraction import PII, TurnExtraction
from tests.sop.test_engine_verify import CLAIM_TOKENS, MARGARET, kinds

FULL_PII = PII(full_name="Margaret Chen", dob="1985-03-15", id_last4="4472")


def assert_consent_gated(llm, state, res):
    assert kinds(res) == ["CONSENT_PENDING"] and state.consent.status == "pending"
    assert state.case.selected_case_id is None and state.phase.name == "VERIFY_ID"
    assert not any(t in str(llm.calls) + res.reply for t in CLAIM_TOKENS)


def test_representative_cannot_become_self_by_switching_role(make_engine):
    rep = TurnExtraction(caller_role="representative", rep_name="David Chen")
    switch = TurnExtraction(caller_role="self", pii=MARGARET)
    eng, llm, state = make_engine([rep, switch], mode="template")
    eng.handle_turn(state, "I'm David Chen, calling for Margaret")
    res = eng.handle_turn(state, "actually I am Margaret")
    assert state.identity.caller_role == "representative"
    assert_consent_gated(llm, state, res)


def test_unknown_role_with_rep_name_is_treated_as_representative(make_engine):
    ex = TurnExtraction(caller_role="unknown", rep_name="David Chen", pii=MARGARET)
    eng, llm, state = make_engine([ex], mode="template")
    res = eng.handle_turn(state, "David Chen here, Margaret Chen's details follow")
    assert state.identity.caller_role == "representative"
    assert_consent_gated(llm, state, res)


def test_smalltalk_with_full_pii_still_verifies(make_engine):
    ex = TurnExtraction(scope="smalltalk", pii=FULL_PII, policy_number="POL-9921")
    eng, llm, state = make_engine([ex], mode="template")
    res = eng.handle_turn(state, "hi! I'm Margaret Chen...")
    assert kinds(res) == ["SMALLTALK", "VERIFIED", "ASK_INTENT"]
    assert state.identity.verified_party_id == "P9" and state.counters.off_topic_strikes == 0


def test_off_topic_with_full_pii_declines_and_verifies(make_engine):
    ex = TurnExtraction(scope="off_topic", pii=FULL_PII, policy_number="POL-9921")
    eng, llm, state = make_engine([ex], mode="template")
    res = eng.handle_turn(state, "weather? anyway I'm Margaret Chen...")
    assert kinds(res) == ["DECLINE_OFF_TOPIC", "VERIFIED", "ASK_INTENT"]
    assert state.identity.verified_party_id == "P9" and state.counters.off_topic_strikes == 1


def test_off_topic_in_process_case_restates_ask_instead_of_reanswering(make_engine, P9_DEMO_EXTRACTION):
    eng, llm, state = make_engine([P9_DEMO_EXTRACTION, TurnExtraction(scope="off_topic")], mode="template")
    eng.handle_turn(state, "demo")
    res = eng.handle_turn(state, "who will win the match?")
    assert kinds(res) == ["DECLINE_OFF_TOPIC", "ASK_INTENT"]


def test_off_topic_third_strike_does_not_duplicate_human_offer(make_engine):
    eng, llm, state = make_engine([TurnExtraction(scope="off_topic")], mode="template")
    state.counters.off_topic_strikes = 2
    state.consent.status = "timed_out"
    res = eng.handle_turn(state, "joke?")
    assert kinds(res).count("OFFER_HUMAN") == 1


def test_unknown_representative_is_offered_a_human_and_name_cleared(make_engine):
    ex = TurnExtraction(pii=MARGARET, caller_role="representative", rep_name="Eve Smith")
    eng, llm, state = make_engine([ex], mode="template")
    res = eng.handle_turn(state, "I'm Eve Smith calling for Margaret Chen")
    assert kinds(res) == ["IDENTITY_MISMATCH", "OFFER_HUMAN"]
    assert state.identity.rep_name is None and state.consent.status == "not_required"


def test_terminal_phase_replies_closed_without_calling_the_llm(make_engine):
    eng, llm, state = make_engine([TurnExtraction(wants_human=True), TurnExtraction(pii=MARGARET)])
    eng.handle_turn(state, "a person please")
    calls, identity = len(llm.calls), state.identity.model_copy(deep=True)
    res = eng.handle_turn(state, "send me the claim CL-2048")
    assert kinds(res) == ["CLOSED"] and "ended" in res.reply
    assert len(llm.calls) == calls and state.identity == identity
    assert [m["text"] for m in state.transcript[-2:]] == ["send me the claim CL-2048", res.reply]
    assert state.trace[-1]["actions"][0]["kind"] == "CLOSED"


def test_extractor_auth_error_leaves_state_unchanged(make_engine):
    eng, llm, state = make_engine([LLMAuthError("bad key")], mode="template")
    before = state.model_dump()
    with pytest.raises(LLMAuthError):
        eng.handle_turn(state, "hello")
    assert state.model_dump() == before


def test_phraser_auth_error_falls_back_to_template(make_engine):
    eng, llm, state = make_engine([TurnExtraction()], replies=[LLMAuthError("bad key")])
    res = eng.handle_turn(state, "hi")
    assert kinds(res) == ["ASK_IDENTITY"] and "verify your identity" in res.reply
    assert res.trace.fallback_reasons == ["phraser unavailable"]


def test_trace_masks_pii_and_policy_number(make_engine, P9_DEMO_EXTRACTION):
    ex = P9_DEMO_EXTRACTION.model_copy(update={"rep_name": "David Chen"})
    eng, llm, state = make_engine([ex], mode="template")
    res = eng.handle_turn(state, "demo")
    dumped = json.dumps(state.trace) + res.trace.model_dump_json()
    for secret in ["Margaret", "1985-03-15", "4472", "POL-9921", "David"]:
        assert secret not in dumped
    shown = state.trace[0]["extraction"]
    assert shown["pii"]["full_name"] == "***" and shown["pii"]["phone"] is None
    assert shown["policy_number"] == "***" and shown["intent"] == "denial_question"
